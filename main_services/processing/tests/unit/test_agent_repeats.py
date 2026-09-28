"""The repeat stop of `AgentRun`: the key of a call, the count of its runs, the texts of a
refused call, the streak, the repeat note and the listing of a sub-agent with no answer.

Each case builds a stored thread with `Sim`, which asks `steps.repeat_sources` which calls of
each new reply repeat, stores a `repeated_call` result for those and the given result for the
others, and records the streak of the reply. No database and no service runs.
"""

import json

from database import agent_runs
from tasks.P_agent import steps, thread_facts
from tasks.P_agent.steps import RepeatSource

THREAD = "0b5e3c1a-1111-4222-8333-944455556666"
RUN = THREAD

#: The literal result strings that `agent_tests/test_thread_index.py` also reads.
TODAY_EMPTY = json.dumps({"success": True, "items": [], "fields": {"total_count": 0}})
TODAY_FULL = json.dumps({"success": True, "items": [{"file_hash": "a" * 64}],
                         "fields": {"total_count": 1}})
SLIM_EMPTY = json.dumps({"items": [], "notes": ["'Raptor approval': 0 found"]})
SLIM_FULL = json.dumps({"items": [{"file_hash": "a5ee8d51b5bc1579"}, {"file_hash": "b" * 16}],
                        "more": "c7f3a91b0d2e"})
REFUSAL = json.dumps({"success": False, "error": "invalid_arguments", "message": "no"})


def ok(**body):
    return json.dumps({"success": True, **body})


class Sim:
    """A stored run thread that grows one reply at a time, as `model_step` and the tool
    steps write it."""

    def __init__(self, kind="chat"):
        self.kind = kind
        self.rows = [agent_runs.RunMessageRow(idx=0, role="human", content="q", run_id=RUN)]
        self.step_no = 0
        self.results = {}

    def _add(self, **fields):
        row = agent_runs.RunMessageRow(idx=len(self.rows), run_id=RUN, **fields)
        self.rows.append(row)
        return row

    def human(self, text):
        self._add(role="human", content=text)

    def compaction(self, **record):
        self._add(role="compaction", content=json.dumps(record))

    def step(self, *calls, synthetic=False):
        """One reply. Each call is `(name, args, content)` or `(name, args, content,
        status)`. Returns `(repeats, streak)`."""
        self.step_no = 0 if synthetic else self.step_no + 1
        entries = []
        for position, call in enumerate(calls):
            name, args = call[0], call[1]
            entries.append({"id": f"s{self.step_no}c{position}", "name": name, "args": args,
                            "kind": "delegation" if name == "run_subagent" else "parallel",
                            "position": position})
        earlier = list(self.rows)
        repeats = steps.repeat_sources(earlier, entries, THREAD)
        usage = {"step_no": self.step_no, **({"synthetic": True} if synthetic else {})}
        ai = self._add(role="ai", tool_calls_json=json.dumps(entries),
                       usage_json=json.dumps(usage))
        streak = steps.repeat_streak(earlier, ai, repeats)
        for position, (entry, call) in enumerate(zip(entries, calls)):
            source = repeats.get(position)
            if source is not None:
                content = json.dumps({"success": False, "error": steps.REPEATED_CALL_CLASS,
                                      "message": steps.repeat_text(source, self.kind)})
                usage = {"status": "error", "error_class": steps.REPEATED_CALL_CLASS}
            else:
                content = call[2]
                usage = {"status": call[3] if len(call) > 3 else "ok"}
            self.results[entry["id"]] = self._add(
                role="tool", content=content, tool_call_id=entry["id"], tool_name=entry["name"],
                usage_json=json.dumps(usage))
        return repeats, streak


def search(query, content=TODAY_FULL, name="search_collections", status="ok"):
    return (name, {"query": query}, content, status)


# ------------------------------------------------------------ the number of runs of one call


def test_a_search_runs_three_times_and_the_fourth_names_three_calls_and_step_1():
    sim = Sim()
    for _ in range(3):
        repeats, _streak = sim.step(("web_search", {"q": "x"}, ok(results=[{"url": "u"}])))
        assert repeats == {}
    repeats, streak = sim.step(("web_search", {"q": "x"}, ok(results=[])))
    assert repeats == {0: RepeatSource("s1c0", 1, "result", 3)} and streak == 1
    message = json.loads(sim.results["s4c0"].content)["message"]
    assert message.startswith("This call has the same name and arguments as 3 earlier calls, "
                              "the first being call s1c0 of step 1, so it was not run.")
    assert message.endswith(steps.SKILL_LINE.format(skill="after_a_result"))


