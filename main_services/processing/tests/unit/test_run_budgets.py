"""The sub-agent budget rules of `tasks/P_agent/run_budgets.py`."""

import pytest

from tasks.P_agent import run_budgets


def _calls(*counts):
    return [(f"call-{c}", [{"objective": f"{c}-{i}"} for i in range(n)])
            for c, n in enumerate(counts)]


@pytest.mark.parametrize("briefings, shares, refused", [
    (3, [1, 1, 1], 0),
    (5, [1, 0, 0, 0, 0], 0),
    (1, [5], 0),
    (7, [1, 0, 0, 0, 0], 2),
])
def test_the_hand_calculation_of_the_share_rule(briefings, shares, refused):
    decision = run_budgets.decide(_calls(briefings), depth=0, used=0, limit=6, own_share=0)
    assert [a.share for a in decision.accepted] == shares
    assert len(decision.refused) == refused
    # The turn can never make more runs than the limit.
    assert len(decision.accepted) + sum(shares) <= 6


def test_a_surplus_past_five_in_one_call_is_refused_by_name():
    decision = run_budgets.decide(_calls(7), depth=0, used=0, limit=300, own_share=0)
    assert len(decision.accepted) == 5
    assert [r["reason"] for r in decision.refused] == [run_budgets.TOO_MANY_BRIEFINGS] * 2
    assert [r["objective"] for r in decision.refused] == ["0-5", "0-6"]


def test_two_calls_share_one_allowance_in_call_order():
    decision = run_budgets.decide(_calls(2, 3), depth=0, used=2, limit=6, own_share=0)
    assert [a.briefing["objective"] for a in decision.accepted] == ["0-0", "0-1", "1-0", "1-1"]
    assert [a.share for a in decision.accepted] == [0, 0, 0, 0]
    assert [(r["tool_call_id"], r["reason"]) for r in decision.refused] == [
        ("call-1", run_budgets.BUDGET_SPENT)]


def test_a_depth_1_caller_spends_its_own_share_and_its_children_get_none():
    decision = run_budgets.decide(_calls(3), depth=1, used=99, limit=0, own_share=2)
    assert [a.share for a in decision.accepted] == [0, 0]
    assert decision.caller_share == 0
    assert len(decision.refused) == 1
    unchanged = run_budgets.decide(_calls(1), depth=1, used=0, limit=0, own_share=5)
    assert unchanged.caller_share == 4


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
    monkeypatch.delenv("AGENT_SUBAGENT_MAX_PER_TURN", raising=False)
    monkeypatch.setenv("AGENT_PLAN_RUN_BUDGET", "")
    assert run_budgets.limit_for(None) == 6
    assert run_budgets.limit_for("p") == 300
    monkeypatch.setenv("AGENT_SUBAGENT_MAX_PER_TURN", "9")
    assert run_budgets.turn_limit() == 9
