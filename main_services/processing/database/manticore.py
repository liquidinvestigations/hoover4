"""Manticore Search connection helpers and per-collection shard table management.

Search data is sharded per collection: logical shard ``<collectionname>_<n>`` (n is
1-based) is ONE physical table, ``<collectionname>_<n>_pages``, holding one row per text
segment with the document's metadata denormalized onto every one of them. Shard tables
are created on demand by the indexing planner
(``tasks/P6_index_data/shard_planner.py``); this module only owns the DDL and the
lifecycle helpers.

**The metadata is duplicated per page on purpose, and a per-document table joined at
query time is not an option.** Manticore's ``LEFT JOIN`` is a nested-loop lookup per left
row evaluated before any predicate, so it costs the same for a query matching one
document as for one matching the corpus - it made an unfiltered facet on a 650 k-row
shard take 13 s instead of 1 s - and it silently DROPS left rows that find no match, so
the counts it produced were short as well as slow. The duplication costs ~15 % on disk
because the columnar engine picks a storage scheme per block and a block of pages
belonging to one document holds identical values. That saving only holds if the writer
inserts rows grouped by document; see ``P6_index_data/activities.py``.

There are deliberately **no distributed tables**. Manticore 14.1.0 (and 17.5.1 / 28.4.4)
cannot run the website's stored-field + FACET query shape over distributed tables -
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

# <collectionname>_<digits>_pages|_vectors, the SHARDED table families.
#
# `<collectionname>_vfs` is deliberately NOT matched by this: it is one table per
# collection rather than per shard, and everything that iterates shards (the ledger
# equality check, the per-shard search fan-out) must not see it. It still has to be
# dropped and purged with the collection, which is why `drop_collection_tables` and
# `purge_dataset_from_manticore` name it explicitly.
_SHARD_TABLE_RE_TEMPLATE = r'^{coll}_[0-9]+_(pages|vectors)$'
_SHARD_NAME_RE = re.compile(r'^([a-z0-9_]+)_([0-9]+)$')

PAGES_TABLE_SUFFIX = 'pages'
VECTORS_TABLE_SUFFIX = 'vectors'
VFS_TABLE_SUFFIX = 'vfs'
ENTITIES_TABLE_SUFFIX = 'entities'


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


def quote_manticore_values(cnx, params) -> list:
    """Escape and quote `params` the way `cnx` would for its own statements.

    The pure-Python connection exposes a ``converter``; the C-extension one does the same
    work behind ``prepare_for_mysql`` and has no converter at all.
    """
    converter = getattr(cnx, "converter", None)
    if converter is not None:
        sql_mode = getattr(cnx, "sql_mode", None)
        return [
            converter.quote(converter.escape(converter.to_mysql(value), sql_mode))
            for value in params
        ]
    return list(cnx.prepare_for_mysql(list(params)))


def bind_manticore_sql(cnx, sql, params=()) -> bytes:
    """Substitute `%s` placeholders in `sql` with `params`, escaped by the driver.

    Same convention as ``cursor.execute(sql, params)`` (every ``%s`` takes one
    parameter, quoting included), and the escaping is the connection's own, so a quote
    becomes ``\\'`` as Manticore wants and never the SQL-standard doubling it rejects.
    Splitting the TEMPLATE on ``%s`` is what makes a ``%s`` inside the *data* harmless.

    Both driver flavours have to be handled: whether ``mysql.connector.connect`` returns
    the C-extension connection or the pure-Python one depends on import order, so the
    worker gets one and a script that imported the driver first gets the other, and only
    one of the two exposes ``prepare_for_mysql``.
    """
    template = sql.encode("utf-8") if isinstance(sql, str) else bytes(sql)
    parts = template.split(b"%s")
    params = list(params)
    if len(parts) - 1 != len(params):
        raise ValueError(
            f"{len(parts) - 1} placeholder(s) in the statement, {len(params)} parameter(s)"
        )
    if not params:
        return template
    values = quote_manticore_values(cnx, params)
    out = bytearray(parts[0])
    for value, tail in zip(values, parts[1:]):
        out += value if isinstance(value, (bytes, bytearray)) else str(value).encode("utf-8")
        out += tail
    return bytes(out)


def manticore_execute(cnx, sql, params=()) -> None:
    """Run one parameterised statement against Manticore.

    **Never use ``cursor.execute`` for a statement carrying corpus text.** The MySQL
    driver scans the fully interpolated statement for a client-side ``DELIMITER``
    command before sending it, and that scanner does not understand the backslash
    escaping the same driver has just applied: a document containing the word
    ``delimiter`` followed by whitespace and a quote (ordinary MediaWiki and manual-page
    text does this) is read as a delimiter change. The statement is then either rejected
    outright or re-split and re-joined into something Manticore answers with
    ``P01: syntax error``, and the document can never be indexed. No amount of escaping
    fixes it, because the corruption happens after the escaping; the data has to stay out
    of the cursor. ``cmd_query`` sends the bytes as they are.
    """
    cnx.cmd_query(bind_manticore_sql(cnx, sql, params))


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


def shard_table_name(collectionname: str, shard_index: int) -> str:
    """Return the physical table name of a logical shard.

    ``'testdata_1_pages'`` for ``('testdata', 1)``.
    Raises ``ValueError`` for an invalid collection name or shard index.
    """
    from database.clickhouse import validate_collectionname
    validate_collectionname(collectionname)
    if not isinstance(shard_index, int) or isinstance(shard_index, bool) or shard_index < 1:
        raise ValueError(f'shard_index must be a positive integer, got {shard_index!r}')
    return f'{collectionname}_{shard_index}_{PAGES_TABLE_SUFFIX}'


def shard_table_from_name(shard_name: str) -> str:
    """Return the physical table name for a logical shard name like ``testdata_1``.

    Inverse of :func:`shard_table_name`; raises ``ValueError`` for anything that is
    not the CANONICAL spelling of a validated collectionname plus a positive integer
    suffix, no leading zeros (``testdata_01``), no stray separators
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
    return shard_table_name(collectionname, index)


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
    shard_table_from_name(shard_name)
    return vectors_table_name(collectionname, int(index))


