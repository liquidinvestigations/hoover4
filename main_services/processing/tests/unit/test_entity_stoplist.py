"""Canonical cases for the entity stop-list.

These are the values that made the Entities facet unusable on a mail corpus, taken from
`entity_hit` as stored, and the values next to them that must survive. The Rust twin
(`website/common/src/entity_stoplist.rs`) mirrors this list value for value: a case added
here belongs there too, or the two sides start disagreeing about what a user sees.
"""

import pytest

from tasks.entity_stoplist import filter_entity_values, is_stopped_entity

# Header names, alone and as the head of a quoted header line.
HEADER_JUNK = [
    "Content-Transfer-Encoding",
    "Message-ID",
    "Mime-Version",
    "MIME-Version",
    "Content-Type",
    "Subject",
    "Subject:",
    "Cc",
    "Date: Mon",
    "Sent: Tuesday",
    "Thread-Topic: Invitation Fontys Open Day",
    "X-Folder",
    "X-Origin",
    "X-FileName",
    "X-To",
    "X-From",
    "X-YMailISG",
    "Authentication-Results",
]

# Days, months, protocol words.
CALENDAR_AND_PROTOCOL_JUNK = [
    "Mon", "Fri", "Thursday", "thursday", "Tuesday",
    "Jan", "May", "September",
    "ESMTP", "SMTP", "quoted-printable", "base64", "7bit", "text/plain",
]

# Encoding and layout debris.
ENCODING_JUNK = [
    "of=",
    "th=",
    "RGVhciBzdHVkZW50LA0KDQpMaWtlIGxhc3QgTm92ZW1iZXI",
    "CH0D30CYqUPrSizQBUYtBpBcLyCczRvQU7JHvAv5endkFKBrVHQHS0GIH9Hz",
    "mZ2kI.zNjgnAdLPRgf0O6aIHpNgu6D76dg_e18XcXsbE2TMgD2OSSf6p5JlW",
    "F O N T Y S",
    "L  B U S I N E S S  S C H O O L",
    "FONT SIZE=1>Updated",
    "-- ",
    "G",
    "I",
]

# Everything a user might legitimately want to filter on. `Mr`, `Inc` and `NA` are
# debatable and are deliberately kept: a stop-list that guesses at what is uninteresting
# removes real names, and one that removes only what cannot be an entity does not.
KEEP = [
    "Enron",
    "Enron Corp",
    "Jeff Dasovich",
    "Vince J Kaminski",
    "PG&E",
    "S&P",
    "Sun Microsystems",
    "May Chen",
    "June Smith",
    "March of Dimes",
    "Mr",
    "Inc",
    "NA",
    "Rights Reserved",
    "Jeff.Dasovich@enron.com",
    "ENRON_DEVELOPMENT@ENRON_DEVELOPMENT",
    "http://www.fontys.nl/fihe/default.asp",
    "Reuters English News Service",
    "New York",
    "J F Kennedy",
    "InternationalBusinessMachinesCorporation",
    "Dow Jones & Company",
    "U.S.",
    "3M",
    "eBay",
    "李",
]


@pytest.mark.parametrize("value", HEADER_JUNK + CALENDAR_AND_PROTOCOL_JUNK + ENCODING_JUNK)
def test_debris_is_stopped(value):
    assert is_stopped_entity(value), f"{value!r} should not be an entity"


@pytest.mark.parametrize("value", KEEP)
def test_real_entities_survive(value):
    assert not is_stopped_entity(value), f"{value!r} must stay searchable"


def test_the_rule_matches_the_whole_value_never_a_substring():
    """The safety argument for dropping bare day and month tokens."""
    assert is_stopped_entity("Sun") and not is_stopped_entity("Sun Microsystems")
    assert is_stopped_entity("May") and not is_stopped_entity("May Chen")
    assert is_stopped_entity("Subject") and not is_stopped_entity("Subject Matter Experts")


def test_filter_keeps_order_and_duplicates():
    values = ["Enron", "Message-ID", "Enron", "Mon", "Kay Mann"]
    assert filter_entity_values(values) == ["Enron", "Enron", "Kay Mann"]


def test_a_paragraph_is_not_an_entity():
    assert is_stopped_entity(" ".join(["word"] * 13))
    assert not is_stopped_entity(" ".join(["word"] * 12))
    assert is_stopped_entity("x" * 201)
