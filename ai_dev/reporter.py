from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from rich.console import Console
from rich.table import Table
from rich.panel import Panel


def _score_style(score: float) -> str:
    if score >= 85:
        return "green"
    if score >= 70:
        return "yellow"
    return "red"


def render_cli_report(report: Dict[str, Any], console: Console | None = None) -> None:
    console = console or Console()

    scores = report["scores"]
    session = report["session_features"]
    rules = report["rule_violations"]

    style = _score_style(scores["composite"])
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
        console.print(
            Panel(
                f"Turn #{largest_turn['turn_index']} | Tokens: {largest_turn['tokens']} | "
                f"Cost: ${largest_turn['turn_cost']:.4f} | Model: {largest_turn['model']}",
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
            hq_table.add_row(
                f"{float(row.get('quality_score', 0.0)):.3f}",
                str(row.get("prompt_uuid", ""))[:8],
                prompt_display,
                f"${float(row.get('downstream_cost', 0.0)):.4f}",
                str(row.get("downstream_tokens", 0)),
                ", ".join(row.get("why") or []),
            )
        console.print(hq_table)


def build_markdown_report(report: Dict[str, Any]) -> str:
    scores = report["scores"]
    session = report["session_features"]
    rules = report["rule_violations"]

    lines: List[str] = []
    lines.append("# AI Coding Prompt Analysis Report")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Composite score: **{scores['composite']}/100**")
    lines.append(f"- Grade: **{scores['grade']}**")
    lines.append(f"- Diagnosis: {scores['diagnosis']}")
    lines.append("")

    lines.append("## Score")
    for key, value in scores["subscores"].items():
        lines.append(f"- {key}: {value}/25")
    weighted = scores.get("weighted_breakdown") or {}
    weights = scores.get("weights") or {}
    if weighted and weights:
        lines.append("")
        lines.append("### Weighted Contributions")
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

    lines.append("## Most Expensive Prompts (User Turns)")
    prompts = session.get("most_expensive_prompts", [])
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

    lines.append("")
    lines.append("## High Quality Prompts (Examples to Copy)")
    hq = session.get("high_quality_prompts", [])
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

    return "\n".join(lines)


def export_markdown_report(report: Dict[str, Any], out_path: str | Path) -> None:
    output_path = Path(out_path)
    output_path.write_text(build_markdown_report(report), encoding="utf-8")
