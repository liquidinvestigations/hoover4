"""Verify stored chat control decisions and actions with database and service fakes.

The tests read each row written by control_event. The integration suite verifies the Temporal workflow.
"""

import asyncio
import json
from dataclasses import replace

import pytest
from temporalio.testing import ActivityEnvironment

from database import agent_runs
from tasks.P_agent import activities, control_steps, steps, stream_writer
from tasks.P_agent.control import coordinator, definitions, registry
from tasks.P_agent.control.model import action_id, digest, freeze

RUN_ID = "0b5e3c1a-1111-4222-8333-944455556666"

SKILLS = {
    "spreadsheets": {"text": "Skill `spreadsheets`.\n\nRead tables.", "description": "tables",
                     "group": "technique", "tools": ["table_page"], "terms": "", "not_for": ""},
    "web_research": {"text": "Skill `web_research`.\n\nSearch the web.", "description": "web",
                     "group": "technique", "tools": ["web_search"], "terms": "", "not_for": ""},
    "emails": {"text": "Skill `emails`.\n\nRead e-mails.", "description": "e-mails",
               "group": "technique", "tools": ["doc_email"], "terms": "", "not_for": ""},
    "citation": {"text": "Skill `citation`.\n\nCite.", "description": "cite", "group": "general",
                 "tools": ["cite_documents"], "terms": "", "not_for": ""},
    "report": {"text": "Skill `report`.", "description": "files", "group": "general",
               "tools": ["write_file"], "terms": "", "not_for": ""},
}
#: An opening request that asks for a file, so the preparation loads the report skill.
REPORT_REQUEST = "Write a report on the Fortress payments."


def _row(**changes):
    base = dict(run_id=RUN_ID, username="u", session_id="s", turn_seq=4, thread_id=RUN_ID,
                queue="chat-model-queue", start_seq=5, next_seq=5)
    base.update(changes)
    return agent_runs.RunRow(**base)


class _Agent:
    """The agent service: the snapshot, the visible skills and the call normalization."""

    def __init__(self):
        self.visible = []
        self.requests = []

    def __call__(self, params, path, body, seconds):
        self.requests.append((path, body))
        if path == "/control_snapshot" and body.get("visibility_only"):
            return {"visible_skills": list(self.visible)}
        if path == "/control_snapshot":
            return {"revision": "assets-1", "system_prompt": "PROMPT dated 2026-10-08",
                    "system_prompt_digest": "p", "prompt_override": False, "skills": SKILLS,
                    "callable_tools": ["read_page", "web_search", "read_skill", "read_documents",
                                       "search_collections", "cite_documents", "table_page"],
                    "catalogue_version": "cat", "profile": "full_research"}
        if path == "/policy_calls":
            return {"entries": [{"id": c["id"], "name": c["name"], "args": c["args"],
                                 "kind": "parallel", "page_share": 24000, "retry": True}
                                for c in body["calls"]]}
        raise AssertionError(path)


@pytest.fixture(autouse=True)
def step_events(monkeypatch):
    from database import agent_step_events

    recorded = []
    monkeypatch.setattr(agent_step_events, "record", recorded.append)
    return recorded


@pytest.fixture
def store(monkeypatch):
    written = {"messages": [], "chat": [], "run": [], "row": _row(), "session_citations": []}

    def write_message(username, session_id, thread_id, run_id, message):
        written["messages"] = [m for m in written["messages"] if m.idx != message.idx]
        written["messages"].append(message)
        written["messages"].sort(key=lambda m: m.idx)

    def write_run(row, **changes):
        written["run"].append(changes)
        written["row"] = replace(written["row"], **changes)

    monkeypatch.setattr(agent_runs, "write_message", write_message)
    monkeypatch.setattr(agent_runs, "read_messages", lambda *a: list(written["messages"]))
    monkeypatch.setattr(agent_runs, "read_run", lambda *a: written["row"])
    monkeypatch.setattr(agent_runs, "write_run", write_run)
    monkeypatch.setattr(agent_runs, "read_earlier_threads", lambda *a: [])
    monkeypatch.setattr(agent_runs, "read_session_tool_messages",
                        lambda u, s, name: {RUN_ID: list(written["session_citations"])})
    monkeypatch.setattr(activities, "_insert_chat_row",
                        lambda u, s, seq, role, **f: written["chat"].append(
                            {"seq": seq, "role": role, **f}))
    monkeypatch.setattr(stream_writer, "_chat_model", lambda: "test-model")
    written["agent"] = _Agent()
    monkeypatch.setattr(coordinator, "_agent_post", written["agent"])
    monkeypatch.setattr(coordinator.Services, "_backend", lambda *a: {"collections": [{"collectionname": "testdata"}], "partial": False, "word_counts": [], "suggestions": []})
    written["messages"].append(agent_runs.RunMessageRow(
        idx=0, role="human", content="Find the payments to Fortress in the spreadsheets.",
        run_id=RUN_ID))
    return written


def _definition(rules, limits=None):
    return {"id": "test", "schema_version": 1, "rules": rules, "limits": limits or {}}


def _pin(store, monkeypatch, raw):
    definition = definitions.validate(raw)
    monkeypatch.setattr(definitions, "resolve", lambda profile: definition)
    return definition


def _hook(hook, anchor_idx=-1, draft_kind="", limit=False, internet=True, seconds=5.0):
    return ActivityEnvironment().run(control_steps.control_event, control_steps.ControlParams(
        run_id=RUN_ID, username="u", session_id="s", hook=hook, anchor_idx=anchor_idx,
        allowed_collections=["testdata"],
        draft_kind=draft_kind, model_limit_reached=limit, internet_tools=internet,
        deadline_seconds=seconds))


def _ai(idx, calls=(), content="", origin=None, step_no=1):
    usage = {"step_no": step_no} if origin is None else {"origin": origin}
    entries = [{"id": c[0], "name": c[1], "args": c[2], "position": i, "seq": 10 + i,
                "kind": "parallel"} for i, c in enumerate(calls)]
    return agent_runs.RunMessageRow(idx=idx, role="ai", content=content, run_id=RUN_ID,
                                    tool_calls_json=json.dumps(entries), usage_json=json.dumps(usage))


def _tool(idx, call_id, name, content, status="ok", evidence=()):
    return agent_runs.RunMessageRow(idx=idx, role="tool", content=json.dumps(content),
                                    tool_call_id=call_id, tool_name=name, run_id=RUN_ID,
                                    usage_json=json.dumps({"status": status,
                                                           "evidence": list(evidence)}))


PREPARE = {"id": "prepare", "hook": "turn_started", "handler": "preparation", "priority": 10,
           "frequency": "turn", "parameters": {"report_skill": True}}
OBJECTS = {"id": "objects", "hook": "tool_batch_completed", "handler": "result_skills",
           "priority": 20, "frequency": "visible_revision",
           "parameters": {"objects": {"spreadsheets": ["table"]},
                          "events": {"citation": "first_read"}}}
READS = {"id": "reads", "hook": "tool_batch_completed", "handler": "web_reads", "priority": 30,
         "frequency": "event", "parameters": {"mode": "rank", "max_urls": 6}}
L4 = {"id": "l4", "hook": "tool_batch_completed", "handler": "discovery", "priority": 50,
      "frequency": "turn", "parameters": {"min_unread": 2}}
# ------------------------------------------------------------------ identities and types


def test_digests_are_canonical_and_reject_non_finite_numbers():
    assert digest({"b": 1, "a": [1, 2]}) == digest({"a": [1, 2], "b": 1})
    assert digest([1, 2]) != digest([2, 1])
    with pytest.raises(ValueError):
        digest({"x": float("nan")})
    assert action_id("e", "r", "t", 0) == action_id("e", "r", "t", 0) != action_id("e", "r", "t", 1)


def test_frozen_parameters_cannot_be_changed_by_a_handler():
    frozen = freeze({"a": {"b": [1, 2]}})
    with pytest.raises(TypeError):
        frozen["a"]["b"] = 3
    assert isinstance(frozen["a"]["b"], tuple)


# ------------------------------------------------------------------ definitions


