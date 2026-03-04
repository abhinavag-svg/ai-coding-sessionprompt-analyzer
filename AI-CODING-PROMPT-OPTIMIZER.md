# AI Coding Prompt Optimizer
**Codename: Vibe Coding Optimizer**

> Brainstormed: February 23, 2026  
> Status: Idea / Pre-build  
> Origin: Lessons learned building a production Shopify app in 7 days with $20 in AI tokens

---

## The Problem

Developers using Claude Code (and AI coding agents broadly) waste significant token budget — and therefore money — not because they write too much, but because they prompt inefficiently. The root causes are:

- **Open-ended prompts** that trigger broad codebase exploration (15 files read when 2 were needed)
- **Missing negative constraints** that cause Claude to touch files it shouldn't
- **Repeated context** across sessions that belongs in `CLAUDE.md` but lives in prompts
- **No visibility** into which prompts are expensive until after the money is spent
- **Correction turns** that double the cost of a task that was underspecified the first time
- **Wrong model selection** — using Sonnet for tasks Haiku handles perfectly

The kicker: **80% of token cost in a session comes from tool outputs (file reads, bash results) — not from the developer's actual messages.** Most developers don't know this. They optimize the wrong thing.

---

## The Solution

A two-layer system:

### Layer 1: MCP Server (Reactive — Post-Session Analysis)
An MCP server that reads `~/.claude/projects/*.jsonl` session files and analyzes prompting patterns over time. Runs locally, free, no API calls needed for core analysis.

### Layer 2: Local Proxy (Proactive — Real-Time Interception)
A local HTTPS proxy that sits between Claude Code and the Anthropic API. Intercepts every prompt before it's sent, runs the rule engine, warns about expensive patterns, and optionally rewrites the prompt — before a single token is spent.

The proxy is the higher-value layer: **catching a $0.50 mistake before it happens is worth more than analyzing it afterward.**

---

## Architecture

```
[Claude Code] → [Local Proxy :8080] → [Anthropic API]
                      |
              ┌───────┴────────┐
              │   Rule Engine  │  (free, TypeScript)
              │   Haiku calls  │  (optional, ~$0.001)
              │   Session log  │  (JSONL append)
              │   Dashboard    │  (localhost:3001)
              └────────────────┘
                      |
              ┌───────┴────────┐
              │   MCP Server   │  (historical analysis)
              └────────────────┘
```

### Proxy Setup (One Env Variable)
```bash
export ANTHROPIC_BASE_URL=http://localhost:8080
claude  # all traffic now routes through optimizer
```

---

## Core Features

### MCP Server Tools

| Tool | What It Does | LLM Needed? |
|---|---|---|
| `analyze_session(id)` | Parse JSONL, flag expensive patterns, score prompts | No |
| `compare_sessions(ids[])` | Token usage trends across multiple sessions | No |
| `suggest_claude_md_additions(path)` | Extract repeated constraints → CLAUDE.md diff | Haiku (optional) |
| `build_prompt_library(path)` | Find zero-correction prompts → PROMPTS.md template | No |
| `token_breakdown(id)` | Cost by turn, cache hits, most expensive prompt | No |

### Proxy Capabilities

| Feature | Description | Cost |
|---|---|---|
| Real-time prompt scoring | Rule engine fires before send | Free |
| Pre-send warnings | Flag vague/expensive prompts | Free |
| Auto CLAUDE.md injection | Inject constraints into every request | Free |
| Smart model routing | Haiku for simple tasks, Sonnet for complex | Saves 40-60% |
| Response caching | Cache repeated file reads within session | Free |
| Live dashboard | Real-time token spend at localhost:3001 | Free |
| Prompt rewrite suggestions | Haiku-powered improved version on request | ~$0.001/call |

---

## Rule Engine (No LLM Required)

All detection rules are pure TypeScript — zero API cost:

```typescript
// 1. VAGUENESS DETECTOR
// Flag prompts under 50 words with no file path mentioned
if (wordCount < 50 && !prompt.includes('/') && !prompt.includes('.ts'))
  → "Too vague — no file path or specific target mentioned"

// 2. OPEN-ENDED EXPLOSION DETECTOR
// Prompt triggered 5+ file reads
if (toolCalls.filter(t => t.name === 'Read').length >= 5)
  → "Triggered broad file exploration — add a hypothesis to scope it"

// 3. REPEATED CONSTRAINT DETECTOR
// Same phrase in 3+ sessions = belongs in CLAUDE.md
const repeated = findRepeatedPhrases(allSessions, minOccurrences: 3)
  → "Move to CLAUDE.md: 'must be synchronous', 'do not modify KNOWN_APPS'"

// 4. CORRECTION TURN DETECTOR
// user → assistant → user (same topic) = underspecified prompt
if (isCorrection(turn[i+2], turn[i]))
  → "Correction turn detected — what constraint was implicit?"

// 5. MISSING NEGATIVE CONSTRAINTS
// Write prompt with no "do not" clause
if (isWritePrompt && !prompt.includes('do not') && !prompt.includes("don't"))
  → "No negative constraints — Claude may edit files you didn't intend"

// 6. TYPE AMBIGUITY DETECTOR
// Function prompt without explicit return type
if (isWritePrompt && !prompt.match(/\):\s*\w+/))
  → "Return type not specified — add explicit TypeScript signature"

// 7. TOKEN SPIKE DETECTOR
// Most expensive turn by input_tokens from JSONL usage field
const spike = turns.sort((a,b) => b.usage.input_tokens - a.usage.input_tokens)[0]

// 8. SUBAGENT SCOPE DETECTOR
// Task tool with no file constraints = expensive broad run
if (toolCall.name === 'Task' && !toolCall.input.prompt.includes('only'))
  → "Subagent has no file scope — add 'read only X and Y'"
```

