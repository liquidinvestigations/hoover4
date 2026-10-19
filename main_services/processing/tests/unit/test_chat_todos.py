"""The todo list's rules, tested without a database.

Validation and the questions the nag protocol asks are pure. The plan operation runs
against an in-memory stand-in for the table, keyed by owner and session as the real one
is, so the version and identity rules are tested without ClickHouse.
"""

import json

import pytest

from database import chat_todos as todos


def _items(*specs):
    return [
        {"id": i, "text": t, "status": s, "note": n}
        for (i, t, s, n) in specs
    ]


# --------------------------------------------------------------------- validation


def test_an_item_defaults_to_pending_and_keeps_its_id():
    [item] = todos.normalise_items([{"id": "a", "text": "look at the emails"}])
    assert item == {"id": "a", "text": "look at the emails", "status": "pending", "note": ""}


def test_an_item_without_an_id_gets_a_positional_one():
    [item] = todos.normalise_items([{"text": "look at the emails"}])
    assert item["id"] == "item-1"


def test_every_stored_status_stays_readable_without_a_note():
    """Older snapshots hold four statuses, and an older done item can have no note."""
    items = todos.normalise_items(_items(("a", "x", "done", ""), ("b", "y", "in_progress", ""),
                                         ("c", "z", "cancelled", "no data")))
    assert [i["status"] for i in items] == ["done", "in_progress", "cancelled"]


def test_the_display_status_reads_legacy_statuses_as_pending_or_done():
    items = _items(("a", "x", "in_progress", ""), ("b", "y", "cancelled", "no data"))
    assert [(i["status"], i["note"]) for i in todos.display_items(items)] == [
        ("pending", ""), ("done", "no data")]


def test_a_replacement_id_is_kept_and_absent_otherwise():
    [old, new] = todos.normalise_items([{"id": "1", "text": "x"}, {"id": "2", "text": "y", "replaces_id": "1"}])
    assert "replaces_id" not in old
    assert new["replaces_id"] == "1"


def test_an_unknown_status_is_refused_by_name():
    with pytest.raises(todos.TodoError, match="expected one of"):
        todos.normalise_items([{"id": "a", "text": "x", "status": "finished"}])


def test_an_empty_text_is_refused():
    with pytest.raises(todos.TodoError, match="no text"):
        todos.normalise_items([{"id": "a", "text": "   "}])


def test_a_duplicate_id_is_refused_rather_than_renamed():
    with pytest.raises(todos.TodoError, match="appears twice"):
        todos.normalise_items(
            _items(("a", "one", "pending", ""), ("a", "two", "pending", ""))
        )


def test_too_many_items_is_refused():
    many = [{"id": f"i{n}", "text": "x"} for n in range(todos.MAX_ITEMS + 1)]
    with pytest.raises(todos.TodoError, match="at most"):
        todos.normalise_items(many)


# ------------------------------------------------------ the questions the nag asks


def test_a_list_with_a_pending_item_is_open():
    todo = {"goal": "g", "items": _items(("a", "x", "pending", ""))}
    assert todos.is_open(todo)


def test_a_cancelled_item_counts_as_resolved():
    """An item abandoned with a reason must not earn a nag."""
    todo = {"goal": "g", "items": _items(("a", "x", "cancelled", "no data"))}
    assert not todos.is_open(todo)
    assert todos.needs_plan(todo)


def test_an_empty_list_is_not_open_but_does_need_a_plan():
    assert not todos.is_open(todos.empty_todo())
    assert todos.needs_plan(todos.empty_todo())


def test_a_fully_resolved_list_needs_a_new_plan():
    todo = {"goal": "g", "items": _items(("a", "x", "done", ""))}
    assert todos.needs_plan(todo)


def test_a_half_done_list_does_not_need_a_new_plan():
    todo = {
        "goal": "g",
        "items": _items(("a", "x", "done", ""), ("b", "y", "pending", "")),
    }
    assert not todos.needs_plan(todo)


# ------------------------------------------------- what resets the nag counter


def test_a_bare_status_flip_is_not_a_material_change():
    """What the cap is for: a model must not be able to farm resets."""
    before = {"goal": "g", "items": _items(("a", "x", "pending", ""))}
    after = {"goal": "g", "items": _items(("a", "x", "done", ""))}
    assert not todos.is_material_change(before, after)


def test_a_new_item_is_a_material_change():
    before = {"goal": "g", "items": _items(("a", "x", "pending", ""))}
    after = {"goal": "g", "items": _items(("a", "x", "pending", ""), ("b", "y", "pending", ""))}
    assert todos.is_material_change(before, after)


def test_a_removed_item_is_a_material_change():
    before = {"goal": "g", "items": _items(("a", "x", "pending", ""), ("b", "y", "pending", ""))}
    after = {"goal": "g", "items": _items(("a", "x", "pending", ""))}
    assert todos.is_material_change(before, after)


def test_rewriting_an_item_is_a_material_change():
    before = {"goal": "g", "items": _items(("a", "x", "pending", ""))}
    after = {"goal": "g", "items": _items(("a", "x, more precisely", "pending", ""))}
    assert todos.is_material_change(before, after)


def test_rewriting_the_goal_is_a_material_change():
    before = {"goal": "g", "items": _items(("a", "x", "pending", ""))}
    after = {"goal": "a narrower g", "items": _items(("a", "x", "pending", ""))}
    assert todos.is_material_change(before, after)


def test_adding_a_note_is_a_material_change():
    """A note carries the reasoning, so writing one is progress the model can show."""
    before = {"goal": "g", "items": _items(("a", "x", "pending", ""))}
    after = {"goal": "g", "items": _items(("a", "x", "pending", "nothing in the 2001 set"))}
    assert todos.is_material_change(before, after)


