"""
Funciones de embeddings intercambiables (variable EMBEDDINGS):

- local (por defecto): modelo multilingüe que corre en la PC, sin clave ni costo por consulta, con
  fastembed (ONNX, sin PyTorch). Por defecto sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
  (384 dimensiones, ~220 MB, se descarga una vez a modelos/). Los documentos de RRHH no salen de la PC.
- simulado: vectores por hashing de palabras y trigramas. No entiende sinónimos; sirve para los tests
  y para probar el circuito sin descargar nada. No se usa para medir.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
MODELO_LOCAL_POR_DEFECTO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


class FuncionEmbeddings:
    nombre = "base"

    def documentos(self, textos: list[str]) -> list[list[float]]:  # pragma: no cover
        raise NotImplementedError

    def consulta(self, texto: str) -> list[float]:  # pragma: no cover
        raise NotImplementedError


class EmbeddingsSimulado(FuncionEmbeddings):
    nombre = "simulado"

    def __init__(self, dimension: int = 512):
        self.dimension = dimension

    def _vector(self, texto: str) -> list[float]:
        v = [0.0] * self.dimension
        palabras = re.findall(r"[a-z0-9]+", normalizar(texto))
        rasgos = palabras + [p[i:i + 3] for p in palabras for i in range(max(1, len(p) - 2))]
        for r in rasgos:
            h = int(hashlib.md5(r.encode()).hexdigest(), 16)
            v[h % self.dimension] += 1.0 if (h >> 8) % 2 else -1.0
        norma = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norma for x in v]

    def documentos(self, textos: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in textos]

    def consulta(self, texto: str) -> list[float]:
        return self._vector(texto)


class EmbeddingsLocal(FuncionEmbeddings):
    def __init__(self, modelo: str = MODELO_LOCAL_POR_DEFECTO, cache: Path = RAIZ / "modelos"):
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Falta fastembed: pip install -r requirements.txt") from exc
        self.nombre = modelo
        self._modelo = TextEmbedding(model_name=modelo, cache_dir=str(cache))
        # Los modelos e5 esperan prefijos distintos para documentos y consultas
        self._pref_doc, self._pref_q = ("passage: ", "query: ") if "e5" in modelo.lower() else ("", "")

    def documentos(self, textos: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._modelo.embed([self._pref_doc + t for t in textos])]

    def consulta(self, texto: str) -> list[float]:
        return next(iter(self._modelo.embed([self._pref_q + texto]))).tolist()


def crear_embeddings_desde_entorno() -> FuncionEmbeddings:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:  # pragma: no cover
        pass
    tipo = os.getenv("EMBEDDINGS", "").strip().lower() or "local"
    if tipo == "simulado":
        return EmbeddingsSimulado()
    if tipo == "local":
        return EmbeddingsLocal(os.getenv("EMBEDDINGS_MODELO", "").strip() or MODELO_LOCAL_POR_DEFECTO)
    raise ValueError(f"EMBEDDINGS='{tipo}' no es válido (local o simulado)")
