"""The Manticore schema operations and the request checks of the schema proxy.

No Manticore runs here. The statements of each operation are captured from `_execute_ddl`.
"""

import json

import pytest

from database import manticore, manticore_schema
from database.manticore_schema import Refused, handle, run

TOKEN = "t" * 40


@pytest.fixture
def daemon(monkeypatch):
    """Capture the statements, and give each endpoint a fixed table list."""
    monkeypatch.setenv("HOOVER4_MANTICORE_TABLE_PREFIX", "zone_a_")
    monkeypatch.delenv("MANTICORE_SCHEMA_URL", raising=False)
    state = {"statements": [], "tables": {manticore.TEXT: [], manticore.VECTORS: []}}
    monkeypatch.setattr(manticore, "_execute_ddl",
                        lambda sql, endpoint=manticore.TEXT: state["statements"].append((endpoint, " ".join(sql.split()))))
    monkeypatch.setattr(manticore, "_list_all_tables", lambda endpoint=manticore.TEXT: list(state["tables"][endpoint]))
    return state


def test_create_operations_build_names_from_the_own_prefix(daemon):
    assert run("create_pages_table", {"collection": "demo", "shard": 2}) == "zone_a_demo_2_pages"
    assert run("create_vectors_table", {"collection": "demo", "shard": 2, "dims": 384}) == "zone_a_demo_2_vectors"
    assert run("create_vfs_table", {"collection": "demo"}) == "zone_a_demo_vfs"
    assert run("create_entities_table", {"collection": "demo"}) == "zone_a_demo_entities"
    endpoints = [e for e, _ in daemon["statements"]]
    assert endpoints == [manticore.TEXT, manticore.VECTORS, manticore.TEXT, manticore.TEXT]
    assert daemon["statements"][0][1].startswith("create table if not exists zone_a_demo_2_pages(")
    assert "knn_dims='384'" in daemon["statements"][1][1]


@pytest.mark.parametrize("operation, arguments", [
    ("create_pages_table", {"collection": "zone_b_demo", "shard": 0}),
    ("create_pages_table", {"collection": "demo", "shard": True}),
    ("create_pages_table", {"collection": "Demo", "shard": 1}),
    ("create_pages_table", {"collection": "demo; drop table x", "shard": 1}),
    ("create_pages_table", {"collection": "demo_1", "shard": 1}),
    ("create_vectors_table", {"collection": "demo", "shard": 1, "dims": 0}),
    ("create_vectors_table", {"collection": "demo", "shard": 1, "dims": "384"}),
    ("create_vfs_table", {"collection": 5}),
])
def test_refused_arguments(daemon, operation, arguments):
    with pytest.raises(Refused):
        run(operation, arguments)
    assert daemon["statements"] == []


def test_unknown_operation_and_wrong_argument_names_are_refused(daemon):
    for operation, arguments in [("create_distributed_table", {"name": "d", "local": ["zone_b_demo_1_pages"]}),
                                 ("drop_table", {"table": "zone_a_demo_1_pages"}),
                                 ("sql", {"statement": "DROP TABLE zone_b_demo_vfs"}),
                                 ("create_vfs_table", {"collection": "demo", "table": "zone_b_demo_vfs"}),
                                 ("create_vfs_table", {}),
                                 ("create_vfs_table", ["demo"]),
                                 (["create_vfs_table"], {"collection": "demo"})]:
        with pytest.raises(Refused):
            run(operation, arguments)
    assert daemon["statements"] == []


def test_add_pages_column_takes_the_type_of_the_pages_ddl(daemon):
    assert run("add_pages_column", {"table": "zone_a_demo_3_pages", "column": "virus_hit"}) == {
        "table": "zone_a_demo_3_pages", "column": "virus_hit", "type": "int"}
    assert daemon["statements"] == [(manticore.TEXT, "ALTER TABLE zone_a_demo_3_pages ADD COLUMN virus_hit int")]


