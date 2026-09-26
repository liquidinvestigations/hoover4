"""The step endpoints: `/model_step` classifies one reply, and `/tool_call` runs one call.

Each test runs against a fake model client and fake MCP tools. The fake agent returns a step
context built from the tools of the test, so no MCP server and no model server is reached.
"""

import asyncio
import hashlib
import json
from dataclasses import asdict
from typing import Any, List

import httpx
import openai
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from mcp.types import EmbeddedResource, TextResourceContents

from agent_common.result_pages import ByteLimit, PageInput, SAFE_MODE_BATCH_BYTES, build_page
from research_agent import execution, steps, subagents
from research_agent.agent import AgentContext
from research_agent.chat_model import ThinkingChatOpenAI
from research_agent.tool_catalogue import build_snapshot

LIST_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}
EMPTY_SCHEMA = {"type": "object", "properties": {}}


def dict_tool(name: str, schema: dict, seen: List[Any], fail: bool = False):
    """A tool shaped as the MCP adapter builds one. It records the headers that the MCP
    client factory would send for the call."""

    async def call(**arguments):
        client = execution.page_share_client(headers={"X-Hoover4-User": "alice"})
        seen.append((name, arguments, dict(client.headers)))
        await client.aclose()
        if fail:
            raise RuntimeError(f"{name} failed on purpose")
        return json.dumps({"tool": name, "ok": True})

    return StructuredTool(
        name=name, description=f"{name.replace('_', ' ')} stub.", args_schema=schema,
        coroutine=call,
    )


class ScriptedModel(BaseChatModel):
    """A chat model that returns scripted replies, or raises, and records what it gets."""

    replies: List[Any]
    bound_log: List[Any]
    kwargs_log: List[Any]
    inputs: List[Any]

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        self.bound_log.append(sorted(t.name for t in tools))
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.inputs.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=reply)])


class FakeAgent:
    """Returns one step context over the given tools, as `MCPGatewayAgent.context_for`."""

    def __init__(self, tools, allowed, kind="chat", llm_kwargs=None):
        self.name = "test"
        self.langfuse_handler = None
        self.context = AgentContext(
            snapshot=build_snapshot(tools, allowed, kind),
            tools=list(tools),
            llm_kwargs=dict(llm_kwargs or {}),
            model_id="stub-model",
            system_text_for=lambda names: "system: " + ",".join(names),
        )

    async def context_for(self, *args, **kwargs):
        return self.context


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setenv("LLM_STREAMING", "false")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setattr(execution, "MAX_PAGE_TOKENS", None)
    monkeypatch.setattr(steps.llm_events, "record_llm_call", lambda *a, **k: None)
    monkeypatch.setattr(steps.compaction, "record_compaction", lambda *a, **k: None)
    monkeypatch.setattr(steps.compaction, "compact_messages", lambda messages, **k: (list(messages), None))
    scripted = ScriptedModel(replies=[], bound_log=[], kwargs_log=[], inputs=[])

    def make(**kwargs):
        scripted.kwargs_log.append(kwargs)
        return scripted

    monkeypatch.setattr(steps, "ThinkingChatOpenAI", make)
    return scripted


RUN = {"run_id": "r1", "kind": "chat", "depth": 0, "username": "alice", "session_id": "s1",
       "allowed_collections": ["testdata"]}


def step_request(messages=None, step_no=1, **extra):
    return steps.ModelStepRequest(
        **RUN, step_no=step_no,
        messages=messages or [{"role": "human", "content": "Find the lease."}], **extra,
    )


def tool_request(name, args=None, **extra):
    extra.setdefault("idempotency_key", "key-1")
    return steps.ToolCallRequest(
        **RUN, call={"id": "c1", "name": name, "args": args or {}}, **extra
    )


async def frames_of(agent, request):
    return [frame async for frame in steps.run_model_step(agent, request)]


def turn_of(frames):
    return next(f for f in frames if f["type"] == "model_turn")


def briefing(objective):
    return {"objective": objective, "known": "", "bring_back": "the documents"}


# ------------------------------------------------------------------------ model step


async def test_a_reply_with_no_call_sends_response_model_turn_and_end(model):
    model.replies.append(AIMessage(content="done"))
    agent = FakeAgent([dict_tool("search_collections", LIST_SCHEMA, [])], {"search_collections"})
    frames = await frames_of(agent, step_request())
    assert [f["type"] for f in frames] == ["response", "model_turn", "end"]
    assert frames[0]["content"] == "done"
    assert turn_of(frames)["tool_calls"] == []
    assert frames[-1]["model"] == "stub-model"


