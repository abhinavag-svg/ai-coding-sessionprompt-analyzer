# AI Dev Intelligence

### From Prompt Optimization → AI Engineering Analytics Platform

------------------------------------------------------------------------

## 1. Problem

AI-native developers are spending:

-   Significant token budget
-   Excessive correction turns
-   Unnecessary file reads
-   Repeated constraint restatements
-   Wrong model selection for task complexity

Current tooling answers:

> "How much did you spend?"

But not:

> "Why did you spend it?"\
> "How could you have spent less?"\
> "Which engineers use AI efficiently?"\
> "What prompt behaviors correlate with cost and quality?"

------------------------------------------------------------------------

## 2. Vision

Build the first:

> AI Developer Intelligence Platform

A system that analyzes real AI coding sessions and produces:

-   Prompt Efficiency Scores
-   Correction Loop Metrics
-   File-Read Explosion Detection
-   Model Misuse Detection
-   Session Comparison
-   Trend Tracking

ML comes later. V1 is deterministic and rule-based.

------------------------------------------------------------------------

# 3. V1 Architecture Design

## High-Level Architecture

CLI → Parser → Feature Extractor → Rule Engine → Scoring Engine →
Reporter

------------------------------------------------------------------------

## Folder Structure

ai-dev-intelligence/

├── cmd/ │ └── cli.py │ ├── core/ │ ├── parser.py │ ├── models.py │ ├──
feature_extractor.py │ ├── rule_engine.py │ ├── scoring.py │ └──
reporter.py │ ├── data/ │ └── sample_sessions/ │ ├── utils/ │ └──
text_utils.py │ ├── tests/ │ ├── requirements.txt └── README.md

------------------------------------------------------------------------

## Data Model Schema

### Session

{ session_id: string, start_time: datetime, end_time: datetime,
total_tokens: int, total_cost: float, model_usage: { model_name:
token_count }, turns: [Turn](#turn) }

------------------------------------------------------------------------

### Turn

{ turn_id: int, role: "user" \| "assistant", content: string,
input_tokens: int, output_tokens: int, cost: float, model: string,
tool_calls: int, files_read: int, is_correction: bool,
specificity_score: int }

------------------------------------------------------------------------

## Feature Extraction (Deterministic)

For each session compute:

-   Total token cost
-   Cost per turn
-   Largest turn
-   Correction count
-   Correction ratio = correction_turns / total_user_turns
-   Avg prompt specificity
-   File read spikes
-   Model overuse patterns
-   Repeated constraint frequency

------------------------------------------------------------------------

# 4. Rule Engine (V1 Intelligence Layer)

Examples:

IF files_read \> 5 AND no file path in prompt\
→ flag file explosion

IF correction_turn detected\
→ increment correction score

IF vague phrases detected ("fix this", "make better")\
→ reduce specificity

IF model == high_cost_model AND output_tokens \< 200\
→ flag overkill model usage

------------------------------------------------------------------------

# 5. Composite Efficiency Scoring Formula

Goal: Produce a 0--100 AI Efficiency Score.

------------------------------------------------------------------------

## Subscores

### 1. Prompt Specificity Score (0--25)

Based on: + file path present + function/class names + negative
constraints − vague language − open-ended phrasing

------------------------------------------------------------------------

### 2. Correction Penalty (0--25)

correction_ratio = correction_turns / user_turns

Score = 25 × (1 − correction_ratio)

Higher correction → lower score

------------------------------------------------------------------------

### 3. Context Scope Efficiency (0--25)

Penalty factors: - file explosion events - excessive tool calls -
unnecessary broad reads

Score = 25 − explosion_penalty

------------------------------------------------------------------------

### 4. Model Efficiency (0--25)

Evaluate: - Expensive model used for trivial task - Underpowered model
causing retries

Score reduces for mismatches.

------------------------------------------------------------------------

# Final Formula

AI Efficiency Score =

Specificity\
+ Correction Score\
+ Scope Efficiency\
+ Model Efficiency

Max = 100

------------------------------------------------------------------------

## Grade Bands

90--100 → A (Highly Efficient AI Usage)\
75--89 → B (Good with minor inefficiencies)\
60--74 → C (Moderate waste)\
40--59 → D (High correction / scope waste)\
\<40 → F (Inefficient AI usage patterns)

------------------------------------------------------------------------

# 6. Example Output

AI Efficiency Score: 72/100 (B)

Insights: - 3 correction loops (18% rework) - 2 file scope explosions -
Repeated constraint: "only modify checkout.ts" (4 times) - Suggest
adding to CLAUDE.md

------------------------------------------------------------------------

# 7. 2-Week Execution Summary

Week 1: - Build parser - Feature extraction - Rule engine - Turn
metrics - Specificity scoring - CLI output

Week 2: - Composite scoring - Session comparison - Trend tracking -
Markdown report export - README + positioning

------------------------------------------------------------------------

# 8. Next Evolution (Future)

-   Counterfactual prompt rewriting
-   Predictive cost model
-   Team SaaS dashboard
-   Cross-user benchmarking
-   ML-based efficiency classifier

V1 is deterministic. Data collected in V1 becomes ML training
foundation.

------------------------------------------------------------------------

End of V1 Product Spec
