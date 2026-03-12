# AI Coding Prompt Optimizer

Analyze Claude Code session logs to measure prompt efficiency, identify token waste, and get cost recovery recommendations.

**Core insight**: 80% of token costs come from tool outputs (file reads, bash results, repeated corrections), not your prompts. This tool makes that visible.

## Installation

```bash
# 1. Clone and create venv
python3 -m venv .venv
source .venv/bin/activate

# 2. Install
pip install -e .
```

## Get Started (HTML Report)

The best way to view results is **injected into Claude Code's Insights report**.

### Step 1: Generate Insights HTML

In Claude Code, run:
```
/insights
```
This generates `~/.claude/usage-data/report.html` (it shows your work activity, projects, sessions, etc.)

### Step 2: Inject ai-dev Token Economics

```bash
ai-dev analyze ~/.claude/projects --insights-html ~/.claude/usage-data/report.html
```

This adds three sections to your Insights HTML:
- **Project Cost Summary** – total spend, waste %, recoverable cost per project
- **Session Efficiency** – top sessions ranked by cost with efficiency scores
- **Token Cost by Anti-Pattern** – where waste comes from (full errors pasted, repeated constraints, etc.)

> **📌 Note**: After running the command above, open `~/.claude/usage-data/report.html` in your browser to see the injected sections alongside your original Insights data.

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

Each dimension scores 0–100. Composite score is clamped to [0, 100].

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

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

See `CLAUDE.md` for project architecture and `docs/specs/product-spec.md` for detailed spec.

## License

MIT
