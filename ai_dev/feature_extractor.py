from __future__ import annotations

import re
from collections import Counter, defaultdict
from statistics import median
from typing import Any, Dict, List

from .scoring_config import ScoringConfig

FILE_PATH_RE = re.compile(r"(?:[\w./-]+\.(?:py|ts|tsx|js|jsx|java|go|rs|md|json|yaml|yml|toml))")
FUNCTION_RE = re.compile(r"\b(?:def|function|class|interface|struct)\s+[A-Za-z_][A-Za-z0-9_]*\b")
VAGUE_PHRASES = (
    "fix this",
    "make it better",
    "improve this",
    "optimize",
    "do it",
    "handle it",
    "something is wrong",
    "issue",
)
CORRECTION_PHRASES = (
    "that is wrong",
    "not what i asked",
    "try again",
    "incorrect",
    "you missed",
    "still failing",
    "redo",
    "fix it",
)

PROMPT_INDUCED_REWORK_PHRASES = (
    "to clarify",
    "i meant",
    "more specifically",
    "be specific",
    "constraints",
    "do not change",
    "only change",
    "missing requirement",
)

MODEL_INDUCED_REWORK_PHRASES = (
    "hallucinat",
    "you are wrong",
    "still wrong",
    "doesn't work",
    "does not work",
    "failed test",
    "error persists",
    "you ignored",
    "not correct",
)

VAGUE_RE = re.compile(r"\b(something|anything|stuff|somehow|maybe|etc)\b", re.IGNORECASE)
CORRECTION_RE = re.compile(r"\b(wrong|incorrect|failed|doesn.?t work|broken|fix)\b", re.IGNORECASE)
ACCEPTANCE_RE = re.compile(r"\b(done when|acceptance criteria|must|should|expected|verify|tests?)\b", re.IGNORECASE)

