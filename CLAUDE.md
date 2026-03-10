# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AI Coding Prompt Optimizer** (codename: "Vibe Coding Optimizer") analyzes Claude Code sessions to measure and optimize AI prompt efficiency. The system reads session logs (JSONL format) and produces efficiency scores, cost breakdowns, and rule-based recommendations to help developers waste fewer tokens.

**Origin**: Built from lessons learned optimizing a production Shopify app development workflow in 7 days using only $20 in AI token budget.

## Key Insight: Token Cost Structure

**80% of token costs come from tool outputs (file reads, bash results), not the developer's actual text.** Developers typically optimize the wrong thing.

## Development Commands

### Setup
```bash
# Create and activate virtual environment
python3.10 -m venv venv
source venv/bin/activate  # macOS/Linux

# Install in development mode
pip install -e .

# Or run CLI directly without installation
python -m ai_dev.cli --help
```

### Main Commands

```bash
# Analyze JSONL session logs (recursive under path)
python -m ai_dev.cli analyze <path> [--export report.md] [--insights-html path/to/report.html]

# Options for analyze:
#   --multi-session       Show per-session breakdown
#   --cost-mode           auto | reported-only | derived-only
#   --billable-only/--all-events
#   --dedupe/--no-dedupe  Enable event deduplication
#   --pricing-file        Custom pricing JSON
#   --insights-html       Path to Claude Code Insights HTML to inject token economics into
#   --refresh-insights    Run 'claude -p /insights' to regenerate the Insights HTML before injecting (requires credits)

# Compute min/default/max cost ranges across pricing profiles
python -m ai_dev.cli cost-range <path> [--conservative-file file.json] [--aggressive-file file.json]
```

## Architecture

### Data Pipeline: Parse → Extract Features → Evaluate Rules → Score → Report

```
JSONL Files
    ↓
Parser (parser.py)
  - find_jsonl_files(): Discover .jsonl files recursively
  - iter_normalized_events(): Stream NormalizedEvent objects
  - _parse_usage(): Extract token counts (input, output, cache_read, cache_write)
  - _is_billable(): Filter terminal events only
    ↓
Costing (costing.py)
  - resolve_cost(): Map tokens → USD using split or blended pricing
  - CostMode: AUTO (intelligently select), REPORTED_ONLY, DERIVED_ONLY
    ↓
Feature Extraction (feature_extractor.py)
  - build_feature_bundle(): Extract metrics at turn and session level
  - Turn features: file paths detected, vague phrases, tool calls, corrections
  - Session features: total tokens, cost, correction ratio, file explosion events
    ↓
Rule Engine (rule_engine.py)
  - evaluate_rules(): Flag violations deterministically (no LLM)
  - File explosion: >5 reads with no file path in prompt
  - Model overkill: expensive model with low output tokens
  - High correction loop: correction_ratio > threshold
  - Repeated constraints: phrases appearing multiple times
  - Vague prompts: <50 words, no file path
    ↓
Scoring (scoring.py)
  - compute_scores(): Generate efficiency scores (0-100)
  - Prompt Clarity (0-25): file paths, function names, acceptance criteria
  - Context Efficiency (0-30): benchmark bands, repeated file reads
  - Rework Rate (0-15): prompt-induced corrections, repeated constraints
  - AI Consistency (0-10): model-induced corrections, unknown rework
  - Task Completion (0-20): session arc, convergence gates
  - Composite: weighted sum across dimensions
    ↓
Reporter (reporter.py)
  - render_cli_report(): Rich formatted CLI output
  - export_markdown_report(): Generate .md files with metrics/suggestions
```

### Data Models (models.py)

- **NormalizedEvent**: Core event wrapper with billing info, token buckets, session/request/message IDs
- **UsageBuckets**: Tracks input_tokens, output_tokens, cache_write_tokens, cache_read_tokens
- **CostMode** enum: AUTO, REPORTED_ONLY, DERIVED_ONLY
- **CostSource** enum: REPORTED, DERIVED_SPLIT, DERIVED_FALLBACK, UNKNOWN

### Key Modules Breakdown

| Module | Purpose |
|--------|---------|
| **cli.py** | Entry point with typer commands (analyze, cost-range, compare) |
| **parser.py** | JSONL ingestion, normalization, billability detection |
| **costing.py** | Token-to-USD conversion with flexible pricing strategies |
| **feature_extractor.py** | Compute turn and session metrics (corrections, file reads, vague phrases, etc.) |
| **rule_engine.py** | Deterministic rule evaluation (no LLM needed) |
| **scoring.py** | Efficiency score calculation with weighted subscores |
| **reporter.py** | CLI, markdown report generation, and Claude Code Insights HTML injection |
| **dedupe.py** | Event deduplication by request/response IDs |
| **constants.py** | Scoring thresholds, benchmark bands |

## Important Files

- **pyproject.toml**: Package metadata, entry point `ai-dev` command (requires `pip install -e .`)
- **pricing.example.json**, **pricing.conservative.json**, **pricing.aggressive.json**: Pricing models for cost estimation
- **docs/specs/product-spec.md**: Public product specification
- **docs/specs/technical-spec.md**: Detailed scoring model, anti-patterns, design decisions
- **AI-Coding-prompt-tasklist.md**: Development roadmap with phase breakdown

## Testing

