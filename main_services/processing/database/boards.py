"""Board storage: every read and write of the investigation board tables.

The tables are in migration `00043_investigation_boards.sql`. Each table has one writer
(see the migration header), so this module has no read-modify-write of a shared row.

Three rules hold for every function here:

* **Every write uses `insert_durable`**, so a read that follows the write sees it.
* **Every read uses `FINAL`.** Without it a read sees superseded state rows and the
  replaced copy of a retried event.
* **A dropped board takes no new row.** `board_is_live` is the check that a writer of an
  event, a fact or a state row calls first.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def now() -> datetime:
    """UTC with the tzinfo dropped: ClickHouse DateTime64 columns are naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _client():
    from database.clickhouse import get_global_client

    return get_global_client()


def _insert(table: str, rows: list[list[Any]], columns: list[str]) -> None:
    from database.clickhouse import insert_durable

    if not rows:
        return
    with _client() as client:
        insert_durable(client, table, rows, column_names=columns)


@dataclass
class BoardRow:
    board_id: str
    owner: str
    title: str
    goal: str
    context: str = ""
    collections: list[str] = field(default_factory=list)
    llm_model: str = ""
    max_explores: int = 12
    max_parallel: int = 1
    explore_step_budget: int = 40
    internet_tools: int = 1
    created_at: datetime | None = None
    is_deleted: int = 0


@dataclass
class EventRow:
    board_id: str
    event_id: str
    event_type: str
    actor: str
    subject: str = ""
    payload: dict = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass
class FactRow:
    board_id: str
    fact_id: str
    kind: str
    text: str
    intent_id: str = ""
    session_id: str = ""
    answer_seq: int = 0
    open_questions: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    created_by: str = "explore"
    created_at: datetime | None = None


@dataclass
class CitationRow:
    board_id: str
    fact_id: str
    label: str
    collection_dataset: str = ""
    collectionname: str = ""
    file_hash: str = ""
    path: str = ""
    page_id: int = 0
    quote: str = ""
    quote_verified: int = 0


BOARD_COLUMNS = ["board_id", "owner", "title", "goal", "context", "collections", "llm_model",
                 "max_explores", "max_parallel", "explore_step_budget", "internet_tools",
                 "created_at", "is_deleted"]
FACT_COLUMNS = ["board_id", "fact_id", "kind", "text", "intent_id", "session_id", "answer_seq",
                "open_questions", "problems", "created_by", "created_at"]
CITATION_COLUMNS = ["board_id", "fact_id", "label", "collection_dataset", "collectionname",
                    "file_hash", "path", "page_id", "quote", "quote_verified"]
INTENT_COLUMNS = ["board_id", "intent_id", "from_facts", "objective", "brief", "state",
                  "attempts", "session_id", "fact_id", "question", "last_error", "created_at",
                  "version", "updated_at"]
STATE_COLUMNS = ["board_id", "status", "explores_used", "reasons_done", "stall_count",
                 "invalid_reasons", "checkpoint_json", "summary_json", "version", "updated_at"]


# ------------------------------------------------------------------------------ boards


def read_live_boards() -> list[BoardRow]:
    """Every board that is not dropped."""
    with _client() as client:
        result = client.query(
            f"SELECT {', '.join(BOARD_COLUMNS)} FROM boards FINAL WHERE is_deleted = 0 "
            "ORDER BY created_at"
        )
    return [BoardRow(**dict(zip(BOARD_COLUMNS, row))) for row in result.result_rows]


def read_board(board_id: str) -> BoardRow | None:
    """One board, tombstoned or not. None when it never existed."""
    with _client() as client:
        result = client.query(
            f"SELECT {', '.join(BOARD_COLUMNS)} FROM boards FINAL WHERE board_id = {{b:String}}",
            parameters={"b": board_id},
        )
    if not result.result_rows:
        return None
    return BoardRow(**dict(zip(BOARD_COLUMNS, result.result_rows[0])))


def board_is_live(board_id: str) -> bool:
    """Whether a writer may still add rows for this board."""
    board = read_board(board_id)
    return board is not None and not board.is_deleted


# ------------------------------------------------------------------------------ events


