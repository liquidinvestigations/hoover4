"""The execution node, the run events, the message rebuild and the graph `_create_graph` builds."""

import asyncio
import hashlib
import json
from typing import Any, List

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool

from research_agent import agent as agent_module
from research_agent.execution import make_execution_node
from research_agent.run_messages import RunMessage, to_langchain
from research_agent.tool_catalogue import build_snapshot


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


# ----------------------------------------------------------------------- stub tools


def dict_tool(name: str, schema: dict, seen: List[Any], fail: bool = False, delay: float = 0.0):
    """A tool shaped as the MCP adapter builds one: a dict `args_schema` and a coroutine."""

    async def call(**arguments):
        seen.append((name, "start", arguments))
        if delay:
            await asyncio.sleep(delay)
        seen.append((name, "end", arguments))
        if fail:
            raise RuntimeError(f"{name} failed on purpose")
        return json.dumps({"tool": name, "ok": True})

    return StructuredTool(
        name=name,
        description=f"{name.replace('_', ' ')} stub.\nSecond line.",
        args_schema=schema,
        coroutine=call,
    )


LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "collectionname": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["query"],
}
EMPTY_SCHEMA = {"type": "object", "properties": {}}


def call_state(calls, bound=()):
    return {
        "messages": [HumanMessage(content="q"), AIMessage(content="", tool_calls=calls)],
        "bound_names": tuple(bound),
        "thread_offset": 0,
    }


# -------------------------------------------------------------- the execution node


async def test_plan_mutations_run_one_after_the_other_in_call_order():
    seen: List[Any] = []
    tools = [
        dict_tool("append_node", EMPTY_SCHEMA, seen, delay=0.02),
        dict_tool("edit_node", EMPTY_SCHEMA, seen, delay=0.01),
        dict_tool("read_plan", EMPTY_SCHEMA, seen, delay=0.03),
    ]
    snapshot = build_snapshot(tools, {"append_node", "edit_node", "read_plan"}, "planner")
    node = make_execution_node(snapshot, emit_events=False)
    calls = [
        {"id": "a", "name": "append_node", "args": {}},
        {"id": "b", "name": "read_plan", "args": {}},
        {"id": "c", "name": "edit_node", "args": {}},
    ]
    out = await node(call_state(calls), {})
    assert [m.tool_call_id for m in out["messages"]] == ["a", "b", "c"]
    mutation_steps = [(n, step) for n, step, _ in seen if n != "read_plan"]
    assert mutation_steps == [
        ("append_node", "start"), ("append_node", "end"),
        ("edit_node", "start"), ("edit_node", "end"),
    ]
    # The other call ran beside the mutations, not after them.
    assert seen.index(("read_plan", "start", {})) < seen.index(("edit_node", "start", {}))


async def test_a_name_outside_the_packs_is_refused_with_tool_unavailable():
    seen: List[Any] = []
    snapshot = build_snapshot(
        [dict_tool("web_search", EMPTY_SCHEMA, seen), dict_tool("search_collections", LIST_SCHEMA, seen)],
        {"search_collections"},
        "chat",
    )
    assert "web_search" not in snapshot.tools_by_name
    node = make_execution_node(snapshot, emit_events=False)
    out = await node(call_state([{"id": "w", "name": "web_search", "args": {}}]), {})
    message = out["messages"][0]
    assert message.status == "error"
    assert json.loads(message.content)["error"] == "tool_unavailable"
    assert seen == []


async def test_a_deferred_tool_runs_only_after_a_catalogue_match_binds_it():
    seen: List[Any] = []
    metadata = dict_tool("doc_metadata", EMPTY_SCHEMA, seen)
    snapshot = build_snapshot([metadata], {"doc_metadata", "search_agent_tools"}, "chat")
    assert "doc_metadata" in snapshot.deferred_names
    node = make_execution_node(snapshot, emit_events=False)

    refused = await node(call_state([{"id": "1", "name": "doc_metadata", "args": {}}]), {})
    assert json.loads(refused["messages"][0].content)["error"] == "tool_unavailable"

    searched = await node(
        call_state([{"id": "2", "name": "search_agent_tools", "args": {"query": "doc metadata"}}]),
        {},
    )
    assert searched["bound_names"] == ("doc_metadata",)

    ran = await node(
        call_state([{"id": "3", "name": "doc_metadata", "args": {}}], searched["bound_names"]),
        {},
    )
    assert ran["messages"][0].status == "success"
    assert seen and seen[0][0] == "doc_metadata"


