"""FastMCP router in front of one playwright-mcp sidecar per chat.

This server used to expose a single `browse_page` tool over a shared Chromium. It now
exposes **Playwright's whole browser surface** — navigate, click, type, fill forms, read
the accessibility snapshot, list network requests and console messages, take screenshots,
manage tabs — routed to a browser that belongs to the calling conversation and nobody
else. `browse_page` does not survive: reading a page is `browser_navigate` followed by
`browser_snapshot`, and keeping a fifth way to do it would only give a small model another
thing to pick wrongly.

How a call flows:

1. the tool name and arguments arrive here, with `x-hoover4-chat-session` naming the chat;
2. :mod:`.urlcheck` inspects every URL-shaped argument **before** anything is dispatched —
   this server sits inside a network where ClickHouse and Temporal answer unauthenticated,
   so the check is the boundary and refusals are *returned* to the model, not raised;
3. :mod:`.router` hands back that chat's :class:`ChatBrowser`, starting one if needed;
4. the call is forwarded to that chat's sidecar over MCP;
5. if the tool could have changed what is on screen, :mod:`.capture` screenshots and
   snapshots the page — **including when the call failed** — and appends the artifact id
   to the result under `_hoover4_artifacts`.

Tool *listing* never spawns a browser: it is answered from a warm template session started
on first ask. `list_tools` runs during graph construction for every chat, including the
ones that will never browse.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.tools.tool import Tool, ToolResult
from mcp.types import TextContent

from agent_common import artifacts

from browser_use_server import capture as capture_mod
from browser_use_server import chat_browser
from browser_use_server import router as router_mod
from browser_use_server.router import router
from browser_use_server.urlcheck import UrlNotAllowed, check_tool_arguments

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
)
log = logging.getLogger(__name__)

#: Header carrying the chat session id, so each conversation browses in its own browser.
#: Set by the research agent from the id the website passes it. Absent means the shared
#: anonymous session — see `router.ANONYMOUS`.
SESSION_HEADER = "x-hoover4-chat-session"
USER_HEADER = "x-hoover4-user"

#: One retry on a dead sidecar. A node process that died between calls should cost the
#: user a restart, not a failed answer; a *second* failure is real and is surfaced.
SIDECAR_RETRIES = 1

mcp = FastMCP(
    name=os.getenv("SERVER_NAME", "hoover4_browser"),
    instructions=os.getenv(
        "SERVER_INSTRUCTIONS",
        "Drive a real browser. Use this when a page renders its content with JavaScript, "
        "when a search result needs reading in full, or when the task requires "
        "interacting with a page rather than just reading it — clicking, filling a form, "
        "paging through results. Start with `browser_navigate`, then `browser_snapshot` "
        "to see the page as an accessibility tree with a `ref` for every element you can "
        "act on. Each conversation has its own browser: cookies and logged-in state "
        "persist between your calls within one chat and are invisible to every other "
        "chat. Only public http/https URLs are reachable.",
    ),
)


def _header(name: str) -> str:
    try:
        headers = get_http_headers()
    except Exception:  # noqa: BLE001 - called outside a request in tests
        return ""
    # Starlette lower-cases header names, but a direct dict does not.
    for key, value in dict(headers).items():
        if key.lower() == name:
            return (value or "").strip()
    return ""


def _refusal(message: str) -> ToolResult:
    """A refusal the model can read and act on.

    Returned, never raised: an opaque tool crash teaches the model nothing, and it will
    try the same internal host again. This says what was refused and why.
    """
    payload = {"success": False, "error": f"refused: {message}"}
    return ToolResult(
        content=[{"type": "text", "text": json.dumps(payload)}],
        structured_content=payload,
    )


class RoutedTool(Tool):
    """One of the sidecar's tools, re-exposed here with routing, checks and capture.

    The schema is copied verbatim from the template session, so the model sees exactly
    playwright-mcp's own contract. What this class adds is everything in the module
    docstring — and it adds it in the router rather than in the sidecar, because there is
    one sidecar per chat and the boundary has to hold for all of them.
    """

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        tool_name = self.name

        # 1. The security boundary, before anything is dispatched.
        try:
            check_tool_arguments(tool_name, arguments)
        except UrlNotAllowed as exc:
            log.info("refused %s: %s", tool_name, exc)
            return _refusal(str(exc))

        await router.ensure_reaper()
        session_id = _header(SESSION_HEADER)
        username = _header(USER_HEADER)

        try:
            chat = await router.get(session_id)
        except chat_browser.BrowserSpawnFailed as exc:
            log.error("could not start a browser for chat %r: %s", session_id, exc)
            return _refusal(f"no browser could be started: {exc}")

        # 2. Forward, serialised per chat. One conversation's calls must not interleave in
        #    its own browser; different conversations run in parallel, which is the whole
        #    reason the old global lock is gone.
        async with chat.lock:
            result, failed = await self._forward(chat, tool_name, arguments)

            # 3. Capture, including on failure — the error path is where the evidence
            #    matters most. A tool that captures nothing still gets an empty marker:
            #    the card authenticates the marker by its position, and that only works
            #    if every result this router returns ends with one.
            captured = None
            if capture_mod.should_capture(tool_name):
                captured = await capture_mod.capture(chat, tool_name, username, failed=failed)
            result = _attach_artifact(result, captured)

            # 4. Tab cap, AFTER the capture: capture reads the active tab, and closing
            #    tabs first could take the one the agent just acted on.
            await chat_browser.enforce_tab_cap(chat, router_mod.MAX_TABS_PER_CHAT)

        return result

    async def _forward(
        self, chat, tool_name: str, arguments: dict[str, Any]
    ) -> tuple[ToolResult, bool]:
        """Call the sidecar, restarting it once if it has died."""
        last_error: Exception | None = None
        for attempt in range(SIDECAR_RETRIES + 1):
            if chat.client is None or not chat_browser.sidecar_alive(chat):
                await chat_browser.restart_sidecar(chat)
            try:
                call = await chat.client.call_tool(
                    tool_name, arguments, raise_on_error=False
                )
            except Exception as exc:  # noqa: BLE001 - a dead sidecar looks like this
                last_error = exc
                log.warning(
                    "sidecar call %s failed (attempt %d): %s", tool_name, attempt + 1, exc
                )
                await chat_browser.restart_sidecar(chat)
                continue
            failed = bool(getattr(call, "is_error", False))
            return (
                ToolResult(
                    content=list(getattr(call, "content", []) or []),
                    structured_content=getattr(call, "structured_content", None),
                ),
                failed,
            )

        # Both attempts failed. This is returned as a tool error rather than raised so the
        # model sees a retryable failure instead of the connection wedging.
        return (
            _refusal(f"the browser sidecar is not responding: {last_error}"),
            True,
        )


#: Marker line carrying the capture ids in the tool result's **text**.
#:
#: `structured_content` is the right place for this and is where it also goes — but it
#: does not survive the path to the transcript. LangGraph's `on_tool_end` hands the
#: website a ToolMessage whose `content` is the text blocks and nothing else, so a card
#: reading only the structured key finds nothing and renders no thumbnail. Verified
#: against a real stored `tool_output`, which was the text and only the text.
#:
#: The cost is ~15 tokens of opaque line per browser call. The card parses it out and
#: **strips it before display**, so it is never shown to the user either.
#:
#: **It is always the last block, and it is always present** — `[hoover4:artifacts] []`
#: when there is nothing to report. That is not tidiness: the rest of a browser tool's
#: text *is the fetched page*, so a hostile page can write this marker into its own body
#: and, if it were the only one, have attacker-chosen titles and URLs rendered inside the
#: trusted "Archived page" chrome. The card only honours a marker on the final line, and
#: an unconditional trailing marker is what makes that check hold for every tool rather
#: than only for the ones that happened to capture something.
ARTIFACT_MARKER = "[hoover4:artifacts]"


def _attach_artifact(
    result: ToolResult, captured: capture_mod.CaptureResult | None
) -> ToolResult:
    """Record the capture on the tool result, in both places a consumer might look.

    The model is told nothing about this beyond an id it has no use for. It exists so the
    website can render the screenshot and the archived page on the tool card.

    `captured` of `None` (or a capture that produced no artifact) still appends an **empty**
    marker. See `ARTIFACT_MARKER`: the card trusts the marker only on the last line, and
    that only means anything if every result ends with one.
    """
    if captured is None or not captured.artifact_id:
        return _append_marker(result, [])
    entry = {
        "artifact_id": captured.artifact_id,
        "kind": artifacts.KIND_PAGE_CAPTURE,
        "status": captured.status,
        "url": captured.url,
        "title": captured.title,
    }
    if captured.detail:
        entry["detail"] = captured.detail

    return _append_marker(result, [entry])


def _append_marker(result: ToolResult, entries: list[dict]) -> ToolResult:
    """Put `entries` in both places a consumer might look, text marker last."""
    # 1. The structured key, for any client that preserves structured content (the host's
    #    .mcp.json entries do).
    structured = result.structured_content
    if isinstance(structured, dict):
        structured = dict(structured)
        structured[artifacts.ARTIFACTS_KEY] = entries
    else:
        structured = {artifacts.ARTIFACTS_KEY: entries}

    # 2. The text marker, for the transcript path — and it must be the FINAL block, since
    #    that position is what the card authenticates it by. See ARTIFACT_MARKER.
    content = list(result.content or [])
    content.append(
        TextContent(type="text", text=f"{ARTIFACT_MARKER} {json.dumps(entries)}")
    )

    return ToolResult(content=content, structured_content=structured)


async def _register_tools() -> int:
    """Copy the sidecar's tool list onto this server, once, from the template session."""
    template = await router.template()
    tools = await template.client.list_tools()
    for spec in tools:
        mcp.add_tool(
            RoutedTool(
                name=spec.name,
                title=getattr(spec, "title", None),
                description=spec.description or "",
                parameters=spec.inputSchema or {"type": "object", "properties": {}},
                output_schema=getattr(spec, "outputSchema", None),
            )
        )
    log.info("registered %d browser tools from the template session", len(tools))
    return len(tools)


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Any):
    from starlette.responses import JSONResponse

    return JSONResponse(
        {
            "status": "ok",
            "service": "hoover4-browser",
            "tools": len(await mcp.get_tools()),
            "sessions": router.describe(),
            **router.health(),
            "artifacts_enabled": artifacts.enabled(),
        }
    )


