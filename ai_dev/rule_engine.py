from __future__ import annotations

from typing import Any, Dict, List


EXPENSIVE_MODEL_HINTS = (
    "gpt-4",
    "o1",
    "o3",
    "opus",
    "sonnet",
    "gemini-1.5-pro",
)


def _rule(rule_id: str, severity: str, description: str, impact_estimate: str) -> Dict[str, str]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "description": description,
        "impact_estimate": impact_estimate,
    }


def evaluate_rules(features: Dict[str, Any]) -> List[Dict[str, str]]:
    session = features["session_features"]
    rules: List[Dict[str, str]] = []

    if session["file_explosion_events"] > 0:
        severity = "high" if session["file_explosion_events"] >= 3 else "medium"
        rules.append(
            _rule(
                "file_explosion",
                severity,
                f"Detected {session['file_explosion_events']} turns with more than 5 file reads.",
                "High context churn and unnecessary token spend.",
            )
        )

    model_usage = session["model_usage_breakdown"]
    total_turns = max(session["total_turns"], 1)
    expensive_turns = 0
    for model, row in model_usage.items():
        if any(tag in model.lower() for tag in EXPENSIVE_MODEL_HINTS):
            expensive_turns += row["turns"]

    if expensive_turns / total_turns > 0.6 and session["total_tokens"] < 80000:
        rules.append(
            _rule(
                "model_overkill",
                "medium",
                "Expensive models dominate usage while total workload appears moderate.",
                "Could reduce cost by routing simple turns to cheaper models.",
            )
        )

    if session["correction_ratio"] > 0.35:
        rules.append(
            _rule(
                "high_correction_loop",
                "high",
                f"Correction ratio is {session['correction_ratio']:.2f}, indicating frequent rework.",
                "Lower quality prompts can increase cycle time and token cost.",
            )
        )

    if session["repeated_phrase_count"] >= 3:
        rules.append(
            _rule(
                "repeated_constraint",
                "medium",
                "Repeated user constraints detected across turns.",
                "Assistant likely missed requirements; prompt specificity may be low.",
            )
        )

    if session["vague_turn_ratio"] > 0.25:
        rules.append(
            _rule(
                "vague_prompt",
                "medium",
                f"Vague language appears in {session['vague_turn_ratio']:.0%} of turns.",
                "Can increase ambiguity and correction loops.",
            )
        )

    return rules
