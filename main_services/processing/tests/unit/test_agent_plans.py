"""The plan tree rules of `database.agent_plans`, with no database.

Cases: `plan-tree` (every operation keeps a valid tree and renumbers siblings), `plan-bound`
(the 150-node bound and the text rules), `root-immutable` (the root cannot move or go, and
its text can change), and the section rule, which makes a flat plan one section.
"""

from datetime import datetime, timedelta

import pytest

from database import agent_plans as ap

PLAN = "0b8e6f8a-3f52-4a55-9d6c-6f6a1c1f2e10"


def _tree(*ops):
    snap = ap.initial_snapshot(PLAN, "What happened to the shipment in March?")
    for op, args in ops:
        snap = ap.apply(snap, op, **args)
    return snap


def _ids(snap):
    return {n.text: n.node_id for n in snap.nodes}


class TestPlanTree:
    def test_version_one_holds_the_root_with_the_first_line_of_the_query(self):
        snap = ap.initial_snapshot(PLAN, "  Line one\nline two  ")
        assert snap.version == 1
        assert [(n.node_id, n.parent_id, n.ordinal, n.text) for n in snap.nodes] == [
            (ap.root_node_id(PLAN), None, 1, "Line one line two")]

    def test_each_operation_writes_the_next_version_and_renumbers_siblings(self):
        snap = _tree(("append_node", {"text": "A"}), ("append_node", {"text": "B"}),
                     ("append_node", {"text": "C"}))
        assert snap.version == 4
        ids = _ids(snap)
        snap = ap.apply(snap, "append_child", parent_id=ids["A"], text="A1")
        snap = ap.apply(snap, "move_node", node_id=ids["C"], new_parent_id="", position=1)
        top = [n.text for n in ap.children_of(snap, snap.root_id)]
        assert top == ["C", "A", "B"]
        snap = ap.apply(snap, "remove_node", node_id=ids["A"])
        assert [(n.text, n.ordinal) for n in ap.children_of(snap, snap.root_id)] == [
            ("C", 1), ("B", 2)]
        assert "A1" not in _ids(snap)
        snap = ap.apply(snap, "edit_node", node_id=ids["B"], text="B edited")
        assert _ids(snap)["B edited"] == ids["B"]
        assert snap.version == 8

    def test_a_node_id_is_the_same_on_a_retry_of_the_same_version(self):
        a = _tree(("append_node", {"text": "A"}))
        b = _tree(("append_node", {"text": "A"}))
        assert a.nodes == b.nodes and a.checksum == b.checksum

    def test_a_move_under_its_own_subtree_is_refused(self):
        snap = _tree(("append_node", {"text": "A"}))
        snap = ap.apply(snap, "append_child", parent_id=_ids(snap)["A"], text="A1")
        ids = _ids(snap)
        with pytest.raises(ap.PlanError, match="own subtree"):
            ap.apply(snap, "move_node", node_id=ids["A"], new_parent_id=ids["A1"])

    def test_an_unknown_parent_is_refused(self):
        with pytest.raises(ap.PlanError, match="no node has the id"):
            _tree(("append_child", {"parent_id": "nope", "text": "x"}))

    def test_the_validator_refuses_a_second_root_and_a_duplicate_ordinal(self):
        root = ap.root_node_id(PLAN)
        with pytest.raises(ap.PlanError, match="exactly one root"):
            ap.validate(ap.PlanSnapshot(PLAN, 2, (
                ap.PlanNode(root, None, 1, "r"), ap.PlanNode("x", None, 2, "x"))))
        with pytest.raises(ap.PlanError, match="same ordinal"):
            ap.validate(ap.PlanSnapshot(PLAN, 2, (
                ap.PlanNode(root, None, 1, "r"), ap.PlanNode("a", root, 1, "a"),
                ap.PlanNode("b", root, 1, "b"))))

    def test_nodes_json_round_trips(self):
        snap = _tree(("append_node", {"text": "A"}), ("append_node", {"text": "B"}))
        assert ap.nodes_from_json(ap.nodes_json(snap.nodes)) == tuple(
            sorted(snap.nodes, key=lambda n: (n.parent_id is not None, n.ordinal)))


