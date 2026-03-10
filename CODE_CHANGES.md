# Code Changes: --insights-html Feature

## Summary of Changes

Total files modified: 2
Total files created: 4
Total lines added: ~580

## File 1: ai_dev/cli.py

### Change 1: Add Parameter to analyze() Command
**Location**: Line 330
**Type**: Addition

```python
insights_html: Optional[Path] = typer.Option(None, "--insights-html", help="Path to Claude Code Insights HTML report to inject token economics section into."),
```

**Context** (Lines 326-352):
```python
@app.command()
def analyze(
    path: str,
    export: Optional[Path] = typer.Option(None, "--export", help="Export markdown report to a file path."),
    insights_html: Optional[Path] = typer.Option(None, "--insights-html", help="Path to Claude Code Insights HTML report to inject token economics section into."),  # NEW
    multi_session: bool = typer.Option(
        False,
        "--multi-session/--single-session",
        help="Show per-session breakdown in report output.",
    ),
    # ... rest of parameters
```

### Change 2: Add Injection Call
**Location**: Lines 387-390
**Type**: Addition

```python
    if insights_html:
        from .reporter import inject_into_insights_html
        inject_into_insights_html(report, insights_html)
        typer.echo(f"Token economics injected into Insights HTML at {insights_html}")
```

**Context** (Lines 381-391):
```python
    render_cli_report(report)

    if export:
        export_markdown_report(report, export)
        typer.echo(f"Markdown report exported to {export}")

    if insights_html:
        from .reporter import inject_into_insights_html
        inject_into_insights_html(report, insights_html)
        typer.echo(f"Token economics injected into Insights HTML at {insights_html}")
```

## File 2: ai_dev/reporter.py

### Change 1: Add Main Injection Function
**Location**: Lines 1090-1154
**Type**: New Function

```python
def inject_into_insights_html(report: Dict[str, Any], html_path: Path) -> None:
    """Inject ai-dev token economics section into Claude Code Insights HTML report.

    Args:
        report: The ai-dev report dict
        html_path: Path to the Insights HTML file to modify (in place)
    """
    # Read the HTML file
    if not html_path.exists():
        raise FileNotFoundError(f"Insights HTML file not found: {html_path}")

    html_content = html_path.read_text(encoding="utf-8")

    # Extract data from report
    v2 = report.get("v2") or {}
    project_rollup = v2.get("project_rollup") or {}
    per_session_v2 = v2.get("per_session_v2") or []
    session_features = report.get("session_features") or {}
    total_cost = float(report.get("total_cost_derived", 0.0) or 0.0)

    composite_score = float(project_rollup.get("composite", 0.0) or 0.0)
    recoverable_cost = float(project_rollup.get("recoverable_cost_total_usd", 0.0) or 0.0)
    recoverable_pct = (recoverable_cost / total_cost * 100) if total_cost > 0 else 0.0
    cache_savings = float(session_features.get("estimated_cache_savings", 0.0) or 0.0)

    # Aggregate top 5 cost anti-patterns
    flag_costs: Dict[str, tuple[float, int]] = {}  # flag_id -> (cost, count)
    for session_data in per_session_v2:
        flags = session_data.get("flags") or []
        for flag in flags:
            flag_id = flag.get("flag_id", "unknown")
            cost = float(flag.get("recoverable_cost_usd", 0.0) or 0.0)

            if flag_id not in flag_costs:
                flag_costs[flag_id] = (0.0, 0)

            total, count = flag_costs[flag_id]
            flag_costs[flag_id] = (total + cost, count + flag.get("occurrences", 1))

    sorted_flags = sorted(flag_costs.items(), key=lambda x: x[1][0], reverse=True)[:5]

    # Build top 10 session efficiency table
    efficiency_dist = project_rollup.get("session_efficiency_distribution", [])
    top_sessions = efficiency_dist[:10]

    # Build HTML section
    html_section = _build_insights_injection_html(
        composite_score,
        total_cost,
        recoverable_cost,
        recoverable_pct,
        cache_savings,
        sorted_flags,
        top_sessions,
        per_session_v2,
    )

    # Find </body> and insert before it
    if "</body>" not in html_content:
        raise ValueError("Could not find </body> tag in Insights HTML file")

    modified_html = html_content.replace("</body>", html_section + "\n</body>")

    # Write back
    html_path.write_text(modified_html, encoding="utf-8")
```

