"""The transforms between the regex scanner's output and what is indexed.

Every one of these is a boundary that cannot be changed later without a rescan and a
reindex, which is why they are pinned here rather than left to the first corpus that
happens to exercise them.
"""

from datetime import datetime, timezone

import pytest

from tasks.regex_entities import (
    DAY_SECONDS,
    assert_parallel_value_arrays,
    date_within_sanity_window,
    mentioned_days,
    money_bucket,
    money_bucket_from_value_json,
    parse_rfc3339,
    snap_to_day,
)


class TestMoneyLadder:
    @pytest.mark.parametrize("amount,expected", [
        (0, "USD under 1"),
        (0.99, "USD under 1"),
        (1, "USD 1-10"),
        (9.99, "USD 1-10"),
        (10, "USD 10-100"),
        (99.99, "USD 10-100"),
        (100, "USD 100-1k"),
        (999.99, "USD 100-1k"),
        (1_000, "USD 1k-10k"),
        (9_999.99, "USD 1k-10k"),
        (10_000, "USD 10k-100k"),
        (99_999.99, "USD 10k-100k"),
        (100_000, "USD 100k-1M"),
        (999_999.99, "USD 100k-1M"),
        (1_000_000, "USD 1M-10M"),
        (9_999_999.99, "USD 1M-10M"),
        (10_000_000, "USD 10M-100M"),
        (99_999_999.99, "USD 10M-100M"),
        (100_000_000, "USD over 100M"),
        (10 ** 12, "USD over 100M"),
    ])
    def test_every_boundary(self, amount, expected):
        """Lower bound inclusive, upper bound exclusive, at all ten rungs."""
        assert money_bucket("USD", amount) == expected

    def test_a_debit_buckets_by_magnitude(self):
        """A negative amount is a sum of the same size. Bucketing it under `under 1`
        because it is less than one would put every refund in the smallest bucket."""
        assert money_bucket("EUR", -25_000) == "EUR 10k-100k"

    def test_the_label_is_ascii(self):
        """The bucket id is stored in a term dictionary, so a spelling change is a
        reindex. The en-dash belongs to rendering and must never reach here."""
        for amount in (5, 5_000, 5_000_000_000):
            assert "–" not in money_bucket("GBP", amount)

    def test_minor_units_become_major_units(self):
        assert money_bucket_from_value_json(
            '{"kind":"money","currency":"USD","amount_minor":"2500000","exponent":2}'
        ) == "USD 10k-100k"

    def test_a_zero_exponent_currency_is_not_divided(self):
        """JPY has no minor unit. Dividing by 100 anyway would file ¥25 000 two rungs
        below where it belongs."""
        assert money_bucket_from_value_json(
            '{"kind":"money","currency":"JPY","amount_minor":"25000","exponent":0}'
        ) == "JPY 10k-100k"

    def test_a_value_that_is_not_money_has_no_bucket(self):
        assert money_bucket_from_value_json('{"kind":"email","address":"a@b.com"}') is None
        assert money_bucket_from_value_json("not json") is None


class TestDaySnap:
    def test_midnight_is_its_own_day(self):
        assert snap_to_day(0) == 0

    def test_one_second_before_the_epoch_is_the_previous_day(self):
        """Floor division, never truncation toward zero. `int(-1 / 86400)` is 0, which
        would put 1969-12-31T23:59:59 on 1970-01-01, and every pre-epoch instant one
        day late, which is precisely the range the signed column exists for."""
        assert snap_to_day(-1) == -DAY_SECONDS

    def test_a_pre_epoch_instant_snaps_backwards(self):
        moment = datetime(1936, 5, 27, 13, 45, tzinfo=timezone.utc)
        snapped = snap_to_day(int(moment.timestamp()))
        assert datetime.fromtimestamp(snapped, timezone.utc) == datetime(
            1936, 5, 27, tzinfo=timezone.utc
        )

    def test_a_modern_instant_snaps_backwards(self):
        moment = datetime(2001, 3, 18, 17, 59, 56, tzinfo=timezone.utc)
        snapped = snap_to_day(int(moment.timestamp()))
        assert datetime.fromtimestamp(snapped, timezone.utc) == datetime(
            2001, 3, 18, tzinfo=timezone.utc
        )


class TestDateSanityWindow:
    def test_the_lower_bound_is_inclusive(self):
        assert date_within_sanity_window(datetime(1800, 1, 1, tzinfo=timezone.utc))

    def test_an_ocr_artefact_is_outside_it(self):
        """A single `01/01/0001` surviving to the index makes the histogram's domain two
        thousand years wide and collapses every real bar to nothing."""
        assert not date_within_sanity_window(datetime(1, 1, 1, tzinfo=timezone.utc))

    def test_a_far_future_date_is_outside_it(self):
        assert not date_within_sanity_window(datetime(2999, 1, 1, tzinfo=timezone.utc))

    def test_next_month_is_inside_it(self):
        now = datetime(2020, 6, 1, tzinfo=timezone.utc)
        assert date_within_sanity_window(datetime(2020, 7, 1, tzinfo=timezone.utc), now)


class TestParseRfc3339:
    def test_a_bare_date(self):
        assert parse_rfc3339("1936-05-27") == datetime(1936, 5, 27, tzinfo=timezone.utc)

    def test_an_offset_is_applied(self):
        assert parse_rfc3339("2001-03-18T17:59:56-05:00") == datetime(
            2001, 3, 18, 22, 59, 56, tzinfo=timezone.utc
        )

    def test_a_zulu_instant(self):
        assert parse_rfc3339("2001-03-18T17:59:56Z") == datetime(
            2001, 3, 18, 17, 59, 56, tzinfo=timezone.utc
        )

    def test_an_impossible_calendar_date_is_not_a_date(self):
        assert parse_rfc3339("2001-02-30") is None

    def test_junk_is_not_a_date(self):
        assert parse_rfc3339("last Tuesday") is None


class TestMentionedDays:
    def test_two_instants_on_one_day_are_one_entry(self):
        days = mentioned_days(["2001-03-18T09:00:00Z", "2001-03-18T23:00:00Z"])
        assert len(days) == 1

    def test_out_of_window_values_are_dropped_not_clamped(self):
        days = mentioned_days(["0001-01-01", "1936-05-27", "gibberish"])
        assert days == [snap_to_day(int(datetime(1936, 5, 27, tzinfo=timezone.utc).timestamp()))]

    def test_the_result_is_sorted_and_spans_the_epoch(self):
        days = mentioned_days(["2020-01-01", "1936-05-27"])
        assert days == sorted(days)
        assert days[0] < 0 < days[1]


class TestArrayParallelism:
    def _row(self, **overrides):
        row = {
            "file_hash": "abc",
            "page_id": 1,
            "entity_values": ["a", "b"],
            "entity_rule_ids": ["r1", "r2"],
            "entity_value_json": ["{}", "{}"],
            "entity_counts": [1, 2],
            "entity_texts": ["A", "B"],
        }
        row.update(overrides)
        return row

    def test_parallel_arrays_pass(self):
        assert_parallel_value_arrays(self._row()) is None

    def test_a_short_array_raises_naming_the_row(self):
        """Nothing in ClickHouse enforces this, and nothing downstream survives it being
        false: an index built from `entity_values[i]` and `entity_rule_ids[i]` attributes
        a value to another value's rule."""
        with pytest.raises(ValueError) as excinfo:
            assert_parallel_value_arrays(self._row(entity_counts=[1]))
        assert "abc" in str(excinfo.value)
