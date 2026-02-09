"""ClickHouse client helpers and migrations for processing storage."""

import clickhouse_connect
import logging
from contextlib import contextmanager
log = logging.getLogger(__name__)

CLICKHOUSE_HOST = 'clickhouse'
CLICKHOUSE_USER = 'hoover4'
CLICKHOUSE_PASS = 'hoover4'
CLICKHOUSE_DB = 'Hoover4_Processing'

@contextmanager
def get_clickhouse_client():
    client = clickhouse_connect.get_client(
        host=CLICKHOUSE_HOST,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASS,
        database=CLICKHOUSE_DB,
        settings={
            'async_insert': 1,
            'wait_for_async_insert': 1,
        }
    )
    try:
        yield client
    finally:
        try:
            client.close()
        except Exception:
            pass

def clickhouse_migrate():
    from clickhouse_migrations.clickhouse_cluster import ClickhouseCluster
    import pathlib
    import os

    cluster = ClickhouseCluster(
        CLICKHOUSE_HOST,
        CLICKHOUSE_USER,
        CLICKHOUSE_PASS,
    )
    parent_path =  pathlib.Path(__file__).parent.resolve()
    db_path = os.path.join(parent_path, 'clickhouse_migrations')
    cluster.migrate(CLICKHOUSE_DB, db_path, cluster_name=None,create_db_if_no_exists=True, multi_statement=True)
    log.info('Migrated tables OK')


if __name__ == "__main__":
    clickhouse_migrate()