"""
Corre el motor sobre las 5 consultas de datos/consultas_pe2.json con el modelo configurado en .env
y guarda la evidencia en resultados/:

  - medicion.csv          tabla de la consigna (validó, tokens, costo, latencia) + promedios
  - medicion.json         resultados completos y KPI
  - terminal_medicion.txt salida real de la terminal

Los tokens salen del campo `usage` de la respuesta de la API (con el proveedor simulado son
estimados y se rotulan así). Las 5 consultas son un SMOKE TEST: prueban el circuito completo, no
alcanzan para afirmar la meta; la medición robusta es la del set fijo de 60 mensajes (PE6).

Uso:  python scripts/medir.py               # mide con el modelo de .env
      python scripts/medir.py --resumen     # rehace la tabla y los KPI desde resultados/medicion.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src.contrato import Entrada  # noqa: E402
from src.motor import Motor, configurar_logs  # noqa: E402
from src.proveedores import ErrorProveedor  # noqa: E402
from scripts._terminal import grabar_terminal  # noqa: E402

DIR_RES = RAIZ / "resultados"
META_DETECCION = 0.95       # KPI técnico de la PE1
META_FALSAS_ALARMAS = 0.10



def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resumen", action="store_true", help="no llama al modelo: resume resultados/medicion.json")
    if ap.parse_args().resumen:
        datos = json.loads((DIR_RES / "medicion.json").read_text(encoding="utf-8"))
        print(f"$ python scripts/medir.py --resumen      # medición del {datos['fecha'].replace('T', ' ')}, "
              f"{datos['proveedor']}/{datos['modelo']}")
        resumir(datos["detalle"], datos["promedios"], datos["kpi"])
        return 0
    with grabar_terminal(DIR_RES / "terminal_medicion.txt"):
        return medir()


def medir() -> int:
    configurar_logs()
    print(f"$ python scripts/medir.py      # {datetime.now():%Y-%m-%d %H:%M}")

    try:
        motor = Motor()
    except ErrorProveedor as e:
        print(f"ERROR de configuración: {e.mensaje}")
        return 1
    print(f"Proveedor: {motor.proveedor.nombre} · modelo: {motor.proveedor.modelo}\n")

    consultas = json.loads((RAIZ / "datos" / "consultas_pe2.json").read_text(encoding="utf-8"))
    detalle = []
    for c in consultas:
        print(f"── Consulta {c['id']}: {c['descripcion']} " + "─" * 30)
        sys.stdout.flush()
        r = motor.procesar(Entrada(**c["entrada"]))
        if r.ok:
            s = r.salida
            resumen = {"estado": r.estado.value, "categoria": s.categoria.value,
                       "tipo": s.tipo.value if s.tipo else None, "legajo": s.legajo,
                       "cantidad": float(s.cantidad) if s.cantidad is not None else None,
                       "unidad": s.unidad.value if s.unidad else None,
                       "campos_faltantes": [f.value for f in s.campos_faltantes],
                       "confianza": s.confianza, "respuesta_supervisor": s.respuesta_supervisor}
        else:
            resumen = {"error": r.tipo_error.value, "mensaje": r.mensaje,
                       "campos_fallidos": [cf.model_dump() for cf in r.campos_fallidos]}
        sys.stderr.flush()
        print(json.dumps(resumen, ensure_ascii=False, indent=2) + "\n")
        detalle.append({"consulta": c, "resultado": json.loads(r.model_dump_json())})

    # ---------------- Promedios y KPI ----------------
    n = len(detalle)
    res = [d["resultado"] for d in detalle]
    prom = {
        "tokens_entrada": sum(x["metricas"]["tokens_entrada"] for x in res) / n,
        "tokens_salida": sum(x["metricas"]["tokens_salida"] for x in res) / n,
        "costo_usd": sum(x["metricas"]["costo_usd"] for x in res) / n,
        "latencia_ms": sum(x["metricas"]["latencia_ms"] for x in res) / n,
        "validacion": sum(1 for x in res if x["ok"]) / n,
        "validacion_primer_intento": sum(1 for x in res if x["ok"] and x["metricas"]["intentos"] == 1) / n,
    }
    incompletas = [d for d in detalle if d["consulta"]["esperado"]["estado"] == "requiere_dato"]
    completas = [d for d in detalle if d["consulta"]["esperado"]["estado"] not in ("requiere_dato",)]
    detectadas = sum(1 for d in incompletas
                     if d["resultado"]["ok"] and d["resultado"]["estado"] == "requiere_dato")
    falsas = sum(1 for d in completas
                 if d["resultado"]["ok"] and d["resultado"]["estado"] == "requiere_dato")
    categoria_ok = sum(1 for d in detalle if d["resultado"]["ok"]
                       and d["resultado"]["salida"]["categoria"] == d["consulta"]["esperado"]["categoria"])
    kpi = {
        "deteccion_faltantes": detectadas / len(incompletas) if incompletas else None,
        "detectadas": detectadas, "incompletas": len(incompletas),
        "falsas_alarmas": falsas / len(completas) if completas else None,
        "falsas": falsas, "completas_o_fuera": len(completas),
        "categoria_correcta": categoria_ok / n,
        "meta_deteccion": META_DETECCION, "meta_falsas_alarmas": META_FALSAS_ALARMAS,
    }

    (DIR_RES / "medicion.json").write_text(json.dumps(
        {"proveedor": motor.proveedor.nombre, "modelo": motor.proveedor.modelo,
         "fecha": datetime.now().isoformat(timespec="minutes"), "promedios": prom, "kpi": kpi,
         "detalle": detalle}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    resumir(detalle, prom, kpi)
    print("\nArchivos: resultados/medicion.csv, resultados/medicion.json, resultados/terminal_medicion.txt")
    return 0


def resumir(detalle: list[dict], prom: dict, kpi: dict) -> None:
    """Tabla de la consigna + KPI con meta (PE1) separados de los indicadores exploratorios (sin meta)."""
    filas = []
    for d in detalle:
        c, r, m = d["consulta"], d["resultado"], d["resultado"]["metricas"]
        fuente = m.get("fuente_tokens", "usage")
        filas.append({
            "#": c["id"], "Consulta": c["entrada"]["mensaje"], "Tipo de caso": c["descripcion"],
            "¿Validó?": ("Sí" if m["intentos"] == 1 else "Sí (reintento)") if r["ok"] else "No",
            "Tokens entrada / salida": f"{m['tokens_entrada']} / {m['tokens_salida']}",
            "Origen de los tokens": "campo usage de la API" if fuente == "usage" else "estimados (simulado)",
            "Costo USD": f"{m['costo_usd']:.6f}", "Latencia ms": m["latencia_ms"],
            "Estado": r.get("estado") or r.get("tipo_error"),
        })
    filas.append({"#": "Prom.", "Consulta": "", "Tipo de caso": "", "¿Validó?": f"{prom['validacion']:.0%}",
                  "Tokens entrada / salida": f"{prom['tokens_entrada']:.0f} / {prom['tokens_salida']:.0f}",
                  "Origen de los tokens": filas[0]["Origen de los tokens"],
                  "Costo USD": f"{prom['costo_usd']:.6f}", "Latencia ms": f"{prom['latencia_ms']:.0f}", "Estado": ""})
    with open(DIR_RES / "medicion.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)

    n = len(detalle)
    print("═" * 78)
    print(f"Tokens: {filas[0]['Origen de los tokens']} (entrada / salida; la salida incluye los tokens de razonamiento)")
    print(f"{'#':<6}{'¿Validó?':<16}{'Tokens in/out':<16}{'Costo USD':<13}{'Latencia ms':<13}Estado")
    for fl in filas:
        print(f"{fl['#']!s:<6}{fl['¿Validó?']:<16}{fl['Tokens entrada / salida']:<16}"
              f"{fl['Costo USD']:<13}{fl['Latencia ms']!s:<13}{fl['Estado']}")
    print("═" * 78)
    det, fa = kpi["deteccion_faltantes"], kpi["falsas_alarmas"]
    print("KPI CON META (definidos en la PE1; n = 5 es un smoke test, la meta se evalúa con el set de 60 en la PE6)")
    print(f"  Detección de faltantes al ingreso: {kpi['detectadas']}/{kpi['incompletas']} = {det:.0%} "
          f"(meta ≥ {META_DETECCION:.0%}) → {'CUMPLE' if det >= META_DETECCION else 'NO CUMPLE'} en esta muestra")
    print(f"  Falsas alarmas: {kpi['falsas']}/{kpi['completas_o_fuera']} = {fa:.0%} "
          f"(meta ≤ {META_FALSAS_ALARMAS:.0%}) → {'CUMPLE' if fa <= META_FALSAS_ALARMAS else 'NO CUMPLE'} en esta muestra")
    print("INDICADORES EXPLORATORIOS (sin meta todavía; sirven de línea de base)")
    print(f"  Categoría correcta: {kpi['categoria_correcta'] * n:.0f}/{n} · validación al primer intento: "
          f"{prom['validacion_primer_intento']:.0%}")
    print(f"  Latencia promedio: {prom['latencia_ms']:.0f} ms · costo promedio: US$ {prom['costo_usd']:.6f} · "
          f"proyectado: US$ {prom['costo_usd'] * 40:.4f} por mes (40 novedades, volumen de sept. 2026)")


if __name__ == "__main__":
    sys.exit(main())
