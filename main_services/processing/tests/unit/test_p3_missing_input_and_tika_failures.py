"""A missing temporary copy fails once with its cause, and a Tika refusal is classified.

No JVM and no ClickHouse: the extractous pool, Magika and the stores are replaced, and
the workflow helpers are pure functions of the results they receive.
"""

import os
from types import SimpleNamespace

import pytest
from temporalio.exceptions import ActivityError, ApplicationError, RetryState

from tasks.P3_parse_files import parse_email, parse_mime, parse_text, parse_tika, workflows
from tasks.P3_parse_files.temp_dirs import (
    TEMP_COPY_MISSING,
    is_temp_copy_missing,
    require_input_file,
)
from tasks.P_admin import rerun_selection, stage_eligibility


def _missing(tmp_path):
    return str(tmp_path / "plan" / "0123abcd")


def _assert_missing_copy_error(error: ApplicationError, path: str) -> None:
    assert error.type == TEMP_COPY_MISSING
    assert error.non_retryable is True
    assert path in str(error)
    assert "temporary copy" in str(error)


def _activity_failure(cause: BaseException) -> ActivityError:
    """The shape a workflow receives when an activity fails."""
    error = ActivityError(
        "Activity task failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="test",
        activity_type="test",
        activity_id="1",
        retry_state=RetryState.NON_RETRYABLE_FAILURE,
    )
    error.__cause__ = cause
    return error


def test_require_input_file_accepts_an_existing_file(tmp_path):
    path = tmp_path / "present"
    path.write_bytes(b"x")
    require_input_file(str(path))


def test_require_input_file_names_the_missing_path(tmp_path):
    path = _missing(tmp_path)
    with pytest.raises(ApplicationError) as excinfo:
        require_input_file(path)
    _assert_missing_copy_error(excinfo.value, path)
    assert is_temp_copy_missing(_activity_failure(excinfo.value))


def test_detect_mime_all_fails_before_any_detector_runs(tmp_path, monkeypatch):
    path = _missing(tmp_path)
    ran = []
    monkeypatch.setattr(parse_mime, "_run_file_multi", lambda p: ran.append("file"))
    monkeypatch.setattr(parse_mime, "_store_file_types_many", lambda *a: ran.append("store"))
    params = parse_mime.DetectMimeParams("c", "ds", "h", path, 30)
    with pytest.raises(ApplicationError) as excinfo:
        parse_mime.detect_mime_all(params)
    _assert_missing_copy_error(excinfo.value, path)
    assert ran == []


def test_file_reports_no_cannot_open_text_as_a_type(monkeypatch):
    def fake_run(cmd, capture_output, text):
        return SimpleNamespace(
            returncode=0,
            stdout=f"{cmd[-1]}: cannot open `{cmd[-1]}' (No such file or directory)\n",
        )

    monkeypatch.setattr(parse_mime.subprocess, "run", fake_run)
    mime_types, _encodings, extensions = parse_mime._run_file_multi("/gone/0123abcd")
    assert mime_types == []
    assert extensions == []


def test_file_keeps_its_primary_match_first(monkeypatch):
    def fake_run(cmd, capture_output, text):
        return SimpleNamespace(
            returncode=0, stdout=f"{cmd[-1]}: image/jpeg\\012- application/octet-stream\n",
        )

    monkeypatch.setattr(parse_mime.subprocess, "run", fake_run)
    mime_types, _encodings, _extensions = parse_mime._run_file_multi("/data/photo")
    assert mime_types == ["image/jpeg", "application/octet-stream"]


def _magika_result(status_value):
    # No `output`: the detector must not read it when the status is not OK.
    return SimpleNamespace(ok=False, status=SimpleNamespace(value=status_value))


@pytest.mark.parametrize("status_value", ["permission_error", "unknown"])
def test_magika_error_names_its_status(tmp_path, monkeypatch, status_value):
    path = tmp_path / "present"
    path.write_bytes(b"x")
    monkeypatch.setattr(parse_mime, "identify_path_with_magika",
                        lambda p: _magika_result(status_value))
    params = parse_mime.DetectMimeParams("c", "ds", "h", str(path), 30)
    with pytest.raises(RuntimeError) as excinfo:
        parse_mime._detect_magika(params)
    assert f"magika status {status_value}" in str(excinfo.value)
    assert str(path) in str(excinfo.value)


def test_magika_file_not_found_is_a_missing_copy(tmp_path, monkeypatch):
    path = _missing(tmp_path)
    monkeypatch.setattr(parse_mime, "identify_path_with_magika",
                        lambda p: _magika_result("file_not_found_error"))
    params = parse_mime.DetectMimeParams("c", "ds", "h", path, 30)
    with pytest.raises(ApplicationError) as excinfo:
        parse_mime._detect_magika(params)
    _assert_missing_copy_error(excinfo.value, path)


def test_tika_fails_on_a_missing_copy_without_running_extractous(tmp_path, monkeypatch):
    path = _missing(tmp_path)
    monkeypatch.setattr(parse_tika, "_extract_with_extractous",
                        lambda p: pytest.fail("extractous ran on a missing path"))
    params = parse_tika.RunTikaParams("c", "ds", "h", path, 30)
    with pytest.raises(ApplicationError) as excinfo:
        parse_tika.run_tika_and_store(params)
    _assert_missing_copy_error(excinfo.value, path)


