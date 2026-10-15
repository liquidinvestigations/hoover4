"""Board command storage: the inputs of every board state change and their receipts.

The tables are in migration `00047_board_commands.sql`. A producer writes an input. The
per-board workflow `BoardCommands` is the only writer of receipts (`tasks/P_board/commands.py`).

* **An input is immutable.** Its key is `(board_id, request_id, payload_digest)`. A retry of
  one request writes the same row again. Two bodies under one request id are two rows, and
  the receipt names the digest that the writer accepted.
* **A receipt advances by phase.** `version` is 1 for `prepared` and 2 for `committed` or
  `rejected`, so a late retry of the prepared write cannot replace a decision.
* **Every read uses FINAL.**
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

PREPARED = "prepared"
COMMITTED = "committed"
REJECTED = "rejected"
#: The `version` of a receipt in each state.
PHASE = {PREPARED: 1, COMMITTED: 2, REJECTED: 2}
#: The state of an input without a receipt.
PENDING = "pending"
#: The state of a request id without an input.
UNKNOWN = "unknown"

INPUT_COLUMNS = ["board_id", "request_id", "payload_digest", "actor", "kind", "body_json", "submitted_at"]
RECEIPT_COLUMNS = ["board_id", "request_id", "payload_digest", "kind", "state", "seq_start", "seq_end",
                   "prepared_json", "result_json", "error", "version", "created_at", "updated_at"]


@dataclass
class CommandInput:
    board_id: str
    request_id: str
    payload_digest: str
    actor: str
    kind: str
    body: dict = field(default_factory=dict)
    submitted_at: datetime | None = None


@dataclass
class Receipt:
    board_id: str
    request_id: str
    payload_digest: str
    kind: str
    state: str
    seq_start: int = 0
    seq_end: int = 0
    prepared: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)
    error: str = ""
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


def digest(body: dict) -> str:
    """The sha256 of the canonical JSON of a body: sorted keys and no spaces."""
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _client():
    from database.clickhouse import get_global_client

    return get_global_client()


def _insert(table: str, rows: list[list[Any]], columns: list[str]) -> None:
    from database.clickhouse import insert_durable

    if rows:
        with _client() as client:
            insert_durable(client, table, rows, column_names=columns)


def submit(board_id: str, request_id: str, kind: str, actor: str, body: dict) -> str:
    """Write one command input and return its digest. The same request with the same body
    writes the same row again."""
    from database.boards import now

    value = digest(body)
    _insert("board_command_inputs",
            [[board_id, request_id, value, actor, kind,
              json.dumps(body, sort_keys=True, ensure_ascii=False), now()]],
            INPUT_COLUMNS)
    return value


def _json(text: str) -> dict:
    try:
        value = json.loads(text or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def read_inputs(board_id: str) -> list[CommandInput]:
    """Every input of a board, oldest first."""
    with _client() as client:
        result = client.query(
            f"SELECT {', '.join(INPUT_COLUMNS)} FROM board_command_inputs FINAL "
            "WHERE board_id = {b:String} ORDER BY submitted_at, request_id, payload_digest",
            parameters={"b": board_id},
        )
    return [CommandInput(row[0], row[1], row[2], row[3], row[4], _json(row[5]), row[6])
            for row in result.result_rows]


def _receipt(row) -> Receipt:
    values = dict(zip(RECEIPT_COLUMNS, row))
    return Receipt(values["board_id"], values["request_id"], values["payload_digest"], values["kind"],
                   values["state"], int(values["seq_start"]), int(values["seq_end"]),
                   _json(values["prepared_json"]), _json(values["result_json"]), values["error"],
                   int(values["version"]), values["created_at"], values["updated_at"])


def read_receipts(board_id: str) -> dict[str, Receipt]:
    """Every receipt of a board, by request id."""
    with _client() as client:
        result = client.query(
            f"SELECT {', '.join(RECEIPT_COLUMNS)} FROM board_command_receipts FINAL "
            "WHERE board_id = {b:String}",
            parameters={"b": board_id},
        )
    return {row[1]: _receipt(row) for row in result.result_rows}


def write_receipt(receipt: Receipt) -> None:
    from database.boards import now

    stamp = now()
    _insert("board_command_receipts",
            [[receipt.board_id, receipt.request_id, receipt.payload_digest, receipt.kind, receipt.state,
              receipt.seq_start, receipt.seq_end,
              json.dumps(receipt.prepared, sort_keys=True, ensure_ascii=False, default=str),
              json.dumps(receipt.result, sort_keys=True, ensure_ascii=False, default=str),
              receipt.error[:2000], PHASE[receipt.state], receipt.created_at or stamp, stamp]],
            RECEIPT_COLUMNS)


def pending_commands(board_ids: list[str]) -> list[tuple[str, str, str]]:
    """`(board_id, request_id, kind)` of every input without a decided receipt: the inputs
    that wait and the commands that are prepared but not committed."""
    if not board_ids:
        return []
    with _client() as client:
        result = client.query(
            "SELECT i.board_id, i.request_id, i.kind FROM "
            "(SELECT board_id, request_id, any(kind) AS kind FROM board_command_inputs FINAL "
            " WHERE board_id IN {b:Array(String)} GROUP BY board_id, request_id) AS i "
            "LEFT ANTI JOIN "
            "(SELECT board_id, request_id FROM board_command_receipts FINAL "
            " WHERE board_id IN {b:Array(String)} AND state IN ('committed', 'rejected')) AS r "
            "USING (board_id, request_id)",
            parameters={"b": list(board_ids)},
        )
    return [(row[0], row[1], row[2]) for row in result.result_rows]


def states(requests: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """The state of each `(board_id, request_id)`: a receipt state, `pending` or `unknown`."""
    if not requests:
        return {}
    boards = sorted({b for b, _ in requests})
    ids = sorted({r for _, r in requests})
    with _client() as client:
        receipts = client.query(
            "SELECT board_id, request_id, state FROM board_command_receipts FINAL "
            "WHERE board_id IN {b:Array(String)} AND request_id IN {r:Array(String)}",
            parameters={"b": boards, "r": ids},
        ).result_rows
        inputs = client.query(
            "SELECT DISTINCT board_id, request_id FROM board_command_inputs FINAL "
            "WHERE board_id IN {b:Array(String)} AND request_id IN {r:Array(String)}",
            parameters={"b": boards, "r": ids},
        ).result_rows
    decided = {(b, r): state for b, r, state in receipts}
    submitted = {(b, r) for b, r in inputs}
    return {key: decided.get(key) or (PENDING if key in submitted else UNKNOWN) for key in requests}


__all__ = [
    "COMMITTED", "CommandInput", "PENDING", "PHASE", "PREPARED", "REJECTED", "Receipt", "UNKNOWN",
    "digest", "pending_commands", "read_inputs", "read_receipts", "states", "submit", "write_receipt",
]
