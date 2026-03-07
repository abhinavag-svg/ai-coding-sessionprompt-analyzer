from __future__ import annotations

from statistics import median
from typing import Any, Dict, List
from .scoring_config import ScoringConfig


def _dominant_model(session_features: Dict[str, Any]) -> str:
    breakdown = session_features.get("model_usage_breakdown") or {}
    best = ("unknown", -1)
    for model, row in breakdown.items():
        turns = int((row or {}).get("turns", 0) or 0)
        if turns > best[1]:
            best = (str(model), turns)
    return best[0]


def compute_cost_rate_usd_per_token(
    turn_features: List[Dict[str, Any]],
    session_features: Dict[str, Any],
    config: ScoringConfig | None = None,
) -> Dict[str, Any]:
    """
    Compute a session-level USD-per-incremental-token rate with an explicit fallback chain.
    """
    cfg = config or ScoringConfig()

    per_turn_rates: List[float] = []
    for t in turn_features:
        if not t.get("is_assistant_turn"):
            continue
        tokens = int(t.get("tokens", 0) or 0)
        cost = float(t.get("turn_cost", 0.0) or 0.0)
        if tokens > 0 and cost > 0:
            per_turn_rates.append(cost / tokens)

    if len(per_turn_rates) >= 50:
        rate = float(median(per_turn_rates))
        return {"usd_per_token": rate, "source": "assistant_turn_median", "confidence": "high"}

    total_cost = float(session_features.get("total_cost", 0.0) or 0.0)
    total_tokens = int(session_features.get("total_tokens", 0) or 0)
    if total_cost > 0.0 and total_tokens > 0:
        return {"usd_per_token": float(total_cost / total_tokens), "source": "session_total", "confidence": "estimated"}

    dominant_model = _dominant_model(session_features)
    # Attempt a pricing-derived proxy: treat (input+output)/2 as a blended token rate.
    split_rates = None
    try:
        # Use default pricing tables via derive_split_cost call path. We just need rates.
        from .constants import DEFAULT_MODEL_PRICING_PER_1K

        model_lower = str(dominant_model).lower()
        matched = None
        for key, rates in DEFAULT_MODEL_PRICING_PER_1K.items():
            if key in model_lower:
                matched = rates
                break
        if matched and float(matched.get("input", 0.0)) > 0 and float(matched.get("output", 0.0)) > 0:
            blended_per_1k = (float(matched["input"]) + float(matched["output"])) / 2.0
            return {"usd_per_token": float(blended_per_1k / 1000.0), "source": "pricing_blended_proxy", "confidence": "low"}
    except Exception:
        pass

    return {
        "usd_per_token": float(cfg.recoverable_cost_floor_baseline_usd_per_token),
        "source": "hardcoded_fallback",
        "confidence": "low",
    }
