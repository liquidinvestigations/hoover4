"""The section rule of `database.agent_plans.sections`, on the four trees of the Rust copy.

The Rust copy is `has_section` in `website/common/src/plan_types.rs`. Its tests use the same
four trees and expect the same answers. The two copies are one rule and change in one patch.
"""

import pytest

from database import agent_plans as ap

PLAN = "5a0f2c1e-7d3b-4e8a-9b61-2f4d8c0e7a13"


def _snapshot(*edges):
    """A snapshot of `(node_id, parent_id)` pairs, with ordinals in the order given."""
    nodes = tuple(ap.PlanNode(node_id=node_id, parent_id=parent_id, ordinal=i, text=node_id)
                  for i, (node_id, parent_id) in enumerate(edges, start=1))
    return ap.PlanSnapshot(plan_id=PLAN, version=1, nodes=nodes)


@pytest.mark.parametrize("edges, has_section", [
    ((), False),
    ((("root", None),), False),
    ((("root", None), ("s1", "root"), ("s2", "root")), True),
    ((("root", None), ("s1", "root"), ("t1", "s1"), ("t2", "s1")), True),
], ids=["no-node", "root-only", "root-with-two-leaf-children", "root-with-one-section"])
def test_the_section_rule_matches_the_rust_copy(edges, has_section):
    assert bool(ap.sections(_snapshot(*edges))) is has_section
