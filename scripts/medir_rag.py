"""
Medición del RAG (PE3). No llama al modelo de lenguaje: solo ingesta y búsqueda.

  1. Ingesta los documentos con las DOS configuraciones de fragmentado (seccion y fijo300).
  2. Top-k: en cuántas preguntas el documento correcto aparece entre los primeros k resultados
     (k = 1, 3 y 5; 5 es el k del sistema), para búsqueda vectorial, BM25 e híbrida.
     Cuentan las 6 normales y las 2 restringidas hechas por un usuario AUTORIZADO; las 2 sin
     respuesta no tienen documento correcto y se evalúan con requiere_humano en scripts/demo_rag.py.
  3. Fugas: las 2 restringidas hechas por el usuario SIN permiso no pueden devolver nada del
     documento restringido (se revisan los 50 primeros resultados de los tres modos).
  4. Contraste: consultas exactas (códigos, formularios, normas) donde se compara vectorial vs híbrida.

Salida: resultados/pe3/medicion_rag.json, medicion_rag.csv y terminal_medicion_rag.txt
Uso:    python scripts/medir_rag.py
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from scripts._terminal import grabar_terminal  # noqa: E402
from src.rag.busqueda import Buscador  # noqa: E402
from src.rag.documentos import CONFIGS_FRAGMENTADO  # noqa: E402
from src.rag.embeddings import crear_embeddings_desde_entorno  # noqa: E402
from src.rag.ingesta import crear_cliente, ingestar  # noqa: E402
from src.rag.permisos import obtener_usuario  # noqa: E402

DIR_RES = RAIZ / "resultados" / "pe3"
KS = (1, 3, 5)
K_SISTEMA = 5
MODOS = ("vectorial", "bm25", "hibrida")


def cargar(nombre: str) -> dict:
    return json.loads((RAIZ / "datos" / nombre).read_text(encoding="utf-8"))


def medir_topk(buscador: Buscador, casos: list[dict]) -> dict:
    """casos: [{id, pregunta, usuario, documentos_esperados}] → hit@k, MRR y posiciones por modo."""
    salida = {}
    for modo in MODOS:
        posiciones, latencias, detalle = [], [], []
        for c in casos:
            t0 = time.perf_counter()
            r = buscador.buscar(c["pregunta"], obtener_usuario(c["usuario"]), k=10, modo=modo)
            latencias.append((time.perf_counter() - t0) * 1000)
            docs = [f.documento for f in r]
            pos = next((i + 1 for i, d in enumerate(docs) if d in c["documentos_esperados"]), None)
            posiciones.append(pos)
            detalle.append({"id": c["id"], "posicion": pos, "top5": [f.fragmento_id for f in r[:5]]})
        n = len(casos)
        salida[modo] = {
            **{f"hit@{k}": sum(1 for p in posiciones if p and p <= k) for k in KS},
            "n": n, "mrr": round(sum(1 / p for p in posiciones if p) / n, 3),
            "latencia_ms": round(statistics.mean(latencias), 1), "detalle": detalle,
        }
    return salida


def medir_fugas(buscador: Buscador, restringidas: list[dict]) -> list[dict]:
    out = []
    for p in restringidas:
        u = obtener_usuario(p["usuario"])
        vistos = {f.fragmento_id for modo in MODOS for f in buscador.buscar(p["pregunta"], u, k=50, modo=modo)}
        fugas = sorted(i for i in vistos if i.startswith(p["documento_restringido"] + "#"))
        out.append({"id": p["id"], "usuario": u.id, "rol": u.rol.value, "documento": p["documento_restringido"],
                    "fragmentos_revisados": len(vistos), "fugas": fugas})
    return out


def medir_contraste(buscador: Buscador, consultas: list[dict], k: int) -> list[dict]:
    out = []
    for c in consultas:
        u = obtener_usuario(c["usuario"])
        fila = {"id": c["id"], "consulta": c["consulta"], "usuario": u.id, "documento": c["documento"]}
        for modo in MODOS:
            r = buscador.buscar(c["consulta"], u, k=k, modo=modo)
            acierto = next((f.fragmento_id for f in r if f.documento == c["documento"]
                            and c["termino"].lower() in f.texto.lower()), None)
            fila[modo] = {"acierto": acierto is not None, "fragmento": acierto,
                          "top": [f.fragmento_id for f in r]}
        out.append(fila)
    return out


def main() -> int:
    DIR_RES.mkdir(parents=True, exist_ok=True)
    with grabar_terminal(DIR_RES / "terminal_medicion_rag.txt"):
        return medir()


def medir() -> int:
    print(f"$ python scripts/medir_rag.py      # {datetime.now():%Y-%m-%d %H:%M}")
    preguntas = cargar("preguntas_rag.json")["preguntas"]
    contraste = cargar("consultas_contraste.json")
    emb = crear_embeddings_desde_entorno()
    print(f"Embeddings: {emb.nombre}")
    if emb.nombre == "simulado":
        print("AVISO: embeddings SIMULADOS (hashing). Sirven para probar el circuito, no para medir.")

    # Casos con documento correcto: normales + restringidas preguntadas por alguien autorizado
    casos = [{**p, "usuario": p.get("usuario_autorizado", p["usuario"])}
             for p in preguntas if p["tipo"] in ("normal", "restringida")]
    restringidas = [p for p in preguntas if p["tipo"] == "restringida"]

    cliente = crear_cliente()
    resultados = {}
    for config in CONFIGS_FRAGMENTADO:
        col = ingestar(config=config, cliente=cliente, embeddings=emb)
        b = Buscador(col, emb)
        resultados[config] = {"fragmentos": col.count(), "topk": medir_topk(b, casos),
                              "fugas": medir_fugas(b, restringidas),
                              "contraste": medir_contraste(b, contraste["consultas"], contraste["k"])}

    # ---------------- Top-k ----------------
    n = len(casos)
    print(f"\n── Top-k: ¿el documento correcto está entre los primeros k? ({n} preguntas con documento: "
          f"6 normales + 2 restringidas hechas por un usuario autorizado)")
    print(f"{'Fragmentado':<13}{'Frag.':>6}  {'Búsqueda':<10}{'hit@1':>8}{'hit@3':>8}{'hit@5':>8}{'MRR':>7}{'ms':>7}")
    filas = []
    for config, r in resultados.items():
        for modo in MODOS:
            m = r["topk"][modo]
            print(f"{config:<13}{r['fragmentos']:>6}  {modo:<10}" + "".join(f"{m[f'hit@{k}']:>5}/{n}" for k in KS)
                  + f"{m['mrr']:>7.3f}{m['latencia_ms']:>7.1f}")
            filas.append({"fragmentado": config, "fragmentos": r["fragmentos"], "busqueda": modo,
                          **{f"hit@{k}": f"{m[f'hit@{k}']}/{n}" for k in KS}, "mrr": m["mrr"],
                          "latencia_ms": m["latencia_ms"]})

    def clave(cfg):
        m = resultados[cfg]["topk"]["hibrida"]
        return (m[f"hit@{K_SISTEMA}"], m["hit@1"], m["mrr"])
    ganadora = max(resultados, key=clave)
    otra = next(c for c in resultados if c != ganadora)
    empate = clave(ganadora) == clave(otra)
    g = resultados[ganadora]["topk"]["hibrida"]
    print(f"\nGanadora (híbrida, criterio: hit@{K_SISTEMA}, luego hit@1, luego MRR): '{ganadora}' con "
          f"hit@{K_SISTEMA} = {g[f'hit@{K_SISTEMA}']}/{n}, hit@1 = {g['hit@1']}/{n}, MRR = {g['mrr']}"
          + (" (EMPATE con la otra configuración: se elige la de menos fragmentos)" if empate else ""))
    if empate and resultados[otra]["fragmentos"] < resultados[ganadora]["fragmentos"]:
        ganadora = otra

    print("\nPosición del primer fragmento del documento correcto (híbrida, configuración ganadora):")
    for d, c in zip(resultados[ganadora]["topk"]["hibrida"]["detalle"], casos):
        print(f"  {d['id']} {c['usuario']:<9} pos={d['posicion'] or '-':<3} {c['pregunta'][:62]:<62} {d['top5'][:3]}")

    # ---------------- Fugas ----------------
    print("\n── Permisos: preguntas restringidas hechas por un usuario SIN permiso (top-50, 3 modos)")
    for config, r in resultados.items():
        for f in r["fugas"]:
            print(f"  {config:<9} {f['id']} {f['usuario']:<9} ({f['rol']:<10}) {f['fragmentos_revisados']:>3} "
                  f"fragmentos revisados · de {f['documento']}: {len(f['fugas'])} {'OK' if not f['fugas'] else 'FUGA'}")

    # ---------------- Contraste ----------------
    k = contraste["k"]
    print(f"\n── Contraste vectorial vs híbrida (consultas exactas, k = {k}; acierto = fragmento del documento "
          "correcto que contiene el término)")
    for config, r in resultados.items():
        print(f"  Fragmentado '{config}':")
        for c in r["contraste"]:
            marca = lambda m: "✔" if c[m]["acierto"] else "✘"  # noqa: E731
            destaca = "  ← híbrida acierta y vectorial falla" if c["hibrida"]["acierto"] and not c["vectorial"]["acierto"] else ""
            print(f"    {c['id']} {c['consulta']:<16} {c['usuario']:<9} vectorial {marca('vectorial')} "
                  f"{c['vectorial']['top']}  híbrida {marca('hibrida')} {c['hibrida']['top']}{destaca}")
    gana = [c for c in resultados[ganadora]["contraste"] if c["hibrida"]["acierto"] and not c["vectorial"]["acierto"]]
    print(f"\nEn '{ganadora}': la híbrida acierta y la vectorial falla en {len(gana)} de "
          f"{len(contraste['consultas'])} consultas exactas: {[c['id'] for c in gana]}")

    with open(DIR_RES / "medicion_rag.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)
    (DIR_RES / "medicion_rag.json").write_text(json.dumps(
        {"fecha": datetime.now().isoformat(timespec="minutes"), "embeddings": emb.nombre, "k_sistema": K_SISTEMA,
         "configs": {c: {k2: v for k2, v in CONFIGS_FRAGMENTADO[c].items()} for c in CONFIGS_FRAGMENTADO},
         "ganadora": ganadora, "n_casos": n, "casos": casos, "resultados": resultados},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nArchivos: resultados/pe3/medicion_rag.csv, medicion_rag.json, terminal_medicion_rag.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
