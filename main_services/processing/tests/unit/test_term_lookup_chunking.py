"""A term-id lookup must not put an unbounded amount of text in one query parameter.

ClickHouse query parameters travel in the request's HTTP form fields, and a field over
`http_max_field_value_size` (128 KiB by default) is rejected with
`Code: 1000 ... HTML Form Exception: Field value too long`, an error that names neither
the parameter nor the query.

Every other `IN {…:Array(String)}` lookup in the pipeline passes file HASHES, which are
64 hex characters each and bounded by the plan's batch size. This one passes distinct
ENTITY VALUES, which are arbitrary text with no bound at all: a fixture corpus produces a
few hundred per batch and never comes close, while one batch of entity-dense documents
produces megabytes and fails every time. That is why the chunking is here and not at the
hash-keyed call sites.
"""

from tasks.P6_index_data.string_term_encodings import (
    _TERM_LOOKUP_BYTE_BUDGET,
    _chunk_by_bytes,
)


def encoded_size(chunk):
    """What the chunk costs as an array literal, matching the chunker's own accounting."""
    return sum(len(v.encode("utf-8", errors="surrogateescape")) + 3 for v in chunk)


def test_nothing_is_lost_or_duplicated():
    values = [f"entity-{i}" for i in range(5000)]
    chunked = [v for chunk in _chunk_by_bytes(values) for v in chunk]
    assert chunked == values


def test_every_chunk_stays_within_the_budget():
    values = ["x" * 100 for _ in range(2000)]
    chunks = list(_chunk_by_bytes(values))
    assert len(chunks) > 1, "a 200 KB input must not go out as one parameter"
    assert all(encoded_size(c) <= _TERM_LOOKUP_BYTE_BUDGET for c in chunks)


def test_the_budget_is_bytes_not_a_count():
    # Same number of values, 100x the text: the byte-sized chunker splits the second,
    # a count-based one would treat them identically and fail on the corpus with the
    # longer values.
    short = list(_chunk_by_bytes(["ab" for _ in range(500)]))
    long = list(_chunk_by_bytes(["ab" * 500 for _ in range(500)]))
    assert len(short) == 1
    assert len(long) > len(short)


def test_a_single_oversized_value_is_still_emitted():
    # Splitting it would change what is being looked up, and dropping it would silently
    # mint a duplicate id for a term that already has one.
    huge = "y" * (_TERM_LOOKUP_BYTE_BUDGET * 3)
    chunks = list(_chunk_by_bytes([huge, "small"]))
    assert [v for c in chunks for v in c] == [huge, "small"]
    assert chunks[0] == [huge]


def test_empty_input_produces_no_queries():
    assert list(_chunk_by_bytes([])) == []


def test_surrogates_do_not_raise():
    # Term values come from extracted text, which reaches here with surrogateescape
    # already applied; the size accounting must use the same error handler or it raises
    # while measuring.
    values = ["ok", "bad\udce9text"]
    assert [v for c in _chunk_by_bytes(values) for v in c] == values
