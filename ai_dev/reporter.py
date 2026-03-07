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
    "specificity": "Specificity",
    "context_scope": "Context Scope",
    "correction_discipline": "Correction Discipline",
    "model_stability": "Model Stability",
    "session_convergence": "Session Convergence",
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


def render_cli_report(report: Dict[str, Any], console: Console | None = None) -> None:
    console = console or Console()

    v2 = report.get("v2") or {}
    recommendations = report.get("recommendations") or {}
    scores = (v2.get("scores") or report.get("scores") or {})
    session = report["session_features"]
    rules = report["rule_violations"]

    if v2 and isinstance(v2.get("project_rollup"), dict):
        project_rollup = v2.get("project_rollup") or {}
        per_session_v2 = v2.get("per_session_v2") or []
        composite = float(project_rollup.get("composite", scores.get("composite", 0.0)) or 0.0)
        style = _score_style(composite)
        summary_text = (
            f"Project Composite Score: [bold {style}]{composite:.2f}/100[/]\n"
            f"Sessions: [bold]{int(project_rollup.get('session_count', 0) or 0)}[/]\n"
            f"Cumulative recoverable cost: ${float(project_rollup.get('recoverable_cost_total_usd', 0.0) or 0.0):.2f}"
        )
        console.print(Panel(summary_text, title="V2 Project Summary"))

        project_recs = recommendations.get("project") or {}
        if project_recs:
            section_blocks = _project_recommendation_sections(project_recs)
            if section_blocks:
                for label, style_name, bullets in section_blocks:
                    console.print(
                        Panel(
                            "\n".join(f"- {bullet}" for bullet in bullets),
                            title=f"Project Recommendations (LLM): {label}",
                            border_style=style_name,
                        )
                    )
            else:
                bullets = list(project_recs.get("bullets") or [])
                if bullets:
                    console.print(Panel("\n".join(f"- {bullet}" for bullet in bullets), title="Project Recommendations (LLM)"))
                elif project_recs.get("message"):
                    console.print(Panel(str(project_recs.get("message")), title="Project Recommendations (LLM)"))

        dim_table = Table(title="Project Dimension Scores (V2)", show_header=True, header_style="bold")
        dim_table.add_column("Dimension")
        dim_table.add_column("Weighted Score", justify="right")
        for dim_id, value in (project_rollup.get("dimensions") or {}).items():
            dim_table.add_row(
                _V2_DIMENSION_LABELS.get(dim_id, dim_id),
                str(value),
            )
        console.print(dim_table)

        flag_freq = project_rollup.get("flag_frequency") or {}
        if flag_freq:
            flag_table = Table(title="Project Flag Frequency (V2)", show_header=True, header_style="bold")
            flag_table.add_column("Flag")
            flag_table.add_column("Count", justify="right")
            for flag_id, count in list(flag_freq.items())[:12]:
                flag_table.add_row(str(flag_id), str(count))
            console.print(flag_table)

        if per_session_v2:
            session_table = Table(title="Per-Session Post-Mortems (V2)", show_header=True, header_style="bold")
            session_table.add_column("Session ID")
            session_table.add_column("Composite", justify="right")
            session_table.add_column("Shape")
            session_table.add_column("Recoverable", justify="right")
            session_table.add_column("Flags", justify="right")
            for row in per_session_v2[:20]:
                session_table.add_row(
                    str(row.get("session_id", "unknown")),
                    f"{float((row.get('scores') or {}).get('composite', 0.0) or 0.0):.2f}",
                    str((row.get("convergence") or {}).get("shape", "unknown")),
                    f"${float(row.get('recoverable_cost_total_usd', 0.0) or 0.0):.2f}",
                    str(len(row.get("flags") or [])),
                )
            console.print(session_table)

            session_recommendations = {
                str(item.get("session_id", "unknown")): item for item in list(recommendations.get("per_session") or [])
            }
            for row in per_session_v2[:20]:
                rec = session_recommendations.get(str(row.get("session_id", "unknown"))) or {}
                bullets = list(rec.get("bullets") or [])
                if bullets:
                    console.print(
                        Panel(
                            "\n".join(f"- {bullet}" for bullet in bullets),
                            title=f"Session Recommendations (LLM): {row.get('session_id', 'unknown')}",
                        )
                    )
    else:
        # Legacy V1 output
        style = _score_style(float(scores["composite"]))
        summary_text = (
            f"Composite Score: [bold {style}]{scores['composite']}/100[/]\n"
            f"Grade: [bold]{scores['grade']}[/]\n"
            f"Diagnosis: {scores['diagnosis']}"
        )
        console.print(Panel(summary_text, title="Prompt Quality Summary"))

        score_table = Table(title="Subscores", show_header=True, header_style="bold")
        score_table.add_column("Metric")
        score_table.add_column("Score", justify="right")
        for key, value in scores["subscores"].items():
            score_table.add_row(key, f"{value:.2f}/25")
        console.print(score_table)

    weighted = scores.get("weighted_breakdown") or {}
    weights = scores.get("weights") or {}
    if weighted and weights:
        weighted_table = Table(title="Weighted Contributions", show_header=True, header_style="bold")
        weighted_table.add_column("Metric")
        weighted_table.add_column("Weight", justify="right")
        weighted_table.add_column("Contribution", justify="right")
        for key, contribution in weighted.items():
            weighted_table.add_row(key, f"{weights.get(key, 0):.1f}%", f"{contribution:.2f}")
        console.print(weighted_table)
        console.print(
            Panel(
                "specificity: prompt concreteness (file paths/symbols/acceptance language) minus vague phrasing penalties\n"
                "correction: rework/correction pressure (prompt/model/unknown rework + repeated constraints)\n"
                "context_scope: context efficiency (avg/median/p90 tokens, over-40k ratio, tool/file-read churn penalties)\n"
                "model_efficiency: overspend signals from rule violations (e.g., model overkill / correction loops)",
                title="Category Definitions",
            )
        )

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
    scores = (v2.get("scores") or report.get("scores") or {})
    session = report["session_features"]
    rules = report["rule_violations"]
    turn_features = report.get("turn_features") or []

    lines: List[str] = []
    lines.append("# AI Coding Prompt Analysis Report")
    lines.append("")
    if v2 and isinstance(v2.get("project_rollup"), dict):
        project_rollup = v2.get("project_rollup") or {}
        per_session_v2 = v2.get("per_session_v2") or []
        session_recs = {
            str(item.get("session_id", "unknown")): item for item in list(recommendations.get("per_session") or [])
        }
        lines.append("## Summary (V2)")
        lines.append(f"- Project composite score: **{project_rollup.get('composite', 0.0)}/100**")
        lines.append(f"- Sessions analyzed: **{int(project_rollup.get('session_count', 0) or 0)}**")
        lines.append(f"- Project cumulative recoverable cost: `${float(project_rollup.get('recoverable_cost_total_usd', 0.0) or 0.0):.2f}`")
        lines.append("")

        project_recs = recommendations.get("project") or {}
        if project_recs:
            lines.append("## Project Recommendations (LLM)")
            section_blocks = _project_recommendation_sections(project_recs)
            if section_blocks:
                for label, _, bullets in section_blocks:
                    lines.append(f"### {label}")
                    for bullet in bullets:
                        lines.append(f"- {bullet}")
                    lines.append("")
            elif project_recs.get("bullets"):
                for bullet in list(project_recs.get("bullets") or []):
                    lines.append(f"- {bullet}")
            elif project_recs.get("message"):
                lines.append(f"- {project_recs.get('message')}")
            lines.append("")

        lines.append("## Project Dimension Scores (V2)")
        for dim_id, value in (project_rollup.get("dimensions") or {}).items():
            lines.append(f"- {_V2_DIMENSION_LABELS.get(dim_id, dim_id)}: {value}")
        lines.append("")

        lines.append("## Per-Session Post-Mortems (V2)")
        if not per_session_v2:
            lines.append("- None")
        else:
            for row in per_session_v2:
                lines.append(
                    f"- Session `{row.get('session_id','unknown')}` | composite `{float((row.get('scores') or {}).get('composite', 0.0) or 0.0):.2f}` "
                    f"| shape `{(row.get('convergence') or {}).get('shape', 'unknown')}` | recoverable `${float(row.get('recoverable_cost_total_usd', 0.0) or 0.0):.2f}`"
                )
                rec = session_recs.get(str(row.get("session_id", "unknown"))) or {}
                if rec.get("bullets"):
                    lines.append("  - recommendations (LLM):")
                    for bullet in list(rec.get("bullets") or []):
                        lines.append(f"    - {bullet}")
                elif rec.get("message") and rec.get("status") not in {"skipped", "ready"}:
                    lines.append(f"  - recommendations (LLM): {rec.get('message')}")
                rate = row.get("cost_rate") or {}
                lines.append(
                    f"  - cost rate: `{float(rate.get('usd_per_token', 0.0) or 0.0):.6f}` USD/token "
                    f"(source={rate.get('source','unknown')}, conf={rate.get('confidence','unknown')})"
                )
                for dim_id, dim in (row.get("dimensions") or {}).items():
                    lines.append(f"  - {_V2_DIMENSION_LABELS.get(dim_id, dim_id)}: {dim.get('points', 0.0)}/{dim.get('max_points', 0.0)}")
                    for d in (dim.get("deductions") or [])[:6]:
                        lines.append(
                            f"    - {d.get('cause_code','')}: -{float(d.get('points', 0.0) or 0.0):.2f} "
                            f"(flag `{d.get('flag_id','')}`)"
                        )
                flags = row.get("flags") or []
                if flags:
                    lines.append("  - flags:")
                for f in flags:
                    lines.append(
                        f"    - **{f.get('flag_id','')}** ({f.get('severity','')}): {f.get('description','')} "
                        f"(x{int(f.get('occurrences',0) or 0)}) | recoverable `${float(f.get('recoverable_cost_usd',0.0) or 0.0):.2f}`"
                    )
        lines.append("")

        lines.append("## Project Flag Frequency (V2)")
        flag_freq = project_rollup.get("flag_frequency") or {}
        if not flag_freq:
            lines.append("- None")
        else:
            for flag_id, count in flag_freq.items():
                lines.append(f"- `{flag_id}`: {count}")
        lines.append("")
    else:
        lines.append("## Summary")
        lines.append(f"- Composite score: **{scores['composite']}/100**")
        lines.append(f"- Grade: **{scores['grade']}**")
        lines.append(f"- Diagnosis: {scores['diagnosis']}")
        lines.append("")

    lines.append("## Score")
    if v2 and isinstance(v2.get("project_rollup"), dict):
        lines.append("- (V2 report; legacy V1 subscores omitted)")
    else:
        for key, value in scores["subscores"].items():
            lines.append(f"- {key}: {value}/25")
    weighted = scores.get("weighted_breakdown") or {}
    weights = scores.get("weights") or {}
    if weighted and weights:
        lines.append("")
        lines.append("### Weighted Contributions")
        lines.append("- Category definitions:")
        lines.append("- specificity: Prompt concreteness (file paths/symbols/acceptance language) minus vague phrasing penalties.")
        lines.append("- correction: Rework/correction pressure (prompt/model/unknown rework + repeated constraints).")
        lines.append("- context_scope: Context efficiency (avg/median/p90 tokens, over-40k ratio, tool/file-read churn penalties).")
        lines.append("- model_efficiency: Overspend signals from rule violations (e.g., model overkill / correction loops).")
        for key, contribution in weighted.items():
            lines.append(f"- {key}: {contribution}/100 contribution (weight={weights.get(key, 0):.1f}%)")
    lines.append("")

    lines.append("## Metrics")
    lines.append(f"- Total turns: {session['total_turns']}")
    lines.append(f"- Total tokens (incremental): {session['total_tokens']}")
    lines.append(f"- Total tokens (effective): {session.get('total_effective_tokens', 0)}")
    lines.append(f"- Cache read tokens: {session.get('total_cache_read_tokens', 0)}")
    lines.append(f"- Cache write tokens: {session.get('total_cache_write_tokens', 0)}")
    lines.append(f"- Avg tokens/turn: {session.get('tokens_per_turn_avg', 0.0):.0f}")
    lines.append(f"- Median tokens/turn: {session.get('tokens_per_turn_median', 0.0):.0f}")
    lines.append(f"- P90 tokens/turn: {session.get('tokens_per_turn_p90', 0.0):.0f}")
    lines.append(f"- Avg effective tokens/turn: {session.get('effective_tokens_per_turn_avg', 0.0):.0f}")
    lines.append(f"- Median effective tokens/turn: {session.get('effective_tokens_per_turn_median', 0.0):.0f}")
    lines.append(f"- P90 effective tokens/turn: {session.get('effective_tokens_per_turn_p90', 0.0):.0f}")
    lines.append(f"- Over-40k turns ratio: {session.get('over_40k_turn_ratio', 0.0):.2%}")
    lines.append(f"- Total cost: ${session['total_cost']:.4f}")
    lines.append(f"- Cost per turn: ${session['cost_per_turn']:.4f}")
    lines.append(f"- Correction ratio: {session['correction_ratio']:.2%}")
    lines.append(f"- Prompt-induced rework: {session.get('prompt_rework_count', 0)} ({session.get('prompt_rework_ratio', 0.0):.2%})")
    lines.append(f"- Model-induced rework: {session.get('model_rework_count', 0)} ({session.get('model_rework_ratio', 0.0):.2%})")
    lines.append(f"- Unknown rework: {session.get('unknown_rework_count', 0)} ({session.get('unknown_rework_ratio', 0.0):.2%})")
    if int(session.get("user_turn_count", 0)) == 0:
        lines.append("- Correction attribution visibility: low (user turns unavailable under current filter)")
    lines.append(f"- File explosion events: {session['file_explosion_events']}")

    dedupe_stats = session.get("dedupe_stats") or {}
    if dedupe_stats:
        lines.append(f"- Dedupe input events: {dedupe_stats.get('input_events', 0)}")
        lines.append(f"- Dedupe output events: {dedupe_stats.get('output_events', 0)}")
        lines.append(f"- Duplicates removed: {dedupe_stats.get('duplicates_removed', 0)}")

    confidence = session.get("cost_confidence") or {}
    source_counts = session.get("cost_source_counts") or {}
    if confidence:
        lines.append(f"- Cost confidence: {confidence.get('level', 'unknown')}")
    if source_counts:
        source_text = ", ".join(f"{k}={v}" for k, v in source_counts.items())
        lines.append(f"- Cost source counts: {source_text}")
    if session.get("pricing_mode"):
        lines.append(f"- Pricing mode: {session['pricing_mode']}")
    if session.get("pricing_file"):
        lines.append(f"- Pricing file: {session['pricing_file']}")
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