async def test_a_streamed_reply_sends_the_same_frames(model, monkeypatch):
    monkeypatch.setenv("LLM_STREAMING", "true")
    model.replies.append(AIMessage(content="done"))
    agent = FakeAgent([dict_tool("search_collections", LIST_SCHEMA, [])], {"search_collections"})
    frames = await frames_of(agent, step_request())
    assert [f["type"] for f in frames] == ["response", "model_turn", "end"]
    assert turn_of(frames)["text"] == "done"


async def test_a_reply_with_three_calls_is_classified(model):
    names = ["search_collections", "append_node"]
    tools = [dict_tool(n, EMPTY_SCHEMA, []) for n in names] + [subagents.make_delegation_tool()]
    agent = FakeAgent(tools, set(names) | {"run_subagent"}, kind="planner")
    model.replies.append(AIMessage(content="", tool_calls=[
        {"id": "a", "name": "search_collections", "args": {"query": "lease"}},
        {"id": "b", "name": "append_node", "args": {}},
        {"id": "d", "name": "run_subagent", "args": {"tasks": [briefing("A")]}},
    ]))
    entries = turn_of(await frames_of(agent, step_request()))["tool_calls"]
    assert [e["kind"] for e in entries] == ["parallel", "ordered", "delegation"]
    assert len(entries[2]["briefings"]) == 1 and entries[2]["page_share"] is None
    assert entries[0]["page_share"] + entries[1]["page_share"] <= SAFE_MODE_BATCH_BYTES
    assert entries[0]["args_digest"] == hashlib.sha1(
        b'search_collections\n{"query":"lease"}').hexdigest()


async def test_run_subagent_with_unreadable_briefings_is_a_parallel_call(model):
    agent = FakeAgent([subagents.make_delegation_tool()], {"run_subagent"}, kind="chat")
    model.replies.append(AIMessage(content="", tool_calls=[
        {"id": "d", "name": "run_subagent", "args": {"tasks": "not json"}}]))
    entries = turn_of(await frames_of(agent, step_request()))["tool_calls"]
    assert entries[0]["kind"] == "parallel" and entries[0]["briefings"] is None
    result = await steps.run_tool_call(agent, tool_request("run_subagent", {"tasks": "not json"}))
    assert (result["status"], result["error_class"]) == ("error", "invalid_arguments")


async def test_a_joined_call_id_gets_a_new_id(model):
    agent = FakeAgent([dict_tool("search_collections", LIST_SCHEMA, [])], {"search_collections"})
    joined = "chatcmpl-tool-7chatcmpl-tool-7"
    model.replies.append(AIMessage(content="", tool_calls=[
        {"id": joined, "name": "search_collections", "args": {"query": "a"}},
        {"id": joined, "name": "search_collections", "args": {"query": "b"}},
    ]))
    entries = turn_of(await frames_of(agent, step_request(step_no=4)))["tool_calls"]
    assert [e["id"] for e in entries] == ["call-4-0", "call-4-1"]


async def test_an_id_of_an_earlier_message_gets_a_new_id(model):
    agent = FakeAgent([dict_tool("search_collections", LIST_SCHEMA, [])], {"search_collections"})
    thread = [
        {"role": "human", "content": "Find the lease."},
        {"role": "ai", "content": "", "tool_calls": [
            {"id": "c1", "name": "search_collections", "args": {"query": "a"}}]},
        {"role": "tool", "content": "{}", "tool_call_id": "c1", "name": "search_collections"},
    ]
    model.replies.append(AIMessage(content="", tool_calls=[
        {"id": "c1", "name": "search_collections", "args": {"query": "b"}},
        {"id": "c9", "name": "search_collections", "args": {"query": "c"}},
    ]))
    entries = turn_of(await frames_of(agent, step_request(thread, step_no=2)))["tool_calls"]
    assert [e["id"] for e in entries] == ["call-2-0", "c9"]


async def test_a_search_result_in_the_thread_binds_its_names(model):
    seen: List[Any] = []
    tools = [dict_tool("search_collections", LIST_SCHEMA, []), dict_tool("folder_list", EMPTY_SCHEMA, seen)]
    agent = FakeAgent(tools, {"search_collections", "folder_list", "search_agent_tools"})
    assert "folder_list" in agent.context.snapshot.deferred_names
    result = json.dumps({"matches": [{"name": "folder_list"}], "text": "bound"})
    thread = [
        {"role": "human", "content": "List the folder."},
        {"role": "ai", "content": "", "tool_calls": [
            {"id": "s1", "name": "search_agent_tools", "args": {"query": "list a folder"}}]},
        {"role": "tool", "content": result, "tool_call_id": "s1", "name": "search_agent_tools"},
    ]
    model.replies.append(AIMessage(content="done"))
    turn = turn_of(await frames_of(agent, step_request(thread, step_no=2)))
    assert turn["bound_names"] == ["folder_list"]
    assert "folder_list" in model.bound_log[-1]

    ran = await steps.run_tool_call(agent, tool_request("folder_list", bound_names=turn["bound_names"]))
    assert ran["status"] == "ok" and seen

    # A failed search result binds nothing.
    thread[2]["status"] = "error"
    model.replies.append(AIMessage(content="done"))
    assert turn_of(await frames_of(agent, step_request(thread, step_no=2)))["bound_names"] == []