def test_a_browser_snapshot_never_repeats():
    sim = Sim()
    for _ in range(5):
        repeats, streak = sim.step(("browser_snapshot", {}, ok(snapshot="")))
        assert repeats == {} and streak == 0


def test_the_same_append_child_with_no_plan_write_between_is_refused():
    sim = Sim()
    args = {"parent_id": "1", "text": "a"}
    sim.step(("append_child", args, ok(version=2)))
    repeats, _ = sim.step(("append_child", args, ok(version=3)))
    assert repeats == {0: RepeatSource("s1c0", 1, "result", 1)}
    assert "as call s1c0 of step 1, so it was not run. Its result is above." in json.loads(
        sim.results["s2c0"].content)["message"]


def test_a_failed_run_does_not_count():
    sim = Sim()
    sim.step(search("x", REFUSAL))
    for _ in range(3):
        repeats, _ = sim.step(search("x"))
        assert repeats == {}
    repeats, _ = sim.step(search("x"))
    assert repeats[0].call_id == "s2c0" and repeats[0].runs == 3


# ------------------------------------------------------------ the cases of the repeats report


def _append_nodes(n):
    return [("append_node", {"text": f"section {i}"}, ok(version=2 + i)) for i in range(n)]


def _append_children(first_version):
    return [("append_child", {"parent_id": str(1 + i % 4), "text": f"task {i}"},
             ok(version=first_version + i)) for i in range(15)]


def test_exempt_reads_and_a_changed_tree():
    """Steps 4 to 11 of the planner run of the repeats report: the sources of step 5 key on
    version 20, the sources of step 4 on 5."""
    sim = Sim(kind="planner")
    for _ in range(3):
        sim.step(search("prep"), search("prep 2"), search("prep 3"))
    sim.step(*_append_nodes(4))                              # step 4, versions 2 to 5
    sim.step(*_append_children(6))                           # step 5, versions 6 to 20
    sim.step(search("between"))                              # step 6
    repeats7, streak7 = sim.step(*_append_children(6))       # step 7
    repeats8, streak8 = sim.step(*_append_children(6))       # step 8
    assert len(repeats7) == len(repeats8) == 15 and (streak7, streak8) == (1, 2)
    assert {r.step_no for r in repeats7.values()} == {5}
    repeats9, streak9 = sim.step(("read_plan", {}, ok(version=20)))
    assert repeats9 == {} and streak9 == 0
    cap = json.dumps({"success": False, "error": "This change makes 5 sections"})
    refused = [(n, a, cap) for n, a, _c in _append_nodes(4)]
    repeats10, streak10 = sim.step(*refused)                 # step 10
    repeats11, streak11 = sim.step(*refused)                 # step 11
    assert (repeats10, streak10, repeats11, streak11) == ({}, 0, {}, 0)
    assert not any(r.role == "human" and r.content.startswith(steps.REPEAT_NOTE_HEAD)
                   for r in sim.rows)


def test_a_real_todo_change_runs_the_same_edit_again():
    sim = Sim()
    edit = ("edit_todo", {"id": "2", "text": "read the memo"}, ok(version=4))
    sim.step(edit)
    sim.step(("mark_todo", {"ids": ["1"], "status": "done"}, ok(version=5)))
    repeats, _ = sim.step(edit)
    assert repeats == {}


def test_a_positional_parent_on_a_changed_tree_runs():
    sim = Sim(kind="planner")
    call = ("append_child", {"parent_id": "3", "text": "x"}, ok(version=11))
    sim.step(call)
    sim.step(("append_child", {"parent_id": "1", "text": "y"}, ok(version=12)))
    sim.step(("append_child", {"parent_id": "2", "text": "z"}, ok(version=13)))
    repeats, _ = sim.step(call)
    assert repeats == {}


