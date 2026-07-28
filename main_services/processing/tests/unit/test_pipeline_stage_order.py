"""Static regression guard: inside ExecuteSinglePlan, ExtractEntitiesForPlan
must be awaited strictly before IndexDatasetPlan.

This is the exact tangle plan part 5 untangles (NER used to run *inside* the
indexing activity), so the stage order is pinned by an AST assertion over
tasks/P2_execute_plan/workflows.py rather than by convention.
"""

import ast

import tasks.P2_execute_plan.workflows as p2_workflows


def _child_workflow_order() -> list[str]:
    """Class names passed as ``<Class>.run`` to execute_child_workflow inside
    ExecuteSinglePlan.run, in source order."""
    source = open(p2_workflows.__file__).read()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ExecuteSinglePlan":
            for fn in node.body:
                if isinstance(fn, ast.AsyncFunctionDef) and fn.name == "run":
                    order = []
                    for child in ast.walk(fn):
                        if (
                            isinstance(child, ast.Call)
                            and isinstance(child.func, ast.Attribute)
                            and child.func.attr == "execute_child_workflow"
                            and child.args
                            and isinstance(child.args[0], ast.Attribute)
                            and child.args[0].attr == "run"
                            and isinstance(child.args[0].value, ast.Name)
                        ):
                            order.append(child.args[0].value.id)
                    return order
    raise AssertionError("ExecuteSinglePlan.run not found in P2_execute_plan/workflows.py")


def test_extract_entities_runs_before_indexing():
    order = _child_workflow_order()
    assert "ExtractEntitiesForPlan" in order, (
        f"ExtractEntitiesForPlan is not executed by ExecuteSinglePlan: {order}"
    )
    assert "IndexDatasetPlan" in order, (
        f"IndexDatasetPlan is not executed by ExecuteSinglePlan: {order}"
    )
    assert order.index("ExtractEntitiesForPlan") < order.index("IndexDatasetPlan"), (
        f"ExtractEntitiesForPlan must run strictly before IndexDatasetPlan: {order}"
    )


def test_sanity_order_is_nonempty():
    assert _child_workflow_order()
