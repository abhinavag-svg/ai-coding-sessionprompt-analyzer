# AI Coding Prompt Optimizer

Analyze Claude Code and Codex session logs to measure prompt efficiency, identify token waste, and get evidence-backed recommendations.

**Core insight**: 80% of token costs come from tool outputs (file reads, bash results, repeated corrections), not your prompts. This tool makes that visible.

## Installation

```bash
# 1. Clone and create venv
python3 -m venv .venv
source .venv/bin/activate

# 2. Install
pip install -e .
```

## Claude Code

Create both an enhanced Claude Insights report and a separate evidence drill-down:

```bash
ai-dev insights
```

The command automatically finds `~/.claude/projects` and the latest report under
`~/.claude/usage-data`. Run `ai-dev insights --refresh` if Claude Insights needs
to be regenerated first.

It produces:

- **Enhanced Claude Insights** — Token Economics is added at runtime without rewriting Anthropic's existing document structure.
- **Standalone evidence report** — session and finding drill-downs, scoring evidence, remedies, and reviewable project-instruction candidates.
- **Suggested project instructions** — a small Markdown candidate file that can be reviewed before copying useful rules into `AGENTS.md` or `CLAUDE.md`.

The analyzer never edits `CLAUDE.md` or `AGENTS.md` automatically. Suggested
instructions must be reviewed and copied explicitly.

### Existing or custom Insights report

```bash
ai-dev insights --insights-html path/to/report.html --output path/to/evidence.html --instructions-output path/to/suggestions.md
```

Runtime augmentation uses a versioned JSON data island and DOM APIs. User-derived
content is rendered with `textContent`, so prompt excerpts cannot inject markup or
scripts into the report.

## Codex

Analyze the local Codex rollout history with the same scoring and evidence layer:

```bash
ai-dev insights --source codex --current-repo-only
```

This automatically reads `~/.codex/sessions` and writes two local artifacts under
`.ai-dev/` in the current directory:

- A standalone HTML evidence report grouped by the repository recorded in each rollout.
- Reviewable `AGENTS.md` instruction candidates promoted only from recurring evidence.

Codex has no Claude Insights HTML page to augment. Token totals come from Codex
`token_count` events. Dollar estimates are omitted unless you provide a pricing
profile matching the recorded Codex model names, or use a bundled pricing profile:

```bash
ai-dev insights --source codex --pricing-file pricing.json
ai-dev insights --source codex --pricing-profile aggressive
```

`--current-repo-only` is recommended for Codex so sessions from other repositories
under `~/.codex/sessions` do not get mixed into the same analysis run.

Session logs can contain prompts, tool arguments, and outputs. Reports stay local,
escape user-derived markup, and redact common credential formats before export.

### Example: What You'll See

**Project Cost Summary:**
| Project | Sessions | Total Cost | Recoverable | Waste % |
|---------|----------|-----------|-----------|---------|
| app-bloat-auditor | 9 | $28.59 | $10.10 | 35.3% |
| ai-coding-sessionprompt-analyzer | 20 | $10.15 | $9.09 | 89.6% |
| ragchatbot-codebase | 16 | $3.18 | $0.11 | 3.4% |

**Session Efficiency** (ranked by cost):
| Session | Project | Score | Shape | Cost | Recoverable | Sample Prompt |
|---------|---------|-------|-------|------|-----------|---|
| 251a6385 | app-bloat-auditor | 85 | Clean | $9.66 | $1.74 | we are not testing if the app... |
| 46068018 | app-bloat-auditor | 86 | Clean | $7.18 | $1.39 | Refer to PRD.md Section 6... |
| 24b119ea | ai-coding-sessionprompt-analyzer | 50 | Correction-Heavy | $6.01 | $6.01 | @docs/specs/product-spec.md... |

**Token Cost by Anti-Pattern:**
- **Prompt Sent Twice** (Pipeline Bug) – 105 occurrences, $8.74 recoverable
- **Full Error Pasted** (Not Trimmed) – 16 occurrences, $7.12 recoverable

## Other Commands

### Markdown Report
```bash
ai-dev analyze ~/.claude/projects --export report.md
```

For Codex JSONL directly:

```bash
ai-dev analyze ~/.codex/sessions --source codex --current-repo-only --standalone-html codex-evidence.html
```

### Standalone Evidence Report

```bash
ai-dev analyze ~/.claude/projects --standalone-html evidence.html
```

### Reviewable Project Instructions

```bash
ai-dev analyze ~/.claude/projects --instructions-output suggested-instructions.md
```

### Cost Range Estimates
```bash
ai-dev cost-range ~/.claude/projects
```
Shows min/max cost estimates across conservative and aggressive pricing.

### With LLM Recommendations (requires Ollama)
```bash
ai-dev analyze ~/.claude/projects --llm-recommendations
```

## What Gets Measured

- **Prompt Clarity** – Are file paths and function names included?
- **Context Efficiency** – Are you reading the same file repeatedly?
- **Rework Rate** – How many corrections did the session need?
- **AI Consistency** – Did model errors cause rework?
- **Task Completion** – Did the session converge successfully?

Dimensions contribute weighted points totaling 100. The composite score is
clamped to [0, 100]. Cost and "estimated avoidable" figures are heuristic and
should be interpreted alongside the included evidence.

## Anti-Patterns Detected

- Duplicate prompts (pipeline bug)
- Full error messages pasted instead of trimmed
- Repeated file reads
- Correction spirals (Claude stuck in a loop)
- Vague prompts without file paths
- Scope creep (session sprawl)

## Pricing & Cost Modes

Three cost modes:
- **AUTO** (default): Use reported costs, fall back to split/blended pricing
- **REPORTED_ONLY**: Only provider-reported costs
- **DERIVED_ONLY**: Calculate from token counts

Custom pricing: `--pricing-file pricing.json`

Bundled pricing profiles: `--pricing-profile conservative|default|aggressive`

Export a bundled template to customize:

```bash
ai-dev pricing-template pricing.json --profile aggressive
```

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

See `CLAUDE.md` for project architecture and `docs/specs/product-spec.md` for detailed spec.

## License

MIT
