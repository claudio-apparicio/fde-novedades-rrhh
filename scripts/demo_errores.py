"""
Demuestra el manejo de errores y guarda la salida real de la terminal en
resultados/terminal_errores.txt:

  1. Salida inválida: el proveedor simulado devuelve dos veces un JSON que no cumple Salida
     → se registra qué campo falló, se reintenta una vez y se devuelve un error estructurado.
  2. Error de API real: se llama al proveedor configurado en .env con una clave inválida
     → el motor captura el error (401 en Anthropic y OpenAI, 400 en xAI) y lo devuelve
       estructurado (sin reintentar).
  3. Sin conexión (simulado): falla dos veces → un reintento y error estructurado.

Uso:  python scripts/demo_errores.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src.contrato import Entrada, TipoError  # noqa: E402
from src.motor import Motor, configurar_logs  # noqa: E402
from src.proveedores import (ProveedorSimulado, _INVALIDA,  # noqa: E402
                             crear_proveedor_desde_entorno)
from scripts._terminal import grabar_terminal  # noqa: E402



ENTRADA = Entrada(supervisor_id="SUP-003", sector="montaje", canal="whatsapp",
                  recibida_en=datetime(2026, 9, 12, 16, 0),
                  mensaje="Juan hizo 4 hs extras el sábado, cargalas porfa")


def mostrar(titulo: str, motor: Motor) -> None:
    print(f"\n── {titulo} " + "─" * (70 - len(titulo)))
    sys.stdout.flush()
    r = motor.procesar(ENTRADA)
    sys.stderr.flush()
    print(r.model_dump_json(indent=2, exclude={"respuesta_cruda"}))


def main() -> int:
    with grabar_terminal(RAIZ / "resultados" / "terminal_errores.txt"):
        return demo()


def demo() -> int:
    configurar_logs()
    print(f"$ python scripts/demo_errores.py      # {datetime.now():%Y-%m-%d %H:%M}")

    mostrar("1. Salida inválida dos veces (proveedor simulado)",
            Motor(ProveedorSimulado(respuestas=[_INVALIDA, _INVALIDA])))

    from dotenv import load_dotenv
    load_dotenv()
    proveedor = os.getenv("PROVEEDOR_LLM", "anthropic").strip().lower() or "anthropic"
    variables = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "xai": "XAI_API_KEY"}
    if proveedor in variables:
        var = variables[proveedor]
        original = os.environ.get(var)
        os.environ[var] = "sk-clave-invalida-para-la-demo"
        try:
            mostrar(f"2. Error real de API: clave inválida ({proveedor})", Motor(crear_proveedor_desde_entorno()))
        finally:
            if original is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = original

    mostrar("3. Sin conexión dos veces (proveedor simulado)",
            Motor(ProveedorSimulado(error=TipoError.SIN_CONEXION)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
