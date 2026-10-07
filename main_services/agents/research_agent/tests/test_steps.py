"""The step endpoints: `/model_step` classifies one reply, and `/tool_call` runs one call.

Each test runs against a fake model client and fake MCP tools. The fake agent returns a step
context built from the tools of the test, so no MCP server and no model server is reached.
"""

import asyncio
import hashlib
import json
from pathlib import Path
from dataclasses import asdict
from types import SimpleNamespace
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
from agent_common.tool_packs import allowed_tools
from research_agent import execution, steps, stumbles
from research_agent.agent import AgentContext, MCPGatewayAgent
from research_agent.chat_model import ThinkingChatOpenAI
from research_agent.skill_tools import SKILL_TOOLS
from research_agent.tool_catalogue import SEARCH_TOOL, build_snapshot

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
    bound_tools: List[Any] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        # `/model_step` binds OpenAI tool definitions (`steps.shown_tool`).
        self.bound_log.append(sorted(t["function"]["name"] for t in tools))
        self.bound_tools = list(tools)
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
    monkeypatch.setattr(steps.llm_events, "record_llm_call", lambda *a, **k: None)
    monkeypatch.setattr(steps.compaction, "record_compaction", lambda *a, **k: None)
    monkeypatch.setattr(steps.compaction, "plan_compaction", lambda *a, **k: None)
    scripted = ScriptedModel(replies=[], bound_log=[], kwargs_log=[], inputs=[])

    def make(**kwargs):
        scripted.kwargs_log.append(kwargs)
        return scripted

    monkeypatch.setattr(steps, "ThinkingChatOpenAI", make)
    return scripted


RUN = {"run_id": "r1", "kind": "chat", "depth": 0, "username": "alice", "session_id": "s1",
       "allowed_collections": ["testdata"]}


def step_request(messages=None, step_no=1, **extra):
    extra.setdefault("thinking", False)
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
    names = ["search_collections", "write_todo"]
    tools = [dict_tool(n, EMPTY_SCHEMA, []) for n in names]
    agent = FakeAgent(tools, set(names) | {"read_tool"}, kind="chat")
    # The thread binds the plan tool with an earlier `read_tool` call.
    thread = [
        {"role": "human", "content": "Find the lease."},
        {"role": "ai", "content": "", "tool_calls": [
            {"id": "r1", "name": "read_tool", "args": {"name": "write_todo"}}]},
        {"role": "tool", "content": '{"tool": "write_todo"}', "tool_call_id": "r1",
         "name": "read_tool"},
    ]
    model.replies.append(AIMessage(content="", tool_calls=[
        {"id": "a", "name": "search_collections", "args": {"query": "lease"}},
        {"id": "b", "name": "write_todo", "args": {}},
        {"id": "c", "name": "unknown_tool", "args": {"tasks": [{"objective": "A"}]}},
    ]))
    entries = turn_of(await frames_of(agent, step_request(thread, step_no=2)))["tool_calls"]
    # The unknown name has no pack.
    assert [e["kind"] for e in entries] == ["parallel", "ordered", "parallel"]
    assert "briefings" not in entries[0]
    assert sum(e["page_share"] for e in entries) <= SAFE_MODE_BATCH_BYTES
    # No repeat key is sent: the worker compares no calls.
    assert "args_digest" not in entries[0] and "budget_exhausted" not in entries[0]


async def test_a_unknown_tool_call_is_refused_as_an_unknown_tool(model):
    agent = FakeAgent([dict_tool("search_collections", LIST_SCHEMA, [])],
                      {"search_collections"}, kind="chat")
    result = await steps.run_tool_call(agent, tool_request(
        "unknown_tool", {"tasks": [{"objective": "A"}]}))
    assert (result["status"], result["error_class"]) == ("error", "tool_unavailable")


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


async def test_every_run_tool_is_available_without_a_search(model):
    seen: List[Any] = []
    tools = [dict_tool("search_collections", LIST_SCHEMA, []), dict_tool("folder_list", EMPTY_SCHEMA, seen)]
    agent = FakeAgent(tools, {"search_collections", "folder_list", "search_agent_tools"})
    assert "folder_list" in agent.context.snapshot.callable_names()
    result = json.dumps({"matches": [{"name": "folder_list"}], "text": "bound"})
    thread = [
        {"role": "human", "content": "List the folder."},
        {"role": "ai", "content": "", "tool_calls": [
            {"id": "s1", "name": "search_agent_tools", "args": {"query": "list a folder"}}]},
        {"role": "tool", "content": result, "tool_call_id": "s1", "name": "search_agent_tools"},
    ]
    model.replies.append(AIMessage(content="done"))
    turn = turn_of(await frames_of(agent, step_request(thread, step_no=2)))
    assert "bound_names" not in turn
    assert "folder_list" in model.bound_log[-1]

    ran = await steps.run_tool_call(agent, tool_request("folder_list"))
    assert ran["status"] == "ok" and seen

    # A failed search does not remove a tool from the run.
    thread[2]["status"] = "error"
    model.replies.append(AIMessage(content="done"))
    assert "folder_list" in model.bound_log[-1]