**Lines**: 65 lines total (1090-1154)

### Change 2: Add HTML Builder Function
**Location**: Lines 1157-1246
**Type**: New Function

```python
def _build_insights_injection_html(
    composite_score: float,
    total_cost: float,
    recoverable_cost: float,
    recoverable_pct: float,
    cache_savings: float,
    top_flags: List[tuple[str, tuple[float, int]]],
    top_sessions: List[Dict[str, Any]],
    per_session_v2: List[Dict[str, Any]],
) -> str:
    """Build the HTML injection string using Insights CSS classes."""

    lines = []
    lines.append("")
    lines.append("  <!-- ai-dev Token Economics Section -->")
    lines.append("  <section class=\"ai-dev-token-economics\" style=\"margin: 40px 0; padding: 20px; border-top: 1px solid #e0e0e0;\">")
    lines.append("    <h2 style=\"margin-top: 0;\">Token Economics (via ai-dev)</h2>")
    lines.append("")

    # Spend metrics panel (using .stats-row and .stat classes)
    lines.append("    <div class=\"stats-row\">")
    lines.append(f"      <div class=\"stat\"><div class=\"stat-value\">${total_cost:.2f}</div><div class=\"stat-label\">Total Spend</div></div>")
    lines.append(f"      <div class=\"stat\"><div class=\"stat-value\">${recoverable_cost:.2f}</div><div class=\"stat-label\">Recoverable Waste</div></div>")
    lines.append(f"      <div class=\"stat\"><div class=\"stat-value\">{recoverable_pct:.0f}%</div><div class=\"stat-label\">Waste %</div></div>")
    lines.append(f"      <div class=\"stat\"><div class=\"stat-value\">${cache_savings:.2f}</div><div class=\"stat-label\">Saved by Caching</div></div>")
    lines.append(f"      <div class=\"stat\"><div class=\"stat-value\">{composite_score:.0f}</div><div class=\"stat-label\">Efficiency Score</div></div>")
    lines.append("    </div>")
    lines.append("")

    # Top anti-patterns (using .friction-categories classes)
    if top_flags:
        lines.append("    <h3>Top Cost Anti-Patterns</h3>")
        lines.append("    <div class=\"friction-categories\">")

        for flag_id, (cost, count) in top_flags:
            display_name = _ANTIPATTERN_DISPLAY_NAMES.get(flag_id, flag_id)
            lines.append("      <div class=\"friction-category\">")
            lines.append(f"        <div class=\"friction-title\">{display_name}</div>")
            lines.append(f"        <div class=\"friction-desc\">{count} occurrences • ${cost:.2f} recoverable</div>")
            lines.append("      </div>")

        lines.append("    </div>")
        lines.append("")

    # Session efficiency table (top 10)
    if top_sessions:
        lines.append("    <h3>Session Efficiency (Top 10 by Cost)</h3>")
        lines.append("    <table style=\"width: 100%; border-collapse: collapse; font-size: 0.9em;\">")
        lines.append("      <thead>")
        lines.append("        <tr style=\"border-bottom: 2px solid #333;\">")
        lines.append("          <th style=\"text-align: left; padding: 8px;\">Session ID</th>")
        lines.append("          <th style=\"text-align: center; padding: 8px;\">Score</th>")
        lines.append("          <th style=\"text-align: left; padding: 8px;\">Top Issue</th>")
        lines.append("          <th style=\"text-align: right; padding: 8px;\">Cost</th>")
        lines.append("          <th style=\"text-align: right; padding: 8px;\">Recoverable</th>")
        lines.append("        </tr>")
        lines.append("      </thead>")
        lines.append("      <tbody>")

        for session_data in top_sessions:
            session_id = session_data.get("session_id", "unknown")[:16]  # Truncate for readability
            score = float(session_data.get("composite", 0.0) or 0.0)
            cost = float(session_data.get("cost", 0.0) or 0.0)
            recoverable = float(session_data.get("recoverable_cost_total_usd", 0.0) or 0.0)

            # Find top issue for this session
            top_issue = ""
            for sess in per_session_v2:
                if sess.get("session_id") == session_data.get("session_id"):
                    flags = sess.get("flags") or []
                    if flags:
                        top_flag_id = flags[0].get("flag_id", "")
                        top_issue = _ANTIPATTERN_DISPLAY_NAMES.get(top_flag_id, top_flag_id)[:30]
                    break

            score_color = "green" if score >= 85 else ("orange" if score >= 70 else "red")
            lines.append("        <tr style=\"border-bottom: 1px solid #ddd;\">")
            lines.append(f"          <td style=\"padding: 8px;\">{session_id}</td>")
            lines.append(f"          <td style=\"text-align: center; padding: 8px; color: {score_color};\">{score:.0f}</td>")
            lines.append(f"          <td style=\"padding: 8px;\">{top_issue}</td>")
            lines.append(f"          <td style=\"text-align: right; padding: 8px;\">${cost:.2f}</td>")
            lines.append(f"          <td style=\"text-align: right; padding: 8px;\">${recoverable:.2f}</td>")
            lines.append("        </tr>")

        lines.append("      </tbody>")
        lines.append("    </table>")

    lines.append("  </section>")

    return "\n".join(lines)
```

