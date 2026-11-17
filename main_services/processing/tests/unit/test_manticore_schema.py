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
    partial = next(t for t in staged if t.startswith("zone_c_demo_1_pages_partial"))
    assert manticore_files.is_partial_table(partial)
    assert staged[partial] == [f"{partial}.0.spa", f"{partial}.meta", f"{partial}.settings"]
    statements = [s for _, s in daemon["statements"]]
    # Each table is imported under its partial name, and renamed onto its target after the last import.
    assert statements[0].startswith(f"IMPORT TABLE {partial} FROM '/var/lib/manticore/restore-")
    assert statements[0].endswith(f"/{partial}/{partial}'")
    assert statements[1].startswith("IMPORT TABLE zone_c_demo_vfs_partial")
    assert statements[2:] == ["DROP TABLE IF EXISTS zone_c_demo_1_pages", f"ALTER TABLE {partial} RENAME zone_c_demo_1_pages",
                              "DROP TABLE IF EXISTS zone_c_demo_vfs",
                              f"ALTER TABLE {statements[1].split()[2]} RENAME zone_c_demo_vfs"]
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


# ----------------------------------------------------------------------------------------------------------------------
# Cancel and cleanup of an export or an import
# ----------------------------------------------------------------------------------------------------------------------

def test_partial_table_names_cannot_match_a_complete_table():
    assert manticore_files.partial_table("zone_a_demo_1_pages", "0123456789abcdef") == \
        "zone_a_demo_1_pages_partial0123456789abcdef"
    for complete in ("zone_a_demo_1_pages", "zone_a_demo_vfs", "zone_a_demo_entities", "zone_a_demo_1_vectors",
                     "zone_a_partial0123456789abcdef_vfs", "zone_a_x_partial0123456789abcdef_1_pages"):
        assert not manticore_files.is_partial_table(complete)
    with pytest.raises(manticore_files.FilesRefused):
        manticore_files.partial_table("zone_a_demo_vfs", "short")


def test_a_cancelled_export_releases_the_freeze_and_removes_its_artifacts(stores):
    folder = stores["backups"] / "demo-export"
    folder.mkdir()
    checks = []

    def cancelled():
        checks.append(1)
        return len(checks) > 2  # the first table and its first file pass
    with pytest.raises(manticore_files.Cancelled):
        run("export_tables", {"collection": "demo", "export": "demo-export"}, cancelled=cancelled)
    assert stores["cursor"].statements == ["FREEZE zone_a_demo_1_pages", "UNFREEZE zone_a_demo_1_pages"]
    assert not (folder / "manticore").exists()


def test_a_cancelled_import_drops_its_partial_tables_and_removes_its_stage(stores, daemon):
    exported(stores)
    imports = []

    def cancelled():
        return len(imports) >= 1  # cancel after the first IMPORT TABLE
    original = manticore._execute_ddl

    def ddl(sql, endpoint=manticore.TEXT):
        if sql.startswith("IMPORT TABLE"):
            imports.append(sql.split()[2])
        original(sql, endpoint)
    import database.manticore as module
    module._execute_ddl = ddl
    try:
        with pytest.raises(manticore_files.Cancelled):
            run("import_tables", {"collection": "demo", "export": "demo-export"}, cancelled=cancelled)
    finally:
        module._execute_ddl = original
    statements = [s for _, s in daemon["statements"]]
    assert statements == [f"IMPORT TABLE {imports[0]} FROM '{statements[0].split(chr(39))[1]}'",
                          f"DROP TABLE IF EXISTS {imports[0]}"]
    assert manticore_files.is_partial_table(imports[0])
    assert not any("RENAME" in s for s in statements)
    assert [p.name for p in stores["data"].iterdir() if p.name.startswith("restore-")] == []


def test_a_failed_import_statement_drops_the_partial_table(stores, daemon, monkeypatch):
    exported(stores)
    statements = []

    def ddl(sql, endpoint=manticore.TEXT):
        statements.append(sql)
        if sql.startswith("IMPORT TABLE zone_a_demo_vfs_partial"):
            raise RuntimeError("1064 disk full")
    monkeypatch.setattr(manticore, "_execute_ddl", ddl)
    with pytest.raises(RuntimeError, match="disk full"):
        run("import_tables", {"collection": "demo", "export": "demo-export"})
    partials = [s.split()[2] for s in statements if s.startswith("IMPORT TABLE")]
    assert statements[2:] == [f"DROP TABLE IF EXISTS {p}" for p in partials]


