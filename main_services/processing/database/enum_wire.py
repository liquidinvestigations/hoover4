"""Reading a ClickHouse ``Enum8`` column back without silently getting an integer.

ClickHouse accepts the NAME on insert (``'from'``, ``'container'``) and the schema shows
names, so the natural thing to write is ``row['role'] == 'from'``. Reading the column
back through ``client.query_arrow(...).to_pylist()`` yields the ORDINAL — an ``int8``.
``1 == 'from'`` is False, it does not raise, and the feature quietly does nothing: the
symptom is an empty column or a filter that matches nothing, days later, with no error
anywhere to point at it.

This has now cost the tree (``kind``, where every container looked like a directory) and
the search index (``role``, where every sender was filed as a recipient and the corpus
had no sender at all). Hence ONE normaliser, used on every enum read, plus a test that
fails the suite if a comparison against a bare string literal appears again.

Two ways to stay out of it, and both are worth having:

* read the column as ``toString(enum_column) AS enum_column`` in the SQL, so the wire
  format is a name whatever the client does with it;
* pass whatever arrives through :func:`enum_from_wire`, which accepts either.
"""

#: ``vfs_nodes.kind``. Names as ClickHouse spells them, ordinals as it stores them.
KIND_ORDINALS = {"dir": 0, "file": 1, "container": 2}

#: The value an unrecognised ``kind`` becomes. A directory: it is the only kind that
#: cannot claim a file hash it does not have.
KIND_DEFAULT = "dir"

#: ``email_addresses.role``. Note the ordinals start at 1, so a falsy check on this
#: column is not the same question as "is it the first name".
ROLE_ORDINALS = {"from": 1, "to": 2, "cc": 3, "bcc": 4}

#: The value an unrecognised ``role`` becomes. A recipient, never a sender: an address
#: wrongly shown as a recipient is a wider match, an address wrongly shown as the sender
#: is a false claim about who wrote the message.
ROLE_DEFAULT = "to"


def enum_from_wire(value, ordinals: dict[str, int], default: str) -> str:
    """Normalise an ``Enum8`` that may arrive as a name or as an ordinal.

    ``ordinals`` maps every name to its ordinal; ``default`` is what an unknown value of
    either shape becomes. The default is an explicit argument rather than "the first
    name", because for ``role`` the first name is ``from`` and a fallback that calls an
    unrecognised address the sender is precisely the failure this module exists to stop.
    """
    if isinstance(value, str):
        return value if value in ordinals else default
    try:
        wanted = int(value)
    except (TypeError, ValueError):
        return default
    for name, ordinal in ordinals.items():
        if ordinal == wanted:
            return name
    return default