@pytest.mark.parametrize("rule, fault", [
    ({**PREPARE, "handler": "missing"}, "unknown handler 'missing'"),
    ({**PREPARE, "hook": "later"}, "unknown hook 'later'"),
    ({**PREPARE, "parameters": {"report_skill": "yes"}}, "report_skill must be true or false"),
    ({**READS, "parameters": {"mode": "random"}}, "mode must be rank"),
    ({**PREPARE, "frequency": "always"}, "unknown frequency"),
])
def test_an_invalid_definition_names_its_fault(rule, fault):
    with pytest.raises(registry.ControlConfigError, match=fault):
        definitions.validate(_definition([rule]))


def test_a_handler_with_another_interface_version_is_a_configuration_error(tmp_path, monkeypatch):
    handlers = tmp_path / "handlers"
    handlers.mkdir()
    (handlers / "old.py").write_text("class Handler:\n    api_version = 0\n"
                                     "    def validate(self, p): pass\n"
                                     "    async def evaluate(self, *a): pass\n")
    (handlers / "manifest.json").write_text(json.dumps({"handlers": [
        {"name": "old", "module": "old.py", "api_version": 1}]}))
    monkeypatch.setenv(registry.CONTROL_DIR_ENV, str(tmp_path))
    try:
        with pytest.raises(registry.ControlConfigError, match="interface version 0"):
            registry.load(refresh=True)
        (handlers / "manifest.json").write_text(json.dumps({"handlers": [
            {"name": "discovery", "module": "old.py", "api_version": 1}]}))
        with pytest.raises(registry.ControlConfigError, match="registered twice"):
            registry.load(refresh=True)
        (handlers / "manifest.json").write_text(json.dumps({"handlers": [
            {"name": "outside", "module": "../x.py", "api_version": 1}]}))
        with pytest.raises(registry.ControlConfigError, match="inside"):
            registry.load(refresh=True)
    finally:
        monkeypatch.delenv(registry.CONTROL_DIR_ENV)
        registry.load(refresh=True)


def test_the_built_in_definitions_resolve(monkeypatch):
    # The built-in activation only: a deployment's control directory can select another.
    monkeypatch.delenv(registry.CONTROL_DIR_ENV, raising=False)
    assert definitions.resolve("full_research").id == "chat-deterministic"
    assert definitions.resolve("internal_search").id == "chat-deterministic"
    record = definitions.resolve("full_research").record()
    assert definitions.pinned(record).revision == record["revision"]
    assert definitions.stale_rules(definitions.pinned(record)) == []


def test_a_run_keeps_its_pinned_revision_after_a_new_activation(store, monkeypatch):
    first = _pin(store, monkeypatch, _definition([]))
    _hook("turn_started", 0)
    second = definitions.validate(_definition([L4]))
    monkeypatch.setattr(definitions, "resolve", lambda profile: second)
    _hook("turn_started", 0)
    control = store["messages"][0].usage["control"]
    assert control["definition"]["revision"] == first.revision != second.revision
    store["messages"] = store["messages"][:1]
    store["messages"][0] = agent_runs.RunMessageRow(idx=0, role="human", content="new turn",
                                                    run_id=RUN_ID)
    _hook("turn_started", 0)
    assert store["messages"][0].usage["control"]["definition"]["revision"] == second.revision


def test_a_turn_without_control_records_keeps_the_earlier_behavior(store):
    store["messages"].append(_ai(1, content="An answer."))
    store["row"] = _row(result="An answer.")
    outcome = _hook("answer_drafted", draft_kind="answer")
    assert not outcome.round and outcome.calls == []
    assert store["chat"] == []


# ------------------------------------------------------------------ preparation and skills


def test_preparation_loads_the_report_skill_and_pins_assets(store, monkeypatch):
    _pin(store, monkeypatch, _definition([PREPARE]))
    store["messages"][0] = replace(store["messages"][0], content=REPORT_REQUEST)
    outcome = _hook("turn_started", 0)
    assert [c.name for c in outcome.calls] == ["read_skill"]
    ai = next(m for m in store["messages"] if m.role == "ai")
    assert ai.usage["origin"] == "policy" and "step_no" not in ai.usage
    assert [c["args"]["name"] for c in ai.tool_calls] == ["report"]
    assert [c.seq for c in outcome.calls] == [5]
    assert store["row"].next_seq == 6
    control = store["messages"][0].usage["control"]
    assert control["assets"]["system_prompt"] == "PROMPT dated 2026-10-08"
    assert steps.pinned_control(store["messages"])["skills"]["spreadsheets"].startswith("Skill")
    decision = control["decisions"]["turn_started"]
    assert decision["status"] == "applied"

def test_a_stored_decision_is_reused_without_a_second_evaluation(store, monkeypatch):
    _pin(store, monkeypatch, _definition([PREPARE]))
    store["messages"][0] = replace(store["messages"][0], content=REPORT_REQUEST)
    first = _hook("turn_started", 0)
    normalized = [p for p, _ in store["agent"].requests if p == "/policy_calls"]
    # A worker restart repeats the activity. The decision and its rows are reused.
    second = _hook("turn_started", 0)
    assert [p for p, _ in store["agent"].requests if p == "/policy_calls"] == normalized
    assert [c.call_id for c in first.calls] == [c.call_id for c in second.calls]
    assert len([m for m in store["messages"] if m.role == "ai"]) == 1

def test_a_missing_action_row_is_written_at_its_reserved_position(store, monkeypatch):
    _pin(store, monkeypatch, _definition([PREPARE]))
    store["messages"][0] = replace(store["messages"][0], content=REPORT_REQUEST)
    _hook("turn_started", 0)
    ai = next(m for m in store["messages"] if m.role == "ai")
    store["messages"] = [m for m in store["messages"] if m.role != "ai"]
    _hook("turn_started", 0)
    again = next(m for m in store["messages"] if m.role == "ai")
    assert (again.idx, again.tool_calls) == (ai.idx, ai.tool_calls)


def _search_batch(store, hits, idx=1):
    store["messages"] += [
        _ai(idx, [("s1", "search_collections", {"queries": ["fortress"]})]),
        _tool(idx + 1, "s1", "search_collections", {"items": hits})]


def test_a_policy_batch_loads_a_skill_and_starts_no_reads(store, monkeypatch):
    _pin(store, monkeypatch, _definition([OBJECTS, READS]))
    _hook("turn_started", 0)
    store["messages"] += [
        _ai(1, [("p1", "read_page", {"urls": ["https://a.example/x"]})], origin="policy"),
        _tool(2, "p1", "read_page", "## A\nhttps://a.example/x\nText.", evidence=[
            {"kind": "document_read", "status": "ok", "reference": {"url": "https://a.example/x"}}]),
        _ai(3, [("w1", "web_search", {"query": "x"})], origin="policy"),
        _tool(4, "w1", "web_search", {"results": [{"url": "https://b.example/1"},
                                                   {"url": "https://b.example/2"}]})]
    outcome = _hook("tool_batch_completed", anchor_idx=3)
    assert outcome.calls == []
    first = _hook("tool_batch_completed", anchor_idx=1)
    # The automatic page read is the first read and the first page read of the turn.
    assert [c.name for c in first.calls] == ["read_skill", "read_skill"]
    ai = [m for m in store["messages"] if m.role == "ai"][-1]
    assert sorted(c["args"]["name"] for c in ai.tool_calls) == ["citation", "web_research"]


# ------------------------------------------------------------------ discovery


def _web_batch(store, idx, urls_by_search, origin=None):
    calls = [(f"w{idx}-{k}", "web_search", {"query": f"q{k}"}) for k in range(len(urls_by_search))]
    store["messages"].append(_ai(idx, calls, origin=origin))
    for k, urls in enumerate(urls_by_search):
        store["messages"].append(_tool(idx + 1 + k, calls[k][0], "web_search",
                                       {"results": [{"url": u} for u in urls]}))


