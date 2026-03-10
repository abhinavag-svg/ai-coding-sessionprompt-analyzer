from __future__ import annotations

import re
from collections import Counter, defaultdict
from statistics import median
from typing import Any, Dict, List, Tuple

from .lexicon import approx_text_tokens
from .scoring_config import ScoringConfig


def _evidence(turn: Dict[str, Any], note: str = "") -> Dict[str, Any]:
    txt = str(turn.get("text", "") or "").strip().replace("\n", " ")
    return {
        "session_id": str(turn.get("session_id", "unknown")),
        "turn_index": int(turn.get("turn_index", 0) or 0),
        "uuid": str(turn.get("uuid", "")),
        "timestamp": str(turn.get("timestamp", "")),
        "snippet": (txt[:160] + ("..." if len(txt) > 160 else "")) if txt else "",
        "note": note,
    }


def _normalize_constraint_line(line: str) -> str:
    t = " ".join((line or "").strip().lower().split())
    return t.strip("-•* ").strip()


_CONSTRAINT_LINE_RE = re.compile(r"^(?:[-•*]\s*)?(do not|don't|must|only|never|please do not|avoid)\b", re.IGNORECASE)


def _extract_constraints(text: str) -> List[str]:
    out: List[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if _CONSTRAINT_LINE_RE.search(line):
            norm = _normalize_constraint_line(line)
            if len(norm) >= 8:
                out.append(norm)
    return out


def _normalize_block(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _qualifies_dup_block(text: str, config: ScoringConfig) -> bool:
    norm = _normalize_block(text)
    return len(norm) >= int(config.prompt_duplication_min_block_chars) and approx_text_tokens(norm) >= int(config.prompt_duplication_min_block_tokens)


_IDE_WRAPPER_SPAN_RE = re.compile(r"<(ide_opened_file|ide_selection)>.*?</\1>", re.IGNORECASE | re.DOTALL)


def _prompt_duplication_match_text(text: str) -> str:
    raw = text or ""
    # Ignore IDE wrapper scaffolding when judging duplication on otherwise authored prompts.
    stripped = _IDE_WRAPPER_SPAN_RE.sub("\n", raw)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped.strip()


def _detect_prompt_duplication(text: str, config: ScoringConfig) -> Tuple[bool, int]:
    raw = _prompt_duplication_match_text(text)
    if not raw:
        return False, 0
    blocks = [_normalize_block(p) for p in re.split(r"\n\s*\n", raw) if _normalize_block(p)]

    seen_blocks: Counter[str] = Counter()
    duplicated_tokens = 0
    for block in blocks:
        if not _qualifies_dup_block(block, config):
            continue
        seen_blocks[block] += 1
        if seen_blocks[block] >= 2:
            duplicated_tokens += approx_text_tokens(block)

    if duplicated_tokens > 0:
        return True, duplicated_tokens

    # Fallback for long single-paragraph prompts: repeated normalized line windows.
    lines = [_normalize_block(line) for line in raw.splitlines() if _normalize_block(line)]
    long_lines = [line for line in lines if _qualifies_dup_block(line, config)]
    if len(long_lines) >= 2:
        for window in (2, 3):
            if len(long_lines) < window * 2:
                continue
            seen_windows: Counter[Tuple[str, ...]] = Counter()
            for idx in range(0, len(long_lines) - window + 1):
                seq = tuple(long_lines[idx : idx + window])
                seen_windows[seq] += 1
                if seen_windows[seq] >= 2:
                    return True, sum(approx_text_tokens(item) for item in seq)

    return False, 0


_STACK_LINE_RE = re.compile(r"^\s*(Traceback|at\s+[\w./-]+\:\d+|Error:|Exception:)\b", re.IGNORECASE)
_HEADER_LINE_RE = re.compile(r"^\s*([A-Za-z0-9-]{2,40})\s*:\s*.+$")
_QUOTED_KEY_VALUE_RE = re.compile(r"^\s*['\"][^'\"]{1,80}['\"]\s*:\s*.+$")
_OBJECT_LITERAL_RE = re.compile(r"^\s*[\]}{,\[]|^\s*[A-Za-z0-9_]+:\s*[\[{].*$")
_PUNCTUATION_DENSE_RE = re.compile(r"[\[\]{}:,]{4,}")


def _error_dump_ratio(text: str, config: ScoringConfig) -> float:
    total = 0.0
    noisy = 0.0
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line_weight = float(len(raw))
        total += line_weight
        if _STACK_LINE_RE.search(line):
            noisy += line_weight * float(config.error_dump_traceback_weight)
            continue
        m = _HEADER_LINE_RE.match(line)
        if m:
            key = (m.group(1) or "").lower()
            if key.startswith(("x-", "cf-", "content-", "strict-", "server", "date", "vary", "report-to", "nel")):
                noisy += line_weight * float(config.error_dump_object_literal_weight)
                continue
        if _QUOTED_KEY_VALUE_RE.match(line) or _OBJECT_LITERAL_RE.match(line):
            noisy += line_weight * float(config.error_dump_object_literal_weight)
            continue
        if _PUNCTUATION_DENSE_RE.search(line):
            noisy += line_weight * float(config.error_dump_punctuation_weight)
            continue
    return float(noisy / max(1.0, total))


def _bounded_rework_cost(
    scorable: List[Dict[str, Any]],
    start_index: int,
    usd_per_token: float,
    config: ScoringConfig,
) -> float:
    if start_index < 0:
        return 0.0
    max_turns = int(config.recoverable_cost_max_turns)
    remaining_turns = max_turns
    cost = 0.0
    for t in scorable[start_index + 1 :]:
        if remaining_turns <= 0:
            break
        if not t.get("is_assistant_turn"):
            continue
        cost += float(int(t.get("tokens", 0) or 0) * usd_per_token)
        remaining_turns -= 1
        if cost >= float(config.recoverable_cost_max_usd):
            return float(config.recoverable_cost_max_usd)
    return min(cost, float(config.recoverable_cost_max_usd))


def detect_antipatterns_v2(
    turn_features: List[Dict[str, Any]],
    session_features: Dict[str, Any],
    convergence: Dict[str, Any],
    cost_rate: Dict[str, Any],
    config: ScoringConfig | None = None,
    is_orchestrated: bool = False,
) -> List[Dict[str, Any]]:
    cfg = config or ScoringConfig()
    scorable = [t for t in turn_features if t.get("v2_is_scorable_turn")]
    eligible_prompt_turns = [t for t in scorable if t.get("v2_prompt_detector_eligible")]
    duplication_prompt_turns = [t for t in eligible_prompt_turns if "telemetry_injected" not in (t.get("prompt_flags") or [])]

    # Adjust thresholds for orchestrated (multi-agent) sessions
    gate1_threshold = 6 if is_orchestrated else 5
    file_thrash_free_reads = 5 if is_orchestrated else int(cfg.file_thrash_free_reads)
    skip_correction_spiral = is_orchestrated
    scope_creep_threshold = 150 if is_orchestrated else 300

    # Check if session started with slash command (programmatic invocation)
    first_user = next((t for t in scorable if t.get("is_user_turn")), None)
    is_slash_command = first_user and "<command-name>" in (first_user.get("text") or "")

    flags: List[Dict[str, Any]] = []

    def add_flag(
        flag_id: str,
        severity: str,
        description: str,
        remedy: str,
        occurrences: int,
        impact_budget_points: float,
        per_occurrence_points: float,
        allocations: List[Dict[str, Any]],
        evidence: List[Dict[str, Any]],
        recoverable_cost_usd: float = 0.0,
    ) -> None:
        total = min(float(impact_budget_points), float(per_occurrence_points) * float(max(0, occurrences)))
        flags.append(
            {
                "flag_id": flag_id,
                "severity": severity,
                "description": description,
                "remedy": remedy,
                "occurrences": occurrences,
                "impact_budget_points": float(impact_budget_points),
                "per_occurrence_points": float(per_occurrence_points),
                "total_deduction_points": round(total, 3),
                "allocations": allocations,
                "evidence": evidence[:8],
                "recoverable_cost_usd": round(float(recoverable_cost_usd), 6),
            }
        )

    usd_per_token = float(cost_rate.get("usd_per_token", 0.0) or 0.0)

    # prompt_duplication (Context Scope 100%)
    dup_evidence: List[Dict[str, Any]] = []
    dup_count = 0
    dup_waste_tokens = 0
    read_turn_tokens: List[int] = []
    for t in scorable:
        if t.get("is_assistant_turn") and any(ev.get("kind") == "tool_use" and str(ev.get("name") or "") == "Read" for ev in (t.get("tool_events") or [])):
            read_turn_tokens.append(int(t.get("tokens", 0) or 0))

    for t in duplication_prompt_turns:
        txt = str(t.get("text") or "")
        dup_hit, dup_tokens = _detect_prompt_duplication(txt, cfg)
        if dup_hit:
            dup_count += 1
            dup_evidence.append(_evidence(t))
            dup_waste_tokens += max(dup_tokens, 0)
    if dup_count:
        add_flag(
            "prompt_duplication",
            "medium",
            "User prompt appears duplicated within the same message.",
            "Fix upstream prompt pipeline; deduplicate before sending.",
            occurrences=dup_count,
            impact_budget_points=4.0,
            per_occurrence_points=4.0,
            allocations=[{"dimension": "context_scope", "share": 1.0, "cause_code": "prompt_duplication"}],
            evidence=dup_evidence,
            recoverable_cost_usd=float(dup_waste_tokens) * usd_per_token,
        )

    # error_dump (Context Scope 80%, Specificity 20%)
    err_evidence: List[Dict[str, Any]] = []
    err_count = 0
    err_waste_tokens = 0
    for t in eligible_prompt_turns:
        txt = str(t.get("text") or "")
        if len(txt) < 500:
            continue
        ratio = _error_dump_ratio(txt, cfg)
        if ratio >= float(cfg.error_dump_fire_ratio):
            err_count += 1
            err_evidence.append(_evidence(t, note=f"ratio={ratio:.2f}"))
            # Waste estimate: all tokens beyond a short baseline.
            tok = int(t.get("v2_tokens_for_heuristics", 0) or 0)
            baseline = 120
            err_waste_tokens += max(0, tok - baseline)
    if err_count:
        add_flag(
            "error_dump",
            "high",
            "Large error/trace/header dump detected in user prompt.",
            "Trim to the error message plus 2 relevant stack frames; remove HTTP headers.",
            occurrences=err_count,
            impact_budget_points=6.0,
            per_occurrence_points=3.0,
            allocations=[
                {"dimension": "context_scope", "share": 0.80, "cause_code": "error_dump"},
                {"dimension": "specificity", "share": 0.20, "cause_code": "error_dump"},
            ],
            evidence=err_evidence,
            recoverable_cost_usd=float(err_waste_tokens) * usd_per_token,
        )

    # file_thrash (Context Scope 100%): same file read >2x.
    read_counts: Counter[str] = Counter()
    read_examples: Dict[str, Dict[str, Any]] = {}
    for t in scorable:
        if not t.get("is_assistant_turn"):
            continue
        for ev in (t.get("tool_events") or []):
            if ev.get("kind") == "tool_use" and str(ev.get("name") or "") == "Read":
                fp = str(ev.get("file_path") or "")
                if fp:
                    read_counts[fp] += 1
                    read_examples.setdefault(fp, _evidence(t, note=f"Read {fp}"))
    # Thrash fires when reads exceed free_reads threshold (default free_reads=2 means >2 triggers)
    thrash_files = [(fp, cnt) for fp, cnt in read_counts.items() if cnt > file_thrash_free_reads]
    if thrash_files:
        ev = [read_examples[fp] for fp, _ in sorted(thrash_files, key=lambda kv: kv[1], reverse=True)[:5]]
        median_read_tokens = int(median(read_turn_tokens)) if read_turn_tokens else 0
        redundant_reads = sum(max(0, cnt - file_thrash_free_reads) for _fp, cnt in thrash_files)
        add_flag(
            "file_thrash",
            "medium",
            "Repeated reads of the same file detected (context loss signal).",
            "After first read, summarize the relevant state to avoid re-reading.",
            occurrences=len(thrash_files),
            impact_budget_points=5.0,
            per_occurrence_points=2.0,
            allocations=[{"dimension": "context_scope", "share": 1.0, "cause_code": "file_thrash"}],
            evidence=ev,
            recoverable_cost_usd=float(redundant_reads * median_read_tokens) * usd_per_token,
        )

    # repeated_constraint (Correction Discipline 75%, Context Scope 25%): same constraint line in 3+ user turns.
    constraint_hits: Counter[str] = Counter()
    constraint_evidence: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in eligible_prompt_turns:
        for c in _extract_constraints(str(t.get("text") or "")):
            constraint_hits[c] += 1
            if len(constraint_evidence[c]) < 3:
                constraint_evidence[c].append(_evidence(t))
    repeated = [(c, cnt) for c, cnt in constraint_hits.items() if cnt >= 3]
    if repeated:
        top = sorted(repeated, key=lambda kv: kv[1], reverse=True)
        occ = sum(1 for _c, _cnt in top)
        ev: List[Dict[str, Any]] = []
        repeated_constraint_tokens = 0
        for c, cnt in top[:3]:
            ev.extend([{"note": f"`{c}` (x{cnt})", **e} for e in constraint_evidence.get(c, [])[:1]])
        for c, cnt in top:
            repeated_constraint_tokens += approx_text_tokens(c) * max(0, cnt - 1)
        add_flag(
            "repeated_constraint",
            "high",
            "Standing constraints repeated across multiple user turns.",
            "Move standing constraints to a project-level system prompt; state once, not per turn.",
            occurrences=occ,
            impact_budget_points=4.0,
            per_occurrence_points=1.0,
            allocations=[
                {"dimension": "correction_discipline", "share": 0.75, "cause_code": "repeated_constraint"},
                {"dimension": "context_scope", "share": 0.25, "cause_code": "repeated_constraint"},
            ],
            evidence=ev,
            recoverable_cost_usd=float(repeated_constraint_tokens) * usd_per_token,
        )

    # correction_spiral (Session Convergence 70%, Correction Discipline 30%): 3+ consecutive correction user turns with no tool use between.
    # Skip for orchestrated (multi-agent) sessions where retries are expected.
    if not skip_correction_spiral:
        spiral_segments: List[Tuple[int, int]] = []
        streak = 0
        seg_start = None
        for i, t in enumerate(scorable):
            if not t.get("is_user_turn"):
                continue
            conf = (t.get("v2_correction") or {}).get("confidence")
            if conf not in {"high", "medium"}:
                streak = 0
                seg_start = None
                continue
            # Check whether there was assistant tool use since previous user scorable.
            prev_user_idx = None
            for j in range(i - 1, -1, -1):
                if scorable[j].get("is_user_turn"):
                    prev_user_idx = j
                    break
            if prev_user_idx is None:
                streak = 1
                seg_start = i
                continue
            tools_between = any(
                scorable[k].get("is_assistant_turn") and int(scorable[k].get("tool_use_count", 0) or 0) > 0
                for k in range(prev_user_idx + 1, i)
            )
            if tools_between:
                streak = 1
                seg_start = i
                continue
            if seg_start is None:
                seg_start = prev_user_idx
                streak = 2
            else:
                streak += 1
            if streak >= 3:
                spiral_segments.append((seg_start, i))
                streak = 0
                seg_start = None

        if spiral_segments:
            ev = [_evidence(scorable[a], note="spiral start") for a, _b in spiral_segments[:2]]
            add_flag(
                "correction_spiral",
                "high",
                "Detected a correction spiral (multiple consecutive correction turns without tool progress).",
                "Stop the spiral: restate the full intent in one prompt instead of iterative corrections.",
                occurrences=len(spiral_segments),
                impact_budget_points=8.0,
                per_occurrence_points=8.0,
                allocations=[
                    {"dimension": "session_convergence", "share": 0.70, "cause_code": "correction_spiral"},
                    {"dimension": "correction_discipline", "share": 0.30, "cause_code": "correction_spiral"},
                ],
                evidence=ev,
            )

    # vague_opener (Specificity 60%, Session Convergence 40%)
    vague = 0
    vague_ev: List[Dict[str, Any]] = []
    first_user = next((t for t in scorable if t.get("v2_prompt_origin_class") == "user_prompt"), None)
    if first_user:
        tok = int(first_user.get("v2_tokens_for_heuristics", 0) or 0)
        if tok < 20:
            # correction before first tool use
            before_tool = []
            for t in scorable:
                if t.get("is_assistant_turn") and int(t.get("tool_use_count", 0) or 0) > 0:
                    break
                before_tool.append(t)
            has_corr = any(
                t.get("is_user_turn") and (t.get("v2_correction") or {}).get("confidence") in {"high", "medium"}
                for t in before_tool[1:]
            )
            if has_corr:
                vague = 1
                vague_ev.append(_evidence(first_user))
    if vague:
        add_flag(
            "vague_opener",
            "medium",
            "Vague opening prompt followed by correction before tool use.",
            "Front-load intent: include file paths, expected behavior, and acceptance criteria in the opening prompt.",
            occurrences=1,
            impact_budget_points=4.0,
            per_occurrence_points=4.0,
            allocations=[
                {"dimension": "specificity", "share": 0.60, "cause_code": "vague_opener"},
                {"dimension": "session_convergence", "share": 0.40, "cause_code": "vague_opener"},
            ],
            evidence=vague_ev,
        )

    # constraint_missing_scaffold (Model Stability 100%): high-specificity prompt followed by correction.
    cms_ev: List[Dict[str, Any]] = []
    cms_count = 0
    cms_index = -1
    for i, t in enumerate(scorable):
        if not t.get("v2_prompt_detector_eligible"):
            continue
        fp = len(t.get("file_paths") or [])
        sym = len(t.get("function_mentions") or [])
        acc = int(t.get("acceptance_hits", 0) or 0)
        high_spec = fp > 0 and (sym > 0 or acc > 0)
        if not high_spec:
            continue
        # Find next user scorable.
        next_user = None
        for j in range(i + 1, len(scorable)):
            if scorable[j].get("is_user_turn"):
                next_user = scorable[j]
                break
        if not next_user:
            continue
        conf = (next_user.get("v2_correction") or {}).get("confidence")
        if conf in {"high", "medium"} and not bool(next_user.get("v2_extension_language")):
            cms_count += 1
            cms_ev.append(_evidence(t))
            cms_index = i
            break
    if cms_count:
        add_flag(
            "constraint_missing_scaffold",
            "medium",
            "High-specificity prompt followed by correction suggests missing scaffolding.",
            "Add scaffolding: expected output format, a worked example, or step decomposition.",
            occurrences=cms_count,
            impact_budget_points=4.0,
            per_occurrence_points=4.0,
            allocations=[{"dimension": "model_stability", "share": 1.0, "cause_code": "constraint_missing_scaffold"}],
            evidence=cms_ev,
            recoverable_cost_usd=_bounded_rework_cost(scorable, cms_index, usd_per_token, cfg),
        )

    # Convergence gate synthetic flags.
    # Skip gate1 for slash-command (programmatic) sessions or if orchestrated doesn't apply.
    gate1_turns = convergence.get("gate1_user_turns_to_first_productive")
    if not is_slash_command:
        if gate1_turns is None:
            first_user = next((t for t in scorable if t.get("is_user_turn")), None)
            if first_user:
                add_flag(
                    "convergence_gate1_miss",
                    "high",
                    "Execution never reached productive tool use.",
                    "Front-load intent and acceptance criteria before exploration.",
                    occurrences=1,
                    impact_budget_points=6.0,
                    per_occurrence_points=6.0,
                    allocations=[{"dimension": "session_convergence", "share": 1.0, "cause_code": "convergence_gate1_miss"}],
                    evidence=[_evidence(first_user)],
                )
        elif int(gate1_turns) > gate1_threshold:
            first_user = next((t for t in scorable if t.get("is_user_turn")), None)
            add_flag(
                "convergence_gate1_miss",
                "high",
                "Execution engaged too late after the intent prompt.",
                "Front-load intent and acceptance criteria before exploration.",
                occurrences=1,
                impact_budget_points=6.0,
                per_occurrence_points=6.0,
                allocations=[{"dimension": "session_convergence", "share": 1.0, "cause_code": "convergence_gate1_miss"}],
                evidence=[_evidence(first_user)] if first_user else [],
        )

    gate2_count = int(convergence.get("gate2_corrections_between_productive", 0) or 0)
    if gate2_count >= 2:
        gate2_ev = [
            _evidence(t)
            for t in scorable
            if t.get("is_user_turn") and (t.get("v2_correction") or {}).get("confidence") in {"high", "medium"}
        ][:4]
        first_gate2_index = next(
            (idx for idx, t in enumerate(scorable) if t.get("is_user_turn") and (t.get("v2_correction") or {}).get("confidence") in {"high", "medium"}),
            -1,
        )
        add_flag(
            "convergence_gate2_failure",
            "high",
            "Correction turns interrupted the productive execution sequence.",
            "Restate the full intent in one prompt rather than iterating corrections.",
            occurrences=1,
            impact_budget_points=8.0,
            per_occurrence_points=8.0,
            allocations=[{"dimension": "session_convergence", "share": 1.0, "cause_code": "convergence_gate2_failure"}],
            evidence=gate2_ev,
            recoverable_cost_usd=_bounded_rework_cost(scorable, first_gate2_index, usd_per_token, cfg),
        )

    # abandoned_session (Session Convergence 100%): ends on a correction.
    abandoned_fired = False
    last_user = next((t for t in reversed(scorable) if t.get("is_user_turn")), None)
    if last_user and (last_user.get("v2_correction") or {}).get("confidence") in {"high", "medium"}:
        add_flag(
            "abandoned_session",
            "high",
            "Session ended mid-correction loop (abandonment signal).",
            "If task was too broad, restart with a scoped sub-task; otherwise decompose step-by-step.",
            occurrences=1,
            impact_budget_points=8.0,
            per_occurrence_points=8.0,
            allocations=[{"dimension": "session_convergence", "share": 1.0, "cause_code": "abandoned_session"}],
            evidence=[_evidence(last_user)],
            recoverable_cost_usd=_bounded_rework_cost(scorable, max(0, len(scorable) - 2), usd_per_token, cfg),
        )
        abandoned_fired = True

    if (convergence.get("gate3_status") == "inconclusive") and not abandoned_fired:
        last_prod_turn_idx = convergence.get("last_productive_turn_index")
        evidence = []
        if last_prod_turn_idx is not None:
            evidence = [_evidence(t) for t in scorable if int(t.get("turn_index", 0) or 0) >= int(last_prod_turn_idx)][0:3]
        add_flag(
            "convergence_gate3_inconclusive",
            "medium",
            "Session settlement is unclear after productive execution.",
            "Settlement unclear. Check whether the session ended mid-task.",
            occurrences=1,
            impact_budget_points=2.0,
            per_occurrence_points=2.0,
            allocations=[{"dimension": "session_convergence", "share": 1.0, "cause_code": "convergence_gate3_inconclusive"}],
            evidence=evidence,
        )

    # scope_creep (Session Convergence 100%): many turns and tool variety increases in last third.
    # Threshold adjusted for orchestrated sessions: 150 (normal) vs 300 (orchestrated adjusts upward).
    if len(scorable) > scope_creep_threshold:
        assistants = [t for t in scorable if t.get("is_assistant_turn")]
        if len(assistants) >= 30:
            split = int(len(assistants) * 2 / 3)
            early_tools = set(n for t in assistants[:split] for n in (t.get("tool_names") or []))
            late_tools = set(n for t in assistants[split:] for n in (t.get("tool_names") or []))
            if len(late_tools) >= len(early_tools) + 3:
                add_flag(
                    "scope_creep",
                    "medium",
                    "Long session with expanding tool variety in the final third (scope creep signal).",
                    "Split into sub-sessions by feature boundary to preserve context coherence.",
                    occurrences=1,
                    impact_budget_points=6.0,
                    per_occurrence_points=6.0,
                    allocations=[{"dimension": "session_convergence", "share": 1.0, "cause_code": "scope_creep"}],
                    evidence=[{"note": f"early_tools={len(early_tools)} late_tools={len(late_tools)}", **_evidence(assistants[-1])}],
                )

    return flags