async def test_arguments_that_do_not_match_the_schema_are_refused_before_the_call():
    seen: List[Any] = []
    snapshot = build_snapshot([dict_tool("search_collections", LIST_SCHEMA, seen)], {"search_collections"}, "chat")
    node = make_execution_node(snapshot, emit_events=False)
    out = await node(call_state([{"id": "x", "name": "search_collections", "args": {}}]), {})
    assert json.loads(out["messages"][0].content)["error"] == "invalid_arguments"
    assert seen == []


# ----------------------------------------------- the graph that `_create_graph` builds


class ScriptedModel(BaseChatModel):
    """A chat model that returns scripted replies and records the tools of each call."""

    replies: List[Any]
    bound_log: List[Any]

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        self.bound_log.append(sorted(t.name for t in tools))
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.replies.pop(0))])


class FakeClient:
    tools: List[Any] = []

    def __init__(self, servers):
        self.servers = servers

    async def get_tools(self):
        return list(FakeClient.tools)


@pytest.fixture
def scripted(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.setenv("LLM_STREAMING", "false")
    monkeypatch.setattr(agent_module.llm_events, "record_llm_call", lambda *a, **k: None)
    model = ScriptedModel(replies=[], bound_log=[])
    monkeypatch.setattr(agent_module, "ThinkingChatOpenAI", lambda *a, **k: model)
    monkeypatch.setattr(agent_module, "MultiServerMCPClient", FakeClient)
    return model


async def run_events(scripted_model, tools, replies, **stream_kwargs):
    FakeClient.tools = tools
    scripted_model.replies.extend(replies)
    agent = agent_module.MCPGatewayAgent(["http://stub/mcp"], "test", "", "stub-model", "full_research")
    events = [
        event
        async for event in agent.stream(
            query=None,
            session_id="s1",
            username="alice",
            allowed_collections=["testdata"],
            thread=[HumanMessage(content="Find the lease.")],
            **stream_kwargs,
        )
    ]
    return agent, events


async def test_a_graph_from_create_graph_sends_decoded_arguments_to_its_tools(scripted):
    seen: List[Any] = []
    tools = [dict_tool("search_collections", LIST_SCHEMA, seen)]
    replies = [
        AIMessage(content="", tool_calls=[{
            "id": "c1", "name": "search_collections",
            "args": {"query": "lease", "collectionname": '["a", "b"]'},
        }]),
        AIMessage(content="The lease is in a."),
    ]
    await run_events(scripted, tools, replies, run_id="run-1")
    starts = [args for name, step, args in seen if step == "start"]
    assert starts == [{"query": "lease", "collectionname": ["a", "b"]}]


async def test_a_run_streams_model_turns_and_a_raised_call_as_an_error_result(scripted):
    seen: List[Any] = []
    tools = [
        dict_tool("search_collections", LIST_SCHEMA, seen),
        dict_tool("read_documents", EMPTY_SCHEMA, seen, fail=True),
    ]
    replies = [
        AIMessage(content="", tool_calls=[
            {"id": "c1", "name": "search_collections", "args": {"query": "lease"}},
            {"id": "c2", "name": "read_documents", "args": {}},
            {"id": "c3", "name": "browser_click", "args": {}},
        ]),
        AIMessage(content="Done."),
    ]
    agent, events = await run_events(scripted, tools, replies, run_id="run-2")
    types = [e["type"] for e in events]
    assert "start_tool" not in types and "end_tool" not in types
    assert types.count("model_turn") == 2
    first_turn = next(e for e in events if e["type"] == "model_turn")["content"]
    assert first_turn["index"] == 1
    assert [c["id"] for c in first_turn["tool_calls"]] == ["c1", "c2", "c3"]

    results = {e["content"]["tool_call_id"]: e["content"] for e in events if e["type"] == "tool_result"}
    starts = {e["content"]["tool_call_id"] for e in events if e["type"] == "tool_start"}
    assert starts == {"c1", "c2", "c3"}
    assert results["c1"]["status"] == "ok"
    assert results["c2"]["status"] == "error"
    assert "failed on purpose" in results["c2"]["content"]
    assert results["c3"]["status"] == "error"
    assert json.loads(results["c3"]["content"])["error"] == "tool_unavailable"
    assert results["c1"]["index"] == 2 and results["c3"]["index"] == 4
    assert events[-1]["type"] == "end"
    # The run's graph is released when its stream ends.
    assert not [k for k in agent._graphs if "run-2" in k]


async def test_the_model_binds_a_deferred_tool_only_after_a_catalogue_match(scripted):
    seen: List[Any] = []
    tools = [
        dict_tool("search_collections", LIST_SCHEMA, seen),
        dict_tool("doc_metadata", EMPTY_SCHEMA, seen),
    ]
    replies = [
        AIMessage(content="", tool_calls=[
            {"id": "c1", "name": "search_agent_tools", "args": {"query": "doc metadata"}},
        ]),
        AIMessage(content="", tool_calls=[{"id": "c2", "name": "doc_metadata", "args": {}}]),
        AIMessage(content="Done."),
    ]
    _, events = await run_events(scripted, tools, replies, run_id="run-3")
    assert "doc_metadata" not in scripted.bound_log[0]
    assert "doc_metadata" in scripted.bound_log[1]
    results = {e["content"]["tool_call_id"]: e["content"] for e in events if e["type"] == "tool_result"}
    assert results["c2"]["status"] == "ok"


async def test_a_narrowed_pack_refuses_its_tools_and_hides_them_from_the_catalogue(scripted, monkeypatch):
    monkeypatch.setenv("AGENT_PACKS_CHAT", "collections,catalogue")
    seen: List[Any] = []
    tools = [dict_tool("search_collections", LIST_SCHEMA, seen), dict_tool("read_todo", EMPTY_SCHEMA, seen)]
    replies = [
        AIMessage(content="", tool_calls=[
            {"id": "c1", "name": "read_todo", "args": {}},
            {"id": "c2", "name": "search_agent_tools", "args": {"query": "read todo"}},
        ]),
        AIMessage(content="Done."),
    ]
    _, events = await run_events(scripted, tools, replies, run_id="run-4")
    assert "read_todo" not in scripted.bound_log[0]
    results = {e["content"]["tool_call_id"]: e["content"] for e in events if e["type"] == "tool_result"}
    assert json.loads(results["c1"]["content"])["error"] == "tool_unavailable"
    assert json.loads(results["c2"]["content"])["matches"] == []
    assert seen == []


async def test_a_run_that_may_not_delegate_binds_no_run_subagent(scripted):
    tools = [dict_tool("search_collections", LIST_SCHEMA, [])]
    await run_events(scripted, tools, [AIMessage(content="Done.")], run_id="run-5", can_delegate=False)
    assert "run_subagent" not in scripted.bound_log[0]
    await run_events(scripted, tools, [AIMessage(content="Done.")], run_id="run-6")
    assert "run_subagent" in scripted.bound_log[-1]


async def test_a_continued_run_has_only_the_tool_turns_left(scripted):
    tools = [dict_tool("search_collections", LIST_SCHEMA, [])]
    replies = [
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "search_collections", "args": {"query": "a"}}]),
        AIMessage(content="Forced answer."),
    ]
    _, events = await run_events(
        scripted, tools, replies, run_id="run-7", tool_turns_used=agent_module.MAX_TOOL_TURNS
    )
    # No turns left: the first tool call goes to the forced answer and never runs.
    assert not [e for e in events if e["type"] == "tool_start"]
    assert events[-1]["type"] == "end"


