"""ClickHouse client helpers and migrations for processing storage.

Storage is split across ``1 + N`` databases:

* ``Hoover4_Processing`` (:data:`GLOBAL_DB`) holds everything that is not scoped to a
  single collection: users, groups, collections, the dataset registry, sessions,
  server settings and the search cache. Migrations live in ``db_global_migrations/``.
* ``Hoover4_Collection_<collectionname>`` holds one collection's ingested data: blobs,
  VFS, parsed content, plans, errors, term dictionaries. Migrations live in
  ``db_collection_migrations/`` and are applied to *every* collection database.

Pick the client by what you are reading, never by convenience:
:func:`get_global_client` for global tables, :func:`get_collection_client` when the
collection is known, :func:`get_client_for_dataset` when only a ``collection_dataset``
is in hand.
"""

import logging
import pathlib
import re
from contextlib import contextmanager

import clickhouse_connect

log = logging.getLogger(__name__)

CLICKHOUSE_HOST = 'clickhouse'
CLICKHOUSE_USER = 'hoover4'
CLICKHOUSE_PASS = 'hoover4'

GLOBAL_DB = 'Hoover4_Processing'
COLLECTION_DB_PREFIX = 'Hoover4_Collection_'

_MIGRATIONS_ROOT = pathlib.Path(__file__).parent.resolve()
GLOBAL_MIGRATIONS_PATH = str(_MIGRATIONS_ROOT / 'db_global_migrations')
COLLECTION_MIGRATIONS_PATH = str(_MIGRATIONS_ROOT / 'db_collection_migrations')

CLIENT_SETTINGS = {
    'async_insert': 1,
    'wait_for_async_insert': 1,
}

# Mirrors website/backend/src/api/admin/collections.rs::collectionname_valid.
# Duplicated deliberately: the two runtimes must independently refuse a bad name.
MAX_COLLECTIONNAME_LENGTH = 48
# No '-': every Manticore identifier (<name>_<n>_pages|_meta|_vectors) is interpolated
# UNQUOTED into SQL in both runtimes, and a dashed table name does not parse.
_COLLECTIONNAME_RE = re.compile(r'^[a-z0-9_]+$')
_SHARD_SUFFIX_RE = re.compile(r'_[0-9]+$')
RESERVED_COLLECTIONNAME_SUFFIXES = ('_pages', '_meta', '_vectors')
RESERVED_COLLECTIONNAMES = ('processing',)

# collection_dataset -> collectionname. Immutable by decision D1, so cached forever.
_COLLECTION_OF_DATASET: dict[str, str] = {}


class UnknownDatasetError(KeyError):
    """Raised when a ``collection_dataset`` has no row in the dataset registry."""


def validate_collectionname(collectionname: str) -> str:
    """Return ``collectionname`` unchanged, or raise ``ValueError``.

    This is the last line of defence against SQL injection through a database name:
    ClickHouse cannot bind a database name as a parameter, so the name is always
    string-interpolated and must be validated before it reaches any statement.
    """
    if not isinstance(collectionname, str):
        raise ValueError(f'collectionname must be a string, got {type(collectionname).__name__}')
    if not collectionname:
        raise ValueError('collectionname must not be empty')
    if len(collectionname) > MAX_COLLECTIONNAME_LENGTH:
        raise ValueError(
            f'collectionname must be at most {MAX_COLLECTIONNAME_LENGTH} characters, '
            f'got {len(collectionname)}'
        )
    if not _COLLECTIONNAME_RE.match(collectionname):
        raise ValueError(
            f'collectionname {collectionname!r} is not a valid slug: only [a-z0-9_] allowed'
        )
    if _SHARD_SUFFIX_RE.search(collectionname):
        raise ValueError(
            f'collectionname {collectionname!r} must not end in _<digits>: '
            'that would collide with a Manticore shard name'
        )
    for suffix in RESERVED_COLLECTIONNAME_SUFFIXES:
        if collectionname.endswith(suffix):
            raise ValueError(
                f'collectionname {collectionname!r} must not end in {suffix!r}: '
                'reserved Manticore table suffix'
            )
    if collectionname in RESERVED_COLLECTIONNAMES:
        raise ValueError(f'collectionname {collectionname!r} is reserved')
    return collectionname


def collection_db_name(collectionname: str) -> str:
    """``Hoover4_Collection_<collectionname>``, after validating the name."""
    return COLLECTION_DB_PREFIX + validate_collectionname(collectionname)


def _client(database: str):
    return clickhouse_connect.get_client(
        host=CLICKHOUSE_HOST,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASS,
        database=database,
        settings=dict(CLIENT_SETTINGS),
    )