async def test_every_model_step_binds_every_tool_of_the_run(model):
    """No step mode binds no tool: a step at the step limit is not sent at all."""
    agent = FakeAgent([dict_tool("search_collections", LIST_SCHEMA, [])], {"search_collections"})
    model.replies.append(AIMessage(content="The answer."))
    frames = await frames_of(agent, step_request())
    assert model.bound_log == [["search_collections"]]
    assert turn_of(frames)["text"] == "The answer."
    assert not hasattr(steps.ModelStepRequest, "mode") and "mode" not in \
        steps.ModelStepRequest.model_fields


@pytest.mark.parametrize("names, bound", [
    (("search_collections", "cite_documents"), True),
    (("web_search", "cite_pages"), True),
    (("search_collections",), False),
])
async def test_the_reply_states_whether_the_citation_tool_was_bound(model, names, bound):
    """The worker checks citations when either citation tool was bound."""
    agent = FakeAgent([dict_tool(n, LIST_SCHEMA, []) for n in names], set(names))
    model.replies.append(AIMessage(content="The answer [D1]."))
    turn = turn_of(await frames_of(agent, step_request()))
    assert turn["usage"]["citation_tool"] is bound


async def test_the_thinking_value_follows_the_request(model):
    agent = FakeAgent([dict_tool("search_collections", LIST_SCHEMA, [])], {"search_collections"})
    model.replies.extend([AIMessage(content=str(i)) for i in range(2)])
    await frames_of(agent, step_request(thinking=True))
    await frames_of(agent, step_request(thinking=False))
    bodies = [k["extra_body"] for k in model.kwargs_log]
    on = {"chat_template_kwargs": {"enable_thinking": True}}
    off = {"chat_template_kwargs": {"enable_thinking": False}}
    assert bodies == [on, off]


def test_a_model_step_request_without_the_thinking_value_is_refused():
    with pytest.raises(ValueError):
        steps.ModelStepRequest(
            **RUN, step_no=1, messages=[{"role": "human", "content": "Find the lease."}]
        )


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


def test_every_browser_tool_that_can_change_the_page_gets_one_attempt():
    """The browser server can list more than its six default tools. A tool that it adds
    gets one attempt unless it only reads the page."""
    for name in ("browser_click", "browser_navigate", "browser_drag", "browser_file_upload",
                 "browser_tabs", "browser_evaluate"):
        assert steps.retries(name) is False, name
    for name in ("read_page", "browser_snapshot", "browser_take_screenshot",
                 "browser_wait_for", "search_collections", "write_todo"):
        assert steps.retries(name) is True, name


ASK_SCHEMA = {"type": "object", "properties": {
    "question": {"type": "string"},
    "options": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}],
                "default": None}}, "required": ["question"]}


async def test_the_arguments_are_normalized_before_the_call_is_classified_and_stored(model):
    """The worker reads the question of `ask_user` from the stored call, so the stored call
    holds the normalized arguments, and the changes are named with it."""
    agent = FakeAgent([dict_tool("ask_user", ASK_SCHEMA, []),
                       dict_tool("mark_todo", MARK_SCHEMA, [])], {"ask_user", "mark_todo"})
    model.replies.append(AIMessage(content="", tool_calls=[
        {"id": "a", "name": "ask_user",
         "args": {"question": 'Which lease?<|"|>', "options": "L-17"}},
        {"id": "b", "name": "mark_todo", "args": {"ids": "1", "status": '"done"'}},
    ]))
    entries = turn_of(await frames_of(agent, step_request()))["tool_calls"]
    assert entries[0]["args"] == {"question": "Which lease?", "options": ["L-17"]}
    assert entries[0]["argument_repairs"] == ["value question lost the quote token"]
    assert entries[1]["args"] == {"ids": ["1"], "status": "done"}
    assert entries[1]["kind"] == "ordered"


async def test_repaired_arguments_are_stored_and_executed(model):
    seen: List[Any] = []
    schema = {"type": "object", "properties": {"queries": {"type": "array", "items": {"type": "string"}}}, "required": ["queries"]}
    agent = FakeAgent([dict_tool("search_collections", schema, seen)], {"search_collections"})
    damaged = {"queries": ['"LJM"', 'Raptor"<|"|><|"|>"LJM1"']}
    model.replies.append(AIMessage(content="", tool_calls=[
        {"id": "a", "name": "search_collections", "args": damaged}]))
    entries = turn_of(await frames_of(agent, step_request()))["tool_calls"]
    assert entries[0]["args"] == {"queries": ['"LJM"', '"Raptor"', '"LJM1"']}
    assert entries[0]["argument_repairs"]
    result = await steps.run_tool_call(agent, tool_request("search_collections", entries[0]["args"]))
    assert result["status"] == "ok" and len(seen) == 1