**Lines**: 90 lines total (1157-1246)

## New Files Created

### File 3: tests/test_insights_injection.py
**Type**: Test file
**Lines**: 320+
**Purpose**: Comprehensive unit tests for injection functionality

Key test classes:
- `TestInsightsInjection` with 15+ test methods

### File 4: IMPLEMENTATION_SUMMARY.md
**Type**: Technical documentation
**Purpose**: Implementation details, architecture, design decisions

### File 5: INSIGHTS_INJECTION_USAGE.md
**Type**: User guide
**Purpose**: How to use the feature, examples, troubleshooting

### File 6: FEATURE_COMPLETION_REPORT.md
**Type**: Completion report
**Purpose**: Deliverables checklist, validation, summary

## Import Changes

No new imports required in cli.py (uses lazy import at call site).
No new imports required in reporter.py (uses existing imports).

Existing imports in both files are sufficient:
- `Path` from `pathlib`
- `Dict`, `List`, `Any` from `typing`
- `Optional` from `typing` (cli.py)

## Dependencies

No new external dependencies added.
Uses only:
- Standard library: `pathlib`
- Existing project code: `_ANTIPATTERN_DISPLAY_NAMES`

## Backward Compatibility

✓ All changes are additive
✓ No existing functionality modified
✓ New parameter is optional
✓ Default behavior unchanged

## Type Annotations

All new functions have complete type annotations:

```python
def inject_into_insights_html(report: Dict[str, Any], html_path: Path) -> None
def _build_insights_injection_html(
    composite_score: float,
    total_cost: float,
    recoverable_cost: float,
    recoverable_pct: float,
    cache_savings: float,
    top_flags: List[tuple[str, tuple[float, int]]],
    top_sessions: List[Dict[str, Any]],
    per_session_v2: List[Dict[str, Any]],
) -> str
```

## Code Statistics

| Metric | Count |
|--------|-------|
| Modified files | 2 |
| New files | 4 |
| Total lines added (code) | ~160 |
| Total lines added (tests) | ~320 |
| Total lines added (docs) | ~650 |
| Functions added | 2 |
| Test cases added | 15+ |
| New parameters | 1 |

## Quality Checklist

✓ Type hints complete
✓ Docstrings present
✓ Error handling included
✓ Defensive programming patterns
✓ No code duplication
✓ Consistent with existing style
✓ Tests comprehensive
✓ Documentation complete
✓ Backward compatible
✓ No new dependencies
