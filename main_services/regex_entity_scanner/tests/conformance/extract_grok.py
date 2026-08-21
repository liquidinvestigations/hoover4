#!/usr/bin/env python3
"""Turn the logstash-patterns-core specs into normalised conformance cases for the date rules.

``vendored/reference/grok/spec/`` holds, per pattern family, the log lines that family is expected
to match: Apache and nginx access logs, syslog, firewall, mail, database and application logs. That
is the native habitat of every machine date format there is, and it is what the four date rules were
written for, so — as with the Recognizers-Text specs — the carrier sentence the identifier
extractors build is not used. Upstream's own log line is the fragment we scan, and the token is the
timestamp inside it.

The specs are Ruby, but nothing here parses Ruby: a spec's value is in its string literals, and a
string literal that holds a timestamp holds it verbatim. Literals are lifted with a lexer for
Ruby's two quoting forms, interpolated ones are dropped because their runtime value is not in the
file, and every timestamp shape in what is left is classified by format. The format is the scheme,
which is what makes the report say which date formats we match rather than which log products we
match.

Exclusions are large here and they are the finding rather than a way around it. Log timestamps are
mostly yearless (syslog), locale-specific (a German month inside an Apache log) or all-numeric, and
the standing policy in ``docs/Rules_And_Patterns.md`` — a date rule ships only when the match itself
fixes year, month and day — refuses all three by design. Each exclusion below names the limit it
rests on.

The script emits one JSON object per line on stdout, sorted by id, in the shape the Rust runner
reads. It runs inside the dev container and needs no network; the case file it writes is checked in.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys

SPECS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "vendored",
    "reference",
    "grok",
    "spec",
)

ORIGIN = "grok"

MONTHS = {
    name: number
    for number, name in enumerate(
        "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), start=1
    )
}

# The plausibility window both date rules apply, so a case whose year falls outside it is a case
# our rules refuse on purpose rather than one they miss.
PLAUSIBLE_YEARS = range(1400, 2201)

# --------------------------------------------------------------------------------------------
# The exclusion reasons, each quoting the limit in the tracked tree it rests on
# --------------------------------------------------------------------------------------------

WHOLE_DAY = (
    "a yearless timestamp: the standing date policy in docs/Rules_And_Patterns.md matches a date "
    "only when the match itself determines year, month and day, and names a syslog line's "
    "Mar  4 09:12:00 as the example it refuses"
)
NUMERIC_ORDER = (
    "an all-numeric date whose field order is not fixed by the format — 03/04/2021 can be read two "
    "ways, which is the ambiguity the date.iso8601 card names as the reason that rule matches the "
    "international order only; no rule matches this shape"
)
COMPACT_DIGITS = (
    "bare YYYYMMDD, which docs/Rules_And_Patterns.md excludes by name: eight adjacent digits with a "
    "valid calendar reading is the noisiest date shape there is and in an identifier-heavy corpus "
    "most of them are not dates"
)
NAMED_MONTH = (
    "a month spelled by name outside the two formats that carry one — the mail-header date and the "
    "bracketed log timestamp. src/rules/date_iso.rs states the limit: human-written dates need a "
    "month-name lexicon and an order-disambiguation policy and are a separate rule, which we do not "
    "ship"
)
LOCALE_MONTH = (
    "a month name from a locale other than English inside a log timestamp. The date.clf card matches "
    "the format as the Apache mod_log_config %t directive emits it, and the date.rfc2822 card the "
    "RFC 5322 grammar; both spell their months in English and neither claims a locale lexicon"
)
NO_ZONE_HEADER = (
    "a mail-header date with no zone. The date.rfc2822 card requires one — a header without a zone "
    "is rare enough not to be worth the ambiguity — so the format is matched only in the spelling "
    "the card claims"
)
COMMA_FRACTION = (
    "a fractional second written with a comma. ISO 8601 prefers the comma and RFC 3339 admits only "
    "the full stop; the date.iso8601 card names RFC 3339 as the profile it matches"
)
WEEK_ONLY = (
    "an ISO week with no weekday. It names a week rather than a day, and the standing date policy "
    "in docs/Rules_And_Patterns.md refuses a match that does not fix the whole day"
)

# --------------------------------------------------------------------------------------------
# The timestamp shapes, longest first. Every one of them appears in the spec corpus.
# --------------------------------------------------------------------------------------------

WEEKDAY = r"Mon|Tue|Wed|Thu|Fri|Sat|Sun"
MONTH_ABBR = r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
MONTH_WORD = r"[A-Z][a-zä-üÀ-ÿ]{2,11}\.?"

SHAPES = [
    # [04/Mar/2021:09:12:00 +0200] and its locale-month variants.
    ("clf", re.compile(r"\[(\d{1,2})/(%s)/(\d{4}):(\d{2}):(\d{2}):(\d{2}) ([+-]\d{4})\]" % MONTH_WORD)),
    # 2021-03-04T09:12:00.123+02:00, and every shorter ISO 8601 spelling down to the bare date.
    (
        "iso8601",
        re.compile(
            r"(\d{4})-(\d{2})-(\d{2})"
            r"(?:([T ])(\d{2}):(\d{2})(?::(\d{2}))?([.,]\d{1,9})?(Z|z|[+-]\d{2}:?\d{2})?)?"
        ),
    ),
    # 20150502T102019Z — the ISO 8601 basic spelling.
    ("iso8601_basic", re.compile(r"\b(\d{8})T(\d{6})(Z|[+-]\d{4})?")),
    # Tue, 04 Mar 2021 09:12:00 +0200 — the mail-header date, zone optional in the corpus.
    (
        "rfc2822",
        re.compile(
            r"(?:(%s), {1,2})?(\d{1,2}) (%s) (\d{4}) (\d{2}):(\d{2})(?::(\d{2}))?"
            r"(?: ([+-]\d{4}|UT|GMT|[ECMP][SD]T))?" % (WEEKDAY, MONTH_ABBR)
        ),
    ),
    # Wed Mar 04 09:12:00 2021 — the C library's asctime order, which no rule matches.
    (
        "ctime",
        re.compile(
            r"(?:%s) (?:%s) {1,2}(\d{1,2}) (\d{2}):(\d{2}):(\d{2})(?:\.\d+)? (\d{4})"
            % (WEEKDAY, MONTH_ABBR)
        ),
    ),
    # Mar  4 09:12:00 — the syslog stamp, with no year anywhere in it.
    ("syslog", re.compile(r"\b(%s) {1,2}(\d{1,2}) (\d{2}):(\d{2}):(\d{2})" % MONTH_ABBR)),
    # 04-Mar-2021 09:12:00 and 04/Mar/2021 09:12:00 without the brackets.
    (
        "named_month",
        re.compile(r"\b(\d{1,2})[-/](%s)[-/](\d{4})(?:[ :](\d{2}):(\d{2})(?::(\d{2}))?)?" % MONTH_ABBR),
    ),
    # 2021-W09-4 and 2021-W09.
    ("iso_week", re.compile(r"\b(\d{4})-?W(\d{2})(?:-?(\d))?\b")),
    # 03/04/2021, 2021/03/04, 04.03.2021 — every all-numeric order. A four-digit year is required in
    # one of the two end positions: without it the shape is indistinguishable from a version string
    # or the leading octets of an IP address, and a log corpus is full of both.
    (
        "numeric",
        re.compile(
            r"(?<![\d.])(?:\d{4}[/.]\d{1,2}[/.]\d{1,2}|\d{1,2}[/.]\d{1,2}[/.]\d{4})"
            r"(?:[ :]\d{2}:\d{2}(?::\d{2})?)?(?![\d.])"
        ),
    ),
    # 20210304 on its own.
    ("compact", re.compile(r"(?<![\d.-])(\d{8})(?![\d.-])")),
]

# A Ruby string literal in either quoting form. Interpolated ones are dropped by the caller: the
# value a spec computes at runtime is not in the file, and a half-substituted line is not a log line.
LITERAL = re.compile(r"\"((?:[^\"\\\n]|\\.)*)\"|'((?:[^'\\\n]|\\.)*)'")

ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "0": "\0"}


def unescape(raw: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == "\\" and index + 1 < len(raw):
            out.append(ESCAPES.get(raw[index + 1], raw[index + 1]))
            index += 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def literals(body: str):
    """Every non-interpolated string literal in a spec file, in source order."""
    for match in LITERAL.finditer(body):
        raw = match.group(1) if match.group(1) is not None else match.group(2)
        if "#{" in raw:
            continue
        text = unescape(raw)
        # A log line is what we are after; a pattern name, a field name or a bare word is not.
        if len(text) < 12 or len(text) > 2000 or not any(c.isdigit() for c in text):
            continue
        yield text


def offset_suffix(zone: str) -> str | None:
    """The one RFC 3339 spelling of a zone, matching what the rules normalise to."""
    named = {
        "UT": "Z",
        "GMT": "Z",
        "EST": "-05:00",
        "EDT": "-04:00",
        "CST": "-06:00",
        "CDT": "-05:00",
        "MST": "-07:00",
        "MDT": "-06:00",
        "PST": "-08:00",
        "PDT": "-07:00",
    }
    if zone in named:
        return named[zone]
    if zone.lower() == "z":
        return "Z"
    sign = zone[0]
    digits = "".join(c for c in zone[1:] if c.isdigit())
    if sign not in "+-" or len(digits) != 4:
        return None
    hours, minutes = int(digits[0:2]), int(digits[2:4])
    if hours > 18 or minutes > 59:
        return None
    if hours == 0 and minutes == 0:
        return "Z"
    return f"{sign}{hours:02d}:{minutes:02d}"


def civil(year: int, month: int, day: int) -> datetime.date | None:
    if year not in PLAUSIBLE_YEARS:
        return None
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def clock_ok(hour: int, minute: int, second: int) -> bool:
    return hour <= 23 and minute <= 59 and second <= 59


def classify(
    kind: str, match: re.Match, prefix: str = "log"
) -> tuple[str, str | None, str | None, str | None, str] | None:
    """(scheme, rule_id, expect_value, exclusion, token) for one timestamp occurrence.

    ``rule_id`` is None exactly when ``exclusion`` is set. ``expect_value`` is the RFC 3339 string
    the matching rule normalises to, computed from the token's own fields.
    """
    token = match.group(0)

    if kind == "clf":
        day, month_name, year, hour, minute, second, zone = match.groups()
        if month_name not in MONTHS:
            return (f"{prefix}.clf", None, None, LOCALE_MONTH, token)
        date = civil(int(year), MONTHS[month_name], int(day))
        suffix = offset_suffix(zone)
        if date is None or suffix is None or not clock_ok(int(hour), int(minute), int(second)):
            return (f"{prefix}.clf", None, None, LOCALE_MONTH, token)
        return (
            f"{prefix}.clf",
            "date.clf",
            f"{date.isoformat()}T{hour}:{minute}:{second}{suffix}",
            None,
            token,
        )

    if kind == "iso8601":
        year, month, day, sep, hour, minute, second, fraction, zone = match.groups()
        date = civil(int(year), int(month), int(day))
        if date is None:
            return (f"{prefix}.iso8601", None, None, NUMERIC_ORDER, token)
        if hour is None:
            return (f"{prefix}.iso8601", "date.iso8601", date.isoformat(), None, token)
        if not clock_ok(int(hour), int(minute), int(second or 0)):
            return (f"{prefix}.iso8601", None, None, NUMERIC_ORDER, token)
        if fraction is not None and fraction.startswith(","):
            return (f"{prefix}.iso8601", None, None, COMMA_FRACTION, token)
        suffix = "" if zone is None else offset_suffix(zone)
        if suffix is None:
            return (f"{prefix}.iso8601", None, None, NUMERIC_ORDER, token)
        if second is None:
            value = f"{date.isoformat()}T{hour}:{minute}{suffix}"
        else:
            value = f"{date.isoformat()}T{hour}:{minute}:{second}{suffix}"
        return (f"{prefix}.iso8601", "date.iso8601", value, None, token)

    if kind == "iso8601_basic":
        return (
            f"{prefix}.iso8601_basic",
            None,
            None,
            "the ISO 8601 basic spelling 20150502T102019Z. Its date half is the bare YYYYMMDD that "
            "docs/Rules_And_Patterns.md excludes by name, and date.iso8601 matches the extended "
            "spelling the RFC 3339 profile defines",
            match.group(0),
        )

    if kind == "rfc2822":
        weekday, day, month_name, year, hour, minute, second, zone = match.groups()
        date = civil(int(year), MONTHS[month_name], int(day))
        if date is None:
            return (f"{prefix}.rfc2822", None, None, NAMED_MONTH, token)
        if weekday is None:
            return (
                f"{prefix}.rfc2822",
                None,
                None,
                "a date-time with a named month and no day of the week. The date.rfc2822 card makes "
                "the day of the week required — it is a free consistency check against the rest of "
                "the date, and it is most of what separates the format from a bare 04 Mar 2021",
                token,
            )
        if zone is None:
            return (f"{prefix}.rfc2822", None, None, NO_ZONE_HEADER, token)
        suffix = offset_suffix(zone)
        if suffix is None or not clock_ok(int(hour), int(minute), int(second or 0)):
            return (f"{prefix}.rfc2822", None, None, NAMED_MONTH, token)
        if date.strftime("%a") != weekday:
            # Upstream's own line, with a weekday that contradicts its date: the rule refuses it and
            # the case scores that refusal rather than being excluded.
            return (f"{prefix}.rfc2822", "date.rfc2822", None, None, token)
        if second is None:
            value = f"{date.isoformat()}T{hour}:{minute}{suffix}"
        else:
            value = f"{date.isoformat()}T{hour}:{minute}:{second}{suffix}"
        return (f"{prefix}.rfc2822", "date.rfc2822", value, None, token)

    if kind == "iso_week":
        year, week, weekday = match.groups()
        if weekday is None:
            return (f"{prefix}.iso_week", None, None, WEEK_ONLY, token)
        if int(year) not in PLAUSIBLE_YEARS or not 1 <= int(week) <= 53 or weekday == "0":
            return (f"{prefix}.iso_week", None, None, WEEK_ONLY, token)
        try:
            date = datetime.date.fromisocalendar(int(year), int(week), int(weekday))
        except ValueError:
            return (f"{prefix}.iso_week", None, None, WEEK_ONLY, token)
        return (f"{prefix}.iso_week", "date.iso_week", date.isoformat(), None, token)

    # An all-numeric run and an eight-digit run are only dates if they read as one. A log corpus is
    # full of version strings, process ids and byte counts of exactly those shapes, and counting
    # them as excluded date cases would inflate the exclusion ledger with things that are not dates.
    if kind == "numeric" and not numeric_reads_as_a_date(token):
        return None
    if kind == "compact":
        digits = match.group(1)
        if civil(int(digits[0:4]), int(digits[4:6]), int(digits[6:8])) is None:
            return None

    reasons = {
        "ctime": NAMED_MONTH,
        "syslog": WHOLE_DAY,
        "named_month": NAMED_MONTH,
        "numeric": NUMERIC_ORDER,
        "compact": COMPACT_DIGITS,
    }
    return (f"{prefix}.{kind}", None, None, reasons[kind], token)


def numeric_reads_as_a_date(token: str) -> bool:
    """True when the three numeric fields are a real day under either field order."""
    fields = re.split(r"[/.]", re.match(r"[\d/.]+", token).group(0))
    if len(fields) != 3:
        return False
    first, middle, last = (int(field) for field in fields)
    if len(fields[0]) == 4:
        return civil(first, middle, last) is not None
    return civil(last, middle, first) is not None or civil(last, first, middle) is not None


def occurrences(text: str):
    """Every timestamp in a log line, longest shape first, none overlapping another."""
    found = []
    for kind, pattern in SHAPES:
        for match in pattern.finditer(text):
            found.append((match.start(), -(match.end() - match.start()), kind, match))
    found.sort(key=lambda item: (item[0], item[1]))
    taken: list[tuple[int, int]] = []
    for start, negative_length, kind, match in found:
        end = start - negative_length
        if any(start < other_end and end > other_start for other_start, other_end in taken):
            continue
        taken.append((start, end))
        yield kind, match


def main() -> None:
    cases = []
    seen = set()
    counters: dict[str, int] = {}
    for name in sorted(os.listdir(SPECS)):
        if not name.endswith("_spec.rb"):
            continue
        with open(os.path.join(SPECS, name), encoding="utf-8") as handle:
            body = handle.read()
        for text in literals(body):
            for kind, match in occurrences(text):
                classified = classify(kind, match)
                if classified is None:
                    continue
                scheme, rule_id, expect_value, exclusion, token = classified
                start = match.start() + text[match.start() :].index(token)
                end = start + len(token)
                key = (text, start, end)
                if key in seen:
                    continue
                seen.add(key)
                counters[scheme] = counters.get(scheme, 0) + 1
                cases.append(
                    {
                        "id": f"{ORIGIN}:{scheme}:{counters[scheme]:04d}",
                        "origin": ORIGIN,
                        "source": f"spec/{name}",
                        "scheme": scheme,
                        "token": token,
                        "text": text,
                        "token_start": len(text[:start].encode("utf-8")),
                        "token_end": len(text[:end].encode("utf-8")),
                        "cue": None,
                        "valid": True,
                        "rule_id": rule_id,
                        "entity_type": None if exclusion else "date",
                        "expect_value": expect_value,
                        "exclusion": exclusion,
                    }
                )

    cases.sort(key=lambda case: case["id"])
    for case in cases:
        print(json.dumps(case, sort_keys=True, ensure_ascii=False))

    scored = sum(1 for case in cases if case["exclusion"] is None)
    print(
        f"{len(cases)} cases, {scored} scored, {len(cases) - scored} excluded",
        file=sys.stderr,
    )
    for scheme, count in sorted(counters.items()):
        print(f"  {scheme}: {count}", file=sys.stderr)


if __name__ == "__main__":
    main()
