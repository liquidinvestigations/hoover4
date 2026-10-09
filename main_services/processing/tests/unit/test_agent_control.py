"""Verify stored chat control decisions and actions with database and service fakes.

The tests read each row written by control_event. The integration suite verifies the Temporal workflow.
"""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from temporalio.testing import ActivityEnvironment

from database import agent_runs
from tasks.P_agent import activities, citations, control_steps, steps, stream_writer
from tasks.P_agent.control import classifier as C
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
}


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
    monkeypatch.setattr(C, "write_events", lambda *a: None)
    monkeypatch.delenv(C.CLASSIFIER_URL_ENV, raising=False)
    written["messages"].append(agent_runs.RunMessageRow(
        idx=0, role="human", content="Find the payments to Fortress in the spreadsheets.",
        run_id=RUN_ID))
    return written


class _Route:
    """The systemone route: answers by question id, or a status for every request."""

    def __init__(self, answers=None, status=200, delay=0.0, raw="[]"):
        self.answers = answers or {}
        self.status = status
        self.delay = delay
        self.raw = raw
        self.bodies = []

    def __call__(self, session, url, body, key, timeout):
        import time

        self.bodies.append((url, body))
        if self.delay:
            time.sleep(self.delay)
        if url.endswith(C.RAW_PATH):
            return 200, {"choices": [{"message": {"content": self.raw}}]}, ""
        if self.status != 200:
            return self.status, {"error": "x"}, ""
        out = {}
        for qid, question in body["questions"].items():
            if qid in self.answers:
                out[qid] = self.answers[qid]
            elif question["type"] == "noul":
                out[qid] = {"noul": 0.0}
            elif question["type"] == "choice":
                first = next(iter(question["criteria"]))
                out[qid] = {"choice": first, "probabilities": {first: 1.0}}
            elif question["type"] == "spans":
                out[qid] = {"items": []}
        return 200, {"answers": out, "model": "dgemma"}, ""


@pytest.fixture
def route(monkeypatch):
    holder = {"route": _Route()}

    def make(deadline, **_):
        return C.Classifier(deadline, base_url="http://route.invalid", api_key="k", model="m",
                            post=lambda *a: holder["route"](*a))

    monkeypatch.setattr(coordinator, "Classifier", make)
    return holder


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
           "frequency": "turn", "parameters": {
               "skills": {"spreadsheets": {"threshold": 0.9}, "web_research": {"threshold": 0.5},
                          "emails": {"threshold": 0.5}},
               "source_skills": {"web_research": ["web", "both"]},
               "flags": {"ranking": "Does the request ask for a superlative?"}}}
OBJECTS = {"id": "objects", "hook": "tool_batch_completed", "handler": "result_skills",
           "priority": 20, "frequency": "visible_revision",
           "parameters": {"objects": {"spreadsheets": ["table"]},
                          "events": {"citation": "first_read"}}}
READS = {"id": "reads", "hook": "tool_batch_completed", "handler": "web_reads", "priority": 30,
         "frequency": "event", "parameters": {"mode": "rank", "max_urls": 6}}
L4 = {"id": "l4", "hook": "tool_batch_completed", "handler": "discovery", "priority": 50,
      "frequency": "turn", "parameters": {"min_unread": 2}}
L3 = {"id": "l3", "hook": "answer_drafted", "handler": "discovery", "priority": 10,
      "frequency": "turn", "parameters": {}}
REVIEW = {"id": "review", "hook": "answer_drafted", "handler": "answer_review", "priority": 20,
          "frequency": "event", "parameters": {"supported": {"repair": True}}}


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
    ({**PREPARE, "parameters": {"skills": {"x": {"threshold": 2}}}}, "between 0 and 1"),
    ({**READS, "parameters": {"mode": "random"}}, "mode must be rank or classifier"),
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


def test_the_built_in_definitions_resolve():
    assert definitions.resolve("full_research").id == "chat-default"
    assert definitions.resolve("internal_search").id == "chat-default"
    record = definitions.resolve("full_research").record()
    assert definitions.pinned(record).revision == record["revision"]
    assert definitions.stale_rules(definitions.pinned(record)) == []


def test_a_run_keeps_its_pinned_revision_after_a_new_activation(store, monkeypatch, route):
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


