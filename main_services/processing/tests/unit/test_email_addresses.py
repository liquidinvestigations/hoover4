"""Participant-header parsing.

Every case here is one the old `"; ".join(msg.get(hdr))` got wrong, and none of them is
visible from the outside: a dropped Cc: just means one fewer name in the sender/receiver
facet, which nobody diffs.
"""

from tasks.P3_parse_files.parse_email import ADDRESS_ROLES, extract_email_addresses


def addresses(result, role=None):
    return [a for r, a, _ in result if role is None or r == role]


def names(result, role=None):
    return [n for r, _, n in result if role is None or r == role]


def test_the_ordinary_case():
    result = extract_email_addresses({
        "from": ["Terry Kafka <t.kafka@blakelaw.net>"],
        "to": ["a@example.com, B User <b@example.com>"],
    })
    assert result == [
        ("from", "t.kafka@blakelaw.net", "Terry Kafka"),
        ("to", "a@example.com", ""),
        ("to", "b@example.com", "B User"),
    ]


def test_addresses_are_lower_cased_but_display_names_are_not():
    """`E.Brandt@BlakeLaw.net` and `e.brandt@blakelaw.net` must be ONE facet value."""
    result = extract_email_addresses({"from": ["E.Brandt <E.Brandt@BlakeLaw.NET>"]})
    assert result == [("from", "e.brandt@blakelaw.net", "E.Brandt")]


def test_a_quoted_display_name_containing_a_comma_is_not_split():
    """The comma inside the quotes is not a separator — a naive split makes two
    recipients out of one, and neither of them has a valid address."""
    result = extract_email_addresses({
        "to": ['"Doe, John" <john@example.com>, jane@example.com'],
    })
    assert addresses(result, "to") == ["john@example.com", "jane@example.com"]
    assert names(result, "to") == ["Doe, John", ""]


def test_a_folded_header_is_one_list():
    result = extract_email_addresses({
        "to": ["a@example.com,\r\n b@example.com,\r\n\tc@example.com"],
    })
    assert addresses(result, "to") == [
        "a@example.com", "b@example.com", "c@example.com",
    ]


def test_a_repeated_header_contributes_every_copy():
    """`msg.get('cc')` returns only the FIRST Cc:, and mail in the wild repeats it."""
    result = extract_email_addresses({"cc": ["a@example.com", "b@example.com"]})
    assert addresses(result, "cc") == ["a@example.com", "b@example.com"]


def test_group_syntax_contributes_its_members_not_its_label():
    result = extract_email_addresses({
        "to": ["Team: alice@example.com, bob@example.com;"],
    })
    assert addresses(result, "to") == ["alice@example.com", "bob@example.com"]


def test_an_empty_group_yields_nothing():
    result = extract_email_addresses({"to": ["undisclosed-recipients:;"]})
    assert result == []


def test_a_display_name_with_no_address_is_not_a_participant():
    """`getaddresses(["Just A Name"])` hands back the bare atom `Just` as an *address*.

    Left alone it becomes a sender facet value that looks like a person and matches
    nothing, so anything without a real `local@domain` is dropped.
    """
    assert extract_email_addresses({"to": ["Just A Name"]}) == []
    assert extract_email_addresses({"to": ["mailer-daemon"]}) == []
    assert extract_email_addresses({"to": ["@example.com"]}) == []
    assert extract_email_addresses({"to": ["a@b@example.com"]}) == []


def test_the_same_address_in_two_roles_is_two_rows():
    """Someone who is both From and Cc is genuinely both, and the schema keys on
    (role, address) so the viewer can show them under each heading."""
    result = extract_email_addresses({
        "from": ["a@example.com"],
        "cc": ["a@example.com"],
    })
    assert result == [("from", "a@example.com", ""), ("cc", "a@example.com", "")]


def test_the_same_address_twice_in_one_role_is_deduplicated_first_name_wins():
    result = extract_email_addresses({
        "to": ["A User <a@example.com>, a@example.com"],
    })
    assert result == [("to", "a@example.com", "A User")]


def test_missing_and_empty_headers_are_skipped():
    assert extract_email_addresses({}) == []
    assert extract_email_addresses({"from": [], "to": [None, ""]}) == []


def test_roles_come_out_in_header_order():
    result = extract_email_addresses({
        "bcc": ["d@example.com"],
        "to": ["b@example.com"],
        "from": ["a@example.com"],
        "cc": ["c@example.com"],
    })
    assert [r for r, _, _ in result] == list(ADDRESS_ROLES)
