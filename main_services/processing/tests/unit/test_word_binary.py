"""Binary Word reader process and font checks."""

import subprocess
import sys
from xml.etree import ElementTree as ET

import pytest

from tasks.P3_parse_files import word_binary
from tasks.P3_parse_files import parse_tika
from tasks.P3_parse_files.parse_office_xml import _word_symbol


def test_symbol_mapping_requires_font_and_known_code():
    symbol = ET.fromstring('<w:sym xmlns:w="urn:word" w:font="Symbol" w:char="f0ae"/>')
    other = ET.fromstring('<w:sym xmlns:w="urn:word" w:font="Arial" w:char="f0ae"/>')
    unknown = ET.fromstring('<w:sym xmlns:w="urn:word" w:font="Symbol" w:char="f0ff"/>')
    assert _word_symbol(symbol) == "→"
    assert _word_symbol(other) == "\ufffd"
    assert _word_symbol(unknown) == "\ufffd"


def test_worker_stop_kills_word_converter(monkeypatch):
    spawned = []
    real_popen = subprocess.Popen

    def capture(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(word_binary.subprocess, "Popen", capture)
    monkeypatch.setattr("tasks.heartbeat.worker_is_stopping", lambda: True)
    with pytest.raises(RuntimeError, match="stopped with its worker"):
        word_binary._run_conversion([sys.executable, "-c", "import time; time.sleep(20)"])
    assert len(spawned) == 1
    assert spawned[0].poll() is not None


def test_word_text_survives_extractous_failure(monkeypatch):
    stored = []
    monkeypatch.setattr("tasks.P3_parse_files.temp_dirs.require_input_file", lambda path: None)
    monkeypatch.setattr(word_binary, "extract_binary_word_text", lambda path: "Word source")
    monkeypatch.setattr(parse_tika, "_extract_with_extractous",
                        lambda path: (_ for _ in ()).throw(RuntimeError("Extractous failed")))
    monkeypatch.setattr("tasks.P3_parse_files.parse_common.insert_text_chunks",
                        lambda *args: stored.append(args))
    params = parse_tika.RunTikaParams("collection", "dataset", "hash", "input.doc", 60)
    with pytest.raises(RuntimeError, match="Extractous failed"):
        parse_tika.run_tika_and_store(params)
    assert stored == [("collection", "dataset", "hash", "binary_word", "Word source")]


def test_word_conversion_failure_still_attempts_extractous(monkeypatch):
    attempted = []
    monkeypatch.setattr("tasks.P3_parse_files.temp_dirs.require_input_file", lambda path: None)
    monkeypatch.setattr(word_binary, "extract_binary_word_text",
                        lambda path: (_ for _ in ()).throw(OSError("conversion failed")))

    def fail_extractous(path):
        attempted.append(path)
        raise RuntimeError("Extractous failed")

    monkeypatch.setattr(parse_tika, "_extract_with_extractous", fail_extractous)
    params = parse_tika.RunTikaParams("collection", "dataset", "hash", "input.doc", 60)
    with pytest.raises(RuntimeError, match="Extractous failed"):
        parse_tika.run_tika_and_store(params)
    assert attempted == ["input.doc"]
