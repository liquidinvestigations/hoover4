"""The VFS ancestor closure: what a folder filter is allowed to find.

Pure — no stack. Every case here is one the testdata corpus actually contains, and none
of them is visible from the outside: a closure that misses a parent means a folder filter
quietly returns fewer documents, and a closure that loops means a worker that never
finishes one plan.
"""

import pytest

from tasks.P6_index_data.vfs_nodes import (
    KIND_CONTAINER,
    KIND_TO_INT,
    KIND_DIR,
    KIND_FILE,
    MAX_ANCESTOR_DEPTH,
    MAX_ANCESTOR_TERMS,
    UNIT_SEP,
    ancestor_node_keys,
    build_node_rows,
    container_parents_from_nodes,
    kind_from_wire,
    dataset_root_key,
    make_node_key,
    normalise_path,
    path_ancestors,
)

DS = "testdata_testfiles"
ROOT = dataset_root_key(DS)


def key(container_hash, path):
    return make_node_key(DS, container_hash, path)


# --- keys ---------------------------------------------------------------------------

def test_a_key_is_scoped_by_dataset_and_container():
    """The bug this whole scheme exists to fix: `/data` is the same string everywhere."""
    assert make_node_key("a", "", "/data") != make_node_key("b", "", "/data")
    assert make_node_key("a", "", "/data") != make_node_key("a", "zip1", "/data")
    assert key("", "/data") == f"{DS}{UNIT_SEP}{UNIT_SEP}/data"
    assert ROOT == f"{DS}{UNIT_SEP}{UNIT_SEP}/"


@pytest.mark.parametrize("raw,expected", [
    ("/a/b", "/a/b"),
    ("a/b", "/a/b"),
    ("/a/b/", "/a/b"),
    ("/", "/"),
    ("//", "/"),
    ("/a//b", "/a/b"),
    ("/a/./b", "/a/b"),
    ("/a/../b", "/b"),
])
def test_paths_are_normalised_to_one_spelling(raw, expected):
    """`/a//b` and `/a/b` must be ONE node, or the tree grows a phantom sibling."""
    assert normalise_path(raw) == expected


@pytest.mark.parametrize("bad", ["/a\x1fb", "/a\nb", "/a\x00b", "/a\x7fb"])
def test_paths_with_control_characters_are_refused(bad):
    """The unit separator inside a path would make the key ambiguous, and an ambiguous
    key silently merges two folders. Refusing is the only safe answer."""
    assert normalise_path(bad) is None
    assert make_node_key(DS, "", bad) is None


def test_path_ancestors_excludes_the_path_itself():
    assert path_ancestors("/a/b/c.txt") == ["/", "/a", "/a/b"]
    assert path_ancestors("/top.txt") == ["/"]
    assert path_ancestors("/") == []


# --- the closure --------------------------------------------------------------------

def test_a_top_level_file_reaches_its_folders_and_the_dataset_root():
    keys, truncated = ancestor_node_keys(DS, [("", "/a/b/c.txt")], {})
    assert keys == {key("", "/"), key("", "/a"), key("", "/a/b"), ROOT}
    assert not truncated


def test_the_dataset_root_is_always_present():
    """It is what the tree's dataset row filters on. A document without it is invisible
    in the tree even though it is in the index."""
    keys, _ = ancestor_node_keys(DS, [], {})
    assert keys == {ROOT}


def test_a_document_inside_an_archive_reaches_the_folder_holding_the_archive():
    # /data/a.zip on disk, doc.txt inside it.
    keys, truncated = ancestor_node_keys(
        DS,
        [("ziphash", "/doc.txt")],
        {"ziphash": [("", "/data/a.zip")]},
    )
    assert key("ziphash", "/") in keys, "its own container root"
    assert key("", "/data/a.zip") in keys, "the archive FILE is a node"
    assert key("", "/data") in keys, "the folder holding the archive"
    assert key("", "/") in keys
    assert not truncated


def test_nested_containers_chain_all_the_way_out():
    """`a.docx` inside `a.zip` inside `b.zip` inside `/data` — the design's own example."""
    keys, truncated = ancestor_node_keys(
        DS,
        [("azip", "/a.docx")],
        {"azip": [("bzip", "/a.zip")], "bzip": [("", "/data/b.zip")]},
    )
    assert key("", "/data") in keys
    assert key("bzip", "/a.zip") in keys
    assert key("", "/data/b.zip") in keys
    assert not truncated