@pytest.mark.parametrize("table, column", [
    ("zone_b_demo_3_pages", "virus_hit"),
    ("zone_a_demo_3_vectors", "virus_hit"),
    ("zone_a_demo_vfs", "virus_hit"),
    ("zone_a_demo_03_pages", "virus_hit"),
    ("zone_a_demo_3_pages", "secret int, x"),
    ("zone_a_demo_3_pages", "not_a_column"),
    ("zone_a_demo_3_pages; drop table zone_b_x", "virus_hit"),
])
def test_add_pages_column_refuses_other_tables_and_columns(daemon, table, column):
    with pytest.raises(Refused):
        run("add_pages_column", {"table": table, "column": column})
    assert daemon["statements"] == []


def test_page_columns_match_the_update_selector():
    from tasks.P_admin.updates.selectors import required_page_columns

    assert manticore_schema.page_columns() == dict(required_page_columns())


def test_drop_collection_tables_drops_only_the_tables_of_the_collection(daemon):
    daemon["tables"][manticore.TEXT] = ["zone_a_demo_1_pages", "zone_a_demo_vfs", "zone_a_demo_entities",
                                        "zone_a_demo_x_1_pages", "zone_a_other_vfs"]
    daemon["tables"][manticore.VECTORS] = ["zone_a_demo_1_vectors", "zone_a_demo_x_1_vectors"]
    dropped = run("drop_collection_tables", {"collection": "demo"})
    assert sorted(dropped) == ["zone_a_demo_1_pages", "zone_a_demo_1_vectors", "zone_a_demo_entities", "zone_a_demo_vfs"]
    assert (manticore.VECTORS, "drop table if exists zone_a_demo_1_vectors") in daemon["statements"]
    assert len(daemon["statements"]) == 4


def test_drop_collection_vector_tables(daemon):
    daemon["tables"][manticore.VECTORS] = ["zone_a_demo_1_vectors", "zone_a_demo_2_vectors", "zone_a_demox_1_vectors"]
    assert run("drop_collection_vector_tables", {"collection": "demo"}) == ["zone_a_demo_1_vectors", "zone_a_demo_2_vectors"]
    assert all(endpoint == manticore.VECTORS for endpoint, _ in daemon["statements"])


def test_migrate_creates_the_tables_and_drops_the_earlier_vectors_tables_of_the_prefix(daemon):
    daemon["tables"][manticore.TEXT] = ["zone_a_demo_1_vectors", "other_demo_1_vectors", "zone_a_demo_1_pages"]
    result = run("migrate", {"collections": {"demo": [1, 2], "empty": []}})
    assert result == {"collections": 2, "shards": 2, "dropped": ["zone_a_demo_1_vectors"]}
    created = [s.split("(")[0].split()[-1] for _, s in daemon["statements"] if s.startswith("create")]
    assert created == ["zone_a_demo_vfs", "zone_a_demo_entities", "zone_a_demo_1_pages", "zone_a_demo_2_pages",
                       "zone_a_empty_vfs", "zone_a_empty_entities"]
    assert (manticore.TEXT, "drop table if exists zone_a_demo_1_vectors") in daemon["statements"]
    for collections in ({"demo": 1}, ["demo"], {"demo": [0]}, {"bad name": [1]}):
        with pytest.raises(Refused):
            run("migrate", {"collections": collections})


def test_proxy_requests(daemon):
    body = json.dumps({"operation": "create_vfs_table", "arguments": {"collection": "demo"}}).encode()
    assert handle(TOKEN, f"Bearer {TOKEN}", body) == (200, {"result": "zone_a_demo_vfs"})
    assert handle(TOKEN, "Bearer wrong", body)[0] == 401
    assert handle(TOKEN, "", body)[0] == 401
    assert handle(TOKEN, f"Bearer {TOKEN}", b"not json")[0] == 400
    assert handle(TOKEN, f"Bearer {TOKEN}", json.dumps({"operation": "create_vfs_table"}).encode())[0] == 400
    sql = json.dumps({"operation": "create_vfs_table", "arguments": {"collection": "demo"}, "sql": "DROP TABLE x"}).encode()
    assert handle(TOKEN, f"Bearer {TOKEN}", sql)[0] == 400
    assert len(daemon["statements"]) == 1


