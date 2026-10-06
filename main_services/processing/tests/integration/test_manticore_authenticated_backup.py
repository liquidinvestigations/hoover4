"""Verify authenticated queries and collection table backup restoration."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import mysql.connector
import pytest
import requests

from database import manticore
from tasks.P_ops import backup, restore
from tasks.P_ops.params import ExportParams, ImportParams

pytestmark = pytest.mark.integration


def test_authenticated_backup_restores_rows_and_search(monkeypatch):
    host = os.getenv("MANTICORE_HOST", "manticore")
    url = os.getenv("MANTICORE_URL", "http://manticore:9308")
    for auth in (None, ("manticore", "wrong")):
        response = requests.post(url + "/sql", data={"query": "SHOW TABLES"},
                                 params={"mode": "raw"}, auth=auth, timeout=10)
        assert response.status_code == 401
    with pytest.raises(mysql.connector.Error):
        mysql.connector.connect(host=host, port=9306, user="manticore", password="wrong",
                                connection_timeout=5)
    # Operation telemetry is separate from the table artifact under verification.
    from database import operations
    monkeypatch.setattr(operations, "merge_detail", lambda *_a, **_k: None)
    monkeypatch.setattr(operations, "update_operation", lambda *_a, **_k: None)
    monkeypatch.setattr(operations, "get_operation", lambda *_a, **_k: {})
    table = "authbackup_1_pages"
    monkeypatch.setattr(manticore, "list_collection_tables", lambda _collection: [table])
    monkeypatch.setattr(restore, "MANTICORE_RESTORE_ROOT", backup.MANTICORE_DATA_ROOT)
    with manticore.get_manticore_client() as client:
        cursor = client.cursor()
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
        cursor.execute(f"CREATE TABLE {table} (page_text text, n int) min_infix_len='3'")
        for i in range(1, 51):
            cursor.execute(f"INSERT INTO {table} (id, page_text, n) VALUES ({i}, 'evidence document', {i})")
        client.commit()
        cursor.execute(f"FLUSH RAMCHUNK {table}")
    try:
        with TemporaryDirectory() as directory:
            Path(directory, "manticore").mkdir()
            exported = backup.export_manticore(ExportParams("auth-export", "authbackup", directory=directory))
            assert exported.bytes_written > 0
            manifest = {"format": backup.FORMAT, "format_version": backup.FORMAT_VERSION,
                        "stores": {"manticore": exported.detail}}
            path = Path(directory, "manifest.json")
            path.write_text(json.dumps({**manifest, "format_version": 1}))
            with pytest.raises(ValueError, match="version 2"):
                restore.read_manifest(directory)
            path.write_text(json.dumps(manifest))
            restored = restore.import_manticore(ImportParams("auth-import", "authbackup", directory=directory))
            assert restored.detail["tables"] == [table]
            with manticore.get_manticore_client() as client:
                cursor = client.cursor()
                cursor.execute(f"SELECT count(*) FROM {table} WHERE MATCH('*viden*')")
                assert cursor.fetchall() == [(50,)]
            response = requests.post(url + "/sql", params={"mode": "raw"},
                data={"query": f"SELECT id FROM {table} WHERE MATCH('document') LIMIT 100"},
                auth=("manticore", "manticore"), timeout=10)
            assert response.status_code == 200
            assert len(response.json()[0]["data"]) == 50
    finally:
        with manticore.get_manticore_client() as client:
            client.cursor().execute(f"DROP TABLE IF EXISTS {table}")
