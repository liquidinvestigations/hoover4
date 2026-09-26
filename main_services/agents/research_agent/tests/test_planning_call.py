"""Mode `plan` of `/model_step`: the first-turn planning call."""

from langchain_core.messages import AIMessage

from research_agent import prompts
from test_steps import (  # noqa: F401 - `model` is a fixture
    LIST_SCHEMA, FakeAgent, dict_tool, frames_of, model, step_request, turn_of,
)

TODO_SCHEMA = {
    "type": "object",
    "properties": {"goal": {"type": "string"},
                   "steps": {"type": "array", "items": {"type": "string"}}},
    "required": ["goal", "steps"],
}


def _agent(web=False):
    tools = [dict_tool("write_todo", TODO_SCHEMA, []),
             dict_tool("search_collections", LIST_SCHEMA, [])]
    if web:
        tools.append(dict_tool("web_search", LIST_SCHEMA, []))
    return FakeAgent(tools, {t.name for t in tools})


async def test_a_plan_step_binds_write_todo_only_with_thinking_off(model):
    model.replies.append(AIMessage(content="", tool_calls=[
        {"id": "p1", "name": "write_todo", "args": {"goal": "g", "steps": ["a", "b"]}},
        {"id": "p2", "name": "search_collections", "args": {"query": "x"}},
    ]))
    frames = await frames_of(_agent(), step_request(mode="plan", thinking=True))
    assert model.bound_log == [["write_todo"]]
    assert model.kwargs_log[0]["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}}
    turn = turn_of(frames)
    assert [c["name"] for c in turn["tool_calls"]] == ["write_todo"]
    system = model.inputs[0][0].content
    assert system.startswith("You write the first plan of a research conversation.")
    assert "The collections that the run can read: testdata." in system
    assert "The web tools are off." in system


async def test_a_plan_step_names_the_web_tools_when_they_are_bound(model):
    model.replies.append(AIMessage(content="no call"))
    frames = await frames_of(_agent(web=True), step_request(mode="plan"))
    assert "The web tools are on." in model.inputs[0][0].content
    assert turn_of(frames)["tool_calls"] == []


def test_the_planning_call_text_holds_no_json_and_no_unrendered_field():
    text = prompts.planning_call(collections=[], web_enabled=False)
    assert "The run can read no collection." in text
    assert "{" not in text and "}" not in text