def read_events(board_id: str) -> list[EventRow]:
    """Every event of a board, oldest first. The event id breaks a tie of write time."""
    with _client() as client:
        result = client.query(
            "SELECT board_id, event_id, event_type, actor, subject, payload_json, created_at "
            "FROM board_events FINAL WHERE board_id = {b:String} ORDER BY created_at, event_id",
            parameters={"b": board_id},
        )
    events = []
    for board, event_id, event_type, actor, subject, payload, created_at in result.result_rows:
        try:
            data = json.loads(payload or "{}")
        except ValueError:
            data = {"raw": payload}
        events.append(EventRow(board, event_id, event_type, actor, subject, data, created_at))
    return events


def write_events(events: list[EventRow]) -> None:
    """Write events. The same event id replaces the earlier row, so a retry is harmless."""
    rows = [[e.board_id, e.event_id, e.event_type, e.actor, e.subject,
             json.dumps(e.payload, ensure_ascii=False), e.created_at or now()] for e in events]
    _insert("board_events", rows, ["board_id", "event_id", "event_type", "actor", "subject",
                                   "payload_json", "created_at"])


def write_event(event: EventRow) -> None:
    write_events([event])


# ------------------------------------------------------------------------------- facts


def read_facts(board_id: str) -> list[FactRow]:
    with _client() as client:
        result = client.query(
            f"SELECT {', '.join(FACT_COLUMNS)} FROM board_facts FINAL "
            "WHERE board_id = {b:String} ORDER BY created_at, fact_id",
            parameters={"b": board_id},
        )
    return [FactRow(**dict(zip(FACT_COLUMNS, row))) for row in result.result_rows]


def fact_exists(board_id: str, fact_id: str) -> bool:
    with _client() as client:
        result = client.query(
            "SELECT count() FROM board_facts FINAL WHERE board_id = {b:String} AND fact_id = {f:String}",
            parameters={"b": board_id, "f": fact_id},
        )
    return bool(result.result_rows and result.result_rows[0][0])


def write_fact(fact: FactRow, citations: list[CitationRow]) -> bool:
    """Write a fact and its citations once. Returns False when the fact already exists, and
    then writes nothing: a fact is immutable after its first write."""
    if fact_exists(fact.board_id, fact.fact_id):
        return False
    created = fact.created_at or now()
    _insert("board_fact_citations",
            [[c.board_id, c.fact_id, c.label, c.collection_dataset, c.collectionname,
              c.file_hash, c.path, c.page_id, c.quote, c.quote_verified] + [created]
             for c in citations],
            CITATION_COLUMNS + ["created_at"])
    _insert("board_facts",
            [[fact.board_id, fact.fact_id, fact.kind, fact.text, fact.intent_id,
              fact.session_id, fact.answer_seq, fact.open_questions, fact.problems,
              fact.created_by, created]],
            FACT_COLUMNS)
    return True


def read_citations(board_id: str) -> list[CitationRow]:
    with _client() as client:
        result = client.query(
            f"SELECT {', '.join(CITATION_COLUMNS)} FROM board_fact_citations FINAL "
            "WHERE board_id = {b:String} ORDER BY fact_id, label",
            parameters={"b": board_id},
        )
    return [CitationRow(**dict(zip(CITATION_COLUMNS, row))) for row in result.result_rows]


# ------------------------------------------------------------------------ state caches


def read_state_rows(board_id: str) -> tuple[dict | None, dict[str, dict]]:
    """The stored state row and intent rows, for the compare before a write."""
    with _client() as client:
        state = client.query(
            f"SELECT {', '.join(STATE_COLUMNS)} FROM board_state FINAL WHERE board_id = {{b:String}}",
            parameters={"b": board_id},
        )
        intents = client.query(
            f"SELECT {', '.join(INTENT_COLUMNS)} FROM board_intents FINAL WHERE board_id = {{b:String}}",
            parameters={"b": board_id},
        )
    state_row = dict(zip(STATE_COLUMNS, state.result_rows[0])) if state.result_rows else None
    intent_rows = {row[1]: dict(zip(INTENT_COLUMNS, row)) for row in intents.result_rows}
    return state_row, intent_rows


def write_state(state: dict, intents: list[dict]) -> None:
    """Write the derived rows. Only `board_plan` calls this."""
    if state:
        _insert("board_state", [[state[c] for c in STATE_COLUMNS]], STATE_COLUMNS)
    _insert("board_intents", [[i[c] for c in INTENT_COLUMNS] for i in intents], INTENT_COLUMNS)


__all__ = [
    "BoardRow", "CitationRow", "EventRow", "FactRow", "board_is_live", "fact_exists", "now",
    "read_board", "read_citations", "read_events", "read_facts", "read_live_boards",
    "read_state_rows", "write_event", "write_events", "write_fact", "write_state",
]
