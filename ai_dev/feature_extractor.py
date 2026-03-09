from __future__ import annotations

import re
from collections import Counter, defaultdict
from statistics import median
from typing import Any, Dict, List

from .lexicon import (
    AFFIRMATION_PHRASES,
    EXPLICIT_CORRECTION_PHRASES,
    EXTENSION_PHRASES,
    any_phrase_hit,
    approx_text_tokens,
    count_phrase_hits,
    first_n_approx_tokens,
)
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

_TEST_COMMAND_TOKENS = ("pytest", "npm test", "pnpm test", "yarn test", "bun test", "go test", "cargo test", "mix test")

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


_SYNTHETIC_USER_PROMPT_FLAGS = frozenset(
    {
        "agent_generated_meta",
        "telemetry_injected",
        "tool_result_only",
        "empty_prompt",
    }
)

SYNTHETIC_PROMPT_CLASSES = frozenset(
    {
        "telemetry_injected",
        "agent_generated_meta",
        "tool_result_only",
        "ide_context_injection",
    }
)

_IDE_CONTEXT_TAG_RE = re.compile(r"<(ide_opened_file|ide_selection)>(.*?)</\1>", re.IGNORECASE | re.DOTALL)


def _is_synthetic_user_prompt(flags: List[str]) -> bool:
    return any(f in _SYNTHETIC_USER_PROMPT_FLAGS for f in (flags or []))


def _synthetic_reasons(flags: List[str]) -> List[str]:
    return [f for f in (flags or []) if f in _SYNTHETIC_USER_PROMPT_FLAGS]


def _prompt_flags(prompt_text: str, tool_events: List[Dict[str, Any]], agent_type: str, agent_id: str) -> List[str]:
    """
    Best-effort provenance flags for user prompt events.

    These are heuristics over Claude Code JSONL; they are meant to avoid misleading
    attribution (e.g., agent-generated meta prompts logged as role=user).
    """
    flags: List[str] = []
    t = (prompt_text or "").strip()
    low = t.lower()
    if agent_type == "subagent" or agent_id.startswith("acompact"):
        flags.append("subagent_user")
    if "<ide_opened_file>" in low or "the user opened the file" in low:
        flags.append("telemetry_injected")
    if "<ide_selection>" in low:
        flags.append("telemetry_injected")
    if low.startswith("your task is to create a detailed summary of the conversation so far"):
        flags.append("agent_generated_meta")
    if "<analysis>" in low and "do not use any tools" in low:
        flags.append("agent_generated_meta")
    if "this session is being continued from a previous conversation" in low:
        flags.append("agent_generated_meta")

    if not t:
        # If the only content is tool_result blocks, it's not a real prompt.
        if tool_events and all(e.get("kind") == "tool_result" for e in tool_events):
            flags.append("tool_result_only")
        else:
            flags.append("empty_prompt")
    return flags


def _ide_injected_chars(text: str) -> int:
    total = 0
    for match in _IDE_CONTEXT_TAG_RE.finditer(text or ""):
        total += len(match.group(0) or "")
    return total


def _classify_prompt_origin(
    *,
    text: str,
    is_user_turn: bool,
    prompt_flags: List[str],
    prior_non_user_scorable_turns: int,
    prior_authored_user_turn_count: int,
) -> Dict[str, Any]:
    total_text_chars = len(text or "")
    ide_injected_chars = _ide_injected_chars(text)
    ide_ratio = float(ide_injected_chars / total_text_chars) if total_text_chars > 0 else 0.0
    mixed_content = False

    if not is_user_turn:
        origin = "non_user"
    elif "tool_result_only" in (prompt_flags or []):
        origin = "tool_result_only"
    elif "agent_generated_meta" in (prompt_flags or []):
        origin = "agent_generated_meta"
    elif "telemetry_injected" in (prompt_flags or []) or ide_injected_chars > 0:
        authored_ratio = 1.0 - ide_ratio if total_text_chars > 0 else 0.0
        if ide_ratio > 0.60:
            origin = "ide_context_injection"
        else:
            if 0.40 <= ide_ratio <= 0.60:
                mixed_content = True
            if prior_authored_user_turn_count == 0 or prior_non_user_scorable_turns >= 5:
                origin = "user_prompt"
            else:
                origin = "user_continuation"
            if authored_ratio <= 0.60 and ide_ratio > 0.60:
                origin = "ide_context_injection"
    elif "empty_prompt" in (prompt_flags or []):
        origin = "tool_result_only"
    else:
        if prior_authored_user_turn_count == 0 or prior_non_user_scorable_turns >= 5:
            origin = "user_prompt"
        else:
            origin = "user_continuation"

    human_authored = origin in {"user_prompt", "user_continuation"}
    prompt_detector_eligible = bool(is_user_turn and human_authored and ("tool_result_only" not in (prompt_flags or [])))
    return {
        "origin_class": origin,
        "human_authored": human_authored,
        "prompt_detector_eligible": prompt_detector_eligible,
        "mixed_content": mixed_content,
        "ide_injected_ratio": round(ide_ratio, 4),
    }