def test_a_turn_without_control_records_keeps_the_earlier_behavior(store, route):
    store["messages"].append(_ai(1, content="An answer."))
    store["row"] = _row(result="An answer.")
    outcome = _hook("answer_drafted", draft_kind="answer")
    assert not outcome.round and outcome.calls == []
    assert store["chat"] == [] and route["route"].bodies == []


# ------------------------------------------------------------------ preparation and skills


def test_preparation_loads_picked_skills_and_pins_assets(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([PREPARE]))
    route["route"] = _Route({"sources=": {"choice": "documents", "probabilities": {"documents": 0.9, "web": 0.1}},
                             "skill_spreadsheets=": {"noul": 0.97}, "skill_web_research=": {"noul": 0.99},
                             "skill_emails=": {"noul": 0.6}})
    outcome = _hook("turn_started", 0)
    assert [c.name for c in outcome.calls] == ["read_skill", "read_skill"]
    ai = next(m for m in store["messages"] if m.role == "ai")
    assert ai.usage["origin"] == "policy" and "step_no" not in ai.usage
    # A documents request gets no web skill. The scores order the loads.
    assert [c["args"]["name"] for c in ai.tool_calls] == ["spreadsheets", "emails"]
    assert [c.seq for c in outcome.calls] == [5, 6]
    assert store["row"].next_seq == 8
    assert "3 to 10 calls" in store["chat"][-1]["content"]
    control = store["messages"][0].usage["control"]
    assert control["assets"]["system_prompt"] == "PROMPT dated 2026-10-08"
    assert steps.pinned_control(store["messages"])["skills"]["spreadsheets"].startswith("Skill")
    decision = control["decisions"]["turn_started"]
    assert decision["facts"]["preparation"]["sources"]["choice"] == "documents"
    assert decision["status"] == "applied"


def test_preparation_normalizes_a_named_collection_span(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([PREPARE]))
    def agent(*args):
        response = store["agent"](*args)
        if "callable_tools" in response:
            response["callable_tools"].append("ask_user")
        return response
    monkeypatch.setattr(coordinator, "_agent_post", agent)
    store["messages"][0] = replace(store["messages"][0], content=
        "How many PDF documents does the epstein collection hold? List the 10 largest.")
    route["route"] = _Route({"names=": {"items": [{"text": "epstein collection"}]}})
    _hook("turn_started", 0)
    facts = store["messages"][0].usage["control"]["decisions"]["turn_started"]["facts"]["preparation"]
    assert facts["names"] == ["epstein"]
    assert facts["absence_records"] == [{"name": "epstein", "kind": "collection", "options": []}]
    assert "Call ask_user" in store["chat"][-1]["content"]
    name_question = next(body["questions"]["names="] for _, body in route["route"].bodies
                         if "names=" in body.get("questions", {}))
    assert "criteria" not in name_question


def test_a_stored_decision_is_reused_without_a_second_evaluation(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([PREPARE]))
    route["route"] = _Route({"skill_spreadsheets=": {"noul": 0.97}})
    first = _hook("turn_started", 0)
    asked = len(route["route"].bodies)
    # A worker restart repeats the activity. The decision and its rows are reused.
    second = _hook("turn_started", 0)
    assert len(route["route"].bodies) == asked
    assert [c.call_id for c in first.calls] == [c.call_id for c in second.calls]
    assert len([m for m in store["messages"] if m.role == "ai"]) == 1


def test_preparation_resolves_followup_sources_from_the_previous_turn(store, monkeypatch, route):
    previous = [agent_runs.RunMessageRow(idx=0, role="human", content="Find current public reports."),
                agent_runs.RunMessageRow(idx=1, role="ai", content="The public report states this [W1].")]
    monkeypatch.setattr(agent_runs, "read_earlier_threads", lambda *a: ["previous"])
    monkeypatch.setattr(agent_runs, "read_messages", lambda u, s, t:
                        previous if t == "previous" else list(store["messages"]))
    store["messages"][0] = replace(store["messages"][0], content="Which sources support these statements?")
    _pin(store, monkeypatch, _definition([PREPARE]))
    _hook("turn_started", 0)
    body = next(body for _, body in route["route"].bodies if "sources=" in body.get("questions", {}))
    assert "Find current public reports." in json.dumps(body)
    assert "The public report states this [W1]." in json.dumps(body)
    assert "new source restriction takes precedence" in body["instructions"]


@pytest.mark.parametrize("handle,quote,expected", [("[W1]", "Verified words.", False),
                                                   ("[W2]", "Verified words.", True),
                                                   ("[W1]", "", True)])
