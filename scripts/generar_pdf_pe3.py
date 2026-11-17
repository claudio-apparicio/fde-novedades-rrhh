"""
Genera el PDF de la PE3 (2-3 páginas) con la evidencia real de resultados/pe3/.

Antes correr (o todo junto con python scripts/evidencia_pe3.py):
    python -m src.rag.ingesta            (y guardar la salida en resultados/pe3/terminal_ingesta.txt)
    pytest tests/test_rag_permisos.py -v (salida en resultados/pe3/terminal_tests_permisos.txt)
    python scripts/medir_rag.py
    python scripts/demo_rag.py

Uso:  python scripts/generar_pdf_pe3.py      → entrega/FDE_PE3_Aparicio_Claudio.pdf
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import CondPageBreak, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402

from scripts import generar_pdf as g  # noqa: E402  (estilos y utilidades del PDF de la PE2)
from src.rag.documentos import CONFIGS_FRAGMENTADO, leer_catalogo  # noqa: E402

g.SUSTITUIR.update({"✔": "OK", "✘": "X", "←": "<-", "└": "'-", "▶": ">"})
RES = RAIZ / "resultados" / "pe3"
AUTOR = g.AUTOR
P, esc, tabla, terminal, W = g.P, g.esc, g.tabla, g.terminal, g.W
base, chico, h1, h2 = g.base, g.chico, g.h1, g.h2


def leer_json(nombre: str):
    ruta = RES / nombre
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None


def leer_lineas(nombre: str) -> list[str]:
    ruta = RES / nombre
    return ruta.read_text(encoding="utf-8").splitlines() if ruta.exists() else [f"(falta resultados/pe3/{nombre})"]


def lado_a_lado(izq, der, proporcion=0.5):
    tb = Table([[izq, der]], colWidths=[W * proporcion, W * (1 - proporcion)])
    tb.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                            ("RIGHTPADDING", (0, 0), (0, 0), 4), ("RIGHTPADDING", (1, 0), (1, 0), 0)]))
    return tb


def si_no(b: bool, si="sí", no="no") -> str:
    return f"<font color='{'#1e7a46' if b else '#b3261e'}'><b>{si if b else no}</b></font>"


def compacto(r: dict) -> list[str]:
    """JSON de una respuesta del RAG sin los campos de novedad vacíos (para que entre en el PDF)."""
    s = {k: v for k, v in r["salida"].items() if v not in (None, [], False) or k in ("citas",)}
    m = r["metricas"]
    d = {"id_consulta": r["id_consulta"], "usuario_id": r["usuario_id"], "rol": r["rol"], "salida": s,
         "estado": r["estado"], "requiere_humano": r["requiere_humano"], "motivo_humano": r["motivo_humano"],
         "fuentes": r["fuentes"], "fragmentos_enviados": r["fragmentos_enviados"],
         "metricas": {k: m[k] for k in ("modelo", "tokens_entrada", "tokens_salida", "fuente_tokens", "costo_usd",
                                        "latencia_ms", "latencia_busqueda_ms", "intentos")}}
    return g.comprimir_json(json.dumps(d, ensure_ascii=False, indent=1).splitlines())


def analizar_errores(resp: dict, med: dict, preguntas: list[dict]) -> list[str]:
    """Explica cada pregunta normal que falló con los rankings de la medición (sin texto armado a mano)."""
    detalle = {modo: {x["id"]: x for x in med["resultados"][resp["fragmentado"]]["topk"][modo]["detalle"]}
               for modo in ("vectorial", "bm25", "hibrida")}
    esperados = {p["id"]: p["documentos_esperados"] for p in preguntas}
    lineas = []
    for f in resp["filas"]:
        if f["correcto"] or f["tipo"] != "normal" or f["id"] not in detalle["hibrida"]:
            continue
        v, b, h = (detalle[m][f["id"]] for m in ("vectorial", "bm25", "hibrida"))
        docs = "/".join(esperados[f["id"]])
        pos = lambda x: f"{x['posicion']}.º" if x["posicion"] else "fuera de los 10 primeros"  # noqa: E731
        lineas.append(esc(
            f"Error {f['id']}: BM25 ubica {docs} en el puesto {pos(b)} ({b['top5'][0]}); la vectorial, {pos(v)}; "
            f"la híbrida le manda al modelo {', '.join(f['fragmentos_enviados'])}"
            + (f", donde {docs} aparece recién en el puesto {pos(h)} y con otra sección" if h["posicion"] else "")
            + f". El modelo no inventó: devolvió requiere_humano = {'true' if f['requiere_humano'] else 'false'} "
            f"({f['motivo']}). Causa: con pesos iguales, lo que solo encuentra BM25 queda por debajo de lo que "
            "encuentran los dos buscadores. Mejora (serializar las tablas con su encabezado y tratar como búsqueda "
            "exacta las preguntas que piden un código) para validar con el set de evals de la PE6, no con estas "
            "mismas 10 preguntas."))
    return lineas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="https://github.com/claudio-apparicio/fde-novedades-rrhh")
    ap.add_argument("--salida", default=str(RAIZ / "entrega" / "FDE_PE3_Aparicio_Claudio.pdf"))
    a = ap.parse_args()

    med, resp = leer_json("medicion_rag.json"), leer_json("respuestas_rag.json")
    if med is None:
        print("Falta resultados/pe3/medicion_rag.json: corré python scripts/medir_rag.py")
        return 1
    ganadora, n = med["ganadora"], med["n_casos"]
    borrador = med["embeddings"] == "simulado" or resp is None or resp["proveedor"] == "simulado"

    story = []
    if borrador:
        story.append(tabla([["BORRADOR - faltan resultados reales (embeddings o proveedor SIMULADO, o falta "
                             "demo_rag). No entregar: corré python scripts/evidencia_pe3.py con tu clave."]], [W],
                           [("BACKGROUND", (0, 0), (-1, -1), g.ROJO)]))
    modelo = f"{resp['proveedor']} / {resp['modelo']}" if resp else "(sin correr)"
    story += [
        P("RAG con permisos y búsqueda híbrida", h1),
        P(esc(f"Pre-Entrega 3 · Asistente de novedades de personal (RRHH, pyme metalúrgica) · {AUTOR}"), chico),
        P(esc(f"Repositorio: {a.repo} (etiqueta pe3) · Embeddings: {med['embeddings']} (local) · Base: ChromaDB · "
              f"LLM: {modelo} · Medido: {med['fecha'].replace('T', ' ')}"), chico),
        Spacer(1, 2),
        P(esc("Flujo: Entrada -> rol del usuario desde el directorio (no del mensaje) -> buscar(consulta, usuario, k=5): "
              "vectorial (ChromaDB, where rol_<rol>=true) + BM25 sobre lo que la base devuelve para ese rol -> fusión "
              "RRF -> solo esos fragmentos van al prompt -> Motor de la PE2 (valida con Pydantic; las citas tienen "
              "que ser fragmentos enviados) -> Salida + fuentes; requiere_humano lo decide el código."), chico),
    ]

    # ---------------- 1. Ingesta ----------------
    story.append(P("1. Ingesta: un comando, dos configuraciones de fragmentado (python -m src.rag.ingesta)", h2))
    ing = leer_lineas("terminal_ingesta.txt")
    corte = next((i for i, l in enumerate(ing) if l.startswith("Ejemplo de fragmento")), len(ing))
    resumen_ing = [l for l in ing[:corte] if l.strip()]
    ejemplo = g.comprimir_json(ing[corte:])
    story.append(lado_a_lado(terminal(resumen_ing, 34, 80, W * 0.6 - 4), terminal(ejemplo, 34, 53, W * 0.4), 0.6))

    # ---------------- 2. Permisos ----------------
    story.append(P("2. Permisos por rol: filtro en la consulta a la base y tests", h2))
    cat = leer_catalogo()
    roles = cat["roles_validos"]
    corto = {"supervisor": "sup.", "analista_rrhh": "anal.", "jefe_rrhh": "jefe", "empleado": "empl."}
    filas = [["Documento"] + [corto.get(r, r) for r in roles]]
    for d in cat["documentos"]:
        fila = [esc(f"{d['codigo']} {d['titulo']}")]
        for r in roles:
            if r not in d["roles"]:
                fila.append(si_no(False, no="no"))
            elif any(r not in v for v in d.get("secciones", {}).values()):
                fila.append("<font color='#b36b00'><b>sí*</b></font>")
            else:
                fila.append(si_no(True))
        filas.append(fila)
    matriz = tabla(filas, [W * 0.25] + [W * 0.06] * 4)
    nota = P(esc("* sin la sección reservada al jefe (CRI-03 §5 excepciones de gerencia; ESC-04 §4 adicionales). "
                 "Archivo fuera del catálogo = no se ingesta. Una sección solo puede restringir."), g.celda)
    tests = [re.sub(r"^tests/test_rag_permisos\.py::test_", "", l) for l in leer_lineas("terminal_tests_permisos.txt")
             if "::" in l or "passed" in l or "failed" in l or l.startswith("$")]
    tests = [re.sub(r"\s+\[\s*\d+%\]$", "", l) for l in tests]
    story.append(lado_a_lado(Table([[matriz], [nota]], colWidths=[W * 0.49]), terminal(tests, 32, 69, W * 0.51), 0.49))

    # ---------------- 3. Preguntas ----------------
    story.append(CondPageBreak(70 * mm))
    story.append(P("3. Las 10 preguntas de prueba y su resultado de punta a punta (responder)", h2))
    preguntas = json.loads((RAIZ / "datos" / "preguntas_rag.json").read_text(encoding="utf-8"))["preguntas"]
    por_id = {f["id"]: f for f in resp["filas"]} if resp else {}
    filas = [["#", "Tipo", "Quién", "Pregunta", "Doc. con la respuesta", "Estado / requiere_humano", "Fuentes", "OK"]]
    for p in preguntas:
        f = por_id.get(p["id"])
        doc = ", ".join(p["documentos_esperados"]) or "ninguno"
        if p["tipo"] == "restringida":
            doc += " (sin permiso)"
        filas.append([p["id"], p["tipo"].replace("_", " "), p["usuario"], esc(p["pregunta"]), esc(doc),
                      esc(f"{f['estado']} / {'sí' if f['requiere_humano'] else 'no'}") if f else "-",
                      esc(", ".join(f["fuentes"]) or "-") if f else "-", si_no(f["correcto"], "sí", "no") if f else "-"])
    story.append(tabla(filas, [W * 0.04, W * 0.075, W * 0.07, W * 0.38, W * 0.12, W * 0.14, W * 0.13, W * 0.045]))
    if resp:
        pr = resp["promedios"]
        for linea in analizar_errores(resp, med, preguntas):
            story.append(P(linea, chico))
        story.append(P(esc(
            f"Correctas: {resp['correctas']}/{resp['n']}. Normal = responde con fuentes del documento esperado; sin respuesta "
            f"y restringida = requiere_humano y ningún fragmento restringido en el prompt enviado. Promedio por consulta: "
            f"{pr['tokens_entrada']:.0f} / {pr['tokens_salida']:.0f} tokens (campo usage de la API), "
            f"US$ {pr['costo_usd']:.6f}, modelo {pr['latencia_ms']:.0f} ms, búsqueda {pr['busqueda_ms']:.0f} ms."), chico))

    # ---------------- 4. Top-k ----------------
    story.append(P(f"4. Medición top-k: ¿el documento correcto está entre los primeros k? (n = {n})", h2))
    filas = [["Fragmentado", "Fragmentos", "Búsqueda", "hit@1", "hit@3", "hit@5 (k del sistema)", "MRR", "ms"]]
    estilos = []
    for config, r in med["resultados"].items():
        for modo in ("vectorial", "bm25", "hibrida"):
            m = r["topk"][modo]
            c = CONFIGS_FRAGMENTADO[config]
            nombre = f"{config} ({c['max_caracteres']} car., solape {c['solapamiento']})"
            filas.append([esc(nombre), str(r["fragmentos"]), modo] + [f"{m[f'hit@{k}']}/{n}" for k in (1, 3, 5)]
                         + [f"{m['mrr']:.3f}", f"{m['latencia_ms']:.1f}"])
            if config == ganadora and modo == "hibrida":
                estilos.append(("BACKGROUND", (0, len(filas) - 1), (-1, len(filas) - 1), g.AZUL_C))
    gm = med["resultados"][ganadora]["topk"]["hibrida"]
    story += [tabla(filas, [W * 0.3, W * 0.09, W * 0.1, W * 0.08, W * 0.08, W * 0.17, W * 0.09, W * 0.09], estilos),
              P(esc(f"Ganó '{ganadora}' (fila resaltada): hit@5 = {gm['hit@5']}/{n}, hit@1 = {gm['hit@1']}/{n}, "
                    f"MRR = {gm['mrr']:.3f}. Criterio: hit@5 (lo que llega al modelo), luego hit@1 y MRR. "
                    "Cuentan las 6 normales y las 2 restringidas preguntadas por el analista (autorizado); las 2 sin "
                    "respuesta no tienen documento correcto y se evalúan con requiere_humano (sección 3). Fugas con "
                    "el usuario sin permiso (top-50, 3 modos, 2 configuraciones): "
                    f"{sum(len(f['fugas']) for r in med['resultados'].values() for f in r['fugas'])}."), chico)]

    # ---------------- 5. Contraste ----------------
    story.append(P("5. Consultas exactas: la híbrida acierta y la solo vectorial falla (k = 3)", h2))
    filas = [["#", "Consulta (usuario)", "Solo vectorial: top 3", "", "Híbrida: top 3", ""]]
    estilos = []
    for c in med["resultados"][ganadora]["contraste"]:
        filas.append([c["id"], esc(f"{c['consulta']} ({c['usuario']})"), esc(", ".join(c["vectorial"]["top"])),
                      si_no(c["vectorial"]["acierto"], "acierta", "falla"), esc(", ".join(c["hibrida"]["top"])),
                      si_no(c["hibrida"]["acierto"], "acierta", "falla")])
        if c["hibrida"]["acierto"] and not c["vectorial"]["acierto"]:
            estilos.append(("BACKGROUND", (0, len(filas) - 1), (-1, len(filas) - 1), g.AZUL_C))
    gana = sum(1 for c in med["resultados"][ganadora]["contraste"] if c["hibrida"]["acierto"] and not c["vectorial"]["acierto"])
    story += [tabla(filas, [W * 0.04, W * 0.22, W * 0.28, W * 0.07, W * 0.28, W * 0.07], estilos),
              P(esc(f"Acierto = entre los 3 primeros hay un fragmento del documento correcto que contiene el término exacto. "
                    f"Filas resaltadas: {gana} consultas donde la híbrida acierta y la vectorial falla (configuración "
                    f"'{ganadora}'). El modelo de embeddings entiende el sentido pero no distingue bien códigos y números; "
                    "BM25 sí, y cuando la consulta trae un código su ranking pesa el doble en la fusión."), chico)]

    # ---------------- 6. Respuestas ----------------
    story.append(CondPageBreak(75 * mm))
    story.append(P("6. Una respuesta con fuentes (P03) y una con requiere_humano = true (P09, supervisor sin permiso)", h2))
    if resp and all("completo" in por_id.get(i, {}) for i in ("P03", "P09")):
        izq, der = compacto(por_id["P03"]["completo"]), compacto(por_id["P09"]["completo"])
        story.append(lado_a_lado(terminal(izq, 44, 66, W * 0.5 - 4), terminal(der, 44, 66, W * 0.5)))
    else:
        story.append(P("(falta resultados/pe3/respuestas_rag.json: corré python scripts/demo_rag.py)", chico))

    # ---------------- 7. Decisiones ----------------
    story.append(P("7. Decisiones y trade-offs", h2))
    r_sec, r_fij = med["resultados"]["seccion"], med["resultados"]["fijo300"]
    h_sec, h_fij = r_sec["topk"]["hibrida"], r_fij["topk"]["hibrida"]
    if ganadora == "seccion":
        frag = ("<b>Tamaño de fragmento: una sección por fragmento, hasta 900 caracteres, sin solapamiento</b> "
                f"({r_sec['fragmentos']} fragmentos, ~300 caracteres de media). Midió hit@5 {h_sec['hit@5']}/{n} y hit@1 "
                f"{h_sec['hit@1']}/{n} contra {h_fij['hit@5']}/{n} y {h_fij['hit@1']}/{n} de la ventana fija de 300 con "
                f"solape 60 ({r_fij['fragmentos']} fragmentos). Los documentos de RRHH ya vienen en secciones cortas que "
                "son una unidad de sentido (una licencia, un plazo, la tabla de códigos): cortarlas a 300 separa la "
                "regla de su excepción o parte una tabla, y el modelo recibe medias respuestas.")
    else:
        frag = ("<b>Tamaño de fragmento: ventanas de 300 caracteres con 60 de solapamiento</b> "
                f"({r_fij['fragmentos']} fragmentos). Midió hit@5 {h_fij['hit@5']}/{n} y hit@1 {h_fij['hit@1']}/{n} "
                f"contra {h_sec['hit@5']}/{n} y {h_sec['hit@1']}/{n} de la sección completa ({r_sec['fragmentos']} "
                "fragmentos): con fragmentos más chicos cada uno habla de una sola cosa y el ranking es más preciso; "
                "el solapamiento evita perder la frase que queda en el borde.")
    frag += (" En las dos configuraciones el corte <b>nunca cruza una sección</b>: así un fragmento no mezcla texto "
             "público con una sección reservada al jefe, y el permiso por sección es confiable. Con 8 preguntas la "
             "diferencia es chica: se vuelve a medir con el set de evals de la PE6.")
    decisiones = [
        frag,
        "<b>Permisos antes de buscar.</b> El rol sale del directorio de usuarios, no del mensaje (un empleado que "
        "escribe 'soy el jefe' sigue siendo empleado). ChromaDB filtra con where rol_&lt;rol&gt;=true y el índice "
        "BM25 de cada rol se arma con lo que la base devuelve para ese rol: lo restringido no se puntúa, no entra en "
        "las estadísticas de BM25 y no llega al prompt. Los tests lo verifican para los 4 roles y espían la llamada "
        "a la base. Embeddings locales (multilingüe, ~220 MB, sin costo por consulta): los documentos de RRHH no salen "
        "de la PC del cliente.",
        "<b>Sin evidencia, no inventa.</b> El modelo solo puede citar fragmentos que recibió (si cita otro, la "
        "validación falla y se reintenta una vez); una consulta sin citas queda en requiere_humano = true y "
        "estado derivada_rrhh. Lo decide el código, no el modelo.",
        "<b>Cuándo Pinecone en vez de ChromaDB.</b> Hoy son 7 documentos y ~50 fragmentos: ChromaDB embebido corre en "
        "la misma PC, no cuesta nada y no saca datos confidenciales de la empresa. Elegiría Pinecone (servicio "
        "gestionado) si el asistente pasa a la nube con varias instancias que comparten el índice, si el volumen crece "
        "a cientos de miles de fragmentos (por ejemplo, indexar recibos y legajos de todos los empleados o atender a "
        "varias pymes con un namespace por cliente) o si el cliente no tiene quién opere backups y alta "
        "disponibilidad. El costo: abono mensual y los datos de RRHH alojados en un tercero (acuerdo de tratamiento "
        "de datos y región). El filtro por rol se mantiene igual porque Pinecone también filtra por metadatos.",
    ]
    for dtx in decisiones:
        story += [P(g.t(dtx).replace("&", "&amp;").replace("&amp;lt;", "&lt;").replace("&amp;gt;", "&gt;"), chico),
                  Spacer(1, 1.5)]

    story.append(P("8. Ajustes por la devolución de la PE2", h2))
    story.append(P(esc(
        "README con el contenido exacto de .env.example y .gitignore (que excluye .env) y verificación desde un clon "
        "limpio (scripts/verificar_clon_limpio.py, salida en resultados/); el error persistente se muestra completo, con "
        "la respuesta cruda del modelo; cada medición rotula que los tokens vienen del campo usage y separa los KPI con "
        "meta de los indicadores exploratorios; las 5 consultas de la PE2 quedan como smoke test y la medición robusta "
        "se hará con el set fijo de 60 mensajes en la PE6. Prompt, validación Pydantic y reglas siguen separados."), chico))

    Path(a.salida).parent.mkdir(parents=True, exist_ok=True)

    def pie(c, doc):
        c.saveState()
        c.setFont("Helvetica", 6.8)
        c.setFillColor(g.GRIS)
        c.drawString(14 * mm, 8 * mm, f"FDE - Pre-Entrega 3 - RAG con permisos y búsqueda híbrida - {AUTOR}")
        c.drawRightString(A4[0] - 14 * mm, 8 * mm, f"Página {doc.page}")
        c.setStrokeColor(g.AZUL)
        c.setLineWidth(1.5)
        c.line(14 * mm, A4[1] - 9 * mm, A4[0] - 14 * mm, A4[1] - 9 * mm)
        c.restoreState()

    doc = SimpleDocTemplate(a.salida, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm,
                            bottomMargin=13 * mm, title="FDE PE3 - RAG con permisos y búsqueda híbrida", author=AUTOR)
    doc.build(story, onFirstPage=pie, onLaterPages=pie)
    try:
        from pypdf import PdfReader
        paginas = len(PdfReader(a.salida).pages)
    except ImportError:
        paginas = None
    print(f"PDF generado: {a.salida}" + (f" ({paginas} páginas)" if paginas else ""))
    if paginas and paginas > 3:
        print("AVISO: la consigna pide 2 a 3 páginas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
