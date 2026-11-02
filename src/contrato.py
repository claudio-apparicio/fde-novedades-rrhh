"""
Contrato de datos del motor (Pydantic).

- Entrada: la consulta que manda el supervisor (historia H1 de la PE1).
- Salida:  lo que el modelo TIENE que devolver. Se valida campo por campo;
           si no cumple, el motor reintenta una vez y después devuelve un
           ErrorMotor con los campos que fallaron.
- ResultadoMotor / ErrorMotor: lo que devuelve el motor, con métricas.

Las reglas de negocio (a quién va, si se eleva al jefe) NO las decide el modelo:
están en reglas.py y se aplican después de validar.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

# ---------------------------------------------------------------------------
# Parámetros (SUPUESTOS a confirmar con el jefe de RRHH; ver PE1)
# ---------------------------------------------------------------------------
RANGOS_POR_UNIDAD = {
    "HS": (Decimal("0.5"), Decimal("12")),
    "dias": (Decimal("1"), Decimal("30")),
    "$": (Decimal("1000"), Decimal("500000")),
}
DIAS_MAX_RETROACTIVO = 60


# ---------------------------------------------------------------------------
# Valores permitidos
# ---------------------------------------------------------------------------
class Sector(str, Enum):
    TORNERIA = "torneria"
    SOLDADURA = "soldadura"
    MONTAJE = "montaje"
    DEPOSITO = "deposito"
    MANTENIMIENTO = "mantenimiento"


class Canal(str, Enum):
    WHATSAPP = "whatsapp"
    MAIL = "mail"
    CHAT_WEB = "chat_web"


class Categoria(str, Enum):
    NOVEDAD = "novedad"            # informa algo para cargar en la liquidación
    CONSULTA = "consulta"          # pregunta sobre política o estado (se responde con documentos en la PE3)
    FUERA_DE_TEMA = "fuera_de_tema"


class TipoNovedad(str, Enum):
    HORAS_EXTRAS_50 = "horas_extras_50"
    HORAS_EXTRAS_100 = "horas_extras_100"
    AUSENCIA_JUSTIFICADA = "ausencia_justificada"
    AUSENCIA_INJUSTIFICADA = "ausencia_injustificada"
    LICENCIA_ENFERMEDAD = "licencia_enfermedad"
    LICENCIA_PARTICULAR = "licencia_particular"
    VACACIONES = "vacaciones"
    FRANCO_COMPENSATORIO = "franco_compensatorio"
    ADELANTO = "adelanto"


class Unidad(str, Enum):
    HORAS = "HS"
    DIAS = "dias"
    PESOS = "$"


class CampoFaltante(str, Enum):
    LEGAJO = "legajo"
    TIPO = "tipo"
    FECHA = "fecha_desde"
    CANTIDAD = "cantidad"
    UNIDAD = "unidad"
    ADJUNTO = "adjunto"


class EstadoNovedad(str, Enum):
    REQUIERE_DATO = "requiere_dato"
    PENDIENTE_ANALISTA = "pendiente_analista"
    PENDIENTE_JEFE = "pendiente_jefe"
    REVISION_MANUAL = "revision_manual"
    DERIVADA_RRHH = "derivada_rrhh"
    FUERA_DE_ALCANCE = "fuera_de_alcance"


class Aprobador(str, Enum):
    ANALISTA_RRHH = "analista_rrhh"
    JEFE_RRHH = "jefe_rrhh"


class TipoError(str, Enum):
    VALIDACION = "validacion"
    LIMITE_DE_USO = "limite_de_uso"
    SIN_CONEXION = "sin_conexion"
    TIEMPO_AGOTADO = "tiempo_agotado"
    AUTENTICACION = "autenticacion"
    API = "error_api"
    CONFIGURACION = "configuracion"


class ErrorDeCampo(ValueError):
    """Error de coherencia que recuerda qué campo falló (para registrarlo, no solo "falló la validación")."""

    def __init__(self, campo: str, mensaje: str):
        super().__init__(mensaje)
        self.campo = campo


UNIDAD_ESPERADA = {
    TipoNovedad.HORAS_EXTRAS_50: Unidad.HORAS,
    TipoNovedad.HORAS_EXTRAS_100: Unidad.HORAS,
    TipoNovedad.ADELANTO: Unidad.PESOS,
}  # el resto se informa en días
REQUIEREN_ADJUNTO = {TipoNovedad.LICENCIA_ENFERMEDAD, TipoNovedad.AUSENCIA_JUSTIFICADA}
CAMPOS_OBLIGATORIOS = {
    CampoFaltante.LEGAJO: "legajo",
    CampoFaltante.TIPO: "tipo",
    CampoFaltante.FECHA: "fecha_desde",
    CampoFaltante.CANTIDAD: "cantidad",
    CampoFaltante.UNIDAD: "unidad",
}


# ---------------------------------------------------------------------------
# ENTRADA
# ---------------------------------------------------------------------------
class Entrada(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    supervisor_id: str = Field(pattern=r"^SUP-\d{3}$", examples=["SUP-003"])
    sector: Sector
    canal: Canal
    recibida_en: datetime
    mensaje: str = Field(min_length=10, max_length=2000)


# ---------------------------------------------------------------------------
# SALIDA (lo que devuelve el modelo)
# ---------------------------------------------------------------------------
class Salida(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categoria: Categoria
    tipo: Optional[TipoNovedad] = None
    legajo: Optional[str] = Field(default=None, pattern=r"^\d{4}$")
    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None
    cantidad: Optional[Decimal] = Field(default=None, gt=0)
    unidad: Optional[Unidad] = None
    tiene_adjunto: bool = False
    campos_faltantes: list[CampoFaltante] = Field(default_factory=list)
    respuesta_supervisor: str = Field(min_length=20, max_length=600)
    confianza: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validar_coherencia(self, info: ValidationInfo) -> "Salida":
        datos = ("tipo", "legajo", "fecha_desde", "fecha_hasta", "cantidad", "unidad")

        # Si no es una novedad, no puede traer datos de novedad
        if self.categoria != Categoria.NOVEDAD:
            cargados = [c for c in datos if getattr(self, c) is not None]
            if cargados or self.campos_faltantes:
                raise ErrorDeCampo(
                    "categoria", f"categoria '{self.categoria.value}' no lleva datos de novedad; vinieron: "
                    f"{cargados + [f.value for f in self.campos_faltantes]}")
            return self

        # Fechas en orden y dentro de la ventana retroactiva
        if self.fecha_desde and self.fecha_hasta and self.fecha_hasta < self.fecha_desde:
            raise ErrorDeCampo("fecha_hasta", "fecha_hasta no puede ser anterior a fecha_desde")
        recibida = (info.context or {}).get("recibida_en")
        if self.fecha_desde and recibida:
            limite = recibida.date() - timedelta(days=DIAS_MAX_RETROACTIVO)
            if self.fecha_desde < limite:
                raise ErrorDeCampo("fecha_desde", f"fecha_desde {self.fecha_desde} supera los {DIAS_MAX_RETROACTIVO} "
                                 "días retroactivos")

        # Unidad coherente con el tipo y cantidad dentro del rango de su unidad
        if self.tipo and self.unidad:
            esperada = UNIDAD_ESPERADA.get(self.tipo, Unidad.DIAS)
            if self.unidad != esperada:
                raise ErrorDeCampo("unidad", f"{self.tipo.value} se informa en '{esperada.value}', "
                                 f"no en '{self.unidad.value}'")
        if self.cantidad is not None and self.unidad:
            minimo, maximo = RANGOS_POR_UNIDAD[self.unidad.value]
            if not minimo <= self.cantidad <= maximo:
                raise ErrorDeCampo("cantidad", f"cantidad {self.cantidad} {self.unidad.value} fuera de rango "
                                 f"[{minimo}, {maximo}]")

        # Los faltantes declarados tienen que coincidir con los campos vacíos
        esperados = {f for f, campo in CAMPOS_OBLIGATORIOS.items() if getattr(self, campo) is None}
        if self.tipo in REQUIEREN_ADJUNTO and not self.tiene_adjunto:
            esperados.add(CampoFaltante.ADJUNTO)
        declarados = set(self.campos_faltantes)
        if declarados != esperados:
            raise ErrorDeCampo(
                "campos_faltantes", "campos_faltantes no coincide con los campos vacíos: "
                f"declarados={sorted(f.value for f in declarados)}, "
                f"esperados={sorted(f.value for f in esperados)}")
        return self


# ---------------------------------------------------------------------------
# Lo que devuelve el motor
# ---------------------------------------------------------------------------
class Metricas(BaseModel):
    proveedor: str
    modelo: str
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd: float = 0.0
    latencia_ms: int = 0
    intentos: int = 0


class ResultadoMotor(BaseModel):
    ok: Literal[True] = True
    id_consulta: str
    salida: Salida
    estado: EstadoNovedad
    aprobador_requerido: Optional[Aprobador] = None
    metricas: Metricas


class CampoFallido(BaseModel):
    campo: str
    error: str
    valor: Optional[str] = None


class ErrorMotor(BaseModel):
    ok: Literal[False] = False
    id_consulta: str
    tipo_error: TipoError
    mensaje: str
    campos_fallidos: list[CampoFallido] = Field(default_factory=list)
    respuesta_cruda: Optional[str] = None
    metricas: Metricas
