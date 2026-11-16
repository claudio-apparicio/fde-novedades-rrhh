"""
Búsqueda híbrida con permisos: vectorial (ChromaDB) + BM25, fusionadas con Reciprocal Rank Fusion.

El permiso se aplica ANTES de buscar, en los dos caminos:
  - vectorial: `coleccion.query(..., where={"rol_<rol>": True})` → ChromaDB solo compara contra los
    fragmentos que el rol puede leer;
  - BM25: el índice de cada rol se arma con `coleccion.get(where=...)`, o sea, con lo que la base
    devuelve para ese rol. Lo restringido no entra ni en las estadísticas (IDF) del rol.

    buscar(consulta, usuario, k) → [FragmentoRecuperado(documento, fragmento_id, texto, puntaje, ...)]
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

from .embeddings import FuncionEmbeddings, crear_embeddings_desde_entorno, normalizar
from .permisos import Rol, Usuario, filtro_rol

log = logging.getLogger("rag.busqueda")

Modo = Literal["hibrida", "vectorial", "bm25"]
K_RRF = 60              # constante habitual de Reciprocal Rank Fusion
CANDIDATOS = 20         # cuántos trae cada buscador antes de fusionar
# Si la consulta trae un código o un número (HE100, F-12, 1035, art. 207), lo exacto pesa más: el
# ranking de BM25 cuenta doble en la fusión. Sin códigos, los dos rankings pesan igual.
PESO_BM25_CON_CODIGO = 2.0
_HAY_CODIGO = re.compile(r"\d|\b[A-ZÁÉÍÓÚÑ]{2,}\b")

STOPWORDS = set("""a al algo como con cual cuales cuando cuanto cuanta cuantos cuantas de del donde el
ella en entre es esa ese eso esta este esto hay la las le les lo los mas me mi mis muy no o para pero
por que se segun ser si sin sobre su sus te tengo tiene tu tus un una uno unos y ya yo""".split())


def _singular(t: str) -> str:
    """Plural → singular muy simple ('conceptos' → 'concepto', 'licencias' → 'licencia')."""
    return t[:-1] if t.isalpha() and len(t) > 4 and t.endswith("s") else t


def tokenizar(texto: str) -> list[str]:
    """Minúsculas, sin tildes y en singular; conserva códigos como 'he100', 'f-12', '19.032' o 'exc-2026-03'."""
    tokens = []
    for t in re.findall(r"[a-z0-9]+(?:[-./][a-z0-9]+)*", normalizar(texto)):
        if t in STOPWORDS:
            continue
        t = _singular(t)
        tokens.append(t)
        partes = re.split(r"[-./]", t)
        if len(partes) > 1:                      # 'f-12' también aporta 'f' y '12'
            tokens.extend(p for p in partes if p and p not in STOPWORDS)
    return tokens


def fusionar_rrf(*rankings: list[str], pesos: tuple[float, ...] = (), k: int = K_RRF) -> dict[str, float]:
    """Reciprocal Rank Fusion: suma peso / (k + posición) de cada ranking."""
    puntajes: dict[str, float] = {}
    for i, ranking in enumerate(rankings):
        peso = pesos[i] if i < len(pesos) else 1.0
        for posicion, fid in enumerate(ranking, start=1):
            puntajes[fid] = puntajes.get(fid, 0.0) + peso / (k + posicion)
    return puntajes


def peso_bm25(consulta: str) -> float:
    return PESO_BM25_CON_CODIGO if _HAY_CODIGO.search(consulta) else 1.0


class FragmentoRecuperado(BaseModel):
    documento: str
    fragmento_id: str
    texto: str
    puntaje: float
    seccion: str
    titulo_documento: str
    roles: str
    rank_vectorial: Optional[int] = None
    rank_bm25: Optional[int] = None
    similitud: Optional[float] = None       # coseno de la búsqueda vectorial (1 = idéntico)


class Buscador:
    def __init__(self, coleccion, embeddings: FuncionEmbeddings):
        self.coleccion = coleccion
        self.embeddings = embeddings
        self._bm25: dict[str, tuple] = {}     # rol → (BM25, ids, documentos, metadatos)
        self.ultima_latencia_ms = 0

    def _indice_bm25(self, rol: Rol):
        if rol.value not in self._bm25:
            from rank_bm25 import BM25Okapi
            datos = self.coleccion.get(where=filtro_rol(rol), include=["documents", "metadatas"])
            # BM25 indexa sección + texto (el título del documento se repite en todos sus fragmentos
            # y solo agregaría ruido a las palabras exactas, que es lo que BM25 aporta)
            corpus = [tokenizar(f"{m['seccion']}\n{d}") for d, m in zip(datos["documents"], datos["metadatas"])]
            bm25 = BM25Okapi(corpus) if corpus else None
            self._bm25[rol.value] = (bm25, datos["ids"], datos["documents"], datos["metadatas"])
        return self._bm25[rol.value]

    def buscar(self, consulta: str, usuario: Usuario, k: int = 3, modo: Modo = "hibrida",
               candidatos: int = CANDIDATOS) -> list[FragmentoRecuperado]:
        if not isinstance(usuario, Usuario):
            raise TypeError("buscar() necesita un Usuario del directorio")
        t0 = time.perf_counter()
        bm25, ids, docs, metas = self._indice_bm25(usuario.rol)
        info = {i: (d, m) for i, d, m in zip(ids, docs, metas)}
        if not ids:
            self.ultima_latencia_ms = round((time.perf_counter() - t0) * 1000)
            return []

        ranking_vec, similitud = [], {}
        if modo in ("hibrida", "vectorial"):
            r = self.coleccion.query(query_embeddings=[self.embeddings.consulta(consulta)],
                                     n_results=min(candidatos, len(ids)), where=filtro_rol(usuario.rol),
                                     include=["distances"])
            ranking_vec = r["ids"][0]
            similitud = {i: round(1 - dist, 4) for i, dist in zip(r["ids"][0], r["distances"][0])}

        ranking_bm25 = []
        if modo in ("hibrida", "bm25") and bm25 is not None:
            puntajes = bm25.get_scores(tokenizar(consulta))
            orden = sorted(range(len(ids)), key=lambda i: puntajes[i], reverse=True)
            ranking_bm25 = [ids[i] for i in orden[:candidatos] if puntajes[i] > 0]

        if modo == "vectorial":
            fusion = {fid: similitud[fid] for fid in ranking_vec}
        elif modo == "bm25":
            fusion = {fid: 1.0 / (K_RRF + p) for p, fid in enumerate(ranking_bm25, start=1)}
        else:
            fusion = fusionar_rrf(ranking_vec, ranking_bm25, pesos=(1.0, peso_bm25(consulta)))

        elegidos = sorted(fusion, key=lambda f: fusion[f], reverse=True)[:k]
        resultado = []
        for fid in elegidos:
            texto, m = info[fid]
            resultado.append(FragmentoRecuperado(
                documento=m["documento"], fragmento_id=fid, texto=texto, puntaje=round(fusion[fid], 5),
                seccion=m["seccion"], titulo_documento=m["titulo_documento"], roles=m["roles"],
                rank_vectorial=ranking_vec.index(fid) + 1 if fid in ranking_vec else None,
                rank_bm25=ranking_bm25.index(fid) + 1 if fid in ranking_bm25 else None,
                similitud=similitud.get(fid)))
        self.ultima_latencia_ms = round((time.perf_counter() - t0) * 1000)
        log.info("búsqueda %s (%s, k=%d) '%s' → %s · %d ms", modo, usuario.rol.value, k, consulta[:50],
                 [f.fragmento_id for f in resultado], self.ultima_latencia_ms)
        return resultado


# ---------------------------------------------------------------------------
# Función del contrato: buscar(consulta, usuario, k)
# ---------------------------------------------------------------------------
_por_defecto: dict[str, Buscador] = {}


def fragmentado_por_defecto() -> str:
    """FRAGMENTADO del .env; si no está, el que ganó en scripts/medir_rag.py; si no hay medición, 'seccion'."""
    if os.getenv("FRAGMENTADO", "").strip():
        return os.getenv("FRAGMENTADO").strip()
    medicion = Path(__file__).resolve().parents[2] / "resultados" / "pe3" / "medicion_rag.json"
    if medicion.exists():
        return json.loads(medicion.read_text(encoding="utf-8")).get("ganadora", "seccion")
    return "seccion"


def buscador_por_defecto(config: Optional[str] = None) -> Buscador:
    """Abre el índice ya ingestado (python -m src.rag.ingesta) con la configuración elegida."""
    from .ingesta import crear_cliente, nombre_coleccion
    config = config or fragmentado_por_defecto()
    if config not in _por_defecto:
        cliente = crear_cliente()
        try:
            coleccion = cliente.get_collection(nombre_coleccion(config))
        except Exception as exc:
            raise RuntimeError(f"No existe el índice '{config}': corré primero python -m src.rag.ingesta") from exc
        embeddings = crear_embeddings_desde_entorno()
        usado = (coleccion.metadata or {}).get("embeddings")
        if usado and usado != embeddings.nombre:
            raise RuntimeError(f"El índice '{config}' se armó con embeddings '{usado}' y ahora están "
                               f"configurados '{embeddings.nombre}': volvé a correr python -m src.rag.ingesta")
        _por_defecto[config] = Buscador(coleccion, embeddings)
    return _por_defecto[config]


def buscar(consulta: str, usuario: Usuario, k: int = 3, modo: Modo = "hibrida",
           buscador: Optional[Buscador] = None) -> list[FragmentoRecuperado]:
    return (buscador or buscador_por_defecto()).buscar(consulta, usuario, k, modo)