def _percentile(values: List[int], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * percentile
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = rank - lower_index
    lower_val = ordered[lower_index]
    upper_val = ordered[upper_index]
    return float(lower_val + (upper_val - lower_val) * fraction)

def _safe_text(turn: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("text", "content", "prompt", "message"):
        value = turn.get(key)
        if isinstance(value, str):
            parts.append(value)
    if not parts and isinstance(turn.get("input"), str):
        parts.append(turn["input"])

    message = turn.get("message")
    if isinstance(message, dict):
        if isinstance(message.get("content"), str):
            parts.append(message["content"])
        elif isinstance(message.get("content"), list):
            for item in message["content"]:
                if isinstance(item, dict):
                    text_value = item.get("text")
                    if isinstance(text_value, str):
                        parts.append(text_value)

    return "\n".join(parts).strip()

def _count_phrase_hits(text: str, phrases: tuple[str, ...]) -> int:
    return sum(1 for phrase in phrases if phrase in text)

def _classify_rework(text_lower: str) -> str:
    prompt_hits = _count_phrase_hits(text_lower, PROMPT_INDUCED_REWORK_PHRASES)
    model_hits = _count_phrase_hits(text_lower, MODEL_INDUCED_REWORK_PHRASES)
    if prompt_hits == 0 and model_hits == 0:
        return "none"
    if prompt_hits > model_hits:
        return "prompt"
    if model_hits > prompt_hits:
        return "model"
    return "unknown"

def _is_user_turn(turn: Dict[str, Any]) -> bool:
    role = str(turn.get("role", "")).lower()
    turn_type = str(turn.get("type", "")).lower()
    message = turn.get("message")
    if isinstance(message, dict):
        message_role = str(message.get("role", "")).lower()
        if message_role:
            role = message_role
    return role == "user" or "user" in turn_type


def _is_assistant_turn(turn: Dict[str, Any]) -> bool:
    role = str(turn.get("role", "")).lower()
    turn_type = str(turn.get("type", "")).lower()
    message = turn.get("message")
    if isinstance(message, dict):
        message_role = str(message.get("role", "")).lower()
        if message_role:
            role = message_role
    return role == "assistant" or "assistant" in turn_type

def extract_turn_features(turn: Dict[str, Any], index: int) -> Dict[str, Any]:
    text = _safe_text(turn)
    text_lower = text.lower()

    file_paths = FILE_PATH_RE.findall(text)
    func_mentions = FUNCTION_RE.findall(text)

    vague_hits = [phrase for phrase in VAGUE_PHRASES if phrase in text_lower]
    correction_hits = [phrase for phrase in CORRECTION_PHRASES if phrase in text_lower]
    rework_class = _classify_rework(text_lower)
    correction_language = len(correction_hits) > 0 or rework_class != "none"

    raw_tool_calls = turn.get("tool_calls")
    tool_calls: List[Any] = raw_tool_calls if isinstance(raw_tool_calls, list) else []
    tool_names: List[str] = []
    file_reads = 0
    edits = 0
    writes = 0
    test_commands = 0
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        tool_name = str(call.get("name") or call.get("tool_name") or call.get("type") or "").strip()
        if not tool_name:
            continue
        tool_names.append(tool_name)
        tool_lower = tool_name.lower()
        if tool_lower == "read":
            file_reads += 1
        if tool_lower == "edit":
            edits += 1
        if tool_lower == "write":
            writes += 1
        if tool_lower == "bash":
            inp = call.get("input")
            if isinstance(inp, dict):
                cmd = str(inp.get("command") or inp.get("cmd") or "").lower()
                if any(tok in cmd for tok in ("pytest", "npm test", "pnpm test", "yarn test", "bun test", "go test", "cargo test", "mix test")):
                    test_commands += 1

    turn_cost = float(turn.get("cost", 0.0) or 0.0)
    no_cache_cost = float(turn.get("no_cache_cost", 0.0) or 0.0) if "no_cache_cost" in turn else 0.0
    cache_savings = float(turn.get("cache_savings", 0.0) or 0.0) if "cache_savings" in turn else 0.0
    tokens = int(turn.get("tokens", 0) or 0)
    tokens_effective = int(turn.get("tokens_effective", 0) or 0)
    cache_read_tokens = int(turn.get("cache_read_tokens", 0) or 0)
    cache_write_tokens = int(turn.get("cache_write_tokens", 0) or 0)
    model = str(turn.get("model", "unknown"))

    is_user_turn = _is_user_turn(turn)
    is_assistant_turn = _is_assistant_turn(turn)
    is_scored_turn = is_user_turn or is_assistant_turn

    return {
        "turn_index": index,
        "uuid": str(turn.get("_uuid", "")),
        "timestamp": str(turn.get("timestamp", "")),
        "is_user_turn": is_user_turn,
        "is_assistant_turn": is_assistant_turn,
        "is_scored_turn": is_scored_turn,
        "model": model,
        "tokens": tokens,
        "tokens_effective": tokens_effective,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "turn_cost": turn_cost,
        "no_cache_cost": no_cache_cost,
        "cache_savings": cache_savings,
        "tool_call_count": len(tool_calls),
        "file_read_count": file_reads,
        "edit_count": edits,
        "write_count": writes,
        "test_command_count": test_commands,
        "tool_names": tool_names,
        "file_paths": file_paths,
        "function_mentions": func_mentions,
        "acceptance_hits": len(ACCEPTANCE_RE.findall(text)),
        "vague_phrase_count": len(vague_hits),
        "correction_language": correction_language,
        "rework_class": rework_class,
        "text": text,
        "source_file": turn.get("_source_file", ""),
        "agent_type": turn.get("_agent_type", "primary"),
        "agent_id": turn.get("_agent_id", "primary"),
        "session_id": turn.get("sessionId") or turn.get("session_id") or "unknown",
    }

def extract_session_features(turn_features: List[Dict[str, Any]], config: ScoringConfig | None = None) -> Dict[str, Any]:
    cfg = config or ScoringConfig()
    scorable_turns = [t for t in turn_features if t.get("is_scored_turn")]
    total_tokens = sum(int(t["tokens"]) for t in scorable_turns)
    total_effective_tokens = sum(int(t.get("tokens_effective", 0)) for t in scorable_turns)
    total_cache_read_tokens = sum(int(t.get("cache_read_tokens", 0)) for t in scorable_turns)
    total_cache_write_tokens = sum(int(t.get("cache_write_tokens", 0)) for t in scorable_turns)
    total_cost = sum(float(t["turn_cost"]) for t in scorable_turns)
    total_turns = len(scorable_turns)

    largest_turn = max(scorable_turns, key=lambda t: t["tokens"], default=None)

    user_turns = [t for t in scorable_turns if t["is_user_turn"]]
    assistant_turns = [t for t in scorable_turns if t.get("is_assistant_turn")]
    estimated_no_cache_cost = sum(float(t.get("no_cache_cost", 0.0)) for t in assistant_turns)
    estimated_cache_savings = sum(float(t.get("cache_savings", 0.0)) for t in assistant_turns)
    no_cache_estimated_turns = sum(1 for t in assistant_turns if float(t.get("no_cache_cost", 0.0)) > 0.0)
    correction_turns = [t for t in user_turns if t["correction_language"]]
    correction_ratio = (len(correction_turns) / len(user_turns)) if user_turns else 0.0
    prompt_rework_turns = [t for t in user_turns if t.get("rework_class") == "prompt"]
    model_rework_turns = [t for t in user_turns if t.get("rework_class") == "model"]
    unknown_rework_turns = [t for t in user_turns if t.get("rework_class") == "unknown"]

    repeated_counter = Counter(
        t["text"].strip().lower() for t in user_turns if t["text"].strip()
    )
    repeated_phrases = [{"text": text, "count": cnt} for text, cnt in repeated_counter.items() if cnt > 1]

    file_explosion_events = sum(1 for t in assistant_turns if t["file_read_count"] > cfg.file_explosion_read_threshold)

    model_usage_breakdown: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"turns": 0, "tokens": 0, "cost": 0.0})
    for t in assistant_turns:
        row = model_usage_breakdown[t["model"]]
        row["turns"] += 1
        row["tokens"] += t["tokens"]
        row["cost"] += t["turn_cost"]

    agent_usage_breakdown: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"turns": 0, "tokens": 0, "cost": 0.0})
    for t in assistant_turns:
        row = agent_usage_breakdown[t["agent_type"]]
        row["turns"] += 1
        row["tokens"] += t["tokens"]
        row["cost"] += t["turn_cost"]

    avg_tool_calls = (sum(int(t["tool_call_count"]) for t in assistant_turns) / len(assistant_turns)) if assistant_turns else 0.0
    tokens_per_turn_series = [int(t["tokens"]) for t in assistant_turns]
    tokens_per_turn_avg = (total_tokens / total_turns) if total_turns else 0.0
    tokens_per_turn_median = median(tokens_per_turn_series) if tokens_per_turn_series else 0.0
    tokens_per_turn_p90 = _percentile(tokens_per_turn_series, 0.9) if tokens_per_turn_series else 0.0
    over_40k_turn_ratio = (
        sum(1 for value in tokens_per_turn_series if value > cfg.expensive_turn_token_threshold) / len(tokens_per_turn_series)
    ) if tokens_per_turn_series else 0.0

    effective_tokens_per_turn_series = [int(t.get("tokens_effective", 0)) for t in assistant_turns]
    effective_tokens_per_turn_avg = (sum(effective_tokens_per_turn_series) / len(effective_tokens_per_turn_series)) if effective_tokens_per_turn_series else 0.0
    effective_tokens_per_turn_median = median(effective_tokens_per_turn_series) if effective_tokens_per_turn_series else 0.0
    effective_tokens_per_turn_p90 = _percentile(effective_tokens_per_turn_series, 0.9) if effective_tokens_per_turn_series else 0.0

    # Prompt windowing: treat a "prompt" as a user turn and attribute downstream spend
    # to assistant turns until the next user turn.
    most_expensive_prompts: List[Dict[str, Any]] = []
    high_quality_prompts: List[Dict[str, Any]] = []
    if user_turns:
        # Use the original scorable order for windowing.
        scorable_by_index = {t["turn_index"]: t for t in scorable_turns}
        user_indices = sorted(t["turn_index"] for t in user_turns)
        assistant_by_index = {t["turn_index"]: t for t in assistant_turns}

        def assistant_window(start_idx: int, end_idx_exclusive: int) -> List[Dict[str, Any]]:
            return [assistant_by_index[i] for i in range(start_idx + 1, end_idx_exclusive) if i in assistant_by_index]

        prompt_rows: List[Dict[str, Any]] = []
        for pos, u_idx in enumerate(user_indices):
            u = scorable_by_index[u_idx]
            next_u_idx = user_indices[pos + 1] if pos + 1 < len(user_indices) else None
            end_idx = (next_u_idx or (max(scorable_by_index.keys()) + 1))
            win = assistant_window(u_idx, end_idx)
            win_cost = sum(float(t["turn_cost"]) for t in win)
            win_tokens = sum(int(t["tokens"]) for t in win)
            win_effective = sum(int(t.get("tokens_effective", 0)) for t in win)
            win_reads = sum(int(t.get("file_read_count", 0)) for t in win)
            win_edits = sum(int(t.get("edit_count", 0)) for t in win)
            win_writes = sum(int(t.get("write_count", 0)) for t in win)
            win_tests = sum(int(t.get("test_command_count", 0)) for t in win)
            win_models: Counter[str] = Counter(t.get("model", "unknown") for t in win)

            next_user = scorable_by_index.get(next_u_idx) if next_u_idx else None
            next_user_is_correction = bool(next_user and next_user.get("correction_language"))

            prompt_text = str(u.get("text") or "")
            fp_count = len(u.get("file_paths") or [])
            sym_count = len(u.get("function_mentions") or [])
            acceptance_hits = int(u.get("acceptance_hits", 0) or 0)
            vague_count = int(u.get("vague_phrase_count", 0) or 0)

            reasons: List[str] = []
            if win_cost >= 0.25:
                reasons.append(f"high downstream cost (${win_cost:.2f})")
            if win_tokens >= max(cfg.expensive_turn_token_threshold, int(tokens_per_turn_p90 or 0)):
                reasons.append(f"high downstream incremental tokens ({win_tokens})")
            if win_reads >= 10:
                reasons.append(f"many file reads ({win_reads})")
            if next_user_is_correction:
                reasons.append("next user turn indicates correction/rework")

            suggestions: List[str] = []
            if fp_count == 0:
                suggestions.append("Name the exact file paths to touch (avoid broad context pulls).")
            if sym_count == 0:
                suggestions.append("Reference specific symbols (functions/classes) to target edits precisely.")
            if acceptance_hits == 0:
                suggestions.append("Add acceptance criteria / definition of done (tests to run, expected behavior).")
            if vague_count > 0:
                suggestions.append("Remove vague language; state concrete constraints and outputs.")
            if win_tokens > 20000:
                suggestions.append("Reduce context churn: include only the minimal relevant context and point to files/symbols.")
            if next_user_is_correction:
                suggestions.append("Front-load constraints and edge cases to prevent correction loops.")

            suggested_rewrite = (
                "Goal: <what to change>\n"
                "Files: <exact paths>\n"
                "Constraints: <what must not change>\n"
                "Acceptance: <tests/expected output>\n"
                "Output: Provide a patch/diff and explain key decisions briefly."
            )

            prompt_rows.append(
                {
                    "turn_index": u_idx,
                    "prompt_uuid": u.get("uuid", ""),
                    "timestamp": u.get("timestamp", "unknown"),
                    "session_id": u.get("session_id", "unknown"),
                    "model": u.get("model", "unknown"),
                    "prompt_text": prompt_text,
                    "prompt_snippet": (prompt_text.strip().replace("\n", " ")[:160] + ("..." if len(prompt_text) > 160 else "")),
                    "downstream_cost": round(win_cost, 6),
                    "downstream_tokens": win_tokens,
                    "downstream_effective_tokens": win_effective,
                    "downstream_turns": len(win),
                    "downstream_models": dict(win_models),
                    "downstream_file_reads": win_reads,
                    "downstream_edits": win_edits,
                    "downstream_writes": win_writes,
                    "downstream_tests": win_tests,
                    "reasons": reasons or ["high absolute spend"],
                    "suggestions": suggestions,
                    "suggested_rewrite": suggested_rewrite,
                    "specificity_signals": {"file_paths": fp_count, "symbols": sym_count, "acceptance_hits": acceptance_hits, "vague_hits": vague_count},
                    "next_user_correction": next_user_is_correction,
                }
            )

        most_expensive_prompts = sorted(prompt_rows, key=lambda r: float(r["downstream_cost"]), reverse=True)[:10]

        # High-quality prompts: exemplars to copy (not just cheap).
        def clamp01(x: float) -> float:
            return max(0.0, min(1.0, x))

        quality_rows: List[Dict[str, Any]] = []
        for row in prompt_rows:
            spec = row["specificity_signals"]
            specificity = clamp01((spec["file_paths"] * 0.25) + (spec["symbols"] * 0.1) + (spec["acceptance_hits"] * 0.2) - (spec["vague_hits"] * 0.2))
            productive = (row["downstream_edits"] + row["downstream_writes"] + row["downstream_tests"]) > 0
            # Outcome: productive work + no immediate correction.
            outcome = 1.0 if productive else 0.2
            if row["next_user_correction"]:
                outcome = max(0.0, outcome - 0.6)
            if row["downstream_turns"] > 10:
                outcome = max(0.0, outcome - 0.2)

            cost = float(row["downstream_cost"])
            tokens = float(row["downstream_tokens"])
            cost_score = clamp01(1.0 - min(1.0, cost / 1.0))  # $1 scaling
            token_score = clamp01(1.0 - min(1.0, tokens / 20000.0))
            efficiency = (cost_score + token_score) / 2.0

            quality = (0.5 * specificity) + (0.3 * outcome) + (0.2 * efficiency)
            if not productive:
                continue  # avoid "high quality" no-ops

            why: List[str] = []
            if spec["file_paths"] > 0:
                why.append("mentions file paths")
            if spec["symbols"] > 0:
                why.append("mentions symbols")
            if spec["acceptance_hits"] > 0:
                why.append("includes acceptance/testing language")
            if not row["next_user_correction"]:
                why.append("no immediate correction turn")
            if row["downstream_cost"] < 0.25:
                why.append("low downstream cost")

            quality_rows.append({**row, "quality_score": round(quality, 4), "why": why})

        high_quality_prompts = sorted(quality_rows, key=lambda r: float(r["quality_score"]), reverse=True)[:10]

    return {
        "total_turns": total_turns,
        "user_turn_count": len(user_turns),
        "total_tokens": total_tokens,
        "total_effective_tokens": total_effective_tokens,
        "total_cache_read_tokens": total_cache_read_tokens,
        "total_cache_write_tokens": total_cache_write_tokens,
        "total_cost": total_cost,
        "estimated_no_cache_cost": round(estimated_no_cache_cost, 6),
        "estimated_cache_savings": round(estimated_cache_savings, 6),
        "no_cache_estimate_turns": no_cache_estimated_turns,
        "assistant_turn_count": len(assistant_turns),
        "cost_per_turn": (total_cost / total_turns) if total_turns else 0.0,
        "largest_turn": largest_turn,
        "correction_count": len(correction_turns),
        "correction_ratio": correction_ratio,
        "prompt_rework_count": len(prompt_rework_turns),
        "model_rework_count": len(model_rework_turns),
        "unknown_rework_count": len(unknown_rework_turns),
        "prompt_rework_ratio": (len(prompt_rework_turns) / len(user_turns)) if user_turns else 0.0,
        "model_rework_ratio": (len(model_rework_turns) / len(user_turns)) if user_turns else 0.0,
        "unknown_rework_ratio": (len(unknown_rework_turns) / len(user_turns)) if user_turns else 0.0,
        "repeated_phrase_count": len(repeated_phrases),
        "repeated_phrases": repeated_phrases[:5],
        "file_explosion_events": file_explosion_events,
        "model_usage_breakdown": dict(model_usage_breakdown),
        "agent_usage_breakdown": dict(agent_usage_breakdown),
        "avg_tool_calls": avg_tool_calls,
        "tokens_per_turn_avg": tokens_per_turn_avg,
        "tokens_per_turn_median": tokens_per_turn_median,
        "tokens_per_turn_p90": tokens_per_turn_p90,
        "over_40k_turn_ratio": over_40k_turn_ratio,
        "effective_tokens_per_turn_avg": effective_tokens_per_turn_avg,
        "effective_tokens_per_turn_median": effective_tokens_per_turn_median,
        "effective_tokens_per_turn_p90": effective_tokens_per_turn_p90,
        "vague_turn_ratio": (
            sum(1 for t in user_turns if t["vague_phrase_count"] > 0) / len(user_turns)
        ) if user_turns else 0.0,
        "file_path_mentions": sum(len(t["file_paths"]) for t in user_turns),
        "function_mentions": sum(len(t["function_mentions"]) for t in user_turns),
        "most_expensive_prompts": most_expensive_prompts,
        "high_quality_prompts": high_quality_prompts,
    }