@pytest.fixture
def proxy_tables():
    manticore_schema._RUNNING.clear()
    yield manticore_schema._RUNNING
    manticore_schema._RUNNING.clear()


def test_cancel_of_a_running_export_through_the_proxy(stores, daemon, monkeypatch, proxy_tables):
    import threading

    folder = stores["backups"] / "demo-export"
    folder.mkdir()
    inside, release = threading.Event(), threading.Event()
    original = manticore_files.add_file

    def slow_add_file(*args):
        inside.set()
        release.wait(10)
        return original(*args)
    monkeypatch.setattr(manticore_files, "add_file", slow_add_file)
    body = json.dumps({"operation": "export_tables", "arguments": {"collection": "demo", "export": "demo-export"},
                       "id": "op1"}).encode()
    answers = []
    worker = threading.Thread(target=lambda: answers.append(handle(TOKEN, f"Bearer {TOKEN}", body)))
    worker.start()
    assert inside.wait(10)
    assert set(proxy_tables) == {"op1"}
    # A second operation with the same id is refused while the first runs.
    assert handle(TOKEN, f"Bearer {TOKEN}", body) == (409, {"error": "the operation op1 runs already"})
    cancels = []
    canceller = threading.Thread(target=lambda: cancels.append(
        manticore_schema.handle_cancel(TOKEN, f"Bearer {TOKEN}", b'{"id": "op1"}')))
    canceller.start()
    while not proxy_tables["op1"].stop.is_set():
        pass
    release.set()
    canceller.join(10)
    worker.join(10)
    assert cancels == [(200, {"result": {"id": "op1", "state": "stopped"}})]
    assert answers == [(409, {"error": "the operation was cancelled"})]
    assert proxy_tables == {}
    assert stores["cursor"].statements == ["FREEZE zone_a_demo_1_pages", "UNFREEZE zone_a_demo_1_pages"]
    assert not (folder / "manticore").exists()
    # The operation has ended, so a second cancel finds nothing and succeeds.
    assert manticore_schema.handle_cancel(TOKEN, f"Bearer {TOKEN}", b'{"id": "op1"}') == (
        200, {"result": {"id": "op1", "state": "absent"}})


def test_cancel_of_an_unknown_or_ended_operation_succeeds(stores, daemon, proxy_tables):
    assert manticore_schema.handle_cancel(TOKEN, f"Bearer {TOKEN}", b'{"id": "neverstarted"}') == (
        200, {"result": {"id": "neverstarted", "state": "absent"}})
    exported(stores)
    body = json.dumps({"operation": "import_tables", "arguments": {"collection": "demo", "export": "demo-export"},
                       "id": "done1"}).encode()
    assert handle(TOKEN, f"Bearer {TOKEN}", body)[0] == 200
    assert manticore_schema.handle_cancel(TOKEN, f"Bearer {TOKEN}", b'{"id": "done1"}') == (
        200, {"result": {"id": "done1", "state": "absent"}})


def test_cancel_and_operation_id_requests_are_checked(daemon, proxy_tables):
    assert manticore_schema.handle_cancel(TOKEN, "Bearer wrong", b'{"id": "a"}')[0] == 401
    assert manticore_schema.handle_cancel(TOKEN, f"Bearer {STATUS_TOKEN}", b'{"id": "a"}')[0] == 401
    for body in (b'not json', b'{"id": "A"}', b'{"id": ""}', b'{"id": 5}', b'{"id": "a", "x": 1}', b'{}',
                 json.dumps({"id": "a" * 65}).encode()):
        assert manticore_schema.handle_cancel(TOKEN, f"Bearer {TOKEN}", body)[0] == 400
    for request in ({"operation": "create_vfs_table", "arguments": {"collection": "demo"}, "id": "a"},
                    {"operation": "export_tables", "arguments": {"collection": "demo", "export": "x"}, "id": "A-1"},
                    {"operation": "export_tables", "arguments": {"collection": "demo", "export": "x"}, "id": 1}):
        assert handle(TOKEN, f"Bearer {TOKEN}", json.dumps(request).encode())[0] == 400
    assert daemon["statements"] == [] and proxy_tables == {}


