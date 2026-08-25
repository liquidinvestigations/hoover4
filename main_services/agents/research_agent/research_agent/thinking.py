"""Thinking-budget control for Qwen3.5 under vLLM.

## What the model actually does

Qwen3.5's chat template decides thinking in the *prompt*, not in the sampler:

    {%- if enable_thinking is defined and enable_thinking is true %}
        {{- '<think>\\n' }}          # opened, model reasons, model closes it
    {%- else %}
        {{- '<think>\\n\\n</think>\\n\\n' }}   # opened AND closed before generation
    {%- endif %}

So the default, with `enable_thinking` unset, gives **no thinking at all** rather than a
small thinking budget: the block is closed before the model emits its first token.
Measured on this host with Qwen3.5-2B, "what is 17*23, reason it out":

    thinking off (default)   441 completion tokens
    thinking on            1,735 completion tokens, closes </think> after ~1,300

That is the time/quality lever, and it is roughly 4x on an easy question. On a hard one
(a two-trains-and-a-bird puzzle) unbounded thinking does not converge at all:

    off (default)          19.0 s      594 tokens   finish=stop
    on (unbounded)        563.5 s   16,000 tokens   finish=length  <- never terminated
    budgeted 750           56.9 s    1,774 tokens   finish=length
    budgeted 375           49.8 s    1,399 tokens   finish=length

**`on` is not a safe production setting on this model** -- nine and a half minutes
without closing `</think>`. The budget is what makes thinking usable at all.

There is no half-way setting built into the model, and vLLM 0.17.1 has no
thinking-budget flag -- `max_thinking_tokens`, `thinking_budget` and
`reasoning_max_tokens` are all silently ignored in the request body (verified against
the running server, they change nothing).

## What this module adds

A budget in tokens, enforced where it can be: `max_tokens` bounds the whole completion,
and a budget of N means the reasoning is allowed N tokens before the answer has to fit
in the remainder. `AGENT_THINKING=budgeted` asks vLLM to stop at `</think>` once the
budget is spent, which turns an unbounded ramble into a bounded one at the cost of a
truncated thought -- acceptable, because the alternative is a turn that never ends.

Three modes:

* `off`     -- template prefills `<think></think>`. Fastest. **The current default.**
* `on`      -- unbounded reasoning. Slowest, best on multi-step questions.
* `budgeted`-- reasoning on, capped at `AGENT_THINKING_BUDGET_TOKENS`.

Tool-calling turns always run with thinking off regardless of mode. A tool call is a
routing decision, not a reasoning problem, and Qwen3.5-2B already reasons past the point
of usefulness into repeated calls (see `agent.py`'s `_repeated_call` guard). The budget
applies to
the turn that writes prose, which is where thinking changes the answer.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

log = logging.getLogger(__name__)

#: Modes, in increasing order of cost.
MODE_OFF = "off"
MODE_ON = "on"
MODE_BUDGETED = "budgeted"
VALID_MODES = (MODE_OFF, MODE_ON, MODE_BUDGETED)

#: Measured ceiling for an unbudgeted thought on Qwen3.5-2B (~1,300 tokens for a
#: trivial arithmetic question). The default budget is half of the round number above
#: it, which is the "half the thinking" setting.
UNBUDGETED_THINKING_TOKENS = 1_500
DEFAULT_BUDGET_TOKENS = UNBUDGETED_THINKING_TOKENS // 2

#: Room reserved for the answer itself once the thinking budget is spent. Without it a
#: budget equal to max_tokens leaves nothing to answer with.
ANSWER_TOKEN_ALLOWANCE = 1_024


def thinking_mode() -> str:
    """Configured mode, defaulting to `off` -- the behaviour before this existed."""
    raw = os.getenv("AGENT_THINKING", MODE_OFF).strip().lower()
    if raw in VALID_MODES:
        return raw
    # A typo must not silently buy 4x the latency in either direction.
    log.warning("AGENT_THINKING=%r is not one of %s; using %s", raw, VALID_MODES, MODE_OFF)
    return MODE_OFF


def thinking_budget_tokens() -> int:
    """Token budget for the reasoning block in `budgeted` mode."""
    raw = os.getenv("AGENT_THINKING_BUDGET_TOKENS", str(DEFAULT_BUDGET_TOKENS))
    try:
        value = int(raw)
    except ValueError:
        log.warning("AGENT_THINKING_BUDGET_TOKENS=%r is not a number; using %d", raw, DEFAULT_BUDGET_TOKENS)
        return DEFAULT_BUDGET_TOKENS
    # Below ~64 tokens the model cannot finish a thought and the truncation costs
    # quality with no latency saving worth having.
    return max(64, min(value, 32_768))


def thinking_kwargs(mode: str | None = None, budget: int | None = None) -> Dict[str, Any]:
    """Extra request body for a *prose-producing* LLM call.

    Returns `extra_body` content for langchain-openai: `chat_template_kwargs` selects
    the template branch, and `max_tokens` bounds the whole completion so a runaway
    thought cannot hold the request open until the agent timeout.
    """
    mode = mode or thinking_mode()

    if mode == MODE_OFF:
        return {"chat_template_kwargs": {"enable_thinking": False}}

    if mode == MODE_ON:
        return {"chat_template_kwargs": {"enable_thinking": True}}

    budget = budget if budget is not None else thinking_budget_tokens()
    return {
        "chat_template_kwargs": {"enable_thinking": True},
        "max_tokens": budget + ANSWER_TOKEN_ALLOWANCE,
    }


def tool_turn_kwargs() -> Dict[str, Any]:
    """Extra request body for a turn that may call a tool: thinking always off."""
    return {"chat_template_kwargs": {"enable_thinking": False}}


def describe() -> str:
    """One line for the startup log, so the mode is visible without reading env."""
    mode = thinking_mode()
    if mode == MODE_BUDGETED:
        return f"thinking={mode} budget={thinking_budget_tokens()} tokens"
    return f"thinking={mode}"
