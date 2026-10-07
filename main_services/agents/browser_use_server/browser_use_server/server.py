"""Serve page reads, captured-page citations, and isolated interactive browsers.

Each chat has its own interactive browser. Page reads use a separate bounded queue.
Successful owned reads store Markdown before `cite_pages` can return verified quotes.
URL checks run before external browser requests. Tool listing uses a template session.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware
from fastmcp.tools.tool import Tool, ToolResult
from mcp.types import TextContent

from agent_common import artifacts, telemetry

from browser_use_server import capture as capture_mod
from browser_use_server import chat_browser
from browser_use_server import read_page, internal_fetch, page_citations
from browser_use_server.reader_routes import Reader
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
#: anonymous session. See `router.ANONYMOUS`.
SESSION_HEADER = "x-hoover4-chat-session"
USER_HEADER = "x-hoover4-user"
#: Header carrying the agent run id. When it is present, the browser is keyed by the run,
#: so two runs of one chat never share a browser. The chat session stays the key for a
#: caller that sends no run id.
RUN_HEADER = "x-hoover4-agent-run"
#: Header carrying the byte share of one call's result. The research agent sends it
#: (`X-Hoover4-Page-Share`). `read_page` fits its whole result inside it.
PAGE_SHARE_HEADER = "x-hoover4-page-share"


#: Bytes kept free beside the marker block for the separator that a client puts between
#: two content blocks when it joins them.
MARKER_SLACK = 16


def page_share() -> int:
    """The byte ceiling of this call's result: the page share header, else
    `read_page.DEFAULT_PAGE_BYTES`."""
    raw = _header(PAGE_SHARE_HEADER)
    try:
        share = int(raw)
    except ValueError:
        return read_page.DEFAULT_PAGE_BYTES
    return share if share > 0 else read_page.DEFAULT_PAGE_BYTES


def browser_key() -> str:
    """The router key of this request: the run id, else the chat session id."""
    return _header(RUN_HEADER) or _header(SESSION_HEADER)

#: One retry on a dead sidecar. A node process that died between calls should cost the
#: user a restart, not a failed answer; a *second* failure is real and is surfaced.
SIDECAR_RETRIES = 1

mcp = FastMCP(
    name=os.getenv("SERVER_NAME", "hoover4_browser"),
    instructions=os.getenv(
        "SERVER_INSTRUCTIONS",
        "Read web pages with a real browser, and drive one when a page needs it. To read "
        "pages, including ones that render their content with JavaScript, call "
        "`read_page` with a list of URLs; it returns each page's text in one call. Only "
        "when a page must be *operated* (a form filled, a control clicked, results paged "
        "through) use `browser_navigate` then `browser_snapshot` to see the page as an "
        "accessibility tree with a `ref` for every element, then `browser_click`, "
        "`browser_type`, `browser_select_option` and `browser_press_key`. Your browser is "
        "your own: cookies and logged-in state persist between your calls and are "
        "invisible to every other chat and agent run. Only public "
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


def _busy(exc: Exception) -> ToolResult:
    """The typed `browser_busy` error: every browser under the cap has a call in flight."""
    payload = {"success": False, "error": "browser_busy", "message": str(exc)}
    return ToolResult(
        content=[{"type": "text", "text": json.dumps(payload)}],
        structured_content=payload,
    )


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
    docstring, and it adds it in the router rather than in the sidecar, because there is
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
        session_id = browser_key()
        username = _header(USER_HEADER)

        try:
            chat = await router.get(session_id)
        except router_mod.BrowserBusy as exc:
            log.warning("no browser for %r: %s", session_id, exc)
            return _busy(exc)
        except chat_browser.BrowserSpawnFailed as exc:
            log.error("could not start a browser for chat %r: %s", session_id, exc)
            return _refusal(f"no browser could be started: {exc}")

        # 2. Forward, serialised per chat. One conversation's calls must not interleave in
        #    its own browser; different conversations run in parallel, which is the whole
        #    reason the old global lock is gone.
        async with chat.lock:
            result, failed = await self._forward(chat, tool_name, arguments)

            # 3. Capture, including on failure, the error path is where the evidence
            #    matters most. A tool that captures nothing still gets an empty marker:
            #    the card authenticates the marker by its position, and that only works
            #    if every result this router returns ends with one.
            result = _drop_dead_links(result)
            result = _loading_note(tool_name, result)

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
            # unused one looked identical there, and the router is the capability most
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
SNAPSHOT_NOT_INCLUDED = ("The page tree is not in this result. Call browser_snapshot to read it. "
                         "Call read_page with the URL to read the text of the page.")
_LOADING = re.compile(r'^\s*- (status|progressbar) "Loading[^"]*"', re.MULTILINE)


def _drop_dead_links(result: ToolResult) -> ToolResult:
    """Replace inaccessible snapshot links with a readable note."""
    content = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if isinstance(block, TextContent) and isinstance(text, str):
            lines = text.splitlines()
            kept = []
            changed = False
            for line in lines:
                if _DEAD_LINK.fullmatch(line):
                    changed = True
                    if kept and kept[-1].strip() == "### Snapshot":
                        kept.append(SNAPSHOT_NOT_INCLUDED)
                    continue
                kept.append(line)
            if changed:
                cleaned = "\n".join(kept)
                cleaned = _EMPTY_TAIL_HEADING.sub("", cleaned.rstrip())
                block = TextContent(type="text", text=cleaned.rstrip())
        content.append(block)
    return ToolResult(content=content, structured_content=result.structured_content)


def _loading_note(tool_name: str, result: ToolResult) -> ToolResult:
    """Name loading elements when a snapshot still shows an incomplete page."""
    if tool_name != "browser_snapshot":
        return result
    count = sum(len(_LOADING.findall(getattr(block, "text", "") or ""))
                for block in result.content or [] if isinstance(block, TextContent))
    if count == 0:
        return result
    content = list(result.content or [])
    note = (f"NOTE: {count} elements say Loading. The page is not complete. "
            "browser_wait_for can wait for a change.")
    for index in range(len(content) - 1, -1, -1):
        block = content[index]
        if isinstance(block, TextContent):
            content[index] = TextContent(type="text", text=f"{block.text.rstrip()}\n{note}")
            break
    return ToolResult(content=content, structured_content=result.structured_content)


#: Marker line carrying the capture ids in the tool result's **text**.
#:
#: `structured_content` is the right place for this and is where it also goes, but it
#: does not survive the path to the transcript. LangGraph's `on_tool_end` hands the
#: website a ToolMessage whose `content` is the text blocks and nothing else, so a card
#: reading only the structured key finds nothing and renders no thumbnail. Verified
#: against a real stored `tool_output`, which was the text and only the text.
#:
#: The cost is ~15 tokens of opaque line per browser call. The card parses it out and
#: **strips it before display**, so it is never shown to the user either.
#:
#: **It is always the last block, and it is always present**: `[hoover4:artifacts]
#: {"artifacts": []}` when there is nothing to report. That is not tidiness: the rest of a
#: browser tool's text *is the fetched page*, so a hostile page can write this marker into
#: its own body and, if it were the only one, have attacker-chosen titles and URLs rendered
#: inside the trusted "Archived page" chrome. The card only honours a marker on the final
#: line, and an unconditional trailing marker is what makes that check hold for every tool
#: rather than only for the ones that happened to capture something.
#:
#: The payload is an **object**, `{"artifacts": [...], "failed": true}`. The card also
#: accepts a bare array, because transcripts hold rows in that shape, but a
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


def _marker_text(entries: list[dict], failed: bool = False) -> str:
    """The text marker block of a result: `ARTIFACT_MARKER` and its JSON payload."""
    payload: dict[str, Any] = {"artifacts": entries}
    if failed:
        payload["failed"] = True
    return f"{ARTIFACT_MARKER} {json.dumps(payload)}"


def _append_marker(
    result: ToolResult, entries: list[dict], failed: bool = False
) -> ToolResult:
    """Put `entries` in both places a consumer might look, text marker last."""

    # 1. The structured key, for any client that preserves structured content (the host's
    #    .mcp.json entries do). It keeps the bare-array shape: a client reading the
    #    structured key has `is_error` from MCP itself and needs no flag from us.
    #
    #    **Only ever ADDED to structured content the sidecar itself produced, never
    #    invented.** Most browser tools answer in TEXT and carry no structured content at
    #    all, and synthesising a dict for them turns `structured_content: None` into
    #    `{"_hoover4_artifacts": []}`, a non-empty structured result, which every client
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

    # 2. The text marker, for the transcript path, and it must be the FINAL block, since
    #    that position is what the card authenticates it by. See ARTIFACT_MARKER.
    content = list(result.content or [])
    content.append(TextContent(type="text", text=_marker_text(entries, failed)))

    return ToolResult(content=content, structured_content=structured)


#: The sidecar tools this server *advertises*, as a comma-separated env var.
#:
#: The sidecar exposes about thirty tools. Advertising all of them makes this one server
#: four fifths of the full-research agent's tool list, and a tool list that long costs
#: accuracy: an adaptive shortlist averaging seven tools scores level with a fixed fifty and
#: beats a fixed five by six points, so thirty from one server is the opposite of adaptive.
#: `read_page` below covers reading a page (the overwhelming majority of what the rest are
#: reached for), and these six cover driving one.
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


#: Names that no longer exist, and what to call instead.
#:
#: A model that learned an old name gets an error *naming the replacement*, not a silent
#: shim: a shim that quietly works means the model never discovers the batched form, which
#: is the entire point of the rename. And not the transport's bare `Unknown tool` either,
#: that tells the model the capability is gone rather than that it moved, and it will either
#: give up or retry the same name.
RETIRED_TOOLS = {
    "browse_page": (
        "read_page",
        "it takes a list of URLs and returns each page's readable text in one call",
    ),
}


class RetiredNames(Middleware):
    """Answer a call to a retired name with the name that replaced it.

    Middleware rather than a registered tool, because those two states are not both
    available from one flag. FastMCP's `enabled` governs listing **and** dispatch together:
    a disabled tool is not advertised *and* cannot be called, so a hidden tool that answers
    when called cannot be expressed as a `Tool` at all. Intercepting the call before the
    registry is consulted is what makes the alias hidden and live at the same time.
    """

    async def on_call_tool(self, context, call_next):
        retired = RETIRED_TOOLS.get(getattr(context.message, "name", ""))
        if retired is None:
            return await call_next(context)
        replacement, what = retired
        log.info("call to retired tool %s; pointing at %s", context.message.name, replacement)
        return _refusal(
            f"`{context.message.name}` no longer exists. Call `{replacement}` instead, "
            f"which {what}."
        )


class ReadPageTool(Tool):
    """`read_page(urls=[…], goal=…)`, the batched ninety-percent case.

    Implemented here rather than forwarded, because it *is* several sidecar calls: navigate,
    extract, capture, per URL. See :mod:`.read_page`.
    """

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        import time

        started = time.monotonic()
        await router.ensure_reaper()
        session_id = browser_key()
        username = _header(USER_HEADER)

        ceiling = page_share()
        reader = Reader(router.reader, username, session_id)
        outcome = await read_page.read(
            reader, arguments.get("urls"), str(arguments.get("goal") or ""), username,
            max(0, int(arguments.get("offset") or 0)),
            find=str(arguments.get("find") or ""),
            version=str(arguments.get("version") or "").strip(),
            ceiling=ceiling, links=arguments.get("links", True) is not False,
        )

        chat_session = _header(SESSION_HEADER)
        if username and chat_session:
            retained = False
            for page in outcome.pages:
                try:
                    retained = bool(await asyncio.to_thread(
                        page_citations.store_read, username, chat_session, page)) or retained
                except Exception:
                    log.exception("could not retain citation text for %s", page.url)
                    outcome.note += " The page preview could not be stored. Read the page again before citing it."
            if retained:
                outcome.note += (
                    " Before using these facts, call cite_pages with this read_page URL and short exact terms from this text. "
                    "Put the returned handle beside each supported claim. A read_page result alone is not a citation."
                )

        failed = bool(outcome.pages) and all(page.error for page in outcome.pages)
        blocked = sum(1 for page in outcome.pages if page.blocked)
        detail = f"{len(outcome.pages)} page(s)"
        if blocked:
            # The count of blocked pages for a period is summed from this text.
            detail += f", {blocked} blocked by a bot check"
        # The real elapsed time, not zero: this is the slowest tool the router offers
        # (several navigations and captures), and `/admin/ai_status` averaging a hardcoded
        # zero into the browser column would make the one tool worth watching invisible.
        telemetry.record_async(
            "browser", provider="read_page",
            latency_ms=(time.monotonic() - started) * 1000.0,
            ok=not failed, detail=detail,
            session_id=session_id,
        )
        # The model reads the page text and the marker block, so both fit the share.
        marker = _marker_text(outcome.artifacts, failed)
        read_page.fit(outcome, ceiling, reserved=len(marker.encode("utf-8")) + MARKER_SLACK)
        result = ToolResult(
            content=[TextContent(type="text", text=read_page.render(outcome))],
            structured_content=None,
        )
        return _append_marker(result, outcome.artifacts, failed=failed)


class CitePagesTool(Tool):
    """Return verified quotes and stable references to previously read page text."""

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        payload = await page_citations.cite(
            _header(USER_HEADER), _header(SESSION_HEADER), arguments.get("pages") if "pages" in arguments else [
                {key: arguments[key] for key in ("url", "terms", "version", "why") if key in arguments}
            ],
        )
        return ToolResult(content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
                          structured_content=payload)


CITE_PAGES_SCHEMA = {
    "type": "object",
    "properties": {"pages": {"type": "array", "minItems": 1, "maxItems": page_citations.MAX_PAGES_PER_CALL,
        "items": {"type": "object", "properties": {
            "url": {"type": "string", "description": "Copy an address successfully read with read_page."},
            "terms": {"type": "array", "minItems": 1, "maxItems": 8,
                      "items": {"type": "string", "minLength": 1, "maxLength": 200},
                      "description": "Copy exact source wording to quote and highlight. Case must match."},
            "version": {"type": "string", "description": "Select a read_page text version when needed."},
            "why": {"type": "string", "maxLength": 300, "description": "State what the page supports."},
        }, "required": ["url", "terms"]}}},
    "anyOf": [{"required": ["pages"]}, {"required": ["url", "terms"]}],
}
CITE_PAGES_SCHEMA["properties"].update(CITE_PAGES_SCHEMA["properties"]["pages"]["items"]["properties"])

CITE_PAGES_DESCRIPTION = (
    "Cite web pages that support the answer. Search for each source and read it with read_page first. "
    "Give its read_page URL and exact terms from the supporting passage. "
    "The tool verifies those terms against the stored Markdown and returns quotes with stable [W1] handles. "
    "Place each returned handle beside its claim. The reader sees the source card and can open its captured text. "
    "Unread pages, blocked pages, and absent terms cannot supply a citation. "
    'Use these handles in place of bare source URLs. Prefer one page per call. '
    'For one page use flat arguments: {"url":"COPY_READ_URL","terms":["COPY_EXACT_PHRASE"]}. '
    'Use short exact phrases. Correct failed calls before answering.'
)


READ_PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "urls": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Give the most promising HTTP or HTTPS page addresses first. "
                "Give at most six addresses. "
                "For repository data files, use raw file addresses. "
                "On GitLab, replace /-/blob/ with /-/raw/."
            ),
        },
        "goal": {
            "type": "string",
            "description": (
                "What you are looking for on these pages, in a few words. "
                "The capture records this goal. This field does not search the text. "
                "Use find for a literal text search."
            ),
        },
        "offset": {
            "type": "integer",
            "minimum": 0,
            "default": 0,
            "description": (
                "Character position in the complete page text. For a plain read, copy the cut line's next offset. "
                "For find matches, copy the more line's next offset with the same find and version. "
                "The result length is not the next match offset."
            ),
        },
        "find": {
            "type": "string",
            "description": (
                "Literal text to find in the page's extracted text, in any case, from offset "
                "on. The result gives each match with the text around it and its character "
                "offset, in place of the page text."
            ),
        },
        "links": {
            "type": "boolean", "default": True,
            "description": "Include link destinations in the extracted Markdown.",
        },
        "version": {
            "type": "string",
            "description": (
                "The version that a cut line or a find result gives. With it, the call reads "
                "the same kept text and does not load the page again."
            ),
        },
    },
    "required": ["urls"],
}

READ_PAGE_DESCRIPTION = (
    "Read web pages or raw repository data files. Give it the URLs of search "
    "results worth reading in full and it navigates to each, waits for it to load, and "
    "returns the page's readable text with the navigation and adverts stripped, plus a "
    "screenshot and an archived copy the user can open. This is how you read a page: use "
    "it instead of navigating and snapshotting one URL at a time. Pass `goal` to record "
    "what you are looking for. Cut pages keep text order. Pages that "
    "refuse, time out or return nothing are reported individually, and the rest still come "
    "back. Some sites show a bot check page, for example \"Just a moment...\". read_page "
    "waits for it to clear. If it does not clear, the page is reported as BLOCKED BY A BOT "
    "CHECK, and its text is not the page. Do not use that text as a source. Try the "
    "archived copy with web_search and sources [\"wayback\"], or another page. "
    "A cut result gives the next character offset and the text's version. Pass one URL with "
    "that offset and version to read its next part. To find entries in a long page, pass "
    "`find` with a literal text: the result gives each match with its offset, and a next "
    "offset when more matches remain. Copy the more line's offset with the same find and version for the next matches. "
    "For a file of a code repository, read its raw address, "
    "such as the `/-/raw/` address on GitLab or `raw.githubusercontent.com` for GitHub. The "
    "viewer page of a large file does not hold its text."
)


async def _register_tools() -> int:
    """Register page reads, page citations, and the interactive allowlist.

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

    mcp.add_tool(CitePagesTool(name="cite_pages", description=CITE_PAGES_DESCRIPTION,
                               parameters=CITE_PAGES_SCHEMA))
    advertised += 1

    mcp.add_middleware(RetiredNames())

    missing = sorted(allowed - {spec.name for spec in tools})
    if missing:
        log.warning(
            "BROWSER_EXPOSED_TOOLS names %s, which the sidecar does not provide",
            ", ".join(missing),
        )
    log.info(
        "registered %d sidecar tools, advertising %d (%d held back)",
        len(tools), advertised, len(tools) - (advertised - 2),
    )
    return advertised


