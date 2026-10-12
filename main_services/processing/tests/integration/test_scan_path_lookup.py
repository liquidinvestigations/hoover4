"""Integration test: the disk scan finds stored paths whatever characters they contain.

A path is corpus content. The scan looks up the paths it already stored before it writes
new rows, and that lookup once put each path into the SQL text with a quote escape that
ClickHouse does not accept for a backslash. A name ending in a backslash failed the scan,
and a crafted name changed the query. A folder with long paths also failed, because the
lookup passed the 256 KiB statement limit.

Requires the docker stack. Run inside the worker container:
``docker exec -it hoover4-worker uv run pytest tests/integration/test_scan_path_lookup.py --integration -q``
"""

import pytest

from database.clickhouse import get_collection_client
from tasks.P0_scan_disk.activities import (
    IngestFilesBatchParams,
    InsertVfsDirectoriesParams,
    ingest_files_batch,
    insert_vfs_directories,
)

pytestmark = pytest.mark.integration

#: Names that the doubled-quote escape broke or that changed the statement.
HOSTILE_NAMES = [
    "O'Brien.txt",
    "ends-in-backslash\\",
    "quote\\'inside.txt",
    "x\\') OR 1=1 -- .txt",
    "tab\tand newline\n.txt",
    "{cd:String}.txt",
]


def _stored(collectionname: str, table: str, collection_dataset: str) -> set[str]:
    with get_collection_client(collectionname) as client:
        rows = client.query(
            f"SELECT path FROM {table} FINAL WHERE collection_dataset = {{cd:String}}",
            parameters={"cd": collection_dataset},
        ).result_rows
    return {row[0] for row in rows}


def test_hostile_file_names_are_stored_once(temp_collection, tmp_path):
    collection_dataset = f"{temp_collection}_names"
    for name in HOSTILE_NAMES:
        (tmp_path / name).write_text(name)
    params = IngestFilesBatchParams(
        collectionname=temp_collection,
        collection_dataset=collection_dataset,
        dataset_path=str(tmp_path),
        file_paths=["/" + name for name in HOSTILE_NAMES],
    )

    assert ingest_files_batch(params).startswith(f"ingested {len(HOSTILE_NAMES)} files")
    assert _stored(temp_collection, "vfs_files", collection_dataset) == {"/" + n for n in HOSTILE_NAMES}
    # The second pass reads every path back through the lookup and finds nothing to do.
    assert ingest_files_batch(params) == f"0 files ({len(HOSTILE_NAMES)} unchanged)"


def test_a_full_range_of_long_folder_paths_is_inserted_once(temp_collection):
    collection_dataset = f"{temp_collection}_dirs"
    # 500 entries is one listing range. 600 bytes each is 300 KB of paths, more than
    # the statement limit and more than one query parameter value can hold.
    dir_paths = [f"/{'d' * 200}/{'e' * 200}/{'f' * 190}-{i:04d}" for i in range(500)]
    dir_paths[0] = "/O'Brien\\"
    params = InsertVfsDirectoriesParams(temp_collection, collection_dataset, dir_paths)

    assert insert_vfs_directories(params) == len(dir_paths)
    assert insert_vfs_directories(params) == 0
    assert _stored(temp_collection, "vfs_directories", collection_dataset) == set(dir_paths)