def test_proxy_reports_a_manticore_error(daemon, monkeypatch):
    def fail(sql, endpoint=manticore.TEXT):
        raise RuntimeError("1064 permission denied")
    monkeypatch.setattr(manticore, "_execute_ddl", fail)
    status, payload = handle(TOKEN, f"Bearer {TOKEN}", json.dumps(
        {"operation": "create_vfs_table", "arguments": {"collection": "demo"}}).encode())
    assert status == 502 and "permission denied" in payload["error"]


def test_callers_use_the_proxy_when_it_is_configured(monkeypatch):
    """With MANTICORE_SCHEMA_URL the module sends each schema change to the proxy and runs no statement itself."""
    sent = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return json.dumps({"result": self.payload}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(request, timeout):
        sent.append((request.full_url, request.get_header("Authorization"), json.loads(request.data)))
        return Response("zone_a_demo_1_pages")

    monkeypatch.setenv("MANTICORE_SCHEMA_URL", "http://manticore-schema:8080")
    monkeypatch.setenv("MANTICORE_SCHEMA_TOKEN", TOKEN)
    monkeypatch.setenv("HOOVER4_MANTICORE_TABLE_PREFIX", "zone_a_")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr(manticore, "_execute_ddl", lambda *a, **k: pytest.fail("a statement ran in the caller"))
    assert manticore.create_shard_tables("demo", 1) == "zone_a_demo_1_pages"
    manticore.add_pages_column("zone_a_demo_1_pages", "virus_hit")
    assert sent == [
        ("http://manticore-schema:8080/operation", f"Bearer {TOKEN}",
         {"operation": "create_pages_table", "arguments": {"collection": "demo", "shard": 1}}),
        ("http://manticore-schema:8080/operation", f"Bearer {TOKEN}",
         {"operation": "add_pages_column", "arguments": {"table": "zone_a_demo_1_pages", "column": "virus_hit"}}),
    ]


def test_proxy_refusal_reaches_the_caller(monkeypatch):
    import io
    import urllib.error

    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(b'{"error": "unknown operation"}'))

    monkeypatch.setenv("MANTICORE_SCHEMA_URL", "http://manticore-schema:8080")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(RuntimeError, match="status 400: unknown operation"):
        manticore.create_vfs_table("demo")


# ----------------------------------------------------------------------------------------------------------------------
# status, export_tables and import_tables
# ----------------------------------------------------------------------------------------------------------------------

STATUS_TOKEN = "s" * 40


class FakeCursor:
    """The SHOW STATUS rows and the FREEZE answers of a daemon whose files are in data_root."""

    def __init__(self, data_root=None):
        self.data_root = data_root
        self.rows = []
        self.statements = []

    def execute(self, sql):
        self.statements.append(sql)
        if sql == "SHOW STATUS":
            self.rows = [("uptime", "7"), ("connections", "99"), ("workers_active", "2"), ("command_search", "5")]
        elif sql.startswith("FREEZE "):
            table = sql.split()[1]
            folder = self.data_root / table
            self.rows = [(f"{manticore_files.DAEMON_DATA_ROOT}/{table}/{p.name}", "") for p in sorted(folder.iterdir())]
        else:
            self.rows = []

    def fetchall(self):
        return self.rows


def fake_client(cursor):
    import contextlib

    class Connection:
        def cursor(self):
            return cursor

    @contextlib.contextmanager
    def client(endpoint=manticore.TEXT):
        yield Connection()
    return client


from database import manticore_files  # noqa: E402


def test_status_returns_only_the_panel_counters_of_both_daemons(daemon, monkeypatch):
    monkeypatch.setattr(manticore, "get_manticore_client", fake_client(FakeCursor()))
    result = run("status", {})
    assert set(result) == {"manticore", "manticore-vectors"}
    assert result["manticore"] == [{"Counter": "uptime", "Value": "7"}, {"Counter": "workers_active", "Value": "2"}]
    with pytest.raises(Refused):
        run("status", {"table": "zone_b_demo_vfs"})
    assert daemon["statements"] == []


