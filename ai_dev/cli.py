from __future__ import annotations

import os
import subprocess
import sys
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

import typer

from .costing import bundled_pricing, bundled_pricing_json, estimate_no_cache_cost, load_pricing_file, resolve_cost
from .dedupe import dedupe_events
from .feature_extractor import build_feature_bundle
from .html_reports import export_standalone_html
from .instruction_candidates import build_instruction_candidates, render_instruction_candidates_markdown
from .llm_recommendations import RecommendationConfig, enrich_report_with_recommendations
from .models import CostMode, PricingProfile, SessionSource
from .parser import find_jsonl_files, load_events
from .analyzer_v2 import analyze_v2
from .reporter import export_markdown_report, render_cli_report
from .scoring_config import ScoringConfig, load_scoring_config

app = typer.Typer(no_args_is_help=True)


def _display_project_folder(source_file: str) -> str:
    encoded = Path(source_file).parent.name if source_file else "unknown"
    marker = "-projects-git-"
    display = encoded.split(marker, 1)[1] if marker in encoded else encoded
    worktree_marker = "--claude-worktrees-"
    if worktree_marker in display:
        project, worktree = display.split(worktree_marker, 1)
        return f"{project} (worktree: {worktree})"
    return display or "unknown"


def _encode_claude_project_path(path: Path) -> str:
    return path.resolve(strict=False).as_posix().replace("/", "-")


def _path_is_within(candidate: Path, root: Path) -> bool:
    candidate_resolved = candidate.resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    try:
        return os.path.commonpath([str(candidate_resolved), str(root_resolved)]) == str(root_resolved)
    except ValueError:
        return False


def _event_matches_project_root(event: Any, source: SessionSource, project_root: Path) -> bool:
    if source == SessionSource.CODEX:
        project_cwd = str(event.payload.get("_project_cwd") or "")
        if not project_cwd:
            return False
        return _path_is_within(Path(project_cwd).expanduser(), project_root)

    encoded_root = _encode_claude_project_path(project_root)
    parent_name = Path(event.source_file).parent.name
    return parent_name == encoded_root or parent_name.startswith(f"{encoded_root}--claude-worktrees-")


def _resolve_current_repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Current directory is not inside a git repository.")
    return Path(result.stdout.strip()).expanduser().resolve(strict=False)