@mcp.custom_route("/sessions", methods=["GET"])
async def list_browser_sessions(_request: Any):
    from starlette.responses import JSONResponse

    return JSONResponse({"sessions": router.describe(), **router.health()})


@mcp.custom_route("/sessions/{session_id}/close", methods=["POST", "DELETE"])
async def close_browser_session(request: Any):
    """Drop one chat's browser.

    Called by the website when a conversation ends, so a chat's cookies and its two
    processes go with the chat rather than fifteen minutes later. Idempotent: closing an
    unknown or already-closed session is a 200 with `closed: false`, because the caller's
    goal ("this session must not be open") is satisfied either way.
    """
    from starlette.responses import JSONResponse

    session_id = request.path_params["session_id"]
    closed = await router.close(session_id)
    return JSONResponse({"session_id": session_id, "closed": closed})


def main() -> None:
    """Register the tools and serve, **on one event loop**.

    `mcp.run()` creates its own loop. Doing the registration on a separate loop first
    would leave the template browser's MCP client bound to a loop that no longer runs, and
    every later use of it would fail with a cross-loop error that names nothing useful. So
    `run_async` is awaited from the same `asyncio.run` that did the setup.
    """
    import asyncio

    log.info("Starting Hoover4 browser MCP router")

    async def serve():
        # The template browser starts here rather than lazily, so a broken image fails at
        # boot with a log line instead of on the first user's first tool call.
        try:
            count = await _register_tools()
            log.info("browser router ready with %d tools", count)
        except Exception:  # noqa: BLE001 - /health must still answer and say why
            log.exception("could not register browser tools from the template session")
        try:
            await mcp.run_async(
                transport="http",
                host=os.getenv("HOST", "0.0.0.0"),
                port=int(os.getenv("PORT", "8087")),
            )
        finally:
            await router.shutdown()

    asyncio.run(serve())


if __name__ == "__main__":
    main()