async def test_a_call_whose_arguments_are_not_json_is_kept_and_refused_with_the_text(model):
    """The tool call parser of the served model streamed an argument text that is not JSON
    (a captured case). The model client lists it as an invalid call. The reply keeps the
    call, and `/tool_call` names the text that the model server sent."""
    seen: List[Any] = []
    agent = FakeAgent([dict_tool("cite_documents", EMPTY_SCHEMA, seen)], {"cite_documents"})
    sent = ('{"citations": [{"document_id": "03a388ac48d3b2cb"}], "{document_id": '
            '"d21ccff5b16f15e9", "},{document_id":')
    model.replies.append(AIMessage(content="", invalid_tool_calls=[
        {"type": "invalid_tool_call", "id": "x", "name": "cite_documents", "args": sent,
         "error": None}]))
    entries = turn_of(await frames_of(agent, step_request()))["tool_calls"]
    assert [(e["name"], e["args"]) for e in entries] == [("cite_documents", {})]
    assert "position" in entries[0]["argument_error"]
    assert entries[0]["argument_error"].endswith("The model server sent: " + sent)
    result = await steps.run_tool_call(agent, steps.ToolCallRequest(
        **RUN, call={"id": "x", "name": "cite_documents", "args": {},
                     "argument_error": entries[0]["argument_error"]},
        idempotency_key="k"))
    assert (result["status"], result["error_class"]) == ("error", "invalid_arguments")
    assert sent in json.loads(result["content"])["message"]
    assert seen == []


async def test_damaged_page_citation_arguments_get_a_flat_retry_example():
    seen = []
    schema = {"type": "object", "properties": {"pages": {
        "type": "array", "items": {"type": "object"}}}}
    agent = FakeAgent([dict_tool("cite_pages", schema, seen)], {"cite_pages"})
    result = await steps.run_tool_call(agent, tool_request(
        "cite_pages", {"pages": ['{<|"|>url<|"|>:<|"|>https://source.example<|"|>}']}))
    assert result["status"] == "error" and result["error_class"] == "invalid_arguments"
    message = json.loads(result["content"])["message"]
    assert "flat arguments" in message and '"terms":["COPY_SHORT_EXACT_PHRASE"]' in message
    assert seen == []


LEAKED = ('call:read_documents{collectionname:<|"|>testdata<|"|>,file_hash:[<|"|>36a12c77e4fd84e8'
          'd38542990f9bd657c6afb9768cae6703fc78b37cf64e88be<|"|>],page:0}')


async def test_a_call_returned_as_text_is_an_unreadable_call_and_no_answer(model):
    """A stored case: the served model returned a call as reply text with no parsed call.
    The reply keeps one call with the name from the text and no rebuilt argument, and
    `/tool_call` refuses it with the text."""
    seen: List[Any] = []
    agent = FakeAgent([dict_tool("read_documents", EMPTY_SCHEMA, seen)], {"read_documents"})
    model.replies.append(AIMessage(content=LEAKED))
    entries = turn_of(await frames_of(agent, step_request()))["tool_calls"]
    assert [(e["name"], e["args"]) for e in entries] == [("read_documents", {})]
    assert LEAKED in entries[0]["argument_error"]
    result = await steps.run_tool_call(agent, steps.ToolCallRequest(
        **RUN, call={"id": entries[0]["id"], "name": "read_documents", "args": {},
                     "argument_error": entries[0]["argument_error"]},
        idempotency_key="k"))
    assert (result["status"], result["error_class"]) == ("error", "invalid_arguments")
    assert seen == []


def test_the_stored_call_text_of_the_fixture_is_one_unreadable_call():
    fixtures = json.loads((Path(__file__).parent / "producer_fixtures"
                           / "gemma4_tool_calls.json").read_text())
    stored = next(e for e in fixtures["entries"] if e["case"] == "call_returned_as_text")
    call = steps.leaked_call(stored["raw"])
    assert (call["name"], call["args"]) == ("read_documents", {})
    assert stored["raw"] in call["argument_error"]


def test_call_syntax_without_a_name_is_an_unnamed_call_and_plain_text_is_none():
    assert steps.leaked_call("<|tool_call>{x:<|\"|>1<|\"|>}")["name"] == steps.UNNAMED_CALL
    assert steps.leaked_call("Use call:read_documents{...} to read.") is None


