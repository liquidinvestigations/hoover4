"""Mode `plan` of `/model_step`: the first-turn planning call."""

from langchain_core.messages import AIMessage

from research_agent import prompts, steps
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


# ------------------------------------------------------------- the prepended item


async def _stored_steps(model, steps_value):
    model.replies.append(AIMessage(content="", tool_calls=[
        {"id": "p1", "name": "write_todo", "args": {"goal": "g", "steps": steps_value}},
    ]))
    frames = await frames_of(_agent(), step_request(mode="plan"))
    return turn_of(frames)["tool_calls"][0]["args"]["steps"]


async def test_the_planning_call_stores_the_preload_item_first(model):
    assert await _stored_steps(model, ["a", "b"]) == [steps.PRELOAD_ITEM, "a", "b"]
    assert steps.PRELOAD_ITEM == "Read relevant tools and skills"


async def test_forty_steps_keep_forty_and_drop_the_last_step_of_the_model(model):
    forty = [f"step {i}" for i in range(1, 41)]
    stored = await _stored_steps(model, forty)
    assert len(stored) == steps.TODO_MAX_ITEMS == 40
    assert stored == [steps.PRELOAD_ITEM] + forty[:39]


async def test_a_list_that_holds_the_item_stores_it_once(model):
    stored = await _stored_steps(model, ["a", "read relevant tools and skills ", "b"])
    assert stored == [steps.PRELOAD_ITEM, "a", "b"]


async def test_steps_sent_as_a_json_string_are_decoded_first(model):
    assert await _stored_steps(model, '["a", "b"]') == [steps.PRELOAD_ITEM, "a", "b"]


def test_arguments_with_no_list_of_steps_stay_as_they_are():
    assert steps.with_preload_item({"goal": "g"}, TODO_SCHEMA) == {"goal": "g"}
