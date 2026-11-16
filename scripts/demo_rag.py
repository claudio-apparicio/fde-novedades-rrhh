"""
Corre las 10 preguntas de prueba de punta a punta con responder() y el modelo configurado en .env.

Para cada pregunta registra: estado, requiere_humano, fuentes citadas, tokens (campo usage de la API),
costo, latencia del modelo y de la búsqueda, y revisa el PROMPT que realmente se envió: en las
preguntas restringidas no puede aparecer ningún fragmento del documento restringido.

Necesita el índice (python -m src.rag.ingesta) y una clave en .env. Usa el fragmentado que ganó en
scripts/medir_rag.py (o FRAGMENTADO del .env).

Salida: resultados/pe3/respuestas_rag.json y terminal_respuestas_rag.txt
Uso:    python scripts/demo_rag.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from scripts._terminal import grabar_terminal  # noqa: E402
from src.contrato import Entrada  # noqa: E402
from src.motor import Motor, configurar_logs  # noqa: E402
from src.proveedores import ErrorProveedor, Proveedor, crear_proveedor_desde_entorno  # noqa: E402
from src.rag.busqueda import buscador_por_defecto, fragmentado_por_defecto  # noqa: E402
from src.rag.permisos import obtener_usuario  # noqa: E402
from src.rag.responder import responder  # noqa: E402

DIR_RES = RAIZ / "resultados" / "pe3"
RECIBIDA = datetime(2026, 11, 16, 10, 0)
MOSTRAR_COMPLETAS = ("P03", "P09")   # una respuesta con fuentes y una con requiere_humano, en JSON completo


class ProveedorConRegistro(Proveedor):
    """Envuelve al proveedor real y guarda el texto exacto de cada pedido (para auditar el prompt)."""

    def __init__(self, real: Proveedor):
        super().__init__(real.modelo)
        self.real, self.nombre, self.prompts = real, real.nombre, []

    def generar(self, sistema, mensajes):
        self.prompts.append(sistema + "\n" + "\n".join(m["content"] for m in mensajes))
        return self.real.generar(sistema, mensajes)


def main() -> int:
    DIR_RES.mkdir(parents=True, exist_ok=True)
    with grabar_terminal(DIR_RES / "terminal_respuestas_rag.txt"):
        return demo()


def demo() -> int:
    configurar_logs()
    print(f"$ python scripts/demo_rag.py      # {datetime.now():%Y-%m-%d %H:%M}")
    try:
        proveedor = ProveedorConRegistro(crear_proveedor_desde_entorno())
        motor = Motor(proveedor)
    except ErrorProveedor as e:
        print(f"ERROR de configuración: {e.mensaje}")
        return 1
    config = fragmentado_por_defecto()
    buscador = buscador_por_defecto(config)
    print(f"Proveedor: {proveedor.nombre} · modelo: {proveedor.modelo} · fragmentado: {config} · "
          f"embeddings: {buscador.embeddings.nombre}\n")

    preguntas = json.loads((RAIZ / "datos" / "preguntas_rag.json").read_text(encoding="utf-8"))["preguntas"]
    filas = []
    for p in preguntas:
        u = obtener_usuario(p["usuario"])
        print(f"── {p['id']} ({p['tipo']}) · {u.id} ({u.rol.value}): {p['pregunta']} " + "─" * 10)
        sys.stdout.flush()
        n_prompts = len(proveedor.prompts)
        entrada = Entrada(supervisor_id=u.id, sector=u.sector, canal="chat_web", recibida_en=RECIBIDA,
                          mensaje=p["pregunta"])
        r = responder(entrada, u, buscador=buscador, motor=motor)
        sys.stderr.flush()
        prompt = "\n".join(proveedor.prompts[n_prompts:])
        restringido = p.get("documento_restringido")
        en_prompt = sorted({ln[1:11] for ln in prompt.splitlines() if restringido and ln.startswith(f"[{restringido}#")})
        m = r.metricas
        fila = {"id": p["id"], "tipo": p["tipo"], "usuario": u.id, "rol": u.rol.value, "pregunta": p["pregunta"],
                "documentos_esperados": p["documentos_esperados"], "ok": r.ok,
                "estado": r.estado.value if r.ok else r.tipo_error.value,
                "requiere_humano": r.requiere_humano, "motivo": getattr(r, "motivo_humano", None),
                "fuentes": [f.fragmento_id for f in r.fuentes] if r.ok else [],
                "fragmentos_enviados": r.fragmentos_enviados if r.ok else [],
                "respuesta": r.salida.respuesta_supervisor if r.ok else r.mensaje,
                "restringido_en_prompt": en_prompt, "tokens_entrada": m.tokens_entrada,
                "tokens_salida": m.tokens_salida, "fuente_tokens": m.fuente_tokens, "costo_usd": m.costo_usd,
                "latencia_ms": m.latencia_ms, "busqueda_ms": m.latencia_busqueda_ms, "intentos": m.intentos}
        if p["tipo"] == "normal":
            fila["correcto"] = (r.ok and not r.requiere_humano and bool(fila["fuentes"])
                                and all(f.split("#")[0] in p["documentos_esperados"] for f in fila["fuentes"]))
        else:
            fila["correcto"] = r.requiere_humano and not en_prompt
        if p["id"] in MOSTRAR_COMPLETAS:
            fila["completo"] = json.loads(r.model_dump_json())
        filas.append(fila)
        if p["id"] in MOSTRAR_COMPLETAS:
            print(r.model_dump_json(indent=2))
        else:
            print(json.dumps({k: fila[k] for k in ("estado", "requiere_humano", "motivo", "fuentes",
                                                   "fragmentos_enviados", "respuesta")},
                             ensure_ascii=False, indent=2))
        if restringido:
            print(f"Prompt enviado: fragmentos de {restringido} = {len(en_prompt)} → "
                  f"{'OK, no llegó nada restringido' if not en_prompt else 'FUGA ' + str(en_prompt)}")
        print()

    n = len(filas)
    print("═" * 100)
    print(f"{'#':<5}{'Tipo':<14}{'Rol':<15}{'Estado':<16}{'Humano':<8}{'Fuentes':<26}{'Tokens in/out':<14}"
          f"{'US$':<10}{'ms LLM':<8}{'ms búsq.':<9}OK")
    for f in filas:
        print(f"{f['id']:<5}{f['tipo']:<14}{f['rol']:<15}{f['estado']:<16}{'sí' if f['requiere_humano'] else 'no':<8}"
              f"{', '.join(f['fuentes']) or '-':<26}{f['tokens_entrada']}/{f['tokens_salida']:<9}"
              f"{f['costo_usd']:<10.6f}{f['latencia_ms']:<8}{f['busqueda_ms']:<9}{'✔' if f['correcto'] else '✘'}")
    print("═" * 100)
    prom = {k: sum(f[k] for f in filas) / n for k in ("tokens_entrada", "tokens_salida", "costo_usd",
                                                         "latencia_ms", "busqueda_ms")}
    correctas = sum(f["correcto"] for f in filas)
    print(f"Correctas: {correctas}/{n} · normales con fuentes del documento esperado: "
          f"{sum(f['correcto'] for f in filas if f['tipo'] == 'normal')}/6 · sin respuesta y restringidas con "
          f"requiere_humano y sin fuga en el prompt: {sum(f['correcto'] for f in filas if f['tipo'] != 'normal')}/4")
    origen = "campo usage de la API" if filas[0]["fuente_tokens"] == "usage" else "ESTIMADOS por el simulado"
    print(f"Promedio (tokens: {origen}): {prom['tokens_entrada']:.0f} entrada / "
          f"{prom['tokens_salida']:.0f} salida · US$ {prom['costo_usd']:.6f} · modelo {prom['latencia_ms']:.0f} ms · "
          f"búsqueda {prom['busqueda_ms']:.0f} ms")
    (DIR_RES / "respuestas_rag.json").write_text(json.dumps(
        {"fecha": datetime.now().isoformat(timespec="minutes"), "proveedor": proveedor.nombre,
         "modelo": proveedor.modelo, "fragmentado": config, "embeddings": buscador.embeddings.nombre,
         "correctas": correctas, "n": n, "promedios": prom, "filas": filas}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print("\nArchivos: resultados/pe3/respuestas_rag.json, terminal_respuestas_rag.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
