"""`POST /preload`: the classifier forms, the picks, and the reads of a run start."""

from __future__ import annotations

import json

import httpx
import pytest

from agent_common.tool_packs import allowed_tools
from research_agent import preload, skill_store, steps
from research_agent.agent import AgentContext
from research_agent.skill_store import SkillContext, load_skills
from research_agent.tool_catalogue import build_snapshot

LOCAL_TOOLS = {"search_agent_tools", "search_skills", "read_skill", "read_tool"}


class FakeTool:
    def __init__(self, name):
        self.name = name
        self.description = f"Do the work of {name.replace('_', ' ')}.\nMore text."
        self.args_schema = {"type": "object", "properties": {"query": {"type": "string"}},
                            "required": ["query"]}


class FakeAgent:
    """One step context over fake tools of the run kind's packs, as `context_for` gives."""

    def __init__(self, kind="chat", packs="all", profile=None):
        allowed = allowed_tools(kind, packs)
        tools = [FakeTool(n) for n in sorted(allowed) if n not in LOCAL_TOOLS]
        # A chat keeps the profile of its container, here the full research agent.
        ctx = SkillContext(profile=profile or skill_store.RUN_KIND_PROFILES.get(
                               kind, "full_research"),
                           tool_names=frozenset())
        snapshot = build_snapshot(tools, allowed, kind, ctx)
        self.context = AgentContext(snapshot=snapshot, tools=tools, llm_kwargs={},
                                    model_id="stub-model",
                                    system_text_for=lambda names: "system",
                                    skill_context=snapshot.skill_context)
        self.contexts = 0

    async def context_for(self, *args, **kwargs):
        self.contexts += 1
        return self.context


class Classifier:
    """A stub of the `systemone` route. It answers each form from a table of scores."""

    def __init__(self, types=None, tools=None, skills=None, fail=()):
        self.scores = {"types": types or {}, "tools": tools or {}, "skills": skills or {}}
        self.fail = dict.fromkeys(fail, 422) if not isinstance(fail, dict) else fail
        self.bodies = []

    @staticmethod
    def part_of(body):
        ids = set(body["questions"])
        if "topic=" in ids:
            return "types"
        if "search_passages=" in ids or "doc_email=" in ids:
            return "tools"
        return "skills"

    def handler(self, request):
        body = json.loads(request.content)
        self.bodies.append((request, body))
        part = self.part_of(body)
        if part in self.fail:
            return httpx.Response(self.fail[part], json={"error": {"message": "refused"}})
        answers = {qid: {"noul": self.scores[part].get(qid[:-1], 0.0)}
                   for qid in body["questions"]}
        return httpx.Response(200, json={"model": body["model"], "answers": answers})


@pytest.fixture
def classifier(monkeypatch):
    monkeypatch.setenv("LLM_CLASSIFIER_URL", "http://classifier.test/v1/systemone")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "stub-model")
    holder = {}

    def install(stub):
        holder["stub"] = stub
        monkeypatch.setattr(preload, "_client", lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(stub.handler)))
        return stub

    return install


RUN = {"run_id": "r1", "depth": 0, "username": "alice", "session_id": "s1",
       "allowed_collections": ["testdata"]}


def request(kind="chat", classify="all", **extra):
    return preload.PreloadRequest(**RUN, kind=kind, request_text="Find the emails of Jeff.",
                                  classify=classify, **extra)


def names_of(result, tool="read_skill"):
    return [r["args"]["name"] for r in result["reads"] if r["name"] == tool]


# ------------------------------------------------------------------------ the picks


def test_two_classes_above_the_second_limit_are_kept_best_first():
    assert preload.request_classes({"topic": 0.93, "person": 0.61, "web": 0.1}) == [
        "topic", "person"]


def test_a_second_class_under_the_limit_is_dropped():
    assert preload.request_classes({"topic": 0.93, "person": 0.49}) == ["topic"]


def test_a_class_tie_goes_to_the_order_of_the_form():
    assert preload.request_classes({"person": 0.8, "topic": 0.8}) == ["topic", "person"]


def test_a_plan_tool_and_a_bound_tool_are_not_picked():
    snap = FakeAgent().context.snapshot
    picks = preload.tool_picks({"doc_email": 0.97, "append_node": 0.98,
                                "search_passages": 0.95}, snap.deferred_names)
    assert [n for n, _ in picks] == ["doc_email"]


