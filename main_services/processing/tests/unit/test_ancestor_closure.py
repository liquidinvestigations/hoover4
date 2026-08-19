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
    return nothing — the regression this fixture exists to catch.
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


def test_build_node_rows_marks_containers_and_links_their_members():
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
    # What is inside the archive hangs off the archive FILE, crossing the boundary. There
    # is no `/` node in between: expanding the archive shows its contents.
    assert key("ziphash", "/") not in nodes
    assert nodes[key("ziphash", "/doc.txt")].parent_key == archive.node_key
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
    member = key("ziphash", "/child.txt")
    assert first[member].parent_key == second[member].parent_key
    assert first[member].parent_key == key("", "/location-1/parent.zip")


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
            # The member is what makes the two copies containers at all — a hash nothing
            # is inside is a plain file, and a plain file is nobody's parent.
            ("ziphash", "/child.txt", "childhash", 10),
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
    """The exact shape `document_metadata` reads: dict rows whose `kind` is an int."""
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
    """The duplicated-container regression, assembled the way the indexer assembles it."""
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


# --- a container is a file with members ---------------------------------------------

#: The three fixture shapes the corpus actually contains, as `(dir_rows, file_rows,
#: detected, hash, expect_container)`. "Detected" is what the archive/email sniff says;
#: whether it is a CONTAINER is a different question, and the answer is membership.
MEMBERSHIP_SHAPES = [
    (
        "eml-2-attachment: an email with one attachment is a container",
        [], [("", "/eml-2-attachment.eml", "mailhash", 900),
             ("mailhash", "/report.pdf", "pdfhash", 400)],
        {"mailhash"}, "mailhash", True,
    ),
    (
        "an email with no attachment is a FILE however it was detected",
        [], [("", "/plain.eml", "mailhash", 900)],
        {"mailhash"}, "mailhash", False,
    ),
    (
        "eml-7-recursive: an email containing itself has a member, so it is a container",
        [], [("", "/self.eml", "selfmail", 10), ("selfmail", "/self.eml", "selfmail", 10)],
        {"selfmail"}, "selfmail", True,
    ),
    (
        "zip-in-multiple-locations: two copies of one archive, one set of members",
        [], [("", "/location-1/parent.zip", "ziphash", 100),
             ("", "/location-2/parent.zip", "ziphash", 100),
             ("ziphash", "/child.txt", "childhash", 10)],
        {"ziphash"}, "ziphash", True,
    ),
    (
        "an archive whose listing found nothing is not an archive",
        [], [("", "/location-1/empty.zip", "ziphash", 100)],
        {"ziphash"}, "ziphash", False,
    ),
    (
        "a container whose only member is a DIRECTORY still has members",
        [("ziphash", "/inner")], [("", "/dirs-only.zip", "ziphash", 100)],
        {"ziphash"}, "ziphash", True,
    ),
]


@pytest.mark.parametrize(
    "label,dir_rows,file_rows,detected,file_hash,expect_container",
    MEMBERSHIP_SHAPES,
    ids=[shape[0].split(":")[0] for shape in MEMBERSHIP_SHAPES],
)
def test_build_node_rows_membership(
    label, dir_rows, file_rows, detected, file_hash, expect_container
):
    """Detection proposes, membership decides.

    Every email in the demo corpus is detected as an archive-like thing, and 100% of them
    had nothing inside — so 543 195 emails rendered as folders that expand to nothing.
    A file with no members is a FILE, whatever the sniff said.
    """
    nodes = nodes_by_key(build_node_rows(DS, dir_rows, file_rows, detected))
    the_file = next(n for n in nodes.values() if n.file_hash == file_hash)
    expected = KIND_CONTAINER if expect_container else KIND_FILE
    assert the_file.kind == expected, label


def test_no_synthetic_container_root():
    """No `/` node inside a container, and the members re-parent onto the container file.

    `depth` drops by exactly one per container hop as a result: the hop IS the hop, and
    the extra `/` level was counting it twice.
    """
    nodes = nodes_by_key(build_node_rows(
        DS,
        dir_rows=[("", "/data")],
        file_rows=[
            ("", "/data/outer.zip", "outerhash", 500),
            ("outerhash", "/inner.zip", "innerhash", 300),
            ("innerhash", "/deep.txt", "deephash", 20),
        ],
        container_hashes={"outerhash", "innerhash"},
    ))
    assert not [n for n in nodes.values() if n.path == "/" and n.container_hash], \
        "a container's root is not a node"

    outer = nodes[key("", "/data/outer.zip")]
    inner = nodes[key("outerhash", "/inner.zip")]
    deep = nodes[key("innerhash", "/deep.txt")]
    assert inner.parent_key == outer.node_key
    assert deep.parent_key == inner.node_key
    # One hop per level, container hops included: /data(1) outer.zip(2) inner.zip(3)
    # deep.txt(4). With the `/` nodes it was six.
    assert (nodes[key("", "/data")].depth, outer.depth, inner.depth, deep.depth) == (1, 2, 3, 4)


def test_ancestor_closure_unchanged():
    """Membership does not go through `parent_key`, so removing the `/` node changes NO
    closure. Pinned as an explicit expected set: if this moves, the change is wrong.
    """
    node_rows = [
        {"kind": KIND_TO_INT[KIND_CONTAINER], "file_hash": "ziphash",
         "container_hash": "", "path": "/location-1/parent.zip"},
    ]
    keys, truncated = ancestor_node_keys(
        DS, [("ziphash", "/inner/child.txt")], container_parents_from_nodes(node_rows),
    )
    assert not truncated
    assert keys == {
        # Inside the container, the `/` KEY is still an ancestor of the path — it is a
        # term, not a node, and the two were never the same thing.
        key("ziphash", "/"),
        key("ziphash", "/inner"),
        key("", "/location-1/parent.zip"),
        key("", "/"),
        key("", "/location-1"),
        ROOT,
    }
