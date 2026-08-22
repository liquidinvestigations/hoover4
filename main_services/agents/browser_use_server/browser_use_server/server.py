"""FastMCP router in front of one playwright-mcp sidecar per chat.

Each chat gets a browser that belongs to it and to nobody else. What this server
*advertises* over that browser is deliberately small: `read_page`, which opens a list of
URLs and returns their readable text with a screenshot and an archived copy each, plus six
interactive tools for pages that have to be driven — navigate, snapshot, click, type,
select an option, press a key.

The sidecar's other two dozen tools are registered **disabled**: absent from `list_tools`,
still routable, and one entry in `BROWSER_EXPOSED_TOOLS` away from coming back. Advertising
all of them made this one server four fifths of a research agent's tool list, and a tool
list that long costs accuracy — the evidence is that a seven-tool adaptive shortlist scores
level with a fixed fifty. `read_page` covers what almost all of them were reached for.

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
import re
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.tools.tool import Tool, ToolResult
from mcp.types import TextContent

from agent_common import artifacts, telemetry

from browser_use_server import capture as capture_mod
from browser_use_server import chat_browser
from browser_use_server import read_page
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
        "Read web pages with a real browser, and drive one when a page needs it. To read "
        "pages — including ones that render their content with JavaScript — call "
        "`read_page` with a list of URLs; it returns each page's text in one call. Only "
        "when a page must be *operated* — a form filled, a control clicked, results paged "
        "through — use `browser_navigate` then `browser_snapshot` to see the page as an "
        "accessibility tree with a `ref` for every element, then `browser_click`, "
        "`browser_type`, `browser_select_option` and `browser_press_key`. Each "
        "conversation has its own browser: cookies and logged-in state persist between "
        "your calls within one chat and are invisible to every other chat. Only public "
        "http/https URLs are reachable.",
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
            result = _drop_dead_links(result)

            captured = None
            if capture_mod.should_capture(tool_name):
                captured = await capture_mod.capture(chat, tool_name, username, failed=failed)
            result = _attach_artifact(result, captured, failed=failed)

            # 4. Tab cap, AFTER the capture: capture reads the active tab, and closing
            #    tabs first could take the one the agent just acted on.
            await chat_browser.enforce_tab_cap(chat, router_mod.MAX_TABS_PER_CHAT)

        return result

    async def _forward(
        self, chat, tool_name: str, arguments: dict[str, Any]
    ) -> tuple[ToolResult, bool]:
        """Call the sidecar, restarting it once if it has died."""
        import time

        last_error: Exception | None = None
        started = time.monotonic()
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
            # One `ai_service_telemetry` row per forwarded tool call. `/admin/ai_status`
            # had a browser column that no writer ever filled, so a dead router and an
            # unused one looked identical there — and the router is the capability most
            # likely to be quietly broken, because a page can fail for reasons that are
            # nobody's fault.
            telemetry.record_async(
                "browser", provider=tool_name,
                latency_ms=(time.monotonic() - started) * 1000.0,
                ok=not failed, detail=tool_name,
                session_id=chat.session_id,
            )
            return (
                ToolResult(
                    content=list(getattr(call, "content", []) or []),
                    structured_content=getattr(call, "structured_content", None),
                ),
                failed,
            )

        # Both attempts failed. This is returned as a tool error rather than raised so the
        # model sees a retryable failure instead of the connection wedging.
        telemetry.record_async(
            "browser", provider=tool_name,
            latency_ms=(time.monotonic() - started) * 1000.0,
            ok=False, detail=f"sidecar unresponsive: {last_error}",
            session_id=chat.session_id,
        )
        return (
            _refusal(f"the browser sidecar is not responding: {last_error}"),
            True,
        )


#: Markdown links into playwright-mcp's own output directory, e.g.
#: `- [Snapshot](.playwright-mcp/page-2026-08-07T16-54-18-139Z.yml)`.
#:
#: The sidecar writes large snapshots to a file inside its own container and links them by
#: relative path. Nothing on either side of this router can open that path: the model
#: cannot read files, and the website renders it as a broken link in the transcript. It is
#: dead weight that also invites the model to ask for a file that does not exist for it.
_DEAD_LINK = re.compile(r"^\s*-?\s*\[[^\]]*\]\(\.playwright-mcp/[^)]*\)\s*$", re.MULTILINE)

#: A section heading left with nothing under it once the dead link above is gone.
_EMPTY_TAIL_HEADING = re.compile(r"\n#+ *\w[^\n]*\s*$")


def _drop_dead_links(result: ToolResult) -> ToolResult:
    """Strip links into the sidecar's output directory from every text block."""
    content = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if isinstance(block, TextContent) and isinstance(text, str):
            cleaned = _DEAD_LINK.sub("", text)
            if cleaned != text:
                # `### Snapshot` followed by only that link is now a heading over nothing.
                cleaned = _EMPTY_TAIL_HEADING.sub("", cleaned.rstrip())
                block = TextContent(type="text", text=cleaned.rstrip())
        content.append(block)
    return ToolResult(content=content, structured_content=result.structured_content)


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
#: **It is always the last block, and it is always present** — `[hoover4:artifacts]
#: {"artifacts": []}` when there is nothing to report. That is not tidiness: the rest of a
#: browser tool's text *is the fetched page*, so a hostile page can write this marker into
#: its own body and, if it were the only one, have attacker-chosen titles and URLs rendered
#: inside the trusted "Archived page" chrome. The card only honours a marker on the final
#: line, and an unconditional trailing marker is what makes that check hold for every tool
#: rather than only for the ones that happened to capture something.
#:
#: The payload is an **object**, `{"artifacts": [...], "failed": true}`. The card also
#: accepts a bare array, because transcripts hold rows in that shape — but a
#: bare array has nowhere to put the one other thing the card cannot work out for itself:
#: whether the call *failed*. Playwright reports failure as `is_error` plus a prose line;
#: by the time the result reaches the website that flag is gone, and without `failed` the
#: card renders "opened http://clickhouse:8123" for a navigation that never happened. `failed`
#: is written only when true, so a successful call's marker is unchanged in size.
ARTIFACT_MARKER = "[hoover4:artifacts]"


