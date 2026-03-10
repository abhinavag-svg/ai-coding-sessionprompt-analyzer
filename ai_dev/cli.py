from __future__ import annotations

import os
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

import typer

from .costing import estimate_no_cache_cost, load_pricing_file, resolve_cost
from .dedupe import dedupe_events
from .feature_extractor import build_feature_bundle
from .llm_recommendations import RecommendationConfig, enrich_report_with_recommendations
from .models import CostMode
from .parser import find_jsonl_files, load_events
from .analyzer_v2 import analyze_v2
from .reporter import export_markdown_report, render_cli_report
from .scoring_config import ScoringConfig, load_scoring_config

app = typer.Typer(no_args_is_help=True)


def _to_record(event, cost: float, cost_source: str, no_cache_cost: float | None = None) -> Dict[str, Any]:
    payload = dict(event.payload)
    message = cast(Dict[str, Any], payload.get("message")) if isinstance(payload.get("message"), dict) else {}

    tool_calls = cast(List[Dict[str, Any]], payload.get("tool_calls")) if isinstance(payload.get("tool_calls"), list) else []
    if not tool_calls and isinstance(message.get("content"), list):
        for item in message["content"]:
            if isinstance(item, dict) and item.get("type") in {"tool_use", "tool_result"}:
                tool_calls.append(item)

    text_parts = []
    if isinstance(message.get("content"), list):
        for item in message["content"]:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                text_parts.append(item["text"])

    # Primary token metric for scoring: incremental IO only.
    payload["tokens"] = event.usage.incremental_tokens
    # Diagnostics: cache/effective token pressure.
    payload["tokens_effective"] = event.usage.effective_tokens
    payload["cache_read_tokens"] = event.usage.cache_read_tokens
    payload["cache_write_tokens"] = event.usage.cache_write_tokens
    payload["cost"] = cost
    payload["cost_source"] = cost_source
    if no_cache_cost is not None:
        payload["no_cache_cost"] = float(no_cache_cost)
        payload["cache_savings"] = float(max(0.0, no_cache_cost - cost))
    payload["tool_calls"] = tool_calls
    payload["model"] = event.model
    payload["sessionId"] = event.session_id
    payload["role"] = event.role or str(message.get("role", ""))
    payload["type"] = payload.get("type", event.event_type)
    payload["_uuid"] = event.uuid
    payload["_parent_uuid"] = event.parent_uuid
    payload["_tool_use_id"] = event.tool_use_id
    payload["_agent_id"] = event.agent_id
    payload["_source_file"] = event.source_file
    payload["_line_num"] = event.line_num
    payload["_agent_type"] = "subagent" if "subagents" in Path(event.source_file).parts else "primary"
    if text_parts and "text" not in payload:
        payload["text"] = "\n".join(text_parts)
    return payload


def _confidence_summary(cost_sources: Counter[str]) -> Dict[str, Any]:
    total = sum(cost_sources.values())
    if total == 0:
        return {"level": "unknown", "coverage": {}}

    coverage = {k: round((v / total) * 100, 2) for k, v in cost_sources.items()}
    exact_share = coverage.get("reported", 0.0)
    split_share = coverage.get("derived_split", 0.0)
    fallback_share = coverage.get("derived_fallback", 0.0)

    if exact_share >= 80:
        level = "exact"
    elif exact_share >= 40:
        level = "high"
    elif split_share >= 70:
        level = "high"
    elif split_share + fallback_share >= 60:
        level = "estimated"
    else:
        level = "unknown"

    return {"level": level, "coverage": coverage}


