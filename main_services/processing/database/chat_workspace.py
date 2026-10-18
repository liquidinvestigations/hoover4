"""Workspace file storage: the reports and other text files that an agent writes in a chat.

The tables are in migration `00048_chat_workspace.sql`. `WorkspaceWriter`
(`tasks/P_workspace/workflows.py`) is the only writer of versions and receipts. The session
tool server reads files through this module, and forwards each write and patch to the
writer. The website reads the same rows for the workspace view and the pinned report of an
answer.

* **A version is immutable.** The key is `(username, session_id, name, version)`. A retried
  commit writes the same row again, and the replacing engine keeps one copy.
* **A receipt is the result of one operation.** The operation id is the idempotency key that
  the worker gives the tool call, so a repeated call returns the stored result.
* **Every read uses FINAL** and skips the tombstones of a deleted session.

The limits and the read format follow the Hermes file tools: at most `MAX_FILE_CHARS`
characters in a file, and a read of at most `MAX_READ_LINES` lines and `MAX_READ_CHARS`
characters that stops at a line end, with a `N|` line gutter.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

MAX_FILE_CHARS = 200_000
MAX_READ_CHARS = 100_000
MAX_READ_LINES = 2_000
MAX_NAME_CHARS = 120
#: A file name: letters, digits, dot, dash and underscore, starting with a letter or a digit.
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

FILE_COLUMNS = ["username", "session_id", "name", "version", "parent_version", "run_id",
                "operation_id", "operation", "content", "citations_json", "patch_json",
                "created_at", "is_deleted"]
RECEIPT_COLUMNS = ["username", "session_id", "operation_id", "name", "version", "ok",
                   "result_json", "created_at"]


@dataclass
class FileVersion:
    username: str
    session_id: str
    name: str
    version: int
    parent_version: int = 0
    run_id: str = ""
    operation_id: str = ""
    operation: str = "write"
    content: str = ""
    citations: list = field(default_factory=list)
    patch: dict = field(default_factory=dict)
    created_at: Optional[datetime] = None


@dataclass
class Receipt:
    operation_id: str
    name: str
    version: int
    ok: bool
    result: dict


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def valid_name(name: str) -> str:
    """Why a file name is refused, or an empty string for a valid name."""
    if not isinstance(name, str) or not name:
        return "Give the file a name, such as report.md."
    if len(name) > MAX_NAME_CHARS:
        return f"A file name has at most {MAX_NAME_CHARS} characters."
    if not NAME_PATTERN.fullmatch(name) or ".." in name:
        return ("A file name holds letters, digits, dots, dashes and underscores, starts with a "
                "letter or a digit, and holds no folder, such as report.md.")
    return ""


def looks_like_read_output(content: str) -> bool:
    """True when most lines of `content` carry the `N|` gutter of a read, with consecutive
    numbers. Such content is a copy of a read result, not the text of the file. The rule
    follows the Hermes write guard."""
    lines = [line for line in content.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    numbers = []
    for line in lines:
        prefix, sep, _rest = line.lstrip().partition("|")
        if sep and prefix.isdigit():
            numbers.append(int(prefix))
    if len(numbers) < 2 or len(numbers) / len(lines) < 0.6:
        return False
    return sum(1 for a, b in zip(numbers, numbers[1:]) if b == a + 1) >= len(numbers) - 1


def render_read(version: FileVersion, offset: int = 1, limit: int = MAX_READ_LINES) -> dict:
    """One read of a file version: lines from `offset` (from 1) with the `N|` gutter, at most
    `limit` lines and `MAX_READ_CHARS` characters, cut at a line end."""
    lines = version.content.splitlines()
    total = len(lines)
    start = max(1, int(offset or 1))
    limit = max(1, min(int(limit or MAX_READ_LINES), MAX_READ_LINES))
    shown, used = [], 0
    for number in range(start, min(total, start + limit - 1) + 1):
        line = f"{number}|{lines[number - 1]}"
        if shown and used + len(line) + 1 > MAX_READ_CHARS:
            break
        shown.append(line)
        used += len(line) + 1
    out: dict[str, Any] = {"name": version.name, "version": version.version,
                           "total_lines": total, "content": "\n".join(shown)}
    end = start + len(shown)
    if end <= total:
        out["next_offset"] = end
    return out


def _client():
    from database.clickhouse import get_global_client

    return get_global_client()


def _version(values: dict) -> FileVersion:
    def parsed(text: str, empty):
        try:
            return json.loads(text) if text else empty
        except ValueError:
            return empty
    return FileVersion(values["username"], values["session_id"], values["name"],
                       int(values["version"]), int(values["parent_version"]), values["run_id"],
                       values["operation_id"], values["operation"], values["content"],
                       parsed(values["citations_json"], []), parsed(values["patch_json"], {}),
                       values["created_at"])


def read_version(username: str, session_id: str, name: str,
                 version: Optional[int] = None) -> Optional[FileVersion]:
    """One version of a file, the highest when `version` is None, or None."""
    where = "" if version is None else " AND version = {v:UInt32}"
    with _client() as client:
        result = client.query(
            f"SELECT {', '.join(FILE_COLUMNS)} FROM chat_workspace_files FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} AND name = {n:String} "
            f"AND is_deleted = 0{where} ORDER BY version DESC LIMIT 1",
            parameters={"u": username, "s": session_id, "n": name, "v": int(version or 0)},
        )
    rows = [dict(zip(result.column_names, row)) for row in result.result_rows]
    return _version(rows[0]) if rows else None


def list_files(username: str, session_id: str) -> list[dict]:
    """The files of a session: name, highest version, character count and time of that
    version, by name."""
    with _client() as client:
        result = client.query(
            # `top`, not `version`: an alias with the column name would replace the column
            # inside `argMax`.
            "SELECT name, max(version) AS top, argMax(lengthUTF8(content), version) AS chars, "
            "argMax(created_at, version) AS updated FROM chat_workspace_files FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} AND is_deleted = 0 "
            "GROUP BY name ORDER BY name",
            parameters={"u": username, "s": session_id},
        )
    return [{"name": r[0], "version": int(r[1]), "chars": int(r[2]), "updated": str(r[3])}
            for r in result.result_rows]


def read_receipt(username: str, session_id: str, operation_id: str) -> Optional[Receipt]:
    with _client() as client:
        result = client.query(
            f"SELECT {', '.join(RECEIPT_COLUMNS)} FROM chat_workspace_receipts FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} AND operation_id = {o:String} "
            "LIMIT 1",
            parameters={"u": username, "s": session_id, "o": operation_id},
        )
    if not result.result_rows:
        return None
    values = dict(zip(result.column_names, result.result_rows[0]))
    try:
        body = json.loads(values["result_json"] or "{}")
    except ValueError:
        body = {}
    return Receipt(values["operation_id"], values["name"], int(values["version"]),
                   bool(values["ok"]), body)


def write_version(version: FileVersion) -> None:
    from database.clickhouse import insert_durable

    with _client() as client:
        insert_durable(client, "chat_workspace_files", [[
            version.username, version.session_id, version.name, int(version.version),
            int(version.parent_version), version.run_id, version.operation_id,
            version.operation, version.content,
            json.dumps(version.citations, sort_keys=True, ensure_ascii=False),
            json.dumps(version.patch, sort_keys=True, ensure_ascii=False) if version.patch else "",
            version.created_at or now(), 0]], column_names=FILE_COLUMNS)


def write_receipt(username: str, session_id: str, receipt: Receipt) -> None:
    from database.clickhouse import insert_durable

    with _client() as client:
        insert_durable(client, "chat_workspace_receipts", [[
            username, session_id, receipt.operation_id, receipt.name, int(receipt.version),
            1 if receipt.ok else 0, json.dumps(receipt.result, sort_keys=True, ensure_ascii=False),
            now()]], column_names=RECEIPT_COLUMNS)


def session_deleted(username: str, session_id: str) -> bool:
    """True when the chat session is deleted. A missing session row is not deleted, because
    a board explore writes its session row before its first turn."""
    with _client() as client:
        rows = client.query(
            "SELECT is_deleted FROM chat_sessions FINAL WHERE username = {u:String} "
            "AND session_id = {s:String} LIMIT 1",
            parameters={"u": username, "s": session_id},
        ).result_rows
    return bool(rows) and int(rows[0][0]) == 1