def _attach_artifact(
    result: ToolResult,
    captured: capture_mod.CaptureResult | None,
    failed: bool = False,
) -> ToolResult:
    """Record the capture and the call's outcome on the tool result.

    The model is told nothing about this beyond an id it has no use for. It exists so the
    website can render the screenshot and the archived page on the tool card, and say out
    loud when the call did not do what its name suggests.

    `captured` of `None` (or a capture that produced no artifact) still appends an **empty**
    marker. See `ARTIFACT_MARKER`: the card trusts the marker only on the last line, and
    that only means anything if every result ends with one.
    """
    if captured is None or not captured.artifact_id:
        return _append_marker(result, [], failed=failed)
    entry = {
        "artifact_id": captured.artifact_id,
        "kind": artifacts.KIND_PAGE_CAPTURE,
        "status": captured.status,
        "url": captured.url,
        "title": captured.title,
    }
    if captured.detail:
        entry["detail"] = captured.detail

    return _append_marker(result, [entry], failed=failed)


def _append_marker(
    result: ToolResult, entries: list[dict], failed: bool = False
) -> ToolResult:
    """Put `entries` in both places a consumer might look, text marker last."""
    payload: dict[str, Any] = {"artifacts": entries}
    if failed:
        payload["failed"] = True

    # 1. The structured key, for any client that preserves structured content (the host's
    #    .mcp.json entries do). It keeps the bare-array shape: a client reading the
    #    structured key has `is_error` from MCP itself and needs no flag from us.
    #
    #    **Only ever ADDED to structured content the sidecar itself produced, never
    #    invented.** Most browser tools answer in TEXT and carry no structured content at
    #    all, and synthesising a dict for them turns `structured_content: None` into
    #    `{"_hoover4_artifacts": []}` — a non-empty structured result, which every client
    #    that prefers structured output over text (Claude Code does) shows the model
    #    INSTEAD of the text, discarding the snapshot, the `browser_evaluate` value, the
    #    console log and the network list. When there is nothing of the sidecar's to add
    #    to, the text marker below is the whole delivery, which is what it exists for.
    structured = result.structured_content
    if isinstance(structured, dict):
        structured = dict(structured)
        structured[artifacts.ARTIFACTS_KEY] = entries
    else:
        structured = None

    # 2. The text marker, for the transcript path — and it must be the FINAL block, since
    #    that position is what the card authenticates it by. See ARTIFACT_MARKER.
    content = list(result.content or [])
    content.append(
        TextContent(type="text", text=f"{ARTIFACT_MARKER} {json.dumps(payload)}")
    )

    return ToolResult(content=content, structured_content=structured)


