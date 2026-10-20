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


def test_the_built_in_definitions_resolve(monkeypatch):
    # The built-in activation only: a deployment's control directory can select another.
    monkeypatch.delenv(registry.CONTROL_DIR_ENV, raising=False)
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
    assert "Search the permitted document collections first" in store["chat"][-1]["content"]
    assert "calls" not in store["chat"][-1]["content"]
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


def _with_requirements(rule):
    return {**rule, "parameters": {**rule["parameters"], "requirements": True}}


def test_a_failed_sibling_request_keeps_the_other_result(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([_with_requirements(PREPARE)]))

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
    _pin(store, monkeypatch, _definition([_with_requirements(PREPARE)]))
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


def test_a_clarification_gets_no_discovery_note(store, monkeypatch, route):
    _prepared(store, monkeypatch, route, [L3])
    _draft(store, "Which Fortress do you mean?")
    assert not _hook("answer_drafted", draft_kind="question").round


def test_named_collection_absence_does_not_require_a_document_search():
    from tasks.P_agent.control import facts
    context = replace(_progress_context(), draft="The collections do not contain epstein.",
                      turn=freeze({"preparation": {"absence_records": [{"name": "epstein", "kind": "collection"}]}}))
    assert facts.justified_absence(context)
    assert not facts.justified_absence(replace(context, draft="No documents contain a different name."))


# ------------------------------------------------------------------ repair rounds


def _cited_answer(store, text="The memo sets the budget [D1]."):
    _draft(store, text)


def test_the_step_limit_stops_the_repair_round(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([]))
    _hook("turn_started", 0)
    _cited_answer(store)
    assert not _hook("answer_drafted", draft_kind="answer", limit=True).round


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
    # The skill request and the name request. No requirement request is made by default.
    assert len(recorded[0]["classifier_events"]) == 2
    assert all(event["actions"] == 0 for event in recorded[0]["classifier_events"])
    assert store["chat"] == []


def test_a_completed_hook_writes_samples_once_across_a_retry(store, monkeypatch, route):
    _pin(store, monkeypatch, _definition([PREPARE]))
    recorded = []
    monkeypatch.setattr(C, "write_events", lambda row, decision: recorded.append(decision))
    _hook("turn_started", 0)
    _hook("turn_started", 0)
    assert len(recorded) == 1
    assert len(recorded[0]["classifier_events"]) == 2
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
    assert result.facts["units"] == 0 and result.facts["level"] == 0
    result = asyncio.run(handler.evaluate(event, _progress_context(plain(result.facts), (fact,), 14), {"signals": False}, object()))
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
    result = asyncio.run(Handler().evaluate(event, _progress_context(previous, facts, 2), {"signals": False}, object()))
    assert result.facts["units"] == 0 and result.facts["level"] == 0
    again = asyncio.run(Handler().evaluate(event, _progress_context(plain(result.facts), facts, 3), {"signals": False}, object()))
    assert len(again.facts["sources"]) == 1
    assert again.facts["searches"][-1]["name"] == name
    assert again.facts["units"] == 1


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


ADVISORY = {"signals": True, "completion": "none", "advice": True, "end_turn": True}


def _trace(params, scores):
    """Run one fixed operation trace through the progress handler with classifier answers
    `scores` (a score for every question, or None for a failed request). Returns the ledger
    after each batch and every action."""
    from tasks.P_agent.control.facts import ResultFact
    from tasks.P_agent.control.handlers.progress import Handler
    from tasks.P_agent.control.model import ClassifierResult, ControlEvent, plain

    class Scores:
        async def ask(self, state, questions, instructions=""):
            if scores is None:
                return ClassifierResult("timeout", freeze({}))
            return ClassifierResult("ok", freeze({q: {"noul": scores} for q in questions}))

    search = ResultFact("s", "search_collections", 1, 2, "model", "ok", {"query": '"missing"'}, item_count=0)
    write = ResultFact("w", "write_file", 1, 2, "model", "ok", {"name": "a.md"}, file_version=("a.md", 1, True))
    same = replace(write, file_version=("a.md", 1, False))
    failed = replace(write, status="error", file_version=())
    batches = [search] * 4 + [write, write, same, failed] + [search] * 12
    previous, ledgers, actions = {}, [], []
    for step, fact in enumerate(batches):
        event = ControlEvent(f"b{step}", "tool_batch_completed", 1, "model")
        result = asyncio.run(Handler().evaluate(event, _progress_context(previous, (fact,), step), params, Scores()))
        previous = plain(result.facts)
        ledgers.append(previous)
        actions.append([(a.kind, a.target_id) for a in result.actions])
    return ledgers, actions