def _build_report(
    records: List[Dict[str, Any]],
    multi_agent: bool,
    dedupe_stats: Dict[str, Any],
    cost_sources: Counter[str],
    pricing_mode: str,
    pricing_file: str | None,
    config: ScoringConfig | None = None,
) -> Dict[str, Any]:
    cfg = config or ScoringConfig()
    features = build_feature_bundle(records, cfg)

    # Compute total derived cost directly from records (not from scorable_turns).
    # This ensures cost is not lost if some billing events have empty role fields.
    total_cost_derived = sum(float(r.get("cost", 0.0) or 0.0) for r in records)

    confidence = _confidence_summary(cost_sources)
    session_features = dict(features["session_features"])
    session_features["dedupe_stats"] = dedupe_stats
    session_features["cost_source_counts"] = dict(cost_sources)
    session_features["cost_confidence"] = confidence
    session_features["pricing_mode"] = pricing_mode
    session_features["pricing_file"] = pricing_file or "default"

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in records:
        grouped[str(row.get("sessionId", "unknown"))].append(row)

    per_session_v2: List[Dict[str, Any]] = []
    for session_id, session_records in sorted(grouped.items(), key=lambda kv: kv[0]):
        # Auto-detect multi-agent sessions: count unique subagent source files
        subagent_files = {r["_source_file"] for r in session_records if r.get("_agent_type") == "subagent"}
        is_orchestrated = len(subagent_files) >= 4

        # Extract project folder from source file path
        source_file = (session_records[0].get("_source_file") or "") if session_records else ""
        project_folder = Path(source_file).parent.name if source_file else ""

        session_bundle = build_feature_bundle(session_records, cfg)
        session_v2 = analyze_v2(session_bundle["turn_features"], session_bundle["session_features"], cfg, is_orchestrated=is_orchestrated)
        per_session_v2.append(
            {
                "session_id": session_id,
                "session_features": session_bundle["session_features"],
                "turn_features": session_bundle["turn_features"],
                "scores": session_v2.scores,
                "dimensions": session_v2.dimensions,
                "flags": session_v2.flags,
                "deductions": session_v2.deductions,
                "convergence": session_v2.convergence,
                "cost_rate": session_v2.cost_rate,
                "recoverable_cost_total_usd": session_v2.recoverable_cost_total_usd,
                "project_folder": project_folder,
            }
        )

    if per_session_v2:
        total_cost = sum(float((row.get("session_features") or {}).get("total_cost", 0.0) or 0.0) for row in per_session_v2)
        dim_ids = ["specificity", "context_scope", "correction_discipline", "model_stability", "session_convergence"]
        rolled_dimensions: Dict[str, float] = {}
        for dim_id in dim_ids:
            weighted_num = 0.0
            weighted_den = 0.0
            for row in per_session_v2:
                cost = float((row.get("session_features") or {}).get("total_cost", 0.0) or 0.0)
                weight = cost if cost > 0 else 1.0
                weighted_num += float((row.get("scores") or {}).get("dimensions", {}).get(dim_id, 0.0) or 0.0) * weight
                weighted_den += weight
            rolled_dimensions[dim_id] = round(weighted_num / weighted_den, 2) if weighted_den > 0 else 0.0

        flag_frequency: Counter[str] = Counter()
        for row in per_session_v2:
            for flag in (row.get("flags") or []):
                flag_frequency[str(flag.get("flag_id") or "")] += int(flag.get("occurrences", 0) or 0)

        project_rollup = {
            "session_count": len(per_session_v2),
            "dimensions": rolled_dimensions,
            "composite": round(sum(rolled_dimensions.values()), 2),
            "recoverable_cost_total_usd": round(sum(float(row.get("recoverable_cost_total_usd", 0.0) or 0.0) for row in per_session_v2), 6),
            "flag_frequency": dict(sorted(flag_frequency.items(), key=lambda kv: (-kv[1], kv[0]))),
            "session_efficiency_distribution": [
                {
                    "session_id": row["session_id"],
                    "composite": float((row.get("scores") or {}).get("composite", 0.0) or 0.0),
                    "cost": float((row.get("session_features") or {}).get("total_cost", 0.0) or 0.0),
                    "shape": str((row.get("convergence") or {}).get("shape", "unknown")),
                    "recoverable_cost_total_usd": float(row.get("recoverable_cost_total_usd", 0.0) or 0.0),
                }
                for row in sorted(per_session_v2, key=lambda r: float((r.get("session_features") or {}).get("total_cost", 0.0) or 0.0), reverse=True)
            ],
        }
    else:
        project_rollup = {"session_count": 0, "dimensions": {}, "composite": 0.0, "recoverable_cost_total_usd": 0.0, "flag_frequency": {}, "session_efficiency_distribution": []}

    report: Dict[str, Any] = {
        "session_features": session_features,
        "turn_features": features["turn_features"],
        "rule_violations": [],
        "scores": project_rollup,
        "total_cost_derived": total_cost_derived,
        "v2": {
            "scores": project_rollup,
            "project_rollup": project_rollup,
            "per_session_v2": per_session_v2,
        },
        "multi_agent": multi_agent,
    }

    if multi_agent:
        per_session = []
        for row in per_session_v2:
            session_metrics = row["session_features"]
            per_session.append(
                {
                    "session_id": row["session_id"],
                    "turns": session_metrics["total_turns"],
                    "tokens": session_metrics["total_tokens"],
                    "cost": session_metrics["total_cost"],
                }
            )
        report["per_session"] = sorted(per_session, key=lambda row: row["cost"], reverse=True)

    return report