def test_l3_accepts_only_a_reused_verified_passage(store, monkeypatch, route, handle, quote, expected):
    from tasks.P_agent.control.handlers.discovery import Handler
    from tasks.P_agent.control.model import ControlEvent, PolicyContext

    context = PolicyContext(RUN_ID, RUN_ID, "full_research", "r", "Which sources?",
                            frozenset({"read_page"}), {}, frozenset(), (), (),
                            {"preparation": {"sources": {"choice": "web"}},
                             "passages": [{"handle": handle, "quotes": [quote] if quote else []}]}, {},
                            draft="The report states this [W1].", capabilities=frozenset({"web"}))
    event = ControlEvent("event", "answer_drafted", 1, "model", "answer")
    result = Handler()._l3(event, context, {})
    assert bool(result.actions) is expected


def test_a_missing_action_row_is_written_at_its_reserved_position(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([PREPARE]))
    route["route"] = _Route({"skill_spreadsheets=": {"noul": 0.97}})
    _hook("turn_started", 0)
    ai = next(m for m in store["messages"] if m.role == "ai")
    store["messages"] = [m for m in store["messages"] if m.role != "ai"]
    _hook("turn_started", 0)
    again = next(m for m in store["messages"] if m.role == "ai")
    assert (again.idx, again.tool_calls) == (ai.idx, ai.tool_calls)


def test_a_failed_sibling_request_keeps_the_other_result(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([PREPARE]))

    class Split(_Route):
        def __call__(self, session, url, body, key, timeout):
            if url.endswith(C.RAW_PATH):
                raise C.requests.Timeout("slow")
            return super().__call__(session, url, body, key, timeout)

    route["route"] = Split({"skill_spreadsheets=": {"noul": 0.97}})
    outcome = _hook("turn_started", 0)
    facts = store["messages"][0].usage["control"]["decisions"]["turn_started"]["facts"]["preparation"]
    assert facts["requirements_status"] == "timeout"
    assert [c.name for c in outcome.calls] == ["read_skill"]


def test_an_absent_route_proceeds_with_no_load(store, monkeypatch):
    _pin(store, monkeypatch, _definition([PREPARE]))
    outcome = _hook("turn_started", 0)
    assert outcome.calls == []
    decision = store["messages"][0].usage["control"]["decisions"]["turn_started"]
    assert any(c["status"] in ("error", "unknown") for c in decision["checks"])


def test_an_invented_requirement_stays_inferred(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([PREPARE]))
    route["route"] = _Route(raw=json.dumps([
        {"condition": "rank by production volume", "scope": "whole", "basis": "evidence",
         "words": "production volume"},
        {"condition": "payments to Fortress", "scope": "item", "basis": "evidence",
         "words": "payments to Fortress"}]))
    _hook("turn_started", 0)
    facts = store["messages"][0].usage["control"]["decisions"]["turn_started"]["facts"]["preparation"]
    assert [(r["text"], r["explicit"]) for r in facts["requirements"]] == [
        ("rank by production volume", False), ("payments to Fortress", True)]


def _search_batch(store, hits, idx=1):
    store["messages"] += [
        _ai(idx, [("s1", "search_collections", {"queries": ["fortress"]})]),
        _tool(idx + 1, "s1", "search_collections", {"items": hits})]


def test_a_request_load_and_a_result_trigger_give_one_visible_copy(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([PREPARE, OBJECTS]))
    route["route"] = _Route({"skill_spreadsheets=": {"noul": 0.97}})
    prepared = _hook("turn_started", 0)
    store["messages"].append(_tool(2, prepared.calls[0].call_id, "read_skill",
                                   SKILLS["spreadsheets"]["text"]))
    store["agent"].visible = ["spreadsheets"]
    _search_batch(store, [{"file_hash": "a", "path": "/x.xlsx", "type": "table"}], idx=3)
    outcome = _hook("tool_batch_completed", anchor_idx=3)
    assert outcome.calls == []
    # Compaction removed the earlier copy. A later qualifying event loads it again.
    store["agent"].visible = []
    _search_batch(store, [{"file_hash": "b", "path": "/y.csv", "type": "table"}], idx=5)
    again = _hook("tool_batch_completed", anchor_idx=5)
    assert [c.name for c in again.calls] == ["read_skill"]


def test_a_policy_batch_loads_a_skill_and_starts_no_reads(store, monkeypatch, route):
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
    assert [c.name for c in first.calls] == ["read_skill"]


