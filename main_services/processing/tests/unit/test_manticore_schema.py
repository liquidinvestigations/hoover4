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