def test_the_status_token_allows_the_status_operation_only(daemon, monkeypatch):
    monkeypatch.setattr(manticore, "get_manticore_client", fake_client(FakeCursor()))
    status = json.dumps({"operation": "status", "arguments": {}}).encode()
    schema = json.dumps({"operation": "create_vfs_table", "arguments": {"collection": "demo"}}).encode()
    assert handle(TOKEN, f"Bearer {STATUS_TOKEN}", status, STATUS_TOKEN)[0] == 200
    assert handle(TOKEN, f"Bearer {TOKEN}", status, STATUS_TOKEN)[0] == 200
    for body in (schema,
                 json.dumps({"operation": "import_tables", "arguments": {"collection": "demo", "export": "x"}}).encode(),
                 json.dumps({"operation": ["status"], "arguments": {}}).encode()):
        assert handle(TOKEN, f"Bearer {STATUS_TOKEN}", body, STATUS_TOKEN)[0] == 403
    # Without a status token of the proxy, the status credential is not valid.
    assert handle(TOKEN, f"Bearer {STATUS_TOKEN}", status, "")[0] == 401
    assert handle(TOKEN, "Bearer ", status, "")[0] == 401
    assert daemon["statements"] == []


@pytest.fixture
def stores(tmp_path, monkeypatch, daemon):
    """A backup root, a daemon data folder with the tables of zone_a_demo, and the local backend over both."""
    backups, data, restore = tmp_path / "backups", tmp_path / "data", tmp_path / "data"
    backups.mkdir()
    for table, files in {"zone_a_demo_1_pages": {"meta": b'{"v": 1}', "0.spa": b"A" * 100, "settings": b"s"},
                         "zone_a_demo_vfs": {"meta": b'{"v": 2}', "ram": b"r"}}.items():
        (data / table).mkdir(parents=True)
        for suffix, content in files.items():
            (data / table / f"{table}.{suffix}").write_bytes(content)
    monkeypatch.setattr(manticore_files, "BACKUP_ROOT", str(backups))
    monkeypatch.setattr(manticore_files, "backend", lambda: manticore_files.LocalFiles(str(data), str(restore)))
    monkeypatch.setattr(manticore_files.time, "sleep", lambda s: None)
    cursor = FakeCursor(data)
    monkeypatch.setattr(manticore, "get_manticore_client", fake_client(cursor))
    monkeypatch.setattr(manticore, "list_collection_tables",
                        lambda c: ["zone_a_demo_1_pages", "zone_a_demo_1_vectors", "zone_a_demo_vfs"])
    return {"backups": backups, "data": data, "cursor": cursor}


def exported(stores, name="demo-export"):
    folder = stores["backups"] / name
    (folder / "manticore").mkdir(parents=True)
    detail = run("export_tables", {"collection": "demo", "export": name})
    (folder / "manifest.json").write_text(json.dumps({"collectionname": "demo", "stores": {"manticore": detail}}))
    return folder, detail


def test_export_then_import_into_another_prefix(stores, daemon, monkeypatch):
    folder, detail = exported(stores)
    assert [a["table"] for a in detail["tables"]] == ["zone_a_demo_1_pages", "zone_a_demo_vfs"]
    assert detail["source_bytes"] == len(b'{"v": 1}') + 100 + 1 + len(b'{"v": 2}') + 1
    assert stores["cursor"].statements == ["FREEZE zone_a_demo_1_pages", "UNFREEZE zone_a_demo_1_pages",
                                           "FREEZE zone_a_demo_vfs", "UNFREEZE zone_a_demo_vfs"]
    staged = {}
    original = manticore._execute_ddl

    def ddl(sql, endpoint=manticore.TEXT):
        if sql.startswith("IMPORT TABLE"):
            path = sql.split("'")[1].replace(manticore_files.DAEMON_DATA_ROOT, str(stores["data"]))
            staged[sql.split()[2]] = sorted(p.name for p in __import__("pathlib").Path(path).parent.iterdir())
        original(sql, endpoint)
    monkeypatch.setattr(manticore, "_execute_ddl", ddl)
    monkeypatch.setenv("HOOVER4_MANTICORE_TABLE_PREFIX", "zone_c_")
    result = run("import_tables", {"collection": "demo", "export": "demo-export"})
    assert result == {"tables": ["zone_c_demo_1_pages", "zone_c_demo_vfs"], "skipped_vectors": 0}
    assert staged["zone_c_demo_1_pages"] == ["zone_c_demo_1_pages.0.spa", "zone_c_demo_1_pages.meta",
                                             "zone_c_demo_1_pages.settings"]
    statements = [s for _, s in daemon["statements"]]
    assert statements[0] == "DROP TABLE IF EXISTS zone_c_demo_1_pages"
    assert statements[1].startswith("IMPORT TABLE zone_c_demo_1_pages FROM '/var/lib/manticore/restore-")
    assert statements[1].endswith("/zone_c_demo_1_pages/zone_c_demo_1_pages'")
    # The stage is removed after the import.
    assert [p.name for p in stores["data"].iterdir() if p.name.startswith("restore-")] == []