DETERMINISTIC_KEYS = ("level", "units", "strongest_step", "progress_seen", "file_versions", "sources",
                      "stop_cause", "signal_units", "refused_repeats", "repeats")


@pytest.mark.parametrize("scores", [0.99, 0.0, None])
def test_advisory_scores_change_no_level_no_ending_and_only_the_advice_note(scores):
    """The same operations give the same deterministic ledger and ending for every
    classifier answer. Only the advice note and the recorded signals differ."""
    base_ledgers, base_actions = _trace({**ADVISORY, "signals": False}, None)
    ledgers, actions = _trace(ADVISORY, scores)
    for got, want in zip(ledgers, base_ledgers):
        assert {k: got[k] for k in DETERMINISTIC_KEYS} == {k: want[k] for k in DETERMINISTIC_KEYS}
    without_advice = [[a for a in batch if a[1] != "progress-advice"] for batch in actions]
    assert without_advice == base_actions
    assert ("end_turn", "progress-end") in [a for batch in actions for a in batch]
    assert ledgers[-1]["stop_cause"] == "operations" and ledgers[-1]["signal_units"] == 0
    advised = [a for batch in actions for a in batch if a[1] == "progress-advice"]
    assert len(advised) == (1 if scores == 0.99 else 0)


def test_new_file_versions_reset_the_level_and_unchanged_or_failed_writes_do_not():
    ledgers, _actions = _trace({**ADVISORY, "signals": False}, None)
    assert ledgers[3]["level"] == 1 and ledgers[4]["level"] == 0 and ledgers[4]["units"] == 0
    assert [ledger["file_versions"] for ledger in ledgers[4:8]] == [["a.md@1"]] * 4
    # The repeated identity, the unchanged write and the failed write each add a unit.
    assert [ledger["units"] for ledger in ledgers[5:8]] == [1, 2, 0] and ledgers[7]["level"] == 1


def test_a_repaired_definition_lets_the_stuck_signal_end_the_turn_earlier_and_names_it():
    deterministic, plain_actions = _trace({**ADVISORY, "advice": False, "signals": False}, None)
    repaired, repaired_actions = _trace({**ADVISORY, "advice": False, "stuck_units": True}, 0.99)
    end = lambda actions: next(i for i, batch in enumerate(actions) if ("end_turn", "progress-end") in batch)
    assert end(repaired_actions) < end(plain_actions)
    assert repaired[end(repaired_actions)]["stop_cause"] == "operations and classifier"
    assert deterministic[end(plain_actions)]["stop_cause"] == "operations"


def test_a_policy_batch_changes_no_progress_state():
    from tasks.P_agent.control.facts import ResultFact
    from tasks.P_agent.control.handlers.progress import Handler
    from tasks.P_agent.control.model import ControlEvent, plain

    previous = {"level": 2, "units": 1, "strongest_step": None, "signal_units": 0}
    fact = ResultFact("p", "read_page", 1, 2, "policy", "ok", {"urls": ["https://a.example"]})
    event = ControlEvent("policy", "tool_batch_completed", 1, "policy")
    result = asyncio.run(Handler().evaluate(event, _progress_context(previous, (fact,), 5), ADVISORY, object()))
    assert plain(result.facts) == previous and not result.actions


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


