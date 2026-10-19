"""The agent's todo lists and the rules the nag protocol reads.

The list is a goal plus items, stored as whole-list snapshots in `chat_todos` and
versioned on an update counter. One operation writes it: [`update_plan`] takes the goal and
the whole step list with statuses. [`read_todo`] returns the current snapshot. One tool
with the whole list keeps the model from mixing up several plan tools, and its result
shows the whole list.

A new write uses two statuses, `pending` and `done`. Stored snapshots can also hold the
legacy `in_progress` and `cancelled`, and they stay readable: [`display_status`] reads
`in_progress` as pending and `cancelled` as done. A stored row keeps its original bytes.

These rules must hold, and none is apparent from the schema:

* **A done step has a reason.** An item that a write moves to `done` must carry a
  nonempty `note`, such as `found`, `not found` or `replaced`. [`update_plan`] gives
  [`DONE_NOTE`] to a done step that the call sent without a note. The rule applies only
  to the transition, so an older done item without a note stays readable and unchanged.
* **An item keeps its identity.** With the same goal, a step with the same text keeps
  its id, and a new step gets a number above every identity in the list. A step that the
  call leaves out is not in the new version. The earlier versions keep it. Older
  snapshots can hold `replaces_id`, which stays readable.
* **An identical write changes nothing.** [`_write_version`] compares the new state with
  the current one and returns the current version when they are equal, so a repeated
  call adds no snapshot.
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


#: Every status a stored item can hold. `in_progress` and `cancelled` occur only in older
#: snapshots. A new write uses [`WRITE_STATUSES`].
ITEM_STATUSES = ("pending", "in_progress", "done", "cancelled")

#: The statuses a new write sets.
WRITE_STATUSES = ("pending", "done")

#: How a legacy status reads, and how a legacy status in a mark call is normalized.
LEGACY_STATUSES = {"in_progress": "pending", "cancelled": "done"}

#: Statuses that count as finished for the purposes of the nag. `cancelled` is here
#: because an item abandoned with a reason is a decision, not an omission.
RESOLVED_STATUSES = ("done", "cancelled")

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
    """One item, checked and reduced to the fields the table holds.

    The fields are `id`, `text`, `status` and `note`, and `replaces_id` when the item
    replaces an earlier one. Every stored status is accepted, so an older snapshot stays
    readable. The completion reason is checked where a write changes an item
    ([`_require_reasons`]), not here.

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
    item = {"id": item_id, "text": text, "status": status, "note": note}
    replaces = str(raw.get("replaces_id") or "").strip()
    if replaces:
        if not _ID_RE.match(replaces):
            raise TodoError(f"item {item_id!r} replaces an id that is not allowed")
        item["replaces_id"] = replaces
    return item


def display_status(status: str) -> str:
    """The status a reader sees: `pending` or `done`, with the legacy statuses mapped."""
    return LEGACY_STATUSES.get(status, status)


def display_items(items: list[dict]) -> list[dict]:
    """The items with display statuses. The note and every other field stay."""
    return [{**item, "status": display_status(item["status"])} for item in items]


def _require_reasons(before: list[dict], after: list[dict]) -> None:
    """Refuse a write that ends an item without a reason.

    Only a transition is checked: an item that is resolved in `after` and was not resolved
    with the same note in `before`. An older done item without a note passes unchanged.
    """
    earlier = {item["id"]: item for item in before}
    for item in after:
        if item["status"] not in RESOLVED_STATUSES or item["note"]:
            continue
        old = earlier.get(item["id"])
        if old is not None and old["status"] in RESOLVED_STATUSES and not old["note"]:
            continue
        raise TodoError(
            f"step {item['id']!r} is done and needs a short reason in note, such as "
            "found, not found or replaced."
        )


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


def _state(goal: str, items: list[dict]) -> tuple:
    """Everything a snapshot records, for the comparison that finds an identical write."""
    return (normalise_goal(goal), [(i["id"], i["text"], i["status"], i["note"], i.get("replaces_id", ""))
                                   for i in items])


