"""The stage activities of detection, Tika and the simple parsers.

Each stage activity calls its existing per-file function once for each file of a group,
through `run_batch`. These tests replace the per-file function and check the parameters
that each call receives, the result of each file, and the empty group. The missing-path
case runs the real `require_input_file`. No JVM, no ClickHouse and no helper process run.
"""

from dataclasses import dataclass, field
from typing import Any, Dict

import pytest
from temporalio.testing import ActivityEnvironment

from tasks.P3_parse_files import (
    parse_audio,
    parse_image,
    parse_mime,
    parse_ocr,
    parse_office_xml,
    parse_table,
    parse_text,
    parse_tika,
)
from tasks.P3_parse_files.batch_runner import (
    BatchFile,
    BatchResult,
    StageBatchParams,
    file_budget_seconds,
    try_budget_seconds,
)
from tasks.P3_parse_files.temp_dirs import TEMP_COPY_MISSING


@dataclass
class Stage:
    """One stage activity, the per-file function it calls, and that function's parameters."""

    module: Any
    batch: str
    per_file: str
    params: type
    extra: Dict[str, Any] = field(default_factory=dict)


STAGES = [
    Stage(parse_mime, "detect_mime_batch", "detect_mime_all", parse_mime.DetectMimeParams),
    Stage(parse_tika, "run_tika_batch", "run_tika_and_store", parse_tika.RunTikaParams),
    Stage(parse_text, "extract_plaintext_batch", "extract_plaintext_chunks",
          parse_text.ExtractPlaintextParams),
    Stage(parse_office_xml, "parse_office_xml_batch", "parse_office_xml_and_store",
          parse_office_xml.ParseOfficeXmlParams),
    Stage(parse_table, "parse_table_batch", "parse_table_and_store",
          parse_table.ParseTableParams, {"table": True}),
    Stage(parse_image, "parse_image_metadata_batch", "parse_image_metadata_and_store",
          parse_image.ParseImageParams),
    Stage(parse_ocr, "run_ocr_batch", "run_ocr_and_store", parse_ocr.RunOcrParams,
          {"engine": True}),
    Stage(parse_audio, "parse_audio_metadata_batch", "parse_audio_metadata_and_store",
          parse_audio.ParseAudioParams),
]

FILES = [
    BatchFile(item_hash="hash-a", file_path="/plan/a", file_size_bytes=0,
              mime_types=["text/csv"], mime_encodings=["utf-8"]),
    BatchFile(item_hash="hash-b", file_path="/plan/b", file_size_bytes=2_500,
              mime_types=["application/vnd.ms-excel"], mime_encodings=[]),
]


def _params(files, engine: str = "") -> StageBatchParams:
    return StageBatchParams(collectionname="coll", collection_dataset="coll_ds",
                            plan_hash="plan", files=list(files), op_id="op-1",
                            engine=engine)


def _run(fn, params: StageBatchParams) -> BatchResult:
    env = ActivityEnvironment()
    env.on_heartbeat = lambda *details: None
    return env.run(fn, params)


def _expected(stage: Stage, file: BatchFile, engine: str):
    kwargs: Dict[str, Any] = dict(
        collectionname="coll", collection_dataset="coll_ds", file_hash=file.item_hash,
        file_path=file.file_path, timeout_seconds=try_budget_seconds(stage.batch,
                                                                     file.file_size_bytes),
        op_id="op-1",
    )
    if stage.extra.get("table"):
        kwargs.update(mime_types=file.mime_types, mime_encodings=file.mime_encodings)
    if stage.extra.get("engine"):
        kwargs.update(engine=engine)
    return stage.params(**kwargs)


@pytest.mark.parametrize("stage", STAGES, ids=[stage.batch for stage in STAGES])
def test_each_file_gets_the_per_file_parameters(stage, monkeypatch):
    calls = []

    def per_file(params):
        calls.append(params)
        return {"value": params.file_hash}

    monkeypatch.setattr(stage.module, stage.per_file, per_file)
    engine = "tesseract" if stage.extra.get("engine") else ""
    result = _run(getattr(stage.module, stage.batch), _params(FILES, engine))

    assert calls == [_expected(stage, file, engine) for file in FILES]
    assert result.stage == stage.batch
    assert [r.item_hash for r in result.results] == ["hash-a", "hash-b"]
    assert [r.status for r in result.results] == ["ok", "ok"]
    assert [r.task_name for r in result.results] == [stage.per_file, stage.per_file]
    assert [r.value for r in result.results] == [{"value": "hash-a"}, {"value": "hash-b"}]
    assert [r.attempts for r in result.results] == [1, 1]


