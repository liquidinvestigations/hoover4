"""Integration test: text shapes that the index writer has to be able to store.

Every string here is taken from a document that could not be indexed, or is the naive
escaping case next to it. The write goes through the same helper the P6 writers use, into
a real Manticore table with a real ``page_text`` field, and the text is read back and
compared — a store that silently truncated or re-escaped would pass a "did it raise"
check and fail this one.

Requires the docker stack; run inside the worker container:
``docker exec -it hoover4-worker uv run pytest tests/integration --integration -q``
"""

import pytest

from database.manticore import get_manticore_client, manticore_execute

pytestmark = [pytest.mark.integration, pytest.mark.timeout(300)]

TABLE = "it_text_shapes_probe"

#: MediaWiki writes bold as three single quotes, and the word `delimiter` appears in the
#: same help pages. A page carrying both is unindexable through a MySQL cursor, and it
#: takes every other document in its batch down with it.
CASES = {
    "mediawiki_bold": "These pages are found in the '''Template:''' namespace\n",
    "delimiter_and_quotes": "or transclusion.\nUse the delimiter ''' to make text bold.",
    "already_escaped_quote": r"a \' b",
    "trailing_backslash": "a line that ends with a backslash\\",
    "quote_at_the_very_end": "a line that ends with a quote'",
    "latex_backslashes": r"\big\{ \Big\{ \bigg\{ \Bigg\{ \to X",
    "percent_placeholder": "100% of %s things",
    "newlines_and_tabs": "a\nb\tc\r\nd",
    "big_page": ("delimiter ''' " + "lorem ipsum dolor sit amet " * 4000)[:262_000],
}


@pytest.fixture()
def probe_table():
    with get_manticore_client() as cnx:
        cursor = cnx.cursor()
        cursor.execute(f"DROP TABLE IF EXISTS {TABLE}")
        cursor.execute(f"CREATE TABLE {TABLE} (id bigint, page_text text stored)")
        cnx.commit()
    yield TABLE
    with get_manticore_client() as cnx:
        cursor = cnx.cursor()
        cursor.execute(f"DROP TABLE IF EXISTS {TABLE}")
        cnx.commit()


def test_every_text_shape_stores_and_reads_back_unchanged(probe_table):
    ids = dict(enumerate(sorted(CASES), start=1))
    with get_manticore_client() as cnx:
        for row_id, name in ids.items():
            manticore_execute(
                cnx,
                f"REPLACE INTO {probe_table} (id, page_text) VALUES (%s, %s)",
                (row_id, CASES[name]),
            )
        cnx.commit()
        cursor = cnx.cursor()
        cursor.execute(f"SELECT id, page_text FROM {probe_table} LIMIT 100")
        stored = {int(row[0]): row[1] for row in cursor.fetchall()}

    for row_id, name in ids.items():
        assert stored.get(row_id) == CASES[name], name
