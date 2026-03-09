from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .lineage import parent_graph_lineage, session_lineage_overview, time_window_lineage


def _score_style(score: float) -> str:
    if score >= 85:
        return "green"
    if score >= 70:
        return "yellow"
    return "red"

def _severity_style(sev: str) -> str:
    s = (sev or "").lower()
    if s in {"high", "critical", "red"}:
        return "red"
    if s in {"medium", "yellow"}:
        return "yellow"
    return "green"


_V2_DIMENSION_LABELS = {
    "specificity": "Prompt Clarity",
    "context_scope": "Context Efficiency",
    "correction_discipline": "Rework Rate",
    "model_stability": "AI Consistency",
    "session_convergence": "Task Completion",
}

_V2_DIMENSION_EXPLANATIONS = {
    "specificity": "Did your prompts tell Claude exactly what to do?",
    "context_scope": "Did you send the right amount of context per turn?",
    "correction_discipline": "How often did Claude have to redo things?",
    "model_stability": "Did the model stay reliable and focused?",
    "session_convergence": "Did sessions reach a clear, productive end?",
}

_ANTIPATTERN_DISPLAY_NAMES = {
    "convergence_gate1_miss": "Slow to Get Started",
    "convergence_gate2_failure": "Work Interrupted by Corrections",
    "convergence_gate3_inconclusive": "Session Ended Without Clear Resolution",
    "correction_spiral": "Stuck in Back-and-Forth Loop",
    "abandoned_session": "Session Abandoned Mid-Task",
    "file_thrash": "Files Being Re-read Repeatedly",
    "repeated_constraint": "Same Rule Repeated Every Turn",
    "error_dump": "Full Error Pasted (Not Trimmed)",
    "vague_opener": "Started Too Vague",
    "prompt_duplication": "Prompt Sent Twice (Pipeline Bug)",
    "scope_creep": "Task Scope Kept Expanding",
    "constraint_missing_scaffold": "Missing Project Setup Scaffold",
}

_SESSION_SHAPE_LABELS = {
    "Clean": "Efficient",
    "Exploration-Heavy": "Exploratory",
    "Correction-Heavy": "High Rework",
    "Abandoned": "Abandoned",
}

_PROJECT_RECOMMENDATION_SECTIONS = (
    ("you_did_well", "You did well", "green"),
    ("absolutely_must_do", "Absolutely must do", "red"),
    ("nice_to_do", "Nice to do", "yellow"),
)


def _project_recommendation_sections(project_recs: Dict[str, Any]) -> List[tuple[str, str, List[str]]]:
    sections = project_recs.get("sections") if isinstance(project_recs.get("sections"), dict) else {}
    out: List[tuple[str, str, List[str]]] = []
    for key, label, style in _PROJECT_RECOMMENDATION_SECTIONS:
        items = list(sections.get(key) or project_recs.get(key) or [])
        if items:
            out.append((label, style, items))
    return out


def _format_session_shape(shape: str) -> str:
    """Convert session shape to display name."""
    return _SESSION_SHAPE_LABELS.get(shape, shape)


def _build_session_health_panel(report: Dict[str, Any]) -> Panel:
    """Build Session Health panel with overall score and key metrics."""
    v2 = report.get("v2") or {}
    project_rollup = v2.get("project_rollup") or {}
    session = report.get("session_features") or {}
    total_cost_derived = float(report.get("total_cost_derived", 0.0) or 0.0)

    composite = float(project_rollup.get("composite", 0.0) or 0.0)
    score_style = _score_style(composite)

    # Determine health description based on score
    if composite >= 85:
        health_text = "Good"
    elif composite >= 70:
        health_text = "Fair"
    else:
        health_text = "Needs Attention"

    recoverable = float(project_rollup.get('recoverable_cost_total_usd', 0.0) or 0.0)
    recoverable_pct = (recoverable / total_cost_derived * 100) if total_cost_derived > 0 else 0.0

    panel_text = (
        f"**Overall Score:** [{score_style}]{composite:.0f} / 100[/] — {health_text}\n"
        f"**What this means:** Your sessions ran well overall. A few recurring patterns are adding avoidable cost.\n"
        f"**Sessions Analyzed:** {int(project_rollup.get('session_count', 0) or 0)}\n"
        f"**Total Spend:** ${total_cost_derived:.2f}\n"
        f"**Recoverable (fixable waste):** **${recoverable:.2f}** — "
        f"{recoverable_pct:.0f}% of your spend could have been avoided\n"
        f"**Saved by caching:** ~${float(session.get('estimated_cache_savings', 0.0) or 0.0):.2f} — caching is working well, keep it"
    )

    return Panel(panel_text, title="Session Health")


