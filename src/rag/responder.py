"""
responder(entrada) → Salida + fuentes, usando solo lo que el usuario tiene permitido ver.

    Entrada ─► usuario del directorio (rol) ─► buscar(mensaje, usuario, k) con filtro de rol en la base
            ─► fragmentos permitidos en el prompt ─► Motor (PE2: valida, reintenta, mide)
            ─► citas válidas = fuentes ─► requiere_humano si no hay evidencia

requiere_humano = true cuando el asistente no puede resolver solo y una persona de RRHH tiene que
contestar ahora: consulta sin citas (no hay evidencia en los documentos permitidos), confianza baja
(revisión manual) o error del motor. Lo decide el código, no el modelo.

Uso:
    python -m src.rag.responder --usuario EMP-1091 --mensaje "¿Qué es el concepto 1035 de mi recibo?"
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from datetime import datetime
from typing import Literal, Optional, Union

from pydantic import BaseModel, ValidationError

from ..contrato import (Aprobador, Canal, Categoria, Entrada, ErrorMotor, EstadoNovedad, Metricas,
                        Salida, TipoError)
from ..motor import Motor, configurar_logs, describir_errores
from ..proveedores import ErrorProveedor
from .busqueda import Buscador, FragmentoRecuperado, buscador_por_defecto
from .permisos import PermisoDenegado, Rol, Usuario, obtener_usuario

log = logging.getLogger("rag.responder")

K_POR_DEFECTO = 5          # k del sistema: con ~300 caracteres por fragmento son ~400 tokens


class Fuente(BaseModel):
    documento: str
    titulo: str
    seccion: str
    fragmento_id: str
    puntaje: float


class RespuestaRAG(BaseModel):
    ok: Literal[True] = True
    id_consulta: str
    usuario_id: str
    rol: Rol
    salida: Salida
    estado: EstadoNovedad
    aprobador_requerido: Optional[Aprobador] = None
    requiere_humano: bool
    motivo_humano: Optional[str] = None
    fuentes: list[Fuente]
    fragmentos_enviados: list[str]      # ids que llegaron al prompt (todos permitidos para el rol)
    metricas: Metricas


def formatear_contexto(fragmentos: list[FragmentoRecuperado]) -> str:
    return "\n\n".join(f"[{f.fragmento_id}] {f.titulo_documento} · {f.seccion}\n{f.texto}" for f in fragmentos)


def responder(entrada: Entrada, usuario: Optional[Usuario] = None, *, buscador: Optional[Buscador] = None,
              motor: Optional[Motor] = None, k: int = K_POR_DEFECTO) -> Union[RespuestaRAG, ErrorMotor]:
    qid = f"Q-{uuid.uuid4().hex[:8]}"
    motor = motor or Motor()
    if usuario is None:
        try:
            usuario = obtener_usuario(entrada.supervisor_id)       # el rol sale del directorio
        except PermisoDenegado as e:
            log.error("[%s] %s", qid, e)
            return ErrorMotor(id_consulta=qid, tipo_error=TipoError.PERMISOS, mensaje=str(e),
                              metricas=Metricas(proveedor=motor.proveedor.nombre, modelo=motor.proveedor.modelo))

    buscador = buscador or buscador_por_defecto()
    fragmentos = buscador.buscar(entrada.mensaje, usuario, k)
    ids = [f.fragmento_id for f in fragmentos]
    log.info("[%s] %s (%s): %d fragmentos permitidos → %s", qid, usuario.id, usuario.rol.value, len(ids), ids)

    r = motor.procesar(entrada, documentos=formatear_contexto(fragmentos) if fragmentos else None,
                       ids_validos=set(ids), rol=usuario.rol.value, qid=qid)
    r.metricas.latencia_busqueda_ms = buscador.ultima_latencia_ms
    if not r.ok:
        return r

    s = r.salida
    por_id = {f.fragmento_id: f for f in fragmentos}
    fuentes = [Fuente(documento=por_id[c].documento, titulo=por_id[c].titulo_documento,
                      seccion=por_id[c].seccion, fragmento_id=c, puntaje=por_id[c].puntaje) for c in s.citas]
    motivo = None
    if s.categoria == Categoria.CONSULTA and not s.citas:
        motivo = ("sin_fragmentos_permitidos" if not fragmentos else "sin_evidencia_en_documentos")
    elif r.estado == EstadoNovedad.REVISION_MANUAL:
        motivo = "confianza_baja"
    if motivo:
        log.info("[%s] requiere_humano=true (%s)", qid, motivo)
    return RespuestaRAG(id_consulta=qid, usuario_id=usuario.id, rol=usuario.rol, salida=s, estado=r.estado,
                        aprobador_requerido=r.aprobador_requerido, requiere_humano=motivo is not None,
                        motivo_humano=motivo, fuentes=fuentes, fragmentos_enviados=ids, metricas=r.metricas)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Responde una consulta con los documentos permitidos")
    p.add_argument("--mensaje", required=True)
    p.add_argument("--usuario", default="SUP-003", help="id del directorio (SUP-003, ANA-001, JEF-001, EMP-1091)")
    p.add_argument("--canal", default="chat_web", choices=[c.value for c in Canal])
    p.add_argument("--k", type=int, default=K_POR_DEFECTO)
    a = p.parse_args(argv)
    configurar_logs()
    try:
        usuario = obtener_usuario(a.usuario)
        entrada = Entrada(supervisor_id=usuario.id, sector=usuario.sector, canal=a.canal, mensaje=a.mensaje,
                          recibida_en=datetime.now().replace(second=0, microsecond=0))
        motor = Motor()
    except PermisoDenegado as e:
        print(json.dumps({"ok": False, "tipo_error": "permisos", "mensaje": str(e)}, ensure_ascii=False, indent=2))
        return 1
    except ValidationError as exc:
        log.error("Entrada inválida: %s", "; ".join(f"{c.campo}: {c.error}" for c in describir_errores(exc)))
        return 2
    except ErrorProveedor as e:
        print(json.dumps({"ok": False, "tipo_error": e.tipo.value, "mensaje": e.mensaje}, ensure_ascii=False, indent=2))
        return 1
    r = responder(entrada, usuario, motor=motor, k=a.k)
    print(r.model_dump_json(indent=2))
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
