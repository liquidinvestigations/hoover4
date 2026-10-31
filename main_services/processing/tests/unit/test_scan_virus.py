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
        def query(self, sql, parameters):
            assert parameters["h"] == ["inf1", "ok1"]
            return type("R", (), {"result_rows": [("inf1", "p2"), ("ok1", "p1")]})()

    @contextmanager
    def client(_):
        yield _Client()

    import database.clickhouse
    monkeypatch.setattr(database.clickhouse, "get_collection_client", client)
    plans = activities.stale_virus_attributes.__wrapped__(TablePlansParams("op", "c", "d"))
    assert plans == {"p2": ["inf1"], "p1": ["ok1"]}
    assert asked == [(["inf1", "inf2"], 1), (["ok1"], 0)]