# --------------------------------------------------------- the stop at run_subagent


def _briefing(objective):
    return {"objective": objective, "known": "", "bring_back": "the documents"}


async def test_a_model_turn_with_two_run_subagent_calls_is_one_delegation(scripted):
    seen: List[Any] = []
    tools = [dict_tool("search_collections", LIST_SCHEMA, seen)]
    replies = [AIMessage(content="", tool_calls=[
        {"id": "d1", "name": "run_subagent", "args": {"tasks": [_briefing("A"), _briefing("B")]}},
        {"id": "c1", "name": "search_collections", "args": {"query": "lease"}},
        {"id": "d2", "name": "run_subagent", "args": {"tasks": json.dumps([_briefing("C")])}},
    ])]
    _, events = await run_events(scripted, tools, replies, run_id="run-d1")
    types = [e["type"] for e in events]
    # One model call: the run ends at the delegation and asks the model nothing more.
    assert types.count("model_turn") == 1 and scripted.replies == []
    results = [e["content"] for e in events if e["type"] == "tool_result"]
    assert [r["tool_call_id"] for r in results] == ["c1"]
    assert [a for n, step, a in seen if step == "start"] == [{"query": "lease"}]
    delegates = [e["content"] for e in events if e["type"] == "delegate"]
    assert [d["tool_call_id"] for d in delegates] == ["d1", "d2"]
    assert [[b["objective"] for b in d["briefings"]] for d in delegates] == [["A", "B"], ["C"]]
    # The continuation writes the two results after the one result of this turn.
    assert [d["index"] for d in delegates] == [3, 4]
    starts = [e["content"]["tool_call_id"] for e in events if e["type"] == "tool_start"]
    assert starts[-2:] == ["d1", "d2"]
    assert types.index("delegate") > max(i for i, t in enumerate(types) if t == "tool_start")
    assert events[-1]["type"] == "end" and events[-1]["content"] == ""


