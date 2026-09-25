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

    def test_a_section_fails_without_an_accepting_review_after_its_newest_work(self):
        snap = _tree(("append_node", {"text": "A"}))
        root = snap.root_id
        t0 = datetime(2026, 1, 1)
        runs = [ap.SectionRun(root, "execute", "completed", t0),
                ap.SectionRun(root, "review", "completed", t0 + timedelta(minutes=1)),
                ap.SectionRun(root, "correct", "completed", t0 + timedelta(minutes=2))]
        accept = '```json\n{"verdict": "accept", "defect_classes": []}\n```'
        reject = '```json\n{"verdict": "reject", "defect_classes": ["missing-source"]}\n```'
        early = ap.PlanDocument("d1", root, "reviewer", "review", 0, reject,
                                t0 + timedelta(minutes=1))
        [entry] = ap.section_states(snap, runs, [early])
        assert (entry["failed"], entry["corrections"], entry["review"],
                entry["defect_classes"]) == (True, 1, "reject", ["missing-source"])
        [unreviewed] = ap.section_states(snap, runs, [])
        assert (unreviewed["failed"], unreviewed["review"]) == (True, "")
        late = ap.PlanDocument("d2", root, "reviewer", "review", 0, accept,
                               t0 + timedelta(minutes=3))
        [entry] = ap.section_states(snap, runs, [early, late])
        assert (entry["failed"], entry["review"], entry["defect_classes"]) == (
            False, "accept", [])
        assert ap.failed_sections_table([entry]) == ""
        table = ap.failed_sections_table([{"title": "A", "failed": True,
                                           "defect_classes": ["no-verdict"]}])
        assert table.splitlines()[0] == "## Failed sections" and "| A | no-verdict |" in table