def test_the_try_budget_is_the_file_budget_and_tika_adds_1000_seconds(monkeypatch):
    seen = {}
    for stage in STAGES[:2]:
        monkeypatch.setattr(stage.module, stage.per_file,
                            lambda params, name=stage.batch: seen.setdefault(
                                name, []).append(params.timeout_seconds))
        _run(getattr(stage.module, stage.batch), _params(FILES))
    assert seen["detect_mime_batch"] == [file_budget_seconds(0), file_budget_seconds(2_500)]
    assert seen["detect_mime_batch"] == [900, 902]
    assert seen["run_tika_batch"] == [1900, 1902]


def test_run_ocr_batch_passes_the_engine_of_the_stage(monkeypatch):
    engines = []
    monkeypatch.setattr(parse_ocr, "run_ocr_and_store",
                        lambda params: engines.append(params.engine) or "ocr_ok_1_passes")
    _run(parse_ocr.run_ocr_batch, _params(FILES, engine="easyocr"))
    assert engines == ["easyocr", "easyocr"]


@pytest.mark.parametrize("stage", STAGES, ids=[stage.batch for stage in STAGES])
def test_an_empty_group_returns_an_empty_result(stage, monkeypatch):
    calls = []
    monkeypatch.setattr(stage.module, stage.per_file, lambda params: calls.append(params))
    result = _run(getattr(stage.module, stage.batch), _params([]))
    assert result == BatchResult(stage=stage.batch, results=[])
    assert calls == []


def _missing_files(tmp_path):
    return [BatchFile(item_hash="gone", file_path=str(tmp_path / "plan" / "gone"),
                      file_size_bytes=10)]


def test_detect_mime_batch_fails_a_missing_copy_after_one_try(tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(parse_mime, "_run_file_multi", lambda p: ran.append("file"))
    monkeypatch.setattr(parse_mime, "_store_file_types_many", lambda *a: ran.append("store"))
    result = _run(parse_mime.detect_mime_batch, _params(_missing_files(tmp_path)))
    [only] = result.results
    assert (only.status, only.error_type, only.attempts) == ("failed", TEMP_COPY_MISSING, 1)
    assert only.non_retryable is True
    assert only.task_name == "detect_mime_all"
    assert ran == []


def test_run_tika_batch_fails_a_missing_copy_after_one_try(tmp_path, monkeypatch):
    def no_pool():
        raise AssertionError("the helper pool must not be reached for a missing copy")

    monkeypatch.setattr(parse_tika, "_get_pool", no_pool)
    result = _run(parse_tika.run_tika_batch, _params(_missing_files(tmp_path)))
    [only] = result.results
    assert (only.status, only.error_type, only.attempts) == ("failed", TEMP_COPY_MISSING, 1)
    assert only.task_name == "run_tika_and_store"


@pytest.fixture
def fresh_pool():
    parse_tika.reset_extractous_pool_for_tests()
    yield
    parse_tika.reset_extractous_pool_for_tests()


def test_the_helper_pool_follows_the_tika_slot_count(monkeypatch, fresh_pool):
    monkeypatch.setenv("HOOVER4_TIKA_CONCURRENCY", "12")
    assert parse_tika._get_pool()._size == 12


def test_the_helper_pool_has_8_helpers_when_the_slot_count_is_empty(monkeypatch, fresh_pool):
    monkeypatch.setenv("HOOVER4_TIKA_CONCURRENCY", "12")
    assert parse_tika._get_pool()._size == 12
    parse_tika.reset_extractous_pool_for_tests()
    monkeypatch.setenv("HOOVER4_TIKA_CONCURRENCY", "")
    assert parse_tika._get_pool()._size == 8
