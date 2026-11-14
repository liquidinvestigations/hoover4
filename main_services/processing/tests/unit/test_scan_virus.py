"""The antivirus stage against a fake scanner: every attempt status, and the effective verdict."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tasks.P3_parse_files import scan_virus


class _Scanner(BaseHTTPRequestHandler):
    answer = (200, {"status": "clean"})
    #: Answers that come before `answer`, one for each request.
    first_answers = []
    received = []

    def log_message(self, *args):
        return

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        type(self).received.append(len(self.rfile.read(length)))
        code, payload = type(self).first_answers.pop(0) if type(self).first_answers else type(self).answer
        body = json.dumps({"engine_version": "1.4.3", "database_version": "28170",
                           "config_fingerprint": "f", "signature": "", **payload}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(scan_virus, "RETRY_DELAYS", (0, 0))


@pytest.fixture
def scanner(monkeypatch, tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Scanner)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("CLAMAV_ENABLED", "true")
    monkeypatch.setenv("CLAMAV_URL", f"http://127.0.0.1:{server.server_port}")
    _Scanner.received = []
    _Scanner.first_answers = []
    path = tmp_path / "f.bin"
    path.write_bytes(b"x" * 1000)
    yield str(path)
    server.shutdown()


@pytest.mark.parametrize("answer, status, verdict, tries", [
    ((200, {"status": "clean"}), "completed", "clean", 1),
    ((200, {"status": "infected", "signature": "Eicar-Test-Signature"}), "completed", "infected", 1),
    ((200, {"status": "incomplete", "signature": "Heuristics.Limits.Exceeded.MaxScanSize"}), "incomplete", "", 1),
    ((502, {"status": "error", "error": "clamd down"}), "failed", "", 3),
])
def test_attempt_statuses(scanner, answer, status, verdict, tries):
    _Scanner.answer = answer
    row = scan_virus.scan_file("ds", "h", scanner, 1000)
    assert (row["attempt_status"], row["verdict"]) == (status, verdict)
    assert _Scanner.received == [1000] * tries
    assert row["database_version"] == "28170" and row["scan_version"] == scan_virus.SCAN_VERSION


def test_a_full_queue_is_tried_again(scanner):
    _Scanner.first_answers = [(503, {"status": "error", "error": "scanner queue is full"})]
    _Scanner.answer = (200, {"status": "clean"})
    row = scan_virus.scan_file("ds", "h", scanner, 1000)
    assert (row["attempt_status"], row["verdict"]) == ("completed", "clean")
    assert _Scanner.received == [1000, 1000]


def test_size_boundary_and_disabled(scanner, monkeypatch):
    assert scan_virus.scan_file("ds", "h", scanner, scan_virus.CLAMAV_MAX_FILE_BYTES + 1)["attempt_status"] == "skipped_size"
    monkeypatch.setenv("CLAMAV_ENABLED", "false")
    assert scan_virus.scan_file("ds", "h", scanner, 1000)["attempt_status"] == "skipped_disabled"
    assert _Scanner.received == []


def test_an_unreachable_scanner_is_a_failed_attempt(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAMAV_ENABLED", "true")
    monkeypatch.setenv("CLAMAV_URL", "http://127.0.0.1:9")
    path = tmp_path / "f"
    path.write_bytes(b"x")
    row = scan_virus.scan_file("ds", "h", str(path), 1)
    assert row["attempt_status"] == "failed" and "ConnectionError" in row["error"]


def test_result_order_is_monotonic():
    first = scan_virus.attempt_row("ds", "h", "completed", "infected")
    second = scan_virus.attempt_row("ds", "h", "failed")
    assert second["result_seq"] > first["result_seq"]


def test_effective_verdict_reads_completed_attempts_only():
    seen = {}

    class Client:
        def query(self, sql, parameters):
            seen["sql"] = sql
            return type("R", (), {"result_rows": [("h", "infected", "Eicar", "28170")]})()

    assert scan_virus.effective_verdicts(Client(), ["h"]) == {
        "h": {"verdict": "infected", "signature": "Eicar", "database_version": "28170"}}
    assert "attempt_status = 'completed'" in seen["sql"] and "argMax" in seen["sql"]


def test_stale_virus_attributes_groups_files_by_plan(monkeypatch):
    """Files whose search rows disagree with their verdict go back to indexing, by plan."""
    from contextlib import contextmanager

    from tasks.P_admin.updates import activities
    from tasks.P_admin.updates.params import TablePlansParams

    monkeypatch.setattr(activities, "_dataset_verdicts",
                        lambda c, d: {"inf1": "infected", "inf2": "infected", "ok1": "clean"})
    asked = []

    def rows_with_other_value(collectionname, dataset, hashes, value):
        asked.append((sorted(hashes), value))
        return {"inf1"} if value == 1 else {"ok1"}

    monkeypatch.setattr(activities, "_hashes_with_attribute", rows_with_other_value)

    class _Client:
        def query(self, sql, parameters, external_data=None):
            # The hashes travel in the request body, not in a query parameter.
            assert parameters == {"cd": "d"}
            assert external_data.files[0].data == b'["inf1"]\n["ok1"]'
            return type("R", (), {"result_rows": [("inf1", "p2"), ("ok1", "p1")]})()

    @contextmanager
    def client(_):
        yield _Client()

    import database.clickhouse
    monkeypatch.setattr(database.clickhouse, "get_collection_client", client)
    plans = activities.stale_virus_attributes.__wrapped__(TablePlansParams("op", "c", "d"))
    assert plans == {"p2": ["inf1"], "p1": ["ok1"]}
    assert asked == [(["inf1", "inf2"], 1), (["ok1"], 0)]


def test_stale_virus_attributes_send_many_hashes_in_the_request_body(monkeypatch):
    """A stale set above the 128 KiB parameter limit of ClickHouse leaves the URL empty of hashes."""
    from contextlib import contextmanager

    from tasks.P_admin.updates import activities
    from tasks.P_admin.updates.params import TablePlansParams

    hashes = [f"{i:064x}" for i in range(5000)]
    monkeypatch.setattr(activities, "_dataset_verdicts", lambda c, d: {h: "infected" for h in hashes})
    monkeypatch.setattr(activities, "_hashes_with_attribute", lambda c, d, h, v: set(h))
    seen = {}

    class _Client:
        def query(self, sql, parameters, external_data=None):
            seen.update(sql=sql, parameters=parameters, external=external_data)
            return type("R", (), {"result_rows": [(h, "p") for h in hashes]})()

    @contextmanager
    def client(_):
        yield _Client()

    import database.clickhouse
    monkeypatch.setattr(database.clickhouse, "get_collection_client", client)
    plans = activities.stale_virus_attributes.__wrapped__(TablePlansParams("op", "c", "d"))
    assert plans == {"p": hashes}
    assert len(repr(seen["parameters"])) < 100
    assert "Array(String)" not in seen["sql"]
    assert len(seen["external"].files[0].data) > 128 * 1024


def test_stale_virus_plan_hashes_compares_the_files_of_one_plan(monkeypatch):
    """Each plan page sends at most the files of one plan to Manticore and to Temporal."""
    from contextlib import contextmanager

    from tasks.P_admin.updates import activities
    from tasks.P_admin.updates.params import TablePlanParams

    asked = []

    def rows_with_other_value(collectionname, dataset, hashes, value):
        asked.append((hashes, value))
        return {"inf1"} if value == 1 else set()

    monkeypatch.setattr(activities, "_hashes_with_attribute", rows_with_other_value)
    seen = {}

    class _Client:
        def query(self, sql, parameters):
            seen.update(sql=sql, parameters=parameters)
            return type("R", (), {"result_rows": [("inf2", "infected"), ("inf1", "infected"), ("ok1", "clean")]})()

    @contextmanager
    def client(_):
        yield _Client()

    import database.clickhouse
    monkeypatch.setattr(database.clickhouse, "get_collection_client", client)
    stale = activities.stale_virus_plan_hashes.__wrapped__(TablePlanParams("op", "c", "d", "plan"))
    assert stale == ["inf1"]
    assert asked == [(["inf1", "inf2"], 1), (["ok1"], 0)]
    assert seen["parameters"] == {"cd": "d", "plan": "plan"}
    assert "HAVING max(plan_hash) = {plan:String}" in seen["sql"]


def test_virus_attribute_pages_continue_after_the_last_compared_plan(monkeypatch):
    from contextlib import contextmanager

    from tasks.P_admin.updates import activities
    from tasks.P_admin.updates.params import VirusPlansParams

    seen = {}

    class _Client:
        def query(self, sql, parameters):
            seen.update(sql=sql, parameters=parameters)
            return type("R", (), {"result_rows": [("p2",), ("p3",)]})()

    @contextmanager
    def client(_):
        yield _Client()

    import database.clickhouse
    monkeypatch.setattr(database.clickhouse, "get_collection_client", client)
    params = VirusPlansParams("op", "c", "d", after="p9", attributes=True, stale_after="p1")
    assert activities.list_virus_attribute_plans.__wrapped__(params) == ["p2", "p3"]
    assert seen["parameters"] == {"cd": "d", "after": "p1"}
    assert "LIMIT 100" in seen["sql"]
