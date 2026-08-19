"""Reading a ClickHouse ``Enum8`` back: names, ordinals, and the comparison that lies.

Pure — no stack. The failure this pins does not raise and does not log. An arrow read of
an ``Enum8`` column yields the ORDINAL, so ``row['role'] == 'from'`` is ``1 == 'from'``,
which is False for every row ever read. It cost the corpus its entire sender field
(``email_from`` empty on 2.28 M documents while ``email_to`` held sender, recipient, cc
and bcc merged together) and, earlier and separately, made every container in the VFS
tree look like a directory.

So: one normaliser, and a grep that fails the suite the third time somebody writes the
comparison by hand.
"""

import pathlib
import re

import pytest

from database.enum_wire import (
    KIND_DEFAULT,
    KIND_ORDINALS,
    ROLE_DEFAULT,
    ROLE_ORDINALS,
    enum_from_wire,
)

P6 = pathlib.Path(__file__).resolve().parents[2] / "tasks" / "P6_index_data"


@pytest.mark.parametrize("wire,expected", [
    # Ordinals, which is what an arrow read actually delivers.
    (1, "from"), (2, "to"), (3, "cc"), (4, "bcc"),
    # Names, which is what the schema shows and what an insert takes.
    ("from", "from"), ("to", "to"), ("cc", "cc"), ("bcc", "bcc"),
    # Unknown, of either shape: the documented default, and it is never `from`.
    (0, ROLE_DEFAULT), (99, ROLE_DEFAULT), ("sender", ROLE_DEFAULT), (None, ROLE_DEFAULT),
])
def test_enum_from_wire_role(wire, expected):
    assert enum_from_wire(wire, ROLE_ORDINALS, ROLE_DEFAULT) == expected


@pytest.mark.parametrize("wire,expected", [
    (0, "dir"), (1, "file"), (2, "container"),
    ("dir", "dir"), ("file", "file"), ("container", "container"),
    (99, KIND_DEFAULT), ("nonsense", KIND_DEFAULT), (None, KIND_DEFAULT),
])
def test_enum_from_wire_kind(wire, expected):
    assert enum_from_wire(wire, KIND_ORDINALS, KIND_DEFAULT) == expected


def test_an_unknown_role_is_never_the_sender():
    """The default is a recipient on purpose: a wrong recipient widens a match, a wrong
    sender is a false claim about who wrote the message."""
    assert ROLE_DEFAULT == "to"
    assert enum_from_wire(7, ROLE_ORDINALS, ROLE_DEFAULT) != "from"


#: A comparison of a row's enum column against a bare string literal, the exact shape
#: that silently never matches. `role == 'from'`, `node["kind"] != "container"`.
BARE_COMPARISON = re.compile(
    r"""\[\s*['"](?:role|kind)['"]\s*\]\s*(?:==|!=)\s*['"]"""
)


def test_no_enum_column_is_compared_to_a_string_literal():
    """The regression test for the whole module.

    Every read of `role` or `kind` in the indexer must go through `enum_from_wire` (or a
    `toString()` in the SQL and then through it anyway). A direct comparison compiles,
    runs, matches nothing and reports success, so nothing but a grep catches it.
    """
    offenders = []
    for source in sorted(P6.rglob("*.py")):
        for number, line in enumerate(source.read_text().splitlines(), start=1):
            if BARE_COMPARISON.search(line):
                offenders.append(f"{source.name}:{number}: {line.strip()}")
    assert not offenders, (
        "an Enum8 column is compared to a string literal; an arrow read gives the "
        "ordinal, so this is always False. Use enum_from_wire:\n" + "\n".join(offenders)
    )


def test_the_grep_catches_the_line_it_was_written_for():
    """The bug as it was actually written, so the guard above cannot rot into a regex
    that matches nothing."""
    assert BARE_COMPARISON.search("bucket = from_by_hash if row['role'] == 'from' else to")
    assert BARE_COMPARISON.search('if node["kind"] != "container":')
    # And what the fix looks like, which must NOT trip it.
    assert not BARE_COMPARISON.search(
        "role = enum_from_wire(row['role'], ROLE_ORDINALS, ROLE_DEFAULT)"
    )
    assert not BARE_COMPARISON.search("if kind_from_wire(raw_kind) != KIND_CONTAINER:")
