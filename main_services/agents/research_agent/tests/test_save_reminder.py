"""The save reminder after citation results. See research_agent/steps.py::save_reminder."""

import json

from research_agent import steps

from tests.test_steps import RUN, FakeAgent, dict_tool

CITED = json.dumps({"citations": [{"handle": "[W1]", "quote_verified": True}]})
SAVED = json.dumps({"success": True, "name": "report.md", "version": 1})
SCHEMA = {"type": "object", "properties": {"url": {"type": "string"}}}


def cite_agent():
    tool = dict_tool("cite_pages", SCHEMA, [])

    async def cite(**arguments):
        return CITED

    tool.coroutine = cite
    return FakeAgent([tool], {"cite_pages"})


def request(*earlier, key="k"):
    """`earlier` items are (name, content) or (name, content, reminded_at)."""
    messages = [{"role": "human", "content": "List the board."}]
    for n, (name, content, *reminded) in enumerate(earlier):
        messages += [{"role": "ai", "content": "", "tool_calls": [{"id": f"e{n}", "name": name, "args": {}}]},
                     {"role": "tool", "tool_call_id": f"e{n}", "name": name, "content": content, "status": "ok",
                      "reminded_at": reminded[0] if reminded else None}]
    return steps.ToolCallRequest(**RUN, call={"id": "c9", "name": "cite_pages", "args": {"url": "u"}},
                                 idempotency_key=key, messages=messages)


async def shown(req):
    result = await steps.run_tool_call(cite_agent(), req)
    assert result["status"] == "ok"
    return result.get("model_content") or result["content"]


async def test_the_first_citation_gets_no_reminder():
    assert steps.SAVE_REMINDER not in await shown(request())


async def test_a_second_citation_without_a_save_gets_the_reminder():
    text = await shown(request(("cite_pages", CITED)))
    assert text.startswith(CITED) and text.endswith(steps.SAVE_REMINDER)


async def test_a_save_after_the_earlier_citation_clears_the_reminder():
    assert steps.SAVE_REMINDER not in await shown(request(("cite_pages", CITED), ("patch_file", SAVED)))


async def test_a_failed_save_does_not_clear_the_reminder():
    failed = json.dumps({"success": False, "error": "The file was not changed."})
    assert steps.SAVE_REMINDER in await shown(request(("cite_pages", CITED), ("write_file", failed)))


async def test_a_call_inside_execute_gets_no_reminder():
    assert steps.SAVE_REMINDER not in await shown(request(("cite_pages", CITED), key="k/execute/0"))


async def test_a_reminder_result_carries_its_time():
    result = await steps.run_tool_call(cite_agent(), request(("cite_pages", CITED)))
    assert isinstance(result["reminded_at"], float)


async def test_no_reminder_within_the_interval_after_a_reminder(monkeypatch):
    now = 10_000.0
    monkeypatch.setattr(steps.time, "time", lambda: now)
    earlier = now - steps.SAVE_REMINDER_INTERVAL_S + 1
    calls = [("cite_pages", CITED, earlier)] + [("cite_pages", CITED)] * 5
    assert steps.SAVE_REMINDER not in await shown(request(*calls))


async def test_after_the_interval_the_reminder_needs_enough_citations(monkeypatch):
    now = 10_000.0
    monkeypatch.setattr(steps.time, "time", lambda: now)
    earlier = now - steps.SAVE_REMINDER_INTERVAL_S - 1
    few = [("cite_pages", CITED, earlier)] + [("cite_pages", CITED)] * (steps.SAVE_REMINDER_CITATIONS - 2)
    assert steps.SAVE_REMINDER not in await shown(request(*few))
    enough = few + [("cite_pages", CITED)]
    assert steps.SAVE_REMINDER in await shown(request(*enough))


async def test_a_save_after_a_reminder_restarts_the_count(monkeypatch):
    now = 10_000.0
    monkeypatch.setattr(steps.time, "time", lambda: now)
    earlier = now - steps.SAVE_REMINDER_INTERVAL_S - 1
    calls = [("cite_pages", CITED, earlier), ("patch_file", SAVED), ("cite_pages", CITED)]
    assert steps.SAVE_REMINDER in await shown(request(*calls))


async def test_only_the_last_citation_call_of_one_reply_gets_the_reminder():
    def with_reply(call_id):
        req = request(("cite_pages", CITED))
        reply = {"role": "ai", "content": "", "tool_calls": [
            {"id": "c8", "name": "cite_pages", "args": {}}, {"id": "c9", "name": "cite_pages", "args": {}}]}
        messages = [m.model_dump() for m in req.messages] + [reply]
        return req.model_copy(update={"messages": [type(req.messages[0])(**m) for m in messages],
                                      "call": req.call.model_copy(update={"id": call_id})})

    assert steps.SAVE_REMINDER not in await shown(with_reply("c8"))
    assert steps.SAVE_REMINDER in await shown(with_reply("c9"))