def _build_what_to_fix_section(per_session_v2: List[Dict[str, Any]], project_rollup: Dict[str, Any]) -> List[str]:
    """Build What to Fix section with flags grouped by pattern and ranked by cost."""
    lines: List[str] = []
    lines.append("")
    lines.append("## What to Fix")
    lines.append("")
    lines.append("These are the highest-impact issues found across your sessions, ranked by cost.")
    lines.append("")

    # Aggregate flags by flag_id across all sessions
    flag_costs: Dict[str, tuple[float, int, List[str]]] = {}  # flag_id -> (cost, count, session_ids)

    for session_data in per_session_v2:
        flags = session_data.get("flags") or []
        session_id = session_data.get("session_id", "unknown")

        for flag in flags:
            flag_id = flag.get("flag_id", "unknown")
            cost = float(flag.get("recoverable_cost_usd", 0.0) or 0.0)

            if flag_id not in flag_costs:
                flag_costs[flag_id] = (0.0, 0, [])

            total_cost, count, session_ids = flag_costs[flag_id]
            flag_costs[flag_id] = (total_cost + cost, count + flag.get("occurrences", 1), session_ids + [session_id])

    # Sort by cost descending
    sorted_flags = sorted(flag_costs.items(), key=lambda x: x[1][0], reverse=True)

    for flag_id, (total_cost, total_count, session_ids) in sorted_flags[:10]:
        display_name = _ANTIPATTERN_DISPLAY_NAMES.get(flag_id, flag_id)
        unique_sessions = len(set(session_ids))

        # Severity indicator (simple heuristic: cost > $5 = critical, > $1 = high)
        if total_cost >= 5.0:
            severity_emoji = "🔴"
        elif total_cost >= 1.0:
            severity_emoji = "🔴"
        else:
            severity_emoji = "🟡"

        lines.append(f"### {severity_emoji} {display_name}")
        lines.append(f"**Found in:** {unique_sessions} of {len(per_session_v2)} sessions · **{total_count} occurrences** · **~${total_cost:.2f} recoverable**")
        lines.append("")

        # Add generic descriptions based on flag type
        descriptions = {
            "prompt_duplication": "Your prompt text is duplicated inside single messages. This is almost always a tool pipeline bug — not something you're doing manually.",
            "file_thrash": "Claude is reading the same files multiple times in a session. This signals that context is getting lost mid-session — Claude has forgotten what it already read.",
            "convergence_gate1_miss": "Claude spent turns responding without using any tools. The task wasn't understood well enough to start.",
            "convergence_gate2_failure": "Claude started working, then got correction turns that broke the flow before the task finished.",
            "error_dump": "A full HTTP response with headers was pasted into a prompt. Only the error message and 2 relevant stack frames are needed — everything else adds noise and cost.",
            "constraint_missing_scaffold": "A well-specified prompt (with file paths) still triggered a correction. This usually means a project-level setup is missing.",
            "repeated_constraint": "The same rule or instruction was repeated in multiple separate prompts instead of being stated once in a project context.",
        }

        description = descriptions.get(flag_id, "An issue that affects prompt efficiency.")
        lines.append(description)
        lines.append("")

        # Add fix suggestions
        fixes = {
            "prompt_duplication": "**Fix:** Check how messages are assembled before sending. Each user turn should contain the prompt exactly once.",
            "file_thrash": "**Fix:** Use `CLAUDE.md` to pin key file paths and context up front. Avoid sessions that span many unrelated tasks.",
            "convergence_gate1_miss": "**Fix:** Lead with a clear goal + file path. Example: _\"Edit `app/routes/app._index.tsx` to add X. Expected: Y.\"_",
            "convergence_gate2_failure": "**Fix:** Instead of sending corrections mid-stream, stop and restate the full intent in a single new prompt.",
            "error_dump": "**Fix:** Trim errors to: error message + 2 relevant stack frames. Remove HTTP headers entirely.",
            "constraint_missing_scaffold": "**Fix:** Add a `CLAUDE.md` with project structure, key conventions, and file map. Run it once as a session opener.",
            "repeated_constraint": "**Fix:** Move standing rules to `CLAUDE.md`. State once, not per turn.",
        }

        fix = fixes.get(flag_id, "Review the flag details to understand the issue.")
        lines.append(fix)
        lines.append("")
        lines.append("---")
        lines.append("")

    return lines


def _build_score_breakdown_table(project_rollup: Dict[str, Any]) -> Table:
    """Build Score Breakdown table with dimensions, scores, and explanations."""
    table = Table(title="Score Breakdown", show_header=True, header_style="bold")
    table.add_column("What's Being Measured")
    table.add_column("Score", justify="right")
    table.add_column("Health", justify="center")

    for dim_id, score_value in (project_rollup.get("dimensions") or {}).items():
        dim_label = _V2_DIMENSION_LABELS.get(dim_id, dim_id)
        explanation = _V2_DIMENSION_EXPLANATIONS.get(dim_id, "")

        # Extract max points (typically 25, 30, 15, 10, 20 per dimension)
        max_points = 25
        if dim_id == "context_scope":
            max_points = 30
        elif dim_id == "model_stability":
            max_points = 10
        elif dim_id == "session_convergence":
            max_points = 20

        # Determine health signal
        if score_value >= max_points * 0.9:
            health = "✅ Excellent"
        elif score_value >= max_points * 0.7:
            health = "✅ Good"
        else:
            health = "⚠️ Could improve"

        full_text = f"**{dim_label}** — {explanation}"
        table.add_row(full_text, f"{score_value:.0f} / {max_points}", health)

    return table


def _build_session_breakdown_table(per_session_v2: List[Dict[str, Any]]) -> Table:
    """Build Session Breakdown table ranked by score."""
    table = Table(title="Session Breakdown", show_header=True, header_style="bold")
    table.add_column("Session")
    table.add_column("Score", justify="right")
    table.add_column("Pattern")
    table.add_column("Top Issues")
    table.add_column("Recoverable", justify="right")

    # Sort by composite score descending
    sorted_sessions = sorted(
        per_session_v2,
        key=lambda x: float((x.get("scores") or {}).get("composite", 0.0) or 0.0),
        reverse=True
    )

    for i, session_data in enumerate(sorted_sessions[:20], 1):
        session_id = str(session_data.get("session_id", "unknown"))[:8]
        composite = float((session_data.get("scores") or {}).get("composite", 0.0) or 0.0)
        shape = _format_session_shape((session_data.get("convergence") or {}).get("shape", "unknown"))
        recoverable = float(session_data.get("recoverable_cost_total_usd", 0.0) or 0.0)

        # Get top 2 flags
        flags = session_data.get("flags") or []
        top_flags = []
        for f in flags[:2]:
            flag_id = f.get("flag_id", "")
            occurrence_count = f.get("occurrences", 1)
            flag_display = _ANTIPATTERN_DISPLAY_NAMES.get(flag_id, flag_id)
            if occurrence_count > 1:
                top_flags.append(f"{flag_display} ×{occurrence_count}")
            else:
                top_flags.append(flag_display)

        issues_text = ", ".join(top_flags) if top_flags else "None"

        table.add_row(
            f"Session {i} ({session_id})",
            f"{composite:.0f}",
            shape,
            issues_text,
            f"${recoverable:.2f}"
        )

    return table


