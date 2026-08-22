"""The nag loop's rules, and the one that makes the cap real.

The loop itself lives in `ChatTurn` and needs Temporal to run; everything it decides
with is here and is pure, so the counters can be exercised without a workflow.

The case worth reading twice is
`a_bare_status_flip_does_not_buy_another_nag`: if flipping one row from pending to
in_progress reset the counter, a model could keep a turn alive for ever by toggling it,
and both caps would be decorative.
"""

from database import chat_todos as todos
from tasks.P_agent import nagging


def _todo(goal="find the invoices", *items):
    return {"goal": goal, "items": list(items), "version": 1}


def _item(item_id, text, status="pending", note=""):
    return {"id": item_id, "text": text, "status": status, "note": note}


# ------------------------------------------------------------------ when to stop


def test_a_finished_plan_is_never_nagged():
    todo = _todo("g", _item("1", "read them", "done"))
    assert nagging.stop_reason(todo, 0, 0) == "resolved"


def test_an_empty_plan_is_never_nagged():
    assert nagging.stop_reason(_todo("g"), 0, 0) == "resolved"


def test_a_cancelled_item_with_a_note_counts_as_finished():
    # The store's rule, not a second copy of it: `cancelled` requires a note, and an
    # item abandoned with a reason is a decision rather than an omission.
    todo = _todo("g", _item("1", "read them", "cancelled", "no such file exists"))
    assert nagging.stop_reason(todo, 0, 0) == "resolved"


def test_an_open_plan_earns_a_nag():
    assert nagging.stop_reason(_todo("g", _item("1", "read them")), 0, 0) == ""


def test_two_nags_without_progress_are_the_limit():
    todo = _todo("g", _item("1", "read them"))
    assert nagging.stop_reason(todo, 1, 1) == ""
    assert "not changed" in nagging.stop_reason(todo, 2, 2)


def test_the_per_turn_cap_stops_a_turn_that_keeps_making_progress():
    # Five nags is the backstop the resetting counter cannot lift: this plan moved
    # before every nag, so `nags_without_progress` is 0 and only the turn cap is left.
    todo = _todo("g", _item("1", "read them"))
    assert nagging.stop_reason(todo, 0, 4) == ""
    assert "in one turn" in nagging.stop_reason(todo, 0, 5)


def test_a_finished_plan_is_told_it_finished_not_that_it_ran_out_of_nags():
    todo = _todo("g", _item("1", "read them", "done"))
    assert nagging.stop_reason(todo, 5, 9) == "resolved"


# ------------------------------------------------ what resets the counter, and what does not


def test_a_bare_status_flip_does_not_buy_another_nag():
    """The whole protocol. Flipping a status is not progress the counter may reset on."""
    before = _todo("g", _item("1", "read them"), _item("2", "summarise them"))
    after = _todo("g", _item("1", "read them", "in_progress"), _item("2", "summarise them"))

    assert not todos.is_material_change(before, after)

    # So a workflow that had already nagged twice stops, exactly as it would have
    # without the flip.
    nags_without_progress = 2
    if todos.is_material_change(before, after):
        nags_without_progress = 0
    assert nagging.stop_reason(after, nags_without_progress, 2) != ""


def test_marking_an_item_done_is_still_not_a_reset():
    before = _todo("g", _item("1", "read them"), _item("2", "summarise them"))
    after = _todo("g", _item("1", "read them", "done"), _item("2", "summarise them"))
    assert not todos.is_material_change(before, after)


def test_a_new_item_is_progress():
    before = _todo("g", _item("1", "read them"))
    after = _todo("g", _item("1", "read them"), _item("2", "summarise them"))
    assert todos.is_material_change(before, after)


def test_a_rewritten_goal_is_progress():
    before = _todo("find the invoices", _item("1", "read them"))
    after = _todo("find the 2003 invoices only", _item("1", "read them"))
    assert todos.is_material_change(before, after)


def test_cancelling_an_item_is_progress_because_the_note_is_new_text():
    # A cancellation carries a note, so it changes the item as well as its status --
    # which is what makes revising an over-ambitious plan a way out rather than a trap.
    before = _todo("g", _item("1", "read the 400 000 emails"))
    after = _todo("g", _item("1", "read the 400 000 emails", "cancelled", "too many to read"))
    assert todos.is_material_change(before, after)


# ------------------------------------------------------------------ what a nag says


def test_the_first_nag_asks_for_the_plan_to_be_revised():
    todo = _todo("g", _item("1", "read them", "done"), _item("2", "summarise them"))
    message = nagging.nag_message(todo, 1)
    assert "write_todo" in message and "cancel" in message
    # It points at the item actually left, not at the finished one.
    assert "summarise them" in message
    assert "1/2 items resolved" in message


def test_the_second_nag_only_asks_for_the_work():
    todo = _todo("g", _item("1", "read them"))
    message = nagging.nag_message(todo, 2)
    assert "write_todo" not in message
    assert "Finish the remaining items" in message


def test_open_items_are_the_unresolved_ones_in_plan_order():
    todo = _todo(
        "g",
        _item("1", "first", "done"),
        _item("2", "second"),
        _item("3", "third", "cancelled", "dropped"),
        _item("4", "fourth", "in_progress"),
    )
    assert [i["id"] for i in nagging.open_items(todo)] == ["2", "4"]