def test_the_proxy_removes_stages_and_partial_tables_of_its_prefix_at_start(daemon, monkeypatch, tmp_path):
    restore = tmp_path / "data"
    for name in ("restore-0123456789abcdef", "restore-fedcba9876543210", "zone_a_demo_vfs", "import"):
        (restore / name / "t").mkdir(parents=True)
    monkeypatch.setattr(manticore_files, "backend", lambda: manticore_files.LocalFiles(str(restore), str(restore)))
    daemon["tables"][manticore.TEXT] = ["zone_a_demo_vfs", "zone_a_demo_vfs_partial0123456789abcdef",
                                        "zone_a_demo_1_pages_partialfedcba9876543210", "zone_b_demo_vfs_partial0123456789abcdef",
                                        "zone_a_demo_1_pages", "zone_a_partial_vfs"]
    assert manticore_schema.start_cleanup() == {"dropped": ["zone_a_demo_vfs_partial0123456789abcdef",
                                                            "zone_a_demo_1_pages_partialfedcba9876543210"]}
    assert [s for _, s in daemon["statements"]] == ["DROP TABLE IF EXISTS zone_a_demo_vfs_partial0123456789abcdef",
                                                    "DROP TABLE IF EXISTS zone_a_demo_1_pages_partialfedcba9876543210"]
    assert sorted(p.name for p in restore.iterdir()) == ["import", "zone_a_demo_vfs"]


def test_the_proxy_does_not_start_while_the_leftovers_stay(daemon, monkeypatch):
    calls = []

    def fail():
        calls.append(1)
        raise OSError("the file service does not answer")
    monkeypatch.setattr(manticore_schema, "remove_leftovers", fail)
    with pytest.raises(SystemExit):
        manticore_schema.start_cleanup(attempts=3, pause=0)
    assert len(calls) == 3


def test_the_service_backend_removes_the_import_folder_of_its_user(monkeypatch):
    sent = []

    class Response:
        status = 200

        def read(self, *a):
            return b"{}"

    class Connection:
        def __init__(self, host, port, timeout):
            pass

        def request(self, method, path, body=None, headers=None):
            sent.append((method, path, headers["Authorization"]))

        def getresponse(self):
            return Response()

        def close(self):
            pass
    monkeypatch.setattr("http.client.HTTPConnection", Connection)
    manticore_files.ServiceFiles("http://manticore:9318", "zone_a_schema", "p").remove_all()
    assert [(m, p) for m, p, _ in sent] == [("DELETE", "/import")]


def test_an_exception_in_the_waiting_thread_cancels_the_proxy_operation(monkeypatch):
    """The Temporal SDK cancels a thread activity with an exception raised in its thread. The caller then sends the
    cancel of its operation id, and raises the exception again."""
    import ctypes
    import threading

    sent, released = [], threading.Event()

    def proxy_request(url, path, payload, timeout, name):
        sent.append((path, payload))
        if path == "/operation":
            released.wait(10)
            raise RuntimeError("The Manticore schema proxy refused export_tables with status 409")
        released.set()
        return {"id": payload["id"], "state": "stopped"}
    monkeypatch.setenv("MANTICORE_SCHEMA_URL", "http://manticore-schema:8080")
    monkeypatch.setattr(manticore, "_proxy_request", proxy_request)
    monkeypatch.setattr(manticore, "CANCEL_POLL_SECONDS", 0.05)
    waiting = threading.get_ident()

    class Cancelled(Exception):
        pass

    def raise_in_waiting_thread():
        while not sent:
            pass
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(waiting), ctypes.py_object(Cancelled))
    threading.Thread(target=raise_in_waiting_thread).start()
    with pytest.raises(Cancelled):
        manticore.schema_operation("export_tables", collection="demo", export="x")
    operation_id = sent[0][1]["id"]
    assert sent == [("/operation", {"operation": "export_tables", "arguments": {"collection": "demo", "export": "x"},
                                    "id": operation_id}),
                    ("/cancel", {"id": operation_id})]


def test_a_finished_proxy_operation_returns_its_result(monkeypatch):
    monkeypatch.setenv("MANTICORE_SCHEMA_URL", "http://manticore-schema:8080")
    monkeypatch.setattr(manticore, "_proxy_request", lambda url, path, payload, timeout, name: {"tables": [], "id": payload["id"]})
    result = manticore.schema_operation("import_tables", collection="demo", export="x")
    assert result["tables"] == [] and len(result["id"]) == 16