def render_cli_report(report: Dict[str, Any], console: Console | None = None) -> None:
    console = console or Console()

    v2 = report.get("v2") or {}
    recommendations = report.get("recommendations") or {}
    session = report["session_features"]
    rules = report["rule_violations"]

    # V2 format is now the only format
    project_rollup = v2.get("project_rollup") or {}
    per_session_v2 = v2.get("per_session_v2") or []

    # 1. Session Health Panel
    console.print(_build_session_health_panel(report))
    console.print()

    # 2. What to Fix Section (as CLI lines, printed as panels)
    # Build the structured flag data
    flag_costs: Dict[str, tuple[float, int, List[str]]] = {}
    for session_data in per_session_v2:
        flags = session_data.get("flags") or []
        session_id = session_data.get("session_id", "unknown")
        for flag in flags:
            flag_id = flag.get("flag_id", "unknown")
            cost = float(flag.get("recoverable_cost_usd", 0.0) or 0.0)
            if flag_id not in flag_costs:
                flag_costs[flag_id] = (0.0, 0, [])
            total_cost, count, session_ids = flag_costs[flag_id]
            flag_costs[flag_id] = (total_cost + cost, count + flag.get("occurrences", 1), session_ids + [session_id])

    sorted_flags = sorted(flag_costs.items(), key=lambda x: x[1][0], reverse=True)

    if sorted_flags:
        console.print("[bold]What to Fix[/]\n")
        console.print("These are the highest-impact issues found across your sessions, ranked by cost.\n")

        descriptions = {
            "prompt_duplication": "Your prompt text is duplicated inside single messages. This is almost always a tool pipeline bug — not something you're doing manually.",
            "file_thrash": "Claude is reading the same files multiple times in a session. This signals that context is getting lost mid-session — Claude has forgotten what it already read.",
            "convergence_gate1_miss": "Claude spent turns responding without using any tools. The task wasn't understood well enough to start.",
            "convergence_gate2_failure": "Claude started working, then got correction turns that broke the flow before the task finished.",
            "error_dump": "A full HTTP response with headers was pasted into a prompt. Only the error message and 2 relevant stack frames are needed — everything else adds noise and cost.",
            "constraint_missing_scaffold": "A well-specified prompt (with file paths) still triggered a correction. This usually means a project-level setup is missing.",
            "repeated_constraint": "The same rule or instruction was repeated in multiple separate prompts instead of being stated once in a project context.",
        }

        fixes = {
            "prompt_duplication": "Check how messages are assembled before sending. Each user turn should contain the prompt exactly once.",
            "file_thrash": "Use `CLAUDE.md` to pin key file paths and context up front. Avoid sessions that span many unrelated tasks.",
            "convergence_gate1_miss": "Lead with a clear goal + file path. Example: _\"Edit `app/routes/app._index.tsx` to add X. Expected: Y.\"_",
            "convergence_gate2_failure": "Instead of sending corrections mid-stream, stop and restate the full intent in a single new prompt.",
            "error_dump": "Trim errors to: error message + 2 relevant stack frames. Remove HTTP headers entirely.",
            "constraint_missing_scaffold": "Add a `CLAUDE.md` with project structure, key conventions, and file map. Run it once as a session opener.",
            "repeated_constraint": "Move standing rules to `CLAUDE.md`. State once, not per turn.",
        }

        for flag_id, (total_cost, total_count, session_ids) in sorted_flags[:10]:
            display_name = _ANTIPATTERN_DISPLAY_NAMES.get(flag_id, flag_id)
            unique_sessions = len(set(session_ids))

            # Severity indicator
            if total_cost >= 5.0:
                severity_emoji = "🔴"
            elif total_cost >= 1.0:
                severity_emoji = "🔴"
            else:
                severity_emoji = "🟡"

            description = descriptions.get(flag_id, "An issue that affects prompt efficiency.")
            fix = fixes.get(flag_id, "Review the flag details to understand the issue.")

            panel_text = (
                f"**Found in:** {unique_sessions} of {len(per_session_v2)} sessions · "
                f"**{total_count} occurrences** · **~${total_cost:.2f} recoverable**\n\n"
                f"{description}\n\n"
                f"**Fix:** {fix}"
            )

            console.print(Panel(panel_text, title=f"{severity_emoji} {display_name}"))
            console.print()

    # 3. Score Breakdown
    console.print(_build_score_breakdown_table(project_rollup))
    console.print()

    # Add context note for Score Breakdown
    context_dim = project_rollup.get("dimensions", {}).get("context_scope", 0.0)
    if context_dim and context_dim < 25:
        console.print("[yellow]Context Efficiency is your main drag — it's being pulled down by duplicate prompts and repeated file reads. Fix those two and this score jumps.[/]\n")

    # 4. Session Breakdown
    console.print(_build_session_breakdown_table(per_session_v2))
    console.print()

    # Call out highest priority session
    if per_session_v2:
        sorted_sessions = sorted(
            per_session_v2,
            key=lambda x: float((x.get("scores") or {}).get("composite", 0.0) or 0.0)
        )
        lowest_session = sorted_sessions[0]
        lowest_id = str(lowest_session.get("session_id", "unknown"))[:8]
        lowest_score = float((lowest_session.get("scores") or {}).get("composite", 0.0) or 0.0)
        lowest_recoverable = float(lowest_session.get("recoverable_cost_total_usd", 0.0) or 0.0)

        console.print(f"[yellow]Session {lowest_id} is your highest priority[/] — "
                     f"it scored {lowest_score:.0f} and has ${lowest_recoverable:.2f} recoverable, "
                     f"mostly from high-cost flag patterns.\n")

    turn_table = Table(title="Turn Metrics", show_header=True, header_style="bold")
    turn_table.add_column("Turns", justify="right")
    turn_table.add_column("Tokens (Inc)", justify="right")
    turn_table.add_column("Avg Tokens/Turn", justify="right")
    turn_table.add_column("Median Tokens/Turn", justify="right")
    turn_table.add_column("P90 Tokens/Turn", justify="right")
    turn_table.add_column("Cost", justify="right")
    turn_table.add_column("Correction Ratio", justify="right")
    turn_table.add_row(
        str(session["total_turns"]),
        str(session["total_tokens"]),
        f"{session.get('tokens_per_turn_avg', 0.0):.0f}",
        f"{session.get('tokens_per_turn_median', 0.0):.0f}",
        f"{session.get('tokens_per_turn_p90', 0.0):.0f}",
        f"${session['total_cost']:.4f}",
        f"{session['correction_ratio']:.2%}",
    )
    console.print(turn_table)

    token_diag = Table(title="Token Diagnostics (Cache / Effective)", show_header=True, header_style="bold")
    token_diag.add_column("Effective Tokens", justify="right")
    token_diag.add_column("Cache Read", justify="right")
    token_diag.add_column("Cache Write", justify="right")
    token_diag.add_column("Eff Avg/Turn", justify="right")
    token_diag.add_column("Eff Median/Turn", justify="right")
    token_diag.add_column("Eff P90/Turn", justify="right")
    token_diag.add_row(
        str(session.get("total_effective_tokens", 0)),
        str(session.get("total_cache_read_tokens", 0)),
        str(session.get("total_cache_write_tokens", 0)),
        f"{session.get('effective_tokens_per_turn_avg', 0.0):.0f}",
        f"{session.get('effective_tokens_per_turn_median', 0.0):.0f}",
        f"{session.get('effective_tokens_per_turn_p90', 0.0):.0f}",
    )
    console.print(token_diag)

    # Cache impact section: estimate cost if cache tokens were billed as regular input.
    est_no_cache = float(session.get("estimated_no_cache_cost", 0.0) or 0.0)
    est_savings = float(session.get("estimated_cache_savings", 0.0) or 0.0)
    est_turns = int(session.get("no_cache_estimate_turns", 0) or 0)
    asst_turns = int(session.get("assistant_turn_count", 0) or 0)
    if est_no_cache > 0.0 or est_turns > 0:
        coverage = (est_turns / asst_turns) if asst_turns else 0.0
        console.print(
            Panel(
                f"Estimated no-cache cost: ${est_no_cache:.4f}\n"
                f"Observed cost: ${float(session.get('total_cost', 0.0)):.4f}\n"
                f"Estimated savings from caching: ${est_savings:.4f}\n"
                f"Estimate coverage: {est_turns}/{asst_turns} assistant turns ({coverage:.1%})",
                title="Caching Impact (Estimate)",
            )
        )

    correction_panel = (
        f"Prompt-induced rework: {session.get('prompt_rework_count', 0)} "
        f"({session.get('prompt_rework_ratio', 0.0):.2%})\n"
        f"Model-induced rework: {session.get('model_rework_count', 0)} "
        f"({session.get('model_rework_ratio', 0.0):.2%})\n"
        f"Unknown rework: {session.get('unknown_rework_count', 0)} "
        f"({session.get('unknown_rework_ratio', 0.0):.2%})"
    )
    if int(session.get("user_turn_count", 0)) == 0:
        correction_panel += "\nVisibility: user turns unavailable (likely billable-only mode)"
    console.print(Panel(correction_panel, title="Correction Attribution"))

    dedupe_stats = session.get("dedupe_stats") or {}
    if dedupe_stats:
        console.print(
            Panel(
                f"Input events: {dedupe_stats.get('input_events', 0)}\n"
                f"Output events: {dedupe_stats.get('output_events', 0)}\n"
                f"Duplicates removed: {dedupe_stats.get('duplicates_removed', 0)}",
                title="Deduplication Summary",
            )
        )

    confidence = session.get("cost_confidence") or {}
    cost_source_counts = session.get("cost_source_counts") or {}
    if confidence or cost_source_counts:
        confidence_level = confidence.get("level", "unknown")
        coverage = confidence.get("coverage", {})
        coverage_text = ", ".join(f"{k}: {v}%" for k, v in coverage.items()) if coverage else "n/a"
        source_text = ", ".join(f"{k}: {v}" for k, v in cost_source_counts.items()) if cost_source_counts else "n/a"
        console.print(
            Panel(
                f"Pricing mode: {session.get('pricing_mode', 'auto')}\n"
                f"Pricing file: {session.get('pricing_file', 'default')}\n"
                f"Confidence level: {confidence_level}\n"
                f"Coverage: {coverage_text}\n"
                f"Cost sources: {source_text}\n"
                f"Over-40k turns: {session.get('over_40k_turn_ratio', 0.0):.2%}",
                title="Cost Confidence",
            )
        )

    largest_turn = session.get("largest_turn")
    if largest_turn:
        who = "user" if largest_turn.get("is_user_turn") else "assistant" if largest_turn.get("is_assistant_turn") else "event"
        flags = largest_turn.get("prompt_flags") or []
        flags_text = f"\nPrompt flags: {', '.join(flags)}" if flags else ""
        cost_source = largest_turn.get("cost_source") or "unknown"
        console.print(
            Panel(
                f"Session: {largest_turn.get('session_id','unknown')}\n"
                f"Turn #{largest_turn.get('turn_index', 0)} ({who}) | UUID: {str(largest_turn.get('uuid',''))[:8]}\n"
                f"Timestamp: {largest_turn.get('timestamp','unknown')}\n"
                f"Model: {largest_turn.get('model','unknown')} | Agent: {largest_turn.get('agent_type','unknown')}/{largest_turn.get('agent_id','unknown')}\n"
                f"Tokens (inc/eff): {largest_turn.get('tokens', 0)}/{largest_turn.get('tokens_effective', 0)} | "
                f"Cache (r/w): {largest_turn.get('cache_read_tokens', 0)}/{largest_turn.get('cache_write_tokens', 0)}\n"
                f"Cost: ${float(largest_turn.get('turn_cost', 0.0) or 0.0):.4f} (source={cost_source}){flags_text}",
                title="Worst (Largest) Turn",
            )
        )

    if rules:
        rule_table = Table(title="Rule Violations", show_header=True, header_style="bold")
        rule_table.add_column("Rule")
        rule_table.add_column("Severity")
        rule_table.add_column("Description")
        for rule in rules:
            rule_table.add_row(rule["rule_id"], rule["severity"], rule["description"])
        console.print(rule_table)
    else:
        console.print("[green]No rule violations detected.[/green]")

    if report.get("multi_agent") and report.get("per_session"):
        session_table = Table(title="Multi-Agent Session Breakdown", show_header=True, header_style="bold")
        session_table.add_column("Session ID")
        session_table.add_column("Turns", justify="right")
        session_table.add_column("Tokens", justify="right")
        session_table.add_column("Cost", justify="right")
        for row in report["per_session"]:
            session_table.add_row(
                row["session_id"],
                str(row["turns"]),
                str(row["tokens"]),
                f"${row['cost']:.4f}",
            )
        console.print(session_table)

    expensive_turns = session.get("expensive_turns") or []
    if expensive_turns:
        expensive_table = Table(title="Most Expensive Turns (Diagnostics)", show_header=True, header_style="bold")
        expensive_table.add_column("Timestamp")
        expensive_table.add_column("Model")
        expensive_table.add_column("Cost", justify="right")
        expensive_table.add_column("Tokens (Inc)", justify="right")
        expensive_table.add_column("Affects")
        for row in expensive_turns[:10]:
            expensive_table.add_row(
                str(row.get("timestamp", "unknown")),
                str(row.get("model", "unknown")),
                f"${float(row.get('cost', 0.0)):.4f}",
                str(row.get("tokens", 0)),
                ", ".join(row.get("affected_categories", [])),
            )
        console.print(expensive_table)

    expensive_prompts = session.get("most_expensive_prompts") or []
    if expensive_prompts:
        prompt_table = Table(title="Most Expensive Prompts (User Turns)", show_header=True, header_style="bold")
        prompt_table.add_column("Timestamp")
        prompt_table.add_column("UUID")
        prompt_table.add_column("Prompt")
        prompt_table.add_column("Cost", justify="right")
        prompt_table.add_column("Inc Tokens", justify="right")
        prompt_table.add_column("Eff Tokens", justify="right")
        prompt_table.add_column("Reads", justify="right")
        prompt_table.add_column("Edits", justify="right")
        prompt_table.add_column("Next Corr", justify="right")
        prompt_table.add_column("Why")
        for row in expensive_prompts[:10]:
            why = ", ".join(row.get("reasons") or [])
            prompt_text = str(row.get("prompt_text", "") or "").strip()
            prompt_display = (prompt_text[:200] + ("..." if len(prompt_text) > 200 else "")) if prompt_text else "<empty>"
            synth_count = len(row.get("synthetic_user_turns_in_window") or [])
            if synth_count:
                why = (why + f" | synth_in_window={synth_count}").strip(" |")
            prompt_table.add_row(
                str(row.get("timestamp", "unknown")),
                str(row.get("prompt_uuid", ""))[:8],
                prompt_display,
                f"${float(row.get('downstream_cost', 0.0)):.4f}",
                str(row.get("downstream_tokens", 0)),
                str(row.get("downstream_effective_tokens", 0)),
                str(row.get("downstream_file_reads", 0)),
                str(int(row.get("downstream_edits", 0)) + int(row.get("downstream_writes", 0))),
                "yes" if row.get("next_user_correction") else "no",
                why,
            )
        console.print(prompt_table)

    high_quality = session.get("high_quality_prompts") or []
    if high_quality:
        hq_table = Table(title="High Quality Prompts (Examples)", show_header=True, header_style="bold")
        hq_table.add_column("Score", justify="right")
        hq_table.add_column("UUID")
        hq_table.add_column("Prompt")
        hq_table.add_column("Cost", justify="right")
        hq_table.add_column("Inc Tokens", justify="right")
        hq_table.add_column("Why")
        for row in high_quality[:10]:
            prompt_text = str(row.get("prompt_text", "") or "").strip()
            prompt_display = (prompt_text[:200] + ("..." if len(prompt_text) > 200 else "")) if prompt_text else "<empty>"
            synth_count = len(row.get("synthetic_user_turns_in_window") or [])
            why = ", ".join(row.get("why") or [])
            if synth_count:
                why = (why + f" | synth_in_window={synth_count}").strip(" |")
            hq_table.add_row(
                f"{float(row.get('quality_score', 0.0)):.3f}",
                str(row.get("prompt_uuid", ""))[:8],
                prompt_display,
                f"${float(row.get('downstream_cost', 0.0)):.4f}",
                str(row.get("downstream_tokens", 0)),
                why,
            )
        console.print(hq_table)

    excluded_user_prompts = session.get("excluded_user_prompts") or []
    if excluded_user_prompts:
        excluded_table = Table(title="Excluded Synthetic 'User' Prompts (Heuristic)", show_header=True, header_style="bold")
        excluded_table.add_column("Timestamp")
        excluded_table.add_column("UUID")
        excluded_table.add_column("Reasons")
        excluded_table.add_column("Trigger UUID")
        excluded_table.add_column("Prompt")
        for row in excluded_user_prompts[:10]:
            excluded_table.add_row(
                str(row.get("timestamp", "unknown")),
                str(row.get("prompt_uuid", ""))[:8],
                ", ".join(row.get("reasons") or []),
                str(row.get("trigger_prompt_uuid", ""))[:8],
                str(row.get("prompt_snippet", "") or ""),
            )
        console.print(excluded_table)