@contextmanager
def _client_ctx(database: str):
    client = _client(database)
    try:
        yield client
    finally:
        try:
            client.close()
        except Exception:
            pass


@contextmanager
def get_global_client():
    """Client bound to :data:`GLOBAL_DB`."""
    with _client_ctx(GLOBAL_DB) as client:
        yield client


@contextmanager
def get_collection_client(collectionname: str):
    """Client bound to this collection's database."""
    with _client_ctx(collection_db_name(collectionname)) as client:
        yield client


@contextmanager
def get_client_for_dataset(collection_dataset: str):
    """Client bound to the database of the collection owning ``collection_dataset``."""
    with get_collection_client(resolve_collection(collection_dataset)) as client:
        yield client


def resolve_collection(collection_dataset: str) -> str:
    """Return the collectionname owning ``collection_dataset``.

    Cached forever in-process: a dataset's collection is fixed at creation (D1).
    Never falls back to the global database - routing collection data into
    ``Hoover4_Processing`` is the worst possible failure mode here, so an unknown
    dataset raises instead.
    """
    cached = _COLLECTION_OF_DATASET.get(collection_dataset)
    if cached is not None:
        return cached

    with get_global_client() as client:
        rows = client.query(
            'SELECT collectionname FROM dataset FINAL '
            'WHERE collection_dataset = {cd:String} AND is_deleted = 0 LIMIT 1',
            parameters={'cd': collection_dataset},
        ).result_rows

    if not rows or not rows[0][0]:
        raise UnknownDatasetError(
            f'dataset {collection_dataset!r} has no collection in '
            f'{GLOBAL_DB}.dataset - cannot pick a collection database'
        )

    collectionname = rows[0][0]
    _COLLECTION_OF_DATASET[collection_dataset] = collectionname
    return collectionname


def list_collections() -> list[str]:
    """Non-deleted collectionnames, sorted."""
    with get_global_client() as client:
        rows = client.query(
            'SELECT collectionname FROM collections FINAL '
            'WHERE is_deleted = 0 ORDER BY collectionname'
        ).result_rows
    return [r[0] for r in rows]


def get_server_setting(key: str) -> str | None:
    """The current value of a ``server_settings`` key, or ``None`` when never written.

    ``server_settings`` is a ReplacingMergeTree versioned by ``updated_at``, so the
    current value is the argMax. Readers of the embeddings probe
    (``embeddings_serving_model`` / ``embeddings_serving_dim``) go through here — the
    probed value is the truth about what the GPU tier serves, and the ini is only the
    request.
    """
    with get_global_client() as client:
        rows = client.query(
            'SELECT argMax(value, updated_at) FROM server_settings WHERE key = {k:String}',
            parameters={'k': key},
        ).result_rows
    value = rows[0][0] if rows else None
    return value or None


def _cluster():
    from clickhouse_migrations.clickhouse_cluster import ClickhouseCluster

    return ClickhouseCluster(CLICKHOUSE_HOST, CLICKHOUSE_USER, CLICKHOUSE_PASS)


def migrate_collection(collectionname: str) -> str:
    """Create this collection's database if needed and apply the collection migrations.

    Idempotent, and the hook used whenever a collection is created.
    Returns the database name.
    """
    db_name = collection_db_name(collectionname)
    _cluster().migrate(
        db_name,
        COLLECTION_MIGRATIONS_PATH,
        cluster_name=None,
        create_db_if_no_exists=True,
        multi_statement=True,
    )
    return db_name


def drop_collection_db(collectionname: str) -> str:
    """``DROP DATABASE IF EXISTS`` for this collection. Destructive and irreversible."""
    db_name = collection_db_name(collectionname)
    with get_global_client() as client:
        client.command(f'DROP DATABASE IF EXISTS `{db_name}`')
    _COLLECTION_OF_DATASET.clear()
    log.warning('Dropped collection database %s', db_name)
    return db_name


def clickhouse_migrate():
    """Migrate the global database, then every non-deleted collection's database.

    Safe to run repeatedly and on a fresh install with zero collections.
    """
    _cluster().migrate(
        GLOBAL_DB,
        GLOBAL_MIGRATIONS_PATH,
        cluster_name=None,
        create_db_if_no_exists=True,
        multi_statement=True,
    )
    log.info('Migrated global database %s', GLOBAL_DB)

    collections = list_collections()
    for collectionname in collections:
        db_name = migrate_collection(collectionname)
        log.info('Migrated collection database %s', db_name)

    log.info('Migrated global + %d collection databases', len(collections))


if __name__ == "__main__":
    clickhouse_migrate()