def _build_expensive_turns(records: List[Dict[str, Any]], p90_tokens: float, top_n: int = 10, config: ScoringConfig | None = None) -> List[Dict[str, Any]]:
    cfg = config or ScoringConfig()
    ranked = sorted(records, key=lambda r: float(r.get("cost", 0.0)), reverse=True)[:top_n]
    out: List[Dict[str, Any]] = []

    for r in ranked:
        text = str(r.get("user_text") or r.get("prompt") or r.get("text") or "")
        tokens = int(r.get("tokens", 0) or 0)
        cost = float(r.get("cost", 0.0) or 0.0)

        affected: List[str] = []
        reasons: List[str] = []

        if tokens >= max(cfg.expensive_turn_token_threshold, int(p90_tokens)):
            affected.append("context_scope")
            reasons.append(f"high tokens ({tokens})")
        if cost >= cfg.expensive_turn_cost_threshold:
            affected.append("model_efficiency")
            reasons.append(f"high turn cost (${cost:.4f})")
        if CORRECTION_RE.search(text):
            affected.append("correction")
            reasons.append("correction language detected")
        if VAGUE_RE.search(text):
            affected.append("specificity")
            reasons.append("vague language detected")

        out.append({
            "timestamp": r.get("timestamp", "unknown"),
            "session_id": r.get("sessionId") or r.get("session_id") or "unknown",
            "model": r.get("model", "unknown"),
            "cost": round(cost, 6),
            "tokens": tokens,
            "affected_categories": sorted(set(affected)) or ["none"],
            "reason": "; ".join(reasons) if reasons else "high absolute spend",
            "snippet": _snippet(text),
        })
    return out

def _snippet(text: str, n: int = 120) -> str:
    t = (text or "").strip().replace("\n", " ")
    return t[:n] + ("..." if len(t) > n else "")

def build_feature_bundle(records: List[Dict[str, Any]], config: ScoringConfig | None = None) -> Dict[str, Any]:
    cfg = config or ScoringConfig()
    turn_features = [extract_turn_features(r, i + 1) for i, r in enumerate(records)]
    session_features = extract_session_features(turn_features, cfg)
    p90_tokens = float(session_features.get("tokens_per_turn_p90", 0.0))
    expensive_turns = _build_expensive_turns(records, p90_tokens=p90_tokens, top_n=10, config=cfg)
    session_features["expensive_turns"] = expensive_turns

    return {
        "turn_features": turn_features,
        "session_features": session_features,
    }