@pytest.mark.parametrize("request_text,expected", [
    ("Find Vince Kaminsjy in the enron collection.", ["enron"]),
    ("Search collection enron and the tables dataset.", ["enron", "tables"]),
    ("Find Vince Kaminsjy in my documents.", ["enron", "tables", "testdata"]),
])
def test_name_lookup_uses_explicit_collection_scope(request_text, expected):
    from tasks.P_agent.control.handlers.absence import check_names
    class Suggestions:
        calls = []
        async def suggestions(self, names, kind, collections):
            self.calls.append((kind, collections))
            return {"word_counts": [{"word": "kaminsjy", "documents": 0}]}
    services = Suggestions()
    context = replace(_progress_context(), request=request_text,
                      collections=("enron", "tables", "testdata"))
    records = asyncio.run(check_names(["Vince Kaminsjy"], context, services))
    assert records[0]["name"] == "Vince Kaminsjy"
    assert services.calls == [(kind, expected) for kind in ("pages", "entities", "folders")]


@pytest.mark.parametrize("scope,expected", [
    ("enron", ["enron"]), (["enron"], ["enron"]),
    (None, ["enron", "tables"]), ([], ["enron", "tables"]),
])
def test_name_lookup_keeps_collection_arguments_whole(scope, expected):
    from tasks.P_agent.control.facts import ResultFact
    from tasks.P_agent.control.handlers.absence import check_names
    class Suggestions:
        calls = []
        async def suggestions(self, names, kind, collections):
            self.calls.append(collections)
            return {"word_counts": [{"word": "kaminsjy", "documents": 0}]}
    fact = ResultFact("read", "read_documents", 1, 2, "model", "ok", {"collection": scope})
    context = replace(_progress_context(), collections=("enron", "tables"), results=(fact,))
    services = Suggestions()
    asyncio.run(check_names(["Vince Kaminsjy"], context, services))
    assert services.calls == [expected] * 3


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


def test_skipped_rule_keeps_control_event_successful(store, route, monkeypatch, step_events):
    rule = {**PREPARE, "requires_tools": ["unavailable_tool"]}
    _pin(store, monkeypatch, _definition([rule]))
    _hook("turn_started")
    events = [event for event in step_events if event.step == "control"]
    assert len(events) == 1
    assert events[0].ok
    assert events[0].error_class == ""


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


@pytest.mark.parametrize("score", [0.1, 0.95])
def test_unavailable_public_sources_do_not_request_document_searches(score):
    from tasks.P_agent.control.handlers.preparation import Handler
    from tasks.P_agent.control.model import ClassifierResult, ControlEvent
    class Answers:
        async def ask(self, state, questions, instructions=""):
            return ClassifierResult("ok", freeze({"sources=": {
                "choice": "documents", "probabilities": {"documents": 1.0}},
                "web_only=": {"noul": score}}))
        async def complete(self, prompt, max_tokens):
            return ClassifierResult("unavailable")
    result = asyncio.run(Handler().evaluate(
        ControlEvent("start", "turn_started", 0, "runtime"), _progress_context(), {}, Answers()))
    text = " ".join(a.arguments.get("text", "") for a in result.actions)
    assert result.facts["requested_web_score"] == score
    assert next(c for c in result.checks if c.target_id == "web_only").score == score
    if score >= 0.9:
        # The note names the tools of this turn. The source choice and the document order
        # stay, and no note asks for a refusal or names the deployment.
        assert result.facts["sources"]["choice"] == "documents"
        assert result.facts["web_tools_absent"] is True
        assert "This turn has no web tools" in text
        assert "deployment" not in text and "needs web access" not in text
        assert "Search the permitted document collections" in text
        assert "at least 4 distinct searches" not in text
    else:
        assert result.facts["sources"]["choice"] == "documents"
        assert "Search the permitted document collections" in text
        assert "web" not in text