def test_missing_model_has_an_explicit_error(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(ValueError, match="No chat model is configured"):
        MCPGatewayAgent._resolve_model(SimpleNamespace(llm_model=""))


async def test_the_model_is_bound_with_one_type_for_each_parameter(model):
    agent = FakeAgent([dict_tool("search_collections", ASK_SCHEMA, [])], {"search_collections"})
    model.replies.append(AIMessage(content="done"))
    await frames_of(agent, step_request())
    bound = {t["function"]["name"]: t["function"] for t in model.bound_tools}
    assert bound["search_collections"]["parameters"]["properties"]["options"] == {
        "type": "array", "items": {"type": "string"}, "default": None}
    # `/tool_call` still validates against the tool's own schema.
    tool = agent.context.snapshot.tools_by_name["search_collections"]
    assert tool.args_schema is ASK_SCHEMA and "anyOf" in ASK_SCHEMA["properties"]["options"]


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
    monkeypatch.setattr(steps.compaction, "plan_compaction", lambda *a, **k: None)

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
    frames = await frames_of(agent, step_request())
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


async def test_a_tool_of_the_run_is_callable_without_a_read():
    seen: List[Any] = []
    agent = FakeAgent([dict_tool("folder_list", EMPTY_SCHEMA, seen)], {"folder_list", "search_agent_tools"})
    result = await steps.run_tool_call(agent, tool_request("folder_list"))
    assert result["status"] == "ok"
    assert seen


def pack_agent(kind, packs, seen):
    """An agent over one stub tool for each MCP tool of the packs. The snapshot builds the
    catalogue and skill tools itself."""
    allowed = allowed_tools(kind, packs)
    local = {SEARCH_TOOL, *SKILL_TOOLS}
    tools = [dict_tool(n, EMPTY_SCHEMA, seen) for n in sorted(allowed - local)]
    return FakeAgent(tools, allowed, kind=kind)


def refusal_of(result):
    assert (result["status"], result["error_class"]) == ("error", "tool_unavailable")
    data = json.loads(result["content"])
    assert data["error"] == "tool_unavailable"
    return data["message"]




async def test_a_web_tool_of_a_chat_lead_is_callable():
    seen: List[Any] = []
    agent = pack_agent("chat", "all", seen)
    result = await steps.run_tool_call(agent, tool_request("web_search"))
    assert result["status"] == "ok" and seen


async def test_a_name_outside_every_pack_names_search_agent_tools_when_the_run_has_it():
    chat = pack_agent("chat", "all", [])
    message = refusal_of(await steps.run_tool_call(chat, tool_request("no_such_tool")))
    assert message == "No tool of this run is named 'no_such_tool'. Find tools with search_agent_tools."
    narrow = pack_agent("chat", "collections,web", [])
    message = refusal_of(await steps.run_tool_call(narrow, tool_request("no_such_tool")))
    assert message == "No tool of this run is named 'no_such_tool'. Find tools with search_agent_tools."


def test_the_refusal_text_of_an_unavailable_tool_names_no_skill():
    for text in ("No tool of this run is named 'x'.",):
        content = json.dumps({"success": False, "message": text})
        assert stumbles.stumble_skill("write_todo", content, "error", {}) is None, text


async def test_the_mcp_server_receives_the_idempotency_key_and_the_share():
    seen: List[Any] = []
    agent = FakeAgent([dict_tool("write_todo", EMPTY_SCHEMA, seen)], {"write_todo"}, kind="chat")
    result = await steps.run_tool_call(
        agent, tool_request("write_todo", idempotency_key="K", page_share=5000))
    assert result["status"] == "ok"
    headers = seen[0][2]
    assert "x-hoover4-idempotency-key" not in headers
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


MARK_SCHEMA = {
    "type": "object",
    "properties": {"ids": {"type": "array", "items": {"type": "string"}},
                   "status": {"type": "string", "enum": ["done", "in_progress"]}},
    "required": ["ids", "status"],
}


async def test_the_quote_token_and_a_stray_quote_layer_are_repaired_and_measured():
    """The `mark_todo` arguments of a demo story, as the tool call parser gave them."""
    seen: List[Any] = []
    agent = FakeAgent([dict_tool("mark_todo", MARK_SCHEMA, seen)], {"mark_todo"})
    result = await steps.run_tool_call(agent, tool_request(
        "mark_todo", {"ids": ['"1"', '"2"'], "status": '"done"<|"|>'}))
    assert result["status"] == "ok"
    assert seen[0][1] == {"ids": ["1", "2"], "status": "done"}
    assert result["measure"][steps.ARGUMENT_REPAIRS_KEY] == [
        "value ids[0] lost one layer of quotes", "value ids[1] lost one layer of quotes",
        "value status lost the quote token", "value status lost one layer of quotes"]


async def test_a_call_with_no_repair_keeps_its_measure():
    agent = FakeAgent([dict_tool("mark_todo", MARK_SCHEMA, [])], {"mark_todo"})
    result = await steps.run_tool_call(
        agent, tool_request("mark_todo", {"ids": ["1"], "status": "done"}))
    assert result["measure"] is None


async def test_a_call_runs_whatever_the_request_says_about_the_context():
    """An older worker sends `budget_exhausted`. The field is ignored, and the tool runs."""
    seen: List[Any] = []
    agent = FakeAgent([dict_tool("read_todo", EMPTY_SCHEMA, seen)], {"read_todo"}, kind="chat")
    result = await steps.run_tool_call(agent, tool_request("read_todo", budget_exhausted=True))
    assert seen and result["status"] == "ok" and result["error_class"] == ""


async def test_a_search_result_returns_its_matches():
    agent = FakeAgent([dict_tool("folder_list", EMPTY_SCHEMA, [])], {"folder_list", "search_agent_tools"})
    result = await steps.run_tool_call(
        agent, tool_request("search_agent_tools", {"query": "list a folder"}))
    assert [match["name"] for match in json.loads(result["content"])["matches"]] == ["folder_list"]


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
            e["name"], page_share=e["page_share"])) for e in entries
    ))
    pages = [r["content"] for r in results]
    assert sum(len(p.encode("utf-8")) for p in pages) <= SAFE_MODE_BATCH_BYTES
    for result in results:
        measure = result["measure"]
        assert measure["page_sha256"] == hashlib.sha256(result["content"].encode("utf-8")).hexdigest()
        assert measure["page_share"] <= SAFE_MODE_BATCH_BYTES // 3 + 400
        assert "page_sha256" not in result["content"]
        assert len(json.loads(result["content"])["items"]) > 0