@mcp.custom_route("/internal/fetch", methods=["POST"])
async def fetch_for_search(request: Any):
    """Serve authenticated search fetches through a separate bounded browser queue."""
    import hmac
    from pathlib import Path
    from starlette.responses import JSONResponse

    token_file = os.getenv("BROWSER_FETCH_TOKEN_FILE", "")
    try:
        token = Path(token_file).read_text().strip() if token_file else ""
    except OSError:
        token = ""
    supplied = request.headers.get("authorization", "")
    if not token or not hmac.compare_digest(supplied.encode("utf-8"), ("Bearer " + token).encode("utf-8")):
        return JSONResponse({"error": "The internal fetch caller is not authorized.",
                             "error_kind": "refused"}, status_code=403)
    try:
        body = await request.json()
    except (ValueError, UnicodeError):
        body = None
    if not isinstance(body, dict) or not isinstance(body.get("url"), str):
        return JSONResponse({"error": "Give a JSON object with a URL string.",
                             "error_kind": "refused"}, status_code=400)
    if body.get("method", "GET") != "GET":
        return JSONResponse({"error": "Only GET requests are supported.",
                             "error_kind": "refused"}, status_code=400)
    for name in ("params", "headers"):
        if body.get(name) is not None and not isinstance(body[name], dict):
            return JSONResponse({"error": f"{name} must be an object.",
                                 "error_kind": "refused"}, status_code=400)
    if body.get("body", internal_fetch.RAW_BODY) not in internal_fetch.BODY_KINDS:
        return JSONResponse({"error": "body must be raw or dom.",
                             "error_kind": "refused"}, status_code=400)
    try:
        timeout = float(body.get("timeout_s", internal_fetch.DEFAULT_TIMEOUT_S))
    except (ValueError, TypeError):
        return JSONResponse({"error": "timeout_s must be a number.",
                             "error_kind": "refused"}, status_code=400)
    outcome = await internal_fetch.fetch(
        router.metasearch, body["url"], params=body.get("params"),
        headers=body.get("headers"), timeout_s=timeout,
        body=body.get("body", internal_fetch.RAW_BODY),
    )
    return JSONResponse(outcome.as_dict())


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


@mcp.custom_route("/runs/{run_id}/release", methods=["POST", "DELETE"])
async def release_run_browser(request: Any):
    """Drop one agent run's browser.

    The agent run workflow calls it once when a run ends. The idle reaper is the second
    release path. Idempotent: an unknown or already released run is a 200 with
    `released: false`.
    """
    from starlette.responses import JSONResponse

    run_id = request.path_params["run_id"]
    released = await router.close(run_id)
    return JSONResponse({"run_id": run_id, "released": released})


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
        # A profile folder that an earlier process left behind belongs to no browser now.
        removed = chat_browser.sweep_leftover_profiles()
        if removed:
            log.info("removed %d leftover browser profile folder(s)", removed)
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