@pytest.mark.parametrize("name", ["list_collections", "search_facet_values", "search_histogram", "folder_overview"])
def test_metadata_results_reset_progress_without_keyword_sources(name):
    from tasks.P_agent.control.facts import ResultFact
    from tasks.P_agent.control.handlers.progress import Handler
    from tasks.P_agent.control.model import ControlEvent, plain

    fact = ResultFact("m", name, 1, 2, "model", "ok", {"collection": "testdata"}, item_count=1)
    context = _progress_context({"level": 3, "units": 2, "strongest_step": 0}, (fact,), 20)
    event = ControlEvent("batch", "tool_batch_completed", 1, "model")
    result = asyncio.run(Handler().evaluate(event, context, {"signals": False}, object()))
    assert result.facts["level"] == 0 and result.facts["units"] == 0
    assert result.facts["strongest_step"] is None and not result.actions
    again = asyncio.run(Handler().evaluate(event, _progress_context(plain(result.facts), (fact,), 21),
                                         {"signals": False}, object()))
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
    result = asyncio.run(Handler().evaluate(event, context, {"signals": False}, object()))
    assert result.facts["level"] == 0 and result.facts["units"] == 0 and not result.actions
    again = asyncio.run(Handler().evaluate(event, _progress_context(plain(result.facts), (fact,), 21),
                                         {"signals": False}, object()))
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
    result = asyncio.run(Handler().evaluate(event, context, {"signals": False}, object()))
    assert result.facts["level"] == 0 and result.facts["units"] == 0 and not result.actions
    again = asyncio.run(Handler().evaluate(event, _progress_context(plain(result.facts), (fact,), 21),
                                         {"signals": False}, object()))
    assert again.facts["units"] == 1


def test_the_quality_definition_resolves_from_a_control_folder(monkeypatch, tmp_path):
    (tmp_path / "definitions").mkdir()
    (tmp_path / "definitions" / "active.json").write_text(json.dumps({"*": "chat-quality"}))
    monkeypatch.setenv(registry.CONTROL_DIR_ENV, str(tmp_path))
    try:
        registry.load(refresh=True)
        definition = definitions.resolve("internal_search")
        assert definition.id == "chat-quality"
        assert definition.limits["paragraph_repair"] == 0
        assert definition.limits["edit_rounds"] == 1
        assert {r.id for r in definition.rules} == {"prepare", "result-skills", "web-reads"}
    finally:
        monkeypatch.delenv(registry.CONTROL_DIR_ENV)
        registry.load(refresh=True)
    assert definitions.resolve("internal_search").limits["paragraph_repair"] == 1


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
                                            {"signals": False}, object()))
    assert result.actions == () and plain_facts(result) == previous


def plain_facts(result):
    from tasks.P_agent.control.model import plain
    return plain(result.facts)


def test_new_file_versions_are_progress_and_an_unchanged_patch_is_not():
    from tasks.P_agent.control.handlers.progress import Handler
    handler, previous = Handler(), {"level": 1, "units": 2}
    patch = _fact("patch_file", file_version=("report.md", 2, True))
    first = asyncio.run(handler.evaluate(_event(), _progress_context(previous, (patch,), 3),
                                         {"signals": False}, object()))
    assert first.facts["level"] == 0 and first.facts["units"] == 0
    assert list(first.facts["file_versions"]) == ["report.md@2"]
    # Several valid patches never count as a stalled search.
    second_patch = _fact("patch_file", file_version=("report.md", 3, True))
    second = asyncio.run(handler.evaluate(_event(), _progress_context(plain_facts(first), (second_patch,), 4),
                                          {"signals": False}, object()))
    assert second.facts["units"] == 0
    unchanged = _fact("patch_file", file_version=("report.md", 3, False))
    third = asyncio.run(handler.evaluate(_event(), _progress_context(plain_facts(second), (unchanged,), 5),
                                         {"signals": False}, object()))
    assert third.facts["units"] == 1
    failed = _fact("write_file", status="error", error_code="invalid_argument")
    fourth = asyncio.run(handler.evaluate(_event(), _progress_context(plain_facts(third), (failed,), 6),
                                          {"signals": False}, object()))
    assert fourth.facts["units"] == 2


class _Signals:
    """Answers every progress question with one score and records the request state."""

    def __init__(self, score):
        self.score = score
        self.states = []

    async def ask(self, state, questions, instructions=""):
        from tasks.P_agent.control.model import ClassifierResult
        self.states.append(state)
        return ClassifierResult("ok", freeze({q: {"noul": self.score} for q in questions}))