# ------------------------------------------------------------------- request sizing


class CharCounter:
    """A token counter that counts one token for four characters, and records each text."""

    def __init__(self, texts):
        self.texts = texts

    def count(self, text):
        self.texts.append(text)
        return len(text) // 4


def _big_result_thread(result_chars):
    """A thread whose last call has a stored result the previous reply was not billed for."""
    return [
        {"role": "human", "content": "Read the lease."},
        {"role": "ai", "content": "", "usage": {"input_tokens": 100, "output_tokens": 10,
                                                "total_tokens": 110},
         "tool_calls": [{"id": "c1", "name": "read_documents", "args": {"file_hash": ["a"]}}]},
        {"role": "tool", "content": "x" * result_chars, "tool_call_id": "c1",
         "name": "read_documents"},
    ]


@pytest.fixture
def sized(model, monkeypatch):
    """A known window of 10,000 tokens, a counter of one token for four characters, and a
    record of what the compaction plan received."""
    from research_agent import request_size

    texts, plans = [], []
    monkeypatch.setattr(steps.compaction, "context_window", lambda model_id: 10_000)
    monkeypatch.setattr(request_size, "_default_counter", lambda model_id: CharCounter(texts))
    monkeypatch.setattr(request_size, "_tokenizer_down", {})
    monkeypatch.delenv("AGENT_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.setattr(steps.compaction, "plan_compaction",
                        lambda *a, **k: plans.append(k) or None)
    return texts, plans


async def test_the_request_size_counts_the_new_results_and_the_schemas(sized, model):
    texts, plans = sized
    agent = FakeAgent([dict_tool("read_documents", EMPTY_SCHEMA, [])], {"read_documents"})
    model.replies.append(AIMessage(content="done"))
    frames = await frames_of(agent, step_request(_big_result_thread(4_000), step_no=2))
    size = turn_of(frames)["usage"]["request_size"]
    # The stored result alone is 1,000 counted tokens, far above the 110 billed tokens.
    assert size["method"] == "tokenizer" and 1_000 < size["tokens"] < 1_808
    assert size["window"] == 10_000 and size["fits"] is True
    assert (size["output_reserve"], size["reserve_source"]) == (8192, "estimate")
    assert size["safe_input"] == 10_000 - 8192
    assert '"read_documents"' in texts[0] or "read_documents" in texts[0]
    # The compaction gets the measured size, and a trigger no higher than the safe input.
    assert plans[0]["measured"] == size["tokens"] and plans[0]["safe_input"] == 1808
    assert turn_of(frames)["model"] == "stub-model"


