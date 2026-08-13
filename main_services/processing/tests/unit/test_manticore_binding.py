"""How corpus text reaches a Manticore statement, and why it does not go via a cursor.

The lesson this file exists to keep: a passing test that asserts whatever the code
produces proves nothing. Every case below is a string that a corpus really contains and
that breaks indexing or that naive escaping gets wrong, and each assertion says what
Manticore accepts, not what the driver happens to emit.

The defect being pinned: ``cursor.execute`` hands the fully interpolated statement to the
driver's client-side script splitter, which looks for a ``DELIMITER`` command in it. That
scanner does not understand the backslash escaping the driver has just applied, so a
document containing the word ``delimiter`` followed by whitespace and a quote is read as a
delimiter change and the statement is destroyed *after* it was escaped correctly. No
escaping fixes it; keeping the data out of the cursor does.
"""

import pytest
from mysql.connector.conversion import MySQLConverter

from database.manticore import bind_manticore_sql, manticore_execute

#: Every one of these appears in the corpus. MediaWiki writes bold as three quotes, and
#: the same help pages use the word `delimiter` — `mediawiki_bold` and `the_delimiter_word`
#: are that pair, and one page carrying them takes its whole indexing batch down.
ADVERSARIAL = {
    "mediawiki_bold": "These pages are found in the '''Template:''' namespace",
    "already_escaped_quote": r"a \' b",
    "trailing_backslash": "a line that ends with a backslash\\",
    "quote_at_the_very_end": "a line that ends with a quote'",
    "the_delimiter_word": "delimiter '",
    "delimiter_then_markup": "Set the delimiter to ''' and continue",
    "latex_backslashes": r"\big\{ \Big\{ \bigg\{ \Bigg\{ \to X",
    "percent_placeholder": "100% of %s things",
}

SQL = "REPLACE INTO t (id, page_text) VALUES (%s, %s)"


class _CextConnection:
    """The C-extension flavour: no `converter`, escaping behind `prepare_for_mysql`."""

    converter = None

    def __init__(self):
        self.sent: list[bytes] = []
        self._conv = MySQLConverter()

    def prepare_for_mysql(self, params):
        return [
            self._conv.quote(self._conv.escape(self._conv.to_mysql(value)))
            for value in params
        ]

    def cmd_query(self, statement):
        self.sent.append(statement)


class _PureConnection:
    """The pure-Python flavour: a `converter` and no `prepare_for_mysql`.

    Both exist in this worker — which one `mysql.connector.connect` hands back depends on
    import order — so the binder is tested against both and neither may be assumed.
    """

    sql_mode = None

    def __init__(self):
        self.sent: list[bytes] = []
        self.converter = MySQLConverter()

    def cmd_query(self, statement):
        self.sent.append(statement)


_FakeConnection = _CextConnection
FLAVOURS = (_CextConnection, _PureConnection)


def _unescape_literal(statement: bytes) -> str:
    """Read the last single-quoted literal of `statement` back, MySQL rules.

    The inverse of the escaping, so the assertion is "Manticore is handed exactly this
    text" rather than "the driver emitted the byte string I pasted in".
    """
    text = statement.decode("utf-8")
    assert text.endswith("')"), text[-20:]
    body = text[text.index(", '", text.index("VALUES")) + 3:-2]
    out, escaped = [], False
    for char in body:
        if escaped:
            out.append({"n": "\n", "r": "\r", "t": "\t", "0": "\0"}.get(char, char))
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            out.append(char)
    assert not escaped, "a literal must not end mid-escape"
    return "".join(out)


@pytest.mark.parametrize("flavour", FLAVOURS)
def test_a_quote_is_escaped_with_a_backslash_never_by_doubling(flavour):
    """Manticore's parser rejects the SQL-standard `''`. This is the whole subject of the
    escaping work and it is asserted against Manticore's rule, not the driver's habit."""
    statement = bind_manticore_sql(flavour(), SQL, (1, "it's"))
    assert statement == b"REPLACE INTO t (id, page_text) VALUES (1, 'it\\'s')"
    assert b"''" not in statement


@pytest.mark.parametrize("flavour", FLAVOURS)
@pytest.mark.parametrize("name", sorted(ADVERSARIAL))
def test_every_adversarial_string_survives_the_round_trip(name, flavour):
    text = ADVERSARIAL[name]
    statement = bind_manticore_sql(flavour(), SQL, (1, text))
    assert _unescape_literal(statement) == text


def test_a_percent_in_the_data_is_not_a_placeholder():
    """The template is split on `%s`, not formatted, so `%s` in a document is just text.
    A `%`-format substitution would consume it and shift every later parameter."""
    statement = bind_manticore_sql(_FakeConnection(), SQL, (1, "100% of %s things"))
    assert _unescape_literal(statement) == "100% of %s things"


def test_a_placeholder_count_mismatch_is_refused():
    for params in ((1,), (1, "a", "b")):
        with pytest.raises(ValueError):
            bind_manticore_sql(_FakeConnection(), SQL, params)


def test_the_drivers_script_splitter_would_destroy_these_statements():
    """The reason `manticore_execute` exists. `has_delimiter` is what `cursor.execute`
    consults, and it says yes to a correctly escaped statement carrying this text — after
    which the cursor either refuses to send it or rewrites it into something Manticore
    answers with a syntax error."""
    from mysql.connector._scripting import MySQLScriptSplitter

    statement = bind_manticore_sql(_FakeConnection(), SQL, (1, ADVERSARIAL["the_delimiter_word"]))
    assert MySQLScriptSplitter.has_delimiter(statement)


@pytest.mark.parametrize("flavour", FLAVOURS)
def test_manticore_execute_sends_the_statement_verbatim(flavour):
    """Not through a cursor: the bytes that were escaped are the bytes that go out."""
    cnx = flavour()
    text = ADVERSARIAL["mediawiki_bold"]
    manticore_execute(cnx, SQL, (1, text))
    assert len(cnx.sent) == 1
    assert cnx.sent[0] == bind_manticore_sql(flavour(), SQL, (1, text))
    assert _unescape_literal(cnx.sent[0]) == text


def test_a_statement_without_parameters_is_untouched():
    cnx = _FakeConnection()
    manticore_execute(cnx, "SELECT 1")
    assert cnx.sent == [b"SELECT 1"]