def test_the_answered_signal_is_not_kept_from_an_earlier_batch():
    from tasks.P_agent.control.handlers.progress import Handler
    previous = {"answered": True, "signals": {"answered": {"streak": 3}}}
    result = asyncio.run(Handler().evaluate(_event(), _progress_context(previous, (), 2), {},
                                            _Signals(0.0)))
    assert result.facts["answered"] is False


def test_completion_advice_needs_delivery_evidence():
    from tasks.P_agent.control.handlers.progress import COMPLETION_ADVICE, Handler
    stalled = {"level": 0, "units": 2}
    search = _fact("search_collections", item_count=0, args={"query": "x"})
    bare = asyncio.run(Handler().evaluate(_event(), _progress_context(stalled, (search,), 2), {},
                                          _Signals(0.95)))
    note = next(a for a in bare.actions if a.kind == "append_note")
    assert COMPLETION_ADVICE not in note.arguments["text"]
    assert "already gives what the request asks for" not in note.arguments["text"]
    write = _fact("write_file", file_version=("report.md", 1, True), call_id="w")
    context = replace(_progress_context(stalled, (search,), 2), results=(write, search))
    evidenced = asyncio.run(Handler().evaluate(_event(), context, {}, _Signals(0.95)))
    note = next(a for a in evidenced.actions if a.kind == "append_note")
    assert COMPLETION_ADVICE in note.arguments["text"]
    off = asyncio.run(Handler().evaluate(_event(), context, {"completion": "none"}, _Signals(0.95)))
    assert all(COMPLETION_ADVICE not in a.arguments.get("text", "") for a in off.actions)


def test_advisory_progress_names_its_origin_once_and_never_ends_the_turn():
    from tasks.P_agent.control.handlers.progress import STUCK_ADVICE, Handler
    handler, previous = Handler(), {"signals": {"stuck": {"streak": 1}, "absent": {"streak": 1}}}
    search = _fact("search_collections", item_count=0, args={"query": "x"})
    params = {"completion": "none", "advice": True, "end_turn": False}
    first = asyncio.run(handler.evaluate(_event(), _progress_context(previous, (search,), 2), params,
                                         _Signals(0.95)))
    advice = [a for a in first.actions if a.target_id == "progress-advice"]
    assert len(advice) == 1 and advice[0].arguments["text"].startswith("A chat check estimates")
    assert STUCK_ADVICE in advice[0].arguments["text"]
    again = asyncio.run(handler.evaluate(_event(), _progress_context(plain_facts(first), (search,), 3),
                                         params, _Signals(0.95)))
    assert not [a for a in again.actions if a.target_id == "progress-advice"]
    ledger = plain_facts(again)
    for step in range(4, 30):
        result = asyncio.run(handler.evaluate(_event(), _progress_context(ledger, (search,), step),
                                              params, _Signals(0.95)))
        ledger = plain_facts(result)
        assert all(a.kind != "end_turn" for a in result.actions)


def test_the_progress_request_shows_the_focused_task_first():
    from tasks.P_agent.control.handlers.progress import Handler
    brief = "Background. " * 400
    task = {"objective": {"text": "Count the monitored bills by state.", "source": "intent"},
            "brief": {"text": brief, "source": "intent"}}
    context = replace(_progress_context(), request=brief + "Count the monitored bills by state.",
                      task=freeze(task))
    signals = _Signals(0.0)
    asyncio.run(Handler().evaluate(_event(), context, {"request_chars": 1500}, signals))
    shown = signals.states[0]["request"]
    assert shown.startswith("objective: Count the monitored bills by state.")
    assert "characters of the task are omitted here" in shown


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
    text, omitted = F.task_text(task, 10_000)
    assert text.index("Name the leader") < text.index("Use the 2001 minutes") and omitted == 0


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


def test_an_argument_error_loads_the_argument_skill_once_while_it_is_visible(store, monkeypatch, route):
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


