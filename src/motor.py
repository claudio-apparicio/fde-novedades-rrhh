"""
Motor LLM base del Asistente de novedades de personal (PE2).

Recibe una Entrada, arma el prompt desde las plantillas de src/prompts/, llama al modelo,
valida la respuesta contra Salida, aplica las reglas de negocio y devuelve un ResultadoMotor
o un ErrorMotor, siempre con tokens, costo en USD y latencia en ms.

Uso:
    python -m src.motor --mensaje "El 1091 hizo 10 hs extras al 100% el sábado"
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Optional, Union

from pydantic import ValidationError

from .contrato import (CampoFallido, Canal, Entrada, ErrorDeCampo, ErrorMotor, Metricas,
                       ResultadoMotor, Salida, Sector, TipoError)
from .precios import PRECIOS_USD_POR_MTOK, calcular_costo
from .proveedores import ErrorProveedor, Proveedor, crear_proveedor_desde_entorno
from .reglas import decidir_estado

log = logging.getLogger("motor")

DIR_PROMPTS = Path(__file__).parent / "prompts"
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
ESPERA_REINTENTO_API_S = 2.0


def cargar_plantilla(nombre: str) -> Template:
    return Template((DIR_PROMPTS / nombre).read_text(encoding="utf-8"))


SISTEMA = (DIR_PROMPTS / "sistema.txt").read_text(encoding="utf-8")
PLANTILLA_USUARIO = cargar_plantilla("usuario.txt")
PLANTILLA_CORRECCION = cargar_plantilla("correccion.txt")


def extraer_json(texto: str) -> dict:
    """Acepta el JSON solo o envuelto en ```json ... ```; cualquier otra cosa es un error."""
    limpio = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())
    inicio, fin = limpio.find("{"), limpio.rfind("}")
    if inicio == -1 or fin == -1:
        raise ValueError("la respuesta no contiene un objeto JSON")
    return json.loads(limpio[inicio:fin + 1])


def _mensaje_es(err: dict) -> str:
    """Mensajes de Pydantic en castellano para los errores más comunes."""
    ctx = err.get("ctx") or {}
    plantillas = {
        "string_pattern_mismatch": "no cumple el patrón {pattern}",
        "enum": "valor no permitido; opciones: {expected}",
        "literal_error": "valor no permitido; opciones: {expected}",
        "less_than_equal": "debe ser ≤ {le}",
        "greater_than_equal": "debe ser ≥ {ge}",
        "greater_than": "debe ser > {gt}",
        "string_too_short": "largo mínimo {min_length} caracteres",
        "string_too_long": "largo máximo {max_length} caracteres",
        "missing": "campo obligatorio ausente",
        "extra_forbidden": "campo no previsto en el contrato",
        "date_from_datetime_parsing": "fecha inválida (formato AAAA-MM-DD)",
        "date_parsing": "fecha inválida (formato AAAA-MM-DD)",
        "decimal_parsing": "debe ser un número",
        "float_parsing": "debe ser un número",
        "bool_parsing": "debe ser true o false",
    }
    try:
        return plantillas[err["type"]].format(**ctx)
    except (KeyError, IndexError):
        return err["msg"]


def describir_errores(exc: Exception) -> list[CampoFallido]:
    """Convierte un error de validación en la lista de campos que fallaron."""
    if isinstance(exc, ValidationError):
        campos = []
        for err in exc.errors():
            origen = (err.get("ctx") or {}).get("error")
            if isinstance(origen, ErrorDeCampo):
                campo, mensaje = origen.campo, str(origen)
            else:
                campo = ".".join(str(p) for p in err["loc"]) or "(objeto)"
                mensaje = _mensaje_es(err)
            valor = err.get("input")
            valor = None if isinstance(valor, dict) else (None if valor is None else str(valor)[:80])
            campos.append(CampoFallido(campo=campo, error=mensaje, valor=valor))
        return campos
    return [CampoFallido(campo="(json)", error=str(exc))]


class Motor:
    def __init__(self, proveedor: Optional[Proveedor] = None):
        self.proveedor = proveedor or crear_proveedor_desde_entorno()
        if self.proveedor.modelo not in PRECIOS_USD_POR_MTOK:
            raise ErrorProveedor(TipoError.CONFIGURACION,
                                 f"No hay precio cargado para el modelo '{self.proveedor.modelo}': "
                                 "agregalo en src/precios.py con su precio publicado")

    # -- llamada con un reintento ante errores transitorios de la API ---------------
    def _llamar(self, mensajes: list[dict], m: Metricas, qid: str):
        for intento_api in (1, 2):
            m.intentos += 1
            t0 = time.perf_counter()
            try:
                r = self.proveedor.generar(SISTEMA, mensajes)
            except ErrorProveedor as e:
                m.latencia_ms += round((time.perf_counter() - t0) * 1000)
                log.error("[%s] error de API (%s): %s", qid, e.tipo.value, e.mensaje[:200])
                if e.reintentable and intento_api == 1:
                    log.info("[%s] reintento de API en %.0f s", qid, ESPERA_REINTENTO_API_S)
                    time.sleep(ESPERA_REINTENTO_API_S)
                    continue
                raise
            ms = round((time.perf_counter() - t0) * 1000)
            m.latencia_ms += ms
            m.tokens_entrada += r.tokens_entrada
            m.tokens_salida += r.tokens_salida
            m.costo_usd = calcular_costo(m.modelo, m.tokens_entrada, m.tokens_salida)
            log.info("[%s] llamada %d · %s/%s · %d + %d tokens · %d ms", qid, m.intentos,
                     self.proveedor.nombre, m.modelo, r.tokens_entrada, r.tokens_salida, ms)
            return r

    def procesar(self, entrada: Entrada) -> Union[ResultadoMotor, ErrorMotor]:
        qid = f"Q-{uuid.uuid4().hex[:8]}"
        m = Metricas(proveedor=self.proveedor.nombre, modelo=self.proveedor.modelo)
        mensajes = [{"role": "user", "content": PLANTILLA_USUARIO.substitute(
            recibida_en=entrada.recibida_en.strftime("%Y-%m-%d %H:%M"),
            dia_semana=DIAS[entrada.recibida_en.weekday()],
            supervisor_id=entrada.supervisor_id, sector=entrada.sector.value,
            canal=entrada.canal.value, mensaje=entrada.mensaje)}]
        log.info("[%s] consulta de %s (%s, %s): %s", qid, entrada.supervisor_id, entrada.sector.value,
                 entrada.canal.value, entrada.mensaje[:70])

        for intento in (1, 2):  # 1 intento + 1 reintento si la salida es inválida
            try:
                r = self._llamar(mensajes, m, qid)
            except ErrorProveedor as e:
                return ErrorMotor(id_consulta=qid, tipo_error=e.tipo, mensaje=e.mensaje, metricas=m)
            try:
                salida = Salida.model_validate(extraer_json(r.texto),
                                               context={"recibida_en": entrada.recibida_en})
            except (ValidationError, ValueError) as exc:
                campos = describir_errores(exc)
                for c in campos:
                    error = c.error if len(c.error) <= 90 else c.error[:87] + "..."
                    log.warning("[%s] validación falló en '%s': %s%s", qid, c.campo, error,
                                f" (valor: {c.valor!r})" if c.valor is not None else "")
                if intento == 1:
                    log.info("[%s] reintento 1/1: se reenvían los errores al modelo", qid)
                    errores = "\n".join(f"- {c.campo}: {c.error}" for c in campos)
                    mensajes += [{"role": "assistant", "content": r.texto},
                                 {"role": "user", "content": PLANTILLA_CORRECCION.substitute(errores=errores)}]
                    continue
                log.error("[%s] la salida sigue inválida después del reintento: se devuelve error "
                          "estructurado", qid)
                return ErrorMotor(id_consulta=qid, tipo_error=TipoError.VALIDACION,
                                  mensaje="La respuesta del modelo no cumple el contrato Salida "
                                          "después de 1 reintento. La novedad pasa a revisión manual.",
                                  campos_fallidos=campos, respuesta_cruda=r.texto[:600], metricas=m)

            estado, aprobador = decidir_estado(salida)
            log.info("[%s] OK · categoria=%s · estado=%s · %d tokens · US$ %.6f · %d ms", qid,
                     salida.categoria.value, estado.value, m.tokens_entrada + m.tokens_salida,
                     m.costo_usd, m.latencia_ms)
            return ResultadoMotor(id_consulta=qid, salida=salida, estado=estado,
                                  aprobador_requerido=aprobador, metricas=m)


def configurar_logs(nivel: int = logging.INFO) -> None:
    logging.basicConfig(level=nivel, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stderr)
    for ruidoso in ("httpx", "anthropic", "openai"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Motor LLM de novedades de personal")
    p.add_argument("--mensaje", required=True, help="texto que manda el supervisor")
    p.add_argument("--supervisor", default="SUP-003")
    p.add_argument("--sector", default="montaje", choices=[s.value for s in Sector])
    p.add_argument("--canal", default="whatsapp", choices=[c.value for c in Canal])
    p.add_argument("--recibida", default=None, help="AAAA-MM-DDTHH:MM (por defecto, ahora)")
    a = p.parse_args(argv)
    configurar_logs()

    try:
        entrada = Entrada(supervisor_id=a.supervisor, sector=a.sector, canal=a.canal, mensaje=a.mensaje,
                          recibida_en=a.recibida or datetime.now().replace(second=0, microsecond=0))
    except ValidationError as exc:
        log.error("Entrada inválida: %s", "; ".join(f"{c.campo}: {c.error}" for c in describir_errores(exc)))
        return 2
    try:
        motor = Motor()
    except ErrorProveedor as e:
        print(json.dumps({"ok": False, "tipo_error": e.tipo.value, "mensaje": e.mensaje},
                         ensure_ascii=False, indent=2))
        return 1

    resultado = motor.procesar(entrada)
    print(resultado.model_dump_json(indent=2))
    return 0 if resultado.ok else 1


if __name__ == "__main__":
    sys.exit(main())
