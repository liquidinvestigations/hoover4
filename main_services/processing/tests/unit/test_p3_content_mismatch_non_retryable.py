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

Measured on the demo box, 2026-09-05: `plans/06-qa-bugfixes/4-plan/pass-04-report.md`.
"""

import subprocess
from dataclasses import dataclass

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


def test_qpdf_other_failure_stays_retryable(monkeypatch):
    monkeypatch.setattr(
        parse_pdf.subprocess, "run",
        lambda *a, **k: _completed(1, stderr=b"some other qpdf error\n"),
    )
    with pytest.raises(RuntimeError) as excinfo:
        parse_pdf._qpdf_show_npages("/does/not/matter")
    assert not isinstance(excinfo.value, ApplicationError)


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


def test_ocr_422_is_non_retryable(monkeypatch, tmp_path):
    import requests

    http_error = requests.HTTPError("422 Client Error")
    http_error.response = _FakeResponse(422)
    with pytest.raises(ApplicationError) as excinfo:
        _run_ocr_activity(monkeypatch, tmp_path, http_error)
    assert excinfo.value.non_retryable is True


def test_ocr_other_http_error_stays_retryable(monkeypatch, tmp_path):
    import requests

    http_error = requests.HTTPError("500 Server Error")
    http_error.response = _FakeResponse(500)
    with pytest.raises(requests.HTTPError):
        _run_ocr_activity(monkeypatch, tmp_path, http_error)
