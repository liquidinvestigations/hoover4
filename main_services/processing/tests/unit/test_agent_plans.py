"""The plan tree rules of `database.agent_plans`, with no database.

Cases: `plan-tree` (a whole-tree write keeps a valid tree, keeps named identities and gives a
retry the same ids), `plan-bound` (the 150-node bound, the four-section bound and the text
rules), `root-immutable` (the root keeps its id and text), the section rule (each direct
child of the root is a section with its whole subtree), and the section outcome rule.
"""

import pytest

from database import agent_plans as ap

PLAN = "0b8e6f8a-3f52-4a55-9d6c-6f6a1c1f2e10"
KEY = "5f1e7c2a-6b1d-4d77-9a0e-1c2b3d4e5f60"


def _node(text, *children, node_id=""):
    out = {"text": text, "children": list(children)}
    if node_id:
        out["node_id"] = node_id
    return out


def _tree(*children, key=KEY, base=None):
    base = base or ap.initial_snapshot(PLAN, "What happened to the shipment in March?")
    return ap.build_tree(base, list(children), key)


def _ids(snap):
    return {n.text: n.node_id for n in snap.nodes}


class TestPlanTree:
    def test_version_one_holds_the_root_with_the_first_line_of_the_query(self):
        snap = ap.initial_snapshot(PLAN, "  Line one\nline two  ")
        assert snap.version == 1
        assert [(n.node_id, n.parent_id, n.ordinal, n.text) for n in snap.nodes] == [
            (ap.root_node_id(PLAN), None, 1, "Line one line two")]

    def test_nested_input_gives_the_parents_and_the_ordinals(self):
        snap = _tree(_node("A", _node("A1"), _node("A2", _node("A2a"))), _node("B"))
        assert snap.version == 2
        ids = _ids(snap)
        parents = {n.text: n.parent_id for n in snap.nodes}
        ordinals = {n.text: n.ordinal for n in snap.nodes}
        assert parents == {snap.nodes[0].text: None, "A": snap.root_id, "B": snap.root_id,
                           "A1": ids["A"], "A2": ids["A"], "A2a": ids["A2"]}
        assert (ordinals["A"], ordinals["B"], ordinals["A1"], ordinals["A2"]) == (1, 2, 1, 2)
        assert ap.render_tree(snap).splitlines()[1:] == [
            "  1. A", "    1.1. A1", "    1.2. A2", "      1.2.1. A2a", "  2. B"]
        assert ap.render_tree(snap, ids["A2"]).splitlines() == [
            "    1.2. A2", "      1.2.1. A2a"]

    def test_a_retry_with_the_same_key_gives_the_same_ids(self):
        first = _tree(_node("A", _node("A1")))
        again = _tree(_node("A", _node("A1")))
        other = _tree(_node("A", _node("A1")), key="other-key")
        assert first.nodes == again.nodes and first.checksum == again.checksum
        assert _ids(first)["A"] != _ids(other)["A"]

    def test_a_named_node_keeps_its_identity_by_id_or_path_and_a_left_out_node_goes(self):
        snap = _tree(_node("A", _node("A1")), _node("B"))
        ids = _ids(snap)
        moved = _tree(_node("B renamed", _node("A1 moved", node_id="1.1"), node_id=ids["B"]),
                      _node("C"), base=snap, key="k2")
        new_ids = _ids(moved)
        assert new_ids["B renamed"] == ids["B"] and new_ids["A1 moved"] == ids["A1"]
        assert "A" not in new_ids and ids["A"] not in {n.node_id for n in moved.nodes}
        assert {n.text: n.parent_id for n in moved.nodes}["A1 moved"] == ids["B"]
        assert moved.version == 3

    def test_an_unknown_id_a_root_id_and_a_duplicate_id_are_refused(self):
        snap = _tree(_node("A"))
        with pytest.raises(ap.PlanError, match="names no node of version 2"):
            _tree(_node("x", node_id="nope"), base=snap)
        with pytest.raises(ap.PlanError, match="names no node"):
            _tree(_node("x", node_id="root"), base=snap)
        with pytest.raises(ap.PlanError, match="appears twice"):
            _tree(_node("x", node_id="1"), _node("y", node_id=_ids(snap)["A"]), base=snap)

    def test_a_malformed_input_is_refused(self):
        with pytest.raises(ap.PlanError, match="must be a list"):
            ap.build_tree(ap.initial_snapshot(PLAN, "q"), "A", KEY)
        with pytest.raises(ap.PlanError, match="object"):
            ap.build_tree(ap.initial_snapshot(PLAN, "q"), ["A"], KEY)

    def test_an_empty_tree_is_the_root_alone(self):
        snap = _tree()
        assert len(snap.nodes) == 1 and ap.sections(snap) == []

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
        snap = _tree(_node("A"), _node("B"))
        assert ap.nodes_from_json(ap.nodes_json(snap.nodes)) == tuple(
            sorted(snap.nodes, key=lambda n: (n.parent_id is not None, n.ordinal)))