class TestNumberPaths:
    """A parent can be named by the number path that `render_tree` shows. The calls are
    the calls of one planner reply that put every node under the root."""

    def test_a_number_path_names_the_parent_of_append_child(self):
        snap = _tree(("append_node", {"text": "Survey"}),
                     ("append_child", {"parent_id": "1", "text": "Search every collection"}),
                     ("append_node", {"text": "Roles"}),
                     ("append_child", {"parent_id": "2.", "text": "Count per collection"}),
                     ("append_child", {"parent_id": " 1.1 ", "text": "One level down"}))
        ids = _ids(snap)
        parent = {n.text: n.parent_id for n in snap.nodes}
        assert parent["Search every collection"] == ids["Survey"]
        assert parent["Count per collection"] == ids["Roles"]
        assert parent["One level down"] == ids["Search every collection"]
        assert [n.text for n, _ in ap.sections(snap)] == ["Search every collection", "Roles"]

    def test_root_names_the_root_and_a_path_names_the_move_target(self):
        snap = _tree(("append_node", {"text": "A"}), ("append_node", {"text": "B"}),
                     ("append_child", {"parent_id": "root", "text": "C"}))
        ids = _ids(snap)
        assert {n.text: n.parent_id for n in snap.nodes}["C"] == snap.root_id
        snap = ap.apply(snap, "move_node", node_id=ids["C"], new_parent_id="2", position=1)
        assert [n.text for n in ap.children_of(snap, ids["B"])] == ["C"]

    def test_a_path_that_names_no_node_is_refused_with_the_nodes(self):
        snap = _tree(("append_node", {"text": "Survey"}))
        with pytest.raises(ap.PlanError) as refused:
            ap.apply(snap, "append_child", parent_id="3", text="x")
        text = str(refused.value)
        assert "no node has the id '3'" in text
        assert f"root {snap.root_id} (What happened to the shipment in March?)" in text
        assert f"1 {_ids(snap)['Survey']} (Survey)" in text

    def test_the_tree_shows_the_path_of_each_node(self):
        snap = _tree(("append_node", {"text": "A"}),
                     ("append_child", {"parent_id": "1", "text": "A1"}))
        ids = _ids(snap)
        assert ap.render_tree(snap).splitlines() == [
            f"root. What happened to the shipment in March? [{snap.root_id}]",
            f"  1. A [{ids['A']}]",
            f"    1.1. A1 [{ids['A1']}]",
        ]

    def test_a_node_id_is_never_read_as_a_path(self):
        # Only the parent argument takes a path. Other node arguments need the id.
        snap = _tree(("append_node", {"text": "A"}))
        with pytest.raises(ap.PlanError, match="no node has the id"):
            ap.apply(snap, "remove_node", node_id="1")


class TestPlanBound:
    def test_the_150th_node_is_accepted_and_the_151st_is_refused(self):
        snap = ap.initial_snapshot(PLAN, "q")
        for i in range(149):
            snap = ap.apply(snap, "append_node", text=f"node {i}")
        assert len(snap.nodes) == 150
        with pytest.raises(ap.PlanError, match="151 nodes and the limit is 150"):
            ap.apply(snap, "append_node", text="one more")

    @pytest.mark.parametrize("text, rule", [
        ("", "empty"), ("two\nlines", "one line"), ("x" * 121, "121 characters"),
    ])
    def test_the_text_rules(self, text, rule):
        with pytest.raises(ap.PlanError, match=rule):
            _tree(("append_node", {"text": text}))

    def test_120_characters_are_accepted(self):
        assert _tree(("append_node", {"text": "x" * 120})).version == 2


class TestRootImmutable:
    def test_the_root_cannot_move_or_go(self):
        snap = _tree(("append_node", {"text": "A"}))
        with pytest.raises(ap.PlanError, match="cannot be moved"):
            ap.apply(snap, "move_node", node_id=snap.root_id, new_parent_id=_ids(snap)["A"])
        with pytest.raises(ap.PlanError, match="cannot be removed"):
            ap.apply(snap, "remove_node", node_id=snap.root_id)

    def test_the_root_text_can_change_and_its_id_stays(self):
        snap = ap.apply(_tree(), "edit_node", node_id=ap.root_node_id(PLAN), text="New root")
        root = next(n for n in snap.nodes if n.parent_id is None)
        assert (root.node_id, root.text) == (ap.root_node_id(PLAN), "New root")


class TestSections:
    def test_a_flat_plan_is_one_section_the_roots(self):
        snap = _tree(("append_node", {"text": "A"}), ("append_node", {"text": "B"}))
        assert [(n.node_id, [t.text for t in tasks]) for n, tasks in ap.sections(snap)] == [
            (snap.root_id, ["A", "B"])]

    def test_a_nested_plan_has_a_section_for_each_node_with_a_leaf_child(self):
        snap = _tree(("append_node", {"text": "A"}), ("append_node", {"text": "B"}))
        ids = _ids(snap)
        snap = ap.apply(snap, "append_child", parent_id=ids["A"], text="A1")
        snap = ap.apply(snap, "append_child", parent_id=ids["B"], text="B1")
        assert [n.text for n, _ in ap.sections(snap)] == ["A", "B"]