def _resolve_pricing_inputs(
    pricing_file: Path | None,
    pricing_profile: PricingProfile,
) -> tuple[Dict[str, Dict[str, float]] | None, Dict[str, float] | None, str]:
    if pricing_file is not None and pricing_profile != PricingProfile.DEFAULT:
        raise typer.BadParameter("Use either --pricing-file or --pricing-profile, not both.", param_hint="--pricing-file")
    if pricing_file is not None:
        if not pricing_file.exists():
            raise FileNotFoundError(f"Pricing file not found: {pricing_file}")
        split_pricing, blended_pricing = load_pricing_file(pricing_file)
        return split_pricing, blended_pricing, str(pricing_file)
    if pricing_profile != PricingProfile.DEFAULT:
        split_pricing, blended_pricing = bundled_pricing(pricing_profile)
        return split_pricing, blended_pricing, f"bundled:{pricing_profile.value}"
    return None, None, "default"


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
    payload["_agent_id"] = payload.get("_agent_id") or event.agent_id
    payload["_source_file"] = event.source_file
    payload["_line_num"] = event.line_num
    payload["_agent_type"] = payload.get("_agent_type") or (
        "subagent" if "subagents" in Path(event.source_file).parts else "primary"
    )
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
    source: SessionSource = SessionSource.CLAUDE,
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
        explicit_project = next(
            (str(row.get("_project_folder") or "") for row in session_records if row.get("_project_folder")),
            "",
        )
        project_folder = explicit_project or _display_project_folder(source_file)

        session_bundle = build_feature_bundle(session_records, cfg)
        if int(session_bundle["session_features"].get("total_turns", 0) or 0) == 0:
            continue
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

        # Roll up the actual final session composites so project scoring retains
        # the recoverable-cost penalty applied by compute_v2_scores(). Summing
        # dimensions here would silently discard that penalty.
        composite_num = 0.0
        composite_den = 0.0
        for row in per_session_v2:
            cost = float((row.get("session_features") or {}).get("total_cost", 0.0) or 0.0)
            weight = cost if cost > 0 else 1.0
            composite_num += float((row.get("scores") or {}).get("composite", 0.0) or 0.0) * weight
            composite_den += weight
        rolled_composite = round(composite_num / composite_den, 2) if composite_den > 0 else 0.0

        flag_frequency: Counter[str] = Counter()
        for row in per_session_v2:
            for flag in (row.get("flags") or []):
                flag_frequency[str(flag.get("flag_id") or "")] += int(flag.get("occurrences", 0) or 0)

        project_rollup = {
            "session_count": len(per_session_v2),
            "dimensions": rolled_dimensions,
            "composite": rolled_composite,
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
        "source": source.value,
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
    pricing_profile: PricingProfile = PricingProfile.DEFAULT,
) -> Dict[str, Any]:
    custom_split_pricing, custom_blended_pricing, pricing_file_label = _resolve_pricing_inputs(
        pricing_file,
        pricing_profile,
    )

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
    pricing_profile: PricingProfile,
    scoring_config: Optional[Path],
    cost_mode: CostMode,
    source: SessionSource = SessionSource.CLAUDE,
    current_repo_only: bool = False,
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
    events = load_events(root, billable_only=billable_only, source=source.value)
    if not events:
        typer.echo("No events available after filtering.", err=True)
        raise typer.Exit(code=1)

    if current_repo_only:
        repo_root = _resolve_current_repo_root()
        original_count = len(events)
        events = [event for event in events if _event_matches_project_root(event, source, repo_root)]
        typer.echo(f"Filtered to current repo ({repo_root}): {len(events)} of {original_count} events")
        if not events:
            typer.echo("No events matched the current repository.", err=True)
            raise typer.Exit(code=1)

    dedupe_stats = {"input_events": len(events), "output_events": len(events), "duplicates_removed": 0}
    if dedupe:
        events, dedupe_stats = dedupe_events(events)

    try:
        custom_split_pricing, custom_blended_pricing, pricing_label = _resolve_pricing_inputs(
            pricing_file,
            pricing_profile,
        )
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if pricing_file:
        typer.echo(f"Loaded pricing file: {pricing_file}")
    elif pricing_profile != PricingProfile.DEFAULT:
        typer.echo(f"Using bundled pricing profile: {pricing_profile.value}")

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
        "pricing_file": pricing_label,
    }


def _normalize_insights_html_flag(argv: list[str]) -> list[str]:
    normalized = []
    idx = 0
    while idx < len(argv):
        arg = argv[idx]
        if arg == "--insights-html":
            next_arg = argv[idx + 1] if idx + 1 < len(argv) else None
            if next_arg is None or next_arg.startswith("--"):
                normalized.append("--insights-html=")
            else:
                normalized.append(arg)
            idx += 1
            continue
        normalized.append(arg)
        idx += 1
    return normalized