# ------------------------------------------------------------------ discovery


def _web_batch(store, idx, urls_by_search, origin=None):
    calls = [(f"w{idx}-{k}", "web_search", {"query": f"q{k}"}) for k in range(len(urls_by_search))]
    store["messages"].append(_ai(idx, calls, origin=origin))
    for k, urls in enumerate(urls_by_search):
        store["messages"].append(_tool(idx + 1 + k, calls[k][0], "web_search",
                                       {"results": [{"url": u} for u in urls]}))


def test_rank_reads_take_each_address_once_and_skip_read_pages(store, monkeypatch, route):
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


def test_classifier_reads_follow_full_scores_and_rank_ties(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([{**READS, "parameters": {"mode": "classifier", "max_urls": 2}}]))
    _hook("turn_started", 0)
    _web_batch(store, 1, [["https://a.example/1", "https://a.example/2", "https://a.example/3"]])
    route["route"] = _Route({"r1_read=": {"noul": 0.5}, "r2_read=": {"noul": 0.9000001},
                             "r3_read=": {"noul": 0.9000001}})
    [call] = _hook("tool_batch_completed", anchor_idx=1).calls
    ai = next(m for m in store["messages"] if m.idx == call.ai_idx)
    assert ai.tool_calls[0]["args"]["urls"] == ["https://a.example/2", "https://a.example/3"]


def test_l4_notes_a_single_page_read_once_per_turn(store, monkeypatch, route):
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


def _prepared(store, monkeypatch, route, rules, sources="web"):
    _pin(store, monkeypatch, _definition([PREPARE] + rules))
    route["route"] = _Route({"sources=": {"choice": sources, "probabilities": {sources: 1.0}}})
    _hook("turn_started", 0)
    route["route"] = _Route()


def test_l3_asks_for_reads_before_an_answer_once(store, monkeypatch, route):
    _prepared(store, monkeypatch, route, [L3])
    _draft(store, "Fortress was paid twice.")
    outcome = _hook("answer_drafted", draft_kind="answer")
    note = store["messages"][-1]
    assert outcome.round and "read_page once with the URLs" in note.content
    assert note.usage["control"]["discovery"] and not note.usage["control"]["repair"]
    _draft(store, "Fortress was paid twice.")
    assert not _hook("answer_drafted", draft_kind="answer").round


def test_l3_uses_document_wording_without_web_tools(store, monkeypatch, route):
    _prepared(store, monkeypatch, route, [L3], sources="documents")
    _draft(store, "Fortress was paid twice.")
    assert _hook("answer_drafted", draft_kind="answer", internet=False).round
    assert "read_documents" in store["messages"][-1].content


def test_a_clarification_gets_no_discovery_note(store, monkeypatch, route):
    _prepared(store, monkeypatch, route, [L3])
    _draft(store, "Which Fortress do you mean?")
    assert not _hook("answer_drafted", draft_kind="question").round


def test_a_clarification_gets_no_citation_round_from_earlier_reads(store, monkeypatch, route):
    _prepared(store, monkeypatch, route, [L3])
    monkeypatch.setattr(citations, "needs_repair", lambda *a: (True, {
        "labels": [], "unsupported_paragraphs": [{"number": 1, "text": "Which epstein collection?"}]}))
    _draft(store, "Which epstein collection do you mean?")
    assert not _hook("answer_drafted", draft_kind="question").round


def test_verified_absence_gets_no_citation_round_from_earlier_reads(store, monkeypatch, route):
    _prepared(store, monkeypatch, route, [L3], sources="documents")
    _search_batch(store, [])
    monkeypatch.setattr(citations, "needs_repair", lambda *a: (True, {
        "labels": [], "unsupported_paragraphs": [{"number": 1, "text": "No documents found."}]}))
    _draft(store, "No documents contain the requested name.")
    assert not _hook("answer_drafted", draft_kind="answer").round


def test_a_clarification_with_an_unissued_handle_still_needs_repair(store, monkeypatch, route):
    _prepared(store, monkeypatch, route, [L3])
    _draft(store, "Which collection do you mean [D999]?")
    assert _hook("answer_drafted", draft_kind="question").round


