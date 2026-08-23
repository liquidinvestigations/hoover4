"""Every term field must be scoped to a dataset, or explicitly declared global.

A term id is `blake2b(term_value)` truncated to 63 bits, and `string_term_text_to_id` is
keyed by `(collection_dataset, term_field, term_value)`, but the ID itself is derived
from the VALUE alone. So two datasets that mint a term from the same string get the same
integer, and a Manticore filter on that integer matches BOTH datasets' documents.

For `filetype` that is correct and wanted: `pdf` means the same thing everywhere, and
sharing the id is what makes one facet list work across collections. For anything
positional (a path, a folder), the result is a silent cross-dataset leak: filtering on one
dataset's `/data` folder also returns the other's.

The rule this module enforces: a term field is either on the GLOBAL allowlist, with a
recorded reason, or its VALUES embed `collection_dataset`.
"""

import ast
import pathlib

from tasks.P6_index_data.vfs_nodes import UNIT_SEP, dataset_root_key, make_node_key

#: Term fields whose values are legitimately global. The same string means the same
#: thing in every dataset, and sharing the id is the point.
GLOBAL_TERM_FIELDS = {
    "filetype",      # "pdf", "document", a type is a type.
    "mime_type",     # "application/pdf".
    "extension",     # "pdf".
    "ner",           # a person's name is the same person across datasets.
    "email_address", # an address is the same mailbox everywhere; merging is wanted.
}

#: Term fields whose values MUST embed the dataset. `vfs_node` is the only one left:
#: `parent_paths` was retired precisely because it did not.
SCOPED_TERM_FIELDS = {"vfs_node"}

#: Retired. Present here so reintroducing it fails a test rather than a corpus.
FORBIDDEN_TERM_FIELDS = {"parent_paths"}

PROCESSING_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _term_fields_used_in_source() -> set[str]:
    """Every literal term-field name passed to `get_string_term_ids`.

    An AST walk rather than a grep: the third positional argument is the field name, and
    only a literal can be checked here. A computed one would need a runtime test and is
    itself a smell worth failing on.
    """
    found: set[str] = set()
    for path in PROCESSING_ROOT.rglob("*.py"):
        if ".venv" in path.parts or "tests" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - not our file to fix
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "get_string_term_ids":
                continue
            if len(node.args) >= 3 and isinstance(node.args[2], ast.Constant):
                found.add(node.args[2].value)
    return found


def test_every_term_field_in_use_is_classified():
    used = _term_fields_used_in_source()
    assert used, "no get_string_term_ids call sites found — did the API change?"
    unclassified = used - GLOBAL_TERM_FIELDS - SCOPED_TERM_FIELDS
    assert not unclassified, (
        f"term field(s) {sorted(unclassified)} are neither on the global allowlist nor "
        f"declared dataset-scoped. Decide which, and say why in this module."
    )


def test_the_retired_term_field_stays_retired():
    """`parent_paths` hashed a bare path, so one id matched every dataset's `/data` and
    every archive's. It is replaced by `vfs_node`, not to be revived."""
    used = _term_fields_used_in_source()
    assert not (used & FORBIDDEN_TERM_FIELDS), (
        f"{sorted(used & FORBIDDEN_TERM_FIELDS)} is back; it is unsafe by construction"
    )


def test_the_allowlist_and_the_scoped_set_are_disjoint():
    assert not (GLOBAL_TERM_FIELDS & SCOPED_TERM_FIELDS)


def test_vfs_node_values_embed_the_dataset():
    """The actual property, not just the classification: two datasets must produce two
    different strings for the same path, so they hash to two different ids."""
    a = make_node_key("testdata_testfiles", "", "/data")
    b = make_node_key("other_emails", "", "/data")
    assert a != b
    assert a.startswith(f"testdata_testfiles{UNIT_SEP}")
    assert dataset_root_key("testdata_testfiles").startswith("testdata_testfiles")


def test_vfs_node_values_embed_the_container():
    """Within one dataset, `/data` on disk and `/data` inside an archive are different
    folders and must not share an id."""
    on_disk = make_node_key("testdata_testfiles", "", "/data")
    in_archive = make_node_key("testdata_testfiles", "ziphash", "/data")
    assert on_disk != in_archive