def _resolve_profile(
    events,
    cost_mode: CostMode,
    pricing_file: Path | None,
) -> Dict[str, Any]:
    custom_split_pricing = None
    custom_blended_pricing = None
    pricing_file_label = "default"
    if pricing_file is not None:
        if not pricing_file.exists():
            raise FileNotFoundError(f"Pricing file not found: {pricing_file}")
        custom_split_pricing, custom_blended_pricing = load_pricing_file(pricing_file)
        pricing_file_label = str(pricing_file)

    records: List[Dict[str, Any]] = []
    cost_sources: Counter[str] = Counter()
    total_cost = 0.0
    total_tokens = 0

    for event in events:
        cost, source = resolve_cost(
            cost_mode,
            event.provider_cost_usd,
            event.model,
            event.usage,
            split_pricing=custom_split_pricing,
            blended_pricing=custom_blended_pricing,
        )
        no_cache_cost = estimate_no_cache_cost(event.model, event.usage, split_pricing=custom_split_pricing)
        source_value = source.value
        cost_sources[source_value] += 1
        total_cost += cost
        total_tokens += event.usage.total_tokens
        records.append(_to_record(event, cost=cost, cost_source=source_value, no_cache_cost=no_cache_cost))

    return {
        "records": records,
        "cost_sources": cost_sources,
        "total_cost": total_cost,
        "total_tokens": total_tokens,
        "pricing_file": pricing_file_label,
    }


def _load_analysis_inputs(
    path: str,
    billable_only: bool,
    dedupe: bool,
    pricing_file: Optional[Path],
    scoring_config: Optional[Path],
    cost_mode: CostMode,
) -> Dict[str, Any]:
    root = Path(path)
    if not root.exists():
        typer.echo(f"Path not found: {root}", err=True)
        raise typer.Exit(code=1)

    files = find_jsonl_files(root)
    if not files:
        typer.echo(f"No .jsonl files found under {root}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Discovered {len(files)} JSONL files")
    events = load_events(root, billable_only=billable_only)
    if not events:
        typer.echo("No events available after filtering.", err=True)
        raise typer.Exit(code=1)

    dedupe_stats = {"input_events": len(events), "output_events": len(events), "duplicates_removed": 0}
    if dedupe:
        events, dedupe_stats = dedupe_events(events)

    custom_split_pricing = None
    custom_blended_pricing = None
    if pricing_file:
        if not pricing_file.exists():
            typer.echo(f"Pricing file not found: {pricing_file}", err=True)
            raise typer.Exit(code=1)
        custom_split_pricing, custom_blended_pricing = load_pricing_file(pricing_file)
        typer.echo(f"Loaded pricing file: {pricing_file}")

    cfg = None
    if scoring_config:
        if not scoring_config.exists():
            typer.echo(f"Scoring config file not found: {scoring_config}", err=True)
            raise typer.Exit(code=1)
        cfg = load_scoring_config(scoring_config)
        typer.echo(f"Loaded scoring config file: {scoring_config}")

    records: List[Dict[str, Any]] = []
    cost_sources: Counter[str] = Counter()
    for event in events:
        cost, source = resolve_cost(
            cost_mode,
            event.provider_cost_usd,
            event.model,
            event.usage,
            split_pricing=custom_split_pricing,
            blended_pricing=custom_blended_pricing,
        )
        no_cache_cost = estimate_no_cache_cost(event.model, event.usage, split_pricing=custom_split_pricing)
        source_value = source.value
        cost_sources[source_value] += 1
        records.append(_to_record(event, cost=cost, cost_source=source_value, no_cache_cost=no_cache_cost))

    typer.echo(f"Loaded {len(records)} normalized records")
    return {
        "records": records,
        "cost_sources": cost_sources,
        "dedupe_stats": dedupe_stats,
        "config": cfg,
        "pricing_file": str(pricing_file) if pricing_file else None,
    }


