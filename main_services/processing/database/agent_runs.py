"""Agent run storage: every read and write of `agent_runs`, `agent_run_messages` and
`agent_turn_stops`.

One `agent_runs` row is the state of one `AgentRun` workflow. The workflow input holds ids
only, and the activities read the row and the thread here. A retry therefore reads the same
state, and no answer, tool result or briefing crosses a Temporal payload.

Three rules hold for every function in this module:

* **Every write uses the unmarked insert or `insert_durable`**, never `insert_idempotent`,
  so a read that follows the write sees it.
* **Every read uses `FINAL` and the full owner prefix** `(username, session_id)`. Without
  `FINAL`, a read before a merge sees every partial version of a message.
* **A run row write reads the row and writes `state_version + 1`.** A creation write always
  uses version 1, so a late creation write never replaces a row that has started. No write
  changes a terminal row.

`writes_transcript` and `is_chat_lead` are the two named properties that every other module
uses in place of a kind and depth test.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timezone
from typing import Any, Iterator

log = logging.getLogger(__name__)

#: The namespace of every `uuid5` run id: child runs, batches and continuations. One constant,
#: so two writers of one child or continuation row compute the same id.
RUN_ID_NAMESPACE = uuid.UUID("5d0c3b4e-8f1a-4b8e-9a53-2f6e0a7c1d42")

#: The states a run row can hold. The last three are terminal.
RUNNING = "running"
WAITING_FOR_CHILDREN = "waiting_for_children"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
TERMINAL_STATES = (COMPLETED, FAILED, CANCELLED)

#: The queue of the agent activity for each top-level kind. The workflow itself runs on
#: `chat-queue`. These names are mirrored in `tasks/P_agent/workflows.py`.
LEAD_QUEUES = {
    "chat": "chat-model-queue",
    "planner": "research-queue",
    "organizer": "research-queue",
}


def batch_id_for(run_id: str) -> str:
    """The delegation batch id of a run. A run delegates at most once, so it is unique."""
    return str(uuid.uuid5(RUN_ID_NAMESPACE, f"{run_id}:batch"))


def child_run_id(batch_id: str, index: int) -> str:
    """The run id of briefing `index` in a batch."""
    return str(uuid.uuid5(uuid.UUID(batch_id), str(index)))


def continuation_run_id(batch_id: str) -> str:
    """The run id of the continuation that a batch starts."""
    return str(uuid.uuid5(uuid.UUID(batch_id), "continuation"))


def _now() -> datetime:
    """UTC with the tzinfo dropped: ClickHouse DateTime64 columns are naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class RunRow:
    """One `agent_runs` row, with the column names of the migration."""

    run_id: str
    username: str
    session_id: str
    turn_seq: int = 0
    thread_id: str = ""
    parent_run_id: str | None = None
    batch_id: str | None = None
    continues_run_id: str | None = None
    depth: int = 0
    kind: str = "chat"
    plan_run_id: str | None = None
    plan_node_id: str | None = None
    purpose: str = ""
    queue: str = ""
    workflow_id: str = ""
    state: str = RUNNING
    briefing: str = ""
    tool_call_id: str = ""
    delegated_batch_id: str | None = None
    delegate_seq: int = 0
    refused_json: str = "[]"
    subagent_share: int = 0
    result: str = ""
    error: str = ""
    start_seq: int = 0
    next_seq: int = 0
    tool_turns_used: int = 0
    extra_tool_turns: int = 0
    nags_this_turn: int = 0
    nags_without_progress: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    started_at: datetime | None = None
    state_version: int = 1
    updated_at: datetime | None = None


RUN_COLUMNS = [f.name for f in fields(RunRow)]
_UUID_COLUMNS = {"run_id", "thread_id"}
_NULLABLE_UUID_COLUMNS = {
    "parent_run_id", "batch_id", "continues_run_id", "plan_run_id", "plan_node_id",
    "delegated_batch_id",
}


def writes_transcript(row: RunRow) -> bool:
    """The run owns its turn's transcript: its tool rows, answer and ending row."""
    return row.depth == 0


def is_chat_lead(row: RunRow) -> bool:
    """The run nags and titles the session."""
    return writes_transcript(row) and row.kind == "chat"


def is_terminal(row: RunRow) -> bool:
    return row.state in TERMINAL_STATES


