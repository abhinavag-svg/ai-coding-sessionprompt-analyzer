# Claude Prompt Efficiency Analyzer — Technical Spec
## V2.0
*Post-mortem analysis of Claude coding session efficiency from JSONL logs*

---

## Table of Contents

1. [What This Is For](#1-what-this-is-for)
2. [Data Source and Ceiling](#2-data-source-and-ceiling)
3. [What Changed from V1 and Why](#3-what-changed-from-v1-and-why)
4. [Scoring Rubric](#4-scoring-rubric)
5. [Anti-Pattern Catalog](#5-anti-pattern-catalog)
6. [Report Structure](#6-report-structure)
7. [Flags Must Link to Dimensions](#7-flags-must-link-to-dimensions)
8. [What V1 to Keep](#8-what-v1-to-keep)
9. [Metrics Reference](#9-metrics-reference)
10. [Out of Scope](#10-out-of-scope)
11. [Success Criteria](#11-success-criteria)
12. [Design Decisions](#12-design-decisions)

---

## 1. What This Is For

The core question this tool tries to answer:

> **Given what I was trying to build, did I use Claude well — in terms of cost, turns, and prompting habits?**

That requires three things:

- **Intent reconstruction** — what was the session actually trying to accomplish? Approximated from first prompts, tool use patterns, and whether the session converged or spiraled.
- **Efficiency measurement** — did it get there cheaply and fast? Not just tokens and cost, but turns-to-first-success, correction loops, and context thrash.
- **Counterfactual suggestions** — what could have been done differently? This is the hard part and requires matching against known anti-patterns.

V2 produces three layers of output that work together:

- **Per-dimension scores** — where did efficiency break down?
- **Anti-pattern flags** — what specifically happened, with evidence
- **Remedies** — what to change, linked directly to the flag that caused the deduction

The composite score is kept for longitudinal tracking but it's no longer the headline. **The headline is the anti-pattern report.**

---

## 2. Data Source and Ceiling

Everything comes from JSONL logs. No external signals, no outcome labeling.

Fields used:

- Turn metadata: uuid, session_id, timestamp, role
- Token counts: input_tokens, output_tokens, cache_read_tokens, cache_write_tokens
- Tool use blocks: tool name, invocation count per turn
- Message content: user prompt text for pattern detection
- Cost: derived from token counts + pricing file, or direct if present

**The honest ceiling:** JSONL cannot tell you whether Claude's output was correct. That's proxied via convergence signals — did tool use stabilize, or did the session end mid-correction? The analyzer measures prompting efficiency, not result quality.

---

## 3. What Changed from V1 and Why

| Area | V1 | V2 | Why |
|---|---|---|---|
| Primary output | Composite score | Anti-pattern report is headline; score kept for trending | A score without a cause isn't actionable |
| Correction dimension | Single score mixing prompt-induced + model-induced + repeated constraints | Split into Correction Discipline (15%) and Model Stability (10%) | Different causes need different fixes — conflating them hides the diagnosis |
| Context Scope penalty | Penalizes high file-read counts | Penalizes repeated reads of the same file only | High Read counts in agentic sessions are normal; re-reading the same file signals context loss |
| Model Efficiency | Vague "overspend signals from rule violations" | Renamed Session Convergence; measures turns-to-convergence and loop detection | Convergence speed is observable in JSONL and doesn't overlap with other dimensions |
| Specificity scoring | Scores prompt style in isolation | Weighted by outcome — only penalized when vagueness caused a correction | A specific prompt followed by 3 correction loops is worse than a vague prompt resolved in 2 turns |
| Diagnosis string | Single freeform string | Removed; flags do this job with evidence | Flags are more precise and link directly to remedies |
| Cost confidence | Reported as "unknown" with no context | Flagged explicitly in the report header | Users need to know when figures are estimates vs actuals |

---

## 4. Scoring Rubric

Five dimensions, weighted, composite out of 100. Weights were revised to make each dimension non-overlapping.

| Dimension | Weight | What It Measures |
|---|---|---|
| Specificity | 25% | Prompt concreteness (file paths, symbols, acceptance criteria) — penalized only when vagueness caused a correction |
| Context Scope | 30% | Redundant context: incremental tokens/turn, over-40k ratio, repeated file reads, constraint re-injection frequency |
| Correction Discipline | 15% | Prompting habits: prompt-induced rework + repeated constraints across turns |
| Model Stability | 10% | Claude failure signals: model-induced rework + unknown rework |
| Session Convergence | 20% | Session arc: turns to first stable execution, correction spirals, abandonment |

**Weight rationale:** Specificity dropped from 30% to 25% to fund Session Convergence (new at 20%). Correction split into Discipline + Stability = 25% total, unchanged from V1. Context Scope unchanged at 30%.

**Clamping order matters:**
1. Compute each dimension's raw points = max_points − allocated deductions
2. Clamp each dimension to [0, max_points]
3. Composite = sum of clamped dimension points
4. Clamp composite to [0, 100]

Dimension clamp must happen before summing. Otherwise a negative dimension pulls the composite below the correct floor.

---

### 4.1 Specificity (25%)

Positive signals from prompt text:
- File paths (e.g. `app/routes/foo.tsx`)
- Symbol references (function names, variable names, class names)
- Acceptance language ("ensure", "verify", "the test should pass")

Penalty only fires when: prompt scores low on positive signals AND the next non-tool turn is a correction. Vague prompts that resolve cleanly aren't penalized.

---

### 4.2 Context Scope (30%)

Measured from **incremental** tokens, not effective/cached:

- Avg, median, P90 incremental tokens/turn
- Over-40k effective context ratio
- Repeated file-read ratio: reads of files seen >2x / total reads
- Constraint re-injection: same phrase in 3+ separate user turns

Cached tokens are diagnostic only — they show caching health but don't drive the scope score. Score on incremental tokens, which are the actual new context added each turn.

---

### 4.3 Correction Discipline (15%)

Measures prompting habits — things within the user's control:

- Prompt-induced rework: correction turn following a low-specificity prompt
- Repeated constraint frequency: same requirement restated 3+ turns

Both have the same fix: better upfront context, or move recurring rules to a project-level system prompt.

---

### 4.4 Model Stability (10%)

Measures Claude failure signals — not user habits:

- Model-induced rework: correction following a high-specificity prompt
- Unknown rework: correction where cause is ambiguous

A low Model Stability score means prompts need more scaffolding — examples, expected output format, step decomposition — even when they're already specific.

---

### 4.5 Session Convergence (20%)

Tracks the session arc through four observable phases:

| Phase | JSONL Signal | Healthy | Unhealthy |
|---|---|---|---|
| Intent | First 1-3 user prompts, low tool use | Short, specific | Vague opener + clarification loop before any tool use |
| Execution | Rising tool use density | Tool use within 3 turns of intent | Long exploration before first tool invocation |
| Correction loop | Alternating user/assistant, no tool use | 0-1 loops | 3+ consecutive correction exchanges |
| Convergence | Tool use drops, short assistant responses | Clean end state | Session ends mid-correction loop |

**Session shapes:**
- `Clean` — fast execution, 0-1 correction loops, converged
- `Exploration-Heavy` — many turns before first tool use
- `Correction-Heavy` — 3+ correction loops mid-session
- `Abandoned` — session ends mid-correction loop

Convergence gates are modeled as synthetic flags (see Section 12.2) so every deduction is traceable through the same flag machinery as prompt-derived anti-patterns.

---

## 5. Anti-Pattern Catalog

Nine named patterns, each JSONL-detectable, linked to dimensions, with a concrete remedy. Every flag has a fixed impact budget — points are allocated across dimensions by split, never applied in full to each dimension independently (see Section 12.1).

**Severity:** 🔴 High | 🟡 Medium

| Pattern | Sev | JSONL Signal | Dimensions | Remedy |
|---|---|---|---|---|
| `error_dump` | 🔴 | Long prompt where stack trace / header content dominates (weighted noise ratio ≥ 0.45) | Context Scope (80%), Specificity (20%) | Trim to error message + 2 relevant stack frames. Remove HTTP headers entirely. |
| `repeated_constraint` | 🔴 | Same constraint phrase in 3+ separate user turns | Correction Discipline (75%), Context Scope (25%) | Move standing constraints to a project-level system prompt. State once. |
| `correction_spiral` | 🔴 | 3+ consecutive user turns with no tool use | Session Convergence (70%), Correction Discipline (30%) | Stop iterating. Restate full intent as one prompt from scratch. |
| `abandoned_session` | 🔴 | Session ends on a correction turn with no convergence signal | Session Convergence (100%) | If task was too broad, restart with a scoped sub-task. If Claude was stuck, switch to step-by-step decomposition. |
| `vague_opener` | 🟡 | First prompt <20 incremental tokens, followed by correction before first tool use | Specificity (60%), Session Convergence (40%) | Front-load intent: file paths, expected behavior, acceptance criteria in the opening prompt. |
| `file_thrash` | 🟡 | Same file Read more than 2x in a session (first 2 reads are free) | Context Scope (100%) | After first read, summarize the relevant state in the next prompt so Claude doesn't re-read. |
| `prompt_duplication` | 🟡 | Authored prompt body repeated verbatim in the same message (after stripping IDE-injected content) | Context Scope (100%) | Deduplication bug in upstream pipeline. Fix before send. |
| `scope_creep` | 🟡 | Turn count >300 with tool variety increasing in the final third | Session Convergence (100%) | Split by feature boundary. Large sessions with expanding scope lose context coherence. |
| `constraint_missing_scaffold` | 🟡 | High-specificity prompt (file paths, symbols) still triggers a correction | Model Stability (100%) | Add scaffolding: expected output format, a worked example, or explicit step decomposition. |

### Synthetic Convergence Flags

Gates fire as synthetic flags through the same flag machinery — no special deduction channel.

| Flag | Points | Severity | Remedy |
|---|---|---|---|
| `convergence_gate1_miss` | 6 | 🔴 | Front-load intent and acceptance criteria before exploration |
| `convergence_gate2_failure` | 8 | 🔴 | Restate full intent in one prompt rather than iterating corrections |
| `convergence_gate3_inconclusive` | 2 | 🟡 | Settlement unclear — check whether task ended mid-stream |
| `abandoned_session` | 8 | 🔴 | Terminal failure flag; suppresses `gate3_inconclusive` |

Suppression rule: if `abandoned_session` fires, `convergence_gate3_inconclusive` is suppressed. Only one terminal convergence flag per session.

---

## 6. Report Structure

> The composite score earns attention. Dimension scores direct it. Flags explain it. Remedies close the loop.

### 6.1 Per-Session Post-Mortem

```
Session: b88e6845
│
├── Composite: 87/100
│
├── Dimensions
│   ├── Specificity:            23/25
│   ├── Context Scope:          26/30
│   ├── Correction Discipline:  11/15  ← repeated_constraint (3pts) + prompt_induced_rework (1pt)
│   ├── Model Stability:         9/10
│   └── Session Convergence:    18/20
│
├── Arc: Correction-Heavy
│   └── Intent (3 turns) → Execution → Correction loop (4 turns) → Convergence
│
├── Flags
│   ├── 🔴 repeated_constraint (3x) → driving Correction Discipline deduction
│   ├── 🟡 error_dump (1x) → minor Context Scope penalty
│   └── 🟡 file_thrash on auth.ts (4 reads) → minor Context Scope penalty
│
└── Remedies
    ├── repeated_constraint → move to system prompt | est. savings: ~$0.40/session
    ├── error_dump → trim to error message + 2 stack frames
    └── file_thrash → summarize auth.ts state after first read
```

### 6.2 Project Post-Mortem

Rolled up across all sessions:

- Dimension score trends — improving per dimension over time?
- Anti-pattern frequency table — habitual vs one-off?
- Cumulative recoverable cost — sum of per-session recoverable totals, not recomputed from a global rate
- Session efficiency distribution — cost per converged session
- Most expensive prompts — top N by downstream cost with pattern annotations

The cumulative recoverable cost figure is the most behavior-changing output. "repeated_constraint cost you $12.40 across this project" drives habit change more than any score.

---

## 7. Flags Must Link to Dimensions

Every deduction needs a cause code. Every flag maps to one or more cause codes. The report renders them linked — not as parallel sections.

**Correct:**
```
Correction Discipline: 11/15
  • repeated_constraint fired 3x → -3 pts → move to system prompt, est. savings $0.40/session
  • prompt_induced_rework 1x → -1 pt → add file path to opening prompt
```

**Wrong:**
```
Correction Discipline: 11/15

Anti-patterns:
  • repeated_constraint (3x)
  • prompt_induced_rework (1x)
```

The wrong version shows a score and a list with no connection between them. Users can't tell which flag caused which deduction.

---

## 8. What to Keep from V1

- Caching analysis (no-cache cost estimate, savings %, coverage) — keep as-is
- Session lineage tracking — foundation for arc modeling
- Deduplication pipeline — working, keep
- Cost source transparency — report `unknown` vs `derived_split` counts in header
- Most expensive prompts list — keep, add anti-pattern annotations

---

## 9. Metrics Reference

| Metric | V2 Use | Notes |
|---|---|---|
| incremental tokens/turn | Context Scope scoring | Primary cost signal |
| effective/cached tokens/turn | Caching health only | Don't drive scope score with this |
| cache read/write tokens | Caching section | Keep as-is |
| correction ratio | Correction Discipline + Model Stability | Split by cause — don't report as one number |
| repeated constraints | Correction Discipline | Count phrases recurring 3+ turns |
| file read counts | Context Scope — repeated reads only | Total reads not penalized; same-file repeats are |
| turns-to-convergence | Session Convergence | Turns from first prompt to first stable tool execution |
| session shape | Session Convergence | Clean / Exploration-Heavy / Correction-Heavy / Abandoned |
| recoverable cost | Remedies + rollup | Primary behavior change driver |

---

## 10. Out of Scope

- **Outcome quality** — whether Claude's output was correct. Proxied via convergence only.
- **Real-time feedback** — post-mortem only.
- **Multi-user comparison** — single-user sessions only.
- **Model selection** — out of scope for V2.

---

## 11. Success Criteria

V2 works if:

- Every score deduction traces to a named anti-pattern with a concrete remedy
- Correction Discipline and Model Stability point to different interventions
- Session Convergence catches correction spirals and abandoned sessions from JSONL alone
- Project post-mortem produces a recoverable cost figure concrete enough to change behavior
- No dimension double-counts signals from another dimension

---

## 12. Design Decisions

Decisions made during development, recorded for traceability. Unresolved items are V3 candidates.

---

### 12.1 Multi-Dimension Anti-Pattern Attribution

**Question:** Can one flag deduct from multiple dimensions, or does that cause double-counting?

**Decision:** Multi-dimension allowed, but each flag has a fixed total impact budget. Points are allocated across dimensions by split — never applied in full to each independently.

| Pattern | Primary | Secondary | Split |
|---|---|---|---|
| `repeated_constraint` | Correction Discipline | Context Scope | 75/25 |
| `error_dump` | Context Scope | Specificity | 80/20 |
| `correction_spiral` | Session Convergence | Correction Discipline | 70/30 |
| `vague_opener` | Specificity | Session Convergence | 60/40 |
| `file_thrash` | Context Scope | — | 100 |
| `abandoned_session` | Session Convergence | — | 100 |
| `constraint_missing_scaffold` | Model Stability | — | 100 |

---

### 12.2 Defining Stable Execution for Session Convergence

**Question:** What counts as the moment of stable execution — first tool use, first productive tool use, or first no-correction window?

**Decision:** Three-gate model. Each gate contributes independently.

```
Gate 1 — Engagement
  First productive tool use within 3 user turns of intent
  Fires: convergence_gate1_miss if missed

Gate 2 — Continuity
  <2 correction turns (confidence >= medium) interrupting the productive sequence
  Fires: convergence_gate2_failure if exceeded

Gate 3 — Settlement
  ≥2 user turns after final productive tool use with no correction signal
  Fires: convergence_gate3_inconclusive if ambiguous (not failed — partial credit)
```

**Productive tool tier:**

| Tier | Tools |
|---|---|
| Productive | `Edit`, `Write`, `MultiEdit`, `Bash`, `NotebookEdit` |
| Exploratory | `Read`, `Grep`, `Glob`, `LS` |
| Administrative | `TodoWrite`, `TodoRead`, `WebSearch` |

Gates are modeled as synthetic flags so traceability (Section 7) holds for convergence deductions too.

---

### 12.3 Recoverable Cost Attribution

**Question:** How to attribute recoverable cost — prompt windowing, until next correction, or fixed horizon?

**Decision:** Three layers, each used for what it's actually good at.

```
Layer 1 — Direct Waste (precise, always calculable)
  Tokens directly wasted in the anti-pattern itself.
  repeated_constraint: repeated phrase tokens × occurrences beyond first
  error_dump: tokens above clean-error baseline (message + 2 frames)
  prompt_duplication: duplicated block token count
  file_thrash: redundant reads beyond FILE_THRASH_FREE_READS=2
              × median incremental tokens of assistant Read-only turns

Layer 2 — Bounded Rework (probabilistic, capped windowing)
  Downstream assistant tokens until next real user prompt.
  Capped by recoverable_cost_max_turns and recoverable_cost_max_usd per flag.
  Used for: constraint_missing_scaffold, convergence_gate2_failure, abandoned_session

Layer 3 — Project Rollup (fixed horizon)
  Fixed multipliers per pattern for cumulative project figure.
  Labeled as estimate — not precision.
```

**Rework caps:**

| Pattern | Cap |
|---|---|
| `repeated_constraint` | 3 turns |
| `error_dump` | 5 turns |
| `correction_spiral` | Full spiral length |
| `vague_opener` | 4 turns |
| `abandoned_session` | Entire session from last productive tool |

Project cumulative recoverable cost = sum of per-session totals. Never recomputed from a global blended rate.

**Unresolved:** Layer 3 fixed multipliers need empirical calibration from real sessions. Initial values are estimates.

---

### 12.4 Correction Turn Detection — Precision vs Recall

**Decision:** Precision. Correction turn classification drives five components simultaneously (Gate 2, Gate 3, `correction_spiral`, `vague_opener`, `constraint_missing_scaffold`). False positives compound across all five. False negatives produce a slightly optimistic score — survivable. False accusations erode trust in the tool fast.

**Detection rule (AND gate — all must be true):**
- NOT affirmation language
- NOT extension language
- AND either: explicit correction language present, OR (follows assistant with tool use AND no new info vs last 3 user turns AND token length confidence >= medium)

**Token confidence bands:**

| Tokens | Confidence |
|---|---|
| < 30 | high |
| 30–60 | medium |
| 60–100 | low |
| > 100 | not classified by length alone |

Downstream usage: `correction_spiral` and Gates 2/3 require `confidence >= medium`.

---

### 12.5 Token Caps for Reactive Turns

**Decision:** correction cap N=60, settlement cap ≤30.

The asymmetry is intentional — settlement detection must be tighter than correction detection. A Gate 3 false positive (calling an active session settled) is worse than a false negative (missing a clean convergence).

| Cap | Value | Used In |
|---|---|---|
| `correction_token_cap` | 60 | Correction classification primary signal |
| `correction_token_cap_low_confidence` | 100 | Low-confidence boundary |
| `settlement_token_cap` | 30 | Gate 3 noise filter |

---

### 12.6 Prompt Eligibility Filter

Prompt-content detectors (`prompt_duplication`, `repeated_constraint`, `vague_opener`, `error_dump`, `constraint_missing_scaffold`) only run on human-authored turns. IDE-injected and agent-generated turns are excluded.

**Origin classes:**

| Class | Eligible |
|---|---|
| `user_prompt` | ✅ |
| `user_continuation` | ✅ |
| `telemetry_injected` | ❌ |
| `agent_generated_meta` | ❌ |
| `tool_result_only` | ❌ |
| `ide_context_injection` | ❌ |

For mixed turns (authored text + IDE wrapper), classify by dominance: if IDE content exceeds 60% of total text, classify as `ide_context_injection`. If authored content exceeds 60%, classify as `user_prompt`/`user_continuation`. The 40–60% overlap zone → `user_continuation` with `mixed_content` noted.

**`prompt_duplication` additionally strips IDE tags from the matching surface** before block comparison — even on eligible turns. The turn remains eligible, but matching runs on authored text only.

```python
IDE_STRIP_RE = re.compile(
    r'<ide_(?:opened_file|selection)[^>]*>.*?</ide_(?:opened_file|selection)>',
    re.DOTALL | re.IGNORECASE
)
BOILERPLATE_STRIP_RE = re.compile(
    r'This may or may not be related to the current task\.?',
    re.IGNORECASE
)
```

Do not reuse `get_authored_text_for_duplication()` in other detectors — they need the full turn text.

**Calibration note:** After the eligibility filter and IDE stripping landed, `prompt_duplication` dropped from 74 occurrences to a small number of genuine cases. The 74 were false positives driven by `<ide_opened_file>` and `<ide_selection>` wrapper structures being matched as repeated blocks.

---

### 12.7 error_dump Weighted Noise Classifier

Original heuristic only caught Python-style tracebacks. Shopify/Node errors use object-literal and quoted-key formats that didn't match.

**Revised classifier constants:**

| Line Type | Weight |
|---|---|
| Traceback-style (`at ...:line`, `Traceback`) | 1.0 |
| Quoted key/value, object-literal header | 0.7 |
| Punctuation-dense, bracket-heavy | 0.5 |
| HTTP/infrastructure keys (`x-*`, `cf-*`, `content-*`, `server`, `date`, `vary`) | 0.7 |

Fire threshold: weighted noise ratio ≥ 0.45 (lowered from 0.60).

**Calibration note:** After calibration against real session data, `error_dump` fired conservatively — once on the Shopify-heavy session. The 0.45 / 1.0, 0.7, 0.5 constants were left unchanged.

---

*Design decisions here should be reflected in the main spec sections above when V3 is drafted.*
