"""
Cost lookup against `pricing.yaml`.

`cost(model, input_tokens, output_tokens)` returns USD using the most
recent price entry with `date <= today` for that model. Also returns
the encoder hint so callers can pick the right tokenizer.

`overhead(profile)` returns hidden token counts to add when the call
is opaque (e.g. Copilot SaaS).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_PRICING_PATH = Path(__file__).with_name("pricing.yaml")


@dataclass(frozen=True)
class PriceEntry:
    model: str
    family: str
    encoder: str
    input_per_million_usd: float
    output_per_million_usd: float
    effective_date: date


@dataclass(frozen=True)
class Overhead:
    hidden_input_tokens: int
    hidden_output_tokens: int


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    with _PRICING_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


def price_for(model: str, *, on: date | None = None) -> PriceEntry:
    on = on or date.today()
    data = _load()
    models = data.get("models", {})
    if model not in models:
        raise KeyError(
            f"Unknown model '{model}' in pricing.yaml. "
            f"Add it under `models:` with at least one price entry."
        )
    spec = models[model]
    entries = sorted(spec["prices"], key=lambda p: _parse_date(p["date"]))
    applicable = [p for p in entries if _parse_date(p["date"]) <= on]
    if not applicable:
        raise ValueError(
            f"No price entry for '{model}' effective on or before {on}. "
            f"Earliest entry is {entries[0]['date']}."
        )
    chosen = applicable[-1]
    return PriceEntry(
        model=model,
        family=spec["family"],
        encoder=spec["encoder"],
        input_per_million_usd=float(chosen["input_per_million_usd"]),
        output_per_million_usd=float(chosen["output_per_million_usd"]),
        effective_date=_parse_date(chosen["date"]),
    )


def cost(model: str, input_tokens: int, output_tokens: int, *, on: date | None = None) -> tuple[float, date]:
    """Return (usd, pricing_date_used) for a given token spend."""
    p = price_for(model, on=on)
    usd = (
        (input_tokens / 1_000_000.0) * p.input_per_million_usd
        + (output_tokens / 1_000_000.0) * p.output_per_million_usd
    )
    return round(usd, 6), p.effective_date


def overhead(profile: str) -> Overhead:
    """Return hidden-token overhead for an opaque call profile."""
    data = _load()
    overheads = data.get("overheads", {})
    if profile not in overheads:
        return Overhead(0, 0)
    o = overheads[profile]
    return Overhead(
        hidden_input_tokens=int(o.get("hidden_input_tokens", 0)),
        hidden_output_tokens=int(o.get("hidden_output_tokens", 0)),
    )