---

## Where LLM Is Actually Needed (Optional, Targeted)

| Task | Model | Est. Cost |
|---|---|---|
| Prompt rewrite suggestions | Haiku | ~$0.001 |
| Semantic duplicate detection | Haiku embeddings | ~$0.0001 |
| CLAUDE.md diff generation | Haiku | ~$0.002 |
| Everything else | None | Free |

Full week analysis of a typical project: **under $0.05 total.**

---

## Tech Stack

```
Runtime:        Node.js + TypeScript
MCP SDK:        @modelcontextprotocol/sdk
Proxy server:   Express or Fastify (lightweight)
JSONL parsing:  readline (stdlib)
Schema validation: zod
Dashboard:      Simple HTML/SSE (no framework needed for v1)
Database:       None — reads flat files, fully stateless
LLM (optional): Anthropic SDK → Haiku only
```

Consistent with the Shopify app stack. No new tools to learn.

---

## Monetization Paths

### Tier 1: Low Effort, Real Revenue
- **Open source + managed cloud (Freemium):** Free local MCP server on GitHub. Charge $9–$19/month for hosted version with cross-machine history and web dashboard.
- **Prompt template marketplace:** Sell curated prompt packs by stack/task type (Shopify, Remix, Prisma). $9–$29 per pack.

### Tier 2: Medium Effort, Higher Ceiling
- **Team/Enterprise tier:** Team dashboard showing aggregate token usage, prompt quality scores, convention standardization across codebases. $49–$99/month per team.
- **MCP gateway listing:** List on MCP-Hive or Kong marketplace as a paid tool. $0.001–$0.01 per analysis invocation — no billing to manage.
- **Consulting / audit service:** Human review layer on top of automated analysis. One-time prompt audit for engineering teams. $500–$2,000 per engagement.

### Tier 3: High Effort, Highest Ceiling
- **AI Dev Productivity Analytics SaaS:** Zoom out to the full problem — token spend per feature, prompt quality scores, session trends, cost per PR. The AI-native equivalent of LinearB/Swarmia. $5M–$50M ARR ceiling, 12–18 month build.

---

## Competitive Landscape

No direct competitor exists for **local, session-aware prompt analysis specifically for Claude Code**. Nearest adjacents:
- General token tracking scripts (show total cost, not *why*)
- `/context` command (snapshot only, no history)
- Third-party dashboards (spend tracking, not prompt-level patterns)

**The gap is real.**

---

## Key Risks

| Risk | Mitigation |
|---|---|
| Anthropic changes JSONL schema | Version parser defensively, watch release notes |
| TOS concerns on proxy | Use API keys only, never subscription auth |
| Privacy sensitivity | Local-only by default, never exfiltrate session data |
| Low value on short projects | Minimum 3+ days of sessions for pattern signal |

---

## Distribution Strategy

The blog post *"From Idea to Shipped: What I Learned Building a Production App in 7 Days for $20"* is already the marketing for this product. The audience it reaches — developers building with Claude Code who care about token efficiency — is exactly the buyer.

**Narrative:** *"I built an app, learned these lessons the hard way, then built the tool that would have taught me faster."*

### Launch Sequence
- **Week 1:** Build and open source the MCP server. Publish companion blog: *"I Built an MCP Server That Analyzes Your Own Claude Code Sessions."*
- **Week 2–4:** Watch GitHub issues for product direction signal.
- **Month 2:** Add `PROMPTS.md` generator + hosted option. Start charging.
- **Month 3+:** Build team dashboard if enterprise interest emerges.

---

## v1 Scope (Weekend Build)

Minimum viable version in 1–2 days:

- [ ] Parse `~/.claude/projects/*.jsonl` files
- [ ] Implement 8 core detection rules
- [ ] `analyze_session` MCP tool
- [ ] `suggest_claude_md_additions` MCP tool
- [ ] Basic CLI output with flagged prompts + suggested fixes
- [ ] README with setup instructions

That's it. Ship that. Everything else is iteration.

---

## Related Reading
- Claude Code best practices: https://code.claude.com/docs/en/best-practices
- MCP server build guide: https://modelcontextprotocol.io/docs/develop/build-server
- Token cost management: https://code.claude.com/docs/en/costs
- LLM proxy patterns: https://apipark.com/techblog/en/mastering-llm-proxy-optimize-your-ai-applications/
- `!` prefix for bash commands: https://dev.to/rajeshroyal/stop-wasting-tokens-the-prefix-that-every-claude-code-user-needs-to-know-2c6i
