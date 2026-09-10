"""Location-only index refresh selects affected documents, never a collection rebuild."""

from tasks.P6_index_data.location_refresh import (
    MECHANISM_AFFECTED,
    MECHANISM_NONE,
    expected_vfs_node_ids,
    hashes_with_stale_locations,
    parse_mva_ids,
    refresh_scope,
)


def test_parse_mva_ids_accepts_tuple_literal_and_lists():
    assert parse_mva_ids("()") == frozenset()
    assert parse_mva_ids("(1, 2, 3)") == frozenset({1, 2, 3})
    assert parse_mva_ids([3, 1]) == frozenset({1, 3})
    assert parse_mva_ids(None) == frozenset()
    # mysql.connector returns an MVA as a comma string with no parentheses.
    assert parse_mva_ids("7795667159360797803") == frozenset({7795667159360797803})
    assert parse_mva_ids("1,2,3") == frozenset({1, 2, 3})


def test_a_second_location_changes_expected_ids():
    ds = "c_d"
    one = expected_vfs_node_ids(ds, [("", "/a/hello.txt")], {})
    two = expected_vfs_node_ids(
        ds, [("", "/a/hello.txt"), ("", "/b/hello.txt")], {}
    )
    assert one
    assert one != two
    assert one < two


def test_stale_when_indexed_closure_misses_a_location():
    expected = {"h": frozenset({1, 2, 3})}
    indexed = {"h": frozenset({1, 2})}
    assert hashes_with_stale_locations(expected, indexed) == ["h"]


def test_current_when_closures_match():
    expected = {"h": frozenset({1, 2})}
    indexed = {"h": frozenset({2, 1})}
    assert hashes_with_stale_locations(expected, indexed) == []


def test_unindexed_hash_is_not_selected():
    expected = {"h": frozenset({1})}
    indexed = {}
    assert hashes_with_stale_locations(expected, indexed) == []


def test_refresh_scope_stays_on_affected_documents():
    selected, mechanism = refresh_scope(["a"], 1000)
    assert selected == ["a"]
    assert mechanism == MECHANISM_AFFECTED


def test_refresh_scope_of_nothing_is_empty():
    selected, mechanism = refresh_scope([], 1000)
    assert selected == []
    assert mechanism == MECHANISM_NONE


def test_refresh_document_locations_defaults_to_dry_run():
    from main import refresh_document_locations

    apply_opt = next(p for p in refresh_document_locations.params if p.name == "apply")
    assert apply_opt.default is False


def test_refresh_document_locations_is_a_dataset_operation():
    from database.operations import KINDS

    assert KINDS["refresh_document_locations"]["target_kind"] == "dataset"
    assert KINDS["refresh_document_locations"]["destructive"] is False
