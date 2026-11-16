"""Fixtures compartidas: un índice ChromaDB temporal con embeddings simulados (no descarga nada)."""
import os

import pytest

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")


@pytest.fixture(scope="session")
def indices(tmp_path_factory):
    from src.rag.embeddings import EmbeddingsSimulado
    from src.rag.ingesta import crear_cliente, ingestar
    cliente = crear_cliente(tmp_path_factory.mktemp("indice"))
    emb = EmbeddingsSimulado()
    return {c: ingestar(config=c, cliente=cliente, embeddings=emb) for c in ("seccion", "fijo300")}, emb


@pytest.fixture(params=["seccion", "fijo300"])
def buscador(request, indices):
    from src.rag.busqueda import Buscador
    colecciones, emb = indices
    return Buscador(colecciones[request.param], emb)
