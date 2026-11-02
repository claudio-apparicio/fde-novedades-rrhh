"""
Abstracción del proveedor de LLM: el motor no sabe si habla con Anthropic, OpenAI o el simulado.
Para cambiar de proveedor alcanza con la variable PROVEEDOR_LLM (o pasar otra instancia al Motor).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from .contrato import TipoError


@dataclass
class RespuestaLLM:
    texto: str
    tokens_entrada: int
    tokens_salida: int          # incluye los de razonamiento, que se cobran como salida
    tokens_razonamiento: int = 0


class ErrorProveedor(Exception):
    """Error de la API traducido a un tipo propio. `reintentable` indica si vale la pena reintentar."""

    def __init__(self, tipo: TipoError, mensaje: str, reintentable: bool = False):
        super().__init__(mensaje)
        self.tipo = tipo
        self.mensaje = mensaje
        self.reintentable = reintentable


def _detalle(exc: Exception) -> str:
    """Texto del error. xAI manda el motivo como texto plano y el SDK de OpenAI no lo incluye en str(exc)."""
    texto = str(exc)
    cuerpo = getattr(exc, "body", None)
    if isinstance(cuerpo, str) and cuerpo not in texto:
        texto += f" - {cuerpo}"
    return texto


def _traducir_error(sdk, exc: Exception) -> ErrorProveedor:
    """Mapea las excepciones de los SDK (Anthropic y OpenAI usan los mismos nombres)."""
    d = _detalle(exc)
    if isinstance(exc, sdk.AuthenticationError) or isinstance(exc, sdk.PermissionDeniedError):
        return ErrorProveedor(TipoError.AUTENTICACION, f"Clave de API inválida o sin permisos: {d}")
    if isinstance(exc, sdk.RateLimitError):
        return ErrorProveedor(TipoError.LIMITE_DE_USO, f"Límite de uso alcanzado (429): {d}", True)
    if isinstance(exc, sdk.APITimeoutError):
        return ErrorProveedor(TipoError.TIEMPO_AGOTADO, f"La API no respondió a tiempo: {d}", True)
    if isinstance(exc, sdk.APIConnectionError):
        return ErrorProveedor(TipoError.SIN_CONEXION, f"No se pudo conectar con la API: {d}", True)
    if isinstance(exc, sdk.InternalServerError):
        return ErrorProveedor(TipoError.API, f"Error del servidor del proveedor: {d}", True)
    if isinstance(exc, sdk.APIStatusError) and exc.status_code == 400 and "api key" in d.lower():
        # xAI responde 400 (no 401) cuando la clave es incorrecta
        return ErrorProveedor(TipoError.AUTENTICACION, f"Clave de API inválida: {d}")
    if isinstance(exc, sdk.APIStatusError):
        return ErrorProveedor(TipoError.API, f"La API rechazó el pedido ({exc.status_code}): {d}")
    return ErrorProveedor(TipoError.API, f"Error inesperado: {exc!r}")


class Proveedor:
    nombre = "base"

    def __init__(self, modelo: str):
        self.modelo = modelo

    def generar(self, sistema: str, mensajes: list[dict]) -> RespuestaLLM:  # pragma: no cover
        raise NotImplementedError


class ProveedorAnthropic(Proveedor):
    nombre = "anthropic"

    def __init__(self, modelo: str, api_key: str, timeout_s: float, max_tokens: int):
        super().__init__(modelo)
        import anthropic
        self._sdk = anthropic
        # max_retries=0: los reintentos los maneja el motor y quedan registrados
        self._cliente = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=0)
        self._max_tokens = max_tokens

    def generar(self, sistema: str, mensajes: list[dict]) -> RespuestaLLM:
        try:
            r = self._cliente.messages.create(model=self.modelo, max_tokens=self._max_tokens,
                                              system=sistema, messages=mensajes)
        except self._sdk.APIError as exc:
            raise _traducir_error(self._sdk, exc) from exc
        texto = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return RespuestaLLM(texto, r.usage.input_tokens, r.usage.output_tokens)


class ProveedorOpenAI(Proveedor):
    nombre = "openai"

    def __init__(self, modelo: str, api_key: str, timeout_s: float, max_tokens: int,
                 reasoning_effort: Optional[str], base_url: Optional[str] = None, nombre: str = "openai",
                 modo_json: bool = True):
        super().__init__(modelo)
        import openai
        self._sdk = openai
        self.nombre = nombre
        self._cliente = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=0)
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort
        self._modo_json = modo_json

    def generar(self, sistema: str, mensajes: list[dict]) -> RespuestaLLM:
        extra = {"reasoning_effort": self._reasoning_effort} if self._reasoning_effort else {}
        if self._modo_json:
            extra["response_format"] = {"type": "json_object"}
        try:
            r = self._cliente.chat.completions.create(
                model=self.modelo, max_completion_tokens=self._max_tokens,
                messages=[{"role": "system", "content": sistema}, *mensajes], **extra)
        except self._sdk.APIError as exc:
            raise _traducir_error(self._sdk, exc) from exc
        u = r.usage
        salida = u.completion_tokens or 0
        detalle = getattr(u, "completion_tokens_details", None)
        razonamiento = (getattr(detalle, "reasoning_tokens", 0) or 0) if detalle else 0
        # OpenAI incluye el razonamiento dentro de completion_tokens. Otros proveedores compatibles
        # (como xAI) lo informan aparte: se nota porque el total supera entrada + salida o porque
        # el razonamiento es mayor que la salida. En ese caso se suma, porque también se cobra.
        if razonamiento and ((u.total_tokens or 0) >= u.prompt_tokens + salida + razonamiento
                             or razonamiento > salida):
            salida += razonamiento
        return RespuestaLLM(r.choices[0].message.content or "", u.prompt_tokens, salida, razonamiento)


class ProveedorSimulado(Proveedor):
    """Funciona sin clave. Sirve para probar el motor y para forzar errores en las pruebas.

    - respuestas: textos a devolver en orden (si no se pasa, devuelve una respuesta fija válida).
    - error: si se pasa un TipoError, cada llamada falla con ese error.
    Los tokens se ESTIMAN (4 caracteres ≈ 1 token) y el costo es 0.
    """
    nombre = "simulado"

    RESPUESTA_FIJA = {
        "categoria": "novedad", "tipo": None, "legajo": None, "fecha_desde": None,
        "fecha_hasta": None, "cantidad": None, "unidad": None, "tiene_adjunto": False,
        "campos_faltantes": ["legajo", "tipo", "fecha_desde", "cantidad", "unidad"],
        "respuesta_supervisor": "[SIMULADO] Recibí tu mensaje. Para cargarlo necesito el legajo, "
                                "el tipo de novedad, la fecha y la cantidad.",
        "confianza": 0.2,
    }

    def __init__(self, respuestas: Optional[list[str]] = None, error: Optional[TipoError] = None):
        super().__init__("simulado")
        self._respuestas = list(respuestas or [])
        self._error = error
        self.llamadas = 0

    def generar(self, sistema: str, mensajes: list[dict]) -> RespuestaLLM:
        self.llamadas += 1
        if self._error:
            raise ErrorProveedor(self._error, f"[SIMULADO] error de API: {self._error.value}",
                                 reintentable=self._error in (TipoError.LIMITE_DE_USO, TipoError.SIN_CONEXION,
                                                              TipoError.TIEMPO_AGOTADO))
        texto = self._respuestas.pop(0) if self._respuestas else json.dumps(self.RESPUESTA_FIJA,
                                                                            ensure_ascii=False)
        prompt = sistema + "".join(m["content"] for m in mensajes)
        return RespuestaLLM(texto, len(prompt) // 4, len(texto) // 4)


# Respuesta inválida para la demo de errores (SIMULAR=respuesta_invalida): un tipo que no existe
# en el Enum, un nombre en lugar de legajo y una confianza fuera de rango, dos veces seguidas.
_INVALIDA = json.dumps({**ProveedorSimulado.RESPUESTA_FIJA, "tipo": "hs_extras", "legajo": "Juan",
                        "cantidad": 4, "unidad": "HS", "fecha_desde": "2026-09-12",
                        "campos_faltantes": [], "confianza": 1.5}, ensure_ascii=False)

MODELOS_POR_DEFECTO = {"anthropic": "claude-haiku-5-5", "openai": "gpt-5-mini", "xai": "grok-4.3",
                       "simulado": "simulado"}
URL_XAI = "https://api.x.ai/v1"  # la API de xAI (Grok) es compatible con el SDK de OpenAI


def crear_proveedor_desde_entorno() -> Proveedor:
    """Lee la configuración de las variables de entorno (o del archivo .env)."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:  # pragma: no cover
        pass

    nombre = os.getenv("PROVEEDOR_LLM", "anthropic").strip().lower() or "anthropic"
    modelo = os.getenv("MODELO_LLM", "").strip() or MODELOS_POR_DEFECTO.get(nombre, "")
    timeout_s = float(os.getenv("LLM_TIMEOUT_S", "") or 30)

    if nombre == "simulado":
        simular = os.getenv("SIMULAR", "").strip()
        if simular == "respuesta_invalida":
            return ProveedorSimulado(respuestas=[_INVALIDA, _INVALIDA])
        if simular:
            return ProveedorSimulado(error=TipoError(simular))
        return ProveedorSimulado()

    if nombre == "anthropic":
        clave = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not clave:
            raise ErrorProveedor(TipoError.CONFIGURACION, "Falta ANTHROPIC_API_KEY en el archivo .env")
        return ProveedorAnthropic(modelo, clave, timeout_s, int(os.getenv("LLM_MAX_TOKENS", "") or 1024))

    if nombre == "openai":
        clave = os.getenv("OPENAI_API_KEY", "").strip()
        if not clave:
            raise ErrorProveedor(TipoError.CONFIGURACION, "Falta OPENAI_API_KEY en el archivo .env")
        esfuerzo = os.getenv("OPENAI_REASONING_EFFORT", "").strip() or "low"
        return ProveedorOpenAI(modelo, clave, timeout_s, int(os.getenv("LLM_MAX_TOKENS", "") or 4000),
                               None if esfuerzo == "ninguno" else esfuerzo)

    if nombre == "xai":
        clave = os.getenv("XAI_API_KEY", "").strip()
        if not clave:
            raise ErrorProveedor(TipoError.CONFIGURACION, "Falta XAI_API_KEY en el archivo .env")
        # Sin response_format ni reasoning_effort: el JSON lo exige el prompt y lo valida Pydantic
        return ProveedorOpenAI(modelo, clave, timeout_s, int(os.getenv("LLM_MAX_TOKENS", "") or 1024),
                               None, base_url=URL_XAI, nombre="xai", modo_json=False)

    raise ErrorProveedor(TipoError.CONFIGURACION,
                         f"PROVEEDOR_LLM='{nombre}' no es válido (anthropic, openai, xai o simulado)")
