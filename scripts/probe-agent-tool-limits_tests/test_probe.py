"""Fake-model tests of `scripts/probe-agent-tool-limits.py`."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "probe-agent-tool-limits.py"
spec = importlib.util.spec_from_file_location("probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
# A dataclass reads its module from `sys.modules` while the module loads.
sys.modules["probe"] = probe
spec.loader.exec_module(probe)

TOOL = {"type": "function", "function": {"name": "read_documents", "parameters": {"type": "object", "properties": {}}}}
FIXTURE = {
    "name": "core-read", "profile": "core", "system": "You answer from the pages.",
    "question": "What is the code word?", "core_tools": [TOOL], "deferred_tools": [],
    "page_tool": "read_documents", "page_arguments": {"file_hash": "h"},
    "filler": "lorem ipsum dolor ", "sentinel": "CODEWORD-ZEBRA", "answer_key": ["zebra"],
    "expect": "answer", "catalogue_query": "read a document",
    "catalogue_ranking": [f"tool_{n}" for n in range(12)], "catalogue_target": "tool_7",
}


class FakeModel:
    """Counts four characters as one token. It answers well while the result tokens of a
    request stay at or under `limit`, and calls the catalogue target when it is listed.
    `drop_after` makes the chat call number `drop_after` raise a transport failure."""

    def __init__(self, limit=5000, drop_after=None, tokenizer_works=True):
        self.limit = limit
        self.drop_after = drop_after
        self.tokenizer_works = tokenizer_works
        self.chats = 0

    def tokenize(self, text):
        if not self.tokenizer_works:
            raise probe.TokenizerFailure("no tokenizer")
        return len(text) // 4

    def chat(self, body):
        self.chats += 1
        if self.drop_after is not None and self.chats > self.drop_after:
            raise probe.TransportFailure("connection reset")
        results = [m["content"] for m in body["messages"] if m["role"] == "tool"]
        if "matches" in results[0]:
            matches = json.loads(results[0])["matches"]
            calls = [{"id": "x", "type": "function", "function": {"name": "tool_7", "arguments": "{}"}}] if "tool_7" in matches else []
            message = {"content": "" if calls else "I cannot find a tool.", "tool_calls": calls}
        else:
            tokens = sum(len(json.loads(r)["items"][0]) // 4 for r in results)
            message = {"content": "The code word is CODEWORD-ZEBRA." if tokens <= self.limit else "I do not know."}
        return 200, {"choices": [{"message": message, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 100, "completion_tokens": 10}}, 0.01, 0.02


def run(tmp_path, model, *extra, fixture=FIXTURE):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture))
    argv = ["--source-model", "Qwen/Qwen3.5-35B-A3B", "--served-name", "qwen3.5-35b-a3b",
            "--parser", "qwen3_xml", "--fixture", str(path), "--output-dir", str(tmp_path / "out"),
            "--series", "s1", "--hardware", "test", "--screen-runs", "3", "--confirm-runs", "4",
            "--start-page-tokens", "1024", "--max-page-tokens", "65536", "--resolution", "256", *extra]
    status = probe.main(argv, model=model)
    lines = (tmp_path / "out" / "s1.jsonl").read_text().splitlines() if (tmp_path / "out" / "s1.jsonl").exists() else []
    return status, [json.loads(line) for line in lines]


def test_the_page_search_doubles_then_brackets_and_confirms(tmp_path):
    status, records = run(tmp_path, FakeModel(limit=5000), "--parallel", "1,2")
    assert status == probe.EXIT_OK
    assert records[0]["kind"] == "series" and records[0]["parser"] == "qwen3_xml"
    selections = {r["parallel_calls"]: r for r in records if r["kind"] == "selection"}
    assert 5000 - 256 <= selections[1]["selected_page_tokens"] <= 5000
    assert 2500 - 256 <= selections[2]["selected_page_tokens"] <= 2500
    assert selections[1]["confirmed"] and selections[2]["confirmed"]
    samples = [r for r in records if r["kind"] == "sample"]
    doubled = [r["page_tokens"] for r in samples if r["parallel_calls"] == 1 and r["run"] == 0][:4]
    assert doubled == [1024, 2048, 4096, 8192]
    confirms = [r for r in samples if r["stage"] == "confirm" and r["parallel_calls"] == 1]
    assert len(confirms) == 4 and all(r["passed"] for r in confirms)
    for key in ("result_tokens", "core_schema_tokens", "deferred_schema_tokens", "outcome", "repeated_calls",
                "malformed_calls", "score", "total_seconds", "connect_seconds", "prompt_tokens",
                "completion_tokens", "peak_context", "safe_mode", "tokenizer_failures"):
        assert key in samples[0], key


def test_an_incomplete_series_exits_nonzero_and_keeps_its_records(tmp_path):
    status, records = run(tmp_path, FakeModel(limit=5000, drop_after=5))
    assert status == probe.EXIT_INCOMPLETE
    samples = [r for r in records if r["kind"] == "sample"]
    assert len(samples) == 6
    assert [r["missing"] for r in samples] == [False] * 5 + [True]
    assert not any(r["kind"] == "selection" for r in records)


def test_the_catalogue_arm_selects_the_smallest_passing_count(tmp_path):
    status, records = run(tmp_path, FakeModel(), "--arm", "catalogue")
    assert status == probe.EXIT_OK
    selection = [r for r in records if r["kind"] == "selection"][0]
    assert selection["selected_match_count"] == 8 and selection["confirmed"]
    assert sorted({r["match_count"] for r in records if r["kind"] == "sample"}) == [6, 7, 8]


def test_a_catalogue_request_binds_the_listed_deferred_tools():
    deferred = [{"type": "function", "function": {"name": f"tool_{n}", "parameters": {}}} for n in range(12)]
    fixture = dict(FIXTURE, deferred_tools=deferred)
    series = probe.Series("m", "m", "qwen3_xml", 0.0, 64, "test", [fixture], Path("unused"))
    request = probe.page_request(series, fixture, "", 1, [f"tool_{n}" for n in range(6)])
    names = [tool["function"]["name"] for tool in request["tools"]]
    assert names == ["read_documents"] + [f"tool_{n}" for n in range(6)]


def test_a_failed_tokenizer_sizes_pages_by_bytes_and_records_it(tmp_path):
    status, records = run(tmp_path, FakeModel(limit=5000, tokenizer_works=False), "--parallel", "1")
    assert status == probe.EXIT_OK
    samples = [r for r in records if r["kind"] == "sample"]
    assert all(r["safe_mode"] for r in samples)
    assert samples[0]["tokenizer_failures"] >= 1


def test_an_unsupported_parser_and_a_changed_series_are_configuration_failures(tmp_path):
    assert run(tmp_path, FakeModel(), "--parser", "hermes")[0] == probe.EXIT_CONFIG
    assert run(tmp_path, FakeModel(), "--parallel", "1")[0] == probe.EXIT_OK
    status, records = run(tmp_path, FakeModel(), "--parallel", "1", "--temperature", "0.7")
    assert status == probe.EXIT_CONFIG
    assert records[0]["temperature"] == 0.0


def test_a_fixture_without_its_keys_is_refused(tmp_path):
    broken = {key: value for key, value in FIXTURE.items() if key != "sentinel"}
    assert run(tmp_path, FakeModel(), fixture=broken)[0] == probe.EXIT_CONFIG
