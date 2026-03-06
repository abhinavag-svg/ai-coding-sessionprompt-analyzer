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
python -m ai_dev.cli analyze <path> [--export report.md]

# Options for analyze:
#   --multi-session       Show per-session breakdown
#   --cost-mode           auto | reported-only | derived-only
#   --billable-only/--all-events
#   --dedupe/--no-dedupe  Enable event deduplication
#   --pricing-file        Custom pricing JSON

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
  - Specificity (0-25): file paths, function names, constraints
  - Correction (0-25): score = 25 × (1 − correction_ratio)
  - Context Scope (0-25): benchmark bands (1k-8k tokens/turn excellent)
  - Model Efficiency (0-15): avoid overkill, penalty for retries
  - Composite: weighted average across subscores
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
| **reporter.py** | CLI and markdown report generation |
| **dedupe.py** | Event deduplication by request/response IDs |
| **constants.py** | Scoring thresholds, benchmark bands |

## Important Files

- **pyproject.toml**: Package metadata, entry point `ai-dev` command (requires `pip install -e .`)
- **pricing.example.json**, **pricing.conservative.json**, **pricing.aggressive.json**: Pricing models for cost estimation
- **AI-CODING-PROMPT-OPTIMIZER.md**: High-level problem statement and vision
- **AI-coding-prompt-v1-Architecture.md**: Detailed V1 architecture design
- **AI-Coding-prompt-tasklist.md**: Development roadmap with phase breakdown

## Testing

No test files exist yet. Tests should be added for:
- Event parsing (edge cases: malformed JSON, missing fields)
- Cost calculation (split vs. blended, cache tokens)
- Feature extraction (regex patterns for file paths, vague phrases)
- Rule engine logic
- Scoring formulas

## Design Notes

### Scoring Strategy (Mar 2026 Decision)

Context Scope now uses **benchmark bands** for tokens per turn:
- Excellent: 1k–8k tokens/turn
- Normal: 8k–20k
- Heavy: 20k–40k
- Over-context: >40k sustained

**Industry guardrails**:
- Median tokens/turn target: <12k
- P90 tokens/turn target: <30k

**Composite weights** (optimized for token efficiency):
- Specificity: 30%
- Correction: 25%
- Context Scope: 30%
- Model Efficiency: 15%

**Correction attribution** is split deterministically (no LLM):
- Prompt-induced rework
- Model-induced rework
- Unknown rework

Reports now include avg/median/P90 tokens per turn and over-40k turn ratio.

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

### Debug Event Parsing
Check `parser.py:iter_normalized_events()` for how JSONL lines are normalized. Key extraction points:
- `session_id` from payload or message
- `model` and `role` from payload or nested message
- Token buckets: input, output, cache_write (creation), cache_read
- `is_billable`: only terminal events with valid request/message IDs

### Add a New Scoring Rule

1. Add rule logic to `rule_engine.py:evaluate_rules()`
2. Return dict with `rule_id`, `severity`, `description`, `impact_estimate`
3. Update scoring weights in `scoring.py:compute_scores()` if needed
4. Test rule with sample session data

## Future Work

- **Phase 6**: Compare command (not yet implemented)
- **Phase 7**: Trend mode (accept folder, aggregate sessions, moving average)
- **ML Layer**: Beyond deterministic rules (not yet started)
- **Dashboard**: localhost:3001 (referenced in docs but not implemented)
- **Proxy Layer**: HTTPS proxy for real-time interception (referenced in docs but not implemented)
