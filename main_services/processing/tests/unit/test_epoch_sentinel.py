"""1970-01-01 means two different things in `email_headers.date_sent`.

`date_sent` is not nullable, so P3 has always written the epoch when the `Date:` header
was missing or unparseable. That makes the epoch both "no date" and "a genuine 1970
email" — and a corpus of undated mail all landing on 1970-01-01 is a date facet with one
enormous fake bucket in it. `date_sent_known` is what separates the two, and this pins
that the resolver honours it in both directions.
"""

from datetime import datetime, timezone

from tasks.P3_parse_files.document_dates import EMAIL_DATE_SOURCE, resolve_dates

UTC = timezone.utc
NOW = datetime(2026, 8, 8, tzinfo=UTC)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def test_the_fallback_epoch_produces_no_date_row():
    """`date_sent_known = 0` means the caller passes nothing at all."""
    assert resolve_dates(None, email_date_sent=None, now=NOW) == []


def test_a_genuine_1970_email_produces_a_date_row():
    """The epoch is a real instant and a real email can carry it. Suppressing it by
    value rather than by the flag would silently lose those documents."""
    result = resolve_dates(None, email_date_sent=EPOCH, now=NOW)
    assert result == [(EPOCH, EMAIL_DATE_SOURCE)]


def test_a_genuine_1970_email_is_inside_the_sanity_window():
    result = resolve_dates(None, email_date_sent=datetime(1970, 1, 1, 0, 0, 1), now=NOW)
    assert len(result) == 1


def test_the_resolver_never_inspects_the_value_to_decide_trust():
    """Belt and braces: an epoch date and a 2013 date go through the same path, so a
    future 'skip if == epoch' shortcut would fail this test rather than the corpus."""
    epoch_result = resolve_dates(None, email_date_sent=EPOCH, now=NOW)
    real_result = resolve_dates(None, email_date_sent=datetime(2013, 5, 1), now=NOW)
    assert [s for _, s in epoch_result] == [s for _, s in real_result] == [EMAIL_DATE_SOURCE]
