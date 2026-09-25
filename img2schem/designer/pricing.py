"""Price API usage from ``designer/data/pricing.yaml`` (SOW RD.5)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Price:
    input: float  # US$ per million tokens
    output: float
    cache_write: float
    cache_read: float


@cache
def _table() -> dict[str, Any]:
    return yaml.safe_load((Path(__file__).parent / "data" / "pricing.yaml").read_text(encoding="utf-8"))


def price(model: str) -> Price:
    t = _table()
    if model not in t["models"]:
        raise ValueError(f"no price for model {model!r}; add it to designer/data/pricing.yaml")
    m = t["models"][model]
    return Price(m["input"], m["output"], m["input"] * t["cache_write_multiplier"],
                 m.get("cache_read", m["input"] * t["cache_read_multiplier"]))  # fmt: skip


def usage_cost(model: str, usage: dict[str, Any]) -> float:
    """US$ for one response's ``usage`` (input, cache writes, cache reads, output)."""
    p = price(model)
    return (
        (usage.get("input_tokens") or 0) * p.input
        + (usage.get("cache_creation_input_tokens") or 0) * p.cache_write
        + (usage.get("cache_read_input_tokens") or 0) * p.cache_read
        + (usage.get("output_tokens") or 0) * p.output
    ) / 1e6


def worst_case(models: list[str], input_tokens: int, max_tokens: int) -> float:
    """The most a call can cost on any of ``models`` (the designer and its fallback): every input token
    written to the cache (the dearest input rate) plus ``max_tokens`` of output."""
    return max((input_tokens * max(p.input, p.cache_write) + max_tokens * p.output) / 1e6
               for p in map(price, models))  # fmt: skip
