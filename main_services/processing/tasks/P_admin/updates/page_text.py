"""Replace indexed page text that ended at a NUL byte of the stored text."""

from temporalio import activity

from tasks.heartbeat import with_heartbeat, stop_if_worker_is_stopping
from tasks.P_admin.updates.entities import EntityUpdateParams, normalize_page_mvas

_PAGES = 100


def stale_page_files(client, collectionname: str, collection_dataset: str, rewrite: bool = False) -> set[str]:
    """The files with a pages row that differs from the indexed copy of a page with a NUL byte.

    `rewrite` replaces each such row. Each row is read alone, because a wide `id IN` read of
    Manticore 29.9.0 returned another row's text.
    """
    from database.manticore import get_manticore_client, indexed_text, manticore_execute, shard_table_from_name
    from tasks.P6_index_data.activities import pages_replace_params, pages_replace_sql, pages_row_id
    from tasks.plan_utils import clean_text
    from tasks.text_sources import fetch_text_batch

    stale: set[str] = set()
    after = ("", "", 0)
    with get_manticore_client() as connection:
        while True:
            stop_if_worker_is_stopping()
            keys = client.query(
                "SELECT DISTINCT file_hash, extracted_by, page_id FROM text_content "
                "WHERE collection_dataset = {cd:String} AND position(text, char(0)) > 0 "
                "AND file_hash IN (SELECT hash FROM vfs_files FINAL WHERE collection_dataset = {cd:String} "
                "AND is_deleted = 0) "
                "AND (file_hash, extracted_by, page_id) > ({hash:String}, {source:String}, {page:UInt32}) "
                f"ORDER BY file_hash, extracted_by, page_id LIMIT {_PAGES}",
                parameters={"cd": collection_dataset, "hash": after[0], "source": after[1],
                            "page": after[2]}).result_rows
            if not keys:
                return stale
            assignments = dict(client.query(
                "SELECT file_hash, shard_name FROM manticore_shard_assignments FINAL "
                "WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)}",
                parameters={"cd": collection_dataset,
                            "hashes": sorted({key[0] for key in keys})}).result_rows)
            for page in fetch_text_batch(client, collection_dataset, [tuple(key) for key in keys]):
                file_hash, source, page_id = page["file_hash"], page["extracted_by"], int(page["page_id"])
                if file_hash not in assignments:
                    continue
                table = shard_table_from_name(assignments[file_hash])
                row_id = pages_row_id(collection_dataset, file_hash, source, page_id)
                cursor = connection.cursor()
                cursor.execute(f"SELECT * FROM {table} WHERE id = {row_id}")
                rows = [dict(zip(cursor.column_names, values)) for values in cursor.fetchall()]
                wanted = indexed_text(clean_text(page["text"]))
                if not rows or rows[0]["page_text"] == wanted:
                    continue
                stale.add(file_hash)
                if rewrite:
                    row = {**rows[0], "page_text": wanted}
                    normalize_page_mvas(row)
                    manticore_execute(connection, pages_replace_sql(table, row),
                                      pages_replace_params(collection_dataset, row))
            connection.commit()
            after = tuple(keys[-1])
            if len(keys) < _PAGES:
                return stale


@activity.defn
@with_heartbeat
def rewrite_page_text(params: EntityUpdateParams) -> int:
    from database.clickhouse import get_collection_client

    with get_collection_client(params.collectionname) as client:
        return len(stale_page_files(client, params.collectionname, params.collection_dataset, rewrite=True))
