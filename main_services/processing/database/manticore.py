"""Manticore Search connection helpers and per-collection shard table management.

Search data is sharded per collection: logical shard ``<collectionname>_<n>`` (n is
1-based) consists of two physical tables, ``<collectionname>_<n>_pages`` and
``<collectionname>_<n>_meta``, with schemas identical to the retired global
``doc_text_pages`` / ``doc_metadata`` tables. Shard tables are created on demand by the
indexing planner (``tasks/P6_index_data/shard_planner.py``); this module only owns the
DDL and the lifecycle helpers.

There are deliberately **no distributed tables**. Manticore 14.1.0 (and 17.5.1 / 28.4.4)
cannot run the website's JOIN + stored-field + FACET query shape over distributed tables -
the daemon crashes or returns NULL stored fields. Search therefore fans out per
shard in the website backend.

Every identifier reaching a DDL string is built from a validated ``collectionname``
plus an integer shard index, or validated against the shard-name regex. Never
interpolate anything else.
"""

from contextlib import contextmanager
import logging
import re

log = logging.getLogger(__name__)

# <collectionname>_<digits>_pages|_meta|_vectors — the SHARDED table families.
#
# `<collectionname>_vfs` is deliberately NOT matched by this: it is one table per
# collection rather than per shard, and everything that iterates shards (the ledger
# equality check, the per-shard search fan-out) must not see it. It still has to be
# dropped and purged with the collection, which is why `drop_collection_tables` and
# `purge_dataset_from_manticore` name it explicitly.
_SHARD_TABLE_RE_TEMPLATE = r'^{coll}_[0-9]+_(pages|meta|vectors)$'
_SHARD_NAME_RE = re.compile(r'^([a-z0-9_]+)_([0-9]+)$')

PAGES_TABLE_SUFFIX = 'pages'
META_TABLE_SUFFIX = 'meta'
VECTORS_TABLE_SUFFIX = 'vectors'
VFS_TABLE_SUFFIX = 'vfs'


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


def vectors_table_name(collectionname: str, shard_index: int) -> str:
    """The physical vectors table of a logical shard (``testdata_1_vectors``)."""
    from database.clickhouse import validate_collectionname
    validate_collectionname(collectionname)
    if not isinstance(shard_index, int) or isinstance(shard_index, bool) or shard_index < 1:
        raise ValueError(f'shard_index must be a positive integer, got {shard_index!r}')
    return f'{collectionname}_{shard_index}_{VECTORS_TABLE_SUFFIX}'


def vectors_table_from_name(shard_name: str) -> str:
    """The vectors table for a logical shard name. Same validation as
    :func:`shard_tables_from_name`."""
    collectionname, index = shard_name.rsplit('_', 1)
    # Reuse the canonical-name validation rather than re-parsing here.
    shard_tables_from_name(shard_name)
    return vectors_table_name(collectionname, int(index))