@pytest.mark.parametrize("export", ["../backups", "/etc", "a/b", ".hidden", "missing", "", 5])
def test_export_and_import_refuse_a_folder_outside_the_backup_root(stores, daemon, export):
    for operation in ("export_tables", "import_tables"):
        with pytest.raises(Refused):
            run(operation, {"collection": "demo", "export": export})
    with pytest.raises(Refused):
        run("import_tables", {"collection": "demo", "export": "x", "table": "zone_b_demo_vfs"})
    assert daemon["statements"] == [] and stores["cursor"].statements == []


def test_import_refuses_a_manifest_that_leaves_the_export_or_names_other_files(stores, daemon):
    import io
    import tarfile

    import zstandard

    folder, detail = exported(stores)
    manifest = json.loads((folder / "manifest.json").read_text())

    def write(**changes):
        artifact = {**detail["tables"][1], **changes}
        (folder / "manifest.json").write_text(json.dumps({**manifest, "stores": {"manticore": {"tables": [artifact]}}}))

    for changes in ({"path": "../../data/zone_a_demo_vfs/zone_a_demo_vfs.meta"}, {"path": "/etc/passwd"},
                    {"table": "zone_b_other_vfs"}, {"table": "zone_a_demo_1_vectorsx"}):
        write(**changes)
        with pytest.raises(Refused):
            run("import_tables", {"collection": "demo", "export": "demo-export"})
    (folder / "manifest.json").write_text(json.dumps({**manifest, "collectionname": "other"}))
    with pytest.raises(Refused):
        run("import_tables", {"collection": "demo", "export": "demo-export"})
    # A member outside the table, or a damaged artifact, stops the import before IMPORT TABLE.
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        info = tarfile.TarInfo("../zone_b_demo_vfs.meta")
        info.size = 2
        tar.addfile(info, io.BytesIO(b"{}"))
    (folder / "manticore" / "evil.tar.zst").write_bytes(zstandard.ZstdCompressor().compress(raw.getvalue()))
    write(path="manticore/evil.tar.zst", sha256="")
    with pytest.raises(Refused):
        run("import_tables", {"collection": "demo", "export": "demo-export"})
    write(sha256="0" * 64)
    with pytest.raises(RuntimeError, match="does not match the checksum"):
        run("import_tables", {"collection": "demo", "export": "demo-export"})
    assert [s for _, s in daemon["statements"] if s.startswith(("IMPORT", "DROP"))] == []


def test_the_target_keeps_the_name_after_the_prefix(monkeypatch):
    monkeypatch.setenv("HOOVER4_MANTICORE_TABLE_PREFIX", "zone_a_")
    assert manticore_files.target_table("demo", "demo_3_pages") == "zone_a_demo_3_pages"
    assert manticore_files.target_table("demo", "zone_b_demo_vfs") == "zone_a_demo_vfs"
    assert manticore_files.target_table("b_demo", "zone_b_demo_entities") == "zone_a_b_demo_entities"
    for source in ("zone_b_demo_03_pages", "zone_b_demox_vfs", "demo_1_vectors", "zone_b_demo_vfs; drop"):
        with pytest.raises(manticore_files.FilesRefused):
            manticore_files.target_table("demo", source)


def test_the_service_backend_stages_below_the_user_of_the_process():
    files = manticore_files.ServiceFiles("http://manticore:9318", "zone_a_schema", "p")
    assert files.daemon_path("ab12", "zone_a_demo_vfs") == \
        "/var/lib/manticore/import/zone_a_schema/ab12/zone_a_demo_vfs/zone_a_demo_vfs"
