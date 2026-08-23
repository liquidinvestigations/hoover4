# The model pair per harness

**These names go stale. The gates in `docs/development/Choosing_A_Model.md` do not.** Model
families here have shipped a new flagship every few weeks, so read this table as a shortlist and
qualify an executor by running it, never by its position on a leaderboard.

Nothing else in the tracked tree names a model. When a name changes, this file is the only edit.

## The pairs

| harness | planner | executor | executor window |
|---|---|---|---|
| Claude Code | Claude Opus 5 | Claude Sonnet 5 | 1M |
| Codex CLI | GPT-5.6 Sol | GPT-5.6 Terra | 1M |
| Cursor | Grok 4.6 | Composer 2.5, small passes only | not published |
| Kimi Code | `kimi-k3` | `kimi-k2.7-code` | 262K |
| Antigravity | Gemini Flash, current line | Gemini Flash, current line | large |
| Qwen Code | Qwen3.5 Plus | Qwen3.5 Flash | 1M on Plus |

Only the Claude Code row runs work here. The rest are recorded so a person setting one up starts
from a shortlist.

## Four things the table is not obvious about

**Composer 2.5 is a large quality drop for an extreme price drop.** It sits about fourteen points
below Grok 4.6 on Cursor's own benchmark, at roughly a tenth to a sixtieth of the cost. It has no
published context window, so it cannot pass the context gate, and it is admissible only for a
pass whose peak is known to be small.

**Antigravity's pair is not Pro and Flash.** The Flash line beats the Pro line on every published
coding benchmark in that family, and costs less. Pairing Pro as the planner buys a worse planner.
Use the current Flash model in both roles until that changes.

**Kimi's executor cannot hold a large pass.** At 262K its 60% budget is about 157,000 tokens,
which is below the 250,000 cap. The lower of the two limits binds, so a Kimi executor plans
against 157,000.

**A model whose whole window equals the cap fails the context gate.** That excludes the cheapest
tier in several families, by arithmetic rather than by opinion.

## Reading a leaderboard

Three aggregators collected on one day disagreed by fourteen points on one model on one benchmark
family. The spread comes from different harnesses, scaffolds, reasoning settings and dates, none
of them held constant. **A gap smaller than that spread is not a reason to switch models.**

The published benchmark closest to the shape of work here is long-horizon iterative coding, which
exists because models that score well on single-patch benchmarks degrade over long tasks. A pass
here runs 150 to 400 tool calls against a live stack, so a single-patch score says little.
