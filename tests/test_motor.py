"""Flujo del motor con el proveedor simulado (no necesita clave). Correr con: pytest"""
import json
from datetime import datetime

import pytest

from src import motor as motor_mod
from src.contrato import Aprobador, Entrada, EstadoNovedad, TipoError
from src.motor import Motor
from src.precios import calcular_costo
from src.proveedores import ProveedorSimulado, _INVALIDA

ENTRADA = Entrada(supervisor_id="SUP-003", sector="montaje", canal="whatsapp",
                  recibida_en=datetime(2026, 9, 12, 16, 0),
                  mensaje="El 1091 hizo 10 hs extras al 100% hoy")

VALIDA = json.dumps({
    "categoria": "novedad", "tipo": "horas_extras_100", "legajo": "1091", "fecha_desde": "2026-09-12",
    "fecha_hasta": None, "cantidad": 10, "unidad": "HS", "tiene_adjunto": False, "campos_faltantes": [],
    "respuesta_supervisor": "Anoté 10 HS al 100% del legajo 1091 para el 12/09. Queda pendiente de aprobación.",
    "confianza": 0.95})


@pytest.fixture(autouse=True)
def sin_espera(monkeypatch):
    monkeypatch.setattr(motor_mod, "ESPERA_REINTENTO_API_S", 0)


def test_respuesta_valida_y_regla_del_jefe():
    r = Motor(ProveedorSimulado([VALIDA])).procesar(ENTRADA)
    assert r.ok and r.estado == EstadoNovedad.PENDIENTE_JEFE
    assert r.aprobador_requerido == Aprobador.JEFE_RRHH
    assert r.metricas.intentos == 1 and r.metricas.tokens_entrada > 0


def test_acepta_json_en_bloque_de_codigo():
    r = Motor(ProveedorSimulado([f"```json\n{VALIDA}\n```"])).procesar(ENTRADA)
    assert r.ok


def test_invalida_y_luego_valida_se_recupera_con_reintento():
    p = ProveedorSimulado([_INVALIDA, VALIDA])
    r = Motor(p).procesar(ENTRADA)
    assert r.ok and p.llamadas == 2 and r.metricas.intentos == 2


def test_invalida_dos_veces_devuelve_error_con_campos():
    p = ProveedorSimulado([_INVALIDA, _INVALIDA])
    r = Motor(p).procesar(ENTRADA)
    assert not r.ok and r.tipo_error == TipoError.VALIDACION
    assert {c.campo for c in r.campos_fallidos} == {"tipo", "legajo", "confianza"}
    assert p.llamadas == 2  # un solo reintento


def test_texto_que_no_es_json():
    r = Motor(ProveedorSimulado(["no sé", "tampoco"])).procesar(ENTRADA)
    assert not r.ok and r.campos_fallidos[0].campo == "(json)"


def test_reintento_ante_error_transitorio_de_api():
    p = ProveedorSimulado(error=TipoError.LIMITE_DE_USO)
    r = Motor(p).procesar(ENTRADA)
    assert not r.ok and r.tipo_error == TipoError.LIMITE_DE_USO and p.llamadas == 2


def test_sin_reintento_ante_clave_invalida():
    p = ProveedorSimulado(error=TipoError.AUTENTICACION)
    r = Motor(p).procesar(ENTRADA)
    assert not r.ok and r.tipo_error == TipoError.AUTENTICACION and p.llamadas == 1


def test_costo_con_precios_publicados():
    # Claude Haiku 5.5: US$ 0,10 entrada / 0,50 salida por millón de tokens
    assert calcular_costo("claude-haiku-5-5", 1_000_000, 0) == pytest.approx(0.10)
    assert calcular_costo("gpt-5-mini", 1000, 500) == pytest.approx(0.00125)


# --- Conteo de tokens de razonamiento (proveedores compatibles con OpenAI) ---------------
class _Uso:
    def __init__(self, prompt, completion, total, razonamiento):
        self.prompt_tokens, self.completion_tokens, self.total_tokens = prompt, completion, total
        self.completion_tokens_details = type("D", (), {"reasoning_tokens": razonamiento})()


def _respuesta(uso):
    msg = type("M", (), {"content": VALIDA})()
    return type("R", (), {"usage": uso, "choices": [type("C", (), {"message": msg})()]})()


@pytest.mark.parametrize("uso,esperado", [
    (_Uso(1000, 600, 1600, 450), 600),   # OpenAI: completion ya incluye el razonamiento
    (_Uso(1000, 140, 1740, 600), 740),   # xAI: el razonamiento viene aparte
    (_Uso(1000, 140, 1140, 0), 140),     # sin razonamiento
])
def test_tokens_de_razonamiento(uso, esperado, monkeypatch):
    from src.proveedores import ProveedorOpenAI
    p = ProveedorOpenAI("gpt-5-mini", "clave", 5, 100, None)
    monkeypatch.setattr(p._cliente.chat.completions, "create", lambda **kw: _respuesta(uso))
    assert p.generar("s", [{"role": "user", "content": "x"}]).tokens_salida == esperado
