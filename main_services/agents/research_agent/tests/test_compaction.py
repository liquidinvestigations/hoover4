"""Context compaction, layer one.

The assertions here are about what the model is sent, never about what is stored: the
transformation is applied to a copy on its way to the provider, and the two tests that
check the input list is unchanged are the ones that keep it that way.
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from research_agent.compaction import (
    DEFAULT_COMPACTION_FRACTION,
    EVICTION_PLACEHOLDER,
    compact_messages,
    compaction_fraction,
    evict_tool_results,
    keep_recent,
    last_billed_tokens,
    threshold_tokens,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("AGENT_COMPACTION_FRACTION", raising=False)
    monkeypatch.delenv("AGENT_COMPACTION_KEEP_RECENT", raising=False)
    # No ClickHouse: the catalog lookup must be unreachable in a unit test, and every
    # test that needs a window passes one explicitly.
    monkeypatch.delenv("CLICKHOUSE_URL", raising=False)


def _call(name, args, result, *, tokens=None):
    """One tool round trip: the assistant asking, and the result coming back."""
    call_id = f"call_{name}_{abs(hash(result)) % 10000}"
    ai = AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )
    if tokens is not None:
        ai.usage_metadata = {
            "input_tokens": tokens[0],
            "output_tokens": tokens[1],
            "total_tokens": tokens[0] + tokens[1],
        }
    return [ai, ToolMessage(content=result, tool_call_id=call_id, name=name)]


def _conversation(n, *, tokens=None):
    messages = [SystemMessage(content="sys"), HumanMessage(content="the question")]
    for i in range(n):
        last = tokens if i == n - 1 else None
        messages += _call(f"tool_{i}", {"q": i}, f"result body {i} " * 50, tokens=last)
    return messages


# --------------------------------------------------------------- the trigger


def test_the_shipped_fraction_is_the_specified_sixty_percent():
    assert compaction_fraction() == DEFAULT_COMPACTION_FRACTION == 0.6


def test_the_fraction_is_configuration_not_a_constant(monkeypatch):
    monkeypatch.setenv("AGENT_COMPACTION_FRACTION", "0.05")
    assert compaction_fraction() == 0.05


@pytest.mark.parametrize("bad", ["", "0", "-1", "1.5", "sixty percent"])
def test_a_fraction_that_is_not_a_fraction_turns_compaction_off_rather_than_clamping(
    monkeypatch, bad
):
    # Clamping a misconfigured trigger into range makes a typo look like a feature.
    monkeypatch.setenv("AGENT_COMPACTION_FRACTION", bad)
    if bad == "":
        assert compaction_fraction() == DEFAULT_COMPACTION_FRACTION
    else:
        assert compaction_fraction() == 0.0
        assert threshold_tokens(262144) == 0


def test_an_unknown_window_never_produces_a_threshold():
    # 0 is the representation of "the provider never said". Dividing by it, or
    # substituting a default for it, is how a conversation silently loses its evidence.
    assert threshold_tokens(0) == 0
    assert threshold_tokens(-1) == 0


def test_the_threshold_is_the_fraction_of_the_stated_window():
    assert threshold_tokens(262144, 0.6) == 157286


def test_nothing_is_compacted_when_the_window_is_unknown():
    messages = _conversation(6, tokens=(200_000, 500))
    out, report = compact_messages(messages, model_id="m", window=0)
    assert report is None
    assert [m.content for m in out] == [m.content for m in messages]


# ------------------------------------------------- reading the billed numbers


def test_the_trigger_reads_the_providers_own_count_off_the_last_call():
    messages = _conversation(3, tokens=(170_000, 900))
    assert last_billed_tokens(messages) == 170_900


def test_a_run_with_no_reported_usage_is_unknown_not_zero_over_the_threshold():
    assert last_billed_tokens(_conversation(3)) == 0
    out, report = compact_messages(_conversation(3), model_id="m", window=262144)
    assert report is None
    assert out[-1].content.startswith("result body")


# ------------------------------------------------------------- what eviction does


def test_old_tool_results_go_and_their_calls_stay():
    messages = _conversation(6, tokens=(200_000, 100))
    out, report = compact_messages(messages, model_id="m", window=262144)

    assert report is not None
    assert report.evicted_count == 3
    assert report.kept_count == 3
    assert report.evicted == ["tool_0", "tool_1", "tool_2"]

    results = [m for m in out if isinstance(m, ToolMessage)]
    assert [m.content for m in results[:3]] == [EVICTION_PLACEHOLDER] * 3
    assert all(m.content.startswith("result body") for m in results[3:])

    # Every tool call the model made is still there, with its arguments, so the model
    # still sees that it searched and what for.
    calls = [c for m in out if isinstance(m, AIMessage) for c in (m.tool_calls or [])]
    assert [c["name"] for c in calls] == [f"tool_{i}" for i in range(6)]
    assert [c["args"] for c in calls] == [{"q": i} for i in range(6)]


def test_every_evicted_result_keeps_the_id_that_pairs_it_to_its_call():
    # An assistant message whose tool_calls have no matching tool result is rejected by
    # an OpenAI-shaped API outright, which is why a result is shortened and never dropped.
    messages = _conversation(6, tokens=(200_000, 100))
    out, _ = compact_messages(messages, model_id="m", window=262144)
    call_ids = {c["id"] for m in out if isinstance(m, AIMessage) for c in (m.tool_calls or [])}
    result_ids = {m.tool_call_id for m in out if isinstance(m, ToolMessage)}
    assert call_ids == result_ids
    assert len(out) == len(messages)


def test_the_users_own_messages_are_never_touched():
    messages = _conversation(6, tokens=(200_000, 100))
    out, _ = compact_messages(messages, model_id="m", window=262144)
    assert [m.content for m in out if isinstance(m, HumanMessage)] == ["the question"]
    assert [m.content for m in out if isinstance(m, SystemMessage)] == ["sys"]


def test_the_list_that_was_passed_in_is_not_modified():
    # The caller's list is the graph state, and the graph state is what the transcript is
    # written from. A user scrolling back must see what they saw before.
    messages = _conversation(6, tokens=(200_000, 100))
    before = [m.content for m in messages]
    compact_messages(messages, model_id="m", window=262144)
    assert [m.content for m in messages] == before
    assert EVICTION_PLACEHOLDER not in before


def test_the_recent_results_kept_is_configuration(monkeypatch):
    monkeypatch.setenv("AGENT_COMPACTION_KEEP_RECENT", "1")
    assert keep_recent() == 1
    _, report = compact_messages(
        _conversation(6, tokens=(200_000, 100)), model_id="m", window=262144
    )
    assert report.evicted_count == 5
    assert report.kept_count == 1


def test_a_second_compaction_does_not_count_the_same_kilobytes_twice():
    messages = _conversation(6, tokens=(200_000, 100))
    once, first = compact_messages(messages, model_id="m", window=262144)
    twice, second = evict_tool_results(once, keep=3)
    assert first.evicted_count == 3
    assert second.evicted_count == 0
    assert [m.content for m in twice] == [m.content for m in once]


def test_the_record_carries_what_it_takes_to_debug_a_compaction():
    messages = _conversation(6, tokens=(200_000, 100))
    _, report = compact_messages(messages, model_id="qwen", window=262144)
    assert report.compaction_id
    assert report.model_id == "qwen"
    assert report.context_window == 262144
    assert report.threshold_tokens == 157286
    assert report.tokens_before == 200_100
    # Filled in one model call later, once the shortened list has been billed.
    assert report.tokens_after == 0
    assert report.chars_before > report.chars_after > 0
    assert report.chars_freed > 0
    assert report.messages_before == report.messages_after == len(messages)


def test_a_turn_under_the_threshold_is_left_completely_alone():
    # This is the ordinary case on current traffic: the widest measured turn on this
    # stack peaks at about a tenth of the window.
    messages = _conversation(16, tokens=(27_381, 0))
    out, report = compact_messages(messages, model_id="m", window=262144)
    assert report is None
    assert not any(m.content == EVICTION_PLACEHOLDER for m in out)


def test_over_the_threshold_with_nothing_evictable_changes_nothing():
    # Layer two is what answers this case, and it is not built. Reporting a compaction
    # that freed nothing would put a row in the trail describing an event that did not
    # happen.
    messages = _conversation(2, tokens=(200_000, 100))
    out, report = compact_messages(messages, model_id="m", window=262144)
    assert report is None
    assert [m.content for m in out] == [m.content for m in messages]
