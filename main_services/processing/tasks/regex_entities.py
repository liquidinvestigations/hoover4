"""The transforms between what the regex entity scanner returns and what is indexed.

Written once and imported by both the scan stage, which stores the raw values, and the
indexing stage, which stores the derived ones. They are here rather than in either stage
because changing any of them means a rescan and a reindex, and a rule that lives in one
stage's module is a rule the other stage can drift away from.

Three things are decided here and nowhere else:

* **which scanner types become facets**, and under which Manticore column and term field;
* **the money magnitude ladder**, because thousands of distinct amounts are not a facet
  and ten buckets per currency are;
* **the day snap and the plausibility window** for mentioned dates, because a term per second
  is unbounded and a term per day is bounded by the corpus's span.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, NamedTuple

#: Seconds in a day. Mentioned dates are snapped to midnight UTC.
DAY_SECONDS = 86_400

#: A date outside this window is dropped rather than clamped.
#:
#: This is the pipeline's window, not the scanner's, and the two are allowed to differ:
#: the scanner applies a per-rule plausibility check knowing only the shape of the text,
#: while this one knows what a corpus looks like. A single OCR'd ``01/01/0001`` that
#: survives to the index makes the histogram's domain two thousand years wide and
#: collapses every real bar to nothing.
DATE_PLAUSIBLE_MIN = datetime(1800, 1, 1, tzinfo=timezone.utc)
DATE_PLAUSIBLE_MAX_LOOKAHEAD = timedelta(days=365)


class FacetField(NamedTuple):
    """One scanner entity type promoted to a facet."""

    #: Scanner entity type, as it appears in `regex_entity_hit.entity_type`.
    entity_type: str
    #: Manticore MVA column on `<shard>_pages`.
    column: str
    #: Term-dictionary field in `string_term_id_to_text`.
    term_field: str


#: The six value facets, in the order the filter modal lists them.
#:
#: `regex_email` is deliberately not `email_address`: that field is the envelope's sender
#: and recipients, and this one is every address the document's body mentions. A needle
#: matching an address should return one row under each, because ticking them applies
#: different filters.
#:
#: The term field is likewise never `ner`. `search_facets.rs` applies the entity stop-list
#: to whatever maps to that field, and the stop-list exists to drop what a *model*
#: mislabels; against checksummed, normalised values it would only do damage.
FACET_FIELDS: tuple[FacetField, ...] = (
    FacetField("email", "re_email", "regex_email"),
    FacetField("phone", "re_phone", "regex_phone"),
    FacetField("bank_account", "re_bank_account", "regex_bank_account"),
    FacetField("company_id", "re_company_id", "regex_company_id"),
    FacetField("money", "re_money", "regex_money"),
    FacetField("crypto_wallet", "re_crypto_wallet", "regex_crypto_wallet"),
)

FACET_BY_ENTITY_TYPE = {field.entity_type: field for field in FACET_FIELDS}

#: The scanner's date type, which is indexed as timestamps rather than as terms.
MENTIONED_DATE_TYPE = "date"


#: The magnitude ladder, lower bound inclusive and upper bound exclusive, applied to the
#: major-unit amount. Ten buckets per currency.
#:
#: Bucket ids are canonical ASCII and are what the term dictionary stores. A label
#: spelling change (an en-dash instead of a hyphen) must never be a reindex, so the
#: en-dash is a render-time concern and never reaches here.
_MONEY_LADDER: tuple[tuple[float, str], ...] = (
    (1, "under 1"),
    (10, "1-10"),
    (100, "10-100"),
    (1_000, "100-1k"),
    (10_000, "1k-10k"),
    (100_000, "10k-100k"),
    (1_000_000, "100k-1M"),
    (10_000_000, "1M-10M"),
    (100_000_000, "10M-100M"),
)
_MONEY_TOP = "over 100M"


def money_bucket(currency: str, amount_major: float) -> str:
    """The facet id for one amount: ``USD 10k-100k``.

    The raw amounts stay in `regex_entity_hit`; only the indexed facet is bucketed, which
    is what lets a viewer show a bucket card containing its own amounts. Changing the
    ladder means a rescan, which is why its boundaries have a test of their own.
    """
    magnitude = abs(amount_major)
    for upper, label in _MONEY_LADDER:
        if magnitude < upper:
            return f"{currency} {label}"
    return f"{currency} {_MONEY_TOP}"


def money_bucket_from_value_json(value_json: str) -> str | None:
    """The bucket for a scanner money value, or None if the value is not money.

    The amount arrives as minor units in a *string*, because a sum of money that
    round-trips through a JSON number is a double and is no longer a sum of money. The
    division into major units happens here and only for the comparison the ladder makes.
    """
    try:
        value = json.loads(value_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict) or value.get("kind") != "money":
        return None
    currency = value.get("currency")
    minor = value.get("amount_minor")
    exponent = value.get("exponent", 0)
    if not currency or minor is None:
        return None
    try:
        major = int(minor) / (10 ** int(exponent))
    except (TypeError, ValueError):
        return None
    return money_bucket(str(currency), major)


#: RFC 3339 as the scanner emits it, including a bare date and a bare `Z`.
_RFC3339_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def parse_rfc3339(raw: str) -> datetime | None:
    """The scanner's date form to an aware UTC datetime, or None.

    A value with no offset is read as UTC. It is the only defensible reading, and being
    an hour out never changes which day-sized bucket a mention lands in, but a value
    read as *local* would silently shift every undated mention by the worker's zone.
    """
    match = _RFC3339_RE.match(raw.strip())
    if not match:
        return None
    year, month, day, hour, minute, second, offset = match.groups()
    try:
        moment = datetime(
            int(year), int(month), int(day),
            int(hour or 0), int(minute or 0), int(second or 0),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        digits = offset[1:].replace(":", "")
        moment -= sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
    return moment


def date_within_plausibility_window(moment: datetime, now: datetime | None = None) -> bool:
    """Whether a mentioned date is plausible enough to index."""
    now = now or datetime.now(timezone.utc)
    return DATE_PLAUSIBLE_MIN <= moment <= now + DATE_PLAUSIBLE_MAX_LOOKAHEAD


def snap_to_day(epoch_seconds: int) -> int:
    """Midnight UTC of the day containing `epoch_seconds`, as signed epoch seconds.

    Floor division, never truncation toward zero: an instant one second before the epoch
    belongs to 1969-12-31, and `int(-1 / 86400)` is 0, which would put it in 1970.
    """
    return (epoch_seconds // DAY_SECONDS) * DAY_SECONDS


def mentioned_days(values: Iterable[str], now: datetime | None = None) -> list[int]:
    """Distinct day timestamps a segment mentions, sorted, range-checked and snapped.

    Signed epoch seconds, because Manticore's own `timestamp` type is 32-bit unsigned and
    cannot hold 1936 at all.
    """
    days: set[int] = set()
    for raw in values:
        moment = parse_rfc3339(raw)
        if moment is None or not date_within_plausibility_window(moment, now):
            continue
        days.add(snap_to_day(int(moment.timestamp())))
    return sorted(days)


def assert_parallel_value_arrays(row: dict) -> None:
    """The five value arrays of a `regex_entity_hit` row are one length.

    Nothing in ClickHouse enforces it, and nothing downstream survives it being false: an
    index built from `entity_values[i]` and `entity_rule_ids[i]` attributes a value to
    another value's rule. The writer is the only place the invariant can hold, so it is
    checked there rather than trusted.
    """
    lengths = {
        name: len(row[name])
        for name in (
            "entity_values",
            "entity_rule_ids",
            "entity_value_json",
            "entity_counts",
            "entity_texts",
        )
    }
    if len(set(lengths.values())) > 1:
        raise ValueError(
            f"regex_entity_hit value arrays are not parallel: {lengths} "
            f"for {row.get('file_hash', '?')} page {row.get('page_id', '?')}"
        )
