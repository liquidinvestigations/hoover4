"""The request body of the thinking switch.

A Qwen-family chat template decides thinking in the prompt. With `enable_thinking` true
the template opens a `<think>` block and the model reasons before it answers. With it
false or unset the template opens and closes the block before generation, so the model
does not reason at all. The value goes in `chat_template_kwargs` of the request body.

The admin switch `server_settings.llm_thinking` (on `/admin/llm`) decides the value for
each agent model step. The worker reads the setting before each model call and sends
`thinking` in the step request. The title call and the compaction summary send
`enable_thinking: false` of their own.
"""

from __future__ import annotations

from typing import Any, Dict


def thinking_body(on: bool) -> Dict[str, Any]:
    """The `extra_body` of one model call, with thinking on or off."""
    return {"chat_template_kwargs": {"enable_thinking": bool(on)}}