class TestPlanBound:
    def test_the_150th_node_is_accepted_and_the_151st_is_refused(self):
        def tree(counts):
            return [_node(f"s{i}", *[_node(f"t{i}.{j}") for j in range(n)])
                    for i, n in enumerate(counts)]

        # The root, 4 sections and 145 tasks are 150 nodes.
        assert len(_tree(*tree([37, 36, 36, 36])).nodes) == 150
        with pytest.raises(ap.PlanError, match="more than 150 nodes"):
            _tree(*tree([37, 37, 36, 36]))

    def test_a_fifth_section_is_refused(self):
        assert len(ap.sections(_tree(*[_node(t) for t in "ABCD"]))) == 4
        with pytest.raises(ap.PlanError, match="5 top-level nodes, and a plan has at most 4"):
            _tree(*[_node(t) for t in "ABCDE"])

    @pytest.mark.parametrize("text, rule", [
        ("", "empty"), ("two\nlines", "one line"), ("x" * 121, "121 characters"),
    ])
    def test_the_text_rules(self, text, rule):
        with pytest.raises(ap.PlanError, match=rule):
            _tree(_node(text))

    def test_120_characters_are_accepted(self):
        assert _tree(_node("x" * 120)).version == 2


class TestRootImmutable:
    def test_the_root_keeps_its_id_and_text(self):
        snap = _tree(_node("A"))
        root = next(n for n in snap.nodes if n.parent_id is None)
        assert (root.node_id, root.text) == (
            ap.root_node_id(PLAN), "What happened to the shipment in March?")


class TestSections:
    def test_each_child_of_the_root_is_a_section_with_the_leaves_of_its_subtree(self):
        snap = _tree(_node("A", _node("A1"), _node("A2", _node("A2a"))), _node("B"))
        assert [(n.text, [t.text for t in tasks]) for n, tasks in ap.sections(snap)] == [
            ("A", ["A1", "A2a"]), ("B", ["B"])]


class TestSectionOutcomes:
    def _snap(self):
        return _tree(_node("A", _node("A1")), _node("B"))

    def test_a_completed_run_with_a_complete_report_does_not_fail(self):
        snap = self._snap()
        a, b = (n.node_id for n, _ in ap.sections(snap))
        runs = [ap.SectionRun(a, "completed", run_id="ra", report="typed"),
                ap.SectionRun(b, "completed", run_id="rb", report="text")]
        entries = ap.section_states(snap, runs)
        assert [(e["title"], e["tasks"], e["failed"], e["cause"]) for e in entries] == [
            ("A", 1, False, ""), ("B", 1, False, "")]
        assert all(e["corrections"] == 0 and e["defect_classes"] == [] for e in entries)
        assert ap.failed_sections_table(entries) == ""

    def test_each_cause_of_a_failed_section(self):
        snap = self._snap()
        a, _ = (n.node_id for n, _ in ap.sections(snap))
        cases = [
            (None, "no run"),
            (ap.SectionRun(a, "failed", error="model down", report="typed"),
             "the run ended failed: model down"),
            (ap.SectionRun(a, "cancelled", report="typed"), "the run ended cancelled"),
            (ap.SectionRun(a, "completed", end_reason="step_budget", report="typed"),
             "the run stopped before an answer (step_budget)"),
            (ap.SectionRun(a, "completed"), "no report"),
            (ap.SectionRun(a, "completed", report="typed", incomplete=True),
             "the report states incomplete execution"),
        ]
        for run, cause in cases:
            [entry, _] = ap.section_states(snap, [run] if run else [])
            assert (entry["failed"], entry["cause"]) == (True, cause)
            assert cause in ap.failed_sections_table([entry])

    def test_an_older_entry_derives_its_cause_from_its_state(self):
        assert ap.failure_cause({"state": ""}) == "no run"
        assert ap.failure_cause({"state": "failed"}) == "the run ended `failed`"
        assert ap.failure_cause({"state": "completed"}) == "no report"


def test_a_verdict_block_is_read_and_a_missing_one_is_no_verdict():
    report = 'Fine.\n```json\n{"verdict": "accept", "defect_classes": []}\n```'
    assert ap.parse_verdict(report) == ("accept", [])
    assert ap.parse_verdict("no block") == ("reject", ["no-verdict"])