async def test_run_subagent_with_unreadable_briefings_gets_an_error_and_does_not_stop(scripted):
    replies = [
        AIMessage(content="", tool_calls=[
            {"id": "d1", "name": "run_subagent", "args": {"tasks": "not json"}}]),
        AIMessage(content="Done."),
    ]
    _, events = await run_events(scripted, [dict_tool("search_collections", LIST_SCHEMA, [])],
                                 replies, run_id="run-d2")
    assert not [e for e in events if e["type"] == "delegate"]
    result = next(e["content"] for e in events if e["type"] == "tool_result")
    assert json.loads(result["content"])["error"] == "invalid_arguments"
    assert [e["type"] for e in events].count("model_turn") == 2


async def test_a_depth_2_run_gets_tool_unavailable_for_run_subagent(scripted):
    """`depth-limit`: a graph with `can_delegate` false binds no `run_subagent`, so the call
    gets the execution node's `tool_unavailable` result and no `delegate` event."""
    replies = [
        AIMessage(content="", tool_calls=[
            {"id": "d1", "name": "run_subagent", "args": {"tasks": [_briefing("A")]}}]),
        AIMessage(content="Done."),
    ]
    _, events = await run_events(scripted, [dict_tool("search_collections", LIST_SCHEMA, [])],
                                 replies, run_id="run-d3", kind="subagent", can_delegate=False)
    assert not [e for e in events if e["type"] == "delegate"]
    result = next(e["content"] for e in events if e["type"] == "tool_result")
    assert json.loads(result["content"])["error"] == "tool_unavailable"


async def test_a_retry_runs_the_unanswered_call_before_the_next_model_call(scripted):
    seen: List[Any] = []
    tools = [dict_tool("search_collections", LIST_SCHEMA, seen)]
    FakeClient.tools = tools
    scripted.replies.extend([AIMessage(content="Done.")])
    agent = agent_module.MCPGatewayAgent(["http://stub/mcp"], "test", "", "stub-model", "full_research")
    thread = [
        HumanMessage(content="Find the lease."),
        AIMessage(content="", tool_calls=[
            {"id": "c1", "name": "search_collections", "args": {"query": "one"}},
            {"id": "c2", "name": "search_collections", "args": {"query": "two"}},
        ]),
        ToolMessage(content="first result", tool_call_id="c1", name="search_collections"),
    ]
    events = [e async for e in agent.stream(
        query=None, session_id="s1", username="alice", allowed_collections=["testdata"],
        thread=thread, run_id="run-d4")]
    assert [a for n, step, a in seen if step == "start"] == [{"query": "two"}]
    result = next(e["content"] for e in events if e["type"] == "tool_result")
    assert (result["tool_call_id"], result["index"]) == ("c2", 3)
    assert [e["type"] for e in events].count("model_turn") == 1


# --------------------------------------------------------- the batch result budget


from dataclasses import asdict

from mcp.types import EmbeddedResource, TextResourceContents