def test_rank_reads_take_each_address_once_and_skip_read_pages(store, monkeypatch):
    _pin(store, monkeypatch, _definition([READS]))
    _hook("turn_started", 0)
    store["messages"] += [
        _ai(1, [("r0", "read_page", {"urls": ["https://a.example/done"]})]),
        _tool(2, "r0", "read_page", "x", evidence=[
            {"kind": "document_read", "status": "ok", "reference": {"url": "https://a.example/done"}}])]
    _web_batch(store, 3, [["https://a.example/1", "https://a.example/done", "https://a.example/2"],
                          ["https://a.example/2#frag", "https://a.example/3"]])
    outcome = _hook("tool_batch_completed", anchor_idx=3)
    [call] = outcome.calls
    ai = next(m for m in store["messages"] if m.idx == call.ai_idx)
    assert ai.tool_calls[0]["args"]["urls"] == [
        "https://a.example/1", "https://a.example/2#frag", "https://a.example/3"]


def test_l4_notes_a_single_page_read_once_per_turn(store, monkeypatch):
    _pin(store, monkeypatch, _definition([L4]))
    _hook("turn_started", 0)
    _web_batch(store, 1, [["https://a.example/1", "https://a.example/2", "https://a.example/3"]])
    _hook("tool_batch_completed", anchor_idx=1)
    store["messages"] += [_ai(3, [("r", "read_page", {"urls": ["https://a.example/1"]})]),
                          _tool(4, "r", "read_page", "x")]
    _hook("tool_batch_completed", anchor_idx=3)
    note = store["messages"][-1]
    assert note.role == "human" and "one read_page call" in note.content
    assert stream_writer.starts_round(note) is False
    assert store["chat"][-1]["tool_name"] == coordinator.BATCH_NOTE_NAME
    store["messages"] += [_ai(6, [("r2", "read_page", {"urls": ["https://a.example/2"]})]),
                          _tool(7, "r2", "read_page", "x")]
    _hook("tool_batch_completed", anchor_idx=6)
    assert sum(m.role == "human" for m in store["messages"]) == 2


def _draft(store, text, idx=None):
    idx = idx if idx is not None else max(m.idx for m in store["messages"]) + 1
    store["messages"].append(_ai(idx, content=text, step_no=idx))
    store["row"] = replace(store["row"], result=text)


# ------------------------------------------------------------------ repair rounds


def _cited_answer(store, text="The memo sets the budget [D1]."):
    _draft(store, text)


def test_the_step_limit_stops_the_repair_round(store, monkeypatch):
    _pin(store, monkeypatch, _definition([]))
    _hook("turn_started", 0)
    _cited_answer(store)
    assert not _hook("answer_drafted", draft_kind="answer", limit=True).round


# ------------------------------------------------------------------ cancellation


def test_a_stopped_run_writes_no_action(store, monkeypatch):
    _pin(store, monkeypatch, _definition([PREPARE]))
    store["row"] = _row(state="cancelled")
    outcome = _hook("turn_started", 0)
    assert outcome.closed and len(store["messages"]) == 1 and store["chat"] == []


def test_a_cancelled_evaluation_writes_no_decision(store, monkeypatch):
    _pin(store, monkeypatch, _definition([PREPARE]))

    async def cancel(*_args):
        raise asyncio.CancelledError()
    monkeypatch.setattr(coordinator, "evaluate", cancel)
    with pytest.raises(BaseException):
        _hook("turn_started", 0)
    assert "decisions" not in store["messages"][0].usage.get("control", {}) or \
        not store["messages"][0].usage["control"]["decisions"]
    assert not any(m.role == "ai" for m in store["messages"])


# ------------------------------------------------------------------ the thread contracts


def test_a_policy_reply_is_not_a_model_reply_for_recovery_and_rounds():
    policy = _ai(3, [("p", "read_page", {"urls": ["u"]})], origin="policy")
    model = _ai(1, [("m", "web_search", {"query": "x"})], content="Planning prose.")
    assert "step_no" not in policy.usage
    messages = [agent_runs.RunMessageRow(idx=0, role="human", content="q"), model, policy]
    assert [c.call_id for c in activities.pending_calls(None, messages)] == ["p"]
    assert stream_writer.round_view(messages)[0] == ""


def test_identical_shared_calls_carry_one_share_key():
    assert steps.share_key("web_search", {"query": "a"}) == steps.share_key("web_search", {"query": "a"})
    assert steps.share_key("web_search", {"query": "a"}) != steps.share_key("web_search", {"query": "b"})
    assert steps.share_key("write_todo", {"items": []}) == ""
    assert steps.share_key("browser_click", {"ref": "1"}) == ""


@pytest.mark.parametrize("usage, content, shared", [
    ({"status": "ok", "evidence": [{"status": "ok"}]}, {"results": []}, True),
    ({"status": "ok", "evidence": [{"status": "partial"}]}, {"items": []}, False),
    ({"status": "error"}, {"error": "x"}, False),
    ({"status": "ok"}, {"success": False}, False),
])
def test_only_a_complete_result_is_shared(usage, content, shared):
    message = agent_runs.RunMessageRow(idx=2, role="tool", content=json.dumps(content),
                                       usage_json=json.dumps(usage))
    assert steps.complete_result(message) is shared


def _progress_context(previous=None, batch=(), steps_count=0):
    from tasks.P_agent.control.model import PolicyContext
    return PolicyContext(run_id=RUN_ID, thread_id=RUN_ID, profile="internal_search:documents",
                         definition_revision="test", request="Find a missing name", callable_tools=frozenset({"search_collections", "search_passages"}),
                         listed_skills=freeze({}), visible_skills=frozenset(), results=tuple(batch), batch=tuple(batch),
                         turn=freeze({"progress": previous or {}}), counters=freeze({"model_steps": steps_count}),
                         capabilities=frozenset({"documents"}), collections=("testdata",))


def test_progress_escalation_resets_units_and_ends_after_six_steps():
    from tasks.P_agent.control.handlers.progress import Handler
    from tasks.P_agent.control.facts import ResultFact
    from tasks.P_agent.control.model import ControlEvent, plain
    event = ControlEvent("batch", "tool_batch_completed", 1, "model")
    fact = ResultFact("s", "search_collections", 1, 2, "model", "ok", {"query": '"missing"'}, item_count=0)
    handler = Handler()
    previous = {}
    for n in range(9):
        result = asyncio.run(handler.evaluate(event, _progress_context(previous, (fact,), n), {}, object()))
        previous = plain(result.facts)
    assert previous["level"] == 3 and previous["strongest_step"] == 8
    result = asyncio.run(handler.evaluate(event, _progress_context(previous, (replace(fact, keyword_sources=("new",)),), 9), {}, object()))
    assert result.facts["units"] == 0 and result.facts["level"] == 0
    result = asyncio.run(handler.evaluate(event, _progress_context(plain(result.facts), (fact,), 14), {}, object()))
    assert [a.kind for a in result.actions] == []


@pytest.mark.parametrize("name", ["doc_search_text", "pdf_search", "table_search_cells"])
def test_document_keyword_match_resets_progress_once(name):
    from tasks.P_agent.control.facts import result_facts
    from tasks.P_agent.control.handlers.progress import Handler
    from tasks.P_agent.control.model import ControlEvent, plain
    args = {"collection": "c", "file_hash": "a" * 16, "query": "needle"}
    messages = [_ai(1, [("s", name, args)]), _tool(2, "s", name,
                {"items": [{"page": 1}], "hit_count": 913, "keyword_sources": ["c/" + "a" * 16]})]
    facts = result_facts(messages)
    event = ControlEvent("batch", "tool_batch_completed", 1, "model")
    previous = {"level": 1, "units": 2}
    result = asyncio.run(Handler().evaluate(event, _progress_context(previous, facts, 2), {}, object()))
    assert result.facts["units"] == 0 and result.facts["level"] == 0
    again = asyncio.run(Handler().evaluate(event, _progress_context(plain(result.facts), facts, 3), {}, object()))
    assert len(again.facts["sources"]) == 1
    assert again.facts["searches"][-1]["name"] == name
    assert again.facts["units"] == 1


