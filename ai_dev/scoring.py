from __future__ import annotations

from typing import Any, Dict, List

from .scoring_config import ScoringConfig


WEIGHT_SPECIFICITY = 30.0
WEIGHT_CORRECTION = 25.0
WEIGHT_CONTEXT_SCOPE = 30.0
WEIGHT_MODEL_EFFICIENCY = 15.0


def _clamp(value: float, lo: float = 0.0, hi: float = 25.0) -> float:
    return max(lo, min(hi, value))


def compute_specificity_score(features: Dict[str, Any], config: ScoringConfig | None = None) -> float:
    cfg = config or ScoringConfig()
    session = features["session_features"]
    total_turns = max(session["total_turns"], 1)

    file_path_bonus = min(cfg.file_path_bonus_max, session["file_path_mentions"] * cfg.file_path_bonus_multiplier)
    function_bonus = min(cfg.function_bonus_max, session["function_mentions"] * cfg.function_bonus_multiplier)
    constraint_bonus = min(cfg.constraint_bonus_max, session["repeated_phrase_count"] * cfg.constraint_bonus_multiplier)
    vague_penalty = min(cfg.vague_penalty_max, session["vague_turn_ratio"] * cfg.vague_penalty_multiplier)

    raw = cfg.specificity_base_score + file_path_bonus + function_bonus + constraint_bonus - vague_penalty
    return _clamp(raw)


def compute_correction_score(features: Dict[str, Any], config: ScoringConfig | None = None) -> float:
    cfg = config or ScoringConfig()
    session = features["session_features"]
    user_turn_count = int(session.get("user_turn_count", 0))
    if user_turn_count == 0:
        return 12.5

    prompt_ratio = float(session.get("prompt_rework_ratio", 0.0))
    model_ratio = float(session.get("model_rework_ratio", 0.0))
    unknown_ratio = float(session.get("unknown_rework_ratio", 0.0))
    repeated_phrase_count = int(session.get("repeated_phrase_count", 0))

    deduction = min(10.0, prompt_ratio * cfg.prompt_rework_multiplier)
    deduction += min(12.0, model_ratio * cfg.model_rework_multiplier)
    deduction += min(5.0, unknown_ratio * cfg.unknown_rework_multiplier)
    deduction += min(4.0, repeated_phrase_count * cfg.repeated_phrase_penalty)

    score = 25.0 - deduction

    combined_rework_ratio = prompt_ratio + model_ratio + unknown_ratio
    if combined_rework_ratio > cfg.high_rework_cap_threshold:
        score = min(score, cfg.high_rework_cap_score)
    elif combined_rework_ratio > cfg.mid_rework_cap_threshold:
        score = min(score, cfg.mid_rework_cap_score)

    return _clamp(score)


def compute_context_scope_score(features: Dict[str, Any], config: ScoringConfig | None = None) -> float:
    cfg = config or ScoringConfig()
    session = features["session_features"]
    avg_tokens_turn = float(session.get("tokens_per_turn_avg", 0.0))
    median_tokens_turn = float(session.get("tokens_per_turn_median", 0.0))
    p90_tokens_turn = float(session.get("tokens_per_turn_p90", 0.0))
    over_40k_ratio = float(session.get("over_40k_turn_ratio", 0.0))

    if avg_tokens_turn <= cfg.tokens_excellent_max:
        score = 25.0
    elif avg_tokens_turn <= cfg.tokens_normal_max:
        score = 25.0 - ((avg_tokens_turn - cfg.tokens_excellent_max) / (cfg.tokens_normal_max - cfg.tokens_excellent_max)) * cfg.avg_band_normal_penalty
    elif avg_tokens_turn <= cfg.tokens_heavy_max:
        score = 20.0 - ((avg_tokens_turn - cfg.tokens_normal_max) / (cfg.tokens_heavy_max - cfg.tokens_normal_max)) * cfg.avg_band_heavy_penalty
    else:
        score = 12.0 - min(cfg.avg_band_over_penalty, ((avg_tokens_turn - cfg.tokens_heavy_max) / cfg.tokens_heavy_max) * cfg.avg_band_over_penalty)

    score -= min(cfg.median_penalty_multiplier, max(0.0, (median_tokens_turn - cfg.median_penalty_threshold) / cfg.median_penalty_threshold) * cfg.median_penalty_multiplier)
    score -= min(cfg.p90_penalty_multiplier, max(0.0, (p90_tokens_turn - cfg.p90_penalty_threshold) / cfg.p90_penalty_threshold) * cfg.p90_penalty_multiplier)
    score -= min(6.0, over_40k_ratio * cfg.over_40k_penalty_multiplier)
    score -= session["file_explosion_events"] * cfg.file_explosion_penalty
    score -= max(0.0, (session["avg_tool_calls"] - cfg.tool_call_baseline) * cfg.tool_call_penalty_per_extra)

    if over_40k_ratio >= cfg.over_40k_cap_ratio:
        score = min(score, cfg.over_40k_cap_score)
    if p90_tokens_turn > cfg.p90_cap_threshold:
        score = min(score, cfg.p90_cap_score)

    return _clamp(score)


