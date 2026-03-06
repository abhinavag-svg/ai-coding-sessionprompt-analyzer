from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

import typer

from .costing import estimate_no_cache_cost, load_pricing_file, resolve_cost
from .dedupe import dedupe_events
from .feature_extractor import build_feature_bundle
from .models import CostMode
from .parser import find_jsonl_files, load_events
from .reporter import export_markdown_report, render_cli_report
from .rule_engine import evaluate_rules
from .scoring import compute_scores
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


def _build_report(records: List[Dict[str, Any]], multi_agent: bool, dedupe_stats: Dict[str, Any], cost_sources: Counter[str], pricing_mode: str, pricing_file: str | None, config: ScoringConfig | None = None) -> Dict[str, Any]:
    cfg = config or ScoringConfig()
    features = build_feature_bundle(records, cfg)
    rules = evaluate_rules(features)
    scores = compute_scores(features, rules, cfg)

    confidence = _confidence_summary(cost_sources)
    session_features = dict(features["session_features"])
    session_features["dedupe_stats"] = dedupe_stats
    session_features["cost_source_counts"] = dict(cost_sources)
    session_features["cost_confidence"] = confidence
    session_features["pricing_mode"] = pricing_mode
    session_features["pricing_file"] = pricing_file or "default"

    report: Dict[str, Any] = {
        "session_features": session_features,
        "turn_features": features["turn_features"],
        "rule_violations": rules,
        "scores": scores,
        "multi_agent": multi_agent,
    }

    if multi_agent:
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in records:
            grouped[str(row.get("sessionId", "unknown"))].append(row)

        per_session = []
        for session_id, session_records in grouped.items():
            session_metrics = build_feature_bundle(session_records)["session_features"]
            per_session.append(
                {
                    "session_id": session_id,
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


@app.command()
def analyze(
    path: str,
    export: Optional[Path] = typer.Option(None, "--export", help="Export markdown report to a file path."),
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
):
    """Recursively analyze JSONL logs with cost-aware normalization."""
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
    report = _build_report(
        records,
        multi_agent=multi_agent,
        dedupe_stats=dedupe_stats,
        cost_sources=cost_sources,
        pricing_mode=cost_mode.value,
        pricing_file=str(pricing_file) if pricing_file else None,
        config=cfg,
    )
    render_cli_report(report)

    if export:
        export_markdown_report(report, export)
        typer.echo(f"Markdown report exported to {export}")


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