def _run_insights_refresh() -> Path:
    """Run claude -p '/insights' to regenerate the Insights HTML report.

    Returns the fixed output path: ~/.claude/usage-data/report.html
    Raises RuntimeError if the command fails or the file is not created.
    """
    # Remove CLAUDECODE from env to bypass nested session guard
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    try:
        result = subprocess.run(
            ["claude", "-p", "/insights"],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )
        if result.returncode != 0:
            error_msg = f"claude -p '/insights' failed with code {result.returncode}"
            if result.stderr:
                error_msg += f"\nStderr: {result.stderr}"
            if result.stdout:
                error_msg += f"\nStdout: {result.stdout}"
            typer.echo(error_msg, err=True)
            raise RuntimeError(error_msg)
    except FileNotFoundError:
        raise RuntimeError("claude command not found in PATH")
    except subprocess.TimeoutExpired:
        raise RuntimeError("claude -p '/insights' timed out after 5 minutes")

    insights_path = Path.home() / ".claude" / "usage-data" / "report.html"
    if not insights_path.exists():
        raise RuntimeError(f"Insights report was not created at {insights_path}")

    return insights_path


@app.command()
def analyze(
    path: str,
    export: Optional[Path] = typer.Option(None, "--export", help="Export markdown report to a file path."),
    insights_html: Optional[Path] = typer.Option(None, "--insights-html", help="Path to Claude Code Insights HTML report to inject token economics section into."),
    refresh_insights: bool = typer.Option(False, "--refresh-insights", help="Run 'claude -p /insights' to regenerate the Insights HTML report before injecting."),
    multi_session: bool = typer.Option(
        False,
        "--multi-session/--single-session",
        help="Show per-session breakdown in report output.",
    ),
    multi_agent: bool = typer.Option(
        False,
        "--multi-agent",
        hidden=True,
        help="Deprecated alias for --multi-session.",
    ),
    cost_mode: CostMode = typer.Option(CostMode.AUTO, "--cost-mode", help="Cost source strategy: auto, reported-only, derived-only."),
    billable_only: bool = typer.Option(False, "--billable-only/--all-events", help="Use billable assistant events only (hides user/progress signals)."),
    dedupe: bool = typer.Option(True, "--dedupe/--no-dedupe", help="Enable event deduplication by request/response ids."),
    pricing_file: Optional[Path] = typer.Option(None, "--pricing-file", help="Optional JSON file with split_per_1k and blended_per_1k pricing maps."),
    scoring_config: Optional[Path] = typer.Option(None, "--scoring-config", help="Optional JSON file with scoring thresholds and multipliers."),
    llm_recommendations: bool = typer.Option(False, "--llm-recommendations", help="Generate project-level recommendations with a local Ollama model."),
    llm_session_recommendations: bool = typer.Option(False, "--llm-session-recommendations", help="Also generate per-session recommendations. Implies --llm-recommendations."),
    llm_model: str = typer.Option("llama3.2:3b", "--llm-model", help="Ollama model to use for report recommendations."),
    llm_endpoint: str = typer.Option("http://localhost:11434", "--llm-endpoint", help="Ollama HTTP endpoint."),
    llm_timeout_sec: float = typer.Option(30.0, "--llm-timeout-sec", help="Timeout in seconds for Ollama availability and generation calls."),
):
    """Analyze AI coding sessions to measure and optimize prompt efficiency."""
    analysis = _load_analysis_inputs(
        path=path,
        billable_only=billable_only,
        dedupe=dedupe,
        pricing_file=pricing_file,
        scoring_config=scoring_config,
        cost_mode=cost_mode,
    )
    report = _build_report(
        analysis["records"],
        multi_agent=multi_agent or multi_session,
        dedupe_stats=analysis["dedupe_stats"],
        cost_sources=analysis["cost_sources"],
        pricing_mode=cost_mode.value,
        pricing_file=analysis["pricing_file"],
        config=analysis["config"],
    )
    if llm_recommendations or llm_session_recommendations:
        report = enrich_report_with_recommendations(
            report,
            RecommendationConfig(
                endpoint=llm_endpoint,
                model=llm_model,
                timeout_sec=llm_timeout_sec,
                include_session_recommendations=llm_session_recommendations,
            ),
        )
    render_cli_report(report)

    if export:
        export_markdown_report(report, export)
        typer.echo(f"Markdown report exported to {export}")

    if refresh_insights:
        insights_html = _run_insights_refresh()
        typer.echo(f"Insights report regenerated at {insights_html}")

    if insights_html:
        from .reporter import inject_into_insights_html
        inject_into_insights_html(report, insights_html, sessions_scan_path=Path(path))
        typer.echo(f"Token economics injected into Insights HTML at {insights_html}")


