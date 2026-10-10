"""The todo list's rules, tested without a database.

Validation and the questions the nag protocol asks are pure. The step operations run
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


# ------------------------------------------------------------- the step operations


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


def test_a_new_goal_numbers_its_steps_and_an_identical_write_keeps_the_version(store):
    first = todos.write_steps("u", "s", "Find X", ["a", "b"])
    assert _shape(first) == [("1", "a", "pending", "", ""), ("2", "b", "pending", "", "")]
    again = todos.write_steps("u", "s", "Find X", ["a", "b"])
    assert (again["version"], again["unchanged"]) == (1, True)
    assert len(store[("u", "s")]) == 1


def test_a_repeated_same_goal_write_keeps_done_steps_and_their_reasons(store):
    todos.write_steps("u", "s", "Find X", ["a", "b"])
    todos.mark_steps("u", "s", ["1"], "done", "found")
    result = todos.write_steps("u", "s", "Find X", ["a", "b"])
    assert result["unchanged"] is True
    assert _shape(result)[0] == ("1", "a", "done", "found", "")


def test_a_changed_goal_starts_a_new_list_and_the_old_snapshot_keeps_the_old_goal(store):
    todos.write_steps("u", "s", "Find X", ["a", "b"])
    todos.mark_steps("u", "s", ["1"], "done", "found")
    result = todos.write_steps("u", "s", "Find Y", ["c"])
    assert (result["goal"], _shape(result)) == ("Find Y", [("1", "c", "pending", "", "")])
    assert store[("u", "s")][1]["goal"] == "Find X"


def test_a_done_mark_needs_a_reason_and_a_refusal_writes_nothing(store):
    todos.write_steps("u", "s", "g", ["a"])
    with pytest.raises(todos.TodoError, match="short reason"):
        todos.mark_steps("u", "s", ["1"], "done", "")
    assert len(store[("u", "s")]) == 1


def test_a_repeated_mark_with_the_same_reason_keeps_the_version(store):
    todos.write_steps("u", "s", "g", ["a"])
    first = todos.mark_steps("u", "s", ["1"], "done", "not found")
    second = todos.mark_steps("u", "s", ["1"], "done", "not found")
    assert (first["version"], second["version"], second["unchanged"]) == (2, 2, True)


def test_legacy_statuses_in_a_mark_are_normalized(store):
    todos.write_steps("u", "s", "g", ["a"])
    started = todos.mark_steps("u", "s", ["1"], "in_progress")
    assert started["unchanged"] is True
    with pytest.raises(todos.TodoError, match="short reason"):
        todos.mark_steps("u", "s", ["1"], "cancelled")
    cancelled = todos.mark_steps("u", "s", ["1"], "cancelled", "out of scope")
    assert _shape(cancelled) == [("1", "a", "done", "out of scope", "")]
    with pytest.raises(todos.TodoError, match="Use pending or done"):
        todos.mark_steps("u", "s", ["1"], "finished", "x")


def test_a_legacy_done_item_without_a_note_survives_later_writes(store):
    store[("u", "s")] = [{"version": 1, "goal": "g", "items": json.dumps(
        _items(("1", "a", "done", ""), ("2", "b", "in_progress", "")))}]
    result = todos.mark_steps("u", "s", ["2"], "done", "found")
    assert _shape(result) == [("1", "a", "done", "", ""), ("2", "b", "done", "found", "")]


def test_an_edit_keeps_matching_steps_and_retains_omitted_ones(store):
    todos.write_steps("u", "s", "g", ["a", "b", "c"])
    todos.mark_steps("u", "s", ["1"], "done", "found")
    result = todos.edit_steps("u", "s", ["c", "d"])
    assert _shape(result) == [
        ("1", "a", "done", "found", ""),
        ("2", "b", "done", todos.REMOVED_NOTE, ""),
        ("3", "c", "pending", "", ""),
        ("4", "d", "pending", "", ""),
    ]


def test_new_identities_stay_above_every_retained_identity(store):
    todos.write_steps("u", "s", "g", ["a", "b"])
    todos.edit_steps("u", "s", ["a"])
    result = todos.edit_steps("u", "s", ["a", "c"])
    assert [i["id"] for i in result["items"]] == ["1", "2", "3"]
    assert result["items"][2]["text"] == "c"


def test_an_explicit_replacement_ends_the_old_step_directly_above_the_new_one(store):
    todos.write_steps("u", "s", "g", ["a", "b", "c"])
    replacement = [{"id": "2", "text": "b, narrower", "note": "replaced by a narrower search"}]
    result = todos.edit_steps("u", "s", ["a", "b, narrower", "c"], replacement)
    assert _shape(result) == [
        ("1", "a", "pending", "", ""),
        ("2", "b", "done", "replaced by a narrower search", ""),
        ("4", "b, narrower", "pending", "", "2"),
        ("3", "c", "pending", "", ""),
    ]
    again = todos.edit_steps("u", "s", ["a", "b, narrower", "c"], replacement)
    assert (again["version"], again["unchanged"]) == (result["version"], True)
    later = todos.edit_steps("u", "s", ["c", "b, narrower"])
    assert [i["id"] for i in later["items"]] == ["1", "3", "2", "4"]


@pytest.mark.parametrize("entry, message", [
    ({"id": "9", "text": "x", "note": "n"}, "does not exist"),
    ({"id": "1", "text": "not a step", "note": "n"}, "exactly once"),
    ({"id": "1", "text": "b", "note": "n"}, "already the text of a step"),
    ({"id": "1", "text": "x", "note": ""}, "needs a note"),
])
def test_a_bad_replacement_is_refused_and_writes_nothing(store, entry, message):
    todos.write_steps("u", "s", "g", ["a", "b"])
    with pytest.raises(todos.TodoError, match=message):
        todos.edit_steps("u", "s", ["x", "b"], [entry])
    assert len(store[("u", "s")]) == 1


def test_duplicate_text_and_a_second_replacement_of_one_step_are_refused(store):
    todos.write_steps("u", "s", "g", ["a", "b"])
    with pytest.raises(todos.TodoError, match="exactly once"):
        todos.edit_steps("u", "s", ["x", "x", "b"], [{"id": "1", "text": "x", "note": "n"}])
    with pytest.raises(todos.TodoError, match="more than one replacement"):
        todos.edit_steps("u", "s", ["x", "y", "b"], [{"id": "1", "text": "x", "note": "n"},
                                                  {"id": "1", "text": "y", "note": "n"}])
    todos.edit_steps("u", "s", ["x", "b"], [{"id": "1", "text": "x", "note": "n"}])
    with pytest.raises(todos.TodoError, match="already replaced"):
        todos.edit_steps("u", "s", ["y", "b"], [{"id": "1", "text": "y", "note": "n"}])


def test_an_edit_that_would_pass_the_item_bound_is_refused_unchanged(store):
    todos.write_steps("u", "s", "g", [f"step {n}" for n in range(todos.MAX_ITEMS)])
    with pytest.raises(todos.TodoError, match="at most"):
        todos.edit_steps("u", "s", ["one new step"])
    assert len(store[("u", "s")]) == 1


def test_owners_and_sessions_keep_separate_lists(store):
    todos.write_steps("u", "s", "g", ["a"])
    todos.write_steps("v", "s", "g", ["b"])
    todos.write_steps("u", "t", "g", ["c"])
    assert [r["items"] for r in store[("u", "s")]] == [json.dumps(
        [{"id": "1", "text": "a", "status": "pending", "note": ""}])]
    assert len(store) == 3