#: Infix indexing, so ``MATCH('doc*')`` and ``MATCH('*ocument*')`` work.
#:
#: Without it the star is dropped during tokenisation and the query silently becomes an
#: exact search for the truncated word - ``doc*`` returned 7 rows where ``document``
#: returned 16, which is not "no wildcard support", it is a *wrong answer* nobody
#: notices. On the real `testdata` shard (156 pages, 26 MB of text) the wrong answers
#: become right ones: `docum*` 0 -> 19, `*ocument*` 0 -> 42, `doc*` 7 -> 34, `te*t`
#: 3 -> 28, while the exact term `document` stays at 16.
#:
#: Storage cost is small but was NOT reliably measurable: `SHOW TABLE ... STATUS`
#: `disk_bytes` on an RT table depends on chunk-merge state, and the same no-infix
#: config measured 16.6 MB, 33.6 MB and 65.4 MB at different points. Under identical
#: treatment (pipeline reindex, then FLUSH + OPTIMIZE) the infix build measured
#: *smaller* - 26.0 MB against 33.6 MB - so whatever the true cost is, it is not one
#: worth trading the wrong answers for. See main_services/agents/README.md.
#:
#: The value is 3 as a statement of intent only. This Manticore version treats
#: min_infix_len as an on/off switch rather than a threshold - 2, 3 and 4 are
#: byte-for-byte identical in size *and* behaviour, and ``do*`` (2 chars) matches even
#: at 4. Do not spend time tuning it. (``min_prefix_len`` *is* a real threshold, and is
#: the wrong tool: it gives no infix matching and makes stars work only for prefixes
#: longer than the minimum.)
#:
#: ALTER TABLE sets this on an existing table and does NOT reindex it: SHOW TABLE
#: SETTINGS will report the new value while queries keep returning the old wrong
#: answers. Changing it means `main.py reindex-collection <name>`.
_INFIX_SETTING = "min_infix_len='3'"


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
        ) engine='columnar' {_INFIX_SETTING}
    """


#: `date_min`/`date_max` for a document with no confirmed date. Manticore attributes are
#: not nullable, so "unknown" needs a reserved value, and i64::MIN is the one no real
#: date can collide with. A BETWEEN range can never match it, so undated documents drop
#: out of every date range automatically; the UI's "Unknown only" filters on equality.
#: The Rust side pins the same constant — keep them in step.
DATE_UNKNOWN = -9223372036854775808

#: `file_size_bytes` for a document that exists in `file_types` but in no `vfs_files`
#: row. 0 is a legitimate size (an empty file), so it cannot double as "unknown", and
#: every size range excludes negatives.
SIZE_UNKNOWN = -1


def meta_table_ddl(table_name: str) -> str:
    """CREATE TABLE statement for a shard metadata table (one row per document).

    ``collection_dataset`` stays on the rows: one shard holds several datasets, and the
    website filters and facets on it.

    **Attribute-only — no full-text fields.** The old ``filenames`` and
    ``metadata_values`` text columns are gone: ``metadata_values`` was written as ``""``
    unconditionally since the day it was created, and ``filenames`` is now covered twice
    over by the ``filename_index`` pages row (match + highlight) and
    ``primary_filename`` (title + name sort). Verified against the live Manticore
    14.1.0 that a table with zero text fields is accepted rather than needing a dummy
    field, and that ``min_infix_len`` on a table with no text field is pointless — hence
    no infix setting here any more.

    Typed attributes and what reads them:

    * ``dates`` multi64 — every confirmed historical date, SIGNED epoch seconds.
      Manticore's own ``timestamp`` is 32-bit unsigned (1970..2106), useless for a
      corpus with pre-1970 material. Verified empirically that multi64 stores negatives
      and that ``ANY(dates) BETWEEN lo AND hi`` matches across zero.
    * ``date_min`` / ``date_max`` bigint — Manticore cannot ORDER BY an MVA, so "oldest
      first" sorts on one and "newest first" on the other. :data:`DATE_UNKNOWN` when the
      document has no dates.
    * ``file_size_bytes`` bigint — buckets are computed at query time with
      ``INTERVAL()``; pre-baking them would make adding a bucket a schema change.
      :data:`SIZE_UNKNOWN` when the document has no ``vfs_files`` row.
    * ``struct_flags`` bigint — a bitfield (see ``STRUCT_FLAG_*``) for the cheap
      booleans that do not each deserve a column.
    * ``primary_filename`` string — a string ATTRIBUTE, not a text field: Manticore can
      ORDER BY the former and not the latter, and this is the result-card title and the
      "sort by name" key.
    * ``file_paths`` multi64 — repurposed from bare parent-path term ids to `vfs_node`
      closure term ids, which are scoped by dataset AND container. The old ids were the
      same integer for `/data` in every dataset and inside every archive.
    * ``email_from`` / ``email_to`` multi64 — term ids of normalised addresses;
      to+cc+bcc merge into ``email_to``.
    """
    return f"""
        create table if not exists {table_name}(
            collection_dataset string,
            file_hash string,
            file_types multi64,
            file_mime_types multi64,
            file_extensions multi64,
            file_paths multi64,
            dates multi64,
            date_min bigint,
            date_max bigint,
            file_size_bytes bigint,
            struct_flags bigint,
            primary_filename string,
            email_from multi64,
            email_to multi64
        ) engine='columnar'
    """


def vfs_table_name(collectionname: str) -> str:
    """The structure-index table of a collection (``testdata_vfs``)."""
    from database.clickhouse import validate_collectionname
    validate_collectionname(collectionname)
    return f'{collectionname}_{VFS_TABLE_SUFFIX}'


def vfs_table_ddl(table_name: str) -> str:
    """CREATE TABLE statement for a collection's VFS structure index.

    One row per node of the materialised tree (ClickHouse ``vfs_nodes``). It powers the
    tree sidebar, the filter pane's folder picker, and in-folder filename search.

    **One table per COLLECTION, not per dataset and not per shard.** Every query already
    filters ``collection_dataset``, a per-dataset table would multiply the table count
    for no query-plan benefit, and a dataset purge is a ``DELETE WHERE
    collection_dataset = …``. It holds one small attribute row per node and no text
    bodies, so it does not need the shard budget: `testdata` has hundreds of rows, and a
    million-file collection is a couple of hundred MB of attributes.

    ``name`` is the only full-text field and it is infix indexed — matching
    ``*report*`` against a basename is the entire point of in-folder search.

    Every read of this table goes through the website's NON-caching Manticore primitive.
    The tree changes as ingestion proceeds and a stale tree is worse than a slow one.
    """
    return f"""
        create table if not exists {table_name}(
            collection_dataset string,
            container_hash string,
            node_key string,
            parent_key string,
            ancestor_keys multi64,
            name text,
            path string,
            kind int,
            file_hash string,
            file_size_bytes bigint,
            depth int
        ) engine='columnar' {_INFIX_SETTING}
    """


def create_vfs_table(collectionname: str) -> str:
    """Create a collection's structure-index table if it does not exist. Idempotent."""
    table = vfs_table_name(collectionname)
    _execute_ddl(vfs_table_ddl(table))
    return table