async def test_mode_final_binds_no_tool(model):
    agent = FakeAgent([dict_tool("search_collections", LIST_SCHEMA, [])], {"search_collections"})
    model.replies.append(AIMessage(content="The answer."))
    frames = await frames_of(agent, step_request(mode="final"))
    assert model.bound_log == []
    assert turn_of(frames)["text"] == "The answer."


async def test_the_thinking_value_follows_the_mode_or_the_request(model):
    agent = FakeAgent([dict_tool("search_collections", LIST_SCHEMA, [])], {"search_collections"})
    model.replies.extend([AIMessage(content="a"), AIMessage(content="b")])
    await frames_of(agent, step_request(thinking=True))
    await frames_of(agent, step_request())
    bodies = [k["extra_body"] for k in model.kwargs_log]
    assert bodies[0] == {"chat_template_kwargs": {"enable_thinking": True}}
    assert bodies[1] == steps.tool_turn_kwargs()


async def test_a_browser_action_gets_one_attempt(model):
    agent = FakeAgent([dict_tool("browser_click", EMPTY_SCHEMA, []),
                       dict_tool("browser_snapshot", EMPTY_SCHEMA, [])],
                      {"browser_click", "browser_snapshot"})
    model.replies.append(AIMessage(content="", tool_calls=[
        {"id": "a", "name": "browser_click", "args": {}},
        {"id": "b", "name": "browser_snapshot", "args": {}},
    ]))
    entries = turn_of(await frames_of(agent, step_request()))["tool_calls"]
    assert [e["retry"] for e in entries] == [False, True]


def _http_error(status):
    request = httpx.Request("POST", "http://stub/v1/chat/completions")
    return openai.BadRequestError(
        "bad request", response=httpx.Response(status, request=request), body=None
    )


async def test_a_model_error_sends_one_error_frame(model):
    agent = FakeAgent([dict_tool("search_collections", LIST_SCHEMA, [])], {"search_collections"})
    model.replies.append(_http_error(400))
    frames = await frames_of(agent, step_request())
    assert len(frames) == 1 and frames[0]["type"] == "error"
    assert (frames[0]["error_class"], frames[0]["retryable"]) == ("http_400", False)


async def test_a_timeout_is_a_retryable_error(model):
    agent = FakeAgent([dict_tool("search_collections", LIST_SCHEMA, [])], {"search_collections"})
    model.replies.append(httpx.ReadTimeout("read timed out"))
    frames = await frames_of(agent, step_request())
    assert [f["type"] for f in frames] == ["error"]
    assert (frames[0]["error_class"], frames[0]["retryable"]) == ("read_timeout", True)


def test_the_error_classes():
    request = httpx.Request("POST", "http://stub")
    assert steps.classify_error(openai.APITimeoutError(request=request)) == ("read_timeout", True)
    assert steps.classify_error(openai.APIConnectionError(request=request)) == ("connect_error", True)
    assert steps.classify_error(_http_error(429)) == ("http_429", True)
    assert steps.classify_error(_http_error(408)) == ("http_408", True)
    assert steps.classify_error(_http_error(503)) == ("http_503", True)
    assert steps.classify_error(ValueError("x")) == ("other", True)


async def test_a_whole_reply_keeps_its_reasoning(monkeypatch):
    monkeypatch.setenv("LLM_STREAMING", "false")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setattr(steps.llm_events, "record_llm_call", lambda *a, **k: None)
    monkeypatch.setattr(steps.compaction, "compact_messages", lambda messages, **k: (list(messages), None))

    def answer(request):
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": "stub-model",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": "The answer.", "reasoning": "r"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    agent = FakeAgent([dict_tool("search_collections", LIST_SCHEMA, [])], {"search_collections"},
                      llm_kwargs={"api_key": "k", "model": "stub-model",
                                  "base_url": "http://stub/v1", "http_async_client": client})
    frames = await frames_of(agent, step_request(mode="final"))
    turn = turn_of(frames)
    assert turn["reasoning"] == "r" and turn["text"] == "The answer."
    assert {"type": "reasoning", "content": "r"} in frames
    assert frames[-1]["usage"]["prompt_tokens"] == 10