def test_a_write_sent_again_in_one_step_keys_on_the_newest_version_of_its_step():
    sim = Sim()
    a = ("append_child", {"parent_id": "1", "text": "a"}, ok(version=2))
    sim.step(a, ("append_child", {"parent_id": "1", "text": "b"}, ok(version=3)))
    repeats, _ = sim.step(a)
    assert repeats == {0: RepeatSource("s1c0", 1, "result", 1)}
    message = json.loads(sim.results["s2c0"].content)["message"]
    assert message.endswith(steps.SKILL_LINE.format(skill="after_a_result"))


def test_a_limit_step_with_an_exempt_read_reaches_the_limit():
    sim = Sim()
    for _ in range(3):
        sim.step(search("x"))
    sim.step(search("x"))
    sim.step(search("x"))
    repeats, streak = sim.step(search("x"), ("read_todo", {}, ok(version=1)))
    assert list(repeats) == [0] and streak == steps.REPEAT_STEP_LIMIT


def test_a_true_loop_on_an_empty_search_gets_the_empty_text():
    sim = Sim()
    for _ in range(3):
        sim.step(search("Raptor approval", TODAY_EMPTY))
    repeats, _ = sim.step(search("Raptor approval", TODAY_EMPTY))
    assert repeats[0].kind == "empty"
    message = json.loads(sim.results["s4c0"].content)["message"]
    assert "3 earlier calls, the first being call s1c0 of step 1, which found nothing" in message
    assert message.endswith(steps.SKILL_LINE.format(skill="no_results"))


def test_a_true_loop_with_content_gets_the_result_text():
    sim = Sim(kind="subagent")
    read = ("read_documents", {"documents": [{"file_hash": "a" * 16}]},
            ok(items=[{"file_hash": "a" * 16, "page": 1}]))
    for _ in range(3):
        sim.step(read)
    repeats, _ = sim.step(read)
    assert repeats[0].kind == "result"
    assert json.loads(sim.results["s4c0"].content)["message"].endswith(
        steps.SKILL_LINE.format(skill="after_a_result"))


def test_a_delegation_sent_again_starts_no_sub_agent_and_names_no_skill():
    sim = Sim(kind="organizer")
    briefings = {"tasks": [{"objective": "read the memo"}]}
    sim.step(("run_subagent", briefings, ok(report="r")))
    repeats, _ = sim.step(("run_subagent", briefings, ok(report="r")))
    assert repeats[0].kind == "delegation"
    message = json.loads(sim.results["s2c0"].content)["message"]
    assert message == steps.REPEAT_TEXT_DELEGATION.format(call_id="s1c0", step_no=1)


def test_an_evicted_source_is_not_a_repeat():
    sim = Sim()
    for _ in range(3):
        sim.step(search("x"))
    sim.compaction(evicted=[[THREAD, sim.results["s1c0"].idx]], summarised=[])
    repeats, _ = sim.step(search("x"))
    assert repeats == {}


def test_a_dropped_skill_read_again_runs():
    # A run-start read keeps 1 run, so only the compaction lets the read run again.
    sim = Sim()
    read = ("read_skill", {"name": "search"}, "Skill `search`.")
    sim.step(read, synthetic=True)
    sim.compaction(version=2, summarised=[], dropped=[[THREAD, sim.results["s0c0"].idx]])
    repeats, _ = sim.step(read)
    assert repeats == {}


def test_a_cut_source_is_not_a_repeat():
    sim = Sim()
    for _ in range(3):
        sim.step(search("x"))
    sim.compaction(version=2, summarised=[], cuts=[[THREAD, sim.results["s2c0"].idx, 100]])
    repeats, _ = sim.step(search("x"))
    assert repeats == {}


def test_a_synthetic_source_gets_the_start_text():
    sim = Sim()
    sim.step(("read_skill", {"name": "search"}, "Skill `search`."), synthetic=True)
    repeats, _ = sim.step(("read_skill", {"name": "search"}, "Skill `search`."))
    assert repeats[0].kind == "start"
    message = json.loads(sim.results["s1c0"].content)["message"]
    assert message.startswith("This call has the same name and arguments as call s0c0, "
                              "which this run made at its start")


def test_the_second_limit_counts_the_note():
    sim = Sim()
    for _ in range(6):
        sim.step(search("x"))
    sim.human(steps.repeat_note_text(sim.rows, None))
    streaks = [sim.step(search("x"))[1] for _ in range(3)]
    assert streaks == [1, 2, 3]
    assert steps.repeat_notes(sim.rows, RUN) == 1


