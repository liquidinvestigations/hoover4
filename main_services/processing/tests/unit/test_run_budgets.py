"""The sub-agent budget rules of `tasks/P_agent/run_budgets.py`."""

import pytest

from tasks.P_agent import run_budgets


def _calls(*counts):
    return [(f"call-{c}", [{"objective": f"{c}-{i}"} for i in range(n)])
            for c, n in enumerate(counts)]


@pytest.mark.parametrize("briefings, accepted, refused", [
    (3, 3, 0),
    (5, 5, 0),
    (1, 1, 0),
    (7, 6, 1),
])
def test_the_budget_accepts_calls_in_order(briefings, accepted, refused):
    decision = run_budgets.decide(_calls(briefings), depth=0, used=0, limit=6, own_share=0)
    assert len(decision.accepted) == accepted
    assert all(a.share == 0 for a in decision.accepted)
    assert len(decision.refused) == refused
    assert len(decision.accepted) <= 6


def test_one_call_has_no_extra_briefing_limit():
    decision = run_budgets.decide(_calls(7), depth=0, used=0, limit=300, own_share=0)
    assert len(decision.accepted) == 7
    assert decision.refused == []


def test_two_calls_share_one_allowance_in_call_order():
    decision = run_budgets.decide(_calls(2, 3), depth=0, used=2, limit=6, own_share=0)
    assert [a.briefing["objective"] for a in decision.accepted] == ["0-0", "0-1", "1-0", "1-1"]
    assert [a.share for a in decision.accepted] == [0, 0, 0, 0]
    assert [(r["tool_call_id"], r["reason"]) for r in decision.refused] == [
        ("call-1", run_budgets.BUDGET_SPENT)]


def test_a_spent_turn_accepts_nothing():
    decision = run_budgets.decide(_calls(2), depth=0, used=6, limit=6, own_share=0)
    assert decision.accepted == [] and len(decision.refused) == 2


def test_the_same_input_gives_the_same_decision():
    """A retry counts without its own batch, so it passes the same `used` and gets the same
    children and shares."""
    first = run_budgets.decide(_calls(3, 2), depth=0, used=1, limit=6, own_share=0)
    second = run_budgets.decide(_calls(3, 2), depth=0, used=1, limit=6, own_share=0)
    assert first == second


def test_the_limits_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("AGENT_PLAN_RUN_BUDGET", "")
    assert run_budgets.limit_for(None) == 5
    assert run_budgets.limit_for("p") == 5
