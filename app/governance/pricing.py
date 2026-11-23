"""Step 5: cost per request.

Cost = prompt_tokens/1M * input_price + completion_tokens/1M * output_price.

The free tiers cost you $0 in real life, so the number stored is the
"equivalent list price": what the same tokens would cost on a paid plan.
That is the figure budgets and the dashboard should use.

Prices are USD per 1 million tokens and are ESTIMATES - check them against
each provider's pricing page and edit PRICES below (or add a file
data/prices.json, same shape, which overrides this table).
A model that is not in the table gets cost None (unknown), never a made-up 0.
"""
import json
from decimal import Decimal

from app.paths import data_dir

# model-name prefix (lowercase) -> (input $/1M tokens, output $/1M tokens)
PRICES = {
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "gemini-3.8-flash": (0.30, 2.50),   # TODO: confirm against Google's pricing page
    "gemini-2.5-flash": (0.30, 2.50),
}

OVERRIDE_FILE = data_dir() / "prices.json"


def _table() -> dict:
    table = dict(PRICES)
    try:
        if OVERRIDE_FILE.exists():
            for name, pair in json.loads(OVERRIDE_FILE.read_text("utf-8")).items():
                table[str(name).lower()] = (float(pair[0]), float(pair[1]))
    except Exception:  # a broken override file must not break requests
        pass
    return table


def calculate_cost(model, prompt_tokens, completion_tokens):
    """Return cost in USD (float, 8 decimals) or None if it cannot be known."""
    if not model or prompt_tokens is None or completion_tokens is None:
        return None
    name = str(model).lower()
    table = _table()
    # longest matching prefix wins, so "gemini-3.8-flash-001" matches "gemini-3.8-flash"
    matches = [k for k in table if name.startswith(k)]
    if not matches:
        return None
    price_in, price_out = table[max(matches, key=len)]
    cost = (Decimal(prompt_tokens) * Decimal(str(price_in))
            + Decimal(completion_tokens) * Decimal(str(price_out))) / Decimal(1_000_000)
    return float(round(cost, 8))
