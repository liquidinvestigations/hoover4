"""The todo list's rules, tested without a database.

Everything here is pure: validation, and the two questions the nag protocol asks a
snapshot. The storage functions are not covered -- they are three lines of insert around
these rules, and a test of them would be a test of ClickHouse.
"""

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


def test_cancelled_without_a_note_is_refused():
    """The rule that stops cancellation becoming a free exit from an awkward plan."""
    with pytest.raises(todos.TodoError, match="needs a note"):
        todos.normalise_items(_items(("a", "do the thing", "cancelled", "")))


def test_cancelled_with_a_note_is_accepted():
    [item] = todos.normalise_items(_items(("a", "do the thing", "cancelled", "no data")))
    assert item["status"] == "cancelled"


def test_done_needs_no_note():
    [item] = todos.normalise_items(_items(("a", "do the thing", "done", "")))
    assert item["note"] == ""


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
    """The whole point of the cap: a model must not be able to farm resets."""
    before = {"goal": "g", "items": _items(("a", "x", "pending", ""))}
    after = {"goal": "g", "items": _items(("a", "x", "in_progress", ""))}
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
