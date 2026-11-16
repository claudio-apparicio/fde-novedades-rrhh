"""
Genera TODA la evidencia de la PE3 y el PDF, en orden, guardando la salida real de cada paso:

  1. python -m src.rag.ingesta                       → resultados/pe3/terminal_ingesta.txt
  2. pytest tests/test_rag_permisos.py -v            → resultados/pe3/terminal_tests_permisos.txt
  3. python scripts/medir_rag.py                     → resultados/pe3/medicion_rag.* (top-k, fugas, contraste)
  4. python scripts/demo_rag.py      (usa la clave)  → resultados/pe3/respuestas_rag.* (10 preguntas)
  5. python scripts/demo_errores.py  (devolución PE2: error persistente completo, con respuesta cruda)
  6. python scripts/generar_pdf_pe3.py               → entrega/FDE_PE3_Aparicio_Claudio.pdf

Uso:  python scripts/evidencia_pe3.py
      python scripts/evidencia_pe3.py --sin-modelo     # saltea 4 y 5 (no gasta tokens)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
RES = RAIZ / "resultados" / "pe3"


def correr(titulo: str, comando: list[str], guardar: Path | None = None, mostrar: str | None = None) -> int:
    print(f"\n▶ {titulo}: {' '.join(comando)}", flush=True)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    p = subprocess.run([sys.executable, *comando], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    salida = p.stdout + (p.stderr if guardar else "")
    if guardar:
        cabecera = f"$ {mostrar or 'python ' + ' '.join(comando)}      # {datetime.now():%Y-%m-%d %H:%M}\n"
        if salida.startswith("$ "):
            cabecera = ""
        guardar.write_text(cabecera + salida, encoding="utf-8")
        print(f"  → {guardar.relative_to(RAIZ)}")
    ultimas = [l for l in (p.stdout + p.stderr).strip().splitlines() if l.strip()][-4:]
    for l in ultimas:
        print(f"  {l}")
    print(f"  {'OK' if p.returncode == 0 else f'ERROR (código {p.returncode})'}")
    return p.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-modelo", action="store_true", help="no corre los pasos que llaman al modelo")
    a = ap.parse_args()
    RES.mkdir(parents=True, exist_ok=True)

    pasos = [
        ("1. Ingesta", ["-m", "src.rag.ingesta"], RES / "terminal_ingesta.txt", None),
        ("2. Tests de permisos por rol", ["-m", "pytest", "tests/test_rag_permisos.py", "-v", "-p", "no:cacheprovider"],
         RES / "terminal_tests_permisos.txt", "pytest tests/test_rag_permisos.py -v"),
        ("3. Medición top-k y contraste", ["scripts/medir_rag.py"], None, None),
    ]
    if not a.sin_modelo:
        pasos += [("4. 10 preguntas de punta a punta", ["scripts/demo_rag.py"], None, None),
                  ("5. Demo de errores (PE2)", ["scripts/demo_errores.py"], None, None)]
    pasos.append(("6. PDF", ["scripts/generar_pdf_pe3.py"], None, None))

    fallas = [t for t, cmd, g, m in pasos if correr(t, cmd, g, m) != 0]
    print("\n" + ("Todo OK." if not fallas else f"Pasos con error: {fallas}"))
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