def _trace(params):
    """Run one fixed operation trace through the progress handler. Returns the ledger after
    each batch and every action."""
    from tasks.P_agent.control.facts import ResultFact
    from tasks.P_agent.control.handlers.progress import Handler
    from tasks.P_agent.control.model import ControlEvent, plain

    search = ResultFact("s", "search_collections", 1, 2, "model", "ok", {"query": '"missing"'}, item_count=0)
    write = ResultFact("w", "write_file", 1, 2, "model", "ok", {"name": "a.md"}, file_version=("a.md", 1, True))
    same = replace(write, file_version=("a.md", 1, False))
    failed = replace(write, status="error", file_version=())
    batches = [search] * 4 + [write, write, same, failed] + [search] * 12
    previous, ledgers, actions = {}, [], []
    for step, fact in enumerate(batches):
        event = ControlEvent(f"b{step}", "tool_batch_completed", 1, "model")
        result = asyncio.run(Handler().evaluate(event, _progress_context(previous, (fact,), step), params, object()))
        previous = plain(result.facts)
        ledgers.append(previous)
        actions.append([(a.kind, a.target_id) for a in result.actions])
    return ledgers, actions


def test_new_file_versions_reset_the_level_and_unchanged_or_failed_writes_do_not():
    ledgers, _actions = _trace({})
    assert ledgers[3]["level"] == 1 and ledgers[4]["level"] == 0 and ledgers[4]["units"] == 0
    assert [ledger["file_versions"] for ledger in ledgers[4:8]] == [["a.md@1"]] * 4
    # The repeated identity, the unchanged write and the failed write each add a unit.
    assert [ledger["units"] for ledger in ledgers[5:8]] == [1, 2, 0] and ledgers[7]["level"] == 1


def test_a_policy_batch_changes_no_progress_state():
    from tasks.P_agent.control.facts import ResultFact
    from tasks.P_agent.control.handlers.progress import Handler
    from tasks.P_agent.control.model import ControlEvent, plain

    previous = {"level": 2, "units": 1, "strongest_step": None}
    fact = ResultFact("p", "read_page", 1, 2, "policy", "ok", {"urls": ["https://a.example"]})
    event = ControlEvent("policy", "tool_batch_completed", 1, "policy")
    result = asyncio.run(Handler().evaluate(event, _progress_context(previous, (fact,), 5), {}, object()))
    assert plain(result.facts) == previous and not result.actions


def test_all_default_handlers_run_without_web_tools():
    from tasks.P_agent.control.model import ControlEvent
    definition = definitions.resolve("internal_search:documents")
    services = coordinator.Services(coordinator.Deadline(5), [])
    context = replace(_progress_context(), listed_skills=freeze(SKILLS))
    for hook in ("turn_started", "tool_batch_completed", "answer_drafted"):
        results = asyncio.run(coordinator.evaluate(definition, ControlEvent(hook, hook, 0, "model"), context, services, services.deadline))
        assert all(record["status"] in ("ok", "skipped") for _, _, record in results)
        for rule, result, record in results:
            if rule.requires_tools:
                assert record["status"] == "skipped"
            for action in result.actions if result else ():
                assert action.arguments.get("name") not in ("web_research", "browser_use")


def test_skipped_rule_keeps_control_event_successful(store, monkeypatch, step_events):
    rule = {**PREPARE, "requires_tools": ["unavailable_tool"]}
    _pin(store, monkeypatch, _definition([rule]))
    _hook("turn_started")
    events = [event for event in step_events if event.step == "control"]
    assert len(events) == 1
    assert events[0].ok
    assert events[0].error_class == ""


def test_empty_collection_scope_stays_empty_during_preparation(store):
    params = control_steps.ControlParams(run_id=RUN_ID, username="u", session_id="s", allowed_collections=[])
    pinned = coordinator._pin(store["row"], store["messages"], params)
    assert pinned["collections"] == []


def test_empty_pinned_collections_do_not_restore_the_requested_scope(store, monkeypatch):
    from tasks.P_agent.control.model import ControlEvent
    monkeypatch.setattr(coordinator.Services, "_backend", lambda *a: {"collections": []})
    params = control_steps.ControlParams(run_id=RUN_ID, username="u", session_id="s",
                                        allowed_collections=["testdata"])
    pinned = coordinator._pin(store["row"], store["messages"], params)
    event = ControlEvent("start", "turn_started", 0, "runtime")
    context = coordinator._context(store["row"], params, store["messages"], pinned,
                                   event, store["messages"][0])
    assert pinned["collections"] == []
    assert context.collections == ()


@pytest.mark.parametrize("name", ["list_collections", "search_facet_values", "search_histogram", "folder_overview"])
def test_metadata_results_reset_progress_without_keyword_sources(name):
    from tasks.P_agent.control.facts import ResultFact
    from tasks.P_agent.control.handlers.progress import Handler
    from tasks.P_agent.control.model import ControlEvent, plain

    fact = ResultFact("m", name, 1, 2, "model", "ok", {"collection": "testdata"}, item_count=1)
    context = _progress_context({"level": 3, "units": 2, "strongest_step": 0}, (fact,), 20)
    event = ControlEvent("batch", "tool_batch_completed", 1, "model")
    result = asyncio.run(Handler().evaluate(event, context, {}, object()))
    assert result.facts["level"] == 0 and result.facts["units"] == 0
    assert result.facts["strongest_step"] is None and not result.actions
    again = asyncio.run(Handler().evaluate(event, _progress_context(plain(result.facts), (fact,), 21),
                                         {}, object()))
    assert again.facts["units"] == 1


def test_invalid_tool_reply_counts_as_a_refused_call():
    from tasks.P_agent.control.facts import result_facts

    args = {"facets": ["file_type"]}
    messages = [_ai(1, [("bad", "search_facet_values", args)]),
                _tool(2, "bad", "search_facet_values", {"success": False, "error": "invalid_argument"})]
    fact = result_facts(messages)[0]
    assert fact.status == "refused" and fact.repeated


@pytest.mark.parametrize("name,args", [("read_documents", {"collection": "c", "offset": 49000}),
                                     ("read_more", {"continuation": "returned"})])
def test_a_new_successful_read_range_resets_search_escalation(name, args):
    from tasks.P_agent.control.facts import ResultFact
    from tasks.P_agent.control.handlers.progress import Handler
    from tasks.P_agent.control.model import ControlEvent, plain

    fact = ResultFact("read", name, 1, 2, "model", "ok", args, reads=(("hash", "partial"),))
    context = _progress_context({"level": 3, "units": 2, "strongest_step": 0}, (fact,), 20)
    event = ControlEvent("batch", "tool_batch_completed", 1, "model")
    result = asyncio.run(Handler().evaluate(event, context, {}, object()))
    assert result.facts["level"] == 0 and result.facts["units"] == 0 and not result.actions
    again = asyncio.run(Handler().evaluate(event, _progress_context(plain(result.facts), (fact,), 21),
                                         {}, object()))
    assert again.facts["units"] == 1


def test_verified_citations_reset_progress_in_a_partly_failed_batch():
    from tasks.P_agent.control.facts import result_facts
    from tasks.P_agent.control.handlers.progress import Handler
    from tasks.P_agent.control.model import ControlEvent, plain

    messages = [_ai(1, [("cite", "cite_documents", {"citations": [{"collection": "c"}]})]),
                _tool(2, "cite", "cite_documents", {"success": False},
                      evidence=[{"kind": "citation", "status": "ok"},
                                {"kind": "citation", "status": "error"}])]
    fact = result_facts(messages)[0]
    assert fact.verified_citations == 1
    event = ControlEvent("batch", "tool_batch_completed", 1, "model")
    context = _progress_context({"level": 3, "units": 2, "strongest_step": 0}, (fact,), 20)
    result = asyncio.run(Handler().evaluate(event, context, {}, object()))
    assert result.facts["level"] == 0 and result.facts["units"] == 0 and not result.actions
    again = asyncio.run(Handler().evaluate(event, _progress_context(plain(result.facts), (fact,), 21),
                                         {}, object()))
    assert again.facts["units"] == 1


def test_a_control_folder_selects_another_definition(monkeypatch, tmp_path):
    (tmp_path / "definitions").mkdir()
    (tmp_path / "definitions" / "active.json").write_text(json.dumps({"*": "chat-null"}))
    monkeypatch.setenv(registry.CONTROL_DIR_ENV, str(tmp_path))
    try:
        registry.load(refresh=True)
        definition = definitions.resolve("internal_search")
        assert definition.id == "chat-null"
        assert definition.rules == ()
    finally:
        monkeypatch.delenv(registry.CONTROL_DIR_ENV)
        registry.load(refresh=True)
    assert definitions.resolve("internal_search").id == "chat-deterministic"