class TestVerdictsAndSectionStates:
    def test_a_verdict_block_is_read_and_a_missing_one_is_no_verdict(self):
        report = 'Fine.\n```json\n{"verdict": "accept", "defect_classes": []}\n```'
        assert ap.parse_verdict(report) == ("accept", [])
        assert ap.parse_verdict("no block") == ("reject", ["no-verdict"])

    def test_a_section_fails_when_its_newest_work_did_not_complete_or_wrote_no_report(self):
        snap = _tree(("append_node", {"text": "A"}))
        root = snap.root_id
        t0 = datetime(2026, 1, 1)
        report = ap.PlanDocument(ap.document_id("r1", "report"), root, "executor", "report",
                                 0, "The report.", t0)
        done = [ap.SectionRun(root, "execute", "completed", t0, run_id="r1", report_node=root)]
        [entry] = ap.section_states(snap, done, [report])
        assert (entry["failed"], entry["state"], entry["review"], entry["defect_classes"]) == (
            False, "completed", "", [])
        [no_run] = ap.section_states(snap, [], [report])
        [ended] = ap.section_states(
            snap, [ap.SectionRun(root, "execute", "failed", t0, run_id="r1",
                                 report_node=root)], [report])
        [unreported] = ap.section_states(snap, done, [])
        assert [e["failed"] for e in (no_run, ended, unreported)] == [True] * 3
        table = ap.failed_sections_table([no_run, ended, unreported])
        assert table.splitlines()[0] == "## Failed sections"
        assert ("| section | cause |" in table and "no run" in table
                and "the run ended `failed`" in table and "no report" in table)
        assert ap.failed_sections_table([entry]) == ""


def _two_sections():
    snap = _tree(("append_node", {"text": "A"}), ("append_node", {"text": "B"}))
    ids = _ids(snap)
    snap = ap.apply(snap, "append_child", parent_id=ids["A"], text="A1")
    snap = ap.apply(snap, "append_child", parent_id=ids["B"], text="B1")
    return snap, ids["A"], ids["B"]


class TestOneCorrectionOfTwoSections:
    """A correction run C names A and B. Its one report is under A, and counts for both."""

    T0 = datetime(2026, 1, 1)

    def _runs(self, c_state):
        snap, a, b = _two_sections()
        t0 = self.T0
        runs = [ap.SectionRun(a, "execute", "completed", t0, run_id="ra", report_node=a),
                ap.SectionRun(b, "execute", "completed", t0, run_id="rb", report_node=b)]
        runs += [ap.SectionRun(node, "correct", c_state, t0 + timedelta(minutes=5),
                               run_id="rc", report_node=a) for node in (a, b)]
        docs = [ap.PlanDocument(ap.document_id(r, "report"), n, "executor", "report", 0,
                                "text", t0) for r, n in (("ra", a), ("rb", b))]
        return snap, runs, docs, a

    def test_the_report_under_the_first_section_counts_for_both(self):
        snap, runs, docs, a = self._runs("completed")
        docs.append(ap.PlanDocument(ap.document_id("rc", "report"), a, "executor", "report",
                                    1, "fixed", self.T0 + timedelta(minutes=9)))
        entries = ap.section_states(snap, runs, docs)
        assert [(e["failed"], e["corrections"]) for e in entries] == [(False, 1), (False, 1)]

    def test_a_failed_correction_fails_both_sections(self):
        snap, runs, docs, _ = self._runs("failed")
        entries = ap.section_states(snap, runs, docs)
        assert [e["failed"] for e in entries] == [True, True]
        assert ap.failed_sections_table(entries).count("the run ended `failed`") == 2

    def test_a_completed_correction_with_no_report_fails_both_sections(self):
        snap, runs, docs, _ = self._runs("completed")
        entries = ap.section_states(snap, runs, docs)
        assert [e["failed"] for e in entries] == [True, True]
        assert ap.failed_sections_table(entries).count("no report") == 2


class TestSectionCap:
    def _four(self):
        snap = _tree(*[("append_node", {"text": t}) for t in "ABCD"])
        ids = _ids(snap)
        for t in "ABCD":
            snap = ap.apply(snap, "append_child", parent_id=ids[t], text=t + "1")
        assert len(ap.sections(snap)) == 4
        return snap, ids

    def test_a_leaf_under_the_root_of_four_sections_is_refused(self):
        snap, _ = self._four()
        with pytest.raises(ap.PlanError, match="makes 5 sections, and a plan has at most 4"):
            ap.apply(snap, "append_node", text="E")

    def test_a_task_under_a_section_is_accepted(self):
        snap, ids = self._four()
        assert len(ap.sections(ap.apply(snap, "append_child", parent_id=ids["A"],
                                        text="A2"))) == 4

    def test_a_fifth_section_by_a_move_is_refused(self):
        snap, ids = self._four()
        snap = ap.apply(snap, "append_child", parent_id=ids["A"], text="A2")
        with pytest.raises(ap.PlanError, match="at most 4"):
            ap.apply(snap, "move_node", node_id=_ids(snap)["A2"], new_parent_id=snap.root_id,
                     position=1)

    def test_a_tree_of_five_sections_from_before_accepts_a_removal(self):
        snap, ids = self._four()
        extra = ap.PlanNode("e-node", snap.root_id, 5, "E")
        leaf = ap.PlanNode("e1-node", "e-node", 1, "E1")
        five = ap.PlanSnapshot(snap.plan_id, snap.version, snap.nodes + (extra, leaf))
        assert len(ap.sections(five)) == 5
        assert len(ap.sections(ap.apply(five, "remove_node", node_id="e-node"))) == 4
        assert len(ap.sections(ap.apply(five, "edit_node", node_id="e-node", text="F"))) == 5
