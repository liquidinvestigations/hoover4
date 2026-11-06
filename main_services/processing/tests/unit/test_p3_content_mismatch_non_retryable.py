"""A file routed to the wrong reader must fail on the first attempt.

`P3`'s routing runs a branch whenever *any one* detector's guess names that branch's
type, even when the other detectors disagree (`tasks/P3_parse_files/workflows.py`). A
weaker detector's wrong guess therefore sends some documents into a reader that was
never going to succeed on their bytes: an email into `qpdf`, a short text file into
`7z`, a TNEF attachment into `ffprobe` and both OCR engines. Each of the four readers
below states plainly, in its own stderr or its own HTTP status, that the bytes are not
its type. Retrying sends the same bytes and gets the same answer, so each of these
raises a non-retryable `ApplicationError` instead of the plain `RuntimeError` that
Temporal would retry to `MaximumAttemptsReached`.

The four cases below were measured against real documents on the demo deployment, where
each reader produced the message this test asserts on.
"""

import subprocess
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from temporalio.exceptions import ApplicationError

from tasks.P3_parse_files import parse_archives, parse_image, parse_ocr, parse_pdf


def _completed(returncode: int, stderr: bytes = b"", stdout: bytes = b""):
    return subprocess.CompletedProcess(args=["x"], returncode=returncode,
                                        stdout=stdout, stderr=stderr)


def test_qpdf_not_a_pdf_header_is_non_retryable(monkeypatch):
    monkeypatch.setattr(
        parse_pdf.subprocess, "run",
        lambda *a, **k: _completed(2, stderr=b"WARNING: x: can't find PDF header\n"),
    )
    with pytest.raises(ApplicationError) as excinfo:
        parse_pdf._qpdf_show_npages("/does/not/matter")
    assert excinfo.value.non_retryable is True


def test_qpdf_other_failure_is_non_retryable(monkeypatch):
    monkeypatch.setattr(
        parse_pdf.subprocess, "run",
        lambda *a, **k: _completed(1, stderr=b"some other qpdf error\n"),
    )
    with pytest.raises(ApplicationError) as excinfo:
        parse_pdf._qpdf_show_npages("/does/not/matter")
    assert excinfo.value.non_retryable is True


def test_7z_cannot_open_as_archive_is_non_retryable(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _completed(2, stderr=b"ERROR: x\nCannot open the file as archive\n"),
    )
    import tasks.P3_parse_files.temp_dirs as temp_dirs

    monkeypatch.setattr(
        temp_dirs, "make_temp_dir",
        lambda *a, **k: str(tmp_path / "extract_out"),
    )
    params = parse_archives.ExtractArchiveParams(
        collectionname="c", collection_dataset="ds", archive_hash="h",
        archive_types=["application/octet-stream"], archive_path=str(tmp_path / "in"),
    )
    with pytest.raises(ApplicationError) as excinfo:
        parse_archives.extract_archive_to_temp(params)
    assert excinfo.value.non_retryable is True


def test_7z_other_failure_stays_retryable(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _completed(2, stderr=b"some other 7z error\n"),
    )
    import tasks.P3_parse_files.temp_dirs as temp_dirs

    monkeypatch.setattr(
        temp_dirs, "make_temp_dir",
        lambda *a, **k: str(tmp_path / "extract_out"),
    )
    params = parse_archives.ExtractArchiveParams(
        collectionname="c", collection_dataset="ds", archive_hash="h",
        archive_types=["application/octet-stream"], archive_path=str(tmp_path / "in"),
    )
    with pytest.raises(RuntimeError) as excinfo:
        parse_archives.extract_archive_to_temp(params)
    assert not isinstance(excinfo.value, ApplicationError)


def test_ffprobe_invalid_data_is_non_retryable(monkeypatch):
    monkeypatch.setattr(
        parse_image.subprocess, "run",
        lambda *a, **k: _completed(1, stderr=b"x: Invalid data found when processing input\n"),
    )
    with pytest.raises(ApplicationError) as excinfo:
        parse_image._run_ffprobe_json("/does/not/matter", 30)
    assert excinfo.value.non_retryable is True