def test_the_whole_reply_converter_reads_reasoning_content_too():
    llm = ThinkingChatOpenAI(api_key="k", model="m")
    result = llm._create_chat_result({"model": "m", "choices": [{"message": {
        "role": "assistant", "content": "x", "reasoning_content": "why"}}]})
    assert result.generations[0].message.additional_kwargs["reasoning_content"] == "why"


def test_a_sub_agent_request_with_earlier_turns_is_refused():
    with pytest.raises(ValueError):
        steps.ModelStepRequest(**{**RUN, "depth": 1}, step_no=1,
                               messages=[{"role": "human", "content": "q"}],
                               earlier=[{"role": "human", "content": "e"}])


# ------------------------------------------------------------------------- tool call


async def test_an_unbound_tool_is_refused_with_tool_unavailable():
    seen: List[Any] = []
    agent = FakeAgent([dict_tool("folder_list", EMPTY_SCHEMA, seen)], {"folder_list", "search_agent_tools"})
    result = await steps.run_tool_call(agent, tool_request("folder_list"))
    assert (result["status"], result["error_class"]) == ("error", "tool_unavailable")
    assert json.loads(result["content"])["error"] == "tool_unavailable"
    assert seen == []


async def test_the_mcp_server_receives_the_idempotency_key_and_the_share():
    seen: List[Any] = []
    agent = FakeAgent([dict_tool("append_node", EMPTY_SCHEMA, seen)], {"append_node"}, kind="planner")
    result = await steps.run_tool_call(
        agent, tool_request("append_node", idempotency_key="K", page_share=5000))
    assert result["status"] == "ok"
    headers = seen[0][2]
    assert headers["x-hoover4-idempotency-key"] == "K"
    assert headers["x-hoover4-page-share"] == "5000"
    # The values belong to the call, and do not leak into the next one.
    assert execution._IDEMPOTENCY_KEY.get() is None and execution._PAGE_SHARE.get() is None


async def test_a_tool_that_raises_is_a_tool_error():
    agent = FakeAgent([dict_tool("read_documents", EMPTY_SCHEMA, [], fail=True)], {"read_documents"})
    result = await steps.run_tool_call(agent, tool_request("read_documents"))
    assert (result["status"], result["error_class"]) == ("error", "tool_error")
    assert "failed on purpose" in result["content"]


async def test_arguments_that_do_not_match_the_schema_are_refused_before_the_call():
    seen: List[Any] = []
    agent = FakeAgent([dict_tool("search_collections", LIST_SCHEMA, seen)], {"search_collections"})
    result = await steps.run_tool_call(agent, tool_request("search_collections", {}))
    assert result["error_class"] == "invalid_arguments" and seen == []


async def test_an_exhausted_budget_runs_no_call():
    seen: List[Any] = []
    agent = FakeAgent([dict_tool("read_plan", EMPTY_SCHEMA, seen)], {"read_plan"}, kind="planner")
    result = await steps.run_tool_call(agent, tool_request("read_plan", budget_exhausted=True))
    assert not seen
    assert result["error_class"] == "budget_exhausted"
    assert json.loads(result["content"])["status"] == "budget_exhausted"


async def test_a_search_result_returns_its_matched_names():
    agent = FakeAgent([dict_tool("folder_list", EMPTY_SCHEMA, [])], {"folder_list", "search_agent_tools"})
    result = await steps.run_tool_call(
        agent, tool_request("search_agent_tools", {"query": "list a folder"}))
    assert result["matched_names"] == ["folder_list"]


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


async def test_three_parallel_pages_share_one_safe_mode_budget(model):
    names = ["search_collections", "read_documents", "table_page"]
    agent = FakeAgent([broker_tool(n, 200) for n in names], set(names))
    model.replies.append(AIMessage(content="", tool_calls=[
        {"id": n, "name": n, "args": {}} for n in names]))
    entries = turn_of(await frames_of(agent, step_request()))["tool_calls"]
    results = await asyncio.gather(*(
        steps.run_tool_call(agent, tool_request(
            e["name"], page_share=e["page_share"], bound_names=names)) for e in entries
    ))
    pages = [r["content"] for r in results]
    assert sum(len(p.encode("utf-8")) for p in pages) <= SAFE_MODE_BATCH_BYTES
    for result in results:
        measure = result["measure"]
        assert measure["page_sha256"] == hashlib.sha256(result["content"].encode("utf-8")).hexdigest()
        assert measure["page_share"] <= SAFE_MODE_BATCH_BYTES // 3 + 400
        assert "page_sha256" not in result["content"]
        assert json.loads(result["content"])["returned_units"] > 0