def test_named_collection_absence_does_not_require_a_document_search():
    from tasks.P_agent.control import facts
    context = replace(_progress_context(), draft="The collections do not contain epstein.",
                      turn=freeze({"preparation": {"absence_records": [{"name": "epstein", "kind": "collection"}]}}))
    assert facts.justified_absence(context)
    assert not facts.justified_absence(replace(context, draft="No documents contain a different name."))


# ------------------------------------------------------------------ repair rounds


def _cited_answer(store, text="The memo sets the budget [D1]."):
    _draft(store, text)


def test_two_repair_rounds_then_the_draft_is_published(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([]))
    _hook("turn_started", 0)
    rounds = []
    for _ in range(3):
        _cited_answer(store)
        rounds.append(_hook("answer_drafted", draft_kind="answer").round)
    assert rounds == [True, True, False]
    notes = [m for m in store["messages"] if citations.is_citation_note(m)]
    assert len(notes) == 2
    # The last draft is checked and its findings are recorded with no further round.
    last = store["messages"][-1]
    decision = last.usage["control"]["decisions"]["answer_drafted"]
    assert decision["repair"]["has_defects"] and not decision["repair"]["allowed"]


def test_an_older_marker_counts_as_one_round(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([]))
    _hook("turn_started", 0)
    _cited_answer(store)
    store["messages"].append(agent_runs.RunMessageRow(
        idx=max(m.idx for m in store["messages"]) + 1, role="human", content="Cite [D1].",
        usage_json=json.dumps({"repair_marker": "citation"}), run_id=RUN_ID))
    _cited_answer(store)
    assert _hook("answer_drafted", draft_kind="answer").round
    _cited_answer(store)
    assert not _hook("answer_drafted", draft_kind="answer").round


def test_a_restart_after_the_note_write_keeps_the_count(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([]))
    _hook("turn_started", 0)
    _cited_answer(store)
    assert _hook("answer_drafted", draft_kind="answer").round
    # The activity runs again after its note write: same note, same count.
    assert _hook("answer_drafted", draft_kind="answer").round
    assert sum(citations.is_citation_note(m) for m in store["messages"]) == 1
    assert len([c for c in store["chat"] if c["role"] == "nag"]) == 2
    assert len({c["seq"] for c in store["chat"] if c["role"] == "nag"}) == 1


def test_the_step_limit_stops_the_repair_round(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([]))
    _hook("turn_started", 0)
    _cited_answer(store)
    assert not _hook("answer_drafted", draft_kind="answer", limit=True).round


def test_a_classifier_timeout_keeps_a_code_defect_round(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([REVIEW]))
    _hook("turn_started", 0)
    route["route"] = _Route(delay=1.0)
    store["session_citations"] = []
    _cited_answer(store)
    outcome = _hook("answer_drafted", draft_kind="answer", seconds=0.3)
    assert outcome.round
    decision = store["messages"][-2].usage["control"]["decisions"]["answer_drafted"]
    assert decision["repair"]["citation_needed"]
    assert any(r["status"] in ("timeout", "ok") for r in decision["rules"])


def test_semantic_findings_join_the_citation_note(store, monkeypatch, route):
    from tasks.P_agent import reports

    _pin(store, monkeypatch, _definition([REVIEW]))
    _hook("turn_started", 0)
    content = {"citations": [{"file_hash": "a" * 16, "handle": "[D1]"}]}
    entries = reports.with_source(reports.normalize(
        "cite_documents", {}, json.dumps(content), "ok",
        [{"collectionname": "c", "file_hash": "a" * 64, "handle": "[D1]", "quote": "The budget is 5.",
          "quote_verified": True}]), RUN_ID, 1)
    store["session_citations"] = [agent_runs.RunMessageRow(
        idx=1, role="tool", tool_name="cite_documents", content=json.dumps(content),
        usage_json=json.dumps({"status": "ok", "evidence": entries}))]
    route["route"] = _Route({"b1_supported=": {"noul": 0.01}})
    _cited_answer(store, "The memo sets the budget at 7 [D1]. See [newspaste].")
    assert _hook("answer_drafted", draft_kind="answer").round
    note = store["messages"][-1]
    assert note.content.count("Correct these parts of the answer") == 1
    assert "newspaste" in note.content and "Cite a passage that states this claim" in note.content


def test_a_draft_without_a_finding_ends_the_turn(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([REVIEW, L3]))
    _hook("turn_started", 0)
    _draft(store, "Hello.")
    assert not _hook("answer_drafted", draft_kind="answer").round
    assert not any(citations.is_citation_note(m) for m in store["messages"])


