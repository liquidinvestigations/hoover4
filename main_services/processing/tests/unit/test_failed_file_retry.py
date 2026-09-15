"""Which re-run recovers which failure, and the chunking that keeps a hash list
inside ClickHouse's parameter limit."""

from tasks.P_admin.failed_file_retry import HASH_CHUNK, chunked


def test_chunked_bounds_every_batch():
    values = [f"h{i}" for i in range(HASH_CHUNK * 2 + 3)]
    batches = list(chunked(values))
    assert sum(len(b) for b in batches) == len(values)
    assert [v for b in batches for v in b] == values
    assert all(len(b) <= HASH_CHUNK for b in batches)


def test_chunked_of_nothing_yields_nothing():
    assert list(chunked([])) == []
