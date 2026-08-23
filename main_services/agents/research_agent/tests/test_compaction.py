"""Context compaction, both layers.

The assertions here are about what the model is sent, never about what is stored: the
transformation is applied to a copy on its way to the provider, and the two tests that
check the input list is unchanged are the ones that keep it that way.

The layer-two tests pass their own summariser. A test that reached a real model would be
testing the model, and the property that matters -- that the never-summarised set survives
whatever the summariser does -- is only demonstrable with a summariser that does its
worst.
"""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from research_agent.compaction import (
    DEFAULT_COMPACTION_FRACTION,
    EVICTION_PLACEHOLDER,
    MIN_EVICTABLE_CHARS,
    citation_index,
    compact_messages,
    compaction_fraction,
    evict_tool_results,
    issued_citations,
    keep_recent,
    last_billed_tokens,
    protected_indexes,
    summarise_messages,
    threshold_tokens,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("AGENT_COMPACTION_FRACTION", raising=False)
    monkeypatch.delenv("AGENT_COMPACTION_KEEP_RECENT", raising=False)
    monkeypatch.delenv("AGENT_COMPACTION_KEEP_RECENT_MESSAGES", raising=False)
    # No LLM either: layer two must never reach a real model from a unit test, and every
    # test that exercises it passes its own summariser.
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL_COMPACTION", raising=False)
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


def test_a_result_shorter_than_the_placeholder_is_left_alone():
    # Replacing it makes the context bigger, which is the opposite of the point. Found on
    # the first driven run: a one-line result grew by 36 characters on being evicted.
    messages = [SystemMessage(content="sys"), HumanMessage(content="q")]
    messages += _call("tiny", {}, "ok")
    messages += _call("tiny_too", {}, "also ok")
    for i in range(4):
        messages += _call(f"big_{i}", {}, "x" * (MIN_EVICTABLE_CHARS + 1000))
    messages[-2].usage_metadata = {
        "input_tokens": 200_000, "output_tokens": 0, "total_tokens": 200_000
    }

    out, report = compact_messages(messages, model_id="m", window=262144)
    assert report.evicted == ["big_0"]
    assert report.chars_after < report.chars_before
    tiny = [m for m in out if isinstance(m, ToolMessage) and m.name.startswith("tiny")]
    assert [m.content for m in tiny] == ["ok", "also ok"]


def test_over_the_threshold_with_neither_layer_able_to_help_changes_nothing():
    # Nothing to evict, and a summariser that gives nothing back. Reporting a compaction
    # that freed nothing would put a row in the trail describing an event that did not
    # happen.
    messages = _conversation(2, tokens=(200_000, 100))
    out, report = compact_messages(
        messages, model_id="m", window=262144, summariser=lambda _: ""
    )
    assert report is None
    assert [m.content for m in out] == [m.content for m in messages]


# ------------------------------------------------- layer two: what is never summarised


def _cite_result(pairs):
    """A `cite_documents` result allocating one handle per (collection, hash) pair."""
    return json.dumps(
        {
            "success": True,
            "citations": [
                {
                    "handle": f"[D{i + 1}]",
                    "collectionname": collection,
                    "file_hash": file_hash,
                    "path": f"/{collection}/doc{i + 1}.txt",
                    "quote": "a quoted sentence",
                    "quote_verified": True,
                }
                for i, (collection, file_hash) in enumerate(pairs)
            ],
        }
    )


def _cited_conversation():
    """A turn that has searched, read, cited, and written prose carrying the handles."""
    messages = [SystemMessage(content="sys"), HumanMessage(content="the question")]
    for i in range(6):
        messages += _call(f"search_{i}", {"q": i}, f"long result {i} " * 200)
    messages += _call("write_todo", {"items": ["read", "cite"]}, "todo saved: read, cite")
    messages += _call(
        "cite_documents", {}, _cite_result([("testdata", "aa11"), ("testdata", "bb22")])
    )
    messages.append(AIMessage(content="The answer draws on [D1] and on [D2]."))
    for i in range(3):
        messages += _call(f"after_{i}", {"q": i}, f"later result {i} " * 200)
    return messages


def _summariser_that_does_its_worst(_prompt):
    """A summariser that would destroy every citation if it were trusted to keep them."""
    return (
        "## Work completed so far\nI forgot all of it.\n"
        "## Facts established, quoted verbatim\nnone\n"
        "## What remains\nunknown\n"
    )


def test_the_user_the_todo_and_every_citation_are_protected_in_code():
    messages = _cited_conversation()
    protected = protected_indexes(messages, keep_recent_messages=0)
    kept = [messages[i] for i in protected]

    assert any(isinstance(m, HumanMessage) and m.content == "the question" for m in kept)
    assert any(isinstance(m, ToolMessage) and m.name == "write_todo" for m in kept)
    assert any(isinstance(m, ToolMessage) and m.name == "cite_documents" for m in kept)
    assert any("[D1]" in str(m.content) for m in kept)
    # And nothing else got swept in with them: the searches are summarisable.
    assert not any(
        isinstance(m, ToolMessage) and m.name.startswith("search_") for m in kept
    )


def test_a_protected_result_keeps_the_call_that_asked_for_it():
    # An assistant message whose tool_calls have no matching result is rejected by the
    # provider outright, so protection has to travel in whole call-and-result groups.
    messages = _cited_conversation()
    protected = protected_indexes(messages, keep_recent_messages=0)
    cite_index = next(
        i for i, m in enumerate(messages)
        if isinstance(m, ToolMessage) and m.name == "cite_documents"
    )
    assert cite_index in protected
    assert cite_index - 1 in protected


def test_every_citation_survives_a_summariser_that_drops_all_of_them():
    # The rule the whole layer exists to keep. The summariser above writes a handoff with
    # no handle in it at all, and every handle still resolves afterwards because the
    # messages carrying them were never handed to it.
    messages = _cited_conversation()
    before = issued_citations(messages)
    assert before == ["[D1]", "[D2]"]

    out, report = summarise_messages(
        messages,
        model_id="m",
        keep_messages=0,
        summariser=_summariser_that_does_its_worst,
    )

    assert report.summarised_count > 0
    assert issued_citations(out) == before
    assert report.handles == before
    # Both halves of the mapping: the result that says what [D1] is, and the prose using it.
    cite = next(m for m in out if isinstance(m, ToolMessage) and m.name == "cite_documents")
    assert "aa11" in cite.content and "bb22" in cite.content
    assert any(isinstance(m, AIMessage) and "[D1]" in str(m.content) for m in out)


def test_the_handoff_names_the_documents_without_asking_the_model_for_them():
    messages = _cited_conversation()
    out, report = summarise_messages(
        messages,
        model_id="m",
        keep_messages=0,
        summariser=_summariser_that_does_its_worst,
    )
    handoff = next(m for m in out if "Context handoff" in str(m.content))
    # A user turn. A system message anywhere but the first position is a 400 from this
    # provider -- `System message must be at the beginning.` -- and the client retries it,
    # so the turn hangs instead of failing.
    assert isinstance(handoff, HumanMessage)
    assert "[D1] testdata/aa11" in handoff.content
    assert "[D2] testdata/bb22" in handoff.content
    assert "## What was replaced" in handoff.content
    assert "## Work completed so far" in handoff.content
    assert "## What remains" in handoff.content
    assert report.summary == handoff.content


def test_the_citation_index_is_read_from_the_tool_result():
    assert citation_index(_cited_conversation()) == [
        "[D1] testdata/aa11  /testdata/doc1.txt",
        "[D2] testdata/bb22  /testdata/doc2.txt",
    ]


def test_summarisation_never_edits_or_mutates_the_input_list():
    messages = _cited_conversation()
    snapshot = [(type(m), str(m.content)) for m in messages]
    summarise_messages(
        messages, model_id="m", keep_messages=0,
        summariser=_summariser_that_does_its_worst,
    )
    assert [(type(m), str(m.content)) for m in messages] == snapshot


def test_a_summariser_that_says_nothing_leaves_the_list_alone():
    # No summary means no summarisation. Compaction exists to save a turn and must never
    # be the thing that ends one.
    messages = _cited_conversation()
    out, report = summarise_messages(
        messages, model_id="m", keep_messages=0, summariser=lambda _: ""
    )
    assert report.summarised_count == 0
    assert out == messages


def test_a_handoff_bigger_than_what_it_replaces_is_refused():
    # Layer one shipped a defect of exactly this shape: it replaced a 91-character result
    # with a 127-character placeholder and grew the context it was shrinking.
    messages = _cited_conversation()
    out, report = summarise_messages(
        messages, model_id="m", keep_messages=0, summariser=lambda _: "x" * 500_000
    )
    assert report.summarised_count == 0
    assert out == messages


def test_the_summarised_list_still_pairs_every_call_with_its_result():
    messages = _cited_conversation()
    out, _ = summarise_messages(
        messages, model_id="m", keep_messages=0,
        summariser=_summariser_that_does_its_worst,
    )
    answered = {m.tool_call_id for m in out if isinstance(m, ToolMessage)}
    asked = {
        c["id"]
        for m in out
        if isinstance(m, AIMessage)
        for c in (m.tool_calls or [])
    }
    assert asked == answered


def test_the_cite_documents_result_is_not_evictable_either():
    # Both layers honour the same never-compacted set. Evicting the handle table while
    # the model's own prose still says [D1] is the same correctness bug by another route.
    messages = _cited_conversation()
    out, report = evict_tool_results(messages, keep=0)
    assert "cite_documents" not in report.evicted
    assert "write_todo" not in report.evicted
    cite = next(m for m in out if isinstance(m, ToolMessage) and m.name == "cite_documents")
    assert "aa11" in cite.content


def test_eviction_runs_first_and_summarisation_only_on_what_it_leaves(monkeypatch):
    # The two layers in order: eviction is most of the benefit for no model call, so it
    # goes first and layer two only sees what it could not reclaim. Keeping eight recent
    # results is what leaves it not enough here -- on the shipped setting of three, this
    # turn is comfortably under after layer one and layer two never runs.
    monkeypatch.setenv("AGENT_COMPACTION_KEEP_RECENT", "8")
    seen = {}

    def summariser(prompt):
        seen["prompt"] = prompt
        return _summariser_that_does_its_worst(prompt)

    messages = _cited_conversation()
    messages[-2].usage_metadata = {
        "input_tokens": 250_000, "output_tokens": 0, "total_tokens": 250_000
    }
    out, report = compact_messages(
        messages, model_id="m", window=262144, summariser=summariser
    )

    assert report.layer == "summarisation"
    assert report.evicted_count > 0
    assert report.summarised_count > 0
    # What layer two was handed had already been evicted, so the summariser never saw the
    # kilobytes eviction had taken out.
    assert EVICTION_PLACEHOLDER in seen["prompt"]
    assert issued_citations(out) == ["[D1]", "[D2]"]
    assert report.chars_after < report.chars_before
