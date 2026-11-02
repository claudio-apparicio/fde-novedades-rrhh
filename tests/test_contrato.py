"""Reglas de validación del contrato. Correr con: pytest"""
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from src.contrato import CampoFaltante, Categoria, Entrada, Salida

RECIBIDA = datetime(2026, 9, 12, 16, 0)


def salida(**kw):
    base = dict(categoria="novedad", tipo="horas_extras_100", legajo="1091", fecha_desde="2026-09-12",
                cantidad=10, unidad="HS", tiene_adjunto=False, campos_faltantes=[],
                respuesta_supervisor="Recibido: 10 HS al 100% del legajo 1091, pendiente de aprobación.",
                confianza=0.9)
    base.update(kw)
    return Salida.model_validate(base, context={"recibida_en": RECIBIDA})


def test_salida_valida():
    assert salida().categoria == Categoria.NOVEDAD


# --- Enum -------------------------------------------------------------------
@pytest.mark.parametrize("campo,valor", [("tipo", "bono"), ("unidad", "semanas"), ("categoria", "chisme")])
def test_enum_rechaza_valores_no_permitidos(campo, valor):
    with pytest.raises(ValidationError):
        salida(**{campo: valor})


def test_entrada_rechaza_sector_inexistente():
    with pytest.raises(ValidationError):
        Entrada(supervisor_id="SUP-001", sector="pintura", canal="mail", recibida_en=RECIBIDA,
                mensaje="mensaje de prueba válido")


# --- Rangos -------------------------------------------------------------------
@pytest.mark.parametrize("kw", [{"confianza": 1.5}, {"confianza": -0.1}, {"cantidad": 0}, {"cantidad": 40}])
def test_rangos(kw):
    with pytest.raises(ValidationError):
        salida(**kw)


def test_fecha_hasta_anterior():
    with pytest.raises(ValidationError, match="fecha_hasta"):
        salida(fecha_hasta="2026-09-01")


def test_fecha_muy_retroactiva():
    with pytest.raises(ValidationError, match="retroactivos"):
        salida(fecha_desde="2026-06-01")


# --- Patrón -------------------------------------------------------------------
@pytest.mark.parametrize("legajo", ["Juan", "104", "10422"])
def test_patron_legajo(legajo):
    with pytest.raises(ValidationError):
        salida(legajo=legajo)


def test_patron_supervisor():
    with pytest.raises(ValidationError):
        Entrada(supervisor_id="J. M.", sector="montaje", canal="mail", recibida_en=RECIBIDA,
                mensaje="mensaje de prueba válido")


# --- Largo mínimo -------------------------------------------------------------
def test_largo_minimo_respuesta():
    with pytest.raises(ValidationError):
        salida(respuesta_supervisor="ok")


def test_largo_minimo_mensaje():
    with pytest.raises(ValidationError):
        Entrada(supervisor_id="SUP-001", sector="montaje", canal="mail", recibida_en=RECIBIDA, mensaje="hs ok")


# --- Coherencia -----------------------------------------------------------------
def test_unidad_incoherente():
    with pytest.raises(ValidationError, match="se informa en"):
        salida(tipo="adelanto", unidad="HS", cantidad=5)


def test_faltantes_deben_coincidir_con_campos_vacios():
    with pytest.raises(ValidationError, match="campos_faltantes"):
        salida(legajo=None)  # falta legajo pero no está declarado


def test_faltante_bien_declarado():
    s = salida(legajo=None, campos_faltantes=["legajo"])
    assert s.campos_faltantes == [CampoFaltante.LEGAJO]


def test_enfermedad_sin_certificado_exige_adjunto():
    with pytest.raises(ValidationError):
        salida(tipo="licencia_enfermedad", unidad="dias", cantidad=7)
    s = salida(tipo="licencia_enfermedad", unidad="dias", cantidad=7, campos_faltantes=["adjunto"])
    assert CampoFaltante.ADJUNTO in s.campos_faltantes


def test_fuera_de_tema_sin_datos_de_novedad():
    with pytest.raises(ValidationError, match="categoria"):
        salida(categoria="fuera_de_tema")
    s = salida(categoria="fuera_de_tema", tipo=None, legajo=None, fecha_desde=None, cantidad=None,
               unidad=None)
    assert s.fecha_desde is None and date(2026, 9, 12)
