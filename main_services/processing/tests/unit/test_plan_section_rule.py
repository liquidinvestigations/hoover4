"""The section rule of `database.agent_plans.sections`, on the trees of the Rust copy.

The Rust copy is `section_count` in `website/common/src/plan_types.rs`. Its tests use the
same trees and expect the same answers. The two copies are one rule and change in one patch.
"""

import pytest

from database import agent_plans as ap

PLAN = "5a0f2c1e-7d3b-4e8a-9b61-2f4d8c0e7a13"


def _snapshot(*edges):
    """A snapshot of `(node_id, parent_id)` pairs, with ordinals in the order given."""
    root = ap.root_node_id(PLAN)
    nodes = tuple(ap.PlanNode(node_id=root if node_id == "root" else node_id,
                              parent_id=root if parent_id == "root" else parent_id,
                              ordinal=i, text=node_id)
                  for i, (node_id, parent_id) in enumerate(edges, start=1))
    return ap.PlanSnapshot(plan_id=PLAN, version=1, nodes=nodes)


@pytest.mark.parametrize("edges, count", [
    ((("root", None),), 0),
    ((("root", None), ("s1", "root"), ("s2", "root")), 2),
    ((("root", None), ("s1", "root"), ("t1", "s1"), ("t2", "s1")), 1),
    ((("root", None), ("s1", "root"), ("s2", "root"), ("t1", "s2"), ("t2", "t1")), 2),
], ids=["root-only", "two-leaf-children", "one-section-of-two-tasks", "nested-subtree"])
def test_the_section_rule_matches_the_rust_copy(edges, count):
    assert len(ap.sections(_snapshot(*edges))) == count
