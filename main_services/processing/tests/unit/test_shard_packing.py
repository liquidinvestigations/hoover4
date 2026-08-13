"""Tests for the pure shard-packing algorithm.

The packer decides which Manticore shard each document of a plan goes to; the
cases below are the ones where a naive packer gets it wrong.
"""

import pytest

from tasks.P6_index_data.shard_planner import (
    MAX_SHARD_ROWS,
    MAX_SHARD_TEXT_BYTES,
    ShardAssignment,
    ShardState,
    pack_into_shards,
)

GB = 1_000_000_000

#: A row budget high enough not to bind, for the cases that are about bytes.
ROOMY = 10 ** 12


def _shard(name_index: int, text_bytes: int = 0, doc_count: int = 0, is_open: bool = True,
           row_count: int = 0) -> ShardState:
    return ShardState(
        shard_name=f"testdata_{name_index}",
        shard_index=name_index,
        text_bytes=text_bytes,
        doc_count=doc_count,
        is_open=is_open,
        row_count=row_count,
    )


def test_empty_ledger_no_candidates_creates_no_shards():
    assignments, ledger = pack_into_shards("testdata", [], [], max_bytes=GB, max_rows=ROOMY)
    assert assignments == []
    assert ledger == []


def test_empty_ledger_small_docs_all_land_in_shard_1():
    candidates = [("a", 10, 1), ("b", 20, 1), ("c", 30, 1)]
    assignments, ledger = pack_into_shards("testdata", [], candidates, max_bytes=GB, max_rows=ROOMY)
    assert assignments == [
        ShardAssignment(shard_name="testdata_1", shard_index=1, hashes=["a", "b", "c"])
    ]
    assert len(ledger) == 1
    assert ledger[0].shard_name == "testdata_1"
    assert ledger[0].text_bytes == 60
    assert ledger[0].doc_count == 3
    assert ledger[0].is_open is True


def test_full_open_shard_is_sealed_and_next_shard_opened():
    ledger = [_shard(1, text_bytes=900_000_000, doc_count=5)]
    assignments, new_ledger = pack_into_shards(
        "testdata", ledger, [("big", 200_000_000, 1)], max_bytes=GB, max_rows=ROOMY
    )
    assert assignments == [
        ShardAssignment(shard_name="testdata_2", shard_index=2, hashes=["big"])
    ]
    shard1, shard2 = new_ledger
    assert shard1.is_open is False
    assert shard1.text_bytes == 900_000_000  # untouched
    assert shard2.is_open is True
    assert shard2.text_bytes == 200_000_000
    assert shard2.doc_count == 1


def test_oversized_single_document_gets_its_own_shard():
    assignments, ledger = pack_into_shards(
        "testdata", [], [("huge", 3 * GB, 1)], max_bytes=GB, max_rows=ROOMY
    )
    assert assignments == [
        ShardAssignment(shard_name="testdata_1", shard_index=1, hashes=["huge"])
    ]
    assert len(ledger) == 1
    assert ledger[0].text_bytes == 3 * GB
    assert ledger[0].is_open is False  # sealed immediately, no infinite loop


def test_oversized_document_followed_by_small_one_opens_new_shard():
    assignments, ledger = pack_into_shards(
        "testdata", [], [("huge", 3 * GB, 1), ("small", 10, 1)], max_bytes=GB, max_rows=ROOMY
    )
    by_hash = {h: a.shard_name for a in assignments for h in a.hashes}
    assert by_hash == {"huge": "testdata_1", "small": "testdata_2"}
    assert ledger[0].is_open is False
    assert ledger[1].is_open is True


def test_no_open_shard_in_ledger_opens_next_index():
    ledger = [_shard(1, text_bytes=2 * GB, doc_count=1, is_open=False),
              _shard(2, text_bytes=GB, doc_count=1, is_open=False)]
    assignments, new_ledger = pack_into_shards(
        "testdata", ledger, [("new", 10, 1)], max_bytes=GB, max_rows=ROOMY
    )
    assert assignments == [
        ShardAssignment(shard_name="testdata_3", shard_index=3, hashes=["new"])
    ]
    assert [s.shard_index for s in new_ledger] == [1, 2, 3]


def test_already_assigned_hash_keeps_its_shard_and_bytes_are_not_recounted():
    ledger = [_shard(1, text_bytes=500, doc_count=1)]
    assignments, new_ledger = pack_into_shards(
        "testdata",
        ledger,
        candidates=[],
        max_bytes=GB, max_rows=ROOMY,
        existing_assignments={"doc-a": "testdata_1"},
    )
    assert assignments == [
        ShardAssignment(shard_name="testdata_1", shard_index=1, hashes=["doc-a"])
    ]
    # Bytes already in the ledger must not be double-counted.
    assert new_ledger[0].text_bytes == 500
    assert new_ledger[0].doc_count == 1