def _to_db(row: RunRow) -> list[Any]:
    values = asdict(row)
    out = []
    for name in RUN_COLUMNS:
        value = values[name]
        if name in _UUID_COLUMNS:
            value = uuid.UUID(str(value))
        elif name in _NULLABLE_UUID_COLUMNS:
            value = uuid.UUID(str(value)) if value else None
        elif name in ("started_at", "updated_at") and value is None:
            value = _now()
        out.append(value)
    return out


def _from_db(values) -> RunRow:
    data = dict(zip(RUN_COLUMNS, values))
    for name in _UUID_COLUMNS | _NULLABLE_UUID_COLUMNS:
        if data[name] is not None:
            data[name] = str(data[name])
    for name in ("turn_seq", "depth", "delegate_seq", "subagent_share", "start_seq",
                 "next_seq", "tool_turns_used", "extra_tool_turns", "nags_this_turn",
                 "nags_without_progress", "prompt_tokens", "completion_tokens",
                 "state_version"):
        data[name] = int(data[name] or 0)
    return RunRow(**data)


def _client():
    from database.clickhouse import get_global_client

    return get_global_client()


def _insert(client, table: str, rows: list[list[Any]], columns: list[str]) -> None:
    from database.clickhouse import insert_durable

    insert_durable(client, table, rows, column_names=columns)


# ------------------------------------------------------------------------- agent_runs


def read_run(username: str, session_id: str, run_id: str) -> RunRow | None:
    """One run row, or None when it does not exist."""
    with _client() as client:
        rows = client.query(
            f"SELECT {', '.join(RUN_COLUMNS)} FROM agent_runs FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} "
            "AND run_id = {r:UUID}",
            parameters={"u": username, "s": session_id, "r": run_id},
        ).result_rows
    return _from_db(rows[0]) if rows else None


def read_turn_runs(username: str, session_id: str, turn_seq: int) -> list[RunRow]:
    """Every run row of one user turn."""
    with _client() as client:
        rows = client.query(
            f"SELECT {', '.join(RUN_COLUMNS)} FROM agent_runs FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} "
            "AND turn_seq = {t:UInt32} ORDER BY started_at, run_id",
            parameters={"u": username, "s": session_id, "t": turn_seq},
        ).result_rows
    return [_from_db(r) for r in rows]


def create_run(row: RunRow) -> None:
    """Write a new run row at `state_version` 1.

    A creation write always uses version 1. A later write reads the row and adds one, so a
    creation write that arrives late never replaces a row that has started.
    """
    row = replace(row, state_version=1, started_at=row.started_at or _now(),
                  updated_at=_now())
    with _client() as client:
        _insert(client, "agent_runs", [_to_db(row)], RUN_COLUMNS)


def write_run(row: RunRow, **changes: Any) -> RunRow | None:
    """Write `changes` into the current row, at the read `state_version` plus one.

    Reads the row first. Returns None and writes nothing when the row does not exist or is
    terminal, because no writer changes a terminal row. `write_ending` uses
    `write_run_terminal` for the terminal write itself.
    """
    current = read_run(row.username, row.session_id, row.run_id)
    if current is None or is_terminal(current):
        return None
    return _write_version(current, changes)


def write_run_terminal(row: RunRow, state: str, **changes: Any) -> RunRow | None:
    """Write a terminal state. Refuses a row that is already terminal."""
    if state not in TERMINAL_STATES:
        raise ValueError(f"{state!r} is not a terminal state")
    return write_run(row, state=state, **changes)


def _write_version(current: RunRow, changes: dict[str, Any]) -> RunRow:
    unknown = set(changes) - set(RUN_COLUMNS)
    if unknown:
        raise ValueError(f"unknown run columns: {sorted(unknown)}")
    new = replace(current, **changes, state_version=current.state_version + 1,
                  updated_at=_now())
    with _client() as client:
        _insert(client, "agent_runs", [_to_db(new)], RUN_COLUMNS)
    return new


