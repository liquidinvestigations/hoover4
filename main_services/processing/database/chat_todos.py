"""The agent's todo list for one chat session, and the rules the nag protocol reads.

The list is a goal plus items, stored as whole-list snapshots in `chat_todos` and
versioned on an update counter. Four operations write it -- `write` replaces the plan,
`edit` changes rows without touching the goal, `mark` flips statuses in a batch -- and
`read` returns the current snapshot. Each is a distinct argument shape on purpose: a
model calls a typed tool correctly far more often than it fills a dispatch envelope.

Two rules here must hold, and neither is obvious from the schema:

* **`cancelled` requires a note.** An item abandoned with a stated reason counts as
  resolved, so an over-ambitious plan does not earn two nags for nothing. The note is
  what stops cancellation being a free exit -- without it, the cheapest way out of any
  plan is to cancel every row.
* **A bare status flip is not a change.** [`is_material_change`] compares two snapshots
  and answers whether the plan itself moved. The nag counter resets on a change, so if
  toggling one row counted, a model could farm resets forever and the cap on nags would
  be decorative. Adding, removing or rewriting an item counts. Rewriting the goal counts.
  Moving `pending` to `done` does not.
"""

import json
import logging
import re
from datetime import datetime, timezone

import pyarrow as pa

log = logging.getLogger(__name__)

#: Every status an item can hold. The last two are resolved, the first two are open.
ITEM_STATUSES = ("pending", "in_progress", "done", "cancelled")

#: Statuses that count as finished for the purposes of the nag. `cancelled` is here
#: because an item abandoned with a reason is a decision, not an omission.
RESOLVED_STATUSES = ("done", "cancelled")

#: Statuses that require an explanatory note before the write is accepted.
NOTE_REQUIRED_STATUSES = ("cancelled",)

#: Caps. A todo is a plan the model has to keep in its head, not a work queue, and an
#: unbounded list is how a plan stops being read.
MAX_ITEMS = 40
MAX_TEXT_CHARS = 500
MAX_GOAL_CHARS = 2000

_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class TodoError(ValueError):
    """A todo write that the rules refuse. The message is shown to the model verbatim."""