**47 unit tests** (32 core + 15 new integration tests) covering:
- Anti-pattern flag detection (all 12 flags with boundary conditions)
- Session grouping and multi-agent auto-detection
- Per-session rollup generation
- Threshold-based rule logic (IDE context exclusion, etc.)
- V2 correction detection logic
- HTML insights injection (CLI integration, CSS rendering)

Run tests:
```bash
python -m pytest tests/ -v
```

All tests pass on main branch after scoring recalibration (PR #2) and HTML injection feature (latest).

## Design Notes

### Scoring Strategy (Current)

Five dimensions, weighted for non-overlapping coverage of efficiency:

| Display Name | Internal Key | Weight | What It Measures |
|---|---|---|---|
| Prompt Clarity | `specificity` | 25% | File paths, symbols, acceptance criteria in prompts |
| Context Efficiency | `context_scope` | 30% | Incremental tokens/turn, repeated file reads |
| Rework Rate | `correction_discipline` | 15% | Prompt-induced corrections, repeated constraints |
| AI Consistency | `model_stability` | 10% | Model-induced corrections, unknown failures |
| Task Completion | `session_convergence` | 20% | Session arc, convergence gates, correction spirals |

**Context Efficiency** uses **benchmark bands** for tokens per turn:
- Excellent: 1k–8k tokens/turn
- Normal: 8k–20k
- Heavy: 20k–40k
- Over-context: >40k sustained

**Industry guardrails**:
- Median tokens/turn target: <12k
- P90 tokens/turn target: <30k

Reports lead with actionable insights (Session Health, What to Fix) before dimension breakdowns.

### Cost Calculation

The system supports three cost modes:
1. **AUTO**: Prioritize reported costs from provider, fall back to derived split pricing, then blended pricing
2. **REPORTED_ONLY**: Use only provider-reported costs (may be incomplete)
3. **DERIVED_ONLY**: Calculate from token counts using custom pricing files

Pricing files are JSON with structure:
```json
{
  "split_per_1k": {
    "model-id": { "input": 0.003, "output": 0.015, "cache_read": 0.00075, "cache_write": 0.003 }
  },
  "blended_per_1k": {
    "model-id": 0.01
  }
}
```

## Common Workflows

### Analyze a Session
```bash
python -m ai_dev.cli analyze ~/.claude/projects/my-project --export report.md
```

### Compare Cost Estimates
```bash
python -m ai_dev.cli cost-range ~/.claude/projects/my-project
```

### Inject Token Economics into Claude Code Insights Report
```bash
# Option 1: Inject into existing Insights report (no credits needed)
python -m ai_dev.cli analyze ~/.claude/projects --insights-html ~/.claude/usage-data/report.html

# Option 2: Regenerate Insights report and inject (from terminal outside Claude Code)
python -m ai_dev.cli analyze ~/.claude/projects --refresh-insights
```

The injection adds:
- Token economics (cost, recoverable %) for each project area in "What You Work On"
- Session Efficiency table showing top sessions with sample prompts
- Anti-pattern insights woven into "Where Things Go Wrong" section

### Debug Event Parsing
Check `parser.py:iter_normalized_events()` for how JSONL lines are normalized. Key extraction points:
- `session_id` from payload or message
- `model` and `role` from payload or nested message
- Token buckets: input, output, cache_write (creation), cache_read
- `is_billable`: only terminal events with valid request/message IDs

### Add a New Anti-Pattern Flag (V2 Scoring)

1. Define flag in `v2_antipatterns.py:detect_antipatterns_v2()`
2. Populate flag dict:
   - `flag_id`: Unique identifier
   - `severity`: "high" | "medium" | "low"
   - `total_deduction_points`: Severity-scaled points (0-100 scale)
   - `allocations[]`: List of dimension allocations (dimension, share, cause_code)
   - `recoverable_cost_usd`: Dollar amount of avoidable waste
3. Consider threshold adjustments for orchestrated sessions (is_orchestrated parameter)
4. Add test case to `tests/test_v2_antipatterns.py` covering boundary conditions
5. Verify all 32 tests pass: `python -m pytest tests/ -v`

See [memory/project-context.md](../.claude/projects/-Users-abhinav-projects-git-ai-coding-sessionprompt-analyzer/memory/project-context.md) for detailed architecture and [memory/discussion-watchpoints.md](../.claude/projects/-Users-abhinav-projects-git-ai-coding-sessionprompt-analyzer/memory/discussion-watchpoints.md) for operational patterns.

## Completed Work (Mar 2026)

✅ **PR #1**: Report redesign + cost display fix + prompt dedup + LLM recommendations
✅ **PR #2**: Scoring recalibration (multi-agent auto-detection, threshold tuning, cost-weight penalty)
✅ **Follow-up**: V2 correction detection fix + insights HTML injection (`--insights-html` flag)
✅ **Documentation unification**: Removed all V1/V2 version references; single `analyze` command on V2 scoring path
✅ **47 unit tests**: All passing (32 core + 15 new integration tests)
✅ **Insights refresh automation**: Added `--refresh-insights` flag to auto-invoke `claude -p /insights` before injection

## Future Work

- **Phase 6**: Compare command (placeholder exists in cli.py)
- **Phase 7**: Trend mode (accept folder, aggregate sessions, moving average)
- **ML Layer**: Beyond deterministic rules (not yet started)
- **Dashboard**: localhost:3001 (referenced in docs but not implemented)
- **Proxy Layer**: HTTPS proxy for real-time interception (referenced in docs but not implemented)
- **Extended anti-patterns**: Additional flags for emerging efficiency issues
