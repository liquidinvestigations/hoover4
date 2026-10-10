"""The agent's todo lists and the rules the nag protocol reads.

The list is a goal plus items, stored as whole-list snapshots in `chat_todos` and
versioned on an update counter. Four operations write it -- `write` sets the goal and the
plan, `edit` changes rows without touching the goal, `mark` sets one status on a batch of
rows -- and `read` returns the current snapshot. Each is a distinct argument shape on
purpose: a model calls a typed tool correctly far more often than it fills a dispatch
envelope.

A new write uses two statuses, `pending` and `done`. Stored snapshots can also hold the
legacy `in_progress` and `cancelled`, and they stay readable: [`display_status`] reads
`in_progress` as pending and `cancelled` as done. A stored row keeps its original bytes.

These rules must hold, and none is apparent from the schema:

* **A new completion needs a reason.** An item that a write moves to `done` must carry a
  nonempty `note`, such as `found`, `not found` or `replaced`. The rule applies only to the
  transition, so an older done item without a note stays readable and unchanged.
* **An item keeps its identity.** Completed and replaced items stay in the list. An edit
  that omits an open item ends it with the note [`REMOVED_NOTE`]. A new item gets a
  number above every identity in the list, so no identity is used twice for one goal.
  A replacement is explicit: the new item records `replaces_id`, and the old item ends
  with the stated reason, directly above it.
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

#: The reason an edit stores on an open item that its new step list omits.
REMOVED_NOTE = "removed from plan"

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
# The step list operations of the todo tools
# ---------------------------------------------------------------------------
#
# The todo tools take a goal and a list of step strings. The store gives each step its
# id, so the model never writes an id. The item rules above still apply to every
# written list.


def _step_texts(steps) -> list[str]:
    """The step strings, stripped, with the empty ones left out."""
    if steps is None:
        steps = []
    if isinstance(steps, str):
        steps = [steps]
    if not isinstance(steps, (list, tuple)):
        raise TodoError("steps must be a list of strings")
    return [str(step).strip() for step in steps if str(step).strip()]


def _folded(text: str) -> str:
    return " ".join(text.split())


def _next_id(items: list[dict]) -> int:
    """The number above every numeric identity in `items`."""
    numbers = [int(item["id"]) for item in items if item["id"].isdigit()]
    return max(numbers, default=0) + 1


def _replacements(raw, items: list[dict], texts: list[str]) -> dict[str, dict]:
    """The checked replacement entries that are not yet applied, by folded new text.

    Each entry names the `id` of the replaced step, the new step `text`, which must occur
    once in `texts`, and the `note` that ends the old step. An entry whose replacement
    already exists, with the same text, is skipped, so a repeated call gives the same
    list. Every other conflict is refused before anything is written.
    """
    if raw is None:
        raw = []
    if not isinstance(raw, (list, tuple)):
        raise TodoError("replacements must be a list of objects with id, text and note")
    by_id = {item["id"]: item for item in items}
    successor = {item["replaces_id"]: item for item in items if item.get("replaces_id")}
    folded = [_folded(text) for text in texts]
    known = ", ".join(item["id"] for item in items)
    planned: dict[str, dict] = {}
    named: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise TodoError("each replacement must be an object with id, text and note")
        old_id = str(entry.get("id") or "").strip()
        text = _folded(str(entry.get("text") or ""))
        note = str(entry.get("note") or "").strip()
        if old_id not in by_id:
            raise TodoError(f"replacement names step {old_id!r}, which does not exist. The steps are {known}.")
        if old_id in named:
            raise TodoError(f"step {old_id!r} has more than one replacement.")
        named.add(old_id)
        if folded.count(text) != 1:
            raise TodoError(f"the replacement text {text!r} must occur exactly once in steps.")
        if text in planned:
            raise TodoError(f"two replacements give the same text {text!r}.")
        earlier = successor.get(old_id)
        if earlier is not None:
            if _folded(earlier["text"]) != text:
                raise TodoError(f"step {old_id!r} was already replaced by step {earlier['id']!r}.")
            continue
        if by_id[old_id]["status"] in RESOLVED_STATUSES:
            raise TodoError(f"step {old_id!r} is already done. Add the new step without a replacement.")
        if any(_folded(item["text"]) == text for item in items):
            raise TodoError(f"the replacement text {text!r} is already the text of a step.")
        if not note:
            raise TodoError(f"the replacement of step {old_id!r} needs a note that says why the old step ended.")
        planned[text] = {"id": old_id, "note": note}
    return planned


def _reconciled(items: list[dict], texts: list[str], replacements) -> list[dict]:
    """The list after an edit to `texts`, with every earlier item retained.

    A step whose text equals a current item's text, with whitespace folded, keeps that
    item's id, status and note. A replacement ends the old item with its note and puts it
    directly above the new item, which records `replaces_id`. Any other new step gets the
    next free number. A current item that no step names stays in the list near its old
    position: a done item as it was, an open item done with [`REMOVED_NOTE`].
    """
    planned = _replacements(replacements, items, texts)
    by_id = {item["id"]: item for item in items}
    unused = [item["id"] for item in items]
    next_id = _next_id(items)
    built: list[dict] = []
    for text in texts:
        key = _folded(text)
        if key in planned:
            entry = planned[key]
            unused.remove(entry["id"])
            built.append({**by_id[entry["id"]], "status": "done", "note": entry["note"]})
            built.append({"id": str(next_id), "text": text, "status": "pending", "note": "",
                          "replaces_id": entry["id"]})
            next_id += 1
            continue
        matches = [by_id[i] for i in unused if _folded(by_id[i]["text"]) == key]
        kept = next((m for m in matches if m["status"] not in RESOLVED_STATUSES), None) or next(iter(matches), None)
        if kept is not None:
            unused.remove(kept["id"])
            built.append(dict(kept))
            continue
        built.append({"id": str(next_id), "text": text, "status": "pending", "note": ""})
        next_id += 1
    for index, item in enumerate(items):
        if item["id"] not in unused:
            continue
        kept = dict(item)
        if kept["status"] not in RESOLVED_STATUSES:
            kept.update(status="done", note=REMOVED_NOTE)
        following = next((i for i, b in enumerate(built) if b.get("replaces_id") == kept["id"]), None)
        if following is not None:
            built.insert(following, kept)
            continue
        earlier = {i["id"] for i in items[:index]}
        position = max((i + 1 for i, b in enumerate(built) if b["id"] in earlier), default=0)
        while 0 < position < len(built) and built[position].get("replaces_id") == built[position - 1]["id"]:
            position += 1
        built.insert(position, kept)
    if len(built) > MAX_ITEMS:
        raise TodoError(
            f"the plan would hold {len(built)} steps, counting done and removed steps, and a "
            f"plan holds at most {MAX_ITEMS}. Give fewer new steps, or start a new goal with write_todo."
        )
    return normalise_items(built)


def write_steps(username: str, session_id: str, goal, steps) -> dict:
    """Set the plan to `goal` and `steps`.

    A new goal starts a new list, and its steps get the ids 1, 2, 3. The earlier snapshots
    keep the earlier goal. The same goal as the current one reconciles the steps as
    [`edit_steps`] does, so a repeated write keeps the done steps and their notes. An
    empty goal or an empty step list is refused, because a plan with neither is not a plan
    the nag protocol can read.
    """
    goal = normalise_goal(goal)
    if not goal:
        raise TodoError("the goal is empty. Write one or two sentences.")
    texts = _step_texts(steps)
    if not texts:
        raise TodoError("steps is empty. Give at least one step.")
    current = read_todo(username, session_id)
    if current["items"] and _folded(normalise_goal(current["goal"])) == _folded(goal):
        items = _reconciled(current["items"], texts, [])
        return _write_version(username, session_id, current["goal"], items, current)
    items = normalise_items(
        [{"id": str(i), "text": text, "status": "pending", "note": ""} for i, text in enumerate(texts, 1)]
    )
    return _write_version(username, session_id, goal, items, current)


def edit_steps(username: str, session_id: str, steps, replacements=None) -> dict:
    """Revise the steps and keep the goal. See [`_reconciled`] for what each step keeps.

    `replacements` is an optional list of `{id, text, note}` entries, one for each step
    that a new step replaces. A session with no plan, or a plan with an empty goal, is
    refused with the error of `write_steps`, because this call keeps the goal.
    """
    texts = _step_texts(steps)
    if not texts:
        raise TodoError("steps is empty. Give at least one step.")
    current = read_todo(username, session_id)
    if not normalise_goal(current["goal"]):
        raise TodoError("the goal is empty. Write one or two sentences.")
    items = _reconciled(current["items"], texts, replacements)
    return _write_version(username, session_id, current["goal"], items, current)


def mark_steps(username: str, session_id: str, ids, status: str, note: str = "") -> dict:
    """Set one status on each step in `ids`: `pending`, or `done` with a reason in `note`.

    A legacy status is normalized first: `in_progress` to pending and `cancelled` to done.
    A step that already reads as pending stays as it is when the status is pending, so
    the legacy in-progress mark adds no snapshot. An id that is not in the plan is refused
    with the ids that are.
    """
    wanted = _step_texts(ids)
    if not wanted:
        raise TodoError("ids is empty. Give at least one step id.")
    given = str(status or "").strip().lower()
    status = LEGACY_STATUSES.get(given, given)
    if status != given:
        log.info("chat_todos: mark status %s normalized to %s", given, status)
    if status not in WRITE_STATUSES:
        raise TodoError(f"status {given!r} is not allowed. Use pending or done.")
    note = str(note or "").strip()
    if status == "done" and not note:
        raise TodoError("a done step needs a short reason in note, such as found, not found or replaced.")
    current = read_todo(username, session_id)
    by_id = {item["id"]: dict(item) for item in current["items"]}
    if not by_id:
        raise TodoError("there is no plan to mark yet. Call write_todo first.")
    known = ", ".join(item["id"] for item in current["items"])
    for item_id in wanted:
        if item_id not in by_id:
            raise TodoError(f"step {item_id!r} does not exist. The steps are {known}.")
    for item_id in wanted:
        item = by_id[item_id]
        if status == "pending" and display_status(item["status"]) == "pending":
            continue
        item["status"] = status
        item["note"] = note
    items = normalise_items([by_id[item["id"]] for item in current["items"]])
    return _write_version(username, session_id, current["goal"], items, current)


def delete_todos(username: str, session_id: str) -> None:
    """Drop every version for one session. Called when the chat session is deleted."""
    from .clickhouse import get_global_client

    with get_global_client() as client:
        client.command(
            "DELETE FROM chat_todos WHERE username = {username:String} "
            "AND session_id = {session_id:String}",
            parameters={"username": username, "session_id": session_id},
        )