async def test_a_request_past_the_safe_input_ends_with_a_context_size_error(sized, model):
    _texts, plans = sized
    agent = FakeAgent([dict_tool("read_documents", EMPTY_SCHEMA, [])], {"read_documents"})
    model.replies.append(AIMessage(content="done"))
    frames = await frames_of(agent, step_request(_big_result_thread(40_000), step_no=2))
    assert [f["type"] for f in frames] == ["error"]
    assert (frames[0]["error_class"], frames[0]["retryable"]) == ("context_size", False)
    assert "and the model accepts 1,808 tokens of input" in frames[0]["content"]
    # No model call was made.
    assert model.inputs == [] and plans[0]["measured"] > 10_000


async def test_a_configured_output_cap_is_the_reserve(sized, model, monkeypatch):
    monkeypatch.setenv("AGENT_MAX_OUTPUT_TOKENS", "2000")
    agent = FakeAgent([dict_tool("read_documents", EMPTY_SCHEMA, [])], {"read_documents"})
    model.replies.append(AIMessage(content="done"))
    size = turn_of(await frames_of(agent, step_request()))["usage"]["request_size"]
    assert (size["output_reserve"], size["reserve_source"], size["safe_input"]) == (
        2000, "configured", 8000)


async def test_a_failed_tokenizer_gives_a_recorded_estimate_and_the_call(sized, model,
                                                                        monkeypatch):
    from research_agent import request_size

    class Broken:
        def count(self, text):
            raise RuntimeError("no tokenizer route")

    monkeypatch.setattr(request_size, "_default_counter", lambda model_id: Broken())
    monkeypatch.setattr(steps.compaction, "context_window", lambda model_id: 100_000)
    agent = FakeAgent([dict_tool("read_documents", EMPTY_SCHEMA, [])], {"read_documents"})
    model.replies.append(AIMessage(content="", tool_calls=[
        {"id": "a", "name": "read_documents", "args": {}}]))
    turn = turn_of(await frames_of(agent, step_request(_big_result_thread(40_000), step_no=2)))
    size = turn["usage"]["request_size"]
    assert size["method"] == "estimate" and "no tokenizer route" in size["error"]
    assert size["tokens"] > 10_000
    # The reply's call is classified with an ordinary share. Nothing refuses it.
    assert turn["tool_calls"][0]["page_share"] == SAFE_MODE_BATCH_BYTES
    assert "budget_exhausted" not in turn["tool_calls"][0]


async def test_an_unknown_window_records_the_fact_and_sends_the_request(model, monkeypatch):
    monkeypatch.setattr(steps.compaction, "context_window", lambda model_id: 0)
    agent = FakeAgent([dict_tool("read_documents", EMPTY_SCHEMA, [])], {"read_documents"})
    model.replies.append(AIMessage(content="done"))
    size = turn_of(await frames_of(agent, step_request()))["usage"]["request_size"]
    assert (size["window_known"], size["safe_input"], size["fits"], size["method"]) == (
        False, 0, True, "estimate")


# ------------------------------------------------------------------- context preparation


def _long_thread(groups=12, result_chars=12_000):
    """A thread of `groups` finished steps, with the usage of the last reply billed."""
    thread = [{"role": "human", "content": "Find the lease.", "thread_id": "t1", "idx": 0}]
    for n in range(groups):
        idx = len(thread)
        thread.append({"role": "ai", "content": "", "thread_id": "t1", "idx": idx,
                       "usage": {"input_tokens": 100, "output_tokens": 10},
                       "tool_calls": [{"id": f"c{n}", "name": "read_documents",
                                       "args": {"n": n}}]})
        thread.append({"role": "tool", "content": f"R{n} " + "x" * result_chars,
                       "tool_call_id": f"c{n}", "name": "read_documents", "thread_id": "t1",
                       "idx": idx + 1})
    return thread


#: The compaction plan before a fixture replaces it.
_REAL_PLAN = steps.compaction.plan_compaction


@pytest.fixture
def compacting(model, monkeypatch):
    """The real compaction plan over a window of 40,000 tokens, a counter of one token for
    four characters, and a recorded summariser."""
    from research_agent import compaction, request_size

    monkeypatch.setattr(steps.compaction, "plan_compaction",
                        lambda *a, **k: _REAL_PLAN(*a, **{**k, "summary_window": 40_000}))
    windows = [40_000]
    monkeypatch.setattr(steps.compaction, "context_window", lambda model_id: windows[0])
    monkeypatch.setattr(request_size, "_default_counter", lambda model_id: CharCounter([]))
    monkeypatch.setattr(request_size, "_tokenizer_down", {})
    monkeypatch.setenv("AGENT_MAX_OUTPUT_TOKENS", "4000")
    summaries = {"calls": [], "text": "## Findings\nR0 says the lease was approved."}

    def summarise(prompt, *, model_id, max_tokens):
        summaries["calls"].append(prompt)
        return summaries["text"]

    monkeypatch.setattr(compaction, "summarise_with_model", summarise)
    return summaries, windows