def test_eight_tools_above_the_limit_give_six_and_a_tie_goes_by_name():
    snap = FakeAgent().context.snapshot
    names = ["doc_email", "doc_metadata", "doc_sources", "folder_list", "table_page",
             "web_search", "whois_lookup", "read_more"]
    picks = preload.tool_picks(dict.fromkeys(names, 0.5), snap.deferred_names)
    assert [n for n, _ in picks] == sorted(names)[:6]


def test_four_technique_skills_give_three_and_three_stumble_skills_give_two():
    ctx = FakeAgent().context.skill_context
    technique = preload.skill_picks({"emails": 0.9, "passages": 0.8, "entities": 0.75,
                                     "spreadsheets": 0.71}, ctx, "technique", 0.7, 3)
    stumble = preload.skill_picks({"document_ids": 0.95, "no_results": 0.92,
                                   "call_arguments": 0.91}, ctx, "stumble", 0.9, 2)
    assert [n for n, _ in technique] == ["emails", "passages", "entities"]
    assert [n for n, _ in stumble] == ["document_ids", "no_results"]


def test_a_general_skill_score_is_not_a_technique_pick():
    ctx = FakeAgent().context.skill_context
    assert preload.skill_picks({"search": 0.99}, ctx, "technique", 0.7, 3) == []


# ------------------------------------------------------------------------ the forms


def test_the_three_forms_hold_the_calibrated_questions():
    snap = FakeAgent().context.snapshot
    types = preload.types_body("x" * 2000, "m")
    tools = preload.tools_body("q", "m", dict(snap.summaries))
    skills = preload.skills_body("q", "m", skill_store.SKILLS)
    assert len(types["state"]["request"]) == 1500
    assert list(types["questions"]) == [f"{c}=" for c in preload.CLASS_ORDER]
    assert types["questions"]["topic="]["instructions"].startswith(
        "Is this request of the kind 'topic': find documents")
    assert len(tools["questions"]) == 39 and all(q.endswith("=") for q in tools["questions"])
    assert tools["questions"]["doc_email="]["instructions"] == (
        "Will the agent call the tool `doc_email`? The tool: Do the work of doc email.")
    assert len(skills["questions"]) == 20
    assert skills["questions"]["emails="]["instructions"] == (
        "Should the agent read the skill `emails`? It teaches: "
        + skill_store.SKILLS["emails"].description)
    assert all(len(b["questions"]) <= 64 for b in (types, tools, skills))


# ------------------------------------------------------------------------ the route


async def test_a_first_chat_turn_reads_the_general_skills_the_picks_and_the_tools(classifier):
    stub = classifier(Classifier(
        types={"topic": 0.93, "person": 0.61},
        tools={"doc_email": 0.97, "append_node": 0.98, "search_passages": 0.95},
        skills={"emails": 0.91, "search": 0.99, "document_ids": 0.94}))
    result = await preload.run_preload(FakeAgent(), request())
    assert result["request_classes"] == ["topic", "person"]
    assert names_of(result) == ["search", "thorough", "method_chat_full", "citation",
                                "plan_first", "emails", "document_ids"]
    assert names_of(result, "read_tool") == ["doc_email"]
    assert json.loads(result["reads"][-1]["content"])["ready"] == "next call"
    assert result["reads"][0]["content"].startswith("Skill `search`.")
    assert all(r["status"] == "ok" and r["id"] == "" for r in result["reads"])
    assert result["picks"]["tools"] == [["doc_email", 0.97]]
    assert result["todo_item_text"] == "Read relevant tools and skills"
    assert result["classifier"]["state"] == "ok"
    assert len(stub.bodies) == 3
    assert all(r.headers["authorization"] == "Bearer test-key" for r, _ in stub.bodies)


async def test_a_skill_that_an_earlier_turn_read_is_not_read_again(classifier):
    classifier(Classifier())
    result = await preload.run_preload(
        FakeAgent(), request(classify="none", already_read=["search", "citation"]))
    assert names_of(result) == ["thorough", "method_chat_full", "plan_first"]


async def test_a_refused_tools_request_gives_partial_and_no_tool_pick(classifier):
    classifier(Classifier(tools={"doc_email": 0.97}, skills={"emails": 0.91}, fail=("tools",)))
    result = await preload.run_preload(FakeAgent(), request())
    assert result["classifier"]["state"] == "partial"
    assert "tools" in result["classifier"]["error"]
    assert result["picks"]["tools"] == [] and names_of(result, "read_tool") == []
    assert names_of(result)[:5] == ["search", "thorough", "method_chat_full", "citation",
                                    "plan_first"]


