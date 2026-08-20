"""A plan must offer each item hash exactly once.

`ProcessItemsBatched` turns every item into a child workflow keyed by the item hash and
now runs several sibling drivers at once, so a hash appearing twice is two concurrent
starts of one workflow id -- `WorkflowAlreadyStartedError`, and that file never parses.
Two things keep it from happening and both are pinned here: the query does not produce
duplicates, and the workflow drops them anyway.
"""

import ast
import re
from pathlib import Path

import tasks.P2_execute_plan.activities as p2_activities
import tasks.P2_execute_plan.workflows as p2_workflows


def _plan_items_sql() -> str:
    source = Path(p2_activities.__file__).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_plan_items_metadata":
            for sub in ast.walk(node):
                if isinstance(sub, ast.JoinedStr):
                    text = "".join(
                        part.value for part in sub.values if isinstance(part, ast.Constant)
                    )
                    if "processing_plan_hits" in text:
                        return text
    raise AssertionError("the plan-items query is no longer an f-string in that function")


def test_the_plan_items_query_collapses_duplicate_hashes():
    sql = _plan_items_sql()
    assert "LEFT JOIN blobs" in sql, f"query no longer joins blobs: {sql}"
    # `blobs` is a ReplacingMergeTree and this join does not read it FINAL, so without
    # one of these a hash with unmerged rows comes back more than once.
    collapses = re.search(r"LIMIT\s+1\s+BY\s+h\.item_hash", sql) or "FINAL" in sql
    assert collapses, (
        "the join can return a hash twice; keep LIMIT 1 BY h.item_hash (or read blobs "
        f"FINAL):\n{sql}"
    )


def test_execute_single_plan_drops_duplicate_item_hashes():
    source = Path(p2_workflows.__file__).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "ExecuteSinglePlan"):
            continue
        body = ast.get_source_segment(source, node) or ""
        assert "unique_items" in body, (
            "ExecuteSinglePlan no longer deduplicates items before grouping them"
        )
        assert "item_groups" in body and "unique_items[i:i + PLAN_GROUP_SIZE]" in body, (
            "the groups are no longer built from the deduplicated list"
        )
        return
    raise AssertionError("ExecuteSinglePlan not found")
