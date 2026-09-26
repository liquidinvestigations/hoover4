"""The node read of `document_metadata`: only container nodes, the same closure.

Pure, no stack. `document_metadata` reads the dataset's `vfs_nodes` once for each chunk,
and `container_parents_from_nodes` keeps only nodes of kind `container`. A read of every
node gives the same closure and holds hundreds of megabytes on a large dataset, so the
query filters on `kind`. These tests pin the filter and the equality of the two closures.
"""

import ast
import inspect
import textwrap

import tasks.P6_index_data.activities as p6
from tasks.P6_index_data.vfs_nodes import (
    KIND_CONTAINER,
    KIND_DIR,
    KIND_FILE,
    KIND_TO_INT,
    container_parents_from_nodes,
    kind_from_wire,
)


def _vfs_nodes_queries() -> list[str]:
    target = p6.document_metadata
    while hasattr(target, "__wrapped__"):
        target = target.__wrapped__
    tree = ast.parse(textwrap.dedent(inspect.getsource(target)))
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and "FROM vfs_nodes" in node.value
    ]


def test_document_metadata_reads_only_container_nodes():
    queries = _vfs_nodes_queries()
    assert len(queries) == 1, f"expected one vfs_nodes query, found {len(queries)}"
    normalised = " ".join(queries[0].split())
    assert "kind = 'container'" in normalised, (
        f"the vfs_nodes read must keep only container nodes: {normalised}"
    )


def _row(container_hash, path, kind, file_hash=""):
    return {"container_hash": container_hash, "path": path, "kind": kind, "file_hash": file_hash}


def test_the_filtered_rows_give_the_same_closure():
    # One archive on disk, one archive inside it, and the same archive twice in two
    # folders, with the dir and file rows around them. `kind` arrives as a name or as an
    # ordinal, so the fixture holds both forms.
    rows = [
        _row("", "/", KIND_DIR),
        _row("", "/mail", KIND_DIR),
        _row("", "/mail/a.txt", KIND_FILE, "h_text"),
        _row("", "/mail/outer.zip", KIND_CONTAINER, "h_outer"),
        _row("", "/copy/outer.zip", KIND_TO_INT[KIND_CONTAINER], "h_outer"),
        _row("h_outer", "/", KIND_DIR),
        _row("h_outer", "/inner", KIND_TO_INT[KIND_DIR]),
        _row("h_outer", "/inner/inner.tar", KIND_CONTAINER, "h_inner"),
        _row("h_inner", "/doc.pdf", KIND_TO_INT[KIND_FILE], "h_doc"),
    ]
    filtered = [row for row in rows if kind_from_wire(row["kind"]) == KIND_CONTAINER]

    assert len(filtered) == 3
    closure = container_parents_from_nodes(rows)
    assert container_parents_from_nodes(filtered) == closure
    assert closure == {
        "h_outer": [("", "/mail/outer.zip"), ("", "/copy/outer.zip")],
        "h_inner": [("h_outer", "/inner/inner.tar")],
    }
