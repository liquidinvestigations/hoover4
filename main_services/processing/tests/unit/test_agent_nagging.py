"""The nag loop's rules, and the one that makes the cap real.

The loop itself lives in `AgentRun` and needs Temporal to run; everything it decides
with is here and is pure, so the counters can be exercised without a workflow.

The case worth reading twice is
`a_bare_status_flip_does_not_buy_another_nag`: if flipping one row from pending to
in_progress reset the counter, a model could keep a turn alive for ever by toggling it,
and both caps would be decorative.
"""

import pytest

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


def test_the_nag_asks_only_for_the_todo_marks():
    """A nag follows the answer. It asks for `done` or `cancelled` on each open item, and
    for no second answer and no new work."""
    todo = _todo("g", _item("1", "read them", "done"), _item("2", "summarise them"),
                 _item("3", "grade them", "in_progress"))
    message = nagging.nag_message(todo, 1)
    assert "mark_todo" in message and "`done`" in message and "`cancelled`" in message
    assert "write_todo" not in message and "read_todo" not in message
    assert "Do not write the answer again" in message
    # It names each open item with its id, and not the finished one.
    assert "- 2. summarise them" in message and "- 3. grade them" in message
    assert "read them" not in message
    assert "1/3 items resolved" in message


def test_the_second_nag_says_the_list_is_still_open():
    todo = _todo("g", _item("1", "read them"))
    message = nagging.nag_message(todo, 2)
    assert message.startswith("Your todo list is still not finished")
    assert "mark_todo" in message and "write_todo" not in message


@pytest.mark.parametrize("nag_number", [1, 2])
def test_every_nag_ends_with_the_skill_of_the_marks(nag_number):
    message = nagging.nag_message(_todo("g", _item("1", "read them")), nag_number)
    assert message.endswith("The skill `todo_upkeep` tells how to mark the items.")


def test_open_items_are_the_unresolved_ones_in_plan_order():
    todo = _todo(
        "g",
        _item("1", "first", "done"),
        _item("2", "second"),
        _item("3", "third", "cancelled", "dropped"),
        _item("4", "fourth", "in_progress"),
    )
    assert [i["id"] for i in nagging.open_items(todo)] == ["2", "4"]


# ------------------------------------------------------------------ the citation round

HASH = "3f9a" + "0" * 56 + "c0de"


def _msg(role, content="", tool_name="", calls=()):
    import json

    from database import agent_runs

    return agent_runs.RunMessageRow(idx=0, role=role, content=content, tool_name=tool_name,
                                    tool_calls_json=json.dumps([{"name": n} for n in calls]))


def _search_result(path="/mail/kean-s/sent/budget-memo.eml"):
    import json

    return _msg("tool", tool_name="search_collections", content=json.dumps({
        "results": [{"file_hash": HASH, "collectionname": "enron", "path": path}]}))


def _thread(*extra):
    return [_msg("human", "What is in the budget memo?"),
            _msg("ai", calls=["search_collections"]), _search_result(), *extra]


@pytest.mark.parametrize("answer", [
    "The memo sets the budget [D1].",
    f"The memo {HASH} sets the budget.",
    f"The memo {HASH[:12]} sets the budget.",
    "The file budget-memo.eml sets the budget.",
    "See /mail/kean-s/sent/budget-memo.eml for the budget.",
])
def test_an_answer_that_names_a_document_with_no_citation_gets_the_round(answer):
    assert nagging.needs_citation_round(answer, _thread())


@pytest.mark.parametrize("answer", [
    "No document in the collection names a budget.",
    "",
    "The answer is 12. and nothing else.",
])
def test_an_answer_that_names_no_document_gets_no_round(answer):
    assert not nagging.needs_citation_round(answer, _thread())


def test_a_turn_with_a_citation_call_gets_no_round():
    thread = _thread(_msg("ai", calls=["cite_documents"]),
                     _msg("tool", tool_name="cite_documents", content="{}"))
    assert not nagging.needs_citation_round("The memo sets the budget [D1].", thread)


def test_a_turn_gets_one_citation_round_at_most():
    thread = _thread(_msg("ai", "The memo sets the budget [D1]."),
                     _msg("human", nagging.CITATION_NOTE))
    assert not nagging.needs_citation_round("The memo sets the budget [D1].", thread)


def test_a_tool_result_that_is_not_json_names_no_document():
    thread = [_msg("tool", tool_name="search_collections", content="not json")]
    assert not nagging.names_documents("A plain sentence.", thread)