def _find_latest_insights_report() -> Path:
    insights_dir = Path.home() / ".claude" / "usage-data"
    if not insights_dir.exists() or not insights_dir.is_dir():
        raise FileNotFoundError(
            f"Claude Insights directory not found: {insights_dir}. Run `claude -p /insights` first."
        )

    candidates = sorted(
        [p for p in insights_dir.glob("report*.html") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            f"No Insights HTML reports found under {insights_dir}."
        )
    return candidates[0]


def _resolve_insights_html_option(insights_html: Optional[str]) -> Optional[Path]:
    if insights_html is None:
        return None
    if insights_html == "":
        return _find_latest_insights_report()

    if insights_html.startswith("file://"):
        parsed = urllib.parse.urlparse(insights_html)
        if parsed.scheme != "file" or not parsed.path:
            raise ValueError(f"Invalid file URI for Insights HTML: {insights_html}")
        return Path(parsed.path)

    return Path(insights_html).expanduser()


def _run_insights_refresh() -> Path:
    """Run claude -p '/insights' to regenerate the Insights HTML report.

    Returns the most recently generated report under ~/.claude/usage-data
    (Claude Code may name it report.html, a timestamped report-*.html, or both).
    Raises RuntimeError if the command fails or no report file is found.
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

    try:
        return _find_latest_insights_report()
    except FileNotFoundError as exc:
        raise RuntimeError(str(exc)) from exc


@app.command()
def analyze(
    path: str,
    source: SessionSource = typer.Option(SessionSource.CLAUDE, "--source", help="Session format: claude or codex."),
    export: Optional[Path] = typer.Option(None, "--export", help="Export markdown report to a file path."),
    insights_html: Optional[str] = typer.Option(
        None,
        "--insights-html",
        help="Optional file path or file URI to Claude Code Insights HTML report to inject token economics into. Use `--insights-html=` or the bare flag to auto-select the latest generated report.",
    ),
    refresh_insights: bool = typer.Option(False, "--refresh-insights", help="Run 'claude -p /insights' to regenerate the Insights HTML report before injecting."),
    standalone_html: Optional[Path] = typer.Option(None, "--standalone-html", help="Write a standalone evidence-drill-down HTML report."),
    instructions_output: Optional[Path] = typer.Option(None, "--instructions-output", help="Write reviewable AGENTS.md/CLAUDE.md instruction candidates."),
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
    pricing_profile: PricingProfile = typer.Option(PricingProfile.DEFAULT, "--pricing-profile", help="Bundled pricing profile: default, conservative, or aggressive."),
    current_repo_only: bool = typer.Option(False, "--current-repo-only", help="Only analyze sessions attributed to the current git repository."),
    scoring_config: Optional[Path] = typer.Option(None, "--scoring-config", help="Optional JSON file with scoring thresholds and multipliers."),
    llm_recommendations: bool = typer.Option(False, "--llm-recommendations", help="Generate project-level recommendations with a local Ollama model."),
    llm_session_recommendations: bool = typer.Option(False, "--llm-session-recommendations", help="Also generate per-session recommendations. Implies --llm-recommendations."),
    llm_model: str = typer.Option("llama3.2:3b", "--llm-model", help="Ollama model to use for report recommendations."),
    llm_endpoint: str = typer.Option("http://localhost:11434", "--llm-endpoint", help="Ollama HTTP endpoint."),
    llm_timeout_sec: float = typer.Option(30.0, "--llm-timeout-sec", help="Timeout in seconds for Ollama availability and generation calls."),
):
    """Analyze AI coding sessions to measure and optimize prompt efficiency."""
    if source == SessionSource.CODEX and (refresh_insights or insights_html is not None):
        raise typer.BadParameter(
            "Claude Insights augmentation is unavailable for --source codex; use --standalone-html.",
            param_hint="--source",
        )
    analysis = _load_analysis_inputs(
        path=path,
        billable_only=billable_only,
        dedupe=dedupe,
        pricing_file=pricing_file,
        pricing_profile=pricing_profile,
        scoring_config=scoring_config,
        cost_mode=cost_mode,
        source=source,
        current_repo_only=current_repo_only,
    )
    report = _build_report(
        analysis["records"],
        multi_agent=multi_agent or multi_session,
        dedupe_stats=analysis["dedupe_stats"],
        cost_sources=analysis["cost_sources"],
        pricing_mode=cost_mode.value,
        pricing_file=analysis["pricing_file"],
        source=source,
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

    if standalone_html:
        export_standalone_html(report, standalone_html)
        typer.echo(f"Standalone evidence report exported to {standalone_html}")

    if instructions_output:
        candidates = build_instruction_candidates(report)
        instructions_output.parent.mkdir(parents=True, exist_ok=True)
        instructions_output.write_text(render_instruction_candidates_markdown(candidates), encoding="utf-8")
        typer.echo(f"Instruction candidates exported to {instructions_output}")

    if refresh_insights:
        insights_html = _run_insights_refresh()
        typer.echo(f"Insights report regenerated at {insights_html}")
    elif insights_html is not None:
        insights_html = _resolve_insights_html_option(insights_html)

    if insights_html:
        from .reporter import inject_into_insights_html
        inject_into_insights_html(report, insights_html, sessions_scan_path=Path(path))
        typer.echo(f"Token economics injected into Insights HTML at {insights_html}")


@app.command()
def insights(
    path: Optional[Path] = typer.Argument(None, help="Session directory. Defaults from --source."),
    source: SessionSource = typer.Option(SessionSource.CLAUDE, "--source", help="Session format: claude or codex."),
    refresh: bool = typer.Option(False, "--refresh", help="Regenerate Claude Insights before augmentation."),
    insights_html: Optional[Path] = typer.Option(None, "--insights-html", help="Existing Claude Insights HTML. Defaults to the latest report."),
    output: Optional[Path] = typer.Option(None, "--output", help="Standalone evidence report path."),
    instructions_output: Optional[Path] = typer.Option(None, "--instructions-output", help="Markdown path for reviewable instruction candidates. Defaults beside the HTML reports."),
    pricing_file: Optional[Path] = typer.Option(None, "--pricing-file", help="Optional pricing profile."),
    pricing_profile: PricingProfile = typer.Option(PricingProfile.DEFAULT, "--pricing-profile", help="Bundled pricing profile: default, conservative, or aggressive."),
    current_repo_only: bool = typer.Option(False, "--current-repo-only", help="Only analyze sessions attributed to the current git repository."),
    scoring_config: Optional[Path] = typer.Option(None, "--scoring-config", help="Optional scoring thresholds."),
):
    """Create session evidence reports for Claude Code or Codex."""
    if source == SessionSource.CODEX and refresh:
        raise typer.BadParameter("--refresh is only available for Claude Insights.", param_hint="--refresh")
    if source == SessionSource.CODEX and insights_html:
        raise typer.BadParameter("--insights-html is only available for Claude Insights.", param_hint="--insights-html")

    selected_path = (path or (
        Path.home() / ".codex" / "sessions"
        if source == SessionSource.CODEX
        else Path.home() / ".claude" / "projects"
    )).expanduser()
    analysis = _load_analysis_inputs(
        path=str(selected_path),
        billable_only=False,
        dedupe=True,
        pricing_file=pricing_file,
        pricing_profile=pricing_profile,
        scoring_config=scoring_config,
        cost_mode=CostMode.AUTO,
        source=source,
        current_repo_only=current_repo_only,
    )
    report = _build_report(
        analysis["records"],
        multi_agent=True,
        dedupe_stats=analysis["dedupe_stats"],
        cost_sources=analysis["cost_sources"],
        pricing_mode=CostMode.AUTO.value,
        pricing_file=analysis["pricing_file"],
        source=source,
        config=analysis["config"],
    )

    if source == SessionSource.CODEX:
        selected_insights = None
    elif refresh:
        selected_insights = _run_insights_refresh()
    elif insights_html:
        selected_insights = insights_html.expanduser()
    else:
        selected_insights = _find_latest_insights_report()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = selected_insights.parent if selected_insights else Path.cwd() / ".ai-dev"
    source_label = source.value
    standalone_path = (
        output.expanduser()
        if output
        else output_dir / f"ai-dev-{source_label}-evidence-{timestamp}.html"
    )

    if selected_insights:
        from .reporter import inject_into_insights_html

        inject_into_insights_html(report, selected_insights, sessions_scan_path=selected_path)
    export_standalone_html(report, standalone_path)

    instruction_path = (
        instructions_output.expanduser()
        if instructions_output
        else output_dir / f"ai-dev-{source_label}-instructions-{timestamp}.md"
    )
    candidates = build_instruction_candidates(report)
    instruction_path.parent.mkdir(parents=True, exist_ok=True)
    instruction_path.write_text(render_instruction_candidates_markdown(candidates), encoding="utf-8")

    if selected_insights:
        typer.echo(f"Enhanced Claude Insights: {selected_insights}")
    typer.echo(f"Standalone evidence report: {standalone_path}")
    typer.echo(f"Reviewable project instructions: {instruction_path}")


@app.command("cost-range")
def cost_range(
    path: str,
    cost_mode: CostMode = typer.Option(CostMode.AUTO, "--cost-mode", help="Cost source strategy: auto, reported-only, derived-only."),
    billable_only: bool = typer.Option(True, "--billable-only/--all-events", help="Use billable terminal events only."),
    dedupe: bool = typer.Option(True, "--dedupe/--no-dedupe", help="Enable event deduplication by request/response ids."),
    conservative_file: Optional[Path] = typer.Option(None, "--conservative-file", help="Pricing JSON for conservative estimate."),
    aggressive_file: Optional[Path] = typer.Option(None, "--aggressive-file", help="Pricing JSON for aggressive estimate."),
    current_repo_only: bool = typer.Option(False, "--current-repo-only", help="Only analyze sessions attributed to the current git repository."),
    source: SessionSource = typer.Option(SessionSource.CLAUDE, "--source", help="Session format: claude or codex."),
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
    events = load_events(root, billable_only=billable_only, source=source.value)
    if not events:
        typer.echo("No events available after filtering.", err=True)
        raise typer.Exit(code=1)

    if current_repo_only:
        repo_root = _resolve_current_repo_root()
        original_count = len(events)
        events = [event for event in events if _event_matches_project_root(event, source, repo_root)]
        typer.echo(f"Filtered to current repo ({repo_root}): {len(events)} of {original_count} events")
        if not events:
            typer.echo("No events matched the current repository.", err=True)
            raise typer.Exit(code=1)

    input_count = len(events)
    duplicates_removed = 0
    if dedupe:
        events, dedupe_stats = dedupe_events(events)
        duplicates_removed = dedupe_stats["duplicates_removed"]

    default_profile = _resolve_profile(events, cost_mode, pricing_file=None, pricing_profile=PricingProfile.DEFAULT)
    conservative_profile = _resolve_profile(
        events,
        cost_mode,
        pricing_file=conservative_file,
        pricing_profile=PricingProfile.CONSERVATIVE if conservative_file is None else PricingProfile.DEFAULT,
    )
    aggressive_profile = _resolve_profile(
        events,
        cost_mode,
        pricing_file=aggressive_file,
        pricing_profile=PricingProfile.AGGRESSIVE if aggressive_file is None else PricingProfile.DEFAULT,
    )

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


@app.command("pricing-template")
def pricing_template(
    output: Path = typer.Argument(..., help="Where to write the pricing JSON template."),
    profile: PricingProfile = typer.Option(PricingProfile.DEFAULT, "--profile", help="Bundled pricing profile to export."),
):
    """Write a bundled pricing profile JSON file for inspection or customization."""
    output = output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(bundled_pricing_json(profile), encoding="utf-8")
    typer.echo(f"Pricing template exported to {output} ({profile.value})")


def main(argv: Optional[list[str]] = None) -> None:
    if argv is None:
        argv = sys.argv[1:]
    argv = _normalize_insights_html_flag(argv)
    app(argv)


if __name__ == "__main__":
    main()
