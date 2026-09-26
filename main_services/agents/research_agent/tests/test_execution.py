"""The message rebuild, the batch result budget and the MCP client factory."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from mcp.types import EmbeddedResource, TextResourceContents
import pytest

from agent_common.result_pages import SAFE_MODE_BATCH_BYTES
from research_agent import execution
from research_agent.run_messages import RunMessage, to_langchain


# ------------------------------------------------------------------ the message rebuild


def test_a_stored_thread_with_a_tool_call_and_its_result_is_rebuilt():
    stored = [
        RunMessage(role="human", content="Who signed the lease?"),
        RunMessage(
            role="ai",
            content="",
            tool_calls=[{"id": "call-1", "name": "search_collections", "args": {"query": "lease"}}],
            usage={"input_tokens": 900, "output_tokens": 40, "total_tokens": 940},
        ),
        RunMessage(role="tool", content='{"hits": 3}', tool_call_id="call-1", name="search_collections"),
    ]
    rebuilt = to_langchain(stored)
    assert [type(m) for m in rebuilt] == [HumanMessage, AIMessage, ToolMessage]
    assert rebuilt[0].content == "Who signed the lease?"
    assert rebuilt[1].tool_calls[0]["id"] == "call-1"
    assert rebuilt[1].tool_calls[0]["name"] == "search_collections"
    assert rebuilt[1].tool_calls[0]["args"] == {"query": "lease"}
    # Stored usage lets compaction measure the thread before the first new model call.
    assert rebuilt[1].usage_metadata["input_tokens"] == 900
    assert rebuilt[1].usage_metadata["total_tokens"] == 940
    assert rebuilt[2].tool_call_id == "call-1"
    assert rebuilt[2].name == "search_collections"
    assert rebuilt[2].content == '{"hits": 3}'


def test_a_tool_row_without_its_call_id_is_refused():
    with pytest.raises(ValueError):
        to_langchain([RunMessage(role="tool", content="x", name="search_collections")])


def test_a_failed_tool_row_is_rebuilt_as_an_error_result():
    rebuilt = to_langchain([
        RunMessage(role="tool", content="x", tool_call_id="c", name="read_documents", status="error"),
        RunMessage(role="tool", content="y", tool_call_id="d", name="read_documents"),
    ])
    assert [m.status for m in rebuilt] == ["error", "success"]


# --------------------------------------------------------- the batch result budget


def test_the_safe_budget_reserves_every_empty_page_first():
    names = ["a", "table_search_cells", "c"]
    budget = execution.safe_budget(names, request_bytes=0, window=0, reserve=8192)
    empty = [len(execution.empty_page_text(n).encode("utf-8")) for n in names]
    assert sum(budget.shares) <= SAFE_MODE_BATCH_BYTES
    assert all(share > e for share, e in zip(budget.shares, empty))
    assert len({share - e for share, e in zip(budget.shares, empty)}) == 1
    # The design's safe-mode case: 110,000 request bytes leave more than the batch bytes.
    assert execution.safe_budget(names, 110_000, 262_144, 8192).total == SAFE_MODE_BATCH_BYTES
    # A nearly full window cuts the batch.
    assert execution.safe_budget(names, 250_000, 262_144, 8192).total == 262_144 - 8192 - 250_000


class CharCounter:
    """A token counter that counts four bytes as one token."""

    def count(self, text: str) -> int:
        return len(text.encode("utf-8")) // 4


def test_the_token_budget_applies_the_allocation():
    messages = [HumanMessage(content="x" * 400), AIMessage(content="", usage_metadata={"input_tokens": 40000, "output_tokens": 0, "total_tokens": 40000})]
    budget = execution.token_budget(["a", "b"], messages, 262_144, CharCounter(), 8192, 30_000, fraction=0.6)
    empty = [CharCounter().count(execution.empty_page_text(n)) for n in ("a", "b")]
    assert budget.mode == "tokens" and not budget.exhausted
    content = (262_144 * 6 // 10 - 8192 - 8192 - 40_000 - sum(empty)) // 2
    assert list(budget.shares) == [e + min(content, 30_000) for e in empty]
    small = execution.token_budget(["a"] * 4, [AIMessage(content="", usage_metadata={"input_tokens": 50, "output_tokens": 0, "total_tokens": 50})], 166, CharCounter(), 20, None, fraction=0.6)
    assert small.exhausted


def test_the_client_factory_sends_the_share_of_the_current_call():
    token = execution._PAGE_SHARE.set(7_000)
    try:
        client = execution.page_share_client(headers={"X-Hoover4-User": "alice"})
        assert client.headers[execution.PAGE_SHARE_HEADER] == "7000"
        assert client.headers["X-Hoover4-User"] == "alice"
    finally:
        execution._PAGE_SHARE.reset(token)
    assert execution.PAGE_SHARE_HEADER not in execution.page_share_client().headers


def test_the_client_factory_sends_the_idempotency_key_of_the_current_call():
    token = execution._IDEMPOTENCY_KEY.set("key-1")
    try:
        client = execution.page_share_client(headers={"X-Hoover4-User": "alice"})
        assert client.headers[execution.IDEMPOTENCY_HEADER] == "key-1"
    finally:
        execution._IDEMPOTENCY_KEY.reset(token)
    assert execution.IDEMPOTENCY_HEADER not in execution.page_share_client().headers


def test_the_measure_is_taken_out_of_the_artifact():
    other = EmbeddedResource(type="resource", resource=TextResourceContents(uri="hoover4://other", text="x"))
    measure = EmbeddedResource(type="resource", resource=TextResourceContents(uri=execution.CALL_MEASURE_URI, text='{"page_bytes": 3}'))
    assert execution.split_measure([other, measure]) == ({"page_bytes": 3}, [other])
    assert execution.split_measure([measure]) == ({"page_bytes": 3}, None)
    assert execution.split_measure(None) == (None, None)
