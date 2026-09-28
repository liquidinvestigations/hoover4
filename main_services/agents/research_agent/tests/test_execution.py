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
    budget = execution.safe_budget(names, request_tokens=0, window=0, reserve=8192)
    empty = [len(execution.empty_page_text(n).encode("utf-8")) for n in names]
    assert sum(budget.shares) <= SAFE_MODE_BATCH_BYTES
    assert all(share > e for share, e in zip(budget.shares, empty))
    assert len({share - e for share, e in zip(budget.shares, empty)}) == 1
    # The design's safe-mode case: 110,000 request tokens leave more than the batch bytes.
    assert execution.safe_budget(names, 110_000, 262_144, 8192).total == SAFE_MODE_BATCH_BYTES
    # A nearly full window cuts the batch.
    assert execution.safe_budget(names, 250_000, 262_144, 8192).total == 262_144 - 8192 - 250_000


class CharCounter:
    """A token counter that counts four bytes as one token."""

    def count(self, text: str) -> int:
        return len(text.encode("utf-8")) // 4


def _long_thread(prompt_tokens: int) -> list:
    """A thread of `prompt_tokens` billed tokens that holds four bytes of text per token,
    so its byte count is larger than a 262,144-token window."""
    return [
        HumanMessage(content="x" * (4 * prompt_tokens)),
        AIMessage(content="", usage_metadata={
            "input_tokens": prompt_tokens, "output_tokens": 0, "total_tokens": prompt_tokens,
        }),
    ]


@pytest.mark.parametrize("mode", ["bytes", "tokens"])
def test_a_thread_of_109000_tokens_still_gets_a_full_page(monkeypatch, mode):
    """A request of 109,000 tokens holds about 436,000 bytes. The budget subtracts the
    request in tokens from the window in tokens, so a single call still gets a full page."""
    monkeypatch.setenv("LLM_MODEL", "served-model")
    monkeypatch.setattr(execution.compaction, "context_window", lambda model: 262_144)
    monkeypatch.setattr(execution, "COMPLETION_RESERVE_TOKENS", 8192 if mode == "tokens" else None)
    monkeypatch.setattr(execution, "MAX_PAGE_TOKENS", 30_000 if mode == "tokens" else None)
    monkeypatch.setattr(execution, "TokenCounter", lambda *args: CharCounter())
    names = ["read_documents"]
    budget = execution.batch_budget([(name, {"file_hash": ["a"]}) for name in names],
                                    _long_thread(109_000))
    empty = len(execution.empty_page_text(names[0]).encode("utf-8"))
    assert budget.mode == mode and not budget.exhausted
    # The minimum page of a tool is its empty page plus one byte of content.
    assert budget.shares[0] >= empty + 1
    if mode == "bytes":
        assert budget.shares[0] == SAFE_MODE_BATCH_BYTES


def test_the_safe_budget_counts_the_bytes_after_the_last_billed_reply():
    """Text that the model has not been billed for yet counts one token per byte."""
    thread = _long_thread(100_000) + [HumanMessage(content="y" * 1000)]
    assert execution.request_tokens(thread) == 100_000 + 1000
    assert execution.request_tokens([HumanMessage(content="z" * 500)]) == 500


def test_the_token_budget_applies_the_allocation():
    messages = [HumanMessage(content="x" * 400), AIMessage(content="", usage_metadata={"input_tokens": 40000, "output_tokens": 0, "total_tokens": 40000})]
    budget = execution.token_budget(["a", "b"], messages, 262_144, CharCounter(), 8192, 30_000, fraction=0.6)
    empty = [CharCounter().count(execution.empty_page_text(n)) for n in ("a", "b")]
    assert budget.mode == "tokens" and not budget.exhausted
    content = (262_144 * 6 // 10 - 8192 - 8192 - 40_000 - sum(empty)) // 2
    assert list(budget.shares) == [e + min(content, 30_000) for e in empty]
    small = execution.token_budget(["a"] * 4, [AIMessage(content="", usage_metadata={"input_tokens": 50, "output_tokens": 0, "total_tokens": 50})], 166, CharCounter(), 20, None, fraction=0.6)
    assert small.exhausted


def test_read_weights_count_distinct_hashes_and_cap_at_ten():
    assert execution.read_weight("search_collections", {"file_hash": ["a"]}) == 0
    assert execution.read_weight("read_documents", {"file_hash": "a"}) == 1
    assert execution.read_weight("read_documents", {"file_hash": ["a", "a", "b"]}) == 2
    assert execution.read_weight("read_documents", {"file_hash": [str(n) for n in range(20)]}) == 10


def test_safe_read_gets_four_shares_beside_a_search():
    names = ["search_collections", "read_documents"]
    empty = [len(execution.empty_page_text(name).encode()) for name in names]
    budget = execution.safe_budget(names, 0, 0, 8192, weights=[0, 4])
    assert budget.shares == (SAFE_MODE_BATCH_BYTES,
                             empty[1] + 4 * (SAFE_MODE_BATCH_BYTES - empty[1]))
    limited = execution.safe_budget(names, 70_000, 100_000, 8192, weights=[0, 10], limit=80_000)
    assert sum(limited.shares) <= 2_000
    assert all(share >= size for share, size in zip(limited.shares, empty))


def test_token_read_gets_four_weighted_units():
    from agent_common.result_pages import allocate

    empty = [0, 0]
    assert allocate(0, empty, 100_000, 0, 8_000, [0, 4]) == [8_000, 32_000]
    assert allocate(80_000, empty, 100_000, 0, 8_000, [0, 4]) == [4_000, 16_000]


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


def test_the_measure_and_the_doc_refs_are_taken_out_of_the_artifact():
    other = EmbeddedResource(type="resource", resource=TextResourceContents(uri="hoover4://other", text="x"))
    measure = EmbeddedResource(type="resource", resource=TextResourceContents(uri=execution.CALL_MEASURE_URI, text='{"page_bytes": 3}'))
    refs = EmbeddedResource(type="resource", resource=TextResourceContents(
        uri=execution.DOC_REFS_URI, text='[{"file_hash": "' + "a" * 64 + '", "collection_dataset": "c_d"}]'))
    assert execution.split_resources([other, measure]) == ({"page_bytes": 3}, None, [other])
    assert execution.split_resources([measure, refs]) == (
        {"page_bytes": 3}, [{"file_hash": "a" * 64, "collection_dataset": "c_d"}], None)
    assert execution.split_resources(None) == (None, None, None)


def test_the_ordered_tools_are_the_plan_tools_and_the_todo_tools():
    """The worker runs `STATE_TOOLS` of `processing/tasks/P_agent/steps.py` in reply order.
    This list is the same set, so the stored kind says what the worker does."""
    assert execution.ORDERED_TOOLS == frozenset({
        "append_node", "append_child", "move_node", "edit_node", "remove_node", "read_plan",
        "write_todo", "edit_todo", "mark_todo", "read_todo",
    })
