from __future__ import annotations

from typing import Any, Dict, List

from .scoring_config import ScoringConfig


PRODUCTIVE_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "Bash", "NotebookEdit"})


def compute_convergence_v2(turn_features: List[Dict[str, Any]], config: ScoringConfig | None = None) -> Dict[str, Any]:
    cfg = config or ScoringConfig()

    scorable = [t for t in turn_features if t.get("v2_is_scorable_turn")]
    user_turns = [t for t in scorable if t.get("is_user_turn")]
    assistant_turns = [t for t in scorable if t.get("is_assistant_turn")]

    def _assistant_used_productive(t: Dict[str, Any]) -> bool:
        if not t.get("is_assistant_turn"):
            return False
        for nm in (t.get("tool_names") or []):
            if nm in PRODUCTIVE_TOOLS:
                return True
        return False

    # Gate 1: turns (user) to first productive tool use, measured from first user turn.
    first_user_idx = None
    for i, t in enumerate(scorable):
        if t.get("is_user_turn"):
            first_user_idx = i
            break
    first_prod_idx = None
    for i, t in enumerate(scorable):
        if _assistant_used_productive(t):
            first_prod_idx = i
            break

    user_turns_to_first_prod = None
    if first_user_idx is not None and first_prod_idx is not None and first_prod_idx >= first_user_idx:
        user_turns_to_first_prod = sum(1 for t in scorable[first_user_idx : first_prod_idx + 1] if t.get("is_user_turn"))

    # Between first and last productive tool use.
    prod_indices = [i for i, t in enumerate(scorable) if _assistant_used_productive(t)]
    first_prod = min(prod_indices) if prod_indices else None
    last_prod = max(prod_indices) if prod_indices else None

    correction_between = 0
    if first_prod is not None and last_prod is not None and last_prod >= first_prod:
        for t in scorable[first_prod : last_prod + 1]:
            if t.get("is_user_turn") and (t.get("v2_correction") or {}).get("confidence") in {"high", "medium"}:
                correction_between += 1

    # Gate 3 settlement: after last productive tool, look for >=2 "settlement" user turns.
    gate3_status = "no_productive_tool"
    settlement_turns = 0
    if last_prod is not None:
        gate3_status = "unsettled"
        for t in scorable[last_prod + 1 :]:
            if not t.get("is_user_turn"):
                continue
            corr = (t.get("v2_correction") or {}).get("confidence") in {"high", "medium", "low"}
            corr_none = (t.get("v2_correction") or {}).get("confidence") == "none"
            if t.get("v2_affirmation_language"):
                settlement_turns += 1
            else:
                tok = int(t.get("v2_tokens_for_heuristics", 0) or 0)
                if tok <= cfg.gate3_settlement_low_token_threshold and corr_none and not bool(t.get("v2_extension_language")):
                    settlement_turns += 1
                else:
                    # A follow-up question or extension makes Gate 3 inconclusive rather than failed.
                    gate3_status = "inconclusive"
                    break
            if settlement_turns >= 2:
                gate3_status = "settled"
                break

        if gate3_status == "unsettled":
            # If the session ends immediately after correction, treat as abandoned.
            last_user = next((t for t in reversed(scorable) if t.get("is_user_turn")), None)
            if last_user and (last_user.get("v2_correction") or {}).get("confidence") in {"high", "medium"}:
                gate3_status = "abandoned"

    # Session shape classification.
    shape = "Clean"
    if first_prod is None and user_turns:
        shape = "Exploration-Heavy"
    if correction_between >= 3:
        shape = "Correction-Heavy"
    if gate3_status == "abandoned":
        shape = "Abandoned"

    return {
        "gate1_user_turns_to_first_productive": user_turns_to_first_prod,
        "gate2_corrections_between_productive": correction_between,
        "gate3_status": gate3_status,  # settled | inconclusive | unsettled | abandoned | no_productive_tool
        "shape": shape,
        "first_productive_turn_index": scorable[first_prod].get("turn_index") if first_prod is not None else None,
        "last_productive_turn_index": scorable[last_prod].get("turn_index") if last_prod is not None else None,
    }

