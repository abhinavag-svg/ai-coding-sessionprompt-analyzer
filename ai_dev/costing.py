from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

from .constants import DEFAULT_MODEL_PRICING_PER_1K, FALLBACK_MODEL_BLENDED_PER_1K
from .models import CostMode, CostSource, UsageBuckets


def load_pricing_file(pricing_file: Path) -> tuple[Dict[str, Dict[str, float]], Dict[str, float]]:
    data = json.loads(pricing_file.read_text(encoding="utf-8"))
    split_rates = data.get("split_per_1k", {}) if isinstance(data, dict) else {}
    blended_rates = data.get("blended_per_1k", {}) if isinstance(data, dict) else {}

    normalized_split: Dict[str, Dict[str, float]] = {}
    for model_key, rates in split_rates.items():
        if not isinstance(model_key, str) or not isinstance(rates, dict):
            continue
        normalized_split[model_key.lower()] = {
            "input": float(rates.get("input", 0.0) or 0.0),
            "output": float(rates.get("output", 0.0) or 0.0),
            "cache_write": float(rates.get("cache_write", 0.0) or 0.0),
            "cache_read": float(rates.get("cache_read", 0.0) or 0.0),
        }

    normalized_blended: Dict[str, float] = {}
    for model_key, rate in blended_rates.items():
        if isinstance(model_key, str) and isinstance(rate, (int, float)):
            normalized_blended[model_key.lower()] = float(rate)

    return normalized_split, normalized_blended


def _find_split_rates(model: str, split_pricing: Dict[str, Dict[str, float]] | None = None) -> Dict[str, float] | None:
    model_lower = model.lower()
    price_table = split_pricing or DEFAULT_MODEL_PRICING_PER_1K
    for key, rates in price_table.items():
        if key in model_lower:
            return rates
    return None


def _find_blended_rate(model: str, blended_pricing: Dict[str, float] | None = None) -> float:
    model_lower = model.lower()
    price_table = blended_pricing or FALLBACK_MODEL_BLENDED_PER_1K
    for key, rate in price_table.items():
        if key in model_lower:
            return rate
    return 0.0


def derive_split_cost(model: str, usage: UsageBuckets, split_pricing: Dict[str, Dict[str, float]] | None = None) -> float | None:
    rates = _find_split_rates(model, split_pricing)
    if not rates:
        return None
    return (
        (usage.input_tokens / 1000.0) * rates["input"]
        + (usage.output_tokens / 1000.0) * rates["output"]
        + (usage.cache_write_tokens / 1000.0) * rates["cache_write"]
        + (usage.cache_read_tokens / 1000.0) * rates["cache_read"]
    )


def derive_fallback_cost(model: str, usage: UsageBuckets, blended_pricing: Dict[str, float] | None = None) -> float | None:
    rate = _find_blended_rate(model, blended_pricing)
    if rate <= 0:
        return None
    return (usage.total_tokens / 1000.0) * rate


def estimate_no_cache_cost(
    model: str,
    usage: UsageBuckets,
    split_pricing: Dict[str, Dict[str, float]] | None = None,
) -> float | None:
    """
    Estimate what the request would have cost without prompt caching.

    Heuristic: treat cache read/write tokens as regular *input* tokens and price them
    at the model's normal input rate (keeping output tokens unchanged).

    This requires split pricing (input/output); if rates are unavailable, return None.
    """
    rates = _find_split_rates(model, split_pricing)
    if not rates:
        return None

    no_cache_input = usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens
    return (
        (no_cache_input / 1000.0) * rates["input"]
        + (usage.output_tokens / 1000.0) * rates["output"]
    )


def resolve_cost(
    mode: CostMode,
    provider_cost: float | None,
    model: str,
    usage: UsageBuckets,
    split_pricing: Dict[str, Dict[str, float]] | None = None,
    blended_pricing: Dict[str, float] | None = None,
) -> Tuple[float, CostSource]:
    if mode == CostMode.REPORTED_ONLY:
        if provider_cost is not None:
            return provider_cost, CostSource.REPORTED
        return 0.0, CostSource.UNKNOWN

    if mode == CostMode.DERIVED_ONLY:
        split_cost = derive_split_cost(model, usage, split_pricing)
        if split_cost is not None:
            return split_cost, CostSource.DERIVED_SPLIT
        fallback_cost = derive_fallback_cost(model, usage, blended_pricing)
        if fallback_cost is not None:
            return fallback_cost, CostSource.DERIVED_FALLBACK
        return 0.0, CostSource.UNKNOWN

    if provider_cost is not None:
        return provider_cost, CostSource.REPORTED

    split_cost = derive_split_cost(model, usage, split_pricing)
    if split_cost is not None:
        return split_cost, CostSource.DERIVED_SPLIT

    fallback_cost = derive_fallback_cost(model, usage, blended_pricing)
    if fallback_cost is not None:
        return fallback_cost, CostSource.DERIVED_FALLBACK

    return 0.0, CostSource.UNKNOWN