#: Infix indexing, so ``MATCH('doc*')`` and ``MATCH('*ocument*')`` work.
#:
#: Without it the star is dropped during tokenisation and the query silently becomes an
#: exact search for the truncated word - ``doc*`` returned 7 rows where ``document``
#: returned 16, which is a *wrong answer* rather than "no wildcard support", and nobody
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


#: `date_min`/`date_max` for a document with no confirmed date. Manticore attributes are
#: not nullable, so "unknown" needs a reserved value, and i64::MIN is the one no real
#: date can collide with. A BETWEEN range can never match it, so undated documents drop
#: out of every date range automatically; the UI's "Unknown only" filters on equality.
#: The Rust side pins the same constant. Keep them in step.
DATE_UNKNOWN = -9223372036854775808

#: `file_size_bytes` for a document that exists in `file_types` but in no `vfs_files`
#: row. 0 is a legitimate size (an empty file), so it cannot double as "unknown", and
#: every size range excludes negatives.
SIZE_UNKNOWN = -1

#: The document-level columns, carried identically by every pages row of one document.
#: Named here because two writers interpolate them and the website filters, facets and
#: sorts on them; a column added to one list and not the other is a Manticore error on
#: every query rather than an empty result.
DOCUMENT_COLUMNS = (
    'file_types',
    'file_mime_types',
    'file_extensions',
    'file_paths',
    'dates',
    'date_min',
    'date_max',
    'file_size_bytes',
    'struct_flags',
    'primary_filename',
    'email_from',
    'email_to',
)