def test_a_container_at_two_paths_contributes_both_ancestries():
    """`zip-in-multiple-locations`: ONE content hash, TWO locations.

    A single-parent model would pick one and make the other location's folder filter
    return nothing — the §4.4 regression this fixture exists to catch.
    """
    keys, _ = ancestor_node_keys(
        DS,
        [("parentzip", "/parent/child.txt")],
        {"parentzip": [("", "/location-1/parent.zip"), ("", "/location-2/parent.zip")]},
    )
    assert key("", "/location-1") in keys
    assert key("", "/location-2") in keys
    assert key("", "/location-1/parent.zip") in keys
    assert key("", "/location-2/parent.zip") in keys


def test_a_document_at_several_paths_reaches_every_one_of_them():
    keys, _ = ancestor_node_keys(DS, [("", "/x/dup.txt"), ("", "/y/dup.txt")], {})
    assert key("", "/x") in keys
    assert key("", "/y") in keys


def test_a_self_containing_email_terminates():
    """`eml-7-recursive` is an email that contains itself. Without the visited set this
    is an infinite loop inside an activity, which shows up as a plan that never
    finishes rather than as an error."""
    keys, truncated = ancestor_node_keys(
        DS,
        [("selfmail", "/attachment.txt")],
        {"selfmail": [("selfmail", "/self.eml")]},
    )
    assert ROOT in keys
    assert key("selfmail", "/") in keys
    # Terminated, which is the point. Whether the cap was reported does not matter as
    # much as the fact that this call returns at all.
    assert isinstance(truncated, bool)


def test_a_mutual_container_cycle_terminates():
    keys, _ = ancestor_node_keys(
        DS,
        [("a", "/doc.txt")],
        {"a": [("b", "/a.zip")], "b": [("a", "/b.zip")]},
    )
    assert ROOT in keys


def test_the_container_hop_cap_is_reported_as_truncation():
    # A chain longer than MAX_ANCESTOR_DEPTH, each link a distinct container.
    parents = {
        f"c{i}": [(f"c{i + 1}", f"/c{i}.zip")] for i in range(MAX_ANCESTOR_DEPTH + 10)
    }
    keys, truncated = ancestor_node_keys(DS, [("c0", "/doc.txt")], parents)
    assert truncated, "hitting the depth cap must be recorded, not silently swallowed"
    assert ROOT in keys


def test_the_term_cap_is_reported_as_truncation():
    deep_path = "/" + "/".join(f"d{i}" for i in range(MAX_ANCESTOR_TERMS + 50))
    keys, truncated = ancestor_node_keys(DS, [("", deep_path)], {})
    assert truncated
    assert len(keys) <= MAX_ANCESTOR_TERMS + 1  # +1 for the dataset root
    assert ROOT in keys, "the dataset root survives truncation"


# --- the node table -----------------------------------------------------------------

def nodes_by_key(nodes):
    return {n.node_key: n for n in nodes}


def test_build_node_rows_synthesises_the_dataset_root():
    nodes = nodes_by_key(build_node_rows(DS, [], [], set()))
    assert ROOT in nodes
    assert nodes[ROOT].kind == KIND_DIR
    assert nodes[ROOT].parent_key == ""
    assert nodes[ROOT].depth == 0


def test_build_node_rows_marks_containers_and_links_their_roots():
    nodes = nodes_by_key(build_node_rows(
        DS,
        dir_rows=[("", "/data")],
        file_rows=[("", "/data/a.zip", "ziphash", 500), ("ziphash", "/doc.txt", "dochash", 20)],
        container_hashes={"ziphash"},
    ))
    archive = nodes[key("", "/data/a.zip")]
    assert archive.kind == KIND_CONTAINER
    assert archive.file_hash == "ziphash"
    assert archive.file_size_bytes == 500
    # The root INSIDE the archive hangs off the archive file, crossing the boundary.
    inner_root = nodes[key("ziphash", "/")]
    assert inner_root.parent_key == archive.node_key
    assert nodes[key("ziphash", "/doc.txt")].kind == KIND_FILE


def test_build_node_rows_synthesises_missing_intermediate_directories():
    """A container listing that skipped a level would otherwise leave a hole in the tree
    exactly where the user is trying to click."""
    nodes = nodes_by_key(build_node_rows(
        DS, dir_rows=[], file_rows=[("", "/a/b/c.txt", "h", 1)], container_hashes=set(),
    ))
    assert key("", "/a") in nodes
    assert key("", "/a/b") in nodes
    assert nodes[key("", "/a")].kind == KIND_DIR


def test_build_node_rows_parents_and_depths_are_consistent():
    nodes = nodes_by_key(build_node_rows(
        DS, dir_rows=[], file_rows=[("", "/a/b/c.txt", "h", 1)], container_hashes=set(),
    ))
    assert nodes[key("", "/a")].parent_key == key("", "/")
    assert nodes[key("", "/a/b")].parent_key == key("", "/a")
    assert nodes[key("", "/a/b/c.txt")].parent_key == key("", "/a/b")
    assert nodes[key("", "/a")].depth < nodes[key("", "/a/b/c.txt")].depth