class RunRowWriter:
    """The one writer of a run row inside `run_agent`.

    It holds one lock. Under the lock it reads the row, refuses to change a terminal row,
    and writes `state_version + 1`. The keepalive thread rewrites `updated_at` every
    `interval` seconds through the same lock, so a keepalive write never replaces a state
    write with an older version. `stop_keepalive` ends the thread before the final writes.
    """

    def __init__(self, row: RunRow, interval: float = 30.0):
        self._key = (row.username, row.session_id, row.run_id)
        self._lock = threading.Lock()
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def read(self) -> RunRow | None:
        """The current row, read under the lock, so no write of this writer is half done."""
        with self._lock:
            return read_run(*self._key)

    def write(self, **changes: Any) -> RunRow | None:
        with self._lock:
            current = read_run(*self._key)
            if current is None or is_terminal(current):
                return None
            return _write_version(current, changes)

    def _keepalive(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.write()
            except Exception:  # noqa: BLE001 - a keepalive must never end the run
                log.warning("[agent_runs] keepalive write failed for %s", self._key[2],
                            exc_info=True)

    def start_keepalive(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._keepalive, daemon=True, name=f"run-keepalive-{self._key[2][:8]}"
            )
            self._thread.start()

    def stop_keepalive(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None


# ------------------------------------------------------------------ agent_run_messages

MESSAGE_COLUMNS = [
    "username", "session_id", "thread_id", "idx", "run_id", "role", "content", "reasoning",
    "tool_calls_json", "tool_call_id", "tool_name", "usage_json", "is_final", "updated_at",
]


@dataclass
class RunMessageRow:
    """One `agent_run_messages` row."""

    idx: int
    role: str
    content: str = ""
    reasoning: str = ""
    tool_calls_json: str = "[]"
    tool_call_id: str = ""
    tool_name: str = ""
    usage_json: str = ""
    is_final: int = 1
    run_id: str = ""

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        try:
            calls = json.loads(self.tool_calls_json or "[]")
        except ValueError:
            return []
        return calls if isinstance(calls, list) else []

    @property
    def usage(self) -> dict[str, Any]:
        try:
            value = json.loads(self.usage_json or "{}")
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}


def write_message(username: str, session_id: str, thread_id: str, run_id: str,
                  message: RunMessageRow) -> None:
    """Write one message at `(thread_id, idx)`. A later write of the same key replaces it."""
    with _client() as client:
        _insert(client, "agent_run_messages", [[
            username, session_id, uuid.UUID(thread_id), int(message.idx),
            uuid.UUID(run_id), message.role, message.content, message.reasoning,
            message.tool_calls_json, message.tool_call_id, message.tool_name,
            message.usage_json, int(message.is_final), _now(),
        ]], MESSAGE_COLUMNS)


def read_messages(username: str, session_id: str, thread_id: str) -> list[RunMessageRow]:
    """The thread's messages in `idx` order, partials included."""
    with _client() as client:
        rows = client.query(
            "SELECT idx, role, content, reasoning, tool_calls_json, tool_call_id, "
            "tool_name, usage_json, is_final, run_id FROM agent_run_messages FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} "
            "AND thread_id = {t:UUID} ORDER BY idx",
            parameters={"u": username, "s": session_id, "t": thread_id},
        ).result_rows
    return [
        RunMessageRow(int(i), role, content, reasoning, calls, call_id, name, usage,
                      int(final), str(run))
        for i, role, content, reasoning, calls, call_id, name, usage, final, run in rows
    ]


# -------------------------------------------------------------------- agent_turn_stops


def turn_is_stopped(username: str, session_id: str, turn_seq: int) -> bool:
    """Whether the website wrote a stop row for this turn."""
    with _client() as client:
        rows = client.query(
            "SELECT count() FROM agent_turn_stops FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} "
            "AND turn_seq = {t:UInt32}",
            parameters={"u": username, "s": session_id, "t": turn_seq},
        ).result_rows
    return bool(rows and int(rows[0][0]))


def write_turn_stop(username: str, session_id: str, turn_seq: int) -> None:
    """Write a stop row. The website is the writer in production. Tests use this."""
    with _client() as client:
        _insert(client, "agent_turn_stops", [[username, session_id, int(turn_seq), _now()]],
                ["username", "session_id", "turn_seq", "created_at"])


def iter_thread_tool_seqs(messages: list[RunMessageRow]) -> Iterator[int]:
    """The transcript seqs that the tool messages of a thread recorded."""
    for message in messages:
        if message.role == "tool":
            seq = message.usage.get("chat_seq")
            if isinstance(seq, int):
                yield seq


__all__ = [
    "CANCELLED", "COMPLETED", "FAILED", "LEAD_QUEUES", "RUNNING", "RUN_COLUMNS",
    "RUN_ID_NAMESPACE", "RunMessageRow", "RunRow", "RunRowWriter", "TERMINAL_STATES",
    "WAITING_FOR_CHILDREN", "batch_id_for", "child_run_id", "continuation_run_id",
    "create_run", "is_chat_lead", "is_terminal", "iter_thread_tool_seqs", "read_messages",
    "read_run", "read_turn_runs", "turn_is_stopped", "write_message", "write_run",
    "write_run_terminal", "write_turn_stop", "writes_transcript",
]
