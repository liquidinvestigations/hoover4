#!/usr/bin/env python3
"""Turn the hoover mail slice into conformance cases for the header rules.

``vendored/reference/hoover-mail/`` is real mail: mbox archives, `.eml` files and Apple Mail
`.emlx` messages, with the message ids, dates, addresses and Received chains that were actually
written into them. Every other origin here puts a token into a sentence somebody wrote for a test.
**This one is the sentence**, and that is why it is here. The fragment scanned is the header
field, folding line breaks and all, which is the only place the field-scoped cue window and the
header-label test are exercised by the shape they exist for.

Where the labels come from, since no upstream assertion exists in a mailbox: RFC 5322 says what a
field means. A `Message-ID:` field holds a message id, a `Date:` field holds a date-time, an address
field holds addresses, and a `Received:` field's bracketed literal is an address literal under RFC
5321. The fields are parsed with the standard library's own mail parser and, for addresses, its
address parser, never with a pattern of ours, because a pattern of ours labelling the cases it is
then scored against measures nothing.

Three things the material decides:

* An `.emlx` file begins with the byte count of the message that follows it and ends with a
  property list, so the message is a slice rather than the file.
* A mailing-list archive obfuscates addresses as ``name at example.com``. There is no address in
  that text, so those fields yield no case rather than a mangled one.
* A message id in a `From:` line would have the same shape as an address. Cases are taken from the
  field that defines the meaning, so the address fields yield addresses and the id fields yield ids,
  and where the two rules disagree about one field the run says so.

The script emits one JSON object per line on stdout, sorted by id, in the shape the Rust runner
reads. It runs inside the dev container and needs no network; the case file it writes is checked in.
"""

from __future__ import annotations

import datetime
import email
import email.utils
import ipaddress
import json
import mailbox
import os
import re
import sys

MAIL = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "vendored",
    "reference",
    "hoover-mail",
)

ORIGIN = "hoover-mail"

