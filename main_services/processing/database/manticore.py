"""Manticore Search connection helpers and per-collection shard table management.

Search data is sharded per collection: logical shard ``<collectionname>_<n>`` (n is
1-based) consists of two physical tables, ``<collectionname>_<n>_pages`` and
``<collectionname>_<n>_meta``, with schemas identical to the retired global
``doc_text_pages`` / ``doc_metadata`` tables. Shard tables are created on demand by the
indexing planner (``tasks/P5_index_data/shard_planner.py``); this module only owns the
DDL and the lifecycle helpers.

There are deliberately **no distributed tables**. Manticore 14.1.0 (and 17.5.1 / 28.4.4)
cannot run the website's JOIN + stored-field + FACET query shape over distributed tables -
the daemon crashes or returns NULL stored fields (see
``plans/2-collections/2-spike-manticore-results.md``). Search therefore fans out per
shard in the website backend (plan part 7).

Every identifier reaching a DDL string is built from a validated ``collectionname``
plus an integer shard index, or validated against the shard-name regex. Never
interpolate anything else.
"""

from contextlib import contextmanager
import logging
import re

log = logging.getLogger(__name__)

# <collectionname>_<digits>_pages|_meta — the only table families this module manages.
_SHARD_TABLE_RE_TEMPLATE = r'^{coll}_[0-9]+_(pages|meta)$'
_SHARD_NAME_RE = re.compile(r'^([a-z0-9_]+)_([0-9]+)$')

PAGES_TABLE_SUFFIX = 'pages'
META_TABLE_SUFFIX = 'meta'


@contextmanager
def get_manticore_client():
    import mysql.connector
    cnx = mysql.connector.connect(
        host="manticore",
        port=9306,
        user="manticore",
        password="manticore", database='Manticore')
    try:
        yield cnx
    finally:
        try:
            cnx.close()
        except Exception as e:
            log.error(f"Error closing Manticore connection: {e}")
            pass


def check_manticore_health():
    log.info("Checking ManticoreSearch health...")
    with get_manticore_client() as cnx:
        cur = cnx.cursor()
        cur.execute("SELECT CURDATE()")
        row = cur.fetchone()
        log.info("MANTICORE OK - Current date is: {0}".format(row[0]))
        return row[0]


def _execute_ddl(sql):
    with get_manticore_client() as cnx:
        log.info("Manticore Execute DDL: {}".format(sql))
        cur = cnx.cursor()
        cur.execute(sql)
        cnx.commit()
        log.info("SQL Executed OK.")


def shard_table_names(collectionname: str, shard_index: int) -> tuple[str, str]:
    """Return the two physical table names of a logical shard.

    ``('testdata_1_pages', 'testdata_1_meta')`` for ``('testdata', 1)``.
    Raises ``ValueError`` for an invalid collection name or shard index.
    """
    from database.clickhouse import validate_collectionname
    validate_collectionname(collectionname)
    if not isinstance(shard_index, int) or isinstance(shard_index, bool) or shard_index < 1:
        raise ValueError(f'shard_index must be a positive integer, got {shard_index!r}')
    shard_name = f'{collectionname}_{shard_index}'
    return (f'{shard_name}_{PAGES_TABLE_SUFFIX}', f'{shard_name}_{META_TABLE_SUFFIX}')


def shard_tables_from_name(shard_name: str) -> tuple[str, str]:
    """Return the two physical table names for a logical shard name like ``testdata_1``.

    Inverse of :func:`shard_table_names`; raises ``ValueError`` for anything that is
    not the CANONICAL spelling of a validated collectionname plus a positive integer
    suffix — no leading zeros (``testdata_01``), no stray separators
    (``testdata_-1``): those would alias shard 1 while naming tables the ledger
    never records.
    """
    from database.clickhouse import validate_collectionname
    m = _SHARD_NAME_RE.match(shard_name or '')
    if not m:
        raise ValueError(f'{shard_name!r} is not a valid shard name (<collectionname>_<n>)')
    collectionname, index = m.group(1), int(m.group(2))
    if f'{collectionname}_{index}' != shard_name:
        raise ValueError(f'{shard_name!r} is not a canonical shard name (<collectionname>_<n>)')
    return shard_table_names(collectionname, index)