def test_mixed_existing_and_new_assignments():
    ledger = [_shard(1, text_bytes=500, doc_count=1)]
    assignments, new_ledger = pack_into_shards(
        "testdata",
        ledger,
        candidates=[("doc-b", 100, 1)],
        max_bytes=GB, max_rows=ROOMY,
        existing_assignments={"doc-a": "testdata_1"},
    )
    by_hash = {h: a.shard_name for a in assignments for h in a.hashes}
    assert by_hash == {"doc-a": "testdata_1", "doc-b": "testdata_1"}
    assert new_ledger[0].text_bytes == 600
    assert new_ledger[0].doc_count == 2


def test_deterministic_and_order_independent():
    ledger = [_shard(1, text_bytes=900_000_000, doc_count=3)]
    candidates = [("a", 200_000_000, 1), ("b", 50, 1), ("c", 300_000_000, 1), ("d", 10, 1)]
    shuffled = [("c", 300_000_000, 1), ("a", 200_000_000, 1), ("d", 10, 1), ("b", 50, 1)]
    first = pack_into_shards("testdata", ledger, candidates, max_bytes=GB, max_rows=ROOMY)
    second = pack_into_shards("testdata", ledger, shuffled, max_bytes=GB, max_rows=ROOMY)
    assert first == second


def test_inputs_are_not_mutated():
    ledger = [_shard(1, text_bytes=100, doc_count=1)]
    candidates = [("a", 10, 1)]
    pack_into_shards("testdata", ledger, candidates, max_bytes=GB, max_rows=ROOMY)
    assert ledger[0].text_bytes == 100
    assert ledger[0].is_open is True
    assert candidates == [("a", 10, 1)]


def test_the_budgets_are_the_measured_ones():
    # 4 GB of raw text is ~6.9 GB on disk and keeps a shard's worst-case facet scan
    # inside the search timeout; 2.5 M rows is where an email corpus binds first.
    assert MAX_SHARD_TEXT_BYTES == 4_000_000_000
    assert MAX_SHARD_ROWS == 2_500_000


def test_the_row_budget_seals_a_shard_that_is_nowhere_near_the_byte_budget():
    # The straggler case: a mail corpus reaches millions of rows while its text is a
    # fraction of the byte budget, and facet cost tracks rows.
    ledger = [_shard(1, text_bytes=1000, doc_count=2, row_count=90)]
    assignments, new_ledger = pack_into_shards(
        "testdata", ledger, [("new", 10, 20)], max_bytes=GB, max_rows=100
    )
    assert assignments == [
        ShardAssignment(shard_name="testdata_2", shard_index=2, hashes=["new"])
    ]
    assert new_ledger[0].is_open is False
    assert new_ledger[1].row_count == 20


def test_a_document_with_more_rows_than_the_budget_gets_its_own_shard():
    # Candidates are packed in hash order, so `a-wide` is placed first.
    assignments, ledger = pack_into_shards(
        "testdata", [], [("a-wide", 10, 500), ("b-small", 10, 1)], max_bytes=GB, max_rows=100
    )
    by_hash = {h: a.shard_name for a in assignments for h in a.hashes}
    assert by_hash == {"a-wide": "testdata_1", "b-small": "testdata_2"}
    assert ledger[0].is_open is False


def test_a_document_with_no_text_still_costs_a_row():
    # Its filename row. Counting it as 0 would let a shard hold unlimited such
    # documents, and every one of them is still a row the group-by walks.
    _, ledger = pack_into_shards(
        "testdata", [], [("a", 0, 0), ("b", 0, 0)], max_bytes=GB, max_rows=ROOMY
    )
    assert ledger[0].row_count == 2


def test_invalid_collectionname_raises():
    with pytest.raises(ValueError):
        pack_into_shards("bad name!", [], [("a", 1, 1)], max_bytes=GB, max_rows=ROOMY)


# --- U1: edge cases called out by the bugfix review ---


