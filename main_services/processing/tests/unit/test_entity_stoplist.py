"""Canonical cases for the entity stop-list, and the parity check against its Rust twin.

These are the values that made the Entities facet unusable on a mail corpus, taken from
`entity_hit` as stored, and the values next to them that must survive. The Rust twin
(`website/common/src/entity_stoplist.rs`) mirrors this list value for value: a case added
here belongs there too, or the two sides start disagreeing about what a user sees.

`test_the_two_implementations_have_not_drifted` is what enforces that. The two modules
cannot share a file -- `hoover4-worker` mounts only `main_services/processing` and
`hoover4-website` mounts only `website/`, so no path is visible to both test runs -- so
instead each side hashes its own copy of the rule data and the cases below into
`STOPLIST_PARITY_DIGEST`, which is the same literal on both sides. Changing a header name,
a threshold or a case on one side alone fails that side immediately; updating the digest
to match then fails the *other* side until the same change is made there. The digest is
therefore not a reminder to keep the lists in step, it is the thing that makes landing
them out of step impossible.
"""

import pytest

from tasks import entity_stoplist
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
    # Letter-spaced runs too short for the token count.
    "∆ Y",
    "U I",
    "R X X",
    "FONT SIZE=1>Updated",
    "-- ",
    "G",
    "I",
]

# A reply block's header keyword glued to the name printed above it.
REPLY_BLOCK_JUNK = [
    "Peter Aldhous Subject",
    "ECT@ENRON Subject",
    "Enron@Enron Subject",
    "David Subject",
    "Eric From",
    "Eric Cc",
    "Larry Sent",
    "Kay Sent: Monday",
    "Ted -----Original Message----- From",
    # `To` and `Date` are ordinary words, so they count only with the header's colon.
    "Sara Shackleton To:",
    "Steven Kean Date:",
    # A doubled colon is still one header keyword. Pinned because this is where the two
    # implementations drifted apart once already.
    "Kay Sent:: Monday",
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
    # A header keyword in the middle of a name is prose, and the first token is exempt
    # entirely: these are the false positives the positional rules avoid.
    "Mission To Mars",
    "Ode To Joy",
    "Subject Matter Experts",
    "From Dusk Till Dawn",
    "Dow Jones & Company",
    "U.S.",
    "3M",
    "eBay",
    "李",
    # A bare trailing `Date` or `To` is ordinary English, not a reply block.
    "Blind Date",
    "Save The Date",
    "Tokyo To",
    "A To Z",
]

DEBRIS = HEADER_JUNK + CALENDAR_AND_PROTOCOL_JUNK + ENCODING_JUNK + REPLY_BLOCK_JUNK


@pytest.mark.parametrize("value", DEBRIS)
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


def test_letter_spacing_is_stopped_but_initials_next_to_a_name_are_not():
    """Lowering the single-character threshold takes `J F Kennedy` with it. What separates
    the two is that letter-spacing leaves nothing but single characters."""
    assert is_stopped_entity("U I") and is_stopped_entity("∆ Y")
    assert not is_stopped_entity("J F Kennedy") and not is_stopped_entity("3M")


def test_a_header_keyword_is_debris_at_the_end_and_prose_in_the_middle():
    assert is_stopped_entity("Eric Cc") and is_stopped_entity("Peter Aldhous Subject")
    assert not is_stopped_entity("Mission To Mars")
    assert not is_stopped_entity("Subject Matter Experts")


def test_filter_keeps_order_and_duplicates():
    values = ["Enron", "Message-ID", "Enron", "Mon", "Kay Mann"]
    assert filter_entity_values(values) == ["Enron", "Enron", "Kay Mann"]