def test_plaintext_fails_on_a_missing_copy(tmp_path):
    path = _missing(tmp_path)
    params = parse_text.ExtractPlaintextParams("c", "ds", "h", path, 30)
    with pytest.raises(ApplicationError) as excinfo:
        parse_text.extract_plaintext_chunks(params)
    _assert_missing_copy_error(excinfo.value, path)


def test_email_activities_fail_on_a_missing_copy(tmp_path):
    path = _missing(tmp_path)
    headers = parse_email.ParseEmailHeadersParams("c", "ds", "h", path)
    with pytest.raises(ApplicationError) as excinfo:
        parse_email.parse_email_extract_text_headers(headers)
    _assert_missing_copy_error(excinfo.value, path)

    attachments = parse_email.ExtractEmailAttachmentsParams(
        collectionname="c", collection_dataset="ds", email_hash="h",
        file_path=path, timeout_seconds=30,
    )
    with pytest.raises(ApplicationError) as excinfo:
        parse_email.extract_email_attachments_to_temp(attachments)
    _assert_missing_copy_error(excinfo.value, path)


def test_a_missing_copy_is_recorded_once_across_the_detectors():
    missing = _activity_failure(ApplicationError(
        "input file /tmp/x does not exist", type=TEMP_COPY_MISSING, non_retryable=True))
    names = ["file", "magika", "extension", "content_sniff", "tika"]
    results = workflows._detector_results_for_error_capture(
        names, [missing] * 4 + [missing], [], [],
    )
    assert results == [missing, None, None, None, None]


def _jpeg_parse_failure():
    return _activity_failure(ApplicationError(
        "extractous failed for /tmp/x after 2 attempt(s): 'ParseError(\"Parse error "
        "occurred : Unexpected RuntimeException from "
        "org.apache.tika.parser.image.JpegParser@1823eeaa\")'",
        type=parse_tika.TIKA_PARSE_FAILED,
        non_retryable=True,
    ))


def test_a_tika_parse_failure_is_a_parse_error_when_another_extractor_succeeded():
    names = workflows._detector_error_task_ids(
        ["file", "tika"], [None, _jpeg_parse_failure()],
        ["parse_image_metadata_and_store", "run_ocr_and_store[tesseract]"],
        ["ok", RuntimeError("ocr failed")],
    )
    assert names == ["detector_error_file", "parse_error_tika"]


def test_a_tika_parse_failure_stays_a_detector_error_when_no_extractor_succeeded():
    names = workflows._detector_error_task_ids(
        ["file", "tika"], [None, _jpeg_parse_failure()],
        ["parse_office_xml_and_store"], [RuntimeError("bad zip")],
    )
    assert names == ["detector_error_file", "detector_error_tika"]


def test_a_retryable_tika_failure_stays_a_detector_error():
    names = workflows._detector_error_task_ids(
        ["tika"], [_activity_failure(RuntimeError("extractous helper closed stdout"))],
        ["parse_image_metadata_and_store"], ["ok"],
    )
    assert names == ["detector_error_tika"]


class _ParseFailurePool:
    def __init__(self):
        self.calls = []

    def extract(self, path):
        self.calls.append(path)
        raise parse_tika.ExtractousParseError(
            f"extractous failed for {path}: 'ParseError(\"Parse error occurred : "
            "Unexpected RuntimeException from org.apache.tika.parser.image.JpegParser@1\")'"
        )


def test_a_file_tika_refuses_at_every_step_is_not_retried(tmp_path, monkeypatch):
    path = tmp_path / "photo"
    path.write_bytes(b"\xff\xd8\xff")
    pool = _ParseFailurePool()
    monkeypatch.setattr(parse_tika, "_get_pool", lambda: pool)
    monkeypatch.setattr(parse_tika, "_detector_candidate_types", lambda p: [
        ("the file detector's first match", "image/jpeg"),
        ("the file detector's second match", "application/x-no-such-type"),
    ])
    with pytest.raises(ApplicationError) as excinfo:
        parse_tika._extract_with_extractous(str(path))
    assert excinfo.value.type == parse_tika.TIKA_PARSE_FAILED
    assert excinfo.value.non_retryable is True
    assert "org.apache.tika.parser.image.JpegParser" in str(excinfo.value)
    assert "no extension known" in str(excinfo.value)
    assert len(pool.calls) == 2


def test_a_helper_failure_keeps_the_chain_retryable(tmp_path, monkeypatch):
    path = tmp_path / "photo"
    path.write_bytes(b"\xff\xd8\xff")

    class _Pool:
        def extract(self, p):
            if p.endswith(".jpg"):
                raise parse_tika.ExtractousParseError("extractous failed: parse error")
            raise EOFError("extractous helper closed stdout")

    monkeypatch.setattr(parse_tika, "_get_pool", lambda: _Pool())
    monkeypatch.setattr(parse_tika, "_detector_candidate_types",
                        lambda p: [("the file detector's first match", "image/jpeg")])
    with pytest.raises(RuntimeError) as excinfo:
        parse_tika._extract_with_extractous(str(path))
    assert not isinstance(excinfo.value, ApplicationError)


def test_parse_error_tika_is_known_and_recovered_by_the_tika_activity():
    assert "parse_error_tika" in stage_eligibility.KNOWN_TASK_NAMES
    assert rerun_selection.recovery_activity("parse_error_tika") == "run_tika_and_store"
