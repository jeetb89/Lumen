# USD per 1M tokens. Update when providers reprice.
PRICE_TABLE: dict[tuple[str, str], dict[str, float]] = {
    ("openai", "gpt-4o"):               {"in": 2.50,  "out": 10.00},
    ("openai", "gpt-4o-mini"):          {"in": 0.15,  "out": 0.60},
    ("openai", "gpt-4.1"):              {"in": 2.00,  "out": 8.00},
    ("openai", "gpt-4.1-mini"):         {"in": 0.40,  "out": 1.60},
    ("anthropic", "claude-opus-4"):     {"in": 15.00, "out": 75.00},
    ("anthropic", "claude-sonnet-4"):   {"in": 3.00,  "out": 15.00},
    ("anthropic", "claude-haiku-4"):    {"in": 0.80,  "out": 4.00},
}


def compute_cost(
    provider: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float | None:
    prices = PRICE_TABLE.get((provider, model))
    if not prices or prompt_tokens is None or completion_tokens is None:
        return None
    return round(
        (prompt_tokens / 1_000_000) * prices["in"]
        + (completion_tokens / 1_000_000) * prices["out"],
        6,
    )


def compute_throughput(
    completion_tokens: int | None,
    latency_ms: int,
    ttft_ms: int | None,
) -> float | None:
    """Generation tokens/s, excluding time-to-first-token where available."""
    if completion_tokens is None or completion_tokens == 0:
        return None
    gen_ms = latency_ms - (ttft_ms or 0)
    if gen_ms <= 0:
        return None
    return round(completion_tokens / (gen_ms / 1000), 2)