def _write_version(username: str, session_id: str, goal: str, items: list[dict],
                   current: dict | None = None) -> dict:
    """Append the next version and return it, or return `current` when nothing changed.

    The returned snapshot has `unchanged`, true when no version was written. A refused
    write raises [`TodoError`] before anything is inserted, so a failed call changes
    nothing. `current` is the snapshot the caller already read.
    """
    if current is None:
        current = read_todo(username, session_id)
    _require_reasons(current["items"], items)
    if current["version"] and _state(current["goal"], current["items"]) == _state(goal, items):
        return {**current, "unchanged": True}
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
        "unchanged": False,
    }


def write_todo(username: str, session_id: str, goal: str, items) -> dict:
    """Store `goal` and `items` as given. The tools use [`write_steps`] instead."""
    return _write_version(
        username, session_id, normalise_goal(goal), normalise_items(items)
    )


# ---------------------------------------------------------------------------
# The plan tool
# ---------------------------------------------------------------------------
#
# `update_plan` takes the goal and the whole step list with statuses. The store gives each
# step its id, so the model never writes an id. The item rules above still apply to every
# written list.

#: The note of a done step that the call gave without a note.
DONE_NOTE = "done"


def _folded(text: str) -> str:
    return " ".join(text.split())


def _next_id(items: list[dict]) -> int:
    """The number above every numeric identity in `items`."""
    numbers = [int(item["id"]) for item in items if item["id"].isdigit()]
    return max(numbers, default=0) + 1


def _plan_step(raw, index: int) -> tuple[str, str, str]:
    """The text, the status and the note of one step of an `update_plan` call. A plain
    string is a pending step. A legacy status is normalized as a stored one reads."""
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, dict):
        raise TodoError(f"step {index + 1} is not an object with text and status")
    text = str(raw.get("text") or raw.get("step") or "").strip()
    if not text:
        raise TodoError(f"step {index + 1} has no text")
    given = str(raw.get("status") or "pending").strip().lower()
    status = LEGACY_STATUSES.get(given, given)
    if status not in WRITE_STATUSES:
        raise TodoError(f"step {index + 1} has status {given!r}. Use pending or done.")
    return text, status, str(raw.get("note") or "").strip()


def update_plan(username: str, session_id: str, goal, steps) -> dict:
    """Set the plan to `goal` and `steps`, the whole list with the status of each step.

    The stored list is the given list, in its order. With the same goal as the current
    plan, a step with the same text, with whitespace folded, keeps its id, and a new step
    gets the next free number. A new goal numbers the steps 1, 2, 3. A done step without
    a note gets [`DONE_NOTE`], or its earlier note when it was already done. An identical
    call adds no version (`_write_version`). An empty goal or an empty list is refused.
    """
    goal = normalise_goal(goal)
    if not goal:
        raise TodoError("the goal is empty. Write one or two sentences.")
    if isinstance(steps, (str, dict)):
        steps = [steps]
    if not isinstance(steps, (list, tuple)) or not steps:
        raise TodoError("steps is empty. Give at least one step.")
    parsed = [_plan_step(raw, index) for index, raw in enumerate(steps)]
    current = read_todo(username, session_id)
    same_goal = bool(current["items"]) and _folded(normalise_goal(current["goal"])) == _folded(goal)
    earlier = list(current["items"]) if same_goal else []
    next_id = _next_id(earlier)
    items = []
    for text, status, note in parsed:
        prior = next((i for i in earlier if _folded(i["text"]) == _folded(text)), None)
        if prior is not None:
            earlier.remove(prior)
            item_id = prior["id"]
        else:
            item_id = str(next_id)
            next_id += 1
        if status == "done" and not note:
            note = prior["note"] if prior is not None and prior["status"] in RESOLVED_STATUSES and prior["note"] else DONE_NOTE
        items.append({"id": item_id, "text": text, "status": status, "note": note if status == "done" else ""})
    if len(items) > MAX_ITEMS:
        raise TodoError(f"a plan holds at most {MAX_ITEMS} steps, got {len(items)}")
    return _write_version(username, session_id, current["goal"] if same_goal else goal,
                          normalise_items(items), current)


def delete_todos(username: str, session_id: str) -> None:
    """Drop every version for one session. Called when the chat session is deleted."""
    from .clickhouse import get_global_client

    with get_global_client() as client:
        client.command(
            "DELETE FROM chat_todos WHERE username = {username:String} "
            "AND session_id = {session_id:String}",
            parameters={"username": username, "session_id": session_id},
        )