def test_deterministic_preparation_loads_the_report_skill_with_no_request(store, monkeypatch, route):
    rule = {**PREPARE, "parameters": {"classifier": False, "report_skill": True}}
    _pin(store, monkeypatch, _definition([rule]))
    store["agent"].requests.clear()
    skills = dict(SKILLS, report={"text": "Skill `report`.", "description": "files", "group": "general",
                                  "tools": ["write_file"], "terms": "", "not_for": ""})
    original = store["agent"]

    def agent(params, path, body, seconds):
        response = original(params, path, body, seconds)
        if path == "/control_snapshot" and not body.get("visibility_only"):
            response = dict(response, skills=skills)
        return response
    monkeypatch.setattr(coordinator, "_agent_post", agent)
    store["messages"][0] = replace(store["messages"][0], content="Write a report on the Fortress payments.")
    outcome = _hook("turn_started", 0)
    assert [c.name for c in outcome.calls] == ["read_skill"]
    assert route["route"].bodies == []
    decision = store["messages"][0].usage["control"]["decisions"]["turn_started"]
    assert decision["facts"]["preparation"]["children"]["ask"] == {"status": "disabled"}
    assert decision["task_digest"]


def test_a_blocked_name_request_keeps_the_skill_picks_and_a_retry_reuses_them(store, monkeypatch, route):
    """The skill request returns, the name request outlives the hook. The decision keeps the
    skill load, records the timeout of the name child, and a worker restart after the decision
    write reuses the decision with no new request."""
    _pin(store, monkeypatch, _definition([PREPARE], {"preparation_seconds": 3}))

    class Blocked(_Route):
        def __call__(self, session, url, body, key, timeout):
            import time
            if "names=" in body.get("questions", {}):
                time.sleep(min(timeout[1], 3))
                return 200, {"answers": {"names=": {"items": [{"text": "late name"}]}}}, ""
            return super().__call__(session, url, body, key, timeout)

    route["route"] = Blocked({"skill_spreadsheets=": {"noul": 0.97}})
    outcome = _hook("turn_started", 0, seconds=3.0)
    assert [c.name for c in outcome.calls] == ["read_skill"]
    decision = store["messages"][0].usage["control"]["decisions"]["turn_started"]
    children = decision["facts"]["preparation"]["children"]
    assert children["ask"]["status"] == "ok" and children["names"]["status"] == "timeout"
    assert decision["facts"]["preparation"]["names"] == []
    asked = len(route["route"].bodies)
    again = _hook("turn_started", 0, seconds=3.0)
    assert len(route["route"].bodies) == asked
    assert [c.call_id for c in again.calls] == [c.call_id for c in outcome.calls]


def test_the_classifier_records_a_digest_of_its_input():
    client = C.Classifier(C.Deadline(2), base_url="http://route.invalid", api_key="k", model="m", post=_Route())
    asyncio.run(client.ask({"request": "a"}, {"q=": {"type": "noul", "instructions": "?"}}))
    asyncio.run(client.ask({"request": "b"}, {"q=": {"type": "noul", "instructions": "?"}}))
    first, second = client.events
    assert len(first["input_digest"]) == 64 and first["input_digest"] != second["input_digest"]


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


@pytest.mark.parametrize("ident", ["chat-deterministic", "chat-advisory", "chat-repaired"])
def test_the_comparison_definitions_validate_and_hold_page_reads_constant(ident, monkeypatch):
    monkeypatch.delenv(registry.CONTROL_DIR_ENV, raising=False)
    path = Path(definitions.__file__).parent / "definitions" / f"{ident}.json"
    definition = definitions.validate(json.loads(path.read_text()), path.name)
    assert definition.id == ident and definition.model_images == "attach"
    reads = next(r for r in definition.rules if r.handler.name == "web_reads")
    assert dict(reads.parameters) == {"mode": "rank", "max_urls": 6, "pool": 10}
    prepare = next(r for r in definition.rules if r.handler.name == "preparation")
    progress = next(r for r in definition.rules if r.handler.name == "progress")
    if ident == "chat-deterministic":
        assert prepare.parameters["classifier"] is False and progress.parameters["signals"] is False
    else:
        assert prepare.parameters["classifier"] is True and progress.parameters["signals"] is True
    if ident == "chat-advisory":
        assert progress.parameters["completion"] == "none" and progress.parameters["advice"] is True


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
                                            context, {"classifier": False}, object()))
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
    ([lambda: _read_page_fact()], []),
    ([lambda: _fact("search_collections")], []),
])
def test_the_method_events_load_the_web_and_browser_skills(batch, expected):
    """The tool results of a method load its skill in every definition, with no classifier.
    A full page read needs no recovery method."""
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