def test_open_shard_already_over_budget_seals_before_taking_more():
    # Possible after a purge shrank a shard's neighbours: the newest open shard is
    # already over budget. The next candidate must seal it and open a fresh shard —
    # never pile onto an over-budget shard.
    ledger = [_shard(1, text_bytes=GB + 5, doc_count=3)]
    assignments, new_ledger = pack_into_shards(
        "testdata", ledger, [("new", 10, 1)], max_bytes=GB, max_rows=ROOMY
    )
    assert assignments == [
        ShardAssignment(shard_name="testdata_2", shard_index=2, hashes=["new"])
    ]
    shard1, shard2 = new_ledger
    assert shard1.is_open is False
    assert shard2.text_bytes == 10


def test_candidate_exactly_at_budget_fits_and_stays_open():
    # text_bytes == max_bytes exactly: fits (the seal rule is strictly-greater).
    assignments, ledger = pack_into_shards(
        "testdata", [], [("exact", GB, 1)], max_bytes=GB, max_rows=ROOMY
    )
    assert assignments == [
        ShardAssignment(shard_name="testdata_1", shard_index=1, hashes=["exact"])
    ]
    assert ledger[0].text_bytes == GB
    # ...but the next document of any size seals it.
    assignments, ledger = pack_into_shards(
        "testdata", [], [("exact", GB, 1), ("next", 1, 1)], max_bytes=GB, max_rows=ROOMY
    )
    by_hash = {h: a.shard_name for a in assignments for h in a.hashes}
    assert by_hash == {"exact": "testdata_1", "next": "testdata_2"}
    assert ledger[0].is_open is False


def test_hash_in_both_candidates_and_existing_keeps_existing_shard():
    # plan_shards filters candidates down to unassigned hashes, but the packer
    # itself must stay sane if a hash slips into both: the existing assignment
    # wins and the bytes are not double-counted.
    ledger = [_shard(1, text_bytes=500, doc_count=1)]
    assignments, new_ledger = pack_into_shards(
        "testdata",
        ledger,
        candidates=[("doc-a", 100, 1)],
        max_bytes=GB, max_rows=ROOMY,
        existing_assignments={"doc-a": "testdata_1"},
    )
    by_hash = {h: a.shard_name for a in assignments for h in a.hashes}
    assert by_hash == {"doc-a": "testdata_1"}
    assert new_ledger[0].doc_count == 1
    assert new_ledger[0].text_bytes == 500


def test_existing_assignment_to_shard_absent_from_ledger_keeps_that_shard():
    # A re-index after the ledger was rebuilt incompletely: the assignment row is
    # the reservation and wins; the packer must not invent a new shard for the
    # document (the writers overwrite in place).
    ledger = [_shard(1, text_bytes=10, doc_count=1)]
    assignments, new_ledger = pack_into_shards(
        "testdata",
        ledger,
        candidates=[],
        max_bytes=GB, max_rows=ROOMY,
        existing_assignments={"doc-x": "testdata_7"},
    )
    assert assignments == [
        ShardAssignment(shard_name="testdata_7", shard_index=7, hashes=["doc-x"])
    ]
    # The ledger is untouched: recompute_shard_ledger rebuilds fill levels anyway.
    assert [s.shard_index for s in new_ledger] == [1]


def test_malformed_shard_name_in_existing_assignments_raises_with_context():
    # A malformed name must fail loudly and say WHICH name was bad — a silent skip
    # would lose documents, a bare ValueError would send the reader hunting.
    with pytest.raises(ValueError, match="not-a-shard-name"):
        pack_into_shards(
            "testdata",
            [],
            [],
            max_bytes=GB, max_rows=ROOMY,
            existing_assignments={"doc-x": "not-a-shard-name"},
        )


# --- U2: the ledger ⋈ stats join behind recompute_shard_ledger ---


def test_merge_ledger_stats_fills_and_preserves_open_flags():
    from tasks.P6_index_data.shard_planner import merge_ledger_stats

    ledger_rows = [("testdata_1", 1, 0), ("testdata_2", 2, 1)]
    stats_rows = [("testdata_2", 700, 12, 4)]
    merged = merge_ledger_stats(ledger_rows, stats_rows)
    assert [(s.shard_name, s.text_bytes, s.row_count, s.doc_count, s.is_open) for s in merged] == [
        ("testdata_1", 0, 0, 0, False),  # no stats -> zeros, sealed stays sealed
        ("testdata_2", 700, 12, 4, True),
    ]


def test_merge_ledger_stats_empty_stats_zeroes_everything():
    from tasks.P6_index_data.shard_planner import merge_ledger_stats

    merged = merge_ledger_stats([("testdata_1", 1, 1)], [])
    assert merged[0].text_bytes == 0
    assert merged[0].row_count == 0
    assert merged[0].doc_count == 0
    assert merged[0].is_open is True  # never re-opens and never seals