#: The sidecar tools this server *advertises*, as a comma-separated env var.
#:
#: The sidecar exposes about thirty tools. Advertising all of them makes this one server
#: four fifths of the full-research agent's tool list, and a tool list that long costs
#: accuracy: an adaptive shortlist averaging seven tools scores level with a fixed fifty and
#: beats a fixed five by six points, so thirty from one server is the opposite of adaptive.
#: `read_page` below covers reading a page — the overwhelming majority of what the rest are
#: reached for — and these six cover driving one.
#:
#: **The unadvertised tools are not deleted.** They are registered disabled, so they are
#: absent from `list_tools` and one env var away from returning, and `read_page` still
#: composes `browser_evaluate` internally. A hardcoded list would drift silently the first
#: time the sidecar is upgraded, which is why this is configuration.
DEFAULT_EXPOSED_TOOLS = (
    "browser_navigate,browser_snapshot,browser_click,"
    "browser_type,browser_select_option,browser_press_key"
)


def exposed_tools() -> set[str]:
    raw = os.getenv("BROWSER_EXPOSED_TOOLS")
    if raw is None or not raw.strip():
        raw = DEFAULT_EXPOSED_TOOLS
    return {name.strip() for name in raw.split(",") if name.strip()}


#: The name `read_page` replaced. A model that learned the old name gets an error saying
#: what to call instead, not a silent shim: a shim that quietly works means the model never
#: discovers the batch form, which is the entire point of the rename.
RETIRED_TOOLS = {
    "browse_page": "read_page",
}


class RetiredTool(Tool):
    """A removed tool name that answers with the name that replaced it."""

    replacement: str = ""

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        return _refusal(
            f"`{self.name}` no longer exists. Call `{self.replacement}` instead — it takes "
            "a list of URLs and returns each page's readable text in one call."
        )


class ReadPageTool(Tool):
    """`read_page(urls=[…], goal=…)` — the batched ninety-percent case.

    Implemented here rather than forwarded, because it *is* several sidecar calls: navigate,
    extract, capture, per URL. See :mod:`.read_page`.
    """

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        import time

        started = time.monotonic()
        await router.ensure_reaper()
        session_id = _header(SESSION_HEADER)
        username = _header(USER_HEADER)

        try:
            chat = await router.get(session_id)
        except chat_browser.BrowserSpawnFailed as exc:
            log.error("could not start a browser for chat %r: %s", session_id, exc)
            return _refusal(f"no browser could be started: {exc}")

        async with chat.lock:
            if chat.client is None or not chat_browser.sidecar_alive(chat):
                await chat_browser.restart_sidecar(chat)
            outcome = await read_page.read(
                chat,
                arguments.get("urls"),
                str(arguments.get("goal") or ""),
                username,
            )
            await chat_browser.enforce_tab_cap(chat, router_mod.MAX_TABS_PER_CHAT)

        failed = bool(outcome.pages) and all(page.error for page in outcome.pages)
        # The real elapsed time, not zero: this is the slowest tool the router offers —
        # several navigations and captures — and `/admin/ai_status` averaging a hardcoded
        # zero into the browser column would make the one tool worth watching invisible.
        telemetry.record_async(
            "browser", provider="read_page",
            latency_ms=(time.monotonic() - started) * 1000.0,
            ok=not failed, detail=f"{len(outcome.pages)} page(s)",
            session_id=chat.session_id,
        )
        result = ToolResult(
            content=[TextContent(type="text", text=read_page.render(outcome))],
            structured_content=None,
        )
        return _append_marker(result, outcome.artifacts, failed=failed)


