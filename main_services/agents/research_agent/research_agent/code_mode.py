"""Run JavaScript in a WebAssembly interpreter with scoped tool calls."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

FUNCTIONS = frozenset({
    "web_search", "read_page", "workspace_list", "workspace_search", "read_file",
    "search_collections", "search_passages", "read_documents", "doc_search_text", "pdf_search",
    "read_more", "table_overview", "table_page", "table_cell", "table_search_cells",
    "workspace_rows", "cite_pages", "cite_documents", "patch_file", "write_file", "browser_extract",
})
MAX_OPERATIONS = 32
TIMEOUT = 160
log = logging.getLogger(__name__)
RUNNER = Path(__file__).with_name("code_mode.cjs")


class SearchArgs(BaseModel):
    query: str = Field(default="", max_length=160)
    detail: bool = False
    cursor: int = Field(default=0, ge=0)
    limit: int | None = Field(default=None, ge=1, le=32)
    schema_offset: int | None = Field(default=None, ge=0)


class ExecuteArgs(BaseModel):
    language: str
    code: str = Field(max_length=32000)


def discover(snapshot, query, detail, allowed, cursor=0, limit=None, schema_offset=None):
    from research_agent.skill_tools import read_tool_result

    matches = snapshot.search(query, limit=len(snapshot.tools_by_name)) if query else [
        {"name": name, "summary": snapshot.summaries[name]} for name in snapshot.tools_by_name
    ]
    matches = [m for m in matches if m["name"] in FUNCTIONS and m["name"] in allowed]
    count = len(matches)
    end = min(count, cursor + (limit or count))
    matches = matches[cursor:end]
    if detail:
        matches = [read_tool_result(m["name"], snapshot) for m in matches]
    if schema_offset is not None and matches:
        from research_agent.result_views import DISPLAY_LIMIT, bounded_json_prefix, encode

        text = encode(matches[0])
        position = min(schema_offset, len(text))
        segment = bounded_json_prefix(text[position:position + 2000], DISPLAY_LIMIT - 500)
        stop = position + len(segment)
        return {"schema_segment": segment, "schema_offset": position,
                "next_schema_offset": stop if stop < len(text) else None,
                "next_cursor": cursor + 1 if cursor + 1 < count else None}
    return {"matches": matches, **({"next_cursor": end} if end < count else {})}


def tools(snapshot_of):
    async def search(query: str = "", detail: bool = False, cursor: int = 0,
                     limit: int | None = None, schema_offset: int | None = None) -> str:
        snapshot = snapshot_of()
        result = discover(snapshot, query, detail, snapshot.callable_names(), cursor, limit, schema_offset)
        return json.dumps(result, ensure_ascii=False)

    async def execute(language: str, code: str) -> str:
        raise RuntimeError("The broker must run this operation.")

    return [
        StructuredTool.from_function(coroutine=search, name="search", args_schema=SearchArgs,
                                     description="Find functions for a JavaScript program. Set detail for call schemas. A result without detail gives names and summaries only. Read each function with detail true or with read_tool before a program calls it."),
        StructuredTool.from_function(coroutine=execute, name="execute", args_schema=ExecuteArgs,
                                     description="Run JavaScript with named research functions. Use read_page for web pages. Ambient fetch is unavailable. Return a summary and receipts."),
    ]


async def run(language, code, names, invoke):
    receipts = []
    if language.lower() not in {"javascript", "js"}:
        return {"success": False, "error": "Use JavaScript.", "receipts": receipts}
    process = None
    try:
        async with asyncio.timeout(TIMEOUT):
            process = await asyncio.create_subprocess_exec(
                "/usr/bin/node", "--max-old-space-size=128", str(RUNNER),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, env={}, cwd="/",
                limit=1024 * 1024,
            )
            process.stdin.write(json.dumps({
                "code": code, "names": sorted(names), "timeout": TIMEOUT * 1000,
            }).encode() + b"\n")
            await process.stdin.drain()
            while line := await process.stdout.readline():
                message = json.loads(line)
                if "call" not in message:
                    return {"success": "error" not in message, **message, "receipts": receipts}
                name, args = message["call"], message.get("args")
                if len(receipts) >= MAX_OPERATIONS:
                    raise ValueError("The program reached its operation limit.")
                if name not in names or not isinstance(args, dict):
                    raise ValueError("The operation or its arguments are invalid.")
                try:
                    result, receipt = await invoke(name, args, len(receipts))
                except Exception:
                    log.exception("code operation %s did not complete", name)
                    result = {"error": "The operation could not complete."}
                    receipt = {"status": "error", **result}
                receipts.append({"tool": name, **receipt})
                encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
                if len(encoded) > 16 * 1024 * 1024:
                    encoded = b'{"broker_error":"The result exceeds the program input limit. Read its saved extent."}'
                process.stdin.write(encoded + b"\n")
                await process.stdin.drain()
            raise ValueError("The JavaScript interpreter stopped before returning a result.")
    except (TimeoutError, ValueError, OSError) as exc:
        return {"success": False, "error": str(exc) or "The program reached its time limit.",
                "receipts": receipts}
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