# ------------------------------------------------------------------ cancellation


def test_a_stopped_run_writes_no_action(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([PREPARE]))
    store["row"] = _row(state="cancelled")
    outcome = _hook("turn_started", 0)
    assert outcome.closed and len(store["messages"]) == 1 and store["chat"] == []


def test_a_cancelled_evaluation_writes_no_decision(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([PREPARE]))
    monkeypatch.setattr(coordinator, "_cancelled", lambda: True)
    route["route"] = _Route(delay=0.2)
    with pytest.raises(BaseException):
        _hook("turn_started", 0)
    assert "decisions" not in store["messages"][0].usage.get("control", {}) or \
        not store["messages"][0].usage["control"]["decisions"]
    assert not any(m.role == "ai" for m in store["messages"])


@pytest.mark.parametrize("temporal", [False, True])
def test_a_cancelled_hook_preserves_request_samples_without_actions(store, monkeypatch, route, temporal):
    from temporalio.exceptions import CancelledError

    _pin(store, monkeypatch, _definition([PREPARE]))
    recorded = []
    monkeypatch.setattr(C, "write_events", lambda row, decision: recorded.append(decision))
    async def cancel(definition, event, context, services, deadline):
        services.classifier.events.append({"sequence": 1, "outcome": "cancelled", "latency_ms": 125})
        raise CancelledError() if temporal else asyncio.CancelledError()
    monkeypatch.setattr(coordinator, "evaluate", cancel)
    with pytest.raises((asyncio.CancelledError, CancelledError)):
        _hook("turn_started", 0)
    sample = recorded[0]["classifier_events"][0]
    assert sample == {"sequence": 1, "outcome": "cancelled", "latency_ms": 125,
                      "actions": 0, "positive_answers": 0, "scored_answers": 0}
    assert recorded[0]["event"]["hook"] == "turn_started"
    assert not store["messages"][0].usage["control"]["decisions"]
    assert store["chat"] == []


def test_a_turn_closed_after_evaluation_preserves_request_samples(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([PREPARE]))
    recorded, reads = [], []
    monkeypatch.setattr(C, "write_events", lambda row, decision: recorded.append(decision))
    def read_row(params):
        reads.append(params)
        return replace(store["row"], state="cancelled") if len(reads) > 1 else store["row"]
    monkeypatch.setattr(steps, "_read_row", read_row)
    outcome = _hook("turn_started", 0)
    assert outcome.closed
    assert len(recorded) == 1
    assert len(recorded[0]["classifier_events"]) == 3
    assert all(event["actions"] == 0 for event in recorded[0]["classifier_events"])
    assert store["chat"] == []


def test_a_completed_hook_writes_samples_once_across_a_retry(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([PREPARE]))
    recorded = []
    monkeypatch.setattr(C, "write_events", lambda row, decision: recorded.append(decision))
    _hook("turn_started", 0)
    _hook("turn_started", 0)
    assert len(recorded) == 1
    assert len(recorded[0]["classifier_events"]) == 3
    assert sum(event["actions"] for event in recorded[0]["classifier_events"]) == 1


# ------------------------------------------------------------------ the classifier client


def test_the_deadline_covers_every_request_of_a_hook():
    now = [0.0]
    deadline = C.Deadline(10.0, clock=lambda: now[0])
    route = _Route()
    client = C.Classifier(deadline, base_url="http://r", api_key="k", model="m", post=route)
    now[0] = 10.0
    result = asyncio.run(client.ask({}, {"a=": {"type": "noul", "instructions": "?"}}))
    assert result.status == "timeout" and route.bodies == []


def test_a_large_question_set_is_split_and_keeps_its_ids():
    route = _Route({f"q{i}=": {"noul": i / 100} for i in range(70)})
    client = C.Classifier(C.Deadline(10), base_url="http://r", api_key="k", model="m", post=route)
    questions = {f"q{i}=": {"type": "noul", "instructions": "?"} for i in range(70)}
    result = asyncio.run(client.ask({}, questions))
    assert [len(b["questions"]) for _, b in route.bodies] == [64, 6]
    assert result.answers["q69="]["noul"] == 0.69 and result.status == "ok"