READ_PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "urls": {
            "type": "array",
            "items": {"type": "string"},
            "description": "The http/https pages to read, most promising first. Up to six.",
        },
        "goal": {
            "type": "string",
            "description": (
                "What you are looking for on these pages, in a few words. Used to choose "
                "which part of a long page survives the length limit."
            ),
        },
    },
    "required": ["urls"],
}

READ_PAGE_DESCRIPTION = (
    "Open several web pages and read them, in one call. Give it the URLs of search "
    "results worth reading in full and it navigates to each, waits for it to load, and "
    "returns the page's readable text with the navigation and adverts stripped, plus a "
    "screenshot and an archived copy the user can open. This is how you read a page: use "
    "it instead of navigating and snapshotting one URL at a time. Pass `goal` to say what "
    "you are looking for, so long pages are cut around the relevant part. Pages that "
    "refuse, time out or return nothing are reported individually — the rest still come "
    "back."
)


async def _register_tools() -> int:
    """Register `read_page`, the interactive allowlist, and the rest as disabled.

    Every sidecar tool is still registered, so restoring one is a change to
    `BROWSER_EXPOSED_TOOLS` and a restart rather than a code change, and a future adaptive
    layer has something to enable. What changes is which of them `list_tools` answers with.
    """
    template = await router.template()
    tools = await template.client.list_tools()
    allowed = exposed_tools()

    advertised = 0
    for spec in tools:
        enabled = spec.name in allowed
        mcp.add_tool(
            RoutedTool(
                name=spec.name,
                title=getattr(spec, "title", None),
                description=spec.description or "",
                parameters=spec.inputSchema or {"type": "object", "properties": {}},
                output_schema=getattr(spec, "outputSchema", None),
                enabled=enabled,
            )
        )
        advertised += int(enabled)

    mcp.add_tool(
        ReadPageTool(
            name="read_page",
            description=READ_PAGE_DESCRIPTION,
            parameters=READ_PAGE_SCHEMA,
        )
    )
    advertised += 1

    for old, new in RETIRED_TOOLS.items():
        mcp.add_tool(
            RetiredTool(
                name=old,
                description=f"Retired. Use `{new}`.",
                parameters={"type": "object", "properties": {}},
                enabled=False,
                replacement=new,
            )
        )

    missing = sorted(allowed - {spec.name for spec in tools})
    if missing:
        log.warning(
            "BROWSER_EXPOSED_TOOLS names %s, which the sidecar does not provide",
            ", ".join(missing),
        )
    log.info(
        "registered %d sidecar tools, advertising %d (%d held back)",
        len(tools), advertised, len(tools) - (advertised - 1),
    )
    return advertised


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Any):
    from starlette.responses import JSONResponse

    # `tools` is what a model is offered; `tools_registered` is everything routable,
    # including the held-back sidecar surface. Reporting only the second made the router
    # look as if the allowlist had done nothing.
    registered = await mcp.get_tools()
    return JSONResponse(
        {
            "status": "ok",
            "service": "hoover4-browser",
            "tools": sum(1 for tool in registered.values() if tool.enabled),
            "tools_registered": len(registered),
            "exposed_tools": sorted(exposed_tools()),
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
    would leave the template browser's MCP client bound to a dead loop, and
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
