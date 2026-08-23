"""The date resolver: which metadata dates get indexed, and which never do.

Pure, no stack. This is where the real bugs live: one wrong key here dates every
document in the corpus "today", and one over-strict parser silently drops the only date
a document has. Both look like "the date filter is a bit off" from the UI.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from tasks.P3_parse_files.document_dates import (
    ARCHIVE_MTIME_SOURCE,
    EMAIL_DATE_SOURCE,
    EXCLUDED_TIKA_DATE_KEYS,
    TIKA_DATE_KEYS,
    in_sanity_window,
    parse_metadata_datetime,
    resolve_dates,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 8, tzinfo=UTC)


def _tika(**keys) -> str:
    """Tika metadata as it actually lands in ClickHouse: values are JSON arrays."""
    return json.dumps({k: ([v] if isinstance(v, str) else v) for k, v in keys.items()})


def sources(result) -> list[str]:
    return [source for _, source in result]


def isos(result) -> list[str]:
    return [when.isoformat() for when, _ in result]


# --- parsing -----------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("2007-10-10T22:44:00Z", "2007-10-10T22:44:00+00:00"),
    ("2007-10-10T22:44:00z", "2007-10-10T22:44:00+00:00"),
    # Naive: read as UTC. Being an hour out never changes the year bucket.
    ("2007-10-10T22:44:00", "2007-10-10T22:44:00+00:00"),
    ("2013-05-01T12:00:00+03:00", "2013-05-01T09:00:00+00:00"),
    ("2013-05-01T12:00:00-05:00", "2013-05-01T17:00:00+00:00"),
    ("2013-05-01", "2013-05-01T00:00:00+00:00"),
    ("2007-10-10T22:44:00.123Z", "2007-10-10T22:44:00.123000+00:00"),
    # PDF's own syntax, which Tika sometimes passes through untouched.
    ("D:20070101224400", "2007-01-01T22:44:00+00:00"),
    ("D:20070101224400+03'00'", "2007-01-01T22:44:00+00:00"),
    ("D:2007", "2007-01-01T00:00:00+00:00"),
])
def test_parses_the_variants_tika_actually_emits(raw, expected):
    assert parse_metadata_datetime(raw).isoformat() == expected


@pytest.mark.parametrize("raw", [
    None, "", "   ", "not a date", "0000-00-00T00:00:00Z", "D:99999999999999",
    "2007-13-45T99:99:99Z",
])
def test_garbage_is_dropped_not_raised(raw):
    """Garbage in document metadata is normal. One bad string must not fail a plan."""
    assert parse_metadata_datetime(raw) is None


# --- the sanity window -------------------------------------------------------------

def test_sanity_window_bounds():
    assert in_sanity_window(datetime(1800, 1, 1, tzinfo=UTC), NOW)
    assert not in_sanity_window(datetime(1799, 12, 31, tzinfo=UTC), NOW)
    assert in_sanity_window(NOW + timedelta(days=364), NOW)
    assert not in_sanity_window(NOW + timedelta(days=366), NOW)


def test_out_of_window_dates_are_dropped_never_clamped():
    """A clamped date is a wrong answer that looks like a right one."""
    result = resolve_dates(_tika(**{
        "dcterms:created": "-4004-10-23T09:00:00Z",
        "dcterms:modified": "2099-01-01T00:00:00Z",
    }), now=NOW)
    assert result == []


def test_pre_1970_dates_survive():
    """The whole reason `dates` is a signed bigint rather than Manticore's timestamp."""
    result = resolve_dates(_tika(**{"dcterms:created": "1936-04-01T00:00:00Z"}), now=NOW)
    assert isos(result) == ["1936-04-01T00:00:00+00:00"]
    assert result[0][0].timestamp() < 0


# --- key selection -----------------------------------------------------------------

def test_file_modified_date_is_never_consulted():
    """Tika's `File Modified Date` is the mtime of the worker's temp file.

    It is present on nearly every document, so including it would date the whole corpus
    "today" and make date filtering worthless.
    """
    result = resolve_dates(_tika(**{
        "File Modified Date": "2026-08-08T12:00:00Z",
        "Last-Modified": "2026-08-08T12:00:00Z",
    }), now=NOW)
    assert result == []


