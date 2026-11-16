"""
Prueba el README desde un clon limpio, siguiendo solo sus instrucciones (devolución de la PE2).

En una carpeta temporal: clona el repo, crea el venv, instala requirements.txt, copia .env.example
como .env SIN claves y corre los comandos del README que no necesitan clave:
  - pytest
  - el motor con el proveedor simulado
  - la ingesta y una consulta del RAG (embeddings simulados, salvo --embeddings-local)
  - git check-ignore: confirma que .env está ignorado y que git no lo ve
Guarda la salida en resultados/verificacion_clon_limpio.txt.

Uso:  python scripts/verificar_clon_limpio.py
      python scripts/verificar_clon_limpio.py --embeddings-local    # además descarga el modelo real (~220 MB)
      python scripts/verificar_clon_limpio.py --repo <ruta o URL> --rama <rama>
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SALIDA = RAIZ / "resultados" / "verificacion_clon_limpio.txt"
REPO = "https://github.com/claudio-apparicio/fde-novedades-rrhh.git"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--rama", default="main")
    ap.add_argument("--embeddings-local", action="store_true")
    a = ap.parse_args()

    log: list[str] = []

    def out(texto: str = ""):
        print(texto, flush=True)
        log.append(texto)

    tmp = Path(tempfile.mkdtemp(prefix="clon_limpio_"))
    clon = tmp / "fde-novedades-rrhh"
    windows = platform.system() == "Windows"
    py = clon / ".venv" / ("Scripts/python.exe" if windows else "bin/python")
    env = {k: v for k, v in os.environ.items()
           if not k.endswith("_API_KEY") and k not in ("PROVEEDOR_LLM", "EMBEDDINGS", "INDICE_DIR", "FRAGMENTADO")}
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})

    def correr(comando: list[str], mostrar: str, extra_env: dict | None = None, ultimas: int = 8) -> int:
        out(f"$ {mostrar}")
        p = subprocess.run(comando, cwd=clon if clon.exists() else tmp, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env={**env, **(extra_env or {})})
        lineas = [l for l in (p.stdout + p.stderr).splitlines() if l.strip()]
        if len(lineas) > ultimas:
            out(f"  [... {len(lineas) - ultimas} líneas antes ...]")
        for l in lineas[-ultimas:]:
            out("  " + l)
        out(f"  → código de salida {p.returncode}\n")
        return p.returncode

    out(f"Verificación del README desde un clon limpio · {datetime.now():%Y-%m-%d %H:%M} · "
        f"{platform.system()} · Python {platform.python_version()}")
    out(f"Carpeta temporal: {tmp}\n")
    pasos = [
        (["git", "clone", "--depth", "1", "--branch", a.rama, a.repo, str(clon)],
         f"git clone --depth 1 --branch {a.rama} {a.repo}", None, 3),
        ([sys.executable, "-m", "venv", str(clon / ".venv")], "python -m venv .venv", None, 3),
        ([str(py), "-m", "pip", "install", "-q", "-r", "requirements.txt"], "pip install -r requirements.txt", None, 4),
    ]
    fallas = 0
    for cmd, mostrar, e, n in pasos:
        if correr(cmd, mostrar, e, n) != 0:
            out("No se pudo preparar el clon: se corta la verificación.")
            SALIDA.write_text("\n".join(log), encoding="utf-8")
            return 1

    shutil.copy(clon / ".env.example", clon / ".env")
    out("$ cp .env.example .env            # sin completar ninguna clave\n")

    emb = {} if a.embeddings_local else {"EMBEDDINGS": "simulado"}
    verificaciones = [
        ([str(py), "-m", "pytest", "-q", "-p", "no:cacheprovider"], "pytest", None, 3),
        ([str(py), "-m", "src.motor", "--mensaje", "Juan hizo horas extra el sábado"],
         'PROVEEDOR_LLM=simulado python -m src.motor --mensaje "Juan hizo horas extra el sábado"',
         {"PROVEEDOR_LLM": "simulado"}, 6),
        ([str(py), "-m", "src.rag.ingesta"],
         ("" if a.embeddings_local else "EMBEDDINGS=simulado ") + "python -m src.rag.ingesta", emb, 6),
        ([str(py), "-m", "src.rag.responder", "--usuario", "EMP-1091", "--mensaje", "¿Qué es el concepto 1035 de mi recibo?"],
         ("" if a.embeddings_local else "EMBEDDINGS=simulado ") + "PROVEEDOR_LLM=simulado python -m src.rag.responder "
         '--usuario EMP-1091 --mensaje "¿Qué es el concepto 1035 de mi recibo?"', {**emb, "PROVEEDOR_LLM": "simulado"}, 6),
        (["git", "check-ignore", "-v", ".env"], "git check-ignore -v .env      # .env tiene que estar ignorado", None, 3),
        (["git", "status", "--porcelain", "--ignored", ".env"], "git status --porcelain --ignored .env   # '!!' = ignorado", None, 3),
    ]
    for cmd, mostrar, e, n in verificaciones:
        fallas += correr(cmd, mostrar, e, n) != 0

    out("RESULTADO: " + ("el README funciona desde un clon limpio, sin claves." if not fallas
                         else f"{fallas} paso(s) fallaron."))
    SALIDA.write_text("\n".join(log) + "\n", encoding="utf-8")
    print(f"\nGuardado en {SALIDA.relative_to(RAIZ)}")
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