def test_a_definition_event_replaces_the_method_mapping_of_its_skill():
    from tasks.P_agent.control.handlers.result_skills import Handler
    search = (_fact("web_search"),)
    context = replace(_progress_context(), listed_skills=freeze({"web_research": {}}),
                      results=search, batch=search)
    only_browser = {"events": {"web_research": "browser"}}
    assert asyncio.run(Handler().evaluate(_event(), context, only_browser, object())).actions == ()
    with pytest.raises(ValueError, match="methods"):
        Handler().validate({"methods": "yes"})


def test_a_web_method_loads_once_while_its_text_is_visible(store, monkeypatch, route):
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


def test_a_child_that_returns_a_failed_classifier_result_records_its_status():
    from tasks.P_agent.control.handlers.preparation import child_status, gather_children
    from tasks.P_agent.control.model import ClassifierResult

    async def returns(value):
        return value
    results, outcomes = asyncio.run(gather_children({
        "ask": returns(ClassifierResult("ok")),
        "names": returns((["x"], [], ClassifierResult("timeout"))),
        "requirements": returns(ClassifierResult("http_error")),
    }, object()))
    assert outcomes["ask"]["status"] == "ok"
    assert outcomes["names"]["status"] == "timeout"
    assert outcomes["requirements"] == {**outcomes["requirements"], "status": "error", "error": "http_error"}
    assert set(results) == {"ask", "names", "requirements"}
    assert child_status(ClassifierResult("skipped")) == {"status": "skipped"}
    assert child_status(("plain",)) == {"status": "ok"}


def test_a_failed_skill_request_beside_a_finished_name_request_keeps_both_outcomes(store, monkeypatch, route):
    """Through the activity: the skill request fails with an HTTP error, the name request
    finishes. The decision records `error` for the skill child and `ok` for the name child."""
    _pin(store, monkeypatch, _definition([PREPARE]))

    class Split(_Route):
        def __call__(self, session, url, body, key, timeout):
            if "names=" in body.get("questions", {}):
                return 200, {"answers": {"names=": {"items": []}}}, ""
            return 500, {"error": "x"}, ""

    route["route"] = Split()
    _hook("turn_started", 0)
    children = store["messages"][0].usage["control"]["decisions"]["turn_started"]["facts"]["preparation"]["children"]
    assert children["ask"]["status"] == "error" and children["names"]["status"] == "ok"


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


def test_a_long_task_shows_the_objective_and_the_constraints_before_the_background():
    from tasks.P_agent.control import facts as F
    task = {"objective": {"text": "Write the second file.", "source": "user", "turn": 3},
            "brief": {"text": "Background. " * 600, "source": "intent"},
            "constraints": [{"text": "Search only the enron collection.", "source": "user", "turn": 1}]}
    text, omitted = F.task_text(task, 400)
    assert text.index("Write the second file.") < text.index("Search only the enron collection.") < text.index("Background.")
    assert omitted > 0 and f"[{omitted} characters of the task are omitted here]" in text
    opening = agent_runs.RunMessageRow(idx=0, role="human", content="Write the second file.",
                                       usage_json=json.dumps({"control": {"task": task}}))
    assert F.task_of(opening)["constraints"][0]["turn"] == 1


def test_a_follow_up_turn_records_its_task_and_the_classifier_reads_the_constraint(store, monkeypatch, route):
    """The earlier turn restricted the collection. The short follow-up keeps that
    restriction in its recorded task and in the input of the preparation request."""
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
    asked = [body for url, body in route["route"].bodies if "sources=" in body.get("questions", {})]
    assert asked and "Search only the testdata collection." in asked[0]["state"]["request"]
    assert asked[0]["state"]["request"].startswith("objective: Search only the testdata collection. Who approved")
    assert "amendments:\n- Now write two files, a.md and b.md." in asked[0]["state"]["request"]