def test_allowlist_and_exclusion_set_are_disjoint():
    assert not (set(TIKA_DATE_KEYS) & EXCLUDED_TIKA_DATE_KEYS)


def test_collects_every_confirmed_date_not_a_best_of():
    """A document written in 2007 and re-saved in 2013 has BOTH dates.

    Search matches a range against any of them, and the viewer shows all of them with
    their provenance. Picking a winner here would make both features wrong.
    """
    result = resolve_dates(_tika(**{
        "dcterms:created": "2007-10-10T22:44:00Z",
        "dcterms:modified": "2013-05-01T00:00:00Z",
        "pdf:docinfo:created": "2007-10-10T22:44:00Z",
    }), now=NOW)
    assert isos(result) == [
        "2007-10-10T22:44:00+00:00",
        "2007-10-10T22:44:00+00:00",
        "2013-05-01T00:00:00+00:00",
    ]
    assert sorted(sources(result)) == [
        "tika:dcterms:created", "tika:dcterms:modified", "tika:pdf:docinfo:created",
    ]


def test_same_date_from_the_same_key_twice_is_deduplicated():
    result = resolve_dates(_tika(**{
        "dcterms:created": ["2007-10-10T22:44:00Z", "2007-10-10T22:44:00+00:00"],
    }), now=NOW)
    assert len(result) == 1


def test_multi_valued_keys_all_contribute():
    result = resolve_dates(_tika(**{
        "dcterms:created": ["2007-10-10T22:44:00Z", "2011-01-01T00:00:00Z"],
    }), now=NOW)
    assert len(result) == 2


@pytest.mark.parametrize("metadata", [None, "", "{}", "not json", "[1,2,3]", "null"])
def test_empty_or_broken_metadata_yields_nothing(metadata):
    assert resolve_dates(metadata, now=NOW) == []


def test_a_bare_string_value_is_tolerated():
    """Tika values are arrays, but a stray scalar must not crash the resolver."""
    result = resolve_dates(json.dumps({"dcterms:created": "2007-10-10T22:44:00Z"}), now=NOW)
    assert len(result) == 1


# --- the non-Tika sources ----------------------------------------------------------

def test_email_and_archive_sources_are_labelled():
    result = resolve_dates(
        None,
        email_date_sent=datetime(2013, 5, 1, 12, 0, 0),
        archive_mtimes=[datetime(2016, 3, 2, tzinfo=UTC)],
        now=NOW,
    )
    assert sources(result) == [EMAIL_DATE_SOURCE, ARCHIVE_MTIME_SOURCE]


def test_naive_email_date_is_read_as_utc():
    """ClickHouse hands back naive datetimes; UTC is what P3 stored."""
    result = resolve_dates(None, email_date_sent=datetime(2013, 5, 1, 12, 0, 0), now=NOW)
    assert isos(result) == ["2013-05-01T12:00:00+00:00"]


def test_an_epoch_integer_is_accepted_as_well_as_a_datetime():
    """`query_arrow().to_pylist()` returns ClickHouse DateTime columns as raw epoch
    integers, not datetimes, which was caught in a worker log rather than by reading the schema.
    Both forms must resolve to the same instant."""
    as_int = resolve_dates(None, email_date_sent=1367409600, now=NOW)
    as_dt = resolve_dates(None, email_date_sent=datetime(2013, 5, 1, 12, 0, 0, tzinfo=UTC), now=NOW)
    assert isos(as_int) == isos(as_dt) == ["2013-05-01T12:00:00+00:00"]
    # Same for the archive-mtime source, which reads the same column type.
    assert isos(resolve_dates(None, archive_mtimes=[1367409600], now=NOW)) == \
        ["2013-05-01T12:00:00+00:00"]


def test_an_out_of_window_archive_mtime_is_dropped():
    result = resolve_dates(None, archive_mtimes=[datetime(1601, 1, 1, tzinfo=UTC)], now=NOW)
    assert result == []


def test_result_is_sorted_ascending():
    result = resolve_dates(
        _tika(**{"dcterms:modified": "2013-05-01T00:00:00Z",
                 "dcterms:created": "2007-01-01T00:00:00Z"}),
        email_date_sent=datetime(2010, 1, 1, tzinfo=UTC),
        now=NOW,
    )
    assert isos(result) == sorted(isos(result))
