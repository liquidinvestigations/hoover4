"""The workspace tools: the text files that the agent writes in a conversation.

``read_file``   one file with a ``N|`` line gutter, or the list of files
``write_file``  create or replace a whole file
``patch_file``  replace one region of a file
``finish_with_report``  select report versions as the answer of the turn

A write or a patch saves work and selects nothing. ``finish_with_report`` validates the
selected versions through the same owner and session scope as a read, and returns them. The
worker runs it after every other call of its batch, and a successful result ends the turn
without another model step (`tasks/P_agent/workflows.py`, `tasks/P_workspace/selection.py`).

The rules live in the pipeline: storage and the read format in `database.chat_workspace`,
and the write and patch rules in `tasks/P_workspace`. A read goes to storage directly. A
write or a patch goes to the session writer workflow `WorkspaceWriter` with
signal-with-start, and this module polls the receipt of its operation id. The operation id
is the idempotency key that the worker gives the tool call (`X-Hoover4-Idempotency-Key`), so
a retried call returns the stored result and changes the file once.

A refusal is a tool error whose text is the JSON result. A writer that gives no receipt
within `WRITER_WAIT_SECONDS` gives a failure with `retryable` true, and the worker sends the
call again with the same key.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Annotated, Any, Optional

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, Field

from agent_todo_server import workspace_views
from agent_todo_server.identity import CallerUnknown, parse_caller
from database import chat_workspace as store

log = logging.getLogger(__name__)

IDEMPOTENCY_HEADER = "x-hoover4-idempotency-key"
RUN_HEADER = "x-hoover4-agent-run"
#: The queue and the names of the writer workflow (`tasks/P_workspace/workflows.py`).
WRITER_TASK_QUEUE = "chat-queue"
WRITER_WORKFLOW = "WorkspaceWriter"
WRITER_PREFIX = "workspace-"
SUBMIT_SIGNAL = "submit"
WRITER_WAIT_SECONDS = float(os.getenv("WORKSPACE_WRITER_WAIT_SECONDS", "60"))
POLL_SECONDS = 0.3

_client: Any = None
_client_lock = asyncio.Lock()


async def temporal_client():
    global _client
    async with _client_lock:
        if _client is None:
            from temporalio.client import Client

            # TEMPORAL_NAMESPACE and TEMPORAL_API_KEY name the namespace and the key of the installation, as
            # main_services/processing/tasks/temporal_client.py reads them. Compose sets neither.
            _client = await Client.connect(os.getenv("TEMPORAL_ADDRESS", "temporal:7233"),
                                           namespace=os.getenv("TEMPORAL_NAMESPACE", "").strip() or "default",
                                           api_key=os.getenv("TEMPORAL_API_KEY", "").strip() or None)
        return _client


def _refuse(body: dict) -> None:
    raise ToolError(json.dumps(body, ensure_ascii=False))


def _caller_and_headers():
    headers = {k.lower(): v for k, v in get_http_headers().items()}
    try:
        caller = parse_caller(headers)
    except CallerUnknown as exc:
        _refuse({"success": False, "error": str(exc)})
    return caller, headers


async def submit(op: str, name: str, **fields: Any) -> str:
    """Send one command to the session writer and wait for its receipt."""
    caller, headers = _caller_and_headers()
    operation_id = (headers.get(IDEMPOTENCY_HEADER) or "").strip() or f"direct-{uuid.uuid4()}"
    command = {"username": caller.username, "session_id": caller.session_id,
               "operation_id": operation_id, "run_id": (headers.get(RUN_HEADER) or "").strip(),
               "op": op, "name": name, **fields}
    receipt = await asyncio.to_thread(store.read_receipt, caller.username, caller.session_id,
                                      operation_id)
    if receipt is None:
        try:
            client = await temporal_client()
            await client.start_workflow(
                WRITER_WORKFLOW, {"username": caller.username, "session_id": caller.session_id,
                                  "pending": []},
                id=f"{WRITER_PREFIX}{caller.session_id}", task_queue=WRITER_TASK_QUEUE,
                start_signal=SUBMIT_SIGNAL, start_signal_args=[command])
        except Exception as exc:  # noqa: BLE001 - every failure to reach the writer is a transport failure
            log.warning("could not reach the workspace writer of %s: %s", caller.session_id, exc)
            _refuse({"success": False, "retryable": True,
                     "error": f"The workspace writer could not be reached: {type(exc).__name__}."})
        waited = 0.0
        while receipt is None and waited < WRITER_WAIT_SECONDS:
            await asyncio.sleep(POLL_SECONDS)
            waited += POLL_SECONDS
            receipt = await asyncio.to_thread(store.read_receipt, caller.username,
                                              caller.session_id, operation_id)
    if receipt is None:
        _refuse({"success": False, "retryable": True,
                 "error": f"The workspace writer gave no result within {WRITER_WAIT_SECONDS:g} s."})
    log.info("workspace %s %s of %s: ok=%s version=%s", op, name, caller.session_id,
             receipt.ok, receipt.version)
    if not receipt.ok:
        _refuse(receipt.result)
    return json.dumps(receipt.result, ensure_ascii=False)


class SelectedFile(BaseModel):
    """One more report file of a finish_with_report call."""

    name: str = Field(description="The file name, such as appendix.md.")
    version: int = Field(description="The version to show, from the write, the patch or read_file.")


def _selected(username: str, session_id: str, name: str, version: Any) -> dict:
    """One selected version with its citation handles. A refusal names the problem."""
    problem = store.valid_name(name)
    if name.startswith('./tmp/'):
        problem = 'Select a report outside ./tmp/.'
    if problem:
        _refuse({"success": False, "error": problem})
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        _refuse({"success": False, "error": f"Give the version of {name} as a number from 1."})
    try:
        found = store.read_version(username, session_id, name, version)
        names = [] if found is not None else [f["name"] for f in store.list_files(username, session_id)]
    except Exception as exc:  # noqa: BLE001 - a storage failure is a transport failure
        log.warning("could not read %s of %s: %s", name, session_id, exc)
        _refuse({"success": False, "retryable": True,
                 "error": f"The workspace could not be read: {type(exc).__name__}."})
    if found is None:
        _refuse({"success": False, "error": f"{name} has no version {version}." + (
            f" The files are {', '.join(names)}. Read a file to see its version."
            if names else " The workspace has no files.")})
    return {"name": found.name, "version": found.version,
            # A stored citation is an object with its `handle`, as the writer resolved it.
            "citations": [c["handle"] for c in found.citations
                          if isinstance(c, dict) and isinstance(c.get("handle"), str)]}


def register(mcp) -> None:
    """Add workspace reads, edits and report selection to the server."""

    @mcp.tool(
        name="read_file",
        description=(
            "Read a workspace file by name or a saved result by path. Offsets start at 1. "
            "A file name uses line offsets. A path uses character offsets. "
            "Copy next_offset to continue. Omit both selectors to list files."
        ),
    )
    def read_file(
        name: Annotated[Optional[str], Field(description="The file name, such as report.md. Leave it out to list the files.")] = None,
        version: Annotated[int | str | None, Field(description="A report version number or saved result version string.")] = None,
        offset: Annotated[int, Field(description="The first line to read, from 1.")] = 1,
        limit: Annotated[int, Field(description="Maximum report lines or saved result characters.")] = store.MAX_READ_LINES,
        path: str | None = None,
        line_offset: Annotated[int | None, Field(ge=1, description="Start a path read at this file line.")] = None,
    ) -> str:
        caller, headers = _caller_and_headers()
        if path is not None:
            if name is not None:
                _refuse({"success": False, "error": "Give either name or path."})
            allowed = workspace_views.collection_access(caller, headers.get("x-hoover4-collections", "").split(","))
            entry, text = workspace_views.body(caller, allowed, path, version)
            start = min(len(text), max(0, offset - 1))
            if line_offset is not None:
                if entry["kind"] != "file":
                    _refuse({"success": False, "error": "Line selection applies to workspace files."})
                start = sum(map(len, text.splitlines(keepends=True)[:line_offset - 1]))
            end = min(len(text), start + max(1, min(10000, limit)))
            return json.dumps({**entry, "text": text[start:end], "start": start, "end": end,
                               "next_offset": end + 1 if end < len(text) else None},
                              ensure_ascii=False)
        if not name:
            files = store.list_files(caller.username, caller.session_id)
            return json.dumps({"files": [{k: f[k] for k in ("name", "version", "chars")} for f in files]},
                              ensure_ascii=False)
        problem = store.valid_name(name)
        if problem:
            _refuse({"success": False, "error": problem})
        if isinstance(version, str):
            try:
                version = int(version)
            except ValueError:
                _refuse({"success": False, "error": "A file version must be an integer."})
        found = store.read_version(caller.username, caller.session_id, name, version)
        if found is None:
            names = [f["name"] for f in store.list_files(caller.username, caller.session_id)]
            missing = f"{name} has no version {version}." if version else f"{name} does not exist."
            _refuse({"success": False, "error": missing + (
                f" The files are {', '.join(names)}." if names else " The workspace has no files.")})
        return json.dumps(store.render_read(found, offset, limit), ensure_ascii=False)

    def scope():
        caller, headers = _caller_and_headers()
        allowed = workspace_views.collection_access(caller, headers.get("x-hoover4-collections", "").split(","))
        return caller, allowed

    @mcp.tool(name="workspace_list", description="List workspace files and stored results by path or kind.")
    def workspace_list(prefix: str = "", kind: str = "", cursor: str = "",
                       limit: Annotated[int, Field(ge=1, le=100)] = 50) -> dict:
        return workspace_views.listing(*scope(), prefix, kind, cursor, limit)

    @mcp.tool(name="workspace_search", description="Search saved text. Return original positions and nearby lines.")
    def workspace_search(terms: list[str], paths: list[str] | None = None, prefix: str = "",
                         match: str = "any", regex: bool = False, mode: str = "lines",
                         case_sensitive: bool = False, context_lines: Annotated[int, Field(ge=0, le=5)] = 2,
                         cursor: Annotated[int, Field(ge=0)] = 0,
                         limit: Annotated[int, Field(ge=1, le=50)] = 10) -> dict:
        return workspace_views.search(*scope(), terms, paths, prefix, match, regex, mode,
                                      case_sensitive, context_lines, cursor, limit)

    @mcp.tool(name="workspace_rows", description="Read, filter and project rows from a saved result, CSV or JSONL file.")
    def workspace_rows(path: str, version: str | int | None = None,
                       columns: list[str] | None = None, filters: list[workspace_views.Filter] | None = None,
                       sort: list[workspace_views.Sort] | None = None,
                       cursor: Annotated[int, Field(ge=0)] = 0,
                       limit: Annotated[int, Field(ge=1, le=100)] = 25,
                       row_offset: Annotated[int | None, Field(ge=0, description="Read a long row as JSON from this character position.")] = None) -> dict:
        return workspace_views.rows(*scope(), path, version, columns or [], filters or [], sort or [],
                                    cursor, limit, row_offset)

    @mcp.tool(
        name="write_file",
        description=(
            "Create or replace a whole text file in this conversation's workspace, such as "
            "report.md. Write every requested report, list, table or draft, and every answer "
            "with citations, as a file. To replace an existing file, send expected_version, "
            "the version that you read. Each citation handle such as [D1] or [W2] must come "
            "from a successful cite_documents or cite_pages call. A call with a problem "
            "changes nothing and returns the findings."
        ),
    )
    async def write_file(
        name: Annotated[str, Field(description="The file name, such as report.md or sources.txt.")],
        content: Annotated[str, Field(description="The whole text of the file. Markdown is shown formatted.")],
        expected_version: Annotated[Optional[int], Field(description="The current version of an existing file. Leave it out for a new file.")] = None,
    ) -> str:
        return await submit("write", name, content=content, expected_version=expected_version)

    @mcp.tool(
        name="patch_file",
        description=(
            "Replace one region of an existing workspace file. old_string is the current "
            "text, with enough context to be unique, and new_string the replacement. Use "
            "replace_all true to change every match. Read the file first when unsure. A call "
            "with a problem changes nothing and returns the error."
        ),
    )
    async def patch_file(
        name: Annotated[str, Field(description="The file name, such as report.md.")],
        old_string: Annotated[str, Field(description="The current text to replace.")],
        new_string: Annotated[str, Field(description="The text that replaces it.")],
        replace_all: Annotated[bool, Field(description="True to replace every match of old_string.")] = False,
    ) -> str:
        return await submit("patch", name, old_string=old_string, new_string=new_string,
                            replace_all=bool(replace_all))

    @mcp.tool(
        name="finish_with_report",
        description=(
            "Show a saved report as your answer and end this turn. Call it when the "
            "requested report or its revision is ready, or when the person asks to see an "
            "earlier report again. A write or a patch saves a file and does not show it. "
            "Give the name and the version that the last write, patch or read returned. "
            "Make it the last call of your reply. A call with a problem changes nothing and "
            "returns the error."
        ),
    )
    def finish_with_report(
        name: Annotated[str, Field(description="The file name of the report to show, such as report.md.")],
        version: Annotated[int, Field(description="The version of the report to show.")],
        message: Annotated[Optional[str], Field(description="One or two sentences for the chat that say what the report holds.")] = None,
        additional: Annotated[Optional[list[SelectedFile]], Field(description="Other report files to list with the answer, when the person asked for several files.")] = None,
    ) -> str:
        caller, _headers = _caller_and_headers()
        primary = _selected(caller.username, caller.session_id, name, version)
        others: list[dict] = []
        for item in additional or []:
            if isinstance(item, dict):
                item = SelectedFile(**item)
            if item.name == primary["name"] or any(o["name"] == item.name for o in others):
                _refuse({"success": False, "error": f"{item.name} is selected more than once."})
            others.append(_selected(caller.username, caller.session_id, item.name, item.version))
        log.info("workspace finish %s %s of %s with %d more", primary["name"], primary["version"],
                 caller.session_id, len(others))
        return json.dumps({"success": True, "finished": True, "report": primary,
                           "additional": others}, ensure_ascii=False)


__all__ = ["register", "submit"]
