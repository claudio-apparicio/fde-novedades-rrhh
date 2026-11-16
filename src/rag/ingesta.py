"""
Ingesta: lee los documentos del catálogo, los limpia, los divide en fragmentos y los guarda en
ChromaDB con sus metadatos (documento, sección y roles que pueden leerlos).

Un solo comando:
    python -m src.rag.ingesta                      # las dos configuraciones de fragmentado
    python -m src.rag.ingesta --config seccion     # solo una
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from .documentos import CONFIGS_FRAGMENTADO, DIR_DOCUMENTOS, cargar_documentos, fragmentar
from .embeddings import FuncionEmbeddings, crear_embeddings_desde_entorno

log = logging.getLogger("rag.ingesta")

RAIZ = Path(__file__).resolve().parents[2]
DIR_INDICE = RAIZ / "indice"


def nombre_coleccion(config: str) -> str:
    return f"documentos_{config}"


def crear_cliente(ruta: Optional[Path] = None):
    import chromadb
    from chromadb.config import Settings
    ruta = Path(ruta or os.getenv("INDICE_DIR", "") or DIR_INDICE)
    return chromadb.PersistentClient(path=str(ruta), settings=Settings(anonymized_telemetry=False))


def ingestar(carpeta: Path = DIR_DOCUMENTOS, config: str = "seccion", *, cliente=None,
             embeddings: Optional[FuncionEmbeddings] = None, mostrar: bool = False):
    """Recibe la carpeta de documentos y devuelve la colección de ChromaDB (se recrea desde cero)."""
    if config not in CONFIGS_FRAGMENTADO:
        raise ValueError(f"config '{config}' no existe; opciones: {list(CONFIGS_FRAGMENTADO)}")
    cliente = cliente or crear_cliente()
    embeddings = embeddings or crear_embeddings_desde_entorno()
    t0 = time.perf_counter()

    documentos = cargar_documentos(carpeta)
    fragmentos = [f for d in documentos for f in fragmentar(d, config)]

    nombre = nombre_coleccion(config)
    if nombre in [c if isinstance(c, str) else c.name for c in cliente.list_collections()]:
        cliente.delete_collection(nombre)
    coleccion = cliente.create_collection(
        nombre, embedding_function=None,
        metadata={"hnsw:space": "cosine", "config": config, "embeddings": embeddings.nombre,
                  **{k: str(v) for k, v in CONFIGS_FRAGMENTADO[config].items()}})
    vectores = embeddings.documentos([f.texto_indexado for f in fragmentos])
    for i in range(0, len(fragmentos), 100):
        lote = fragmentos[i:i + 100]
        coleccion.add(ids=[f.id for f in lote], embeddings=vectores[i:i + 100],
                      documents=[f.texto for f in lote], metadatas=[f.metadatos() for f in lote])
    ms = round((time.perf_counter() - t0) * 1000)

    if mostrar:
        c = CONFIGS_FRAGMENTADO[config]
        corto = {"supervisor": "sup", "analista_rrhh": "ana", "jefe_rrhh": "jefe", "empleado": "emp"}
        print(f"\n── '{config}': máx. {c['max_caracteres']} car., solape {c['solapamiento']}, "
              f"{'por párrafos' if c['respeta_parrafos'] else 'ventana fija'}, nunca cruza secciones")
        print(f"{'Doc.':<7}{'Archivo':<41}{'Secc':>5}{'Frag':>5}  Roles")
        for d in documentos:
            n = sum(1 for f in fragmentos if f.documento == d.codigo)
            print(f"{d.codigo:<7}{d.archivo[:40]:<41}{len(d.secciones):>5}{n:>5}  "
                  f"{','.join(corto.get(r, r) for r in d.roles)}")
            for sec in d.secciones:
                if sec.roles != d.roles:
                    print(f"{'':<9}└ {sec.titulo[:40]} → {','.join(corto.get(r, r) for r in sec.roles)}")
        largos = [len(f.texto) for f in fragmentos]
        print(f"Total: {len(documentos)} docs · {len(fragmentos)} fragmentos · {sum(largos) / len(largos):.0f} car. "
              f"de media · {ms} ms → colección '{nombre}'")
    log.info("colección %s: %d fragmentos en %d ms", nombre, coleccion.count(), ms)
    return coleccion


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Ingesta de documentos en ChromaDB")
    p.add_argument("--carpeta", default=str(DIR_DOCUMENTOS))
    p.add_argument("--config", default="todas", choices=["todas", *CONFIGS_FRAGMENTADO])
    p.add_argument("--ejemplo", default="CRI-03#006", help="fragmento cuyos metadatos se muestran")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)-7s %(message)s", stream=sys.stderr)

    cliente, embeddings = crear_cliente(), crear_embeddings_desde_entorno()
    configs = list(CONFIGS_FRAGMENTADO) if a.config == "todas" else [a.config]
    print(f"$ python -m src.rag.ingesta      # índice ChromaDB en indice/ · embeddings: {embeddings.nombre}")
    colecciones = {c: ingestar(Path(a.carpeta), c, cliente=cliente, embeddings=embeddings, mostrar=True)
                   for c in configs}
    ej = colecciones[configs[0]].get(ids=[a.ejemplo], include=["documents", "metadatas"])
    if ej["ids"]:
        print(f"\nEjemplo de fragmento ({a.ejemplo}, configuración '{configs[0]}'):")
        print(json.dumps({"id": ej["ids"][0], "texto": ej["documents"][0], "metadatos": ej["metadatas"][0]},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