# ------------------------------------------------------- policies and repairs


def _fact(name, status="ok", args=None, **fields):
    from tasks.P_agent.control.facts import ResultFact
    return ResultFact(fields.pop("call_id", "c"), name, 1, 2, fields.pop("origin", "model"), status,
                      args or {}, **fields)


def _event(origin="model"):
    from tasks.P_agent.control.model import ControlEvent
    return ControlEvent("batch", "tool_batch_completed", 1, origin)


def test_a_policy_batch_changes_no_progress_count():
    from tasks.P_agent.control.handlers.progress import Handler
    previous = {"level": 2, "units": 2, "sources": ["x"]}
    batch = (_fact("read_skill", origin="policy"),)
    result = asyncio.run(Handler().evaluate(_event("policy"), _progress_context(previous, batch, 4),
                                            {}, object()))
    assert result.actions == () and plain_facts(result) == previous


def plain_facts(result):
    from tasks.P_agent.control.model import plain
    return plain(result.facts)


def test_new_file_versions_are_progress_and_an_unchanged_patch_is_not():
    from tasks.P_agent.control.handlers.progress import Handler
    handler, previous = Handler(), {"level": 1, "units": 2}
    patch = _fact("patch_file", file_version=("report.md", 2, True))
    first = asyncio.run(handler.evaluate(_event(), _progress_context(previous, (patch,), 3),
                                         {}, object()))
    assert first.facts["level"] == 0 and first.facts["units"] == 0
    assert list(first.facts["file_versions"]) == ["report.md@2"]
    # Several valid patches never count as a stalled search.
    second_patch = _fact("patch_file", file_version=("report.md", 3, True))
    second = asyncio.run(handler.evaluate(_event(), _progress_context(plain_facts(first), (second_patch,), 4),
                                          {}, object()))
    assert second.facts["units"] == 0
    unchanged = _fact("patch_file", file_version=("report.md", 3, False))
    third = asyncio.run(handler.evaluate(_event(), _progress_context(plain_facts(second), (unchanged,), 5),
                                         {}, object()))
    assert third.facts["units"] == 1
    failed = _fact("write_file", status="error", error_code="invalid_argument")
    fourth = asyncio.run(handler.evaluate(_event(), _progress_context(plain_facts(third), (failed,), 6),
                                          {}, object()))
    assert fourth.facts["units"] == 2


def test_the_task_of_a_turn_comes_from_its_opening_usage():
    from tasks.P_agent.control import facts as F
    plain_turn = agent_runs.RunMessageRow(idx=0, role="human", content="Find the lease.")
    assert F.task_of(plain_turn) == {"objective": {"text": "Find the lease.", "source": "user"}}
    board = replace(plain_turn, content="Long brief.", usage_json=json.dumps({"task": {
        "objective": {"text": "Name the leader.", "source": "intent"},
        "corrections": [{"text": "Use the 2001 minutes.", "source": "correction-minutes"}],
        "bad": "not a field"}}))
    task = F.task_of(board)
    assert task["objective"]["text"] == "Name the leader." and "bad" not in task
    assert task["corrections"] == [{"text": "Use the 2001 minutes.", "source": "correction-minutes"}]


def test_the_result_triggers_load_the_recovery_skills():
    from tasks.P_agent.control.handlers.result_skills import Handler
    params = {"events": {"report": ["first_write", "workspace_error"],
                         "call_arguments": "argument_error", "document_ids": "unknown_document"}}
    listed = freeze({name: {} for name in ("report", "call_arguments", "document_ids")})

    def loads(batch, earlier=()):
        context = replace(_progress_context(), listed_skills=listed,
                          results=tuple(earlier) + tuple(batch), batch=tuple(batch))
        result = asyncio.run(Handler().evaluate(_event(), context, params, object()))
        return sorted(a.target_id for a in result.actions)

    write = _fact("write_file", file_version=("a.md", 1, True))
    assert loads([write]) == ["report"]
    earlier = replace(write, ai_idx=0)
    assert loads([_fact("patch_file", file_version=("a.md", 2, True))], [earlier]) == []
    assert loads([_fact("write_file", status="error", error_code="")]) == ["report"]
    assert loads([_fact("read_documents", status="refused", error_code="invalid_argument")]) == ["call_arguments"]
    assert loads([_fact("read_page", status="error", error_code="invalid_arguments")]) == ["call_arguments"]
    assert loads([_fact("read_documents", status="error", error_code="not_found")]) == ["document_ids"]
    assert loads([_fact("search_collections")]) == []


def test_the_argument_trigger_matches_the_stored_argument_errors():
    """The result shapes are copies of stored tool messages: the agent service error, the
    website route error, and the validation text of a tool server, with and without a
    status in the usage. A refused address and a missing document are not argument errors."""
    from tasks.P_agent.control.facts import result_facts
    from tasks.P_agent.control.handlers.result_skills import Handler

    def raw(idx, call_id, name, text, usage):
        return agent_runs.RunMessageRow(idx=idx, role="tool", content=text, tool_call_id=call_id,
                                        tool_name=name, run_id=RUN_ID, usage_json=json.dumps(usage))

    agent_error = json.dumps({"success": False, "error": "invalid_arguments", "message":
                              "arguments: 'urls' is a required property.", "tool": "read_page"})
    route_error = json.dumps({"error": "invalid_argument", "success": False,
                              "message": "sheet 0 has no column id 0. Its column ids are 1 to 4."})
    validation = ("Error: 1 validation error for call[table_page]\ncolumn\n  Unexpected keyword "
                  "argument [type=unexpected_keyword_argument, input_value='0', input_type=str]")
    validations = ("Error: 2 validation errors for call[cite_documents]\ncitations.list[Citation].0.why2\n"
                   "  Extra inputs are not permitted [type=extra_forbidden]")
    refused = json.dumps({"success": False, "error": "refused: browser_navigate: 'javascript:void(0)' "
                          "is not an http or https URL"})
    cases = {
        "agent": (raw(2, "agent", "read_page", agent_error, {"status": "error", "error_class": "invalid_arguments"}), True),
        "agent-no-usage": (raw(2, "agent-no-usage", "cite_pages", agent_error, {}), True),
        "route": (raw(2, "route", "table_page", route_error, {"status": "ok", "error_class": ""}), True),
        "text": (raw(2, "text", "table_page", validation, {"status": "error", "error_class": "tool_error"}), True),
        "text-no-usage": (raw(2, "text-no-usage", "cite_documents", validations, {}), True),
        "refused": (raw(2, "refused", "browser_navigate", refused, {"status": "ok"}), False),
        "missing": (_tool(2, "missing", "read_documents", {"success": False, "error": "not_found"}, status="error"), False),
    }
    params = {"events": {"call_arguments": "argument_error"}}
    listed = freeze({"call_arguments": {}})
    for call_id, (message, expected) in cases.items():
        facts = result_facts([_ai(1, [(call_id, message.tool_name, {})]), message])
        context = replace(_progress_context(), listed_skills=listed, results=tuple(facts), batch=tuple(facts))
        result = asyncio.run(Handler().evaluate(_event(), context, params, object()))
        loaded = [a.target_id for a in result.actions] == ["call_arguments"]
        assert loaded is expected, (call_id, facts[0].error_code, facts[0].status)


#: The `/tool_call` reply of the agent service for `read_page` with `url` in place of the
#: required list `urls` (`research_agent` test `test_a_url_for_the_urls_list_is_refused_
#: and_the_corrected_call_runs`).
URL_FOR_URLS = {"success": False, "error": "invalid_arguments", "tool": "read_page",
                "message": "arguments: 'urls' is a required property."}