def _now() -> datetime:
    """UTC with the tzinfo dropped: ClickHouse DateTime columns are naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def empty_todo(session_id: str = "", username: str = "") -> dict:
    """The list a session has before anything has ever been written to it.

    Version 0 is the sentinel for "never written". The first real write is version 1,
    so a caller can tell "no plan yet" from "a plan that happens to be empty".
    """
    return {
        "session_id": session_id,
        "username": username,
        "version": 0,
        "goal": "",
        "items": [],
        "updated_at": None,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def normalise_item(raw: dict, index: int) -> dict:
    """One item, checked and reduced to exactly the four fields the table holds.

    Raises [`TodoError`] rather than dropping a bad field, because a silently discarded
    item is a plan the model treats as written and the user cannot see.
    """
    if not isinstance(raw, dict):
        raise TodoError(f"item {index} is not an object")

    item_id = str(raw.get("id") or "").strip()
    if not item_id:
        item_id = f"item-{index + 1}"
    if not _ID_RE.match(item_id):
        raise TodoError(
            f"item id {item_id!r} is not allowed: letters, digits, dot, dash and "
            "underscore only, up to 64 characters"
        )

    text = str(raw.get("text") or "").strip()
    if not text:
        raise TodoError(f"item {item_id!r} has no text")
    if len(text) > MAX_TEXT_CHARS:
        raise TodoError(f"item {item_id!r} text is longer than {MAX_TEXT_CHARS} characters")

    status = str(raw.get("status") or "pending").strip().lower()
    if status not in ITEM_STATUSES:
        raise TodoError(
            f"item {item_id!r} has status {status!r}: expected one of "
            + ", ".join(ITEM_STATUSES)
        )

    note = str(raw.get("note") or "").strip()
    if status in NOTE_REQUIRED_STATUSES and not note:
        raise TodoError(
            f"item {item_id!r} is {status} and needs a note saying why. A cancelled item "
            "counts as resolved, so the reason is the whole record of the decision."
        )

    return {"id": item_id, "text": text, "status": status, "note": note}


def normalise_items(raw_items) -> list[dict]:
    """A whole list, checked. Duplicate ids are refused, not renamed."""
    if raw_items is None:
        raw_items = []
    if not isinstance(raw_items, (list, tuple)):
        raise TodoError("items must be a list")
    if len(raw_items) > MAX_ITEMS:
        raise TodoError(f"a todo holds at most {MAX_ITEMS} items, got {len(raw_items)}")

    items = [normalise_item(raw, i) for i, raw in enumerate(raw_items)]
    seen = set()
    for item in items:
        if item["id"] in seen:
            raise TodoError(f"item id {item['id']!r} appears twice")
        seen.add(item["id"])
    return items


def normalise_goal(goal) -> str:
    goal = str(goal or "").strip()
    if len(goal) > MAX_GOAL_CHARS:
        raise TodoError(f"goal is longer than {MAX_GOAL_CHARS} characters")
    return goal


# ---------------------------------------------------------------------------
# The questions the nag protocol asks
# ---------------------------------------------------------------------------


def is_open(todo: dict) -> bool:
    """True when at least one item is still pending or in progress.

    A list with no items at all is not open: there is nothing to nag about. That is also
    what makes the plan-first rule mechanical -- an empty or fully resolved todo is the
    trigger to plan, and it is checkable here rather than being a judgement the model has
    to make about whether a follow-up question started a new investigation.
    """
    return any(item["status"] not in RESOLVED_STATUSES for item in todo.get("items", []))


def needs_plan(todo: dict) -> bool:
    """True when the plan-first protocol applies: no plan yet, or every item resolved."""
    items = todo.get("items", [])
    if not items:
        return True
    return not is_open(todo)


def is_material_change(before: dict, after: dict) -> bool:
    """Did the plan itself move between these two snapshots?

    This is the nag counter's reset condition, and it deliberately ignores status. A
    model that could earn a reset by flipping one row from pending to in_progress would
    never hit the cap, and the cap is the only thing bounding a turn. So: the goal
    changing counts, an item appearing or disappearing counts, an item's text or note
    changing counts. A status flip on an item that was already there does not.
    """
    if normalise_goal(before.get("goal")) != normalise_goal(after.get("goal")):
        return True

    def shape(todo):
        return {i["id"]: (i["text"], i["note"]) for i in todo.get("items", [])}

    return shape(before) != shape(after)


def summarise(todo: dict) -> str:
    """One line for a log or a nag message: how much of the plan is left."""
    items = todo.get("items", [])
    if not items:
        return "no plan written"
    resolved = sum(1 for i in items if i["status"] in RESOLVED_STATUSES)
    return f"{resolved}/{len(items)} items resolved"


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _insert(row: dict) -> None:
    from .clickhouse import get_global_client, insert_arrow_durable

    table = pa.table({
        "session_id": pa.array([row["session_id"]], type=pa.string()),
        "username": pa.array([row["username"]], type=pa.string()),
        "version": pa.array([int(row["version"])], type=pa.uint32()),
        "goal": pa.array([row["goal"]], type=pa.string()),
        "items": pa.array([row["items"]], type=pa.string()),
        "updated_at": pa.array([row["updated_at"]], type=pa.timestamp("ms")),
    })
    with get_global_client() as client:
        insert_arrow_durable(client, "chat_todos", table)


def read_todo(username: str, session_id: str) -> dict:
    """The current list, or [`empty_todo`] when nothing has been written.

    The newest version is the highest `version`, which is the tail of the sort key, so
    this reads a range rather than scanning. A malformed `items` blob is reported as an
    empty list and logged rather than raised: a todo that cannot be parsed must not make
    the whole turn fail.
    """
    from .clickhouse import get_global_client

    sql = (
        "SELECT version, goal, items, updated_at FROM chat_todos "
        "WHERE username = {username:String} AND session_id = {session_id:String} "
        "ORDER BY version DESC LIMIT 1"
    )
    with get_global_client() as client:
        result = client.query(
            sql, parameters={"username": username, "session_id": session_id}
        )
    if not result.result_rows:
        return empty_todo(session_id, username)

    version, goal, items_json, updated_at = result.result_rows[0]
    try:
        items = normalise_items(json.loads(items_json or "[]"))
    except (ValueError, TypeError) as e:
        log.warning("chat_todos: unreadable items for session %s: %s", session_id, e)
        items = []
    return {
        "session_id": session_id,
        "username": username,
        "version": int(version),
        "goal": goal,
        "items": items,
        "updated_at": updated_at,
    }


def _write_version(username: str, session_id: str, goal: str, items: list[dict]) -> dict:
    """Append the next version. Returns the snapshot that was written."""
    current = read_todo(username, session_id)
    version = int(current["version"]) + 1
    _insert({
        "session_id": session_id,
        "username": username,
        "version": version,
        "goal": goal,
        "items": json.dumps(items, ensure_ascii=False),
        "updated_at": _now(),
    })
    return {
        "session_id": session_id,
        "username": username,
        "version": version,
        "goal": goal,
        "items": items,
        "updated_at": None,
    }


def write_todo(username: str, session_id: str, goal: str, items) -> dict:
    """Replace the whole plan -- the plan-first call. Goal and items both move."""
    return _write_version(
        username, session_id, normalise_goal(goal), normalise_items(items)
    )


def edit_todo(username: str, session_id: str, items) -> dict:
    """Replace the items and keep the goal.

    The argument is the list the model wants to end up with, not a patch. Asking for the
    whole list is what makes removal expressible at all, and it is the shape a model
    fills correctly -- a patch language invites half-applied edits nobody can see.
    """
    current = read_todo(username, session_id)
    return _write_version(
        username, session_id, current["goal"], normalise_items(items)
    )


def mark_todo(username: str, session_id: str, marks) -> dict:
    """Batched status changes, by item id. Everything else on the item is untouched.

    A mark naming an id that is not in the list is refused rather than ignored: the
    model treats it as recorded progress, and silently dropping it makes the plan and the
    transcript disagree.
    """
    if not isinstance(marks, (list, tuple)) or not marks:
        raise TodoError("marks must be a non-empty list of {id, status, note}")

    current = read_todo(username, session_id)
    by_id = {item["id"]: dict(item) for item in current["items"]}
    if not by_id:
        raise TodoError("there is no todo to mark yet -- call write_todo first")

    for mark in marks:
        if not isinstance(mark, dict):
            raise TodoError("each mark must be an object with id, status and note")
        item_id = str(mark.get("id") or "").strip()
        if item_id not in by_id:
            known = ", ".join(sorted(by_id))
            raise TodoError(f"no item {item_id!r} in this todo. Known ids: {known}")
        item = by_id[item_id]
        if "status" in mark and mark["status"] is not None:
            item["status"] = str(mark["status"]).strip().lower()
        if "note" in mark and mark["note"] is not None:
            item["note"] = str(mark["note"]).strip()
        by_id[item_id] = item

    order = [item["id"] for item in current["items"]]
    items = normalise_items([by_id[i] for i in order])
    return _write_version(username, session_id, current["goal"], items)


def delete_todos(username: str, session_id: str) -> None:
    """Drop every version for one session. Called when the chat session is deleted."""
    from .clickhouse import get_global_client

    with get_global_client() as client:
        client.command(
            "DELETE FROM chat_todos WHERE username = {username:String} "
            "AND session_id = {session_id:String}",
            parameters={"username": username, "session_id": session_id},
        )