def pages_table_ddl(table_name: str) -> str:
    """CREATE TABLE statement for a shard's table (one row per text segment).

    ``collection_dataset`` stays on the rows: one shard holds several datasets, and the
    website filters and facets on it.

    ``page_text`` is the only full-text field; everything else is a typed attribute,
    which is what Manticore can group, sort and range-filter on. The document-level half
    (:data:`DOCUMENT_COLUMNS`) repeats on every page of a document. See the module
    docstring for why that is cheaper than joining it.

    Attributes and what reads them:

    * ``ner_per`` / ``ner_org`` / ``ner_loc`` / ``ner_misc`` multi64, term ids of the
      entities found in THIS segment. Per segment rather than per document, which is
      what lets a facet count documents while the extraction stays page-local.
    * ``dates`` multi64, every confirmed historical date, SIGNED epoch seconds.
      Manticore's own ``timestamp`` is 32-bit unsigned (1970..2106), useless for a
      corpus with pre-1970 material. Verified empirically that multi64 stores negatives
      and that ``ANY(dates) BETWEEN lo AND hi`` matches across zero.
    * ``date_min`` / ``date_max`` bigint, Manticore cannot ORDER BY an MVA, so "oldest
      first" sorts on one and "newest first" on the other, and the date filter is an
      interval-overlap test over the pair. :data:`DATE_UNKNOWN` when the document has no
      dates.
    * ``file_size_bytes`` bigint, buckets are computed at query time with
      ``INTERVAL()``; pre-baking them would make adding a bucket a schema change.
      :data:`SIZE_UNKNOWN` when the document has no ``vfs_files`` row.
    * ``struct_flags`` bigint, a bitfield (see ``STRUCT_FLAG_*``) for the cheap
      booleans that do not each deserve a column.
    * ``primary_filename`` string, a string ATTRIBUTE, not a text field: Manticore can
      ORDER BY the former and not the latter, and this is the result-card title and the
      "sort by name" key. Filename MATCHING goes through the ``filename_index`` row
      instead.
    * ``file_paths`` multi64, `vfs_node` closure term ids, scoped by dataset AND
      container, so the same folder name in two datasets or two archives is two ids.
    * ``email_from`` / ``email_to`` multi64, term ids of normalised addresses;
      to+cc+bcc merge into ``email_to``.
    * ``re_email`` / ``re_phone`` / ``re_bank_account`` / ``re_company_id`` /
      ``re_money`` / ``re_crypto_wallet`` multi64, term ids from the regex entity
      scanner, per segment like the ``ner_*`` columns. ``re_email`` is NOT
      ``email_from``/``email_to``: those are the envelope's sender and recipients, and
      this is every address the body mentions. ``re_money``'s ids resolve to magnitude
      buckets, never to amounts. Thousands of distinct sums are not a facet.
    * ``mentioned_dates`` multi64, dates the document TALKS ABOUT, signed epoch seconds
      snapped to midnight UTC, one entry per distinct day. Snapped because second
      precision gives a term per instant and the corpus's distinct *days* are bounded by
      its span. It is filtered with ``ANY(mentioned_dates) BETWEEN lo AND hi`` and never
      with the interval-overlap test ``dates`` uses: a document that mentions 1936 and
      2020 occupies neither 2005 nor anything in between, while a file created in 1990
      and modified in 2020 genuinely occupies that whole span.
    * ``mentioned_date_min`` / ``mentioned_date_max`` bigint, the histogram's domain,
      and :data:`DATE_UNKNOWN` for a segment that mentions no date. They must never be
      used to filter, for the reason above.
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
            ner_misc multi64,
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
            email_to multi64,
            re_email multi64,
            re_phone multi64,
            re_bank_account multi64,
            re_company_id multi64,
            re_money multi64,
            re_crypto_wallet multi64,
            mentioned_dates multi64,
            mentioned_date_min bigint,
            mentioned_date_max bigint
        ) engine='columnar' {_INFIX_SETTING}
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

    ``name`` is the only full-text field and it is infix indexed. Matching
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


def entities_table_name(collectionname: str) -> str:
    """The term-search table of a collection (``testdata_entities``)."""
    from database.clickhouse import validate_collectionname
    validate_collectionname(collectionname)
    return f'{collectionname}_{ENTITIES_TABLE_SUFFIX}'


def entities_table_ddl(table_name: str) -> str:
    """CREATE TABLE statement for a collection's facet-term search index.

    It exists because **nothing in Manticore filters a facet by its bucket's name.** The
    MVAs hold `hash_string_to_uint63` term ids and the text lives only in ClickHouse
    `string_term_id_to_text`, so there is not even a string for a facet query to match.
    A typed needle has to be resolved to term ids somewhere else first, and this is that
    somewhere.

    Without it the filter pane's "Search X" boxes narrow the twenty-one buckets already
    on screen, which on a corpus with tens of thousands of distinct values answers
    "nothing matches" for values that are present.

    ``term_text`` is the only full-text field and is infix indexed, so a needle matches
    inside a value rather than only at its start, and ``HIGHLIGHT()`` over it is what
    gives a row its match reason. ``term_display`` is the same string as an attribute,
    because a text field cannot be selected back exactly.

    ``term_id`` is the value the facet MVAs hold, carried here so one query answers the
    whole question. It is not derivable from the row id, which hashes the field and the
    id together, and looking it up again in ClickHouse would be a second round trip for
    a number this row already knows.

    One table per COLLECTION, holding every facet field except ``filetype``, that one
    has few enough buckets to fit on screen and needs no search. Reads go through the
    NON-caching Manticore primitive, for the same reason the tree does: it changes while
    ingestion runs, and a stale term list is worse than a slow one.
    """
    return f"""
        create table if not exists {table_name}(
            term_field string,
            term_text text,
            term_display string,
            term_id bigint,
            collection_dataset string
        ) engine='columnar' {_INFIX_SETTING}
    """


def create_entities_table(collectionname: str) -> str:
    """Create a collection's facet-term search table if it does not exist. Idempotent."""
    table = entities_table_name(collectionname)
    _execute_ddl(entities_table_ddl(table))
    return table


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
    altered: ``dims`` must be the probed serving dimension, and a model change means
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

    Read from Manticore's own ``SHOW CREATE TABLE``, which is the only source of truth for a
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