async def test_every_request_refused_gives_failed_and_the_always_read_skills(classifier):
    classifier(Classifier(fail={"types": 500, "tools": 422, "skills": 502}))
    result = await preload.run_preload(FakeAgent(), request())
    assert result["classifier"]["state"] == "failed"
    assert result["request_classes"] == []
    assert len(names_of(result)) == 5


async def test_an_empty_classifier_url_gives_off_and_sends_nothing(classifier, monkeypatch):
    stub = classifier(Classifier(types={"topic": 0.9}))
    monkeypatch.setenv("LLM_CLASSIFIER_URL", "")
    result = await preload.run_preload(FakeAgent(), request())
    assert result["classifier"] == {"state": "off", "error": "", "ms": 0}
    assert stub.bodies == [] and result["request_classes"] == []
    assert len(names_of(result)) == 5


async def test_a_subagent_reads_its_skills_with_no_classifier(classifier):
    stub = classifier(Classifier(types={"topic": 0.9}))
    result = await preload.run_preload(FakeAgent("subagent"), request("subagent", "none"))
    assert stub.bodies == []
    assert names_of(result) == ["search", "thorough", "method_subagent", "citation",
                                "plan_first"]


async def test_a_planner_sends_the_types_request_only(classifier):
    stub = classifier(Classifier(types={"deep": 0.9}))
    agent = FakeAgent("planner", "collections,web,plan")
    result = await preload.run_preload(agent, request("planner", "types"))
    assert [Classifier.part_of(b) for _, b in stub.bodies] == ["types"]
    assert names_of(result) == ["search", "thorough", "method_planner", "citation"]
    assert names_of(result, "read_tool") == []


# --------------------------------------------------------- the classes in the skill text


@pytest.fixture
def class_store(tmp_path, monkeypatch):
    for name, group, tools in (("method_planner", "role", ""),
                               ("search", "general", "search_collections")):
        (tmp_path / f"{name}.md.j2").write_text(
            f"---\nname: {name}\ngroup: {group}\ndescription: the {name} text\n"
            f"tools: {tools}\n---\nclasses={{{{ request_classes | join(\",\") }}}}\n")
    monkeypatch.setattr(skill_store, "SKILLS", load_skills(tmp_path))


async def test_a_planner_read_renders_the_classes_and_a_later_read_does_not(classifier,
                                                                           class_store):
    classifier(Classifier(types={"person": 0.9, "topic": 0.8}))
    agent = FakeAgent("planner", "collections,web,plan")
    result = await preload.run_preload(agent, request("planner", "types"))
    read = next(r for r in result["reads"] if r["args"]["name"] == "method_planner")
    assert read["content"].endswith("classes=person,topic")
    later = await steps.run_tool_call(agent, steps.ToolCallRequest(
        **RUN, kind="planner", call={"id": "c1", "name": "read_skill",
                                     "args": {"name": "method_planner"}},
        idempotency_key="key-1"))
    assert later["status"] == "ok"
    assert later["content"].endswith("classes=")


async def test_a_chat_read_renders_no_classes(classifier, class_store):
    classifier(Classifier(types={"person": 0.9, "topic": 0.8}))
    result = await preload.run_preload(FakeAgent(), request())
    assert result["request_classes"] == ["person", "topic"]
    read = next(r for r in result["reads"] if r["args"]["name"] == "search")
    assert read["content"].endswith("classes=")


async def test_a_planner_preload_renders_the_packing_of_its_classes(classifier, monkeypatch):
    """The synthetic read holds the classes and the window of the run's model. A later read
    with the cached context holds the unknown kind at the default window."""
    from research_agent import compaction
    from research_agent.skill_tools import read_skill_result

    monkeypatch.setattr(compaction, "context_window",
                        lambda model: 262_144 if model == "stub-model" else 0)
    classifier(Classifier(types={"person": 0.9, "topic": 0.8}))
    agent = FakeAgent("planner", "collections,web,plan")
    result = await preload.run_preload(agent, request("planner", "types"))
    read = next(r for r in result["reads"] if r["args"]["name"] == "method_planner")
    assert "of the kind person and topic" in read["content"]
    assert "about 6 tasks" in read["content"]
    cached = agent.context.skill_context
    later = read_skill_result("method_planner", cached)
    assert "of the kind unknown" in later and "about 6 tasks" in later
    differ = [(a, b) for a, b in zip(read["content"].splitlines(), later.splitlines()) if a != b]
    assert len(differ) == 1 and "of the kind" in differ[0][0]
    assert (cached.request_classes, cached.model_id) == ((), "")