from agent_common.result_pages import ByteLimit, PageInput, SAFE_MODE_BATCH_BYTES, build_page
from research_agent import execution


def broker_tool(name: str, rows: int, row_bytes: int = 400):
    """A paged tool shaped as the MCP adapter builds one. Like the page broker, it reads
    the page share from the request header that `page_share_client` sends, sizes its page
    within that share, and returns the page with its measure as an embedded resource."""

    async def call(**arguments):
        client = execution.page_share_client(headers={"X-Hoover4-User": "alice"})
        share = int(client.headers.get(execution.PAGE_SHARE_HEADER, "24000"))
        await client.aclose()
        items = [{"n": n, "text": chr(97 + n % 26) * row_bytes} for n in range(rows)]
        page, measure = build_page(
            PageInput(name, "rows", items, None, rows, {}, "src", arguments, None,
                      lambda count: None if count >= rows else {"offset": count}),
            ByteLimit(share),
        )
        resource = EmbeddedResource(type="resource", resource=TextResourceContents(
            uri=execution.CALL_MEASURE_URI, mimeType="application/json",
            text=json.dumps({**asdict(measure), "page_share": share}),
        ))
        return page, [resource]

    return StructuredTool(
        name=name, description=f"{name} stub.", args_schema=EMPTY_SCHEMA, coroutine=call,
        response_format="content_and_artifact",
    )


async def test_three_parallel_pages_share_one_safe_mode_budget(monkeypatch):
    monkeypatch.setattr(execution, "MAX_PAGE_TOKENS", None)
    monkeypatch.setattr(execution.compaction, "context_window", lambda model: 0)
    names = ["search_collections", "read_documents", "table_page"]
    snapshot = build_snapshot([broker_tool(n, 200) for n in names], set(names), "chat")
    node = make_execution_node(snapshot, emit_events=False)
    out = await node(call_state([{"id": n, "name": n, "args": {}} for n in names], names), {})
    pages = [m.content for m in out["messages"]]
    assert sum(len(p.encode("utf-8")) for p in pages) <= SAFE_MODE_BATCH_BYTES
    for message in out["messages"]:
        measure = message.response_metadata["call_measure"]
        assert measure["page_sha256"] == hashlib.sha256(message.content.encode("utf-8")).hexdigest()
        assert measure["budget_mode"] == "bytes" and measure["page_share"] <= SAFE_MODE_BATCH_BYTES // 3 + 400
        assert message.artifact is None
        assert "page_sha256" not in message.content
        assert json.loads(message.content)["returned_units"] > 0


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


async def test_an_exhausted_budget_runs_no_call(monkeypatch):
    seen: List[Any] = []
    snapshot = build_snapshot([dict_tool("read_plan", EMPTY_SCHEMA, seen)], {"read_plan"}, "chat")
    monkeypatch.setattr(execution, "batch_budget", lambda names, messages: execution.BatchBudget("tokens", (1,), 1, exhausted=True))
    node = make_execution_node(snapshot, emit_events=False)
    out = await node(call_state([{"id": "a", "name": "read_plan", "args": {}}]), {})
    assert not seen
    assert json.loads(out["messages"][0].content)["status"] == "budget_exhausted"


def test_the_client_factory_sends_the_share_of_the_current_call():
    token = execution._PAGE_SHARE.set(7_000)
    try:
        client = execution.page_share_client(headers={"X-Hoover4-User": "alice"})
        assert client.headers[execution.PAGE_SHARE_HEADER] == "7000"
        assert client.headers["X-Hoover4-User"] == "alice"
    finally:
        execution._PAGE_SHARE.reset(token)
    assert execution.PAGE_SHARE_HEADER not in execution.page_share_client().headers


def test_the_measure_is_taken_out_of_the_artifact():
    other = EmbeddedResource(type="resource", resource=TextResourceContents(uri="hoover4://other", text="x"))
    measure = EmbeddedResource(type="resource", resource=TextResourceContents(uri=execution.CALL_MEASURE_URI, text='{"page_bytes": 3}'))
    assert execution.split_measure([other, measure]) == ({"page_bytes": 3}, [other])
    assert execution.split_measure([measure]) == ({"page_bytes": 3}, None)
    assert execution.split_measure(None) == (None, None)