async def test_a_compacting_step_sends_the_frame_the_summary_and_a_version_3_record(
        compacting, model):
    summaries, _windows = compacting
    agent = FakeAgent([dict_tool("read_documents", EMPTY_SCHEMA, [])], {"read_documents"})
    model.replies.append(AIMessage(content="done"))
    frames = await frames_of(agent, step_request(_long_thread(), step_no=13))
    assert [f["type"] for f in frames][:1] == ["compaction"]
    turn = turn_of(frames)
    record = turn["compaction"]
    assert (record["version"], record["status"], turn["summarised"]) == (3, "ok", True)
    assert len(summaries["calls"]) == 1
    size = turn["usage"]["request_size"]
    assert size["fits"] and size["before_compaction"] > size["tokens"]
    sent = [m.content for m in model.inputs[0]]
    assert any(c.startswith(steps.compaction.RECORD_HEADER) for c in sent)
    assert sent[-1].startswith("R11 ")
    assert "note_warning" not in turn


async def test_a_failed_summary_sends_the_previous_list_when_it_fits(compacting, model,
                                                                    monkeypatch):
    summaries, _windows = compacting
    summaries["text"] = ""
    # A trigger under the size of the list, and a safe input above it.
    monkeypatch.setenv("AGENT_COMPACTION_FRACTION", "0.5")
    agent = FakeAgent([dict_tool("read_documents", EMPTY_SCHEMA, [])], {"read_documents"})
    model.replies.append(AIMessage(content="done"))
    frames = await frames_of(agent, step_request(_long_thread(10), step_no=11))
    turn = turn_of(frames)
    assert turn["compaction"]["status"] == "failed" and turn["summarised"] is False
    sent = [m.content for m in model.inputs[0]]
    assert not any(c.startswith(steps.compaction.RECORD_HEADER) for c in sent)
    assert len(sent) == 1 + 1 + 2 * 10


async def test_a_failed_summary_of_a_list_that_does_not_fit_ends_the_run(compacting, model):
    summaries, _windows = compacting
    summaries["text"] = ""
    agent = FakeAgent([dict_tool("read_documents", EMPTY_SCHEMA, [])], {"read_documents"})
    model.replies.append(AIMessage(content="done"))
    frames = await frames_of(agent, step_request(_long_thread(), step_no=13))
    assert [f["type"] for f in frames] == ["compaction", "error"]
    assert (frames[1]["error_class"], frames[1]["retryable"]) == ("context_preparation", False)
    assert "The summary of the older steps failed" in frames[1]["content"]
    assert model.inputs == []


def _size_refusal(text="This model's maximum context length is 20000 tokens."):
    request = httpx.Request("POST", "http://model.invalid/v1/chat/completions")
    return openai.BadRequestError(text, response=httpx.Response(400, request=request),
                                  body=None)


async def test_a_provider_size_refusal_prepares_the_request_once_more(compacting, model):
    summaries, _windows = compacting
    agent = FakeAgent([dict_tool("read_documents", EMPTY_SCHEMA, [])], {"read_documents"})
    # Under the trigger, so the first request is the whole list. The provider refuses it.
    model.replies.extend([_size_refusal(), AIMessage(content="done")])
    frames = await frames_of(agent, step_request(_long_thread(7), step_no=8))
    turn = turn_of(frames)
    assert len(model.inputs) == 2
    assert len(model.inputs[1]) < len(model.inputs[0])
    assert turn["compaction"]["status"] == "ok" and len(summaries["calls"]) == 1
    # The stated limit of the refusal is the window of the new preparation.
    assert turn["usage"]["request_size"]["window"] == 20_000


async def test_an_identical_request_after_a_size_refusal_is_not_sent_again(compacting, model):
    agent = FakeAgent([dict_tool("read_documents", EMPTY_SCHEMA, [])], {"read_documents"})
    model.replies.extend([_size_refusal("prompt is too long"), AIMessage(content="done")])
    # One step: nothing older can be summarised, so the new preparation is the same request.
    frames = await frames_of(agent, step_request(_long_thread(1), step_no=2))
    assert frames[-1]["type"] == "error" and frames[-1]["error_class"] == "context_size"
    assert "gave the same request" in frames[-1]["content"]
    assert len(model.inputs) == 1


async def test_another_refusal_is_not_a_size_refusal(compacting, model):
    agent = FakeAgent([dict_tool("read_documents", EMPTY_SCHEMA, [])], {"read_documents"})
    model.replies.extend([_size_refusal("invalid tool schema"), AIMessage(content="done")])
    frames = await frames_of(agent, step_request(_long_thread(1), step_no=2))
    assert frames[-1]["type"] == "error" and frames[-1]["error_class"] == "http_400"
    assert len(model.inputs) == 1