@app.command("cost-range")
def cost_range(
    path: str,
    cost_mode: CostMode = typer.Option(CostMode.AUTO, "--cost-mode", help="Cost source strategy: auto, reported-only, derived-only."),
    billable_only: bool = typer.Option(True, "--billable-only/--all-events", help="Use billable terminal events only."),
    dedupe: bool = typer.Option(True, "--dedupe/--no-dedupe", help="Enable event deduplication by request/response ids."),
    conservative_file: Optional[Path] = typer.Option(None, "--conservative-file", help="Pricing JSON for conservative estimate."),
    aggressive_file: Optional[Path] = typer.Option(None, "--aggressive-file", help="Pricing JSON for aggressive estimate."),
):
    """Compute min/default/max cost estimates across pricing profiles."""
    root = Path(path)
    if not root.exists():
        typer.echo(f"Path not found: {root}", err=True)
        raise typer.Exit(code=1)

    files = find_jsonl_files(root)
    if not files:
        typer.echo(f"No .jsonl files found under {root}", err=True)
        raise typer.Exit(code=1)

    project_root = Path(__file__).resolve().parent.parent
    conservative_file = conservative_file or (project_root / "pricing.conservative.json")
    aggressive_file = aggressive_file or (project_root / "pricing.aggressive.json")

    typer.echo(f"Discovered {len(files)} JSONL files")
    events = load_events(root, billable_only=billable_only)
    if not events:
        typer.echo("No events available after filtering.", err=True)
        raise typer.Exit(code=1)

    input_count = len(events)
    duplicates_removed = 0
    if dedupe:
        events, dedupe_stats = dedupe_events(events)
        duplicates_removed = dedupe_stats["duplicates_removed"]

    default_profile = _resolve_profile(events, cost_mode, pricing_file=None)
    conservative_profile = _resolve_profile(events, cost_mode, pricing_file=conservative_file)
    aggressive_profile = _resolve_profile(events, cost_mode, pricing_file=aggressive_file)

    default_cost = default_profile["total_cost"]
    low_cost = conservative_profile["total_cost"]
    high_cost = aggressive_profile["total_cost"]

    typer.echo("Cost Range Summary")
    typer.echo(f"- Events (input -> analyzed): {input_count} -> {len(events)}")
    typer.echo(f"- Duplicates removed: {duplicates_removed}")
    typer.echo(f"- Tokens analyzed: {default_profile['total_tokens']}")
    typer.echo(f"- Conservative: ${low_cost:.4f} ({conservative_file})")
    typer.echo(f"- Default:      ${default_cost:.4f} (built-in pricing)")
    typer.echo(f"- Aggressive:   ${high_cost:.4f} ({aggressive_file})")
    typer.echo(f"- Range spread: ${high_cost - low_cost:.4f}")
    typer.echo(f"- Default vs Conservative: ${default_cost - low_cost:.4f}")
    typer.echo(f"- Aggressive vs Default: ${high_cost - default_cost:.4f}")


@app.command()
def compare(_: str = typer.Argument("")):
    """Placeholder for Phase 6 compare command."""
    typer.echo("compare command will be implemented in Phase 6")


if __name__ == "__main__":
    app()
