"""The workspace tools: the text files that the agent writes in a conversation.

``read_file``   one file with a ``N|`` line gutter, or the list of files
``write_file``  create or replace a whole file
``patch_file``  replace one region of a file

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
from pydantic import Field

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

            _client = await Client.connect(os.getenv("TEMPORAL_ADDRESS", "temporal:7233"))
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


def register(mcp) -> None:
    """Add the three workspace tools to the server."""

    @mcp.tool(
        name="read_file",
        description=(
            "Read a file of this conversation's workspace. Each line starts with its number "
            "and |. The result gives the version, total_lines, and next_offset when the file "
            "continues. Leave out name to list the files and their current versions. It "
            "reads only the files that this conversation wrote. Read collection documents "
            "with read_documents."
        ),
    )
    def read_file(
        name: Annotated[Optional[str], Field(description="The file name, such as report.md. Leave it out to list the files.")] = None,
        version: Annotated[Optional[int], Field(description="An earlier version to read. Leave it out for the current version.")] = None,
        offset: Annotated[int, Field(description="The first line to read, from 1.")] = 1,
        limit: Annotated[int, Field(description="The most lines to read, at most 2000.")] = store.MAX_READ_LINES,
    ) -> str:
        caller, _headers = _caller_and_headers()
        if not name:
            files = store.list_files(caller.username, caller.session_id)
            return json.dumps({"files": [{k: f[k] for k in ("name", "version", "chars")} for f in files]},
                              ensure_ascii=False)
        problem = store.valid_name(name)
        if problem:
            _refuse({"success": False, "error": problem})
        found = store.read_version(caller.username, caller.session_id, name, version)
        if found is None:
            names = [f["name"] for f in store.list_files(caller.username, caller.session_id)]
            missing = f"{name} has no version {version}." if version else f"{name} does not exist."
            _refuse({"success": False, "error": missing + (
                f" The files are {', '.join(names)}." if names else " The workspace has no files.")})
        return json.dumps(store.render_read(found, offset, limit), ensure_ascii=False)

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


__all__ = ["register", "submit"]