async def test_oversized_newest_results_reduce_largest_first_and_keep_full_evidence(monkeypatch):
    from research_agent.run_messages import RunMessage
    from research_agent.request_size import RequestSize
    calls = []
    class Pager:
        async def ainvoke(self, args):
            calls.append(args)
            return json.dumps({"items": [args["content"][:500]], "more": "0123456789ab"})
    context = SimpleNamespace(model_id="stub", result_pager=Pager())
    rows = [RunMessage(role="human", content="question", thread_id="t", idx=0),
            RunMessage(role="ai", content="", tool_calls=[{"id": "a", "name": "doc_email", "args": {}},
                {"id": "b", "name": "doc_email", "args": {}}], thread_id="t", idx=1),
            RunMessage(role="tool", content="a" * 10000, tool_call_id="a", name="doc_email", thread_id="t", idx=2),
            RunMessage(role="tool", content="b" * 20000, tool_call_id="b", name="doc_email", thread_id="t", idx=3)]
    def measure(system, schemas, messages, **kw):
        return RequestSize(tokens=sum(len(m.content) for m in messages), method="test", window=14000, output_reserve=1000, reserve_source="test")
    monkeypatch.setattr(steps.request_size, "measure", measure)
    monkeypatch.setattr(steps.compaction, "plan_compaction", lambda *a, **kw: None)
    request = step_request(messages=[m.model_dump() for m in rows])
    frames = [item async for item in steps._prepare(request, context, "", "", rows, rows, 14000)]
    prepared = frames[-1]
    assert prepared.size["fits"] and calls[0]["call_id"] == "b"
    assert prepared.reductions[0]["idx"] == 3
    assert rows[3].content == "b" * 20000
    assert calls[0]["content"] == rows[3].content


async def test_repeated_read_runs_again_after_its_result_is_reduced(model):
    seen = []
    agent = FakeAgent([dict_tool("read_documents", LIST_SCHEMA, seen)], {"read_documents"})
    messages = [{"role": "human", "content": "question", "thread_id": "t", "idx": 0},
        {"role": "ai", "content": "", "tool_calls": [{"id": "old", "name": "read_documents", "args": {"query": "x"}}], "thread_id": "t", "idx": 1},
        {"role": "tool", "content": "complete", "tool_call_id": "old", "name": "read_documents", "status": "ok", "thread_id": "t", "idx": 2}]
    request = tool_request("read_documents", {"query": "x"}).model_copy(update={"messages": [steps.RunMessage(**m) for m in messages]})
    repeated = await steps.run_tool_call(agent, request)
    assert "repeats call old" in repeated["content"] and seen == []
    request.messages[-1].model_content = "partial"
    assert (await steps.run_tool_call(agent, request))["status"] == "ok"
    assert len(seen) == 1


@pytest.mark.parametrize("name,handle", [("cite_pages", "[W1]"), ("cite_documents", "[D1]")])
@pytest.mark.parametrize("changed", [None, "terms", "read", "reduced", "failed", "partial"])
async def test_only_complete_unchanged_verified_citations_skip_reexecution(name, handle, changed):
    seen = []
    agent = FakeAgent([dict_tool(name, LIST_SCHEMA, seen)], {name})
    result = {"citations": [{"handle": handle, "quote_verified": True}], "errors": []}
    if changed == "failed":
        result = {"citations": [], "errors": [{"error": "Absent wording"}]}
    if changed == "partial":
        result["errors"] = [{"error": "Another source is unread"}]
    messages = [
        {"role": "human", "content": "question", "thread_id": "t", "idx": 0},
        {"role": "ai", "content": "", "tool_calls": [{"id": "old", "name": name,
            "args": {"query": "first passage"}}], "thread_id": "t", "idx": 1},
        {"role": "tool", "content": json.dumps(result), "tool_call_id": "old", "name": name,
            "status": "ok", "thread_id": "t", "idx": 2},
    ]
    if changed == "read":
        messages.append({"role": "tool", "content": "New source version", "tool_call_id": "read",
                         "name": "read_page", "status": "ok", "thread_id": "t", "idx": 3})
    if changed == "reduced":
        messages[-1]["model_content"] = "partial result"
    request = tool_request(name, {"query": "another passage" if changed == "terms" else "first passage"})
    request = request.model_copy(update={"messages": [steps.RunMessage(**message) for message in messages]})
    response = await steps.run_tool_call(agent, request)
    assert response["status"] == "ok"
    if changed is None:
        assert seen == [] and f"Use its verified handles {handle}" in response["content"]
    else:
        assert len(seen) == 1