def test_a_header_keyword_that_is_also_an_english_word_needs_its_colon():
    """The whole point of the two-tier keyword set.

    `Cc` and `Subject` end nothing but a reply block, so a bare one is enough. `Date` and
    `To` end real names, so they are debris only when the header's colon is still there --
    and the value that is genuinely a header line is caught by the whole-value rule long
    before this one is reached.
    """
    assert not is_stopped_entity("Blind Date") and not is_stopped_entity("Tokyo To")
    assert is_stopped_entity("Sara Shackleton To:") and is_stopped_entity("Steven Kean Date:")
    assert is_stopped_entity("Date: Mon") and is_stopped_entity("To: Vince J Kaminski")
    assert is_stopped_entity("X-To") and is_stopped_entity("X-cc")


def test_a_paragraph_is_not_an_entity():
    assert is_stopped_entity(" ".join(["word"] * 13))
    assert not is_stopped_entity(" ".join(["word"] * 12))
    assert is_stopped_entity("x" * 201)


# --------------------------------------------------------------------------------------
# Parity with the Rust twin.
# --------------------------------------------------------------------------------------

#: FNV-1a 64 of `canonical_stoplist_rendering()`. The identical literal lives in
#: `website/common/src/entity_stoplist.rs`; when this test tells you the digest changed,
#: make the same edit there and set the new digest in BOTH files.
STOPLIST_PARITY_DIGEST = "f4d99d806844b2eb"


def canonical_stoplist_rendering() -> str:
    """Every value the two implementations must agree on, in one deterministic string.

    Sorted, because the two languages spell their collections differently and only the
    content is the contract. Byte order and code-point order coincide in UTF-8, so
    Python's `sorted` and Rust's `sort` produce the same sequence.
    """
    sections = [
        ("mail_header_names", sorted(entity_stoplist.MAIL_HEADER_NAMES)),
        ("protocol_tokens", sorted(entity_stoplist.PROTOCOL_TOKENS)),
        ("day_and_month_tokens", sorted(entity_stoplist.DAY_AND_MONTH_TOKENS)),
        ("reply_block_headers", sorted(entity_stoplist._REPLY_BLOCK_HEADERS)),
        (
            "colon_only_reply_block_headers",
            sorted(entity_stoplist._COLON_ONLY_REPLY_BLOCK_HEADERS),
        ),
        ("original_message_marker", [entity_stoplist._ORIGINAL_MESSAGE_MARKER]),
        (
            "limits",
            [
                f"blob_min_case_switches={entity_stoplist._BLOB_MIN_CASE_SWITCHES}",
                f"blob_min_chars={entity_stoplist._BLOB_MIN_CHARS}",
                f"max_chars={entity_stoplist._MAX_CHARS}",
                f"max_single_char_tokens={entity_stoplist._MAX_SINGLE_CHAR_TOKENS}",
                f"max_tokens={entity_stoplist._MAX_TOKENS}",
            ],
        ),
        ("debris", sorted(DEBRIS)),
        ("keep", sorted(KEEP)),
    ]
    lines = []
    for name, items in sections:
        lines.append(f"[{name}]")
        lines.extend(items)
    return "".join(f"{line}\n" for line in lines)


def fnv1a_64(text: str) -> str:
    """FNV-1a over UTF-8. Chosen because it is ten lines in both languages and needs no
    dependency on either side; this is a change detector, not a security boundary."""
    digest = 0xCBF29CE484222325
    for byte in text.encode("utf-8"):
        digest = ((digest ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{digest:016x}"


def test_the_two_implementations_have_not_drifted():
    """A rule changed here and not in the Rust twin makes the facet and the document
    panel disagree about the same value, which is invisible until a user notices."""
    digest = fnv1a_64(canonical_stoplist_rendering())
    assert digest == STOPLIST_PARITY_DIGEST, (
        f"the stop-list data changed: digest is {digest}, not {STOPLIST_PARITY_DIGEST}. "
        "Make the same change in website/common/src/entity_stoplist.rs and set "
        f"STOPLIST_PARITY_DIGEST to {digest} in both files."
    )
