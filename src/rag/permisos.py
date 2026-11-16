"""
Roles, usuarios y el filtro de permisos que se aplica EN LA CONSULTA A LA BASE (no después).

- El rol de cada usuario sale del directorio (datos/usuarios.json), nunca del mensaje.
- Cada fragmento guarda un booleano por rol (rol_supervisor, rol_empleado, ...). La búsqueda
  vectorial le pasa a ChromaDB `where={"rol_<rol>": True}` y el índice BM25 se arma solo con los
  fragmentos que devuelve ChromaDB con ese mismo filtro. Lo que el rol no puede leer no se puntúa,
  no se rankea y no llega al prompt.
"""
from __future__ import annotations

import json
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ..contrato import Sector

RAIZ = Path(__file__).resolve().parents[2]
RUTA_DIRECTORIO = RAIZ / "datos" / "usuarios.json"


class Rol(str, Enum):
    SUPERVISOR = "supervisor"
    ANALISTA = "analista_rrhh"
    JEFE = "jefe_rrhh"
    EMPLEADO = "empleado"


class Usuario(BaseModel):
    id: str = Field(pattern=r"^(SUP-\d{3}|ANA-\d{3}|JEF-\d{3}|EMP-\d{4})$")
    rol: Rol
    sector: Optional[Sector] = None


class PermisoDenegado(Exception):
    """El usuario no está en el directorio: no se busca nada en su nombre."""


def clave_rol(rol: Rol | str) -> str:
    return f"rol_{Rol(rol).value}"


def filtro_rol(rol: Rol | str) -> dict:
    """Filtro `where` de ChromaDB: solo fragmentos que este rol puede leer."""
    return {clave_rol(rol): True}


@lru_cache(maxsize=4)
def cargar_directorio(ruta: Path = RUTA_DIRECTORIO) -> dict[str, Usuario]:
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    return {u["id"]: Usuario(**u) for u in datos["usuarios"]}


def obtener_usuario(usuario_id: str) -> Usuario:
    try:
        return cargar_directorio()[usuario_id]
    except KeyError:
        raise PermisoDenegado(f"El usuario '{usuario_id}' no está en el directorio: no se buscan "
                              "documentos en su nombre") from None