def test_an_argument_error_loads_the_argument_skill_once_while_it_is_visible(store, monkeypatch):
    """A wrong argument name loads `call_arguments`. A second wrong call while the skill is
    visible loads nothing, and the corrected successful call loads nothing."""
    rule = {**OBJECTS, "id": "arguments", "parameters": {"events": {"call_arguments": "argument_error"}}}
    _pin(store, monkeypatch, _definition([rule]))
    monkeypatch.setitem(SKILLS, "call_arguments", {
        "text": "Skill `call_arguments`.\n\nCopy the argument names.", "description": "arguments",
        "group": "general", "tools": [], "terms": "", "not_for": ""})
    _hook("turn_started", 0)
    store["messages"] += [
        _ai(1, [("bad", "read_page", {"url": "https://a.example/x"})]),
        agent_runs.RunMessageRow(idx=2, role="tool", content=json.dumps(URL_FOR_URLS), tool_call_id="bad",
                                 tool_name="read_page", run_id=RUN_ID,
                                 usage_json=json.dumps({"status": "error", "error_class": "invalid_arguments"}))]
    loaded = _hook("tool_batch_completed", anchor_idx=1)
    assert [c.name for c in loaded.calls] == ["read_skill"]
    policy = max(m.idx for m in store["messages"])
    written = next(m for m in store["messages"] if m.idx == loaded.calls[0].ai_idx)
    assert [e["args"] for e in written.tool_calls] == [{"name": "call_arguments"}]
    store["messages"].append(_tool(policy + 1, loaded.calls[0].call_id, "read_skill",
                                   SKILLS["call_arguments"]["text"]))
    store["agent"].visible = ["call_arguments"]
    store["messages"] += [
        _ai(policy + 2, [("bad2", "read_page", {"url": "https://a.example/y"})]),
        agent_runs.RunMessageRow(idx=policy + 3, role="tool", content=json.dumps(URL_FOR_URLS), tool_call_id="bad2",
                                 tool_name="read_page", run_id=RUN_ID, usage_json=json.dumps({}))]
    assert _hook("tool_batch_completed", anchor_idx=policy + 2).calls == []
    store["messages"] += [
        _ai(policy + 4, [("good", "read_page", {"urls": ["https://a.example/x"]})]),
        _tool(policy + 5, "good", "read_page", "## A\nhttps://a.example/x\nText.")]
    assert _hook("tool_batch_completed", anchor_idx=policy + 4).calls == []


def test_argument_errors_have_one_status_and_source_text_stays_a_result():
    """Both argument codes and the validation text give the status `refused`, with or
    without a status in the usage. A successful result that quotes the validation text is
    an ordinary result, and a missing document keeps its own code."""
    from tasks.P_agent.control.facts import result_facts

    def fact(content, usage):
        message = agent_runs.RunMessageRow(idx=2, role="tool", content=content, tool_call_id="c",
                                           tool_name="read_documents", run_id=RUN_ID, usage_json=json.dumps(usage))
        return result_facts([_ai(1, [("c", "read_documents", {})]), message])[0]

    validation = "Error: 1 validation error for call[read_page]\nurls\n  Field required [type=missing]"
    for content in (json.dumps({"success": False, "error": "invalid_arguments"}),
                    json.dumps({"success": False, "error": "invalid_argument"}), validation):
        for usage in ({}, {"status": "error"}, {"status": "ok"}):
            got = fact(content, usage)
            assert (got.status, got.error_code in ("invalid_argument", "invalid_arguments")) == ("refused", True), (content, usage)
    quoted = json.dumps({"success": True, "documents": [{"file_hash": "h", "text": validation}]})
    assert (fact(quoted, {}).status, fact(quoted, {}).error_code) == ("ok", "")
    assert fact("The log says " + validation, {}).status == "ok"
    missing = fact(json.dumps({"success": False, "error": "not_found"}), {})
    assert (missing.status, missing.error_code) == ("error", "not_found")
    forbidden = fact(json.dumps({"success": False, "error": "forbidden"}), {})
    assert (forbidden.status, forbidden.error_code) == ("refused", "forbidden")


def test_result_facts_name_the_file_version_and_the_error_code():
    from tasks.P_agent.control.facts import result_facts
    messages = [_ai(1, [("w", "write_file", {"name": "a.md"}), ("p", "patch_file", {"name": "a.md"}),
                        ("r", "read_documents", {"file_hash": "0" * 64})]),
                _tool(2, "w", "write_file", {"success": True, "name": "a.md", "version": 1}),
                _tool(3, "p", "patch_file", {"success": True, "name": "a.md", "version": 1, "unchanged": True}),
                _tool(4, "r", "read_documents", {"success": False, "error": "not_found"}, status="error")]
    facts = {f.call_id: f for f in result_facts(messages)}
    assert facts["w"].file_version == ("a.md", 1, True)
    assert facts["p"].file_version == ("a.md", 1, False)
    assert facts["r"].error_code == "not_found" and facts["r"].file_version == ()


def test_preparation_loads_the_report_skill_with_no_model_request(store, monkeypatch):
    _pin(store, monkeypatch, _definition([PREPARE]))
    store["messages"][0] = replace(store["messages"][0], content=REPORT_REQUEST)
    outcome = _hook("turn_started", 0)
    assert [c.name for c in outcome.calls] == ["read_skill"]
    decision = store["messages"][0].usage["control"]["decisions"]["turn_started"]
    assert "classifier" not in decision and "classifier_events" not in decision
    assert decision["task_digest"]

def test_model_images_is_validated_pinned_and_sent_to_the_agent():
    plain_def = definitions.validate(_definition([]))
    images = definitions.validate({**_definition([]), "model_images": "on_demand"})
    assert plain_def.model_images == "attach" and images.model_images == "on_demand"
    assert plain_def.revision != images.revision
    with pytest.raises(registry.ControlConfigError, match="model_images"):
        definitions.validate({**_definition([]), "model_images": "sometimes"})
    record = images.record()
    assert definitions.pinned(record).model_images == "on_demand"
    old = {k: v for k, v in plain_def.record().items() if k != "model_images"}
    assert definitions.pinned(old).model_images == "attach"
    opening = agent_runs.RunMessageRow(idx=0, role="human", content="q", usage_json=json.dumps(
        {"control": {"definition": record, "assets": {"system_prompt": "P", "skills": {}}}}))
    assert steps.pinned_control([opening])["model_images"] == "on_demand"
    legacy = replace(opening, usage_json=json.dumps(
        {"control": {"definition": old, "assets": {"system_prompt": "P", "skills": {}}}}))
    assert steps.pinned_control([legacy])["model_images"] == "attach"


def test_an_unchanged_definition_keeps_its_revision_without_the_image_setting():
    raw = _definition([PREPARE])
    assert definitions.validate(raw).revision == definitions.validate({**raw, "model_images": "attach"}).revision


# ------------------------------------------------- output intent, methods and task context


REPORT_REQUESTS = {
    "Write a report on the Fortress payments.": True,
    "Write three files: a.md, b.md and c.md, one for each supplier.": True,
    "Create separate markdown files for each year.": True,
    "Save the list as suppliers.md.": True,
    "Put the results in a file.": True,
    "Draft a memo to the board.": True,
    "Read budget.csv and write a summary to summary.md.": True,
    "Summarize the report titled 'Annual Report 2019'.": False,
    "Find the draft agreement between Enron and Dynegy.": False,
    "Which files are in the folder /archives?": False,
    "List the files in the archive parent.zip.": False,
    "Is there a password in a file in this collection?": False,
    "Make a list of the files that mention Fortress.": False,
    "What does budget.csv say about rent?": False,
    "Who wrote the report on California?": False,
}


@pytest.mark.parametrize("request_text,expected", sorted(REPORT_REQUESTS.items()))
def test_the_report_skill_follows_the_requested_output(request_text, expected):
    """An output action, a file destination or a named output path loads `report`. A report
    title, a draft agreement or a question about files names an input and loads nothing."""
    from tasks.P_agent.control.handlers.preparation import Handler
    from tasks.P_agent.control.model import ControlEvent
    context = replace(_progress_context(), request=request_text,
                      listed_skills=freeze({"report": {}}),
                      task=freeze({"objective": {"text": request_text, "source": "user"}}))
    result = asyncio.run(Handler().evaluate(ControlEvent("start", "turn_started", 0, "runtime"),
                                            context, {}, object()))
    assert [a.target_id for a in result.actions] == (["report"] if expected else [])


