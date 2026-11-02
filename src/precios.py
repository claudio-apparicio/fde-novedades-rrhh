"""
Precios publicados en USD por millón de tokens (consultados el 02/11/2026).
- Anthropic: https://platform.claude.com/docs/en/about-claude/pricing
- OpenAI:    https://developers.openai.com/api/docs/models/gpt-5-mini
- xAI:       https://docs.x.ai/docs/models (grok-4.3 según costbench.com, verificado el 10/10/2026;
             confirmalo en la consola de xAI antes de medir)
Si usás otro modelo, agregalo acá con su precio publicado.
"""
from __future__ import annotations

PRECIOS_USD_POR_MTOK = {
    # modelo: (entrada, salida)
    "claude-haiku-5-5": (0.10, 0.50),    # prompts de hasta 100.000 tokens
    "claude-sonnet-5-5": (2.00, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "grok-4.3": (1.25, 2.50),           # contextos de menos de 200.000 tokens
    "simulado": (0.0, 0.0),
}


def calcular_costo(modelo: str, tokens_entrada: int, tokens_salida: int) -> float:
    if modelo not in PRECIOS_USD_POR_MTOK:
        raise KeyError(f"No hay precio cargado para '{modelo}'. Agregalo en src/precios.py.")
    p_in, p_out = PRECIOS_USD_POR_MTOK[modelo]
    return round((tokens_entrada * p_in + tokens_salida * p_out) / 1_000_000, 8)
