# A Mathematical Formula for Your AI Coding Efficiency — Built to Complement Claude Insights

Claude's Insights tool is genuinely impressive. If you haven't looked at it closely, you should. It reads your session history, identifies friction patterns, categorizes what went wrong and why, estimates satisfaction, and even drafts CLAUDE.md additions tailored to your specific mistakes. For behavioral analysis at the project level, it goes much further than most people expect from a usage dashboard.

So when I started building a prompt efficiency analyzer, the honest question wasn't "does this already exist?" It was: "what specifically doesn't Insights do, and is that gap worth filling?"

The answer I landed on: Insights gives you a narrative. What I wanted was a formula — a deterministic, reproducible, session-level score that I could track over time, compare across sessions, and use to measure whether my prompting habits were actually improving. Not a qualitative summary. A number with a derivation I could audit.

That distinction turned out to matter more than I expected.

**GitHub:** [github.com/abhinavag-svg/ai-coding-sessionprompt-analyzer](https://github.com/abhinavag-svg/ai-coding-sessionprompt-analyzer)

---

## What Insights Does Well — And Where a Formula Adds Something Different

Insights analyzes your sessions holistically. It reads across your full project history, identifies recurring friction patterns like "wrong approach" or "buggy code," and tells you which specific sessions exemplify each pattern. It's LLM-powered, which means it can reason about context, connect dots across disparate sessions, and produce natural language recommendations that feel genuinely useful.

What it produces is inherently qualitative — a well-reasoned assessment. That's actually appropriate for the level it operates at. Insights is answering "what's going wrong in my workflow?" which is a question that benefits from judgment and synthesis.

But there's a complementary question that a qualitative summary can't fully answer: **"By exactly how much did this session underperform, on which specific dimensions, and how does that compare to my session last Tuesday?"**

That question requires a formula. Specifically, it requires:

- A consistent scoring rubric applied identically to every session
- Dimension-level subscores, not just an overall assessment, so you can isolate what changed
- Attribution that separates your behavior from the model's behavior mathematically, not just descriptively
- A recoverable cost estimate in dollars, not just a pattern label
- Session-to-session comparability — so you can tell if you're actually getting better

Insights tells you that you had 13 "wrong approach" friction events across 24 sessions. The prompt optimizer tells you that in session 7, your Rework Rate score was 8/15 because two correction turns within the first 5 exchanges indicate your opening prompt lacked acceptance criteria — and the estimated recoverable cost of that pattern across the project is $X.

Both views are true. They answer different questions.

---

## Why a Mathematical Model — Not Just Pattern Detection

The core problem with scoring AI coding sessions deterministically is attribution. When a session costs more than expected, the cause could be any combination of things: prompts that were too vague, context that kept getting re-injected, the model exploring files instead of writing code, corrections that compounded on each other.

These causes overlap and interact. A single bad prompt can trigger a file read cascade *and* a correction loop — and naive analysis double-counts the cost. You end up penalizing the same behavior twice and the score becomes noise.

Building a proper scoring model required solving three specific problems:

**1. Separating what you control from what Claude controls.** A correction turn could mean your prompt was underspecified, or it could mean the model made an error on a perfectly good prompt. Those have completely different remedies. Collapsing them into a single "correction penalty" makes the score look precise while being diagnostically useless. The model explicitly splits rework into *prompt-induced* (your side) and *model-induced* (Claude's side) before scoring either.

**2. Scaling from session to project.** A single session is too noisy for reliable signal. One expensive session might reflect a genuinely complex task — not bad prompting. Meaningful patterns emerge across sessions: the constraint you keep re-injecting turn after turn, the vague opener that reliably triggers a 15-file exploration cascade. The tool aggregates session-level scores into project-level rollups before drawing conclusions about habits.

**3. Expressing waste in dollars, not just labels.** A score of 71/100 doesn't change behavior. "Your `repeated_constraint` pattern cost an estimated $12.40 across this project — and it would take 30 seconds to move that constraint into `CLAUDE.md`" does. The formula translates behavioral patterns into recoverable dollar estimates.

---

## The Key Insight: 80% of Token Cost Comes From Tool Outputs

Here's what reading JSONL session logs surfaces that most developers using AI coding agents don't realize:

**80% of your token costs come from tool outputs — file reads, bash results, grep outputs — not from your actual prompts.**

When you write a vague prompt like "fix the authentication bug," Claude doesn't just generate a response. It reads 15 files trying to figure out which authentication bug you mean. Each of those tool calls pumps tokens into your context window — and you pay for every one of them.

A more specific prompt — "fix the JWT expiration check in `app/middleware/auth.ts`, the `verifyToken` function is not handling the `exp` claim correctly" — might trigger 2 file reads instead of 15. Same task, fraction of the cost.

Insights can identify that you have a "wrong approach" pattern. The token-level view this tool provides explains the *mechanical cost* of that pattern — exactly how many tokens the exploration cascade consumed, which turn it spiked on, and how much of it was recoverable.

---

## The Scoring Model

The tool produces a composite efficiency score (0–100) across five weighted dimensions, applied to every session independently:

| Dimension | Weight | What It Measures |
|---|---|---|
| Prompt Clarity | 25% | Prompt concreteness — penalized only when vagueness caused a correction |
| Context Efficiency | 30% | Tokens/turn benchmarks, repeated file reads, constraint re-injection |
| Rework Rate | 15% | Prompt-induced corrections and repeated constraints |
| AI Consistency | 10% | Model-induced corrections and unknown failures |
| Task Completion | 20% | Session arc: engagement, continuity, settlement |

Context Efficiency uses benchmark bands: Excellent (1k–8k tokens/turn), Normal (8k–20k), Heavy (20k–40k), Over-context (>40k sustained), with industry guardrails at median <12k and P90 <30k tokens/turn.

Task Completion models session health as three convergence gates: did productive tool use start within 3 turns of the opening prompt (Engagement)? Did execution sustain without correction spirals (Continuity)? Did the session end cleanly rather than mid-loop (Settlement)?

The split between Rework Rate and AI Consistency is the design decision that matters most. Both capture correction turns — but they measure different causes with different owners. Collapsing them, as the first version of this tool did, produces a score that feels precise but tells you nothing about what to actually fix.

---

## Nine Named Anti-Patterns With Fixed Impact Budgets

The scoring is driven by nine deterministic anti-pattern detectors — no LLM required, just pattern matching on observable signals in the JSONL logs.

**High severity:** Error dumps (pasting full stack traces instead of trimming to the relevant error), repeated constraints (restating the same rule in 3+ turns instead of putting it in `CLAUDE.md`), correction spirals (3+ consecutive user turns with no tool use), and abandoned sessions (session ends mid-correction loop with no resolution).

**Medium severity:** Vague openers (opening prompt under 20 tokens, immediately followed by a correction), file thrashing (same file read more than twice), prompt duplication (same text sent twice in one message), scope creep (session exceeds 300 turns with tool variety still expanding), and missing scaffolding (specific prompt still triggers model-induced correction).

Each anti-pattern carries a fixed point budget, split proportionally across the dimensions it affects. A `repeated_constraint` flag deducts from both Rework Rate (75%) and Context Efficiency (25%). The split prevents double-counting while preserving diagnostic precision — you know exactly where in the score the penalty landed and why.

---

## Session-Level Analysis, Project-Level Rollup

The tool operates at two levels simultaneously, because that's the only way to separate signal from noise.

At the **session level**, each run produces a scored efficiency report: which anti-patterns fired, which turns were the most expensive, what the model spent its time on, and whether the session converged cleanly or ended in an unresolved correction loop.

At the **project level**, the tool rolls up session scores to surface patterns that only become statistically visible across time. A single vague opener might be an anomaly. The same constraint re-injected in six consecutive sessions is a habit — and it has a recoverable dollar value attached to it, calculated in three layers: direct waste (redundant tokens in the repeated phrase), bounded rework (downstream tokens in a capped window after the triggering prompt), and project rollup (cumulative across all sessions).

This is where the tool pairs naturally with what Insights already surfaces. Insights tells you that "wrong approach" was your top friction type across 13 sessions. The project rollup tells you the token cost of that pattern, which sessions drove the most waste, and which specific prompting habit was the primary cause.

---

## Where This Goes Next

The current tool is a post-session analyzer. You run it after the fact, it scores what happened. That's useful, but the logical evolution builds directly on this foundation:

**IDE integration** is the highest-leverage near-term path. A VS Code extension that runs the rule engine before you hit send — flagging a prompt with no file path and no function name before the 15-file cascade starts — prevents waste instead of measuring it. Your session history becomes the training data; the IDE becomes the feedback loop.

**MCP server** is the version that closes the loop entirely. An MCP server exposing `analyze_session`, `suggest_claude_md_additions`, and `build_prompt_library` would let Claude itself access your efficiency history mid-session — preemptively asking for clarifying information when it detects a pattern that historically led to correction spirals in your projects. This is where the data model this tool builds becomes genuinely compound in value.

**Proxy layer** is the most ambitious path. A local HTTPS proxy between Claude Code and the Anthropic API — set one environment variable, every prompt routes through the optimizer first. Real-time scoring, pre-send warnings, automatic CLAUDE.md injection, smart model routing. The proxy catches the mistake before a token is spent.

**Team analytics** is the natural enterprise extension. The deterministic rule engine produces consistent measurements across users, which means you can aggregate: token spend per feature, prompt quality scores across a team, cost per PR. The data model supports it today.

---

## It's Open Source

The tool is MIT-licensed and available now. It's a Python CLI — `pip install -e .` and point it at your Claude session logs.

```bash
ai-dev analyze ~/.claude/logs/ --dedupe --export report.md
```

It supports configurable pricing profiles for cost estimation and exports detailed Markdown reports. No cloud dependency, no API calls required for core analysis.

**GitHub:** [github.com/abhinavag-svg/ai-coding-sessionprompt-analyzer](https://github.com/abhinavag-svg/ai-coding-sessionprompt-analyzer)

If you're using Claude Insights and want a complementary view — one that gives you a reproducible number per session, dimension-level subscores you can track over time, and a dollar figure attached to each anti-pattern — this is that tool. Contributions welcome. The rule engine is extensible: adding a new anti-pattern is a function returning a rule ID, severity, description, and impact estimate. If you've found a prompting pattern that wastes tokens, open a PR.

---

*Built with Claude. Scored by the tool that was built with Claude. It's prompts all the way down.*
