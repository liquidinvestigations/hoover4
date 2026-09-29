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


def test_the_budget_reserves_every_empty_page_and_divides_the_rest_equally():
    names = ["a", "table_search_cells", "read_documents"]
    budget = execution.batch_budget(names)
    empty = [len(execution.empty_page_text(n).encode("utf-8")) for n in names]
    assert budget.total == sum(budget.shares) <= SAFE_MODE_BATCH_BYTES
    assert all(share > e for share, e in zip(budget.shares, empty))
    assert len({share - e for share, e in zip(budget.shares, empty)}) == 1
    assert SAFE_MODE_BATCH_BYTES - budget.total < len(names)


def test_one_call_gets_the_whole_batch_target():
    assert execution.batch_budget(["read_documents"]).shares == (SAFE_MODE_BATCH_BYTES,)


def test_a_document_count_gives_no_extra_share():
    """A call that reads ten documents gets the same share as a search beside it. The page
    broker divides the call's share among its documents."""
    budget = execution.batch_budget(["search_collections", "read_documents"])
    empty = [len(execution.empty_page_text(n).encode()) for n in
             ("search_collections", "read_documents")]
    assert budget.shares[0] - empty[0] == budget.shares[1] - empty[1]


def test_the_budget_does_not_read_the_conversation():
    """The shares depend on the tool names only, so a long thread refuses no call."""
    assert "messages" not in execution.batch_budget.__code__.co_varnames
    assert not hasattr(execution, "request_tokens")


def test_empty_pages_above_the_target_keep_every_empty_page():
    """More calls than the target holds: each call keeps its empty page, and no call is
    refused."""
    names = ["search_collections"] * 200
    empty = len(execution.empty_page_text(names[0]).encode())
    budget = execution.batch_budget(names)
    assert budget.shares == (empty,) * 200
    assert budget.total > SAFE_MODE_BATCH_BYTES


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
        "write_plan", "read_plan", "write_todo", "edit_todo", "mark_todo", "read_todo",
    })


def test_every_tool_of_the_browser_server_is_a_browser_tool():
    """The worker's `steps.is_browser_tool` has the same rule, and runs these calls of one
    reply in call order. The rule covers the tools that `BROWSER_EXPOSED_TOOLS` can add."""
    from agent_common.tool_packs import PACKS

    for name in PACKS["browser"] | {"read_page", "browser_take_screenshot",
                                     "browser_wait_for", "browser_navigate_back"}:
        assert execution.is_browser_tool(name), name
    for name in ("search_collections", "web_search", "read_documents", "read_more"):
        assert not execution.is_browser_tool(name), name