def test_reordering_alone_is_not_a_material_change():
    before = {"goal": "g", "items": _items(("a", "x", "pending", ""), ("b", "y", "pending", ""))}
    after = {"goal": "g", "items": _items(("b", "y", "pending", ""), ("a", "x", "pending", ""))}
    assert not todos.is_material_change(before, after)


def test_summarise_counts_resolved_over_total():
    todo = {
        "goal": "g",
        "items": _items(
            ("a", "x", "done", ""),
            ("b", "y", "cancelled", "no data"),
            ("c", "z", "pending", ""),
        ),
    }
    assert todos.summarise(todo) == "2/3 items resolved"


# ------------------------------------------------------------------ the plan tool


@pytest.fixture
def store(monkeypatch):
    """An in-memory `chat_todos` table: every inserted version, by owner and session."""
    rows: dict[tuple[str, str], list[dict]] = {}

    def fake_read(username, session_id):
        versions = rows.get((username, session_id))
        if not versions:
            return todos.empty_todo(session_id, username)
        row = versions[-1]
        return {"session_id": session_id, "username": username, "version": row["version"],
                "goal": row["goal"], "items": todos.normalise_items(json.loads(row["items"])),
                "updated_at": None}

    def fake_insert(row):
        rows.setdefault((row["username"], row["session_id"]), []).append(row)

    monkeypatch.setattr(todos, "read_todo", fake_read)
    monkeypatch.setattr(todos, "_insert", fake_insert)
    return rows


def _shape(todo):
    return [(i["id"], i["text"], i["status"], i["note"], i.get("replaces_id", "")) for i in todo["items"]]


def P(text, status="pending", note=""):
    return {"text": text, "status": status, "note": note}


def test_a_new_goal_numbers_its_steps_and_an_identical_call_keeps_the_version(store):
    first = todos.update_plan("u", "s", "Find X", [P("a"), P("b")])
    assert _shape(first) == [("1", "a", "pending", "", ""), ("2", "b", "pending", "", "")]
    again = todos.update_plan("u", "s", "Find X", [P("a"), P("b")])
    assert (again["version"], again["unchanged"]) == (1, True)
    assert len(store[("u", "s")]) == 1


def test_the_same_goal_keeps_ids_by_text_and_numbers_new_steps_above_them(store):
    todos.update_plan("u", "s", "Find X", [P("a"), P("b"), P("c")])
    result = todos.update_plan("u", "s", "Find X", [P("c"), P("a", "done", "found"), P("d")])
    assert _shape(result) == [("3", "c", "pending", "", ""), ("1", "a", "done", "found", ""),
                              ("4", "d", "pending", "", "")]


def test_a_done_step_without_a_note_gets_the_default_or_keeps_its_note(store):
    todos.update_plan("u", "s", "g", [P("a", "done", "found"), P("b")])
    result = todos.update_plan("u", "s", "g", [P("a", "done"), P("b", "done")])
    assert _shape(result) == [("1", "a", "done", "found", ""), ("2", "b", "done", todos.DONE_NOTE, "")]


def test_a_changed_goal_starts_a_new_list_and_the_old_snapshot_keeps_the_old_goal(store):
    todos.update_plan("u", "s", "Find X", [P("a", "done", "found"), P("b")])
    result = todos.update_plan("u", "s", "Find Y", [P("c")])
    assert (result["goal"], _shape(result)) == ("Find Y", [("1", "c", "pending", "", "")])
    assert store[("u", "s")][0]["goal"] == "Find X"


def test_plain_strings_and_legacy_statuses_are_read_and_unknown_statuses_refused(store):
    result = todos.update_plan("u", "s", "g", ["a", {"text": "b", "status": "in_progress"},
                                               {"step": "c", "status": "cancelled", "note": "out"}])
    assert _shape(result) == [("1", "a", "pending", "", ""), ("2", "b", "pending", "", ""),
                              ("3", "c", "done", "out", "")]
    with pytest.raises(todos.TodoError, match="Use pending or done"):
        todos.update_plan("u", "s", "g", [P("a", "finished")])
    assert len(store[("u", "s")]) == 1


@pytest.mark.parametrize("goal, steps, message", [
    ("", [P("a")], "goal is empty"),
    ("g", [], "steps is empty"),
    ("g", [{"status": "done"}], "has no text"),
    ("g", [P(f"step {n}") for n in range(todos.MAX_ITEMS + 1)], "at most"),
])
def test_a_bad_plan_is_refused_and_writes_nothing(store, goal, steps, message):
    with pytest.raises(todos.TodoError, match=message):
        todos.update_plan("u", "s", goal, steps)
    assert ("u", "s") not in store


def test_a_legacy_done_item_without_a_note_survives_later_calls(store):
    store[("u", "s")] = [{"version": 1, "goal": "g", "items": json.dumps(
        _items(("1", "a", "done", ""), ("2", "b", "in_progress", "")))}]
    result = todos.update_plan("u", "s", "g", [P("a", "done"), P("b", "done", "found")])
    assert _shape(result) == [("1", "a", "done", todos.DONE_NOTE, ""), ("2", "b", "done", "found", "")]


def test_owners_and_sessions_keep_separate_lists(store):
    todos.update_plan("u", "s", "g", [P("a")])
    todos.update_plan("v", "s", "g", [P("b")])
    todos.update_plan("u", "t", "g", [P("c")])
    assert [r["items"] for r in store[("u", "s")]] == [json.dumps(
        [{"id": "1", "text": "a", "status": "pending", "note": ""}])]
    assert len(store) == 3
