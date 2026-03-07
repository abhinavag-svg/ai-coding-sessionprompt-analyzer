# Claude Prompt Efficiency Analyzer
## Version 2.0 — Design Specification
*Post-Mortem Analysis of Claude Session Efficiency from JSONL Logs*

---

## Table of Contents

1. [Purpose & Goals](#1-purpose--goals)
2. [Data Source](#2-data-source)
3. [What Changed from V1 and Why](#3-what-changed-from-v1-and-why)
4. [Scoring Rubric — V2](#4-scoring-rubric--v2)
5. [Anti-Pattern Catalog](#5-anti-pattern-catalog)
6. [Report Output Structure](#6-report-output-structure)
7. [Critical Implementation Rule: Flags Must Link to Dimensions](#7-critical-implementation-rule-flags-must-link-to-dimensions)
8. [What to Retain from V1](#8-what-to-retain-from-v1)
9. [Metrics Reference](#9-metrics-reference)
10. [Explicit Out of Scope](#10-explicit-out-of-scope)
11. [Success Criteria for V2](#11-success-criteria-for-v2)

---

## 1. Purpose & Goals

This spec defines V2 of the Claude Prompt Efficiency Analyzer — a tool that performs post-mortem analysis of Claude coding sessions from raw JSONL logs, answering the core question:

> **Given what you were trying to accomplish, did you use Claude optimally — in terms of cost, turns, and prompting habits?**

The V2 system produces three layered outputs that work together:

- **Per-dimension scores** — diagnosis of where efficiency was lost
- **Anti-pattern flags** — specific named events with evidence from the session
- **Actionable remedies** — concrete changes linked to each flag, with estimated cost savings

V2 moves away from a single composite score as the primary output. The composite is retained for longitudinal trending but is no longer the headline. **The headline is the anti-pattern report.**

---

## 2. Data Source

**Source: JSONL conversation logs only.** No external signals, no outcome labeling required.

Key fields used from JSONL:

- **Turn metadata:** uuid, session_id, timestamp, role (user/assistant)
- **Token counts:** input_tokens, output_tokens, cache_read_tokens, cache_write_tokens
- **Tool use blocks:** tool name, invocation count per turn
- **Message content:** user prompt text (for pattern detection)
- **Cost:** derived from token counts + pricing file, or direct if present

> **Ceiling Note:** JSONL logs cannot provide outcome quality — whether Claude's output was actually correct. This is proxied via session convergence signals (see Section 4.5). The analyzer measures efficiency of the prompting process, not correctness of the result.

---

## 3. What Changed from V1 and Why

| Area | V1 Behavior | V2 Change | Rationale |
|------|-------------|-----------|-----------|
| Primary output | Composite score (e.g. 95.84/100) | Anti-pattern report is headline; composite retained for trending | A score without cause is not actionable. Flags tell you what to fix. |
| Correction dimension | Single score combining prompt-induced + model-induced + repeated constraints | Split into Correction Discipline (15%) and Model Stability (10%) | Three different causes need three different remedies. Conflating them hides the diagnosis. |
| Context Scope penalty | Penalizes high file-read counts | Penalizes repeated reads of the same file only | High Read counts in agentic sessions are normal. Re-reading the same file signals context loss, not thoroughness. |
| Model Efficiency | Vague "overspend signals from rule violations" | Renamed Session Convergence; measures turns-to-convergence and loop detection | Convergence speed is directly observable in JSONL and non-overlapping with other dimensions. |
| Specificity scoring | Scores prompt style in isolation | Specificity weighted by whether turn led to successful execution without correction | A specific prompt followed by 3 correction loops is worse than a vague prompt resolved in 2 turns. |
| Diagnosis string | Single string e.g. "High correction churn is reducing efficiency" | Removed; replaced by linked anti-pattern flags | The flags do this job with more precision and evidence. |
| Cost confidence | Reported as "unknown" for many turns | Flagged explicitly as a data quality issue in the report header | Users should know when cost figures are estimates vs actuals. |

---

## 4. Scoring Rubric — V2

Rubric methodology retained: weighted dimensions producing a composite score out of 100. Weights revised to reflect non-overlapping definitions.

| Dimension | Weight | What It Measures |
|-----------|--------|-----------------|
| Specificity | 25% | Prompt concreteness (file paths, symbols, acceptance criteria) weighted by outcome — penalized only when vagueness is followed by a correction turn. |
| Context Scope | 30% | Redundant context signals: incremental tokens/turn, over-40k ratio, repeated file-read ratio (same file >2x), constraint re-injection frequency. Penalizes redundant context, not total context. |
| Correction Discipline | 15% | Your prompting habits: prompt-induced rework rate + repeated constraint frequency across turns. |
| Model Stability | 10% | Claude failure signals: model-induced rework + unknown rework rates. |
| Session Convergence | 20% | Session arc efficiency: turns-to-first-stable-execution, correction spiral detection, abandonment signal (session ends mid-loop). |

> **Weight rationale:** Specificity reduced from 30% to 25% to fund Session Convergence (new at 20%). Correction split into Discipline (15%) + Stability (10%) = 25% total, unchanged from V1. Context Scope unchanged at 30%.

---

### 4.1 Specificity (25%)

**Positive signals** (from prompt text):
- File paths present (e.g. `app/routes/foo.tsx`)
- Symbol references (function names, variable names, class names)
- Acceptance language (e.g. "ensure", "verify", "the test should pass", "confirm that")

**Penalty applied only when:**
- Prompt scores low on positive signals AND the next non-tool turn is a correction

Rationale: vague prompts that resolve cleanly should not be penalized. Only vagueness that caused rework counts against the score.

---

### 4.2 Context Scope (30%)

Measured from **incremental** (not effective/cached) tokens per turn:

- Avg, median, P90 incremental tokens/turn
- Over-40k effective context ratio
- Repeated file-read ratio: (reads of files seen >2x in session) / (total reads)
- Constraint re-injection count: same constraint phrase detected in 3+ separate user turns

> **Key Design Note:** Cached tokens are diagnostic only — they show caching health but should not drive the scope score. Score on incremental tokens, which represent actual new context introduced each turn.

---

### 4.3 Correction Discipline (15%)

Measures **your** prompting habits as a user:

- Prompt-induced rework rate (detected via correction turn following a low-specificity prompt)
- Repeated constraint frequency (same requirement restated across 3+ turns)

Both are within your control and have the same remedy: better upfront context or project-level system prompts.

---

### 4.4 Model Stability (10%)

Measures **Claude** failure signals — not your prompting habits:

- Model-induced rework rate (correction turn following a high-specificity prompt)
- Unknown rework rate (correction turn where cause is ambiguous)

A low Model Stability score suggests your prompts need more scaffolding (examples, constraints, step decomposition) even when they are specific.

---

### 4.5 Session Convergence (20%)

Models the session arc. Observable phases from JSONL:

| Phase | Signal in JSONL | Healthy vs Unhealthy |
|-------|----------------|----------------------|
| Intent | First 1-3 user prompts, low tool use | Healthy: short, specific. Unhealthy: vague opener followed by clarification loop before any tool use. |
| Execution | Rising tool use density | Healthy: tool use starts within 3 turns of intent. Unhealthy: long exploration before first tool invocation. |
| Correction loop | Alternating user/assistant with no tool use | Healthy: 0-1 loops. Unhealthy: 3+ consecutive correction exchanges. |
| Convergence | Tool use drops, short assistant responses | Healthy: clean end state. Unhealthy: session ends mid-correction loop (abandonment signal). |

Score is based on: turns-to-first-tool-use, correction loop count mid-session, and whether session ends in convergence or abandonment.

**Session shape classifications:**
- `Clean` — fast execution, 0-1 correction loops, converged
- `Exploration-Heavy` — many turns before first tool use
- `Correction-Heavy` — 3+ correction loops mid-session
- `Abandoned` — session ends mid-correction loop

---

## 5. Anti-Pattern Catalog

Each anti-pattern is named, JSONL-detectable, linked to one or more scoring dimensions, and carries a concrete remedy.

**Severity:** 🔴 High impact | 🟡 Medium | ⚪ Low/informational

| Pattern | Sev | JSONL Signal | Dimension | Remedy |
|---------|-----|-------------|-----------|--------|
| `error_dump` | 🔴 | Long user prompt where >60% of characters are stack trace / HTTP header content | Specificity, Context Scope | Trim to error message + 2 relevant stack frames only. Remove HTTP headers entirely. |
| `repeated_constraint` | 🔴 | Same constraint phrase appears in 3+ separate user turns | Correction Discipline, Context Scope | Move standing constraints to a project-level system prompt. State once, not per-turn. |
| `vague_opener` | 🟡 | First prompt <20 incremental tokens, followed by correction turn before first tool use | Specificity, Session Convergence | Front-load intent: include file paths, the specific behavior expected, and acceptance criteria in the opening prompt. |
| `correction_spiral` | 🔴 | 3+ consecutive user turns with no tool use between them | Session Convergence, Correction Discipline | Stop the spiral. Restate the complete intent from scratch as a single new prompt rather than iterating corrections. |
| `file_thrash` | 🟡 | Same file Read more than 2x in a single session | Context Scope | After the first read, summarize the relevant state in your next prompt so Claude retains it without re-reading. |
| `prompt_duplication` | 🟡 | User prompt text appears verbatim twice within the same message | Context Scope | Bug in your upstream pipeline — deduplication step needed before prompt is sent. |
| `scope_creep` | 🟡 | Session turn count >300 with tool variety increasing in the final third of the session | Session Convergence | Split into sub-sessions by feature boundary. Large sessions with expanding scope lose context coherence. |
| `constraint_missing_scaffold` | 🟡 | High-specificity prompt (good file paths, symbols) followed by model-induced correction | Model Stability | Add scaffolding: expected output format, a worked example, or explicit step decomposition even when prompt is specific. |
| `abandoned_session` | 🔴 | Session ends with correction turn as last user message (no convergence signal) | Session Convergence | Review what caused abandonment. If task was too broad, restart with scoped sub-task. If Claude was stuck, switch to step-by-step decomposition. |

---

## 6. Report Output Structure

> **Design Principle:** The composite score earns attention. The dimension scores direct it. The anti-pattern flags explain it. The remedies close the loop. Each layer is necessary; none is sufficient alone.

---

### 6.1 Session Post-Mortem

Produced at end of each session:

```
Session Post-Mortem
│
├── Composite Score: 87/100
│
├── Dimension Scores
│   ├── Specificity:            23/25
│   ├── Context Scope:          26/30
│   ├── Correction Discipline:  11/15  ← deducted: repeated_constraint (3pts) + prompt_induced_rework (1pt)
│   ├── Model Stability:         9/10
│   └── Session Convergence:    18/20
│
├── Session Arc: Correction-Heavy
│   └── Phases: Intent (3 turns) → Execution → Correction loop (4 turns) → Convergence
│
├── Anti-Pattern Flags
│   ├── 🔴 repeated_constraint (3 occurrences) → driving Correction Discipline deduction
│   ├── 🟡 error_dump (1 occurrence) → minor Context Scope penalty
│   └── 🟡 file_thrash on auth.ts (read 4x) → minor Context Scope penalty
│
└── Remedies
    ├── repeated_constraint → move to system prompt | est. savings: ~$0.40/session
    ├── error_dump → trim to error message + 2 stack frames
    └── file_thrash → summarize auth.ts state after first read
```

---

### 6.2 Project Post-Mortem

Produced at project close, rolled up across all sessions:

- **Dimension score trends** across sessions — are you improving per dimension?
- **Anti-pattern frequency table** — which patterns are habitual vs one-off?
- **Estimated cumulative recoverable cost** — total savings if anti-patterns were resolved
- **Session efficiency distribution** — cost per convergence, sorted by session
- **Most expensive prompts** — top N by downstream cost with pattern annotations

> **Behavior Change Driver:** The cumulative recoverable cost figure (e.g. *"repeated_constraint cost you an estimated $12.40 across this project"*) is the single most behavior-changing output. Concrete dollar figures drive habit change more than abstract scores.

---

## 7. Critical Implementation Rule: Flags Must Link to Dimensions

Anti-pattern flags must be **explicitly wired** to the dimension score they affect — not listed in parallel. This is the most common failure mode in reporting tools.

**Implementation requirement:** every dimension score deduction has a `cause_code`. Every anti-pattern flag maps to one or more `cause_codes`. The report renders them as linked, not as separate sections.

**Example (correct):**

```
Correction Discipline: 11/15
  Deduction breakdown:
    • repeated_constraint fired 3x → -3 pts → move to system prompt, est. savings $0.40/session
    • prompt_induced_rework 1 occurrence → -1 pt → add file path to opening prompt
```

**Example (wrong):**

```
Correction Discipline: 11/15        ← score with no explanation

Anti-patterns:                       ← separate section, not connected to score
  • repeated_constraint (3x)
  • prompt_induced_rework (1x)
```

---

## 8. What to Retain from V1

- **Caching analysis** (estimated no-cache cost, savings %, coverage) — accurate and valuable, keep as-is
- **Session lineage tracking** — essential foundation for arc modeling
- **Deduplication pipeline** — already working, keep
- **Cost source transparency** — keep reporting `unknown` vs `derived_split` counts in report header
- **Most expensive prompts list** — retain, add anti-pattern annotations to each entry

---

## 9. Metrics Reference

| Metric | Use in V2 | Notes |
|--------|-----------|-------|
| incremental tokens/turn | Context Scope scoring | Primary cost signal. Use for scope decisions. |
| effective/cached tokens/turn | Caching health only | Diagnostic — do not drive scope score with this. |
| cache read / write tokens | Caching analysis section | Retain as-is from V1. |
| correction ratio | Correction Discipline + Model Stability | Split by cause type — do not report as single number. |
| repeated constraints | Correction Discipline | Count distinct constraint phrases recurring 3+ turns. |
| file read counts | Context Scope — repeated reads only | Total reads not penalized; same-file repeat reads are. |
| turns-to-convergence | Session Convergence | **New in V2.** Turns from first user prompt to first stable tool execution. |
| session shape | Session Convergence | **New in V2.** Classify as: Clean / Exploration-Heavy / Correction-Heavy / Abandoned. |
| recoverable cost estimate | Remedies + Project rollup | **New in V2.** Per anti-pattern cost estimate; primary behavior change driver. |

---

## 10. Explicit Out of Scope

- **Outcome quality scoring** — whether Claude's output was actually correct. Cannot be derived from JSONL alone. Proxied only via convergence signals.
- **Real-time / in-session feedback** — this is a post-mortem tool only.
- **Multi-user comparison** — spec covers single-user session analysis.
- **Model selection recommendations** — out of scope for V2.

---

## 11. Success Criteria for V2

V2 is successful if:

- Every composite score deduction is traceable to a named anti-pattern with a concrete remedy
- Correction Discipline and Model Stability scores point to different interventions
- Session Convergence reliably detects correction spirals and abandoned sessions from JSONL alone
- Project post-mortem produces a recoverable cost figure specific enough to motivate habit change
- No dimension double-counts signals already captured by another dimension

---

## 12. Brainstorming — Open Design Questions

This section captures clarifying questions explored during spec development. Decisions are recorded here for traceability. Not all questions are resolved — unresolved items are candidates for V3.

---

### 12.1 Multi-Dimension Anti-Pattern Attribution

**Question:** Should a single anti-pattern (e.g. `repeated_constraint`) be allowed to deduct points from multiple dimensions, or should each flag map to exactly one dimension to avoid double-counting?

**Options considered:**
- One flag → one dimension (simple, loses diagnostic precision)
- One flag → multiple dimensions freely (rich diagnosis, risks double-counting in composite)

**Decision:** Allow multi-dimension impact with a fixed total impact budget per flag, allocated across dimensions. The total deduction for a flag is fixed regardless of how many dimensions it touches. Primary dimension receives the majority of the budget (root cause); secondary dimensions receive the remainder (downstream effect).

**Example allocation:**

| Pattern | Primary Dimension | Secondary Dimension | Split |
|---|---|---|---|
| `repeated_constraint` | Correction Discipline | Context Scope | 75% / 25% |
| `error_dump` | Context Scope | Specificity | 80% / 20% |
| `correction_spiral` | Session Convergence | Correction Discipline | 70% / 30% |
| `vague_opener` | Specificity | Session Convergence | 60% / 40% |
| `file_thrash` | Context Scope | — | 100% |
| `abandoned_session` | Session Convergence | — | 100% |
| `constraint_missing_scaffold` | Model Stability | — | 100% |

---

### 12.2 Defining "Stable Execution" for Session Convergence

**Question:** What should count as the moment of stable execution for turns-to-convergence measurement?
1. First tool use
2. First productive tool use
3. First no-correction window

**Options considered:**
- Option 1 fires too early — `TodoWrite` or `Read` in turn 2 would trigger it regardless of whether real work started
- Option 2 is the right anchor for when execution *starts* but doesn't tell you if it *succeeded*
- Option 3 is the right signal for whether output held but can't be measured in real time and conflates silence with success

**Decision:** Three-gate model — each gate contributes independently to the Session Convergence score:

```
Gate 1 — Engagement Gate
  First productive tool use (Edit, Write, Bash, MultiEdit)
  Threshold: within 3 turns of intent prompt = full score

Gate 2 — Continuity Gate
  No correction loop interrupting tool use sequence
  Threshold: <2 correction turns between first and last productive tool use

Gate 3 — Settlement Gate
  Final productive tool use followed by ≥2 user turns with no correction signal
  Threshold: detectable via turn content heuristics
```

**Productive tool tier defined as:**

| Tier | Tools | Rationale |
|---|---|---|
| Productive | `Edit`, `Write`, `MultiEdit`, `Bash`, `NotebookEdit` | Directly mutates or executes against the codebase |
| Exploratory | `Read`, `Grep`, `Glob`, `LS` | Orientation — necessary but not execution |
| Administrative | `TodoWrite`, `TodoRead`, `WebSearch` | Scaffolding — not task execution |

---

### 12.3 Recoverable Cost Attribution Method

**Question:** How should recoverable cost be attributed to an anti-pattern / prompt?
1. Prompt Windowing — fixed window of turns around the offending prompt
2. Until Next Correction — all turns between the offending prompt and the next correction signal
3. Fixed Horizon — fixed token/cost multiplier per anti-pattern type

**Options considered:**
- Option 1: window size is arbitrary; doesn't track actual downstream damage
- Option 2: attributes productive turns downstream of a bad prompt; conflates duration with causation without a cap
- Option 3: consistent and simple but disconnected from what actually happened; too blunt for session-level diagnosis

**Decision:** Layered attribution — each layer used for what it is actually good at:

```
Layer 1 — Direct Waste (precise, always calculable)
  Tokens that were directly redundant in the anti-pattern itself.
  repeated_constraint: repeated phrase tokens × occurrences
  error_dump: tokens above a clean-error baseline (message + 2 frames)
  prompt_duplication: exactly half the prompt tokens
  → Hard floor. What you definitely wasted regardless of what happened next.

Layer 2 — Rework Attribution (probabilistic, capped Prompt Windowing)
  Correction window turns attributed using a short fixed window (3-5 turns).
  Capped per pattern to prevent Until-Next-Correction overreach.
  → Honest causal attribution without overclaiming.

Layer 3 — Project Rollup (Fixed Horizon)
  Fixed multipliers per pattern type for cumulative recoverable cost figure.
  Explicitly labeled as an estimate in the report.
  → Motivational figure, not precision measurement.
```

**Rework window caps by pattern:**

| Pattern | Cap | Rationale |
|---|---|---|
| `repeated_constraint` | 3 turns | Habit signal, low direct rework |
| `error_dump` | 5 turns | Direct cause of misdiagnosis loops |
| `correction_spiral` | Full spiral length | The spiral is the rework — attribute it all |
| `vague_opener` | 4 turns | Scoped to early clarification phase |
| `abandoned_session` | Entire session from last productive tool | Everything after convergence failed is waste |

**Unresolved:** Calibration of Fixed Horizon multipliers (Layer 3) requires empirical baseline data from real sessions. Initial values will be estimates; should be tuned after V2 is running against real JSONL data.

---

*End of brainstorming section. Questions resolved here should be reflected in the main spec sections above when V3 is drafted.*