def test_the_requested_files_come_from_deliverables_first():
    from tasks.P_agent.control.handlers.preparation import requested_output
    board = {"objective": {"text": "Find the dated events.", "source": "intent"},
             "deliverables": [{"text": "A report file events.md", "source": "intent"}]}
    assert requested_output(board) == {"file": True, "names": ["events.md"], "count": 1}
    several = {"objective": {"text": "Write three files: a.md, b.md and c.md.", "source": "user"}}
    assert requested_output(several) == {"file": True, "names": ["a.md", "b.md", "c.md"], "count": 3}
    inventory = {"objective": {"text": "Which report files are in /archives?", "source": "user"}}
    assert requested_output(inventory)["file"] is False


def _read_page_fact(status="ok", reads=(("https://a.example", "ok"),)):
    return _fact("read_page", status=status, args={"urls": ["https://a.example"]}, reads=reads)


@pytest.mark.parametrize("batch,expected", [
    ([lambda: _fact("web_search", urls=("https://a.example",))], ["web_research"]),
    ([lambda: _fact("web_search", status="error")], []),
    ([lambda: _fact("web_search", origin="policy")], []),
    ([lambda: replace(_read_page_fact(reads=(("https://a.example", "partial"),)), origin="policy")], ["web_research"]),
    ([lambda: _fact("browser_navigate", args={"url": "https://a.example"})], ["browser_use"]),
    ([lambda: _read_page_fact(status="error", reads=())], ["web_research"]),
    ([lambda: _read_page_fact(status="refused", reads=())], []),
    ([lambda: _read_page_fact(reads=(("https://a.example", "partial"),))], ["web_research"]),
    ([lambda: _read_page_fact(reads=(("https://a.example", "error"),))], ["web_research"]),
    ([lambda: _read_page_fact()], ["web_research"]),
    ([lambda: _fact("search_collections")], []),
])
def test_the_method_events_load_the_web_and_browser_skills(batch, expected):
    """The tool results of a method load its skill in every definition.
    The first full page read loads the web method, because it holds the web citation rules."""
    from tasks.P_agent.control.handlers.result_skills import Handler
    facts = tuple(make() for make in batch)
    listed = freeze({"web_research": {}, "browser_use": {}})
    context = replace(_progress_context(), listed_skills=listed, results=facts, batch=facts)
    result = asyncio.run(Handler().evaluate(_event(), context, {}, object()))
    assert sorted(a.target_id for a in result.actions) == expected
    off = asyncio.run(Handler().evaluate(_event(), context, {"methods": False}, object()))
    assert [a.target_id for a in off.actions] == []
    unlisted = replace(context, listed_skills=freeze({}))
    assert asyncio.run(Handler().evaluate(_event(), unlisted, {}, object())).actions == ()


def _document_read_fact(status="ok", reads=(("h1", "ok"),)):
    return _fact("read_documents", status=status, args={"documents": ["h1"]}, reads=reads)


@pytest.mark.parametrize("order,current,legacy", [
    # A direct page read with no web search before it.
    (["page"], [["web_research"]], [["citation", "web_research"]]),
    (["document"], [["citation"]], [["citation"]]),
    (["page", "document"], [["web_research"], ["citation"]], [["citation", "web_research"], []]),
    (["document", "page"], [["citation"], ["web_research"]], [["citation"], ["web_research"]]),
    (["page", "page"], [["web_research"], []], [["citation", "web_research"], []]),
    (["document", "document"], [["citation"], []], [["citation"], []]),
    (["mixed"], [["citation", "web_research"]], [["citation", "web_research"]]),
])
def test_the_first_document_read_loads_citation_and_the_first_page_read_loads_web_research(
        order, current, legacy):
    """Each batch of `order` follows the earlier ones in the same turn. `current` is the
    built-in rule `first_document_read`. `legacy` is a configured definition of an earlier
    revision with `first_read`, which loads `citation` on the first read of either kind. Both
    load `web_research` on the first page read, with no web search before it."""
    from tasks.P_agent.control.handlers.result_skills import Handler
    listed = freeze({"citation": {}, "web_research": {}})
    for event, expected in (("first_document_read", current), ("first_read", legacy)):
        params = {"events": {"citation": event}}
        Handler().validate(params)
        earlier, got = (), []
        for index, kind in enumerate(order):
            batch = {"page": (_read_page_fact(),), "document": (_document_read_fact(),),
                     "mixed": (_document_read_fact(), _read_page_fact())}[kind]
            batch = tuple(replace(f, ai_idx=index + 1) for f in batch)
            context = replace(_progress_context(), listed_skills=listed,
                              results=earlier + batch, batch=batch)
            result = asyncio.run(Handler().evaluate(_event_at(index + 1), context, params, object()))
            got.append(sorted(a.target_id for a in result.actions))
            earlier += batch
        assert got == expected, event


def test_a_web_only_turn_loads_web_research_on_a_page_read_and_no_citation_skill():
    """A web-only run does not list `citation`, so a page read loads only `web_research`,
    also under a legacy definition."""
    from tasks.P_agent.control.handlers.result_skills import Handler
    batch = (_read_page_fact(),)
    context = replace(_progress_context(), listed_skills=freeze({"web_research": {}}),
                      results=batch, batch=batch)
    for events in ({"citation": "first_document_read"}, {"citation": "first_read"}):
        result = asyncio.run(Handler().evaluate(_event(), context, {"events": events}, object()))
        assert [a.target_id for a in result.actions] == ["web_research"]


def _event_at(anchor_idx):
    from tasks.P_agent.control.model import ControlEvent
    return ControlEvent("batch", "tool_batch_completed", anchor_idx, "model")


def test_a_definition_event_replaces_the_method_mapping_of_its_skill():
    from tasks.P_agent.control.handlers.result_skills import Handler
    search = (_fact("web_search"),)
    context = replace(_progress_context(), listed_skills=freeze({"web_research": {}}),
                      results=search, batch=search)
    only_browser = {"events": {"web_research": "browser"}}
    assert asyncio.run(Handler().evaluate(_event(), context, only_browser, object())).actions == ()
    with pytest.raises(ValueError, match="methods"):
        Handler().validate({"methods": "yes"})


def test_a_web_method_loads_once_while_its_text_is_visible(store, monkeypatch):
    """A successful web search loads `web_research` through the stored rule. A second web
    search while the skill text is visible loads nothing."""
    rule = {**OBJECTS, "id": "methods", "parameters": {}}
    _pin(store, monkeypatch, _definition([rule]))
    _hook("turn_started", 0)
    store["messages"].extend([
        _ai(1, [("w1", "web_search", {"queries": ["mill closure"]})]),
        _tool(2, "w1", "web_search", {"results": [{"url": "https://a.example/1"}]}),
    ])
    first = _hook("tool_batch_completed", 1)
    assert [c.name for c in first.calls] == ["read_skill"]
    written = next(m for m in store["messages"] if m.idx == first.calls[0].ai_idx)
    assert [e["args"] for e in written.tool_calls] == [{"name": "web_research"}]
    store["messages"].append(_tool(max(m.idx for m in store["messages"]) + 1, first.calls[0].call_id,
                                   "read_skill", SKILLS["web_research"]["text"]))
    store["agent"].visible = ["web_research"]
    policy = max(m.idx for m in store["messages"])
    store["messages"].extend([
        _ai(policy + 1, [("w2", "web_search", {"queries": ["mill owner"]})]),
        _tool(policy + 2, "w2", "web_search", {"results": [{"url": "https://a.example/2"}]}),
    ])
    assert list(_hook("tool_batch_completed", policy + 1).calls) == []


def test_a_chat_task_keeps_an_earlier_source_restriction_with_its_turn():
    from tasks.P_agent.control import facts as F
    first = F.chat_task("Search only the enron collection. Who approved the talking points?", 1, [])
    assert first["constraints"] == [{"text": "Search only the enron collection.", "source": "user", "turn": 1}]
    follow = F.chat_task("Now write it as a file.", 3, [first])
    # An output request that refers to the earlier work amends the active objective.
    assert follow["objective"] == {"text": "Search only the enron collection. Who approved the talking points?",
                                   "source": "user", "turn": 1}
    assert follow["amendments"] == [{"text": "Now write it as a file.", "source": "user", "turn": 3}]
    assert follow["constraints"] == [{"text": "Search only the enron collection.", "source": "user", "turn": 1}]
    newer = F.chat_task("Do not use the web for this one.", 5, [first, follow])
    assert [c["turn"] for c in newer["constraints"]] == [5, 1]
    legacy = F.chat_task("And the second one?", 2, [{"objective": {"text": "Use only documents from 2001 in the archive.", "source": "user"}}])
    assert legacy["constraints"] == [{"text": "Use only documents from 2001 in the archive.", "source": "user"}]
    assert "constraints" not in F.chat_task("Who approved the talking points?", 1, [])