def test_build_node_rows_picks_a_stable_parent_for_a_duplicated_container():
    """Two copies of one archive: `parent_key` has to pick one, and the choice must not
    flip between runs or the breadcrumb changes under the user. Membership does not use
    it (see the closure tests above)."""
    file_rows = [
        ("", "/location-2/parent.zip", "ziphash", 100),
        ("", "/location-1/parent.zip", "ziphash", 100),
        ("ziphash", "/child.txt", "childhash", 10),
    ]
    first = nodes_by_key(build_node_rows(DS, [], file_rows, {"ziphash"}))
    second = nodes_by_key(build_node_rows(DS, [], list(reversed(file_rows)), {"ziphash"}))
    assert first[key("ziphash", "/")].parent_key == second[key("ziphash", "/")].parent_key


def test_a_recursive_email_does_not_hang_the_depth_walk():
    nodes = build_node_rows(
        DS,
        dir_rows=[],
        file_rows=[
            ("", "/self.eml", "selfmail", 10),
            ("selfmail", "/self.eml", "selfmail", 10),
        ],
        container_hashes={"selfmail"},
    )
    assert nodes, "the builder returned rather than looping"
    assert all(n.depth >= 0 for n in nodes)


def test_container_parents_from_nodes_collects_every_location():
    nodes = build_node_rows(
        DS,
        dir_rows=[],
        file_rows=[
            ("", "/location-1/parent.zip", "ziphash", 100),
            ("", "/location-2/parent.zip", "ziphash", 100),
        ],
        container_hashes={"ziphash"},
    )
    parents = container_parents_from_nodes(nodes)
    assert sorted(parents["ziphash"]) == [
        ("", "/location-1/parent.zip"),
        ("", "/location-2/parent.zip"),
    ]


def test_paths_with_control_characters_are_left_out_of_the_tree():
    nodes = nodes_by_key(build_node_rows(
        DS, dir_rows=[("", "/bad\x1fname")], file_rows=[("", "/ok.txt", "h", 1)],
        container_hashes=set(),
    ))
    assert key("", "/ok.txt") in nodes
    assert not any("\x1fname" in k.split(UNIT_SEP)[-1] for k in nodes)


# --- the wire format of `kind` ------------------------------------------------------

def test_kind_survives_the_round_trip_through_clickhouse():
    """ClickHouse takes the Enum8 NAME on insert and gives back the ORDINAL on read.

    Comparing that int against `'container'` is always false and never raises, so every
    container silently becomes a directory. The only visible symptom was a folder filter
    finding one document where two were reachable — caught on the live stack, not by any
    test, which is why this one exists.
    """
    assert kind_from_wire("container") == KIND_CONTAINER
    assert kind_from_wire(2) == KIND_CONTAINER
    assert kind_from_wire(0) == KIND_DIR
    assert kind_from_wire(1) == KIND_FILE
    # Anything unrecognised degrades to a directory rather than raising: a tree with a
    # mislabelled node is navigable, a tree that fails to build is not.
    assert kind_from_wire(99) == KIND_DIR
    assert kind_from_wire("nonsense") == KIND_DIR


def test_container_parents_are_found_from_ordinal_kinds():
    """The exact shape `index_metadata` reads: dict rows whose `kind` is an int."""
    rows = [
        {"kind": KIND_TO_INT[KIND_CONTAINER], "file_hash": "ziphash",
         "container_hash": "", "path": "/location-1/parent.zip"},
        {"kind": KIND_TO_INT[KIND_CONTAINER], "file_hash": "ziphash",
         "container_hash": "", "path": "/location-2/parent.zip"},
        {"kind": KIND_TO_INT[KIND_DIR], "file_hash": "",
         "container_hash": "", "path": "/location-1"},
    ]
    parents = container_parents_from_nodes(rows)
    assert sorted(parents["ziphash"]) == [
        ("", "/location-1/parent.zip"),
        ("", "/location-2/parent.zip"),
    ]


def test_a_document_in_a_duplicated_container_reaches_both_locations_end_to_end():
    """The §4.4 regression, assembled the way the indexer assembles it."""
    node_rows = [
        {"kind": KIND_TO_INT[KIND_CONTAINER], "file_hash": "ziphash",
         "container_hash": "", "path": "/location-1/parent.zip"},
        {"kind": KIND_TO_INT[KIND_CONTAINER], "file_hash": "ziphash",
         "container_hash": "", "path": "/location-2/parent.zip"},
    ]
    keys, _ = ancestor_node_keys(
        DS, [("ziphash", "/parent/child.txt")], container_parents_from_nodes(node_rows),
    )
    assert key("", "/location-1") in keys
    assert key("", "/location-2") in keys