MESSAGE_ID_FIELDS = ("message-id", "in-reply-to", "references", "resent-message-id")
ADDRESS_FIELDS = (
    "from",
    "sender",
    "reply-to",
    "to",
    "cc",
    "bcc",
    "resent-from",
    "resent-to",
    "return-path",
    "delivered-to",
    "x-original-to",
    "errors-to",
)

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
# The zone abbreviations the obsolete grammar allows and the rule reads, with their offsets.
NAMED_ZONES = {
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

# The date-time the rule claims, in the shape its card names: a weekday, a day, a month name, a
# four-digit year, a clock and a zone.
MAIL_DATE = re.compile(
    r"(?P<weekday>Mon|Tue|Wed|Thu|Fri|Sat|Sun), {1,2}(?P<day>\d{1,2}) "
    r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
    r"(?P<year>\d{4}) (?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))? "
    r"(?P<zone>[+\-]\d{4}|UT|GMT|EST|EDT|CST|CDT|MST|MDT|PST|PDT)"
)

# The Received field has its own grammar, not the address grammar: RFC 5321 §4.4 gives it a `for`
# clause holding the path the message was accepted for. This finds the clause; the path inside it is
# handed to the address parser like any other.
FOR_CLAUSE = re.compile(r"\bfor\s+(<[^<>]*>)")

# The address literal of RFC 5321, which is how a Received field names the host it took the message
# from. The brackets are the field's, and what is inside them is handed to a parser rather than
# matched: `ipaddress` decides whether it is an address, not this expression.
BRACKETED = re.compile(r"\[([^\[\]\s]+)\]")

# --------------------------------------------------------------------------------------------
# The exclusion reasons, each quoting the limit in the tracked tree it rests on
# --------------------------------------------------------------------------------------------

NO_WEEKDAY = (
    "a date-time written without its day of the week. The date.rfc2822 card names the weekday form "
    "and checks the weekday against the calendar date, which is most of what separates a mail "
    "header from a bare day and month in running text"
)
UNREAD_ZONE = (
    "a zone the card does not admit: a numeric offset, or one of the North American abbreviations "
    "the obsolete grammar allows, and nothing else"
)
WEEKDAY_MISMATCH = (
    "a date-time whose day of the week contradicts its calendar date. The date.rfc2822 card checks "
    "the two against each other by name, because a mangled or fabricated header rarely agrees with "
    "itself, and the rule reports nothing rather than choosing which half to trust"
)


def messages():
    """Every message in the slice, with the file it came from.

    Three containers, three ways in: an mbox holds many messages and the standard library splits
    it; an `.emlx` declares the byte length of its message on its first line and appends a property
    list after it; an `.eml` is one message, possibly behind a byte-order mark.
    """
    for directory, _, names in os.walk(MAIL):
        for name in sorted(names):
            path = os.path.join(directory, name)
            relative = os.path.relpath(path, MAIL)
            if name == ".upstream":
                continue
            if os.path.basename(directory) == "mbox":
                for index, message in enumerate(mailbox.mbox(path), start=1):
                    yield f"{relative}#{index}", message
                continue
            with open(path, "rb") as handle:
                data = handle.read()
            if name.endswith(".emlx"):
                length, rest = data.split(b"\n", 1)
                data = rest[: int(length.strip())]
            yield relative, email.message_from_bytes(data.lstrip(b"\xef\xbb\xbf"))


def fields(message):
    """Each header field as it stands in the message: its name, its raw value, and the fragment.

    The fragment is the field itself (the name, the colon and the value with its folding line
    breaks), because that is what the rules are given in production and what the cue window is
    scoped to.
    """
    for name, value in message.items():
        if not isinstance(value, str):
            continue
        yield name, value, f"{name}: {value}"


def rfc3339_of(match: re.Match) -> str:
    """The instant the rule reports for a mail date, in its spelling.

    The civil time is kept and the offset written beside it; converting to UTC would report an
    instant the header does not name. `+0000`, `UT` and `GMT` are the one exception, because they
    are the offset RFC 3339 spells `Z`.
    """
    zone = match.group("zone")
    if zone in NAMED_ZONES:
        offset = NAMED_ZONES[zone]
    else:
        hours, minutes = int(zone[1:3]), int(zone[3:5])
        offset = "Z" if hours == 0 and minutes == 0 else f"{zone[0]}{hours:02}:{minutes:02}"
    date = "{:04}-{:02}-{:02}".format(
        int(match.group("year")),
        MONTHS.index(match.group("month")) + 1,
        int(match.group("day")),
    )
    clock = f"{match.group('hour')}:{match.group('minute')}"
    if match.group("second") is not None:
        clock = f"{clock}:{match.group('second')}"
    return f"{date}T{clock}{offset}"


def date_case(value: str):
    """(token, expected value, exclusion) for a Date field, or `None` when it holds no date."""
    match = MAIL_DATE.search(value)
    if match is None:
        if re.search(r"\d{1,2} (?:%s) \d{4}" % "|".join(MONTHS), value):
            return value.strip(), None, NO_WEEKDAY
        if re.search(r"(?:%s), " % "|".join(WEEKDAYS), value):
            return value.strip(), None, UNREAD_ZONE
        return None
    weekday = datetime.date(
        int(match.group("year")),
        MONTHS.index(match.group("month")) + 1,
        int(match.group("day")),
    ).strftime("%a")
    if weekday != match.group("weekday"):
        return match.group(), None, WEEKDAY_MISMATCH
    return match.group(), rfc3339_of(match), None


def addresses_in(value: str):
    """The addr-specs of an address field, as the standard library's address parser reads them."""
    for _, address in email.utils.getaddresses([value]):
        # A mailing-list archive writes `name at example.com`, which holds no address at all.
        if address.count("@") == 1 and " " not in address:
            yield address


def literals_in(value: str):
    """The bracketed address literals of a Received field that really are addresses."""
    for match in BRACKETED.finditer(value):
        try:
            parsed = ipaddress.ip_address(match.group(1))
        except ValueError:
            continue
        yield match.group(1), str(parsed)


def main() -> None:
    cases = []
    counters: dict[str, int] = {}

    def add(scheme, source, fragment, token, rule_id, entity_type, expect_value, exclusion=None):
        start = fragment.find(token)
        if start < 0:
            return
        counters[scheme] = counters.get(scheme, 0) + 1
        cases.append(
            {
                "id": f"{ORIGIN}:{scheme}:{counters[scheme]:04d}",
                "origin": ORIGIN,
                "source": source,
                "scheme": scheme,
                "token": token,
                "text": fragment,
                "token_start": len(fragment[:start].encode("utf-8")),
                "token_end": len(fragment[:start].encode("utf-8"))
                + len(token.encode("utf-8")),
                # The header name is the rule's own documented label rather than a cue word placed
                # in a carrier, so there is no cue to record: the fragment is the real thing.
                "cue": None,
                "valid": True,
                "rule_id": None if exclusion else rule_id,
                "entity_type": None if exclusion else entity_type,
                "expect_value": None if exclusion else expect_value,
                "exclusion": exclusion,
            }
        )

    for source, message in messages():
        for name, value, fragment in fields(message):
            lowered = name.lower()
            if lowered in MESSAGE_ID_FIELDS:
                for token in value.split():
                    if token.startswith("<") and token.endswith(">") and "@" in token:
                        add(
                            "message_id",
                            source,
                            fragment,
                            token,
                            "message.rfc5322",
                            "message_id",
                            token[1:-1],
                        )
            elif lowered == "date":
                found = date_case(value)
                if found is not None:
                    token, expect_value, exclusion = found
                    add(
                        "date",
                        source,
                        fragment,
                        token,
                        "date.rfc2822",
                        "date",
                        expect_value,
                        exclusion,
                    )
            elif lowered in ADDRESS_FIELDS:
                for address in addresses_in(value):
                    local, _, domain = address.rpartition("@")
                    add(
                        "address",
                        source,
                        fragment,
                        address,
                        "email.basic",
                        "email",
                        f"{local}@{domain.lower()}",
                    )
            elif lowered == "received":
                clause = FOR_CLAUSE.search(value)
                for address in addresses_in(clause.group(1) if clause else ""):
                    local, _, domain = address.rpartition("@")
                    add(
                        "received.address",
                        source,
                        fragment,
                        address,
                        "email.basic",
                        "email",
                        f"{local}@{domain.lower()}",
                    )
                for token, canonical in literals_in(value):
                    add(
                        "received.ip",
                        source,
                        fragment,
                        token,
                        "network.ip",
                        "network",
                        canonical,
                    )

    cases.sort(key=lambda item: item["id"])
    for item in cases:
        print(json.dumps(item, sort_keys=True, ensure_ascii=False))

    scored = sum(1 for item in cases if item["exclusion"] is None)
    print(
        f"{len(cases)} cases, {scored} scored, {len(cases) - scored} excluded",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