def test_a_follow_up_turn_records_its_task_and_its_constraint(store, monkeypatch):
    """The earlier turn restricted the collection. The short follow-up keeps that
    restriction in its recorded task."""
    earlier = [agent_runs.RunMessageRow(idx=0, role="human", run_id="earlier",
                                        content="Search only the testdata collection. Who approved the transfer?"),
               agent_runs.RunMessageRow(idx=1, role="ai", run_id="earlier", content="Kim approved it [D1].")]
    current = list(store["messages"])
    monkeypatch.setattr(agent_runs, "read_earlier_threads", lambda *a: ["earlier"])
    monkeypatch.setattr(agent_runs, "read_messages",
                        lambda u, s, thread: earlier if thread == "earlier" else list(store["messages"]))
    store["messages"][0] = replace(current[0], content="Now write two files, a.md and b.md.")
    _pin(store, monkeypatch, _definition([PREPARE]))
    _hook("turn_started", 0)
    control = store["messages"][0].usage["control"]
    # The follow-up amends the earlier objective, which stays the objective of the turn.
    assert control["task"]["objective"]["text"] == "Search only the testdata collection. Who approved the transfer?"
    assert control["task"]["amendments"][0]["text"] == "Now write two files, a.md and b.md."
    assert control["task"]["constraints"][0]["text"] == "Search only the testdata collection."
    state = control["task_state"]
    assert state["request"] == {"turn": 4, "kind": "amendment"}
    assert [(g["names"], g["count"]) for g in state["output_spec"]["groups"]] == [(["a.md", "b.md"], 2)]


# ------------------------------------------------------------------ the pinned task record


def _earlier_turn(thread, request, state=None, files=()):
    """The rows of one ended earlier turn: its opening row, with a stored task record when
    `state` is given, and one successful write for each file name."""
    usage = {"control": {"task_state": state}} if state is not None else {}
    rows = [agent_runs.RunMessageRow(idx=0, role="human", run_id=thread, content=request,
                                     usage_json=json.dumps(usage))]
    for n, name in enumerate(files):
        rows.append(agent_runs.RunMessageRow(idx=1 + 2 * n, role="ai", run_id=thread, content="",
                                             tool_calls_json=json.dumps([{"id": f"w{n}", "name": "write_file",
                                                                          "args": {"name": name}}])))
        rows.append(agent_runs.RunMessageRow(idx=2 + 2 * n, role="tool", run_id=thread, tool_call_id=f"w{n}",
                                             tool_name="write_file",
                                             content=json.dumps({"success": True, "name": name, "version": 1}),
                                             usage_json=json.dumps({"status": "ok"})))
    rows.append(agent_runs.RunMessageRow(idx=99, role="ai", run_id=thread, content="Done."))
    return rows


def _session(store, monkeypatch, turns, request):
    """Pin the current turn after the earlier `turns` ({thread: rows}). Returns the threads
    that the pin read."""
    read = []

    def messages(u, s, thread):
        if thread in turns:
            read.append(thread)
            return turns[thread]
        return list(store["messages"])

    monkeypatch.setattr(agent_runs, "read_earlier_threads", lambda *a: list(turns))
    monkeypatch.setattr(agent_runs, "read_messages", messages)
    store["messages"][0] = replace(store["messages"][0], content=request)
    # No skill load, so the visibility check reads no earlier thread.
    _pin(store, monkeypatch, _definition([{**PREPARE, "parameters": {"report_skill": False}}]))
    _hook("turn_started", 0)
    return read


def test_the_pin_stores_one_task_record_and_a_retry_or_a_code_change_keeps_it(store, monkeypatch):
    from tasks.P_agent.control import task_state as TS
    store["messages"][0] = replace(store["messages"][0], content="Write two memos. Create three reports.")
    _pin(store, monkeypatch, _definition([PREPARE, {**OBJECTS, "id": "objects"}]))
    _hook("turn_started", 0)
    control = store["messages"][0].usage["control"]
    state = control["task_state"]
    assert state["schema_version"] == TS.SCHEMA_VERSION and control["task"] == TS.text_task(state)
    assert [(g["noun"], g["count"]) for g in state["output_spec"]["groups"]] == [("memo", 2), ("report", 3)]

    def changed(*args, **kwargs):
        raise AssertionError("a pinned turn is not interpreted again")

    monkeypatch.setattr(TS, "derive", changed)
    _hook("turn_started", 0)
    assert store["messages"][0].usage["control"]["task_state"] == state
    store["messages"].extend([_ai(1, [("s1", "search_collections", {"query": "x"})]),
                              _tool(2, "s1", "search_collections", {"items": []})])
    _hook("tool_batch_completed", 1)
    decision = store["messages"][1].usage["control"]["decisions"]["tool_batch_completed"]
    assert decision["task_state_digest"] == digest(state)


def test_a_continuation_reads_the_stored_record_of_the_last_turn_and_its_files(store, monkeypatch):
    from tasks.P_agent.control import task_state as TS
    earlier = TS.derive("Write two memos on the loans.", 3, None)
    turns = {"t1": _earlier_turn("t1", "Find the lease."),
             "t3": _earlier_turn("t3", "Write two memos on the loans.", earlier, files=("memo-1.md",))}
    read = _session(store, monkeypatch, turns, "Continue.")
    assert read == ["t3"], "a stored record ends the read"
    state = store["messages"][0].usage["control"]["task_state"]
    assert state["request"] == {"turn": 4, "kind": "continuation"} and state["objective"]["turn"] == 3
    assert state["output_spec"]["delivered_before"] == [{"name": "memo-1.md", "version": 1, "turn": 3}]
    assert state["reconstruction"]["complete"] is True
    assert TS.delivery(state, ["memo-2.md"])["state"] == "complete"


def test_a_legacy_session_is_rebuilt_from_its_requests_within_the_bound(store, monkeypatch):
    from tasks.P_agent.control import coordinator as CO, task_state as TS
    turns = {"t1": _earlier_turn("t1", "Use only the enron collection. Do not use the web. Who signed the lease?"),
             "t2": _earlier_turn("t2", "You may now use the web. Write a report.")}
    _session(store, monkeypatch, turns, "Continue.")
    state = store["messages"][0].usage["control"]["task_state"]
    assert state["reconstruction"] == {"turns_read": 2, "complete": True, "source": "records"}
    assert TS.source_scope(state)["web"] == "allowed"
    assert [g["noun"] for g in state["output_spec"]["groups"]] == ["report"]
    assert "Do not use the web." not in json.dumps(store["messages"][0].usage["control"]["task"])
    many = {f"t{n}": _earlier_turn(f"t{n}", f"Find payment {n}.") for n in range(CO.MAX_TASK_THREADS + 3)}
    store["messages"][0] = replace(store["messages"][0], usage_json="{}")
    read = _session(store, monkeypatch, many, "Continue.")
    assert len(read) == CO.MAX_TASK_THREADS
    state = store["messages"][0].usage["control"]["task_state"]
    assert state["reconstruction"]["complete"] is False
    assert not TS.complete_interpretation(state)


def test_a_board_turn_keeps_its_structured_task_as_its_record(store, monkeypatch):
    task = {"objective": {"text": "Name the leader.", "source": "intent"},
            "deliverables": [{"text": "A report file leader.md", "source": "intent"}]}
    store["messages"][0] = replace(store["messages"][0], content="Long brief. Write two memos.",
                                   usage_json=json.dumps({"task": task}))
    _pin(store, monkeypatch, _definition([PREPARE]))
    _hook("turn_started", 0)
    control = store["messages"][0].usage["control"]
    assert "task" not in control
    assert control["task_state"]["objective"]["text"] == "Name the leader."
    assert [g["names"] for g in control["task_state"]["output_spec"]["groups"]] == [["leader.md"]]