def _extract_tool_events(tool_calls: List[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        kind = str(call.get("type") or "").strip()
        if kind not in {"tool_use", "tool_result"}:
            continue
        if kind == "tool_use":
            inp = call.get("input") if isinstance(call.get("input"), dict) else {}
            out.append(
                {
                    "kind": "tool_use",
                    "tool_use_id": str(call.get("id") or call.get("tool_use_id") or ""),
                    "name": str(call.get("name") or ""),
                    "file_path": str(inp.get("file_path") or inp.get("path") or ""),
                    "command": str(inp.get("command") or inp.get("cmd") or ""),
                }
            )
        else:
            out.append(
                {
                    "kind": "tool_result",
                    "tool_use_id": str(call.get("tool_use_id") or ""),
                    "content_snippet": _snippet(str(call.get("content") or ""), n=120),
                }
            )
    return out


def extract_turn_features(turn: Dict[str, Any], index: int) -> Dict[str, Any]:
    text = _safe_text(turn)
    text_lower = text.lower()

    file_paths = FILE_PATH_RE.findall(text)
    func_mentions = FUNCTION_RE.findall(text)
    symbol_names: List[str] = []
    for m in func_mentions:
        parts = str(m).split()
        if parts:
            symbol_names.append(parts[-1])

    vague_hits = [phrase for phrase in VAGUE_PHRASES if phrase in text_lower]
    correction_hits = [phrase for phrase in CORRECTION_PHRASES if phrase in text_lower]
    rework_class = _classify_rework(text_lower)
    correction_language = len(correction_hits) > 0 or rework_class != "none"

    raw_tool_calls = turn.get("tool_calls")
    tool_calls: List[Any] = raw_tool_calls if isinstance(raw_tool_calls, list) else []
    tool_events = _extract_tool_events(tool_calls)
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
                if any(tok in cmd for tok in _TEST_COMMAND_TOKENS):
                    test_commands += 1

    turn_cost = float(turn.get("cost", 0.0) or 0.0)
    no_cache_cost = float(turn.get("no_cache_cost", 0.0) or 0.0) if "no_cache_cost" in turn else 0.0
    cache_savings = float(turn.get("cache_savings", 0.0) or 0.0) if "cache_savings" in turn else 0.0
    tokens = int(turn.get("tokens", 0) or 0)
    tokens_effective = int(turn.get("tokens_effective", 0) or 0)
    cache_read_tokens = int(turn.get("cache_read_tokens", 0) or 0)
    cache_write_tokens = int(turn.get("cache_write_tokens", 0) or 0)
    model = str(turn.get("model", "unknown"))
    cost_source = str(turn.get("cost_source", "") or "")

    is_user_turn = _is_user_turn(turn)
    is_assistant_turn = _is_assistant_turn(turn)
    is_scored_turn = is_user_turn or is_assistant_turn
    agent_type = str(turn.get("_agent_type", "primary"))
    agent_id = str(turn.get("_agent_id", "primary"))
    flags = _prompt_flags(text, tool_events, agent_type=agent_type, agent_id=agent_id) if is_user_turn else []

    # V2: turn semantics and shared correction/extension signals.
    tokens_for_heuristics = tokens if tokens > 0 else approx_text_tokens(text)
    tool_result_only = bool(is_user_turn and ("tool_result_only" in (flags or [])))
    has_tool_use = any(e.get("kind") == "tool_use" for e in tool_events)
    v2_is_scorable_turn = bool((is_user_turn or is_assistant_turn) and tokens_for_heuristics > 0 and (not tool_result_only) and ((text or "").strip() or has_tool_use))

    affirmation_language = any_phrase_hit(text_lower, AFFIRMATION_PHRASES)
    extension_language = any_phrase_hit(text_lower, EXTENSION_PHRASES)
    explicit_correction_hits = count_phrase_hits(text_lower, EXPLICIT_CORRECTION_PHRASES)
    explicit_correction_language = explicit_correction_hits > 0

    return {
        "turn_index": index,
        "uuid": str(turn.get("_uuid", "")),
        "parent_uuid": str(turn.get("_parent_uuid", "")),
        "tool_use_id": str(turn.get("_tool_use_id", "")),
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
        "cost_source": cost_source,
        "no_cache_cost": no_cache_cost,
        "cache_savings": cache_savings,
        "tool_call_count": len(tool_calls),
        "tool_use_count": sum(1 for e in tool_events if e.get("kind") == "tool_use"),
        "tool_result_count": sum(1 for e in tool_events if e.get("kind") == "tool_result"),
        "tool_events": tool_events,
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
        "agent_type": agent_type,
        "agent_id": agent_id,
        "prompt_flags": flags,
        "session_id": turn.get("sessionId") or turn.get("session_id") or "unknown",

        # V2 fields (stateful fields are filled in build_feature_bundle).
        "v2_tokens_for_heuristics": tokens_for_heuristics,
        "v2_is_scorable_turn": v2_is_scorable_turn,
        "v2_tool_result_only": tool_result_only,
        "v2_affirmation_language": affirmation_language,
        "v2_extension_language": extension_language,
        "v2_explicit_correction_language": explicit_correction_language,
        "v2_explicit_correction_hits": explicit_correction_hits,
        "v2_explicit_correction_dominant": False,
        "v2_prev_scorable_turn_index": None,
        "v2_prev_scorable_uuid": "",
        "v2_prev_was_assistant_with_tool_use": False,
        "v2_has_new_info_vs_last_k_user_turns": False,
        "v2_likely_extension": False,
        "v2_correction": {"is_correction": False, "confidence": "none", "reasons": []},
        "v2_symbol_names": symbol_names,
        "v2_prompt_origin_class": "unknown",
        "v2_human_authored_prompt": False,
        "v2_prompt_detector_eligible": False,
        "v2_mixed_content": False,
        "v2_ide_injected_ratio": 0.0,
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
    excluded_user_prompts: List[Dict[str, Any]] = []
    if user_turns:
        # Use the original scorable order for windowing.
        scorable_by_index = {t["turn_index"]: t for t in scorable_turns}
        user_indices = sorted(t["turn_index"] for t in user_turns)
        assistant_by_index = {t["turn_index"]: t for t in assistant_turns}

        def assistant_window(start_idx: int, end_idx_exclusive: int) -> List[Dict[str, Any]]:
            return [assistant_by_index[i] for i in range(start_idx + 1, end_idx_exclusive) if i in assistant_by_index]

        last_real_prompt_uuid = ""
        last_real_prompt_snippet = ""
        real_prompt_boundaries: List[int] = []
        for u_idx in user_indices:
            u = scorable_by_index[u_idx]
            prompt_text = str(u.get("text") or "")
            text_stripped = prompt_text.strip()
            flags = u.get("prompt_flags") or []
            if _is_synthetic_user_prompt(flags):
                excluded_user_prompts.append(
                    {
                        "timestamp": u.get("timestamp", "unknown"),
                        "prompt_uuid": u.get("uuid", ""),
                        "prompt_snippet": _snippet(prompt_text, n=200),
                        "prompt_flags": list(flags),
                        "reasons": _synthetic_reasons(flags),
                        "trigger_prompt_uuid": last_real_prompt_uuid,
                        "trigger_prompt_snippet": last_real_prompt_snippet,
                    }
                )
                continue
            if not text_stripped:
                continue
            real_prompt_boundaries.append(u_idx)
            last_real_prompt_uuid = str(u.get("uuid", "") or "")
            last_real_prompt_snippet = _snippet(prompt_text, n=200)

        prompt_rows: List[Dict[str, Any]] = []
        if real_prompt_boundaries:
            synthetic_user_by_index: Dict[int, Dict[str, Any]] = {}
            for u_idx in user_indices:
                u = scorable_by_index[u_idx]
                flags = u.get("prompt_flags") or []
                if _is_synthetic_user_prompt(flags):
                    synthetic_user_by_index[u_idx] = u

            max_idx = max(scorable_by_index.keys()) if scorable_by_index else 0

            for pos, u_idx in enumerate(real_prompt_boundaries):
                u = scorable_by_index[u_idx]
                next_u_idx = real_prompt_boundaries[pos + 1] if pos + 1 < len(real_prompt_boundaries) else None
                end_idx = (next_u_idx or (max_idx + 1))
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

                synthetic_in_window: List[Dict[str, Any]] = []
                for s_idx, s_turn in sorted(synthetic_user_by_index.items(), key=lambda kv: kv[0]):
                    if u_idx < s_idx < end_idx:
                        s_text = str(s_turn.get("text") or "")
                        synthetic_in_window.append(
                            {
                                "uuid": str(s_turn.get("uuid", "") or ""),
                                "timestamp": str(s_turn.get("timestamp", "unknown") or "unknown"),
                                "flags": list(s_turn.get("prompt_flags") or []),
                                "snippet": _snippet(s_text, n=160),
                            }
                        )

                reasons: List[str] = []
                if win_cost >= 0.25:
                    reasons.append(f"high downstream cost (${win_cost:.2f})")
                if win_tokens >= max(cfg.expensive_turn_token_threshold, int(tokens_per_turn_p90 or 0)):
                    reasons.append(f"high downstream incremental tokens ({win_tokens})")
                if win_reads >= 10:
                    reasons.append(f"many file reads ({win_reads})")
                if next_user_is_correction:
                    reasons.append("next user turn indicates correction/rework")
                if synthetic_in_window:
                    reasons.append(f"synthetic user prompts in window ({len(synthetic_in_window)})")

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
                        "synthetic_user_turns_in_window": synthetic_in_window,
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

        # Exclude expensive prompts from quality candidates to avoid overlap
        expensive_ids = {r["prompt_uuid"] for r in most_expensive_prompts}

        quality_rows: List[Dict[str, Any]] = []
        for row in prompt_rows:
            if row["prompt_uuid"] in expensive_ids:
                continue
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
        "excluded_user_prompts": excluded_user_prompts,
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
    # Ensure consistent ordering across multi-file Claude logs.
    def _sort_key(r: Dict[str, Any]) -> tuple:
        return (
            str(r.get("timestamp") or ""),
            str(r.get("_source_file") or ""),
            int(r.get("_line_num") or 0),
            str(r.get("_uuid") or ""),
        )

    ordered = sorted(records, key=_sort_key)
    # V2 state is maintained per session across scorable turns.
    session_state: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "last_scorable": None,
            "prior_user_infos": [],
            "non_user_scorable_since_last_authored": 0,
            "authored_user_turn_count": 0,
        }
    )

    turn_features: List[Dict[str, Any]] = []
    for i, r in enumerate(ordered):
        tf = extract_turn_features(r, i + 1)
        sid = str(tf.get("session_id", "unknown"))
        st = session_state[sid]

        origin = _classify_prompt_origin(
            text=str(tf.get("text") or ""),
            is_user_turn=bool(tf.get("is_user_turn")),
            prompt_flags=list(tf.get("prompt_flags") or []),
            prior_non_user_scorable_turns=int(st.get("non_user_scorable_since_last_authored", 0) or 0),
            prior_authored_user_turn_count=int(st.get("authored_user_turn_count", 0) or 0),
        )
        tf["v2_prompt_origin_class"] = origin["origin_class"]
        tf["v2_human_authored_prompt"] = bool(origin["human_authored"])
        tf["v2_prompt_detector_eligible"] = bool(origin["prompt_detector_eligible"])
        tf["v2_mixed_content"] = bool(origin["mixed_content"])
        tf["v2_ide_injected_ratio"] = float(origin["ide_injected_ratio"])

        prev = st.get("last_scorable")
        if prev is not None:
            tf["v2_prev_scorable_turn_index"] = int(prev.get("turn_index", 0) or 0)
            tf["v2_prev_scorable_uuid"] = str(prev.get("uuid", "") or "")
            tf["v2_prev_was_assistant_with_tool_use"] = bool(
                prev.get("is_assistant_turn") and int(prev.get("tool_use_count", 0) or 0) > 0
            )

        # new info compared to prior *user* scorable turns only
        prior_infos: List[set] = st.get("prior_user_infos") or []
        prior_union: set = set()
        for s in prior_infos[-int(cfg.new_info_user_lookback_turns) :]:
            prior_union |= set(s)

        cur_info = set((tf.get("file_paths") or [])) | set((tf.get("v2_symbol_names") or []))
        has_new_info = bool(cur_info - prior_union) if prior_union else bool(cur_info)
        tf["v2_has_new_info_vs_last_k_user_turns"] = has_new_info
        tf["v2_likely_extension"] = bool((not bool(tf.get("v2_extension_language"))) and has_new_info)

        # Guarded explicit correction dominance checks.
        text = str(tf.get("text") or "")
        text_lower = text.lower()
        first_n = first_n_approx_tokens(text, int(cfg.correction_explicit_dominant_first_n_tokens))
        within_first = any_phrase_hit(first_n.lower(), EXPLICIT_CORRECTION_PHRASES)
        explicit_hits = int(tf.get("v2_explicit_correction_hits", 0) or 0)
        tok = int(tf.get("v2_tokens_for_heuristics", 0) or 0)

        if tok < int(cfg.correction_reactive_tokens_high):
            length_conf = "high"
        elif tok <= int(cfg.correction_reactive_tokens_medium):
            length_conf = "medium"
        elif tok <= int(cfg.correction_reactive_tokens_low):
            length_conf = "low"
        else:
            length_conf = "none"

        density = tok <= int(cfg.correction_explicit_density_max_tokens) and explicit_hits >= int(cfg.correction_explicit_density_min_hits)
        short_reactive = length_conf in {"high", "medium"}
        explicit_dominant = bool(tf.get("v2_explicit_correction_language")) and (within_first or density or short_reactive)
        tf["v2_explicit_correction_dominant"] = explicit_dominant

        # Shared correction detection (precision-first).
        reasons: List[str] = []
        is_correction = False
        confidence = "none"
        if tf.get("is_user_turn") and tf.get("v2_is_scorable_turn"):
            if tf.get("v2_affirmation_language"):
                reasons.append("affirmation_language")
            elif tf.get("v2_extension_language"):
                reasons.append("extension_language")
            else:
                prev_tool = bool(tf.get("v2_prev_was_assistant_with_tool_use"))
                no_new_info = not bool(tf.get("v2_has_new_info_vs_last_k_user_turns"))
                structural = prev_tool and no_new_info and (length_conf in {"high", "medium"})
                if structural:
                    reasons.append("structural_reactive")
                if explicit_dominant:
                    reasons.append("explicit_correction_dominant")
                candidate = explicit_dominant or structural

                if tf.get("v2_likely_extension") and not (explicit_dominant and short_reactive):
                    candidate = False
                    reasons.append("likely_extension_blocks_correction")

                if candidate:
                    is_correction = True
                    if explicit_dominant and within_first and short_reactive:
                        confidence = "high"
                    elif structural and length_conf == "high":
                        confidence = "high"
                    elif structural and length_conf == "medium":
                        confidence = "medium"
                    elif explicit_dominant and density and short_reactive:
                        confidence = "medium"
                    else:
                        confidence = "low"

        tf["v2_correction"] = {"is_correction": is_correction, "confidence": confidence, "reasons": reasons}

        # Update per-session state.
        if tf.get("v2_is_scorable_turn"):
            st["last_scorable"] = tf
            if tf.get("is_user_turn") and tf.get("v2_human_authored_prompt"):
                st["authored_user_turn_count"] = int(st.get("authored_user_turn_count", 0) or 0) + 1
                st["non_user_scorable_since_last_authored"] = 0
            elif not tf.get("is_user_turn"):
                st["non_user_scorable_since_last_authored"] = int(st.get("non_user_scorable_since_last_authored", 0) or 0) + 1
        if tf.get("is_user_turn") and tf.get("v2_is_scorable_turn") and (str(tf.get("text") or "").strip()):
            prior_infos.append(cur_info)
            # keep last k user info sets
            k = max(1, int(cfg.new_info_user_lookback_turns))
            if len(prior_infos) > k:
                st["prior_user_infos"] = prior_infos[-k:]
            else:
                st["prior_user_infos"] = prior_infos

        turn_features.append(tf)

    session_features = extract_session_features(turn_features, cfg)
    p90_tokens = float(session_features.get("tokens_per_turn_p90", 0.0))
    expensive_turns = _build_expensive_turns(ordered, p90_tokens=p90_tokens, top_n=10, config=cfg)
    session_features["expensive_turns"] = expensive_turns

    return {
        "turn_features": turn_features,
        "session_features": session_features,
    }
