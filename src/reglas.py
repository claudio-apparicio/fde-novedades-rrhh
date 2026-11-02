"""
Reglas de negocio deterministas. Se aplican DESPUÉS de validar la salida del modelo:
el modelo interpreta el mensaje, el código decide el circuito de aprobación.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .contrato import Aprobador, Categoria, EstadoNovedad, Salida, TipoNovedad

# SUPUESTOS de la PE1 (en sept. se elevaron 10 HS y $150.000; no se elevaron 6 HS ni $80.000)
UMBRAL_HS_EXTRAS = Decimal("8")
UMBRAL_ADELANTO = Decimal("100000")
# Por debajo de esta confianza, la propuesta la revisa una persona aunque esté completa
UMBRAL_CONFIANZA = 0.7


def decidir_estado(s: Salida) -> tuple[EstadoNovedad, Optional[Aprobador]]:
    if s.categoria == Categoria.FUERA_DE_TEMA:
        return EstadoNovedad.FUERA_DE_ALCANCE, None
    if s.categoria == Categoria.CONSULTA:
        return EstadoNovedad.DERIVADA_RRHH, Aprobador.ANALISTA_RRHH
    if s.campos_faltantes:
        return EstadoNovedad.REQUIERE_DATO, None
    if s.confianza < UMBRAL_CONFIANZA:
        return EstadoNovedad.REVISION_MANUAL, Aprobador.ANALISTA_RRHH
    if s.tipo in (TipoNovedad.HORAS_EXTRAS_50, TipoNovedad.HORAS_EXTRAS_100) and s.cantidad > UMBRAL_HS_EXTRAS:
        return EstadoNovedad.PENDIENTE_JEFE, Aprobador.JEFE_RRHH
    if s.tipo == TipoNovedad.ADELANTO and s.cantidad > UMBRAL_ADELANTO:
        return EstadoNovedad.PENDIENTE_JEFE, Aprobador.JEFE_RRHH
    return EstadoNovedad.PENDIENTE_ANALISTA, Aprobador.ANALISTA_RRHH
