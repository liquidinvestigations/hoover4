"""The file count and byte count below each VFS node.

Pure, no stack. The website's read-time fallback in `website/backend/src/api/vfs/stats.rs`
must give the same numbers for the same trees, and its tests use the same four fixtures.
"""

from tasks.P6_index_data.vfs_nodes import build_node_rows, make_node_key

DS = "fx"


def stats(nodes, container_hash, path):
    by_key = {node.node_key: node for node in nodes}
    node = by_key[make_node_key(DS, container_hash, path)]
    return node.subtree_file_count, node.subtree_size_bytes


def test_folder_counts_files_below_it_and_plain_files_read_zero():
    nodes = build_node_rows(
        DS,
        [("", "/a"), ("", "/a/b"), ("", "/empty")],
        [("", "/a/one.txt", "1", 10), ("", "/a/b/two.txt", "2", 20), ("", "/top.txt", "3", 5)],
        set(),
    )
    assert stats(nodes, "", "/") == (3, 35)
    assert stats(nodes, "", "/a") == (2, 30)
    assert stats(nodes, "", "/a/b") == (1, 20)
    assert stats(nodes, "", "/empty") == (0, 0)
    assert stats(nodes, "", "/top.txt") == (0, 0)


def test_demoted_container_with_no_members_is_a_plain_file():
    nodes = build_node_rows(DS, [], [("", "/empty.zip", "Z", 7)], {"Z"})
    assert stats(nodes, "", "/") == (1, 7)
    assert stats(nodes, "", "/empty.zip") == (0, 0)


def test_self_containing_email_is_not_opened_twice():
    nodes = build_node_rows(
        DS,
        [("", "/mail")],
        [("", "/mail/e.eml", "E", 100), ("E", "/e.eml", "E", 100), ("E", "/a.txt", "T", 5)],
        {"E"},
    )
    assert stats(nodes, "", "/") == (3, 100)
    assert stats(nodes, "", "/mail") == (3, 100)
    assert stats(nodes, "", "/mail/e.eml") == (2, 105)
    assert stats(nodes, "E", "/e.eml") == (2, 105)
    assert stats(nodes, "E", "/a.txt") == (0, 0)


def test_copy_of_the_holder_in_a_subfolder_is_one_file_there():
    nodes = build_node_rows(
        DS,
        [("E", "/sub")],
        [("", "/e.eml", "E", 100), ("E", "/sub/e.eml", "E", 100), ("E", "/a.txt", "T", 5)],
        {"E"},
    )
    assert stats(nodes, "E", "/sub") == (1, 100)
    assert stats(nodes, "E", "/sub/e.eml") == (2, 105)
    assert stats(nodes, "", "/e.eml") == (2, 105)
    assert stats(nodes, "", "/") == (3, 100)


def test_two_container_cycle_stops_at_the_open_container():
    nodes = build_node_rows(
        DS,
        [],
        [("", "/a.zip", "A", 50), ("A", "/b.zip", "B", 30), ("A", "/y.txt", "Y", 3),
         ("B", "/a.zip", "A", 50), ("B", "/x.txt", "X", 2)],
        {"A", "B"},
    )
    assert stats(nodes, "", "/") == (5, 50)
    assert stats(nodes, "", "/a.zip") == (4, 33)
    assert stats(nodes, "A", "/b.zip") == (2, 52)
    assert stats(nodes, "B", "/a.zip") == (2, 33)


def test_container_at_two_paths_counts_under_both():
    nodes = build_node_rows(
        DS,
        [("", "/p"), ("", "/q")],
        [("", "/p/a.zip", "A", 40), ("", "/q/a.zip", "A", 40),
         ("A", "/b1.zip", "B", 10), ("A", "/sub/b2.zip", "B", 10), ("B", "/z.txt", "Z", 1)],
        {"A", "B"},
    )
    assert stats(nodes, "", "/") == (10, 80)
    assert stats(nodes, "", "/p") == (5, 40)
    assert stats(nodes, "", "/q") == (5, 40)
    assert stats(nodes, "", "/p/a.zip") == (4, 20)
    assert stats(nodes, "A", "/sub") == (2, 10)
    assert stats(nodes, "A", "/b1.zip") == (1, 1)


def test_long_chain_has_no_depth_limit():
    files = [("", "/c0.zip", "C0", 1)]
    for i in range(3000):
        files.append((f"C{i}", f"/c{i + 1}.zip", f"C{i + 1}", 1))
    files.append(("C3000", "/leaf.txt", "L", 1))
    nodes = build_node_rows(DS, [], files, {f"C{i}" for i in range(3001)})
    assert stats(nodes, "", "/") == (3002, 1)
    assert stats(nodes, "", "/c0.zip") == (3001, 1)
    assert stats(nodes, "C2999", "/c3000.zip") == (1, 1)


def test_prototype_chain_fixture_values():
    files = [("", "/c0.zip", "C0", 1)]
    for i in range(70):
        files.append((f"C{i}", f"/c{i + 1}.zip", f"C{i + 1}", 1))
    files.append(("C70", "/leaf.txt", "L", 1))
    nodes = build_node_rows(DS, [], files, {f"C{i}" for i in range(71)})
    assert stats(nodes, "", "/") == (72, 1)