def test_a_malformed_answer_is_absent_and_never_zero():
    route = _Route({"a=": {"noul": "high"}, "b=": {"noul": 0.4}})
    client = C.Classifier(C.Deadline(10), base_url="http://r", api_key="k", model="m", post=route)
    result = asyncio.run(client.ask({}, {"a=": {"type": "noul", "instructions": "?"},
                                         "b=": {"type": "noul", "instructions": "?"}}))
    assert "a=" not in result.answers and result.answers["b="]["noul"] == 0.4


def test_no_route_means_unavailable():
    client = C.Classifier(C.Deadline(10), base_url="", api_key="", model="m")
    result = asyncio.run(client.ask({}, {"a=": {"type": "noul", "instructions": "?"}}))
    assert result.status == "unavailable"


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
                         definition_revision="test", request="Find a missing name", callable_tools=frozenset({"search_collections", "search_passages", "ask_user"}),
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
        result = asyncio.run(handler.evaluate(event, _progress_context(previous, (fact,), n), {"signals": False}, object()))
        previous = plain(result.facts)
    assert previous["level"] == 3 and previous["strongest_step"] == 8
    result = asyncio.run(handler.evaluate(event, _progress_context(previous, (replace(fact, keyword_sources=("new",)),), 9), {"signals": False}, object()))
    assert result.facts["units"] == 0 and result.facts["level"] == 3
    result = asyncio.run(handler.evaluate(event, _progress_context(plain(result.facts), (fact,), 14), {"signals": False}, object()))
    assert [a.kind for a in result.actions] == ["end_turn"]


def test_signal_streak_requires_two_scores_and_resets_on_failure():
    from tasks.P_agent.control.handlers.progress import Handler
    from tasks.P_agent.control.model import ClassifierResult, ControlEvent, plain
    class Signals:
        fail = False
        async def ask(self, state, questions, instructions=""):
            answers = {} if self.fail else {q: {"noul": 0.95} for q in questions}
            return ClassifierResult("timeout" if self.fail else "ok", freeze(answers))
    services = Signals()
    event = ControlEvent("batch", "tool_batch_completed", 1, "model")
    first = asyncio.run(Handler().evaluate(event, _progress_context(), {}, services))
    assert not first.facts["signals"]["stuck"]["fired"]
    second = asyncio.run(Handler().evaluate(event, _progress_context(plain(first.facts)), {}, services))
    assert second.facts["signals"]["stuck"]["fired"] and second.facts["signals"]["absent"]["fired"]
    services.fail = True
    failed = asyncio.run(Handler().evaluate(event, _progress_context(plain(second.facts)), {}, services))
    assert failed.facts["signals"]["stuck"]["streak"] == 0


def test_absence_uses_counts_across_table_kinds():
    from tasks.P_agent.control.handlers.absence import check_names, note_action
    class Suggestions:
        async def suggestions(self, names, kind, collections):
            return {"word_counts": [{"word": "john", "documents": 10 if kind == "pages" else 0}, {"word": "smithx", "documents": 0}],
                    "suggestions": [{"word": "smithx", "candidates": [{"word": "smith", "distance": 1, "documents": 8}]}]}
    context = _progress_context()
    records = asyncio.run(check_names(["John Smithx"], context, Suggestions()))
    assert records[0]["options"] == ["John smith"]
    assert "Search the web" not in note_action(records, context)[0].arguments["text"]
    assert "Call ask_user now with these options" in note_action(records, context)[0].arguments["text"]


def test_classifier_events_keep_chunk_metadata_without_text():
    client = C.Classifier(C.Deadline(2), base_url="http://route.invalid", api_key="k", model="m", post=_Route())
    questions = {f"q{n}=": {"type": "noul", "instructions": "private question"} for n in range(65)}
    asyncio.run(client.ask({"request": "private request"}, questions, trace={"rule_id": "progress", "handler": "progress"}))
    assert len(client.events) == 2
    assert [len(e["question_ids"]) for e in client.events] == [64, 1]
    assert all(e["handler"] == "progress" for e in client.events)
    assert "private" not in json.dumps(client.events)


def test_all_default_handlers_run_without_web_tools():
    from tasks.P_agent.control.model import ControlEvent
    definition = definitions.resolve("internal_search:documents")
    client = C.Classifier(C.Deadline(5), base_url="http://route.invalid", api_key="k", model="m", post=_Route())
    services = coordinator.Services(client, [])
    context = replace(_progress_context(), listed_skills=freeze(SKILLS))
    for hook in ("turn_started", "tool_batch_completed", "answer_drafted"):
        results = asyncio.run(coordinator.evaluate(definition, ControlEvent(hook, hook, 0, "model"), context, services, client.deadline))
        assert all(record["status"] in ("ok", "skipped") for _, _, record in results)
        for rule, result, record in results:
            if rule.requires_tools:
                assert record["status"] == "skipped"
            for action in result.actions if result else ():
                assert action.arguments.get("name") not in ("web_research", "browser_use")