def vectors_table_ddl(table_name: str, dims: int) -> str:
    """CREATE TABLE statement for a shard vectors table (one row per embedded chunk).

    The disposable HNSW copy of ClickHouse ``text_chunk_vectors``. Deliberately NOT
    ``engine='columnar'`` (the columnar library does not back ``float_vector``) and
    deliberately lean: the chunk text stays in ClickHouse, so a dropped or
    wrong-dimensioned table is rebuilt from the durable store, and the RAM-resident
    HNSW graph carries no text. ``knn_dims`` is fixed at creation and CANNOT be
    altered — ``dims`` must be the probed serving dimension, and a model change means
    drop + rebuild (``main.py reindex-collection``).

    ``collection_dataset`` stays on the rows: the dataset purge deletes by it.
    """
    if not isinstance(dims, int) or isinstance(dims, bool) or not 1 <= dims <= 65535:
        raise ValueError(f'knn_dims must be an int in [1, 65535], got {dims!r}')
    return f"""
        create table if not exists {table_name}(
            collection_dataset string,
            file_hash string,
            extracted_by string,
            page_id int,
            chunk_index int,
            embedding float_vector knn_type='hnsw' knn_dims='{dims}' hnsw_similarity='COSINE'
        )
    """


def shard_knn_dims(vectors_table: str) -> int | None:
    """The ``knn_dims`` of an existing vectors table, or ``None`` if it does not exist.

    Read from Manticore's own ``SHOW CREATE TABLE`` — the only source of truth for a
    property that cannot be altered after creation. The P6 vector indexer compares
    this against the probed serving dimension and refuses on mismatch: writing 384-dim
    vectors into a 1024-dim table is the failure the whole probe mechanism exists to
    prevent.
    """
    with get_manticore_client() as cnx:
        cur = cnx.cursor()
        try:
            cur.execute(f"SHOW CREATE TABLE {vectors_table}")
        except Exception:
            return None
        row = cur.fetchone()
    if not row or len(row) < 2:
        return None
    m = re.search(r"knn_dims='(\d+)'", row[1])
    return int(m.group(1)) if m else None


