"""
Genera el PDF de 2 páginas de la PE2 a partir de la evidencia real en resultados/.

Antes correr:
    python scripts/medir.py
    python scripts/demo_errores.py
    git tag pe2            (para que aparezca en la captura del repositorio)

Uso:
    python scripts/generar_pdf.py
Sale en entrega/FDE_PE2_Aparicio_Claudio.pdf
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

RAIZ = Path(__file__).resolve().parents[1]
RES = RAIZ / "resultados"
AUTOR = "Claudio Aparicio"

# Fuentes base de PDF (están en cualquier máquina). Reemplazamos los símbolos que no traen.
SUSTITUIR = {"≥": ">=", "≤": "<=", "→": "->", "─": "-", "═": "=", "…": "...", "↔": "<->", "×": "x",
             "“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-"}


def t(s: str) -> str:
    for a, b in SUSTITUIR.items():
        s = s.replace(a, b)
    return s


def esc(s: str) -> str:
    return t(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


AZUL = colors.HexColor("#1d5c8c")
AZUL_C = colors.HexColor("#e6eff6")
GRIS = colors.HexColor("#5b6670")
LINEA = colors.HexColor("#c9d2da")
ROJO = colors.HexColor("#b3261e")
VERDE = colors.HexColor("#1e7a46")
TERM_BG = colors.HexColor("#1e2329")
TERM_FG = colors.HexColor("#e6e6e6")

base = ParagraphStyle("b", fontName="Helvetica", fontSize=8.3, leading=10.3)
chico = ParagraphStyle("c", parent=base, fontSize=7.4, leading=9)
celda = ParagraphStyle("ce", parent=base, fontSize=7.2, leading=8.7)
cab = ParagraphStyle("ca", parent=celda, fontName="Helvetica-Bold", textColor=colors.white)
h1 = ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=14, leading=17, textColor=AZUL)
h2 = ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=10, leading=12.5, textColor=AZUL,
                    spaceBefore=5, spaceAfter=2.5)
mono = ParagraphStyle("m", fontName="Courier", fontSize=6.1, leading=7.1, textColor=TERM_FG)
W = A4[0] - 28 * mm


def P(s, st=base):
    return Paragraph(s, st)


def tabla(filas, anchos, extra=None):
    data = [[P(c, cab if i == 0 else celda) if isinstance(c, str) else c for c in fila]
            for i, fila in enumerate(filas)]
    tb = Table(data, colWidths=anchos, repeatRows=1)
    estilo = [("BACKGROUND", (0, 0), (-1, 0), AZUL), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINEA),
              ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
              ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    tb.setStyle(TableStyle(estilo + (extra or [])))
    return tb


def terminal(lineas: list[str], max_lineas: int, ancho_chars: int = 138, ancho=W):
    salida = []
    for ln in lineas:
        ln = t(ln.rstrip("\n"))
        partes = textwrap.wrap(ln, ancho_chars, subsequent_indent="    ", drop_whitespace=False) or [""]
        salida.extend(partes)
    if len(salida) > max_lineas:
        salida = salida[:max_lineas - 1] + ["    [... recortado para el PDF; salida completa en resultados/ ...]"]
    html = "<br/>".join(esc(x).replace(" ", "&nbsp;") for x in salida)
    tb = Table([[Paragraph(html, mono)]], colWidths=[ancho])
    tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TERM_BG), ("LEFTPADDING", (0, 0), (-1, -1), 5),
                            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return tb


def bloque(archivo: Path, inicio: str, fin_prefijo: str) -> list[str]:
    """Devuelve las líneas desde la que empieza con `inicio` hasta la siguiente que empieza con `fin_prefijo`."""
    if not archivo.exists():
        return [f"(no se encontró {archivo.relative_to(RAIZ)}: corré el script correspondiente)"]
    lineas = archivo.read_text(encoding="utf-8").splitlines()
    out, dentro = [], False
    for ln in lineas:
        if ln.startswith(inicio):
            dentro = True
        elif dentro and ln.startswith(fin_prefijo):
            break
        if dentro:
            out.append(ln)
    return out or [f"(no se encontró el bloque '{inicio}' en {archivo.name})"]


def comprimir_json(lineas: list[str]) -> list[str]:
    """Junta en una línea las listas cortas del JSON para que entre en el PDF."""
    out, buf = [], None
    for ln in lineas:
        if buf is not None:
            buf.append(ln.strip())
            if ln.strip().startswith("]"):
                out.append(buf[0] + " ".join(buf[1:]).replace("[ ", "["))
                buf = None
            continue
        if ln.rstrip().endswith("[") and not ln.strip().startswith("{"):
            buf = [ln.rstrip()]
            continue
        out.append(ln)
    return out + (buf or [])


def git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        return f"(git {' '.join(args)} falló: {e})\n"


def arbol(archivos: list[str]) -> list[str]:
    lineas, vistos = [], set()
    for f in sorted(archivos, key=lambda x: (x.count("/") > 0, x)):
        partes = f.split("/")
        for i in range(len(partes) - 1):
            d = "/".join(partes[:i + 1])
            if d not in vistos:
                vistos.add(d)
                lineas.append("    " * i + partes[i] + "/")
        lineas.append("    " * (len(partes) - 1) + partes[-1])
    return lineas


def captura_repo() -> list[str]:
    tag = git("tag", "--list", "pe2").strip()
    archivos = [f for f in git("ls-files").splitlines() if f and not f.endswith("__init__.py")
                and not f.endswith(".gitkeep")]
    izq = ["$ git tag --list pe2", tag or "(todavía no existe la etiqueta pe2: corré `git tag pe2`)",
           "$ git log --oneline --decorate -3", *git("log", "--oneline", "--decorate", "-3").splitlines()]
    der = ["$ git ls-files  (como árbol)", *arbol(archivos)]
    return izq, der


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="https://github.com/claudio-apparicio/fde-novedades-rrhh")
    ap.add_argument("--salida", default=str(RAIZ / "entrega" / "FDE_PE2_Aparicio_Claudio.pdf"))
    a = ap.parse_args()

    med_path = RES / "medicion.json"
    if not med_path.exists():
        print("Falta resultados/medicion.json: corré primero python scripts/medir.py")
        return 1
    med = json.loads(med_path.read_text(encoding="utf-8"))
    prom, kpi, det = med["promedios"], med["kpi"], med["detalle"]
    simulado = med["proveedor"] == "simulado"

    story = []
    if simulado:
        story.append(tabla([["BORRADOR - estos datos salen del proveedor SIMULADO. No entregar: corré "
                             "scripts/medir.py con tu clave y volvé a generar el PDF."]], [W],
                           [("BACKGROUND", (0, 0), (-1, -1), ROJO)]))
    story += [
        P("Motor LLM base y validación estructurada", h1),
        P(esc(f"Pre-Entrega 2 · Asistente de novedades de personal (RRHH, pyme metalúrgica) · {AUTOR}"), chico),
        P(esc(f"Repositorio: {a.repo} (etiqueta pe2) · Proveedor: {med['proveedor']} · Modelo: "
              f"{med['modelo']} · Medido: {med['fecha'][:16].replace('T', ' ')}"), chico),
    ]

    # ---------------- 1. Contrato ----------------
    story.append(P("1. Contrato de datos (src/contrato.py)", h2))
    ent = [["Entrada", "Regla"],
           ["supervisor_id", "patrón ^SUP-\\d{3}$"],
           ["sector", "Enum: 5 sectores de planta"],
           ["canal", "Enum: whatsapp, mail, chat_web"],
           ["recibida_en", "fecha-hora"],
           ["mensaje", "largo 10 a 2000"]]
    sal = [["Salida (la devuelve el modelo)", "Regla"],
           ["categoria", "Enum: novedad, consulta, fuera_de_tema"],
           ["tipo", "Enum: 9 tipos de novedad · opcional"],
           ["legajo", "patrón ^\\d{4}$ · opcional"],
           ["fecha_desde / fecha_hasta", "fecha; hasta >= desde; máx. 60 días atrás"],
           ["cantidad + unidad", "> 0; Enum HS/dias/$; rango HS 0,5-12, días 1-30, $ 1.000-500.000; unidad acorde al tipo"],
           ["tiene_adjunto", "bool"],
           ["campos_faltantes", "Enum; debe coincidir EXACTO con los campos vacíos (+ adjunto si es enfermedad/ausencia justificada)"],
           ["respuesta_supervisor", "largo 20 a 600"],
           ["confianza", "rango 0 a 1"]]
    ent_t = tabla([[esc(x) for x in f] for f in ent], [W * 0.13, W * 0.17])
    sal_t = tabla([[esc(x) for x in f] for f in sal], [W * 0.2, W * 0.48])
    cont = Table([[ent_t, sal_t]], colWidths=[W * 0.31, W * 0.69])
    cont.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (0, 0), 6)]))
    story += [cont, Spacer(1, 2), P(esc(
        "Si categoria no es «novedad», todos los datos de novedad deben venir vacíos. Después de validar, el "
        "código (no el modelo) decide el estado: requiere_dato, pendiente_analista, pendiente_jefe (HS > 8 o "
        "adelanto > $100.000), revision_manual (confianza < 0,7), derivada_rrhh o fuera_de_alcance."), chico)]

    # ---------------- 2. Ejecución exitosa ----------------
    story.append(P("2. Ejecución exitosa (salida real de la terminal, consulta 1)", h2))
    ok = comprimir_json(bloque(RES / "terminal_medicion.txt", "── Consulta 1", "── Consulta 2"))
    story.append(terminal(ok, 26))

    # ---------------- 3. Ejecución con error ----------------
    story.append(P("3. Ejecución con error (salida real de la terminal)", h2))
    err_file = RES / "terminal_errores.txt"
    err = bloque(err_file, "── 1.", "── 2.")
    if err and err[-1].startswith("── 3."):
        err = err[:-1]
    err = [ln for ln in err if '"respuesta_cruda"' not in ln]
    err = comprimir_json(err)
    api = bloque(err_file, "── 2.", "── 3.")
    story.append(terminal(err, 30))
    if api and not api[0].startswith("(no se encontró"):
        api_logs = [ln for ln in api if " ERROR " in ln or ln.startswith("──") or '"tipo_error"' in ln]
        story += [Spacer(1, 2), terminal(api_logs, 6)]

    story.append(PageBreak())

    # ---------------- 4. Medición ----------------
    story.append(P("4. Medición de las 5 consultas", h2))
    filas = [["#", "Consulta", "¿Validó?", "Tokens (entrada / salida)", "Costo USD", "Latencia ms", "Estado"]]
    for d in det:
        r, c, m = d["resultado"], d["consulta"], d["resultado"]["metricas"]
        valido = ("Sí" if m["intentos"] == 1 else "Sí (reintento)") if r["ok"] else "No"
        estado = r.get("estado") or r.get("tipo_error")
        filas.append([str(c["id"]), esc(f"<i>{c['descripcion']}</i>: ") .replace("&lt;i&gt;", "<i>")
                      .replace("&lt;/i&gt;", "</i>") + esc(c["entrada"]["mensaje"]), valido,
                      f"{m['tokens_entrada']} / {m['tokens_salida']}", f"{m['costo_usd']:.6f}",
                      str(m["latencia_ms"]), esc(estado)])
    filas.append(["<b>Prom</b>", "", f"<b>{prom['validacion']:.0%}</b>",
                  f"<b>{prom['tokens_entrada']:.0f} / {prom['tokens_salida']:.0f}</b>",
                  f"<b>{prom['costo_usd']:.6f}</b>", f"<b>{prom['latencia_ms']:.0f}</b>", ""])
    story.append(tabla(filas, [W * 0.05, W * 0.43, W * 0.09, W * 0.12, W * 0.09, W * 0.08, W * 0.14],
                       [("BACKGROUND", (0, -1), (-1, -1), AZUL_C)]))

    d_ok = kpi["deteccion_faltantes"] is not None and kpi["deteccion_faltantes"] >= kpi["meta_deteccion"]
    f_ok = kpi["falsas_alarmas"] is not None and kpi["falsas_alarmas"] <= kpi["meta_falsas_alarmas"]

    def marca(b):
        color = "#1e7a46" if b else "#b3261e"
        return f"<font color='{color}'><b>{'cumple' if b else 'no cumple'}</b></font>"

    comp = [["Indicador", "Medido (n = 5)", "Meta PE1", "Resultado"],
            ["KPI técnico: detección de faltantes al ingreso",
             f"{kpi['detectadas']}/{kpi['incompletas']} = {kpi['deteccion_faltantes']:.0%}", ">= 95 %", marca(d_ok)],
            ["Falsas alarmas (pide datos a una consulta completa o fuera de tema)",
             f"{kpi['falsas']}/{kpi['completas_o_fuera']} = {kpi['falsas_alarmas']:.0%}", "<= 10 %", marca(f_ok)],
            ["Categoría correcta (novedad / consulta / fuera de tema)", f"{kpi['categoria_correcta']:.0%}", "-", "-"],
            ["Latencia promedio por consulta (la demora hoy es de 22 h por novedad)",
             f"{prom['latencia_ms']:.0f} ms", "-", "-"],
            ["Costo promedio por consulta / proyectado mes (40 novedades)",
             f"US$ {prom['costo_usd']:.6f} / US$ {prom['costo_usd'] * 40:.4f}", "-", "-"]]
    story += [Spacer(1, 3), tabla([[esc(x) if i < 3 else x for i, x in enumerate(f)] for f in comp],
                                  [W * 0.48, W * 0.2, W * 0.16, W * 0.16]),
              P(esc("n = 5 no alcanza para afirmar que se cumple la meta: es la primera medición. En la PE6 se "
                    "corre el set fijo de 60 mensajes definido en la PE1."), chico)]

    # ---------------- 5. Repo ----------------
    story.append(P("5. Estructura del repositorio y etiqueta pe2", h2))
    izq, der = captura_repo()
    mitad = W / 2 - 3
    rep = Table([[terminal(izq, 14, 64, mitad), terminal(der, 26, 64, mitad)]], colWidths=[W / 2, W / 2])
    rep.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    story.append(rep)

    # ---------------- 6. Decisiones ----------------
    story.append(P("6. Decisiones y trade-offs", h2))
    if med["proveedor"] == "xai":
        modelo_txt = (f"<b>Modelo: {med['modelo']}</b> de xAI (US$ 1,25 entrada / 2,50 salida por millón de "
                      "tokens), usado a través del SDK de OpenAI con la URL de xAI. Con 40 novedades por mes "
                      "el costo sigue siendo de centavos. El motor corre igual con Claude Haiku 5.5 "
                      "(US$ 0,10 / 0,50) o gpt-5-mini cambiando PROVEEDOR_LLM, sin tocar el resto del código.")
    elif med["proveedor"] == "openai":
        modelo_txt = (f"<b>Modelo: {med['modelo']}</b> (US$ 0,25 entrada / 2,00 salida por millón de tokens). "
                      "Es un modelo de razonamiento: los tokens de razonamiento se cobran como salida y suben "
                      "la latencia, por eso se usa reasoning_effort=low. La alternativa más barata es Claude "
                      "Haiku 5.5 (US$ 0,10 / 0,50), soportada cambiando PROVEEDOR_LLM sin tocar el motor.")
    else:
        modelo_txt = (f"<b>Modelo: {med['modelo']}</b> (US$ 0,10 entrada / 0,50 salida por millón de tokens). "
                      "La tarea es extraer datos de mensajes cortos, no razonar en profundidad, así que conviene "
                      "el modelo más barato y rápido. Con el volumen real (40 novedades/mes) el costo mensual "
                      "es de centavos, así que el precio no es la restricción: si la detección no llega a la meta, "
                      "primero se ajusta el prompt y después se prueba Sonnet 5.5 (20 veces más caro). El motor "
                      "también corre con gpt-5-mini cambiando PROVEEDOR_LLM.")
    decisiones = [
        modelo_txt,
        "<b>Prompt de sistema</b> (src/prompts/sistema.txt, separado del código y armado con string.Template): "
        "le da al modelo un rol acotado (solo interpreta; no aprueba ni decide a quién va), le prohíbe inventar "
        "(dato ausente = null + campos_faltantes; nunca deducir un legajo de un nombre, que fue la causa de 3 "
        "de las 9 incompletas de septiembre), le pide resolver fechas relativas con la fecha de recepción, le "
        "repite los valores del Enum y los rangos, y fija el formato JSON exacto. La regla de negocio "
        "(umbral del jefe, confianza mínima) queda en código: es auditable y no depende del modelo.",
        "<b>Cuando la salida no valida</b>, el motor registra en el log cada campo que falló con su valor, "
        "le reenvía al modelo esos errores una sola vez (src/prompts/correccion.txt) y, si vuelve a fallar, "
        "devuelve un ErrorMotor estructurado (tipo, campos fallidos, respuesta cruda y métricas): la novedad no "
        "se carga y pasa a revisión manual del analista. Los errores de API se traducen a tipos propios: "
        "límite de uso, sin conexión, tiempo agotado y 5xx se reintentan una vez a los 2 s; clave inválida y "
        "pedido rechazado no se reintentan. Los reintentos automáticos del SDK están apagados para que "
        "cada llamada quede medida y registrada.",
    ]
    for dtx in decisiones:
        story.append(P(t(dtx).replace("&", "&amp;").replace("&amp;nbsp;", "&nbsp;"), chico))
        story.append(Spacer(1, 2))

    Path(a.salida).parent.mkdir(parents=True, exist_ok=True)

    def pie(c, doc):
        c.saveState()
        c.setFont("Helvetica", 6.8)
        c.setFillColor(GRIS)
        c.drawString(14 * mm, 8 * mm, f"FDE - Pre-Entrega 2 - Motor LLM base - {AUTOR}")
        c.drawRightString(A4[0] - 14 * mm, 8 * mm, f"Página {doc.page}")
        c.setStrokeColor(AZUL)
        c.setLineWidth(1.5)
        c.line(14 * mm, A4[1] - 9 * mm, A4[0] - 14 * mm, A4[1] - 9 * mm)
        c.restoreState()

    doc = SimpleDocTemplate(a.salida, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=13 * mm, title="FDE PE2 - Motor LLM base",
                            author=AUTOR)
    doc.build(story, onFirstPage=pie, onLaterPages=pie)
    try:
        from pypdf import PdfReader
        n = len(PdfReader(a.salida).pages)
    except ImportError:
        n = None
    print(f"PDF generado: {a.salida}" + (f" ({n} páginas)" if n else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