def test_one_file_of_three_requested_files_is_no_delivery_evidence():
    """The classifier answer stays an observation. With one of three named files stored, the
    level note has no completion advice, and the ledger names the missing files."""
    from tasks.P_agent.control.handlers.progress import COMPLETION_ADVICE, Handler
    task = freeze({"objective": {"text": "Write three files: a.md, b.md and c.md.", "source": "user"}})
    stalled = {"level": 0, "units": 2}
    search = _fact("search_collections", item_count=0, args={"query": "x"})
    one = _fact("write_file", file_version=("a.md", 1, True), call_id="w1")
    context = replace(_progress_context(stalled, (search,), 2), results=(one, search), task=task)
    partial = asyncio.run(Handler().evaluate(_event(), context, {}, _Signals(0.95)))
    note = next(a for a in partial.actions if a.kind == "append_note")
    assert COMPLETION_ADVICE not in note.arguments["text"]
    ledger = plain_facts(partial)
    assert ledger["delivery"]["state"] == "incomplete" and ledger["delivery"]["missing"] == ["b.md", "c.md"]
    assert ledger["answered"] is True and ledger["delivery_evidence"] is False
    writes = tuple(_fact("write_file", file_version=(n, 1, True), call_id=f"w-{n}") for n in ("a.md", "b.md", "c.md"))
    complete = asyncio.run(Handler().evaluate(_event(), replace(context, results=writes + (search,)), {}, _Signals(0.95)))
    note = next(a for a in complete.actions if a.kind == "append_note")
    assert COMPLETION_ADVICE in note.arguments["text"]
    assert plain_facts(complete)["delivery"]["state"] == "complete"
    # A file write still counts as progress for the deterministic ledger.
    progress = asyncio.run(Handler().evaluate(_event(), replace(_progress_context(stalled, (one,), 2), results=(one,), task=task), {}, _Signals(0.0)))
    assert plain_facts(progress)["level"] == 0 and plain_facts(progress)["units"] == 0


def test_a_cancelled_preparation_keeps_its_samples_and_applies_no_action(store, monkeypatch, route):
    """The run stops while the name request blocks. The activity raises the cancellation
    after the children end, stores no decision and starts no call, and the request samples
    are written with no applied action."""
    import threading

    _pin(store, monkeypatch, _definition([PREPARE], {"preparation_seconds": 3}))
    written = []
    monkeypatch.setattr(C, "write_events", lambda row, record: written.append(record))

    class Blocked(_Route):
        def __call__(self, session, url, body, key, timeout):
            import time
            if "names=" in body.get("questions", {}):
                time.sleep(1.5)
            return super().__call__(session, url, body, key, timeout)

    route["route"] = Blocked({"skill_spreadsheets=": {"noul": 0.97}})
    env = ActivityEnvironment()
    threading.Timer(0.4, env.cancel).start()
    with pytest.raises(BaseException) as raised:
        env.run(control_steps.control_event, control_steps.ControlParams(
            run_id=RUN_ID, username="u", session_id="s", hook="turn_started", anchor_idx=0,
            allowed_collections=["testdata"], internet_tools=True, deadline_seconds=3.0))
    assert type(raised.value).__name__ == "CancelledError"
    control = store["messages"][0].usage["control"]
    assert "turn_started" not in (control.get("decisions") or {})
    assert len(store["messages"]) == 1
    assert written and all(e["actions"] == 0 for e in written[-1]["classifier_events"])
    assert written[-1]["classifier_events"], "the request samples are kept"


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
    _pin(store, monkeypatch, _definition([PREPARE]))
    _hook("turn_started", 0)
    return read


def test_the_pin_stores_one_task_record_and_a_retry_or_a_code_change_keeps_it(store, monkeypatch, route):
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


def test_a_continuation_reads_the_stored_record_of_the_last_turn_and_its_files(store, monkeypatch, route):
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


def test_a_legacy_session_is_rebuilt_from_its_requests_within_the_bound(store, monkeypatch, route):
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


def test_a_board_turn_keeps_its_structured_task_as_its_record(store, monkeypatch, route):
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
