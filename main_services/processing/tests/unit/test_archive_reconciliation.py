"""Removed container descendants retain only reachable occurrences."""

from tasks.P3_parse_files import parse_archives
from tasks.P0_scan_disk import activities


def test_removed_nested_container_preserves_shared_live_content(monkeypatch):
    rows = [("", "/live.txt", "shared", 1, 0, ""),
            ("removed", "/nested.zip", "nested", 1, 0, ""),
            ("nested", "/dead.txt", "dead", 1, 0, ""),
            ("nested", "/shared.txt", "shared", 1, 0, ""),
            ("shared", "/child.txt", "shared-child", 1, 0, "")]
    tombstones = []

    class Client:
        def query(self, sql, parameters):
            selected = [row for row in rows if row[0] in parameters["parents"]]
            values = [(row[2],) for row in selected] if "SELECT DISTINCT hash" in sql else selected
            return type("Rows", (), {"result_rows": values})()

    monkeypatch.setattr(activities, "_tombstone_paths",
                        lambda client, dataset, gone, now, **kwargs: tombstones.extend(gone))
    count = parse_archives._reconcile_removed_descendants(Client(), "dataset", {"removed"})
    assert count == 3
    assert {(row["container_hash"], row["hash"]) for row in tombstones} == {
        ("removed", "nested"), ("nested", "dead"), ("nested", "shared")}
    assert all(row["hash"] != "shared-child" for row in tombstones)