def test_empty_collection_scope_stays_empty_during_preparation(store, route):
    params = control_steps.ControlParams(run_id=RUN_ID, username="u", session_id="s", allowed_collections=[])
    pinned = coordinator._pin(store["row"], store["messages"], params)
    assert pinned["collections"] == []


def test_web_skill_requires_capability_when_source_choice_is_missing():
    from tasks.P_agent.control.handlers.preparation import Handler
    from tasks.P_agent.control.model import ClassifierResult, ControlEvent
    class Answers:
        async def ask(self, state, questions, instructions=""):
            return ClassifierResult("ok", freeze({q: {"noul": 0.99} for q in questions if q.startswith("skill_")}))
        async def complete(self, prompt, max_tokens):
            return ClassifierResult("unavailable")
    context = replace(_progress_context(), listed_skills=freeze(SKILLS))
    result = asyncio.run(Handler().evaluate(ControlEvent("start", "turn_started", 0, "runtime"), context,
                         {"skills": {"web_research": {"threshold": 0.5}}, "source_skills": {"web_research": ["web", "both"]}}, Answers()))
    assert not any(a.kind == "load_skill" for a in result.actions)


def test_document_guidance_has_no_web_step_without_web_capability():
    from tasks.P_agent.control.handlers.preparation import Handler
    from tasks.P_agent.control.model import ClassifierResult, ControlEvent
    class Answers:
        async def ask(self, state, questions, instructions=""):
            if "sources=" in questions:
                assert "web" not in questions["sources="]["criteria"]
                assert "Choose web" not in instructions
            return ClassifierResult("ok", freeze({"sources=": {
                "choice": "documents", "probabilities": {"documents": 1.0}}}))
        async def complete(self, prompt, max_tokens):
            return ClassifierResult("unavailable")
    result = asyncio.run(Handler().evaluate(
        ControlEvent("start", "turn_started", 0, "runtime"), _progress_context(), {}, Answers()))
    text = " ".join(a.arguments.get("text", "") for a in result.actions)
    assert "Read their relevant documents." in text
    assert "web" not in text


@pytest.mark.parametrize("completion", [False, True])
def test_cancelled_requests_record_elapsed_latency(monkeypatch, completion):
    now = [100.0]
    monkeypatch.setattr(C.time, "monotonic", lambda: now[0])
    client = C.Classifier(C.Deadline(5, clock=lambda: now[0]),
                          base_url="http://route.invalid", api_key="k", model="m")
    async def cancelled(*args):
        now[0] += 0.125
        raise asyncio.CancelledError
    monkeypatch.setattr(client, "_request", cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(client.complete("request", 10) if completion else
                    client.ask({}, {"q=": {"type": "noul", "instructions": "Question?"}}))
    assert len(client.events) == 1
    assert client.events[0]["outcome"] == "cancelled"
    assert client.events[0]["latency_ms"] == 125


@pytest.mark.parametrize("request_text,name", [
    ("The files have a folder called greenvelope. Count its campaigns.", "greenvelope"),
    ('Search the collection named "Case Files".', "Case Files"),
])
def test_explicit_name_survives_an_empty_classifier_span(request_text, name):
    from tasks.P_agent.control.handlers.preparation import Handler
    from tasks.P_agent.control.model import ClassifierResult, ControlEvent
    class Answers:
        async def ask(self, state, questions, instructions=""):
            return ClassifierResult("ok", freeze({"names=": {"items": []}}))
        async def complete(self, prompt, max_tokens):
            return ClassifierResult("unavailable")
        async def suggestions(self, names, kind, collections):
            return {"word_counts": [{"word": names[0], "documents": 0}]}
    context = replace(_progress_context(), request=request_text)
    result = asyncio.run(Handler().evaluate(
        ControlEvent("start", "turn_started", 0, "runtime"), context, {}, Answers()))
    assert result.facts["names"] == (name,)
    assert result.facts["absence_records"][0]["name"] == name
    assert "Call ask_user" in " ".join(a.arguments.get("text", "") for a in result.actions)


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