def test_a_run_of_kind_planner_gets_no_skill_line():
    source = RepeatSource("c", 1, "empty", 1)
    assert steps.SKILL_LINE.format(skill="no_results") not in steps.repeat_text(source, "planner")
    assert steps.repeat_text(source, "chat").endswith(steps.SKILL_LINE.format(skill="no_results"))


# ------------------------------------------------------------ found_nothing and the listing


def test_found_nothing_reads_the_shared_result_strings():
    assert thread_facts.found_nothing("search_collections", TODAY_EMPTY)
    assert thread_facts.found_nothing("search_passages", SLIM_EMPTY)
    assert thread_facts.found_nothing("web_search", json.dumps({"results": []}))
    assert not thread_facts.found_nothing("search_collections", TODAY_FULL)
    assert not thread_facts.found_nothing("search_collections", SLIM_FULL)
    assert not thread_facts.found_nothing("search_collections", REFUSAL)
    assert not thread_facts.found_nothing("read_documents", TODAY_EMPTY)


def test_the_repeat_note_lists_open_items_and_empty_searches():
    sim = Sim()
    sim.step(("search_collections", {"queries": ["Pier 7 lease", "Harbor Estates"],
                                     "collections": ["enron"]}, TODAY_EMPTY))
    todo = {"items": [{"id": "3", "text": "Find the board minutes that approve the lease",
                       "status": "pending"},
                      {"id": "4", "text": "done one", "status": "done"}]}
    text = steps.repeat_note_text(sim.rows, todo)
    assert text.splitlines() == [
        "Repeat note. Your last 3 replies only repeated earlier calls, so none of them ran.",
        "These todo items are still open:",
        '- 3 "Find the board minutes that approve the lease"',
        "These searches found nothing:",
        '- search_collections ["Pier 7 lease", "Harbor Estates"] filters '
        '{"collections": ["enron"]}',
        "Do not send these calls again. Change the query, remove a filter, work on an open "
        "item, or write your answer. If the next 3 replies repeat earlier calls again, the "
        "run must answer."]
    assert not steps.FINAL_TEXT["repeated_call"].startswith(steps.REPEAT_NOTE_HEAD)
    assert "todo items" not in steps.repeat_note_text(sim.rows, None)


def test_the_listing_names_documents_read_returned_and_searches_with_nothing():
    sim = Sim(kind="subagent")
    hit = {"collectionname": "enron", "file_hash": "a5ee8d51b5bc1579",
           "path": "/maildir/lay-k/inbox/40"}
    for q in ("a", "b", "c"):
        sim.step(search(q, ok(items=[hit])))
    sim.step(search("Raptor approval", TODAY_EMPTY))
    sim.step(("read_documents", {}, ok(items=[
        {"collectionname": "enron", "file_hash": "5e8bb0ff3822761c",
         "path": "/maildir/kean-s/sent/12", "page": 1},
        {"collectionname": "enron", "file_hash": "5e8bb0ff3822761c",
         "path": "/maildir/kean-s/sent/12", "page": 2}])))
    assert thread_facts.found_documents_text(sim.rows).splitlines() == [
        thread_facts.LISTING_HEAD,
        "## Documents read",
        "- enron/5e8bb0ff3822761c /maildir/kean-s/sent/12. pages 1, 2",
        "## Documents that the searches returned",
        "- enron/a5ee8d51b5bc1579 /maildir/lay-k/inbox/40. in 3 searches",
        "## Searches that found nothing",
        '- search_collections "Raptor approval" filters {}']


def test_the_final_text_of_a_sub_agent_ends_with_its_bring_back():
    row = agent_runs.RunRow(run_id=RUN, username="u", session_id="s", kind="subagent", depth=1,
                            briefing=json.dumps({"objective": "o", "bring_back": "The dates."}))
    params = steps.ModelStepParams(run_id=RUN, username="u", session_id="s", mode="final",
                                   final_reason="repeated_call")
    assert steps.final_text(row, params) == (steps.FINAL_TEXT["repeated_call"]
                                             + "\n\nBring back: The dates.")
    params.empty_retry = True
    assert steps.final_text(row, params) == steps.EMPTY_ANSWER_TEXT + "\n\nBring back: The dates."
