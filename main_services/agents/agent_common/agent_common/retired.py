"""Tool names that no longer exist, answered with the name that replaced them.

When a single-item tool becomes a batched one the old name has to go, or the model that
learned it never discovers the batch form — which is the entire point of the rename. But
it must not go *silently*: a model calling a name that has been removed gets the
transport's bare `Unknown tool`, which reads as "this capability is gone" rather than
"this moved", so it either gives up or retries the same name.

**Middleware, not a registered tool, and the reason is not stylistic.** FastMCP's
`enabled` flag gates listing and dispatch together: a disabled tool is absent from
`list_tools` *and* refuses to run, so its body never executes and the helpful error never
reaches anyone. "Hidden but live" cannot be expressed as a `Tool`. Intercepting the call
before the registry is consulted is what makes the alias hidden and answering at once.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastmcp.server.middleware import Middleware
from fastmcp.tools.tool import ToolResult

log = logging.getLogger(__name__)


class RetiredNames(Middleware):
    """Answer calls to retired names with the replacement.

    `replacements` maps an old tool name to `(new_name, what_it_does)`. The second half
    matters: a model told only "use read_documents" has to guess the arguments, and
    guessing wrong costs the same round trip the rename was meant to save.
    """

    def __init__(self, replacements: dict[str, tuple[str, str]]) -> None:
        self.replacements = replacements

    async def on_call_tool(self, context: Any, call_next: Any) -> ToolResult:
        name = getattr(getattr(context, "message", None), "name", "")
        retired = self.replacements.get(name)
        if retired is None:
            return await call_next(context)
        replacement, what = retired
        log.info("call to retired tool %s; pointing at %s", name, replacement)
        payload = {
            "success": False,
            "error": (
                f"`{name}` no longer exists. Call `{replacement}` instead — {what}."
            ),
        }
        return ToolResult(
            content=[{"type": "text", "text": json.dumps(payload)}],
            structured_content=payload,
        )


__all__ = ["RetiredNames"]
