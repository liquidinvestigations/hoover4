# Model mappings

These names match the project role definitions. Update this table when a configured model
changes. The gates in `docs/development/Choosing_A_Model.md` define how a model qualifies.

## The mappings

| harness | organizer | `executor-light` | `executor-heavy` | reviewer |
|---|---|---|---|---|
| Claude Code | `claude-opus-5`, high | `claude-sonnet-5`, high | `claude-opus-5`, medium | `claude-opus-5`, xhigh |
| Codex | `gpt-5.6-sol`, high | `gpt-5.6-terra`, high | `gpt-5.6-sol`, medium | `gpt-5.6-sol`, xhigh |
| Cursor | `grok-4.6[effort=high]` | `composer-2.5[fast=false]` | `grok-4.6[effort=medium]` | `grok-4.6[effort=xhigh]` |

## Other harnesses

| harness | organizer candidate | executor candidate | executor window |
|---|---|---|---|
| Kimi Code | `kimi-k3` | `kimi-k2.7-code` | 262K |
| Antigravity | Gemini Flash, current line | Gemini Flash, current line | large |
| Qwen Code | Qwen3.5 Plus | Qwen3.5 Flash | 1M on Plus |

Kimi model selection stays in the user configuration. The other rows are candidates for
configuration and do not define project roles.

## Platform limits

Claude Code, Codex and Cursor have project agent definitions. Cursor can substitute a
compatible model when a plan or team policy blocks the selected model.
Codex custom agent settings take precedence over an explicit spawn value. An active session
can retain role definitions that changed on disk. Start a fresh session to use changed names.
Claude accepts a per-invocation model value that takes precedence over the role file. The
organizer omits that value. Codex role files point to the Claude role instructions. Cursor
role files are generated from the Claude role files with Cursor model identifiers.
Claude and Codex executor models have a one-million-token window in the recorded model data.
Cursor has not published a Composer 2.5 context window. Apply the lower of the 60 percent
window limit and the pass cap when sizing a package.

## Four things the table does not make clear

**Composer 2.5 has a lower coding score and a lower price than Grok 4.6.** Cursor's published
benchmark places it about fourteen points below Grok 4.6. Its context window is unpublished.
Use it only when the pass peak is known to fit.

**Antigravity uses the Flash line for both candidates.** The current Flash line leads the Pro
line on the published coding benchmarks cited in the model selection research.

**Kimi's executor has a 262K window.** Its 60 percent budget is about 157,000 tokens.
That value is below the 250,000 pass cap, so the lower limit applies.

**A model whose whole window equals the pass cap fails the context gate.** This excludes the
cheapest model in several families by calculation.

## Reading a leaderboard

Benchmark results differ across harnesses, scaffolds, reasoning settings and collection dates.
A single-patch score gives limited evidence for a pass that uses many tools against a live stack.
Qualify a model with the acceptance trial in `docs/development/Choosing_A_Model.md`.
