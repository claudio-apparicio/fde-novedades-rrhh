"""
Lectura, limpieza, división en secciones y fragmentado de los documentos del caso.

- Solo se leen los archivos que figuran en documentos/catalogo.json (denegado por defecto).
- Los permisos se asignan por documento y, si hace falta, por sección (una sección solo puede
  restringir los roles de su documento).
- Ninguna configuración de fragmentado cruza el límite de una sección: así un fragmento nunca mezcla
  texto público con texto restringido.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .permisos import Rol

log = logging.getLogger("rag.documentos")

RAIZ = Path(__file__).resolve().parents[2]
DIR_DOCUMENTOS = RAIZ / "documentos"

# Dos configuraciones de fragmentado que se comparan en la medición (scripts/medir_rag.py)
CONFIGS_FRAGMENTADO = {
    # Una sección = un fragmento; si pasa de 900 caracteres se corta entre párrafos
    "seccion": {"max_caracteres": 900, "solapamiento": 0, "respeta_parrafos": True},
    # Ventanas fijas de 300 caracteres con 60 de solapamiento (cortan en el espacio más cercano)
    "fijo300": {"max_caracteres": 300, "solapamiento": 60, "respeta_parrafos": False},
}


@dataclass
class Seccion:
    titulo: str
    texto: str
    roles: tuple[str, ...]


@dataclass
class Documento:
    codigo: str
    titulo: str
    archivo: str
    version: str
    roles: tuple[str, ...]
    secciones: list[Seccion] = field(default_factory=list)


@dataclass
class Fragmento:
    id: str                 # POL-01#004
    documento: str          # POL-01
    titulo_documento: str
    seccion: str
    roles: tuple[str, ...]
    texto: str
    orden: int
    config: str
    archivo: str
    version: str

    @property
    def texto_indexado(self) -> str:
        """Lo que se vectoriza y se indexa en BM25: el texto con su documento y sección como contexto."""
        return f"{self.titulo_documento} · {self.seccion}\n{self.texto}"

    def metadatos(self) -> dict:
        """Metadatos para ChromaDB (solo str, int, float o bool). Un booleano por rol para filtrar."""
        meta = {"documento": self.documento, "titulo_documento": self.titulo_documento,
                "seccion": self.seccion, "roles": ",".join(self.roles), "fragmento_id": self.id,
                "orden": self.orden, "config": self.config, "archivo": self.archivo,
                "version": self.version, "caracteres": len(self.texto)}
        for rol in Rol:
            meta[f"rol_{rol.value}"] = rol.value in self.roles
        return meta


# ---------------------------------------------------------------------------
# Limpieza
# ---------------------------------------------------------------------------
_PIE_DE_PAGINA = re.compile(r"^\s*[—–-]*\s*.*P[aá]gina\s+\d+\s+de\s+\d+\s*[—–-]*\s*$", re.I | re.M)


def limpiar(texto: str) -> str:
    """Quita el ruido típico de un PDF exportado y de un Markdown, sin tocar el contenido."""
    texto = texto.replace("\r\n", "\n").replace("\t", " ")
    texto = re.sub(r"<!--.*?-->", "", texto, flags=re.S)                 # comentarios HTML
    texto = _PIE_DE_PAGINA.sub("", texto)                                 # "— CCT-05 · Página 1 de 3 —"
    # Encabezados repetidos en cada página: líneas idénticas que aparecen 2 veces o más
    repetidas = {l for l, n in Counter(l.strip() for l in texto.split("\n")).items()
                 if n >= 2 and len(l) > 25 and not l.startswith(("|", "-"))}
    texto = "\n".join(l for l in texto.split("\n") if l.strip() not in repetidas)
    texto = re.sub(r"(\w)-\n(\w)", r"\1\2", texto)                       # palabras cortadas con guion
    texto = re.sub(r"[  ]{2,}", " ", texto)
    return texto.strip()


def _desenvolver(bloque: str) -> str:
    """Une las líneas cortadas de un párrafo; respeta ítems de lista y filas de tabla."""
    lineas = [l.rstrip() for l in bloque.split("\n") if l.strip()]
    if lineas and lineas[0].lstrip().startswith("|"):
        filas = []
        for l in lineas:
            celdas = [c.strip() for c in l.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in celdas):
                continue                                                  # separador |---|
            filas.append(" · ".join(celdas))
        return "\n".join(filas)
    salida: list[str] = []
    for l in lineas:
        if l.lstrip().startswith("- ") or not salida:
            salida.append(l.strip())
        else:
            salida[-1] += " " + l.strip()
    return "\n".join(salida)


def _parrafos(texto: str) -> list[str]:
    return [p for p in (_desenvolver(b) for b in re.split(r"\n\s*\n", texto)) if p]


# ---------------------------------------------------------------------------
# Secciones
# ---------------------------------------------------------------------------
_TITULO_TXT = re.compile(r"^(\d+)\.\s+([A-ZÁÉÍÓÚÑ ]{4,})$")


def dividir_secciones(texto: str, extension: str) -> tuple[str, list[tuple[str, str]]]:
    """Devuelve (título del documento, [(título de sección, texto)])."""
    titulo_doc, actual, cuerpo, secciones = "", "Introducción", [], []

    def cerrar():
        contenido = "\n\n".join(_parrafos("\n".join(cuerpo)))
        if contenido:
            secciones.append((actual, contenido))

    for linea in texto.split("\n"):
        s = linea.strip()
        if extension == ".md" and s.startswith("# ") and not titulo_doc:
            titulo_doc = s[2:].strip()
            continue
        nuevo = None
        if extension == ".md" and s.startswith("## "):
            nuevo = s[3:].strip()
        elif extension == ".txt" and _TITULO_TXT.match(s):
            n, nombre = _TITULO_TXT.match(s).groups()
            nuevo = f"{n}. {nombre.strip().capitalize()}"
        if nuevo:
            cerrar()
            actual, cuerpo = nuevo, []
        else:
            cuerpo.append(linea)
    cerrar()
    return titulo_doc, secciones


# ---------------------------------------------------------------------------
# Catálogo y carga
# ---------------------------------------------------------------------------
def leer_catalogo(carpeta: Path = DIR_DOCUMENTOS) -> dict:
    return json.loads((Path(carpeta) / "catalogo.json").read_text(encoding="utf-8"))


def cargar_documentos(carpeta: Path = DIR_DOCUMENTOS) -> list[Documento]:
    carpeta = Path(carpeta)
    catalogo = leer_catalogo(carpeta)
    validos = set(catalogo["roles_validos"])
    en_catalogo = {d["archivo"] for d in catalogo["documentos"]}
    for archivo in sorted(carpeta.iterdir()):
        if archivo.suffix in (".md", ".txt") and archivo.name not in en_catalogo:
            log.warning("'%s' no está en el catálogo: no se ingesta (denegado por defecto)", archivo.name)

    documentos = []
    for d in catalogo["documentos"]:
        roles = tuple(d["roles"])
        if not roles or not set(roles) <= validos:
            raise ValueError(f"{d['codigo']}: roles inválidos {roles}")
        ruta = carpeta / d["archivo"]
        titulo_archivo, secciones = dividir_secciones(limpiar(ruta.read_text(encoding="utf-8")), ruta.suffix)
        restricciones = d.get("secciones", {})
        faltan = set(restricciones) - {t for t, _ in secciones}
        if faltan:
            raise ValueError(f"{d['codigo']}: el catálogo restringe secciones que no existen: {faltan}")
        doc = Documento(d["codigo"], d.get("titulo") or titulo_archivo, d["archivo"], d.get("version", ""), roles)
        for titulo, texto in secciones:
            roles_sec = tuple(restricciones.get(titulo, roles))
            if not set(roles_sec) <= set(roles):
                raise ValueError(f"{d['codigo']} · {titulo}: una sección no puede ampliar los roles del documento")
            doc.secciones.append(Seccion(titulo, texto, roles_sec))
        documentos.append(doc)
    return documentos


# ---------------------------------------------------------------------------
# Fragmentado
# ---------------------------------------------------------------------------
def _cortar_en_palabra(texto: str, maximo: int) -> int:
    if len(texto) <= maximo:
        return len(texto)
    corte = texto.rfind(" ", 0, maximo)
    return corte if corte > maximo // 2 else maximo


def _ventanas(texto: str, maximo: int, solapamiento: int) -> list[str]:
    partes, inicio = [], 0
    while inicio < len(texto):
        fin = inicio + _cortar_en_palabra(texto[inicio:], maximo)
        partes.append(texto[inicio:fin].strip())
        if fin >= len(texto):
            break
        siguiente = texto.rfind(" ", inicio, fin - solapamiento) if solapamiento else fin
        inicio = siguiente + 1 if solapamiento and siguiente > inicio else fin
    return [p for p in partes if p]


def _por_parrafos(texto: str, maximo: int) -> list[str]:
    partes, actual = [], ""
    for p in texto.split("\n\n"):
        if len(p) > maximo:                                     # párrafo enorme: ventanas sin solape
            if actual:
                partes.append(actual)
                actual = ""
            partes.extend(_ventanas(p, maximo, 0))
        elif actual and len(actual) + 2 + len(p) > maximo:
            partes.append(actual)
            actual = p
        else:
            actual = f"{actual}\n\n{p}" if actual else p
    if actual:
        partes.append(actual)
    return partes


def fragmentar(doc: Documento, config: str) -> list[Fragmento]:
    c = CONFIGS_FRAGMENTADO[config]
    fragmentos, n = [], 0
    for sec in doc.secciones:                                    # nunca se cruza una sección
        if c["respeta_parrafos"]:
            textos = _por_parrafos(sec.texto, c["max_caracteres"])
        else:
            textos = _ventanas(sec.texto.replace("\n\n", "\n"), c["max_caracteres"], c["solapamiento"])
        for t in textos:
            n += 1
            fragmentos.append(Fragmento(f"{doc.codigo}#{n:03d}", doc.codigo, doc.titulo, sec.titulo,
                                        sec.roles, t, n, config, doc.archivo, doc.version))
    return fragmentos