def create_shard_tables(collectionname: str, shard_index: int, vector_dims: int | None = None) -> str:
    """Create the tables of a logical shard if they do not exist. Idempotent.

    ``vector_dims`` is the PROBED serving dimension (``main.py probe-embeddings`` via
    ``server_settings.embeddings_serving_dim``), never the ini's request: a
    ``_vectors`` table's ``knn_dims`` is fixed at creation and cannot be altered, so a
    table built from the wrong dimension is a silent wrong-answer machine until someone
    drops and rebuilds it. ``None`` creates no vectors table (embeddings not probed
    yet); the P6 vector indexer refuses loudly if it then finds vectors to write.
    """
    pages_table = shard_table_name(collectionname, shard_index)
    _execute_ddl(pages_table_ddl(pages_table))
    if vector_dims is not None:
        _execute_ddl(vectors_table_ddl(vectors_table_name(collectionname, shard_index), vector_dims))
    return pages_table


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
    """Every Manticore table a collection owns: its shard tables plus the two
    collection-wide indexes, the VFS tree and the facet-term list.

    What teardown and purge iterate. Kept separate from :func:`list_shard_tables`
    because the callers that reason about *shards* (the ledger equality check, the
    per-shard search fan-out) must not be handed a table that has no shard index.
    """
    tables = list_shard_tables(collectionname)
    all_tables = _list_all_tables()
    for table in (vfs_table_name(collectionname), entities_table_name(collectionname)):
        if table in all_tables:
            tables.append(table)
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

    Every ``_vectors`` table is created from this value, never from the ini, which is
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
        # The structure index and the facet-term index have no ledger to recover from
        # (each is one table per collection, rebuilt from ClickHouse by P6), so they are
        # healed here unconditionally rather than per recorded shard.
        create_vfs_table(collectionname)
        create_entities_table(collectionname)
        with get_collection_client(collectionname) as client:
            rows = client.query(
                "SELECT shard_index FROM manticore_shards FINAL ORDER BY shard_index"
            ).result_rows
        for (shard_index,) in rows:
            create_shard_tables(collectionname, int(shard_index), vector_dims=vector_dims)
        if rows:
            log.info(
                "Collection %s: ensured %d shard tables exist",
                collectionname, len(rows),
            )
    log.info("ManticoreSearch migration OK.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    manticore_migrate()