def create_shard_tables(collectionname: str, shard_index: int, vector_dims: int | None = None) -> tuple[str, str]:
    """Create the tables of a logical shard if they do not exist. Idempotent.

    ``vector_dims`` is the PROBED serving dimension (``main.py probe-embeddings`` via
    ``server_settings.embeddings_serving_dim``), never the ini's request: a
    ``_vectors`` table's ``knn_dims`` is fixed at creation and cannot be altered, so a
    table built from the wrong dimension is a silent wrong-answer machine until someone
    drops and rebuilds it. ``None`` creates no vectors table (embeddings not probed
    yet); the P6 vector indexer refuses loudly if it then finds vectors to write.
    """
    pages_table, meta_table = shard_table_names(collectionname, shard_index)
    _execute_ddl(pages_table_ddl(pages_table))
    _execute_ddl(meta_table_ddl(meta_table))
    if vector_dims is not None:
        _execute_ddl(vectors_table_ddl(vectors_table_name(collectionname, shard_index), vector_dims))
    return (pages_table, meta_table)


def _list_all_tables() -> list[str]:
    with get_manticore_client() as cnx:
        cur = cnx.cursor()
        cur.execute("SHOW TABLES")
        return [row[0] for row in cur.fetchall()]


def list_shard_tables(collectionname: str) -> list[str]:
    """All physical SHARD tables of a collection, sorted.

    Matches exactly ``<collectionname>_<digits>_(pages|meta|vectors)`` - a collection
    named ``testdata_x`` must not show up in ``testdata``'s list, and the collection's
    single ``<collectionname>_vfs`` table is deliberately excluded (it is not sharded;
    see :func:`list_collection_tables`).
    """
    from database.clickhouse import validate_collectionname
    validate_collectionname(collectionname)
    pattern = re.compile(_SHARD_TABLE_RE_TEMPLATE.format(coll=re.escape(collectionname)))
    return sorted(t for t in _list_all_tables() if pattern.match(t))


def list_collection_tables(collectionname: str) -> list[str]:
    """Every Manticore table a collection owns: its shard tables plus its VFS table.

    What teardown and purge iterate. Kept separate from :func:`list_shard_tables`
    because the callers that reason about *shards* — the ledger equality check, the
    per-shard search fan-out — must not be handed a table that has no shard index.
    """
    tables = list_shard_tables(collectionname)
    vfs_table = vfs_table_name(collectionname)
    if vfs_table in _list_all_tables():
        tables.append(vfs_table)
    return tables


def drop_collection_tables(collectionname: str) -> list[str]:
    """Drop every Manticore table of a collection. Returns the dropped table names."""
    dropped = []
    for table in list_collection_tables(collectionname):
        _execute_ddl(f"drop table if exists {table}")
        dropped.append(table)
    if dropped:
        log.warning("Dropped Manticore tables for collection %s: %s", collectionname, dropped)
    return dropped


def probed_embedding_dims() -> int | None:
    """The probed serving dimension from ``server_settings``, or ``None`` if unprobed.

    Every ``_vectors`` table is created from this value — never from the ini, which is
    the request rather than the truth. ``None`` means `main.py probe-embeddings` has
    not run (or embeddings are disabled): no vectors tables get created, and the P6
    vector indexer refuses loudly if it nevertheless finds vectors to write.
    """
    from database.clickhouse import get_server_setting
    raw = get_server_setting("embeddings_serving_dim")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        log.warning("embeddings_serving_dim %r is not a number; treating as unprobed", raw)
        return None


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
    vector_dims = probed_embedding_dims()
    for collectionname in list_collections():
        # The structure index has no ledger to recover from — it is one table per
        # collection, rebuilt from ClickHouse `vfs_nodes` by P6 — so it is healed here
        # unconditionally rather than per recorded shard.
        create_vfs_table(collectionname)
        with get_collection_client(collectionname) as client:
            rows = client.query(
                "SELECT shard_index FROM manticore_shards FINAL ORDER BY shard_index"
            ).result_rows
        for (shard_index,) in rows:
            create_shard_tables(collectionname, int(shard_index), vector_dims=vector_dims)
        if rows:
            log.info(
                "Collection %s: ensured %d shard table pairs exist",
                collectionname, len(rows),
            )
    log.info("ManticoreSearch migration OK.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    manticore_migrate()