def pages_table_ddl(table_name: str) -> str:
    """CREATE TABLE statement for a shard pages table (one row per text segment).

    Schema is identical to the retired global ``doc_text_pages``.
    """
    return f"""
        create table if not exists {table_name}(
            collection_dataset string,
            file_hash string,
            extracted_by string,
            page_id int,
            page_text text,
            ner_per multi64,
            ner_org multi64,
            ner_loc multi64,
            ner_misc multi64
        ) engine='columnar'
    """


def meta_table_ddl(table_name: str) -> str:
    """CREATE TABLE statement for a shard metadata table (one row per document).

    Schema is identical to the retired global ``doc_metadata``. ``collection_dataset``
    stays on the rows: one shard holds several datasets, and the website filters and
    facets on it.
    """
    return f"""
        create table if not exists {table_name}(
            collection_dataset string,
            file_hash string,
            file_types multi64,
            file_mime_types multi64,
            file_extensions multi64,
            file_paths multi64,
            filenames text,
            metadata_values text
        ) engine='columnar'
    """


def create_shard_tables(collectionname: str, shard_index: int) -> tuple[str, str]:
    """Create the two tables of a logical shard if they do not exist. Idempotent."""
    pages_table, meta_table = shard_table_names(collectionname, shard_index)
    _execute_ddl(pages_table_ddl(pages_table))
    _execute_ddl(meta_table_ddl(meta_table))
    return (pages_table, meta_table)


def _list_all_tables() -> list[str]:
    with get_manticore_client() as cnx:
        cur = cnx.cursor()
        cur.execute("SHOW TABLES")
        return [row[0] for row in cur.fetchall()]


def list_shard_tables(collectionname: str) -> list[str]:
    """All physical shard tables of a collection, sorted.

    Matches exactly ``<collectionname>_<digits>_(pages|meta)`` - a collection named
    ``testdata_x`` must not show up in ``testdata``'s list.
    """
    from database.clickhouse import validate_collectionname
    validate_collectionname(collectionname)
    pattern = re.compile(_SHARD_TABLE_RE_TEMPLATE.format(coll=re.escape(collectionname)))
    return sorted(t for t in _list_all_tables() if pattern.match(t))


def drop_collection_tables(collectionname: str) -> list[str]:
    """Drop every shard table of a collection. Returns the dropped table names."""
    dropped = []
    for table in list_shard_tables(collectionname):
        _execute_ddl(f"drop table if exists {table}")
        dropped.append(table)
    if dropped:
        log.warning("Dropped Manticore tables for collection %s: %s", collectionname, dropped)
    return dropped


def manticore_migrate():
    """Health check, then self-heal shard tables for every collection.

    Shard tables are created on demand by the indexing planner, not at migrate time.
    What migrate does is bring back any shard table recorded in a collection's
    ``manticore_shards`` ledger but missing from Manticore (e.g. after a Manticore
    volume loss). Recovered tables come back EMPTY - see
    ``main.py reindex-collection`` for the reindex story.
    """
    check_manticore_health()
    log.info("Starting ManticoreSearch migration....")
    from database.clickhouse import get_collection_client, list_collections
    for collectionname in list_collections():
        with get_collection_client(collectionname) as client:
            rows = client.query(
                "SELECT shard_index FROM manticore_shards FINAL ORDER BY shard_index"
            ).result_rows
        for (shard_index,) in rows:
            create_shard_tables(collectionname, int(shard_index))
        if rows:
            log.info(
                "Collection %s: ensured %d shard table pairs exist",
                collectionname, len(rows),
            )
    log.info("ManticoreSearch migration OK.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    manticore_migrate()