def test_ffprobe_other_failure_stays_retryable(monkeypatch):
    monkeypatch.setattr(
        parse_image.subprocess, "run",
        lambda *a, **k: _completed(1, stderr=b"some other ffprobe error\n"),
    )
    with pytest.raises(RuntimeError) as excinfo:
        parse_image._run_ffprobe_json("/does/not/matter", 30)
    assert not isinstance(excinfo.value, ApplicationError)


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def _run_ocr_activity(monkeypatch, tmp_path, http_error):
    image_path = tmp_path / "winmail.dat"
    image_path.write_bytes(b"not actually an image, just some bytes")

    monkeypatch.setattr(parse_ocr, "_passes_for", lambda engine, ds: ["eng"])
    monkeypatch.setattr(parse_ocr, "read_preview_bytes", lambda *a: None)

    class _FakeClient:
        def query(self, *a, **k):
            raise RuntimeError("no watermark in this test")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import database.clickhouse as clickhouse

    monkeypatch.setattr(clickhouse, "get_collection_client", lambda *a, **k: _FakeClient())

    import tasks.ocr_client as ocr_client

    def _raise_http_error(*a, **k):
        raise http_error

    monkeypatch.setattr(ocr_client, "engine_configured", lambda engine: True)
    monkeypatch.setattr(ocr_client, "run_ocr", _raise_http_error)

    params = parse_ocr.RunOcrParams(
        collectionname="c", collection_dataset="ds", file_hash="h",
        file_path=str(image_path), engine="tesseract", timeout_seconds=30,
    )
    return parse_ocr.run_ocr_and_store(params)


def test_ocr_422_is_a_skip_and_not_an_error(monkeypatch, tmp_path):
    import requests
    import tasks.ocr_targets as ocr_targets

    recorded = []
    monkeypatch.setattr(ocr_targets, "record_ocr_skips", lambda *a, **k: recorded.append(a))
    http_error = requests.HTTPError("422 Client Error")
    http_error.response = _FakeResponse(422)
    outcome = _run_ocr_activity(monkeypatch, tmp_path, http_error)
    assert outcome.value == "ocr_skipped_undecodable"
    assert recorded and recorded[0][-2] == "ocr_skipped_undecodable"


def test_image_metadata_of_unreadable_bytes_is_a_skip_and_not_an_error(monkeypatch):
    monkeypatch.setattr(
        parse_image.subprocess, "run",
        lambda *a, **k: _completed(1, stderr=b"x: Invalid data found when processing input\n"),
    )
    outcome = parse_image.parse_image_metadata_and_store(parse_image.ParseImageParams(
        collectionname="c", collection_dataset="ds", file_hash="h", file_path="/does/not/matter",
        timeout_seconds=30))
    assert outcome.value == "image_undecodable"


def test_ocr_other_http_error_stays_retryable(monkeypatch, tmp_path):
    import requests

    http_error = requests.HTTPError("500 Server Error")
    http_error.response = _FakeResponse(500)
    with pytest.raises(requests.HTTPError):
        _run_ocr_activity(monkeypatch, tmp_path, http_error)


def test_audio_of_unreadable_bytes_is_a_skip_and_not_an_error(monkeypatch):
    from tasks.P3_parse_files import parse_audio
    from tasks.task_timing import SkippedOutcome

    monkeypatch.setattr(parse_audio.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout=b"", stderr=b"x: Invalid data found when processing input\n"))
    params = parse_audio.ParseAudioParams("c", "c_d", "h", "/tmp/x", 30)
    assert isinstance(parse_audio.parse_audio_metadata_and_store(params), SkippedOutcome)


def test_a_file_without_a_pdf_header_has_its_own_error_type():
    from tasks.P3_parse_files import parse_pdf

    with pytest.raises(ApplicationError) as caught:
        parse_pdf._raise_qpdf_show_npages_error(SimpleNamespace(
            stderr=b"WARNING: x: can't find PDF header", stdout=b""))
    assert caught.value.type == parse_pdf.NOT_A_PDF


def test_an_archive_that_does_not_open_is_a_skip(monkeypatch):
    from tasks.P3_parse_files import parse_archives

    def refuse(_params):
        raise ApplicationError("no", type=parse_archives.ARCHIVE_NOT_OPENED, non_retryable=True)

    monkeypatch.setattr(parse_archives, "extract_archive_to_temp", refuse)
    captured = {}
    monkeypatch.setattr(parse_archives, "run_batch", lambda *a, **k: captured.update(k))
    params = SimpleNamespace(collectionname="c", collection_dataset="c_d", files=[])
    parse_archives.extract_archive_batch.__wrapped__(params)
    file = SimpleNamespace(item_hash="h", file_names=["x.7z"], mime_types=[], file_path="/tmp/x")
    outcome = captured["step"](file)
    assert outcome.value == {"out_dir": "", "entry_count": 0}
