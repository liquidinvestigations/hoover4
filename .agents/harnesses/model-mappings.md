# Model mappings

These names match the project role definitions. Update this table when a configured model
changes. `docs/development/Choosing_A_Model.md` describes how to assess a proposed change.

## The mappings

| harness | organizer | `executor-light` | `executor-heavy` | reviewer |
|---|---|---|---|---|
| Claude Code | `claude-opus-5-5`, high | `claude-opus-5-5`, medium | `claude-opus-5-5`, medium | `claude-opus-5-5`, high |
| Codex | `gpt-6-sol`, high | `gpt-5.6-terra`, high | `gpt-6-sol`, medium | `gpt-6-sol`, high |
| Cursor | `grok-4.7[effort=high]` | `composer-2.5[fast=false]` | `grok-4.7[effort=medium]` | `grok-4.7[effort=high]` |

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
Verify actual context limits when changing a model mapping.
A configured context limit does not create a default tool-call budget.

## Comparing models

Benchmark results differ across harnesses, reasoning settings, and workloads.
Use representative repository tasks when a model comparison is requested.
The model-selection guidance describes what to measure without imposing a fixed pass cap.