def build_markdown_report(report: Dict[str, Any]) -> str:
    v2 = report.get("v2") or {}
    recommendations = report.get("recommendations") or {}
    session = report["session_features"]
    rules = report["rule_violations"]
    turn_features = report.get("turn_features") or []
    total_cost_derived = float(report.get("total_cost_derived", 0.0) or 0.0)

    lines: List[str] = []
    lines.append("# AI Coding Session Report")
    lines.append("")
    lines.append("---")
    lines.append("")

    # V2 format is now the only format
    project_rollup = v2.get("project_rollup") or {}
    per_session_v2 = v2.get("per_session_v2") or []

    # 1. Session Health
    lines.append("## Session Health")
    lines.append("")
    composite = float(project_rollup.get("composite", 0.0) or 0.0)
    if composite >= 85:
        health_text = "Good"
    elif composite >= 70:
        health_text = "Fair"
    else:
        health_text = "Needs Attention"

    lines.append(f"| | |")
    lines.append(f"|---|---|")
    lines.append(f"| **Overall Score** | {composite:.0f} / 100 — {health_text} |")
    lines.append(f"| **What this means** | Your sessions ran well overall. A few recurring patterns are adding avoidable cost. |")
    lines.append(f"| **Sessions Analyzed** | {int(project_rollup.get('session_count', 0) or 0)} |")
    lines.append(f"| **Total Spend** | ${total_cost_derived:.2f} |")

    recoverable = float(project_rollup.get('recoverable_cost_total_usd', 0.0) or 0.0)
    recoverable_pct = (recoverable / total_cost_derived * 100) if total_cost_derived > 0 else 0.0
    lines.append(f"| **Recoverable (fixable waste)** | **${recoverable:.2f}** — {recoverable_pct:.0f}% of your spend could have been avoided |")

    cache_savings = float(session.get('estimated_cache_savings', 0.0) or 0.0)
    lines.append(f"| **Saved by caching** | ~${cache_savings:.2f} — caching is working well, keep it |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 2. What to Fix
    lines.append("## What to Fix")
    lines.append("")
    lines.append("These are the highest-impact issues found across your sessions, ranked by cost.")
    lines.append("")

    # Aggregate flags by flag_id
    flag_costs: Dict[str, tuple[float, int, List[str]]] = {}
    for session_data in per_session_v2:
        flags = session_data.get("flags") or []
        session_id = session_data.get("session_id", "unknown")
        for flag in flags:
            flag_id = flag.get("flag_id", "unknown")
            cost = float(flag.get("recoverable_cost_usd", 0.0) or 0.0)
            if flag_id not in flag_costs:
                flag_costs[flag_id] = (0.0, 0, [])
            total_cost, count, session_ids = flag_costs[flag_id]
            flag_costs[flag_id] = (total_cost + cost, count + flag.get("occurrences", 1), session_ids + [session_id])

    sorted_flags = sorted(flag_costs.items(), key=lambda x: x[1][0], reverse=True)

    descriptions = {
        "prompt_duplication": "Your prompt text is duplicated inside single messages. This is almost always a tool pipeline bug — not something you're doing manually.",
        "file_thrash": "Claude is reading the same files multiple times in a session. This signals that context is getting lost mid-session — Claude has forgotten what it already read.",
        "convergence_gate1_miss": "Claude spent turns responding without using any tools. The task wasn't understood well enough to start.",
        "convergence_gate2_failure": "Claude started working, then got correction turns that broke the flow before the task finished.",
        "error_dump": "A full HTTP response with headers was pasted into a prompt. Only the error message and 2 relevant stack frames are needed — everything else adds noise and cost.",
        "constraint_missing_scaffold": "A well-specified prompt (with file paths) still triggered a correction. This usually means a project-level setup is missing.",
        "repeated_constraint": "The same rule or instruction was repeated in multiple separate prompts instead of being stated once in a project context.",
    }

    fixes = {
        "prompt_duplication": "Check how messages are assembled before sending. Each user turn should contain the prompt exactly once.",
        "file_thrash": "Use `CLAUDE.md` to pin key file paths and context up front. Avoid sessions that span many unrelated tasks.",
        "convergence_gate1_miss": "Lead with a clear goal + file path. Example: _\"Edit `app/routes/app._index.tsx` to add X. Expected: Y.\"_",
        "convergence_gate2_failure": "Instead of sending corrections mid-stream, stop and restate the full intent in a single new prompt.",
        "error_dump": "Trim errors to: error message + 2 relevant stack frames. Remove HTTP headers entirely.",
        "constraint_missing_scaffold": "Add a `CLAUDE.md` with project structure, key conventions, and file map. Run it once as a session opener.",
        "repeated_constraint": "Move standing rules to `CLAUDE.md`. State once, not per turn.",
    }

    for flag_id, (total_cost, total_count, session_ids) in sorted_flags[:10]:
        display_name = _ANTIPATTERN_DISPLAY_NAMES.get(flag_id, flag_id)
        unique_sessions = len(set(session_ids))

        # Severity emoji
        if total_cost >= 5.0:
            severity_emoji = "🔴"
        elif total_cost >= 1.0:
            severity_emoji = "🔴"
        else:
            severity_emoji = "🟡"

        description = descriptions.get(flag_id, "An issue that affects prompt efficiency.")
        fix = fixes.get(flag_id, "Review the flag details to understand the issue.")

        lines.append(f"### {severity_emoji} {display_name}")
        lines.append(f"**Found in:** {unique_sessions} of {len(per_session_v2)} sessions · **{total_count} occurrences** · **~${total_cost:.2f} recoverable**")
        lines.append("")
        lines.append(description)
        lines.append("")
        lines.append(f"**Fix:** {fix}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # 3. Score Breakdown
    lines.append("## Score Breakdown")
    lines.append("")
    lines.append("How your sessions scored across five dimensions. Each score reflects a different way your prompts affect cost and quality.")
    lines.append("")
    lines.append("| What's Being Measured | Score | Health |")
    lines.append("|---|---|---|")

    for dim_id, score_value in (project_rollup.get("dimensions") or {}).items():
        dim_label = _V2_DIMENSION_LABELS.get(dim_id, dim_id)
        explanation = _V2_DIMENSION_EXPLANATIONS.get(dim_id, "")

        # Determine max points
        max_points = 25
        if dim_id == "context_scope":
            max_points = 30
        elif dim_id == "model_stability":
            max_points = 10
        elif dim_id == "session_convergence":
            max_points = 20

        # Health signal
        if score_value >= max_points * 0.9:
            health = "✅ Excellent"
        elif score_value >= max_points * 0.7:
            health = "✅ Good"
        else:
            health = "⚠️ Could improve"

        lines.append(f"| **{dim_label}** — {explanation} | {score_value:.0f} / {max_points} | {health} |")

    lines.append("")
    context_dim = project_rollup.get("dimensions", {}).get("context_scope", 0.0)
    if context_dim and context_dim < 25:
        lines.append("**Context Efficiency** is your main drag — it's being pulled down by duplicate prompts and repeated file reads. Fix those two and this score jumps.")
        lines.append("")

    lines.append("---")
    lines.append("")

    # 4. Session Breakdown
    lines.append("## Session Breakdown")
    lines.append("")
    lines.append("| Session | Score | Pattern | Top Issues | Recoverable |")
    lines.append("|---|---|---|---|---|")

    sorted_sessions = sorted(
        per_session_v2,
        key=lambda x: float((x.get("scores") or {}).get("composite", 0.0) or 0.0),
        reverse=True
    )

    for i, session_data in enumerate(sorted_sessions[:20], 1):
        session_id = str(session_data.get("session_id", "unknown"))[:8]
        composite = float((session_data.get("scores") or {}).get("composite", 0.0) or 0.0)
        shape = _format_session_shape((session_data.get("convergence") or {}).get("shape", "unknown"))
        recoverable = float(session_data.get("recoverable_cost_total_usd", 0.0) or 0.0)

        # Get top flags
        flags = session_data.get("flags") or []
        top_flags = []
        for f in flags[:2]:
            flag_id = f.get("flag_id", "")
            occurrence_count = f.get("occurrences", 1)
            flag_display = _ANTIPATTERN_DISPLAY_NAMES.get(flag_id, flag_id)
            if occurrence_count > 1:
                top_flags.append(f"{flag_display} ×{occurrence_count}")
            else:
                top_flags.append(flag_display)

        issues_text = ", ".join(top_flags) if top_flags else "None"

        lines.append(f"| Session {i} ({session_id}) | {composite:.0f} | {shape} | {issues_text} | ${recoverable:.2f} |")

    lines.append("")

    if sorted_sessions:
        lowest_session = sorted_sessions[0]
        lowest_id = str(lowest_session.get("session_id", "unknown"))[:8]
        lowest_score = float((lowest_session.get("scores") or {}).get("composite", 0.0) or 0.0)
        lowest_recoverable = float(lowest_session.get("recoverable_cost_total_usd", 0.0) or 0.0)

        lines.append(f"**Session {lowest_id} is your highest priority** — "
                    f"it scored {lowest_score:.0f} and has ${lowest_recoverable:.2f} recoverable, "
                    f"mostly from high-cost flag patterns.")
        lines.append("")

    lines.append("---")
    lines.append("")

    # 5. Technical Details (in collapsible block)
    lines.append("## Technical Details")
    lines.append("")
    lines.append("<details>")
    lines.append("<summary>Token & cost metrics (click to expand)</summary>")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Total turns | {session['total_turns']} |")
    lines.append(f"| Incremental tokens | {session['total_tokens']} |")
    lines.append(f"| Effective tokens (with cache) | {session.get('total_effective_tokens', 0)} |")
    lines.append(f"| Cache read tokens | {session.get('total_cache_read_tokens', 0)} |")
    lines.append(f"| Cache write tokens | {session.get('total_cache_write_tokens', 0)} |")
    lines.append(f"| Avg tokens/turn | {session.get('tokens_per_turn_avg', 0.0):.0f} |")
    lines.append(f"| Median tokens/turn | {session.get('tokens_per_turn_median', 0.0):.0f} |")
    lines.append(f"| P90 tokens/turn | {session.get('tokens_per_turn_p90', 0.0):.0f} |")
    lines.append(f"| Effective avg/turn | {session.get('effective_tokens_per_turn_avg', 0.0):.0f} |")
    lines.append(f"| Correction ratio | {session['correction_ratio']:.2%} |")

    dedupe_stats = session.get("dedupe_stats") or {}
    if dedupe_stats:
        lines.append(f"| Duplicates removed | {dedupe_stats.get('duplicates_removed', 0)} |")

    est_no_cache = float(session.get("estimated_no_cache_cost", 0.0) or 0.0)
    est_savings = float(session.get("estimated_cache_savings", 0.0) or 0.0)
    if est_no_cache > 0.0:
        lines.append(f"| Estimated no-cache cost | ${est_no_cache:.2f} |")
    if est_savings > 0.0:
        lines.append(f"| **Cache savings** | **${est_savings:.2f}** |")

    lines.append("")
    lines.append("</details>")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Report generated by AI Coding Prompt Optimizer · [docs/specs/product-spec.md](docs/specs/product-spec.md)*")
    lines.append("")

    lines.append("## Caching Impact (Estimate)")
    est_no_cache = float(session.get("estimated_no_cache_cost", 0.0) or 0.0)
    est_savings = float(session.get("estimated_cache_savings", 0.0) or 0.0)
    est_turns = int(session.get("no_cache_estimate_turns", 0) or 0)
    asst_turns = int(session.get("assistant_turn_count", 0) or 0)
    if est_no_cache <= 0.0:
        lines.append("- Insufficient pricing coverage to estimate no-cache cost.")
    else:
        coverage = (est_turns / asst_turns) if asst_turns else 0.0
        lines.append(f"- Estimated no-cache cost: ${est_no_cache:.4f}")
        lines.append(f"- Estimated savings from caching: ${est_savings:.4f}")
        lines.append(f"- Estimate coverage: {est_turns}/{asst_turns} assistant turns ({coverage:.1%})")
    lines.append("")

    largest_turn = session.get("largest_turn") or {}
    if largest_turn:
        who = "user" if largest_turn.get("is_user_turn") else "assistant" if largest_turn.get("is_assistant_turn") else "event"
        lines.append("## Worst (Largest) Turn")
        lines.append(f"- Session: `{largest_turn.get('session_id','unknown')}`")
        lines.append(f"- Turn index: {largest_turn.get('turn_index', 0)} ({who})")
        lines.append(f"- Timestamp: `{largest_turn.get('timestamp','unknown')}`")
        lines.append(f"- UUID: `{largest_turn.get('uuid','')}`")
        lines.append(f"- Model: `{largest_turn.get('model','unknown')}`")
        lines.append(f"- Tokens (incremental): {largest_turn.get('tokens', 0)}")
        lines.append(f"- Tokens (effective): {largest_turn.get('tokens_effective', 0)}")
        lines.append(f"- Cache read/write: {largest_turn.get('cache_read_tokens', 0)}/{largest_turn.get('cache_write_tokens', 0)}")
        lines.append(f"- Cost: ${float(largest_turn.get('turn_cost', 0.0) or 0.0):.4f} (source: `{largest_turn.get('cost_source') or 'unknown'}`)")
        lines.append(f"- Agent: `{largest_turn.get('agent_type','unknown')}` / `{largest_turn.get('agent_id','unknown')}`")
        if largest_turn.get("source_file"):
            lines.append(f"- Source: `{largest_turn.get('source_file')}`")
        flags = largest_turn.get("prompt_flags") or []
        if flags:
            lines.append(f"- Prompt flags: {', '.join(flags)}")
        if float(largest_turn.get("turn_cost", 0.0) or 0.0) == 0.0 and int(largest_turn.get("tokens", 0) or 0) > 0:
            lines.append("- Note: cost is $0.00 because this event had no reported cost and could not be derived (pricing/model/usage mismatch).")
        lines.append("")

    lines.append("## Session Lineage Overview")
    overview = session_lineage_overview(turn_features) if turn_features else []
    if not overview:
        lines.append("- None")
    else:
        for row in overview:
            tools = ", ".join(f"{name}={cnt}" for name, cnt in (row.get("top_tools") or []))
            lines.append(
                f"- session `{row['session_id']}`: turns={row['total_turns']} user={row['user_turns']} assistant={row['assistant_turns']} "
                f"prompts(non-empty)={row['prompts_non_empty']} tool_use={row['tool_use_count']} tool_result={row['tool_result_count']} "
                f"subagent_user={row['subagent_user_turns']} agent_meta={row['agent_generated_meta_turns']} tool_result_only={row['tool_result_only_user_turns']} "
                f"top_tools=[{tools}]"
            )
    lines.append("")

    # Group turns by session once for prompt drilldowns.
    turns_by_session: Dict[str, List[Dict[str, Any]]] = {}
    if turn_features:
        for t in turn_features:
            sid = str(t.get("session_id", "unknown"))
            turns_by_session.setdefault(sid, []).append(t)

    lines.append("## Violations")
    if rules:
        for rule in rules:
            lines.append(
                f"- **{rule['rule_id']}** ({rule['severity']}): {rule['description']} "
                f"→ Impact: {rule['impact_estimate']}"
            )
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Suggestions")
    # Keep generic suggestions minimal; prefer the per-prompt suggestions below.
    lines.append("- Use incremental tokens for context scope decisions; treat cached tokens as diagnostics.")
    if session.get("correction_ratio", 0.0) > 0.2:
        lines.append("- Reduce correction loops by stating explicit acceptance criteria and constraints up front.")
    lines.append("")

    if report.get("multi_agent") and report.get("per_session"):
        lines.append("## Multi-Agent Breakdown")
        for row in report["per_session"]:
            lines.append(
                f"- Session `{row['session_id']}`: turns={row['turns']}, tokens={row['tokens']}, cost=${row['cost']:.4f}"
            )
        lines.append("")

    lines.append("## Excluded Synthetic 'User' Prompts (Heuristic)")
    excluded = session.get("excluded_user_prompts", [])[:10]
    if not excluded:
        lines.append("- None")
    else:
        for i, p in enumerate(excluded, 1):
            reasons = ", ".join(p.get("reasons") or [])
            trig = str(p.get("trigger_prompt_uuid") or "")
            trig_display = f"`{trig}`" if trig else "<none>"
            lines.append(
                f"- {i}. `{p.get('timestamp','unknown')}` | uuid `{p.get('prompt_uuid','')}` | reasons [{reasons or 'unknown'}] | trigger {trig_display}"
            )
            snippet = str(p.get("prompt_snippet") or "").strip()
            if snippet:
                lines.append(f"  - prompt: {snippet}")
    lines.append("")

    lines.append("## Most Expensive Prompts (User Turns)")
    prompts = session.get("most_expensive_prompts", [])[:3]
    if not prompts:
        lines.append("- None")
    else:
        for i, p in enumerate(prompts, 1):
            lines.append(
                f"- {i}. `{p.get('timestamp','unknown')}` | session `{p.get('session_id','unknown')}` | uuid `{p.get('prompt_uuid','')}` | "
                f"downstream cost `${p.get('downstream_cost',0.0)}` | inc tokens `{p.get('downstream_tokens',0)}` | "
                f"eff tokens `{p.get('downstream_effective_tokens',0)}` | reads `{p.get('downstream_file_reads',0)}`"
            )
            prompt_text = str(p.get("prompt_text") or "").strip()
            if prompt_text:
                lines.append("  - prompt:")
                lines.append("```")
                lines.append(prompt_text)
                lines.append("```")
            else:
                lines.append("  - prompt: <empty>")
            if p.get("reasons"):
                lines.append(f"  - why: {', '.join(p['reasons'])}")
            synth = p.get("synthetic_user_turns_in_window") or []
            if synth:
                lines.append(f"  - synthetic user turns in window: {len(synth)}")
            suggestions = p.get("suggestions") or []
            if suggestions:
                lines.append("  - suggestions:")
                for s in suggestions[:6]:
                    lines.append(f"    - {s}")
            if p.get("suggested_rewrite"):
                lines.append("  - suggested rewrite:")
                lines.append("```")
                lines.append(str(p["suggested_rewrite"]))
                lines.append("```")

            # Dual lineage drilldowns (Markdown only)
            if turn_features and p.get("prompt_uuid"):
                prompt_uuid = str(p.get("prompt_uuid") or "")
                session_turns = turns_by_session.get(str(p.get("session_id", "unknown")), [])
                lines.append("  - lineage (time window):")
                for l in time_window_lineage(session_turns, prompt_uuid, max_events=25):
                    lines.append(f"    {l}")
                lines.append("  - lineage (parent graph):")
                for l in parent_graph_lineage(session_turns, prompt_uuid, max_events=25, max_depth=6):
                    lines.append(f"    {l}")

    lines.append("")
    lines.append("## High Quality Prompts (Examples to Copy)")
    hq = session.get("high_quality_prompts", [])[:3]
    if not hq:
        lines.append("- None")
    else:
        for i, p in enumerate(hq, 1):
            lines.append(
                f"- {i}. score `{p.get('quality_score',0.0)}` | uuid `{p.get('prompt_uuid','')}` | downstream cost `${p.get('downstream_cost',0.0)}` | "
                f"inc tokens `{p.get('downstream_tokens',0)}`"
            )
            prompt_text = str(p.get("prompt_text") or "").strip()
            if prompt_text:
                lines.append("  - prompt:")
                lines.append("```")
                lines.append(prompt_text)
                lines.append("```")
            else:
                lines.append("  - prompt: <empty>")
            why = p.get("why") or []
            if why:
                lines.append(f"  - why: {', '.join(why)}")
            synth = p.get("synthetic_user_turns_in_window") or []
            if synth:
                lines.append(f"  - synthetic user turns in window: {len(synth)}")

            if turn_features and p.get("prompt_uuid"):
                prompt_uuid = str(p.get("prompt_uuid") or "")
                session_turns = turns_by_session.get(str(p.get("session_id", "unknown")), [])
                lines.append("  - lineage (time window):")
                for l in time_window_lineage(session_turns, prompt_uuid, max_events=25):
                    lines.append(f"    {l}")
                lines.append("  - lineage (parent graph):")
                for l in parent_graph_lineage(session_turns, prompt_uuid, max_events=25, max_depth=6):
                    lines.append(f"    {l}")

    return "\n".join(lines)


def export_markdown_report(report: Dict[str, Any], out_path: str | Path) -> None:
    output_path = Path(out_path)
    output_path.write_text(build_markdown_report(report), encoding="utf-8")
