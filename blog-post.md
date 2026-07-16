# Why I Built a Session-Level Analyzer for Claude Code, Even Though Claude Insights Already Exists

Claude Insights already exists, and it is genuinely useful.

It tells you what kinds of work you do, where friction shows up, which sessions went poorly, and what patterns repeat across a project. It can even suggest improvements to your `CLAUDE.md`. For project-level reflection, it is much better than most people expect.

So when I started building this tool, the real question was not:

> "Does Claude already have something like this?"

It was:

> "What is still missing if Insights already gives me a smart qualitative summary?"

The answer I kept running into was this: I needed **session-level, deterministic, auditable feedback**.

I wanted to know:

- Which exact session was wasteful?
- On which dimensions did it break down?
- Was the waste caused by my prompt, by repeated context, or by model behavior?
- How much of that waste was likely recoverable?
- Was I actually getting better week over week?

Insights gave me narrative understanding. I wanted a formula I could inspect, compare, and track over time.

That is why this project exists.

**GitHub:** [github.com/abhinavag-svg/ai-coding-sessionprompt-analyzer](https://github.com/abhinavag-svg/ai-coding-sessionprompt-analyzer)

---

## A Concrete Example of the Gap

One of the saved reports I analyzed made the difference very obvious.

At the project level, the analyzer repo itself showed:

- `$10.15` total cost
- `$9.09` estimated recoverable
- `89.6%` waste

At the session level, one session in that same project was scored:

- `50/100`
- shape: `Correction-Heavy`
- cost: `$6.01`
- recoverable: `$6.01`

That is exactly the kind of thing I wanted to see.

Claude Insights can tell me that a broader pattern exists across the project.
The session-level analyzer tells me which exact session went sideways, how badly, and which anti-patterns drove the waste.

---

## The Problem I Felt Personally

This tool came out of a frustration I kept having while building real projects with Claude Code.

Some sessions felt incredibly effective. I would give Claude a clear target, it would read the right files, make the change, run the right checks, and finish cleanly.

Other sessions felt expensive and messy:

- too many file reads
- repeated corrections
- the same constraints restated over and over
- long loops that should have been one clean pass
- work that was almost done, but needed multiple prompts to get there

The problem was not just that these sessions were annoying. It was that I had **no precise way to measure why they were expensive**.

Token spend alone was not enough.
Narrative summaries alone were not enough.
What I wanted was a way to look back at a session and say:

> "This cost more than it should have because the opening prompt was vague, the same files were re-read, and the task entered a correction spiral."

And I wanted that diagnosis to be reproducible.

---

## Why Session-Level Analysis Was Missing

Claude Insights operates at a very useful level: the project and behavior level.

It can tell you:

- your most common friction types
- what kinds of work you spend time on
- how sessions tend to go wrong
- what recurring habits might belong in `CLAUDE.md`

That is valuable, and this project is not trying to replace it.

But there is another level of analysis that matters if you care about prompt quality as an engineering discipline: the **single session**.

A session is where prompting choices actually get made.

That is where you can observe:

- whether the first prompt was specific enough
- whether context was scoped well or sprayed too broadly
- whether Claude had to re-read the same files repeatedly
- whether corrections came from prompt ambiguity or model instability
- whether the task converged cleanly or died mid-loop

Project summaries are excellent for pattern recognition.
Session scoring is better for **measurement**.

If you want to improve your workflow, you need both.

---

## Why Insights and This Tool Can Coexist

The cleanest way to describe the difference is this:

- **Claude Insights** gives you a smart narrative about your work.
- **This tool** gives you a deterministic scorecard for each session.

Insights is answering:

> "What seems to be happening across my workflow?"

This tool is answering:

> "How exactly did this session perform, why did it score that way, and what part of the waste was recoverable?"

Those are not competing questions.
They are complementary ones.

In fact, the best experience is using them together:

- Insights provides the broad behavioral story.
- Session-level analysis provides the measurement layer underneath it.

That measurement layer matters because once you have a deterministic per-session score, you can:

- compare one session to another
- benchmark your own prompting habits over time
- attach specific anti-patterns to specific costs
- quantify improvement instead of just describing it

---

## The Core Insight That Changed How I Thought About Prompting

The biggest thing I learned from reading Claude Code session logs is this:

> Most of the cost is usually not your typed prompt. It is the context explosion that follows.

In practice, a vague request does not just generate a vague answer.
It often triggers a chain of tool calls:

- file reads
- grep results
- bash output
- repeated exploration
- repeated clarification

That output becomes context.
And that context is where a lot of the spend comes from.

This changed the entire framing of the project for me.
I stopped thinking only about "Was the prompt good?"
I started thinking about:

> "Did the prompt cause an expensive session shape?"

That is a much more useful question.

---

## What "Deterministic" Means Here

This word matters, so it is worth being explicit.

In this project, "deterministic" means:

- the core score is computed from fixed rules over JSONL session logs
- the same session should produce the same result on repeated runs
- every deduction can be traced back to an observable signal
- the core scoring path does not require an LLM call

There may be optional recommendation layers elsewhere in the product, but the core methodology is rule-based and auditable.

---

## The Methodology: How the Score Is Calculated

The scoring model is intentionally deterministic.
The core analyzer does not rely on an LLM to decide whether a session was efficient.

Instead, it parses Claude Code JSONL logs and computes a composite score out of five weighted dimensions:

| Dimension | Weight | What it measures |
|---|---:|---|
| Prompt Clarity | 25 | Was the prompt concrete enough to guide execution? |
| Context Efficiency | 30 | Did the session send the right amount of context, without repeated reads or context thrash? |
| Rework Rate | 15 | How much rework came from prompting habits? |
| AI Consistency | 10 | How much rework appeared model-induced rather than prompt-induced? |
| Task Completion | 20 | Did the session engage, sustain, and converge cleanly? |

The analyzer starts from observable signals in the logs:

- prompt text
- token counts
- tool calls
- turn sequencing
- repeated file reads
- correction turns
- session endings

From there it derives scores and anti-patterns.

### 1. Prompt Clarity

This dimension looks for signs that the opening prompt gave Claude enough direction:

- file paths
- symbol names
- explicit targets
- acceptance criteria

Importantly, low specificity alone is not enough to trigger a penalty.
The penalty only matters when vagueness appears to have caused rework.

That means the tool is trying to avoid a common mistake in scoring systems: penalizing concise prompts that actually worked fine.

### 2. Context Efficiency

This is the most important dimension in the model.

It measures how much new context had to be loaded turn by turn, including:

- average and percentile incremental tokens per turn
- repeated file reads
- repeated constraint injection
- sustained over-context behavior

The key idea here is that prompt waste is often indirect.
The expensive part is not the original sentence.
The expensive part is the chain of reads, outputs, and re-reads it causes.

### 3. Rework Rate

This dimension tracks prompting habits that create avoidable loops:

- prompt-induced correction turns
- repeated restatement of the same constraints

This is the "what part of the churn came from me?" section of the score.

### 4. AI Consistency

Not all rework is the user's fault.

Sometimes the prompt is good, but the model still goes down the wrong path.
This dimension isolates those cases so the score stays useful.

That split matters a lot.
If you collapse all corrections into one bucket, the score feels numeric but is not actionable.
You cannot tell whether the fix is:

- write a better prompt
- add stronger scaffolding
- switch tactics
- or simply recognize that the model was unstable in that session

### 5. Task Completion

This dimension models the shape of the session:

- did productive tool use start soon enough?
- did the task stay on track?
- did it converge cleanly?
- or did it end inside a correction loop?

This turns session quality into something you can reason about rather than just feel.

---

## The Anti-Pattern Layer

The score is only useful if it can explain itself.

That is why the most important output is not really the composite number.
It is the anti-pattern layer underneath it.

The analyzer currently uses deterministic detectors for patterns such as:

- full error dumps instead of trimmed errors
- repeated constraints that should live in `CLAUDE.md`
- correction spirals
- abandoned sessions
- vague openers
- repeated file reads
- duplicated prompts
- scope creep
- missing scaffolding around otherwise specific prompts

Each anti-pattern has:

- a fixed impact budget
- a mapping to one or more score dimensions
- a concrete remedy
- a recoverable cost estimate

That means the score is not just:

> "You got 68."

It is closer to:

> "You lost points here because the same constraint was re-injected across turns, this drove context waste, and this pattern has an estimated recoverable cost."

That is a much more useful form of feedback.

---

## Why Recoverable Cost Matters

I did not want this tool to stop at labels.

It is one thing to say:

- you had repeated corrections
- you re-read files
- you pasted overly long errors

It is another thing to say:

> "These behaviors likely cost you real money, and a chunk of that was recoverable."

That framing changes how people use the tool.

A score is interesting.
A cost estimate is motivating.

Once you can tie waste to habits, fixes become much more obvious:

- move repeated constraints into `CLAUDE.md`
- trim stack traces before sending them
- front-load file paths and acceptance criteria
- split broad tasks earlier

---

## Important Caveats

This is not a claim of perfect financial attribution.

Recoverable cost is best understood as a directional estimate, not an accounting truth. It is a heuristic based on observable waste patterns, bounded deductions, and capped rollups. That makes it useful for prioritization, but not a precise statement that "this exact dollar amount would certainly have been saved."

There are also sessions the analyzer can misread:

- healthy exploration in a genuinely unfamiliar codebase
- debugging sessions that require trial and error
- intentionally broad refactors
- long sessions that are expensive because the task itself was large, not because the prompting was poor

So the intended use is primarily:

- self-benchmarking over time
- comparing sessions within a project or workflow
- identifying recurring prompting habits worth fixing

It is not meant to be a universal ranking of developers or a claim about final code quality.

---

## How the Project Evolved Over Time

This did not start as a polished scoring framework.

It evolved in stages.

### Phase 1: "Why are some sessions so much more expensive?"

The earliest version of the idea was basically cost curiosity.
I wanted to understand why two sessions that felt similar could have very different token bills.

That led to the first big realization: the expensive part was often not the prompt itself, but the tool-output cascade it triggered.

### Phase 2: "Can I identify recurring waste patterns?"

Once I started looking at sessions structurally, the same patterns kept showing up:

- repeated context
- file thrash
- vague starts
- correction loops
- prompts that looked short and innocent but produced very expensive session behavior

At that point, simple totals were no longer enough.
The project became an anti-pattern detector.

### Phase 3: "A list of patterns is useful, but I still need a score"

The next step was realizing that pattern detection without a scoring model still leaves a gap.

If you want to answer:

> "Am I improving?"

you need consistency.

That pushed the project toward:

- fixed dimensions
- explicit weights
- traceable deductions
- per-session comparability

### Phase 4: "The score must separate my mistakes from Claude's mistakes"

This was the design change that made the tool much better.

Early scoring approaches tended to lump corrections together.
That produced a number, but not a diagnosis.

The project improved when it started separating:

- prompt-induced rework
- model-induced rework
- session convergence failures
- context inefficiency

That separation made the output much more actionable.

### Phase 5: "This should not replace Insights, it should plug into it"

Over time the product direction became clearer:
the right move was not to compete with Claude Insights as a dashboard, but to complement it with a more rigorous measurement layer.

That is what led to the HTML injection path as well.
Instead of forcing a separate experience, the analyzer can now enrich the report developers are already looking at.

---

## Why I Felt the Need to Build It

At a personal level, I wanted a tool that would have helped me while I was learning how to work well with Claude Code.

I did not just want advice like:

- "be more specific"
- "use `CLAUDE.md` better"
- "avoid vague prompts"

I wanted something more concrete:

- show me which session broke down
- show me where the cost came from
- tell me whether the issue was my prompt, the session shape, or the model
- make the tradeoffs visible enough that I can change my habits

That is the product I kept wishing existed.

So I built the version I wanted to use myself.

---

## What I Think Is Still Important to Say Clearly

This tool is not claiming to measure absolute coding quality.

It measures prompting efficiency from what is visible in the logs.
That is an important limitation.

JSONL logs can tell you:

- what was asked
- what tools were called
- how much context was consumed
- where correction loops appeared
- whether the session seems to have converged

They cannot perfectly tell you whether the final code was actually good.

So the right claim is not:

> "This tool knows whether Claude solved your task correctly."

The right claim is:

> "This tool can measure how efficiently the session was run, and where prompting behavior appears to have created waste."

That distinction matters.

---

## Where This Goes Next

Right now, this is a post-session analyzer.
You run it after the work is done.

But the longer-term direction is obvious:

- use session history to improve future prompting
- detect repeated constraints and promote them into `CLAUDE.md`
- move from post-mortem analysis toward pre-send guidance
- eventually build feedback loops directly into the coding workflow

The real ambition is not just to score past sessions.
It is to help create better future ones.

---

## How to Use the CLI

The tool is a local CLI. You point it at your Claude Code session logs and either export a standalone report or inject the analysis directly into Claude Insights.

Basic install:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Generate a Markdown report from Claude session logs:

```bash
ai-dev analyze ~/.claude/projects --export report.md
```

Inject the analysis into Claude Insights HTML:

```bash
/insights
ai-dev analyze ~/.claude/projects --insights-html ~/.claude/usage-data/report.html
```

Estimate min/max cost ranges with different pricing assumptions:

```bash
ai-dev cost-range ~/.claude/projects
```

The HTML injection path is the most compelling day-to-day workflow because it lets you keep Claude Insights as the main reading surface while layering in session efficiency, project cost summary, and token cost by anti-pattern from `ai-dev`.

If you want recommendations beyond the deterministic scoring path, there is also an optional recommendation mode documented in the repo, but the core analyzer works locally without needing an LLM call for the score itself.

---

## Closing Thought

Claude Insights helped prove that analyzing coding-agent behavior is worthwhile.
This project comes from the next question:

> "What if I also want a session-level measurement system I can audit, compare, and improve against?"

That is the gap this tool tries to fill.

Not instead of Insights.
Alongside it.

If Insights gives the story, this tool tries to give the scorecard.

And when you are trying to get better at something, having both is a lot more useful than having only one.