def compute_model_efficiency_score(features: Dict[str, Any], rules: List[Dict[str, str]], config: ScoringConfig | None = None) -> float:  # noqa: ARG001
    deduction = 0.0
    rule_ids = {r["rule_id"] for r in rules}
    if "model_overkill" in rule_ids:
        deduction += 8.0
    if "high_correction_loop" in rule_ids:
        deduction += 5.0
    return _clamp(25.0 - deduction)


def _grade_band(total: float) -> str:
    if total >= 90:
        return "A"
    if total >= 80:
        return "B"
    if total >= 70:
        return "C"
    if total >= 60:
        return "D"
    return "F"


def _diagnosis(scores: Dict[str, float]) -> str:
    weakest_key = min(scores, key=scores.get)
    labels = {
        "specificity": "Prompt specificity is the main bottleneck.",
        "correction": "High correction churn is reducing efficiency.",
        "context_scope": "Context scope is too broad or noisy.",
        "model_efficiency": "Model selection strategy is likely over-spending.",
    }
    return labels[weakest_key]


def compute_scores(features: Dict[str, Any], rules: List[Dict[str, str]], config: ScoringConfig | None = None) -> Dict[str, Any]:
    cfg = config or ScoringConfig()
    specificity = compute_specificity_score(features, cfg)
    correction = compute_correction_score(features, cfg)
    context_scope = compute_context_scope_score(features, cfg)
    model_efficiency = compute_model_efficiency_score(features, rules, cfg)

    composite = (
        (specificity / 25.0) * WEIGHT_SPECIFICITY
        + (correction / 25.0) * WEIGHT_CORRECTION
        + (context_scope / 25.0) * WEIGHT_CONTEXT_SCOPE
        + (model_efficiency / 25.0) * WEIGHT_MODEL_EFFICIENCY
    )
    score_map = {
        "specificity": round(specificity, 2),
        "correction": round(correction, 2),
        "context_scope": round(context_scope, 2),
        "model_efficiency": round(model_efficiency, 2),
    }

    weighted_breakdown = {
        "specificity": round((specificity / 25.0) * WEIGHT_SPECIFICITY, 2),
        "correction": round((correction / 25.0) * WEIGHT_CORRECTION, 2),
        "context_scope": round((context_scope / 25.0) * WEIGHT_CONTEXT_SCOPE, 2),
        "model_efficiency": round((model_efficiency / 25.0) * WEIGHT_MODEL_EFFICIENCY, 2),
    }

    return {
        "subscores": score_map,
        "composite": round(composite, 2),
        "grade": _grade_band(composite),
        "diagnosis": _diagnosis(score_map),
        "weights": {
            "specificity": WEIGHT_SPECIFICITY,
            "correction": WEIGHT_CORRECTION,
            "context_scope": WEIGHT_CONTEXT_SCOPE,
            "model_efficiency": WEIGHT_MODEL_EFFICIENCY,
        },
        "weighted_breakdown": weighted_breakdown,
    }
