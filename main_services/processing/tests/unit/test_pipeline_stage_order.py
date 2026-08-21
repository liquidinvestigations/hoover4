"""Static regression guard: stage order inside ExecuteSinglePlan and ExecutePlans.

P4 (entities) and P5 (chunk+embed) must both complete before P6 (indexing): P6 reads
the entity_hit rows and copies text_chunk_vectors into the shard's HNSW table, so an
index that runs first comes up with no entities and empty `_vectors` tables. P4 and P5
themselves are independent -- disjoint tables, different worker queues -- and run
together. The same AST walk pins the dataset-scoped VFS activities on ExecutePlans
(once per batch) and asserts IndexDatasetPlan no longer drives them.
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
                    found = []
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
                            found.append((child.lineno, child.args[0].value.id))
                    # ast.walk is breadth-first, so a call nested inside another (a
                    # gathered pair, say) comes back out of order. Line number is what
                    # "source order" means here.
                    return [name for _lineno, name in sorted(found)]
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


def test_chunk_embed_runs_before_indexing():
    # P6's vector indexer copies the text_chunk_vectors rows P5 writes; an index that
    # runs before embedding comes up with empty _vectors tables.
    order = _child_workflow_order()
    assert "ChunkEmbedForPlan" in order, (
        f"ChunkEmbedForPlan is not executed by ExecuteSinglePlan: {order}"
    )
    assert order.index("ChunkEmbedForPlan") < order.index("IndexDatasetPlan"), (
        f"ChunkEmbedForPlan must run strictly before IndexDatasetPlan: {order}"
    )


def test_entities_and_chunk_embed_are_gathered():
    """They read the same text_content and write disjoint tables, so they run together.

    Running them in sequence left one worker tier idle for the whole of the other's
    stage. This pins the pair inside one gather so a later edit cannot quietly
    re-serialise them.
    """
    source = open(p2_workflows.__file__).read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "gather"):
            continue
        started = {
            arg.args[0].value.id
            for arg in node.args
            if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute)
            and arg.func.attr == "execute_child_workflow" and arg.args
            and isinstance(arg.args[0], ast.Attribute)
            and isinstance(arg.args[0].value, ast.Name)
        }
        if {"ExtractEntitiesForPlan", "ChunkEmbedForPlan"} <= started:
            return
    raise AssertionError(
        "ExtractEntitiesForPlan and ChunkEmbedForPlan are no longer started together")


def test_sanity_order_is_nonempty():
    assert _child_workflow_order()


def _stage_order() -> list[str]:
    """Every stage ExecuteSinglePlan.run drives, in SOURCE order.

    Both kinds: ``execute_child_workflow(<Class>.run, …)`` contributes the class name,
    ``execute_activity(<fn>, …)`` contributes the function name. Sorted by line number
    rather than taken from ``ast.walk``, which is breadth-first and would put a stage
    nested inside an ``if`` after one that follows it in the file.
    """
    source = open(p2_workflows.__file__).read()
    tree = ast.parse(source)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "ExecuteSinglePlan"):
            continue
        for child in ast.walk(node):
            if not (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)):
                continue
            if not child.args:
                continue
            target = child.args[0]
            if child.func.attr == "execute_child_workflow":
                if isinstance(target, ast.Attribute) and target.attr == "run" \
                        and isinstance(target.value, ast.Name):
                    found.append((child.lineno, target.value.id))
            elif child.func.attr == "execute_activity":
                if isinstance(target, ast.Name):
                    found.append((child.lineno, target.id))
    return [name for _, name in sorted(found)]


def test_date_resolution_runs_after_parsing_and_before_indexing():
    """P6 builds the `dates` search attribute from `document_dates`.

    Resolve too early and there is no tika_metadata to read; resolve too late and the
    document is indexed undated and stays that way until something re-indexes it —
    which nothing does on its own. Both failures are silent, hence the pin.
    """
    order = _stage_order()
    assert "resolve_document_dates" in order, (
        f"resolve_document_dates is not driven by ExecuteSinglePlan: {order}"
    )
    assert order.index("ProcessItemsBatched") < order.index("resolve_document_dates") \
        < order.index("IndexDatasetPlan"), (
        f"date resolution must sit between parsing and indexing: {order}"
    )


def _execute_targets(source: str, class_name: str) -> list[tuple[int, str]]:
    """``execute_activity`` / ``execute_child_workflow`` targets in ``Class.run``,
    in source order (line number, name)."""
    tree = ast.parse(source)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue
        for child in ast.walk(node):
            if not (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)):
                continue
            if not child.args:
                continue
            target = child.args[0]
            if child.func.attr == "execute_child_workflow":
                if isinstance(target, ast.Attribute) and target.attr == "run" \
                        and isinstance(target.value, ast.Name):
                    found.append((child.lineno, target.value.id))
            elif child.func.attr == "execute_activity":
                if isinstance(target, ast.Name):
                    found.append((child.lineno, target.id))
    return sorted(found)


def test_index_dataset_plan_does_not_rebuild_the_dataset_tree():
    """build_vfs_nodes / resolve_canonical_file_type / index_vfs_structure are
    dataset-scoped. Driving them per plan is O(nodes x plans)."""
    import tasks.P6_index_data.workflows as p6_workflows
    names = [name for _, name in _execute_targets(
        open(p6_workflows.__file__).read(), "IndexDatasetPlan"
    )]
    for forbidden in ("build_vfs_nodes", "resolve_canonical_file_type", "index_vfs_structure"):
        assert forbidden not in names, (
            f"IndexDatasetPlan must not execute {forbidden}: {names}"
        )


def test_execute_plans_rebuilds_the_tree_once_per_batch():
    """ClickHouse vfs before the per-plan children; the rebuild, the canonical-type
    sweep and the Manticore copy after them, and BEFORE the continuation and restart
    returns so every invocation indexes the tree it just produced."""
    source = open(p2_workflows.__file__).read()
    ordered = [name for _, name in _execute_targets(source, "ExecutePlans")]
    for required in ("build_vfs_nodes", "resolve_canonical_file_type",
                     "ExecuteSinglePlan", "index_vfs_structure"):
        assert required in ordered, (
            f"{required} is not executed by ExecutePlans: {ordered}"
        )
    assert ordered.index("build_vfs_nodes") \
        < ordered.index("ExecuteSinglePlan") \
        < ordered.index("resolve_canonical_file_type") \
        < ordered.index("index_vfs_structure"), (
        f"tree rebuild must wrap the per-plan children: {ordered}"
    )
    # The pre-loop rebuild cannot see structure this batch's own P3 produced, so
    # the tree is rebuilt again between the children and the Manticore copy.
    assert ordered.count("build_vfs_nodes") == 2, (
        f"build_vfs_nodes must run before and after the per-plan children: {ordered}"
    )
    assert ordered.index("ExecuteSinglePlan") \
        < len(ordered) - 1 - ordered[::-1].index("build_vfs_nodes") \
        < ordered.index("index_vfs_structure"), (
        f"the second build_vfs_nodes must sit between the children and the copy: {ordered}"
    )


def test_canonical_file_type_runs_inside_the_plan_that_produced_the_evidence():
    """`file_types` is written by P3, inside the per-plan children. A canonical pass
    that runs only outside them reads an empty table on a first ingest and writes
    nothing, and every document is then indexed with no file type, no MIME and no
    extensions at all — which is what an empty File types facet looks like."""
    source = open(p2_workflows.__file__).read()
    single = [name for _, name in _execute_targets(source, "ExecuteSinglePlan")]
    assert "resolve_canonical_file_type" in single, (
        f"ExecuteSinglePlan must resolve its own plan's canonical types: {single}"
    )
    assert single.index("resolve_canonical_file_type") < single.index("IndexDatasetPlan"), (
        f"canonical types must be resolved before the plan is indexed: {single}"
    )
    # ExecutePlans hands off to a continuation or a restart child instead of
    # returning normally. Indexing the tree after that hand-off means only whichever
    # invocation happens to be terminal ever copies it, so a child that raises -- or
    # one that finds no plans left -- leaves the browser on the previous ingest.
    index_line = next(
        line for line, name in _execute_targets(source, "ExecutePlans")
        if name == "index_vfs_structure"
    )
    handoff_line = next(
        n for n, text in enumerate(source.splitlines(), start=1)
        if text.strip() == "if continuation_hash:"
    )
    assert index_line < handoff_line, (
        f"index_vfs_structure (line {index_line}) must precede the continuation "
        f"hand-off (line {handoff_line})"
    )
