Phase 0 — Project Setup (Day 0–1)

Repository Setup
	•	Create GitHub repo - Done
	•	Setup homebrew or pip - Done
	•	Add .env support - Done
	•	Add structured logging (loguru) - Done

CLI Framework
	•	Install typer (clean CLI UX) - Done
	•	Create ai_dev/cli.py - Done
	•	Add base command: ai-dev analyze <path>

Phase 1 — Parsing Layer

1. Log Ingestion

Tasks:
	•	Build file loader (JSONL reader)
	•	Validate schema
	•	Handle malformed logs gracefully
	•	Normalize fields (tokens, cost, tool calls)

Edge Cases:
	•	Missing token counts
	•	Multiple models in session
	•	Tool calls without metadata

⸻

2. Core Data Models

Define Pydantic models:
	•	Session
	•	Turn
	•	ModelUsage
	•	SessionMetrics

Add validation:
	•	Ensure token sums match session total
	•	Compute derived cost if missing

⸻

🔹 Phase 2 — Feature Extraction Layer

Create feature_extractor.py.

Turn-Level Features
	•	Detect file paths (regex for .ts, .py, etc.)
	•	Detect function/class mentions
	•	Detect vague phrases
	•	Count tool calls
	•	Count file reads
	•	Detect correction language
	•	Compute turn cost

⸻

Session-Level Features
	•	Total token usage
	•	Cost per turn
	•	Largest turn
	•	Correction count
	•	Correction ratio
	•	Repeated phrase detection
	•	File explosion events (>5 reads)
	•	Model usage breakdown

⸻

🔹 Phase 3 — Rule Engine

Create rule_engine.py.

Implement Rules
	•	File explosion rule
	•	Model overkill rule
	•	High correction loop rule
	•	Repeated constraint rule
	•	Vague prompt rule

Each rule should return:
{
  rule_id,
  severity,
  description,
  impact_estimate
}

Phase 4 — Scoring Engine

Create scoring.py.

⸻

1. Specificity Scoring
	•	Add file path bonus
	•	Add function name bonus
	•	Add constraint bonus
	•	Subtract vague penalty
	•	Normalize to 0–25

⸻

2. Correction Score
	•	correction_ratio = correction_turns / user_turns
	•	Score = 25 × (1 − correction_ratio)
	•	Clamp 0–25

⸻

3. Context Scope Score
	•	Deduct for explosion events
	•	Deduct for excessive tool calls
	•	Clamp 0–25

⸻

4. Model Efficiency Score
	•	Deduct for expensive model underutilization
	•	Deduct for repeated retries with cheap model
	•	Clamp 0–25

⸻

5. Composite Score
	•	Sum subscores
	•	Generate grade band
	•	Generate short diagnosis summary

⸻

 Phase 5 — Reporting Layer

Create reporter.py.

CLI Output
	•	Rich formatted output (use rich)
	•	Color-coded score
	•	Table for turn metrics
	•	Highlight worst turn
	•	List rule violations

⸻

Markdown Export
	•	Create markdown template
	•	Include:
	•	Summary
	•	Score
	•	Metrics
	•	Violations
	•	Suggestions

Command: ai-dev analyze session.json --export report.md

Phase 6 — Session Comparison
	•	Load two sessions
	•	Compare:
	•	Score delta
	•	Correction delta
	•	Cost delta
	•	Print comparative summary

Command: ai-dev compare s1.json s2.json

Phase 7 — Trend Mode (Optional)
	•	Accept folder input
	•	Aggregate N sessions
	•	Compute moving average score
	•	Show trend direction

Decision Notes — Composite Recalibration (Mar 2026)
	•	Context Scope now follows benchmark bands for tokens per turn:
		•	Excellent: 1k–8k
		•	Normal: 8k–20k
		•	Heavy: 20k–40k
		•	Over-context: >40k sustained
	•	Industry guardrails used in scoring penalties:
		•	Median tokens/turn target < 12k
		•	P90 tokens/turn target < 30k
	•	Composite weights are optimized for token efficiency:
		•	Specificity 30%
		•	Correction 25%
		•	Context Scope 30%
		•	Model Efficiency 15%
	•	Correction attribution is split (deterministic, no LLM):
		•	Prompt-induced rework
		•	Model-induced rework
		•	Unknown rework
	•	Reports now include avg/median/P90 tokens per turn and over-40k turn ratio.