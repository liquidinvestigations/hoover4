"""The stage activities of the email, archive, PDF, OCR-PDF and video chains.

Each stage activity calls the existing per-file function for each file of a group, through
the batch runner. These tests patch the per-file functions that write to a datastore, and
run the email extraction for real over small messages in a temporary folder.
"""

import os
import tempfile
from email.message import EmailMessage

import pytest
from temporalio.exceptions import ApplicationError

from tasks.P3_parse_files import parse_archives, parse_email, parse_ocr_pdf, parse_pdf, parse_video
from tasks.P3_parse_files.batch_runner import BatchFile, StageBatchParams, file_budget_seconds

MIB = 1024 * 1024


def _params(files, engine=""):
    return StageBatchParams(collectionname="c", collection_dataset="c_d", plan_hash="plan",
                            files=files, op_id="op-1", engine=engine)


def _folder_with(path, names):
    """Make a folder `path` that holds one file for each name, and return it."""
    os.makedirs(path, exist_ok=True)
    for name in names:
        full = os.path.join(path, name)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as handle:
            handle.write(name)
    return str(path)


@pytest.fixture
def temp_root(tmp_path, monkeypatch):
    """Make `make_temp_dir` write under this test's temporary folder."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path


def _eml(path, attachment: bool) -> str:
    msg = EmailMessage()
    msg["From"] = "a@example.com"
    msg["To"] = "b@example.com"
    msg["Subject"] = "test"
    msg.set_content("body text")
    if attachment:
        msg.add_attachment(b"member bytes", maintype="application",
                           subtype="octet-stream", filename="notes.bin")
    path.write_bytes(bytes(msg))
    return str(path)


# Email.

def test_email_attachments_count_and_empty_folder_removed(temp_root):
    files = [
        BatchFile(item_hash="e1", file_path=_eml(temp_root / "one.eml", True), file_size_bytes=10),
        BatchFile(item_hash="e2", file_path=_eml(temp_root / "two.eml", False), file_size_bytes=10),
    ]
    batch = parse_email.extract_email_attachments_batch(_params(files))

    assert batch.stage == "extract_email_attachments_batch"
    assert [r.status for r in batch.results] == ["ok", "ok"]
    assert [r.task_name for r in batch.results] == ["extract_email_attachments_to_temp"] * 2
    first, second = (r.value for r in batch.results)
    assert first["attachment_count"] == 1 and first["member_count"] == 1
    assert os.listdir(first["out_dir"]) == ["notes.bin"]
    assert second["attachment_count"] == 0 and second["member_count"] == 0
    assert not os.path.exists(second["out_dir"])


def test_email_with_no_attachment_part_counts_zero(temp_root):
    path = temp_root / "plain.eml"
    path.write_bytes(b"From: a@example.com\r\nSubject: x\r\n\r\nonly a body\r\n")
    batch = parse_email.extract_email_attachments_batch(
        _params([BatchFile(item_hash="e3", file_path=str(path))]))

    assert batch.results[0].status == "ok"
    assert batch.results[0].value["attachment_count"] == 0
    assert batch.results[0].value["member_count"] == 0


def test_email_attachments_pass_the_file_budget(monkeypatch):
    seen = []
    monkeypatch.setattr(parse_email, "extract_email_attachments_to_temp",
                        lambda p: seen.append(p) or {"out_dir": "", "attachment_count": 0})
    parse_email.extract_email_attachments_batch(
        _params([BatchFile(item_hash="e4", file_path="/x/e4", file_size_bytes=2500)]))

    assert seen[0].email_hash == "e4" and seen[0].file_path == "/x/e4"
    assert seen[0].timeout_seconds == file_budget_seconds(2500)


def test_email_headers_build_the_per_file_parameters(monkeypatch):
    seen = []
    monkeypatch.setattr(parse_email, "parse_email_extract_text_headers",
                        lambda p: seen.append(p) or f"email {p.email_hash}")
    batch = parse_email.parse_email_headers_batch(_params([
        BatchFile(item_hash="h1", file_path="/x/h1"),
        BatchFile(item_hash="h2", file_path="/x/h2"),
    ]))

    assert [(p.collectionname, p.collection_dataset, p.email_hash, p.file_path) for p in seen] == [
        ("c", "c_d", "h1", "/x/h1"), ("c", "c_d", "h2", "/x/h2")]
    assert [r.value for r in batch.results] == ["email h1", "email h2"]
    assert batch.results[0].task_name == "parse_email_extract_text_headers"


@pytest.mark.parametrize("stage", ["parse_email_headers_batch", "extract_email_attachments_batch"])
def test_email_missing_path_fails_after_one_try(temp_root, stage):
    batch = getattr(parse_email, stage)(
        _params([BatchFile(item_hash="gone", file_path=str(temp_root / "gone.eml"))]))

    result = batch.results[0]
    assert result.status == "failed"
    assert result.error_type == "TempCopyMissing"
    assert result.attempts == 1


def test_empty_file_list_gives_an_empty_result():
    assert parse_email.parse_email_headers_batch(_params([])).results == []


# Archive.

def test_archive_extracts_then_records(tmp_path, monkeypatch):
    calls = []
    out_dir = _folder_with(tmp_path / "extract_a1", ["x.txt", "sub/y.txt"])

    def extract(p):
        calls.append(("extract", p.archive_hash, p.archive_types, p.archive_path))
        return {"out_dir": out_dir, "entry_count": 2}

    monkeypatch.setattr(parse_archives, "extract_archive_to_temp", extract)
    monkeypatch.setattr(parse_archives, "record_archive_container",
                        lambda p: calls.append(("record", p.archive_hash, p.archive_types)) or "a1")
    batch = parse_archives.extract_archive_batch(_params([
        BatchFile(item_hash="a1", file_path="/x/a1", mime_types=["application/zip"])]))

    assert calls == [("extract", "a1", ["application/zip"], "/x/a1"),
                     ("record", "a1", ["application/zip"])]
    result = batch.results[0]
    assert result.status == "ok" and result.task_name == "extract_archive_to_temp"
    assert result.value == {"out_dir": out_dir, "entry_count": 2, "member_count": 2}


def test_archive_failure_records_nothing(monkeypatch):
    recorded = []

    def extract(_p):
        raise ApplicationError("not an archive", non_retryable=True)

    monkeypatch.setattr(parse_archives, "extract_archive_to_temp", extract)
    monkeypatch.setattr(parse_archives, "record_archive_container", recorded.append)
    batch = parse_archives.extract_archive_batch(_params([BatchFile(item_hash="a2", file_path="/x")]))

    assert batch.results[0].status == "failed" and batch.results[0].attempts == 1
    assert recorded == []


# PDF.

@pytest.mark.parametrize(("size", "pages", "small"), [
    (64 * MIB - 1, 5000, True),
    (64 * MIB, 999, True),
    (64 * MIB, 1000, False),
])
def test_pdf_extract_chooses_the_path(tmp_path, monkeypatch, size, pages, small):
    calls = []
    out_dir = _folder_with(tmp_path / "pdf_p1", ["page-1.png", "page-2.png"])
    monkeypatch.setattr(parse_pdf, "pdf_small_extract_text_and_images",
                        lambda p: calls.append(("small", p.page_count)) or {"out_dir": out_dir})
    monkeypatch.setattr(parse_pdf, "pdf_large_split_to_chunks",
                        lambda p: calls.append(("large", p.page_count, p.size_bytes))
                        or {"out_dir": out_dir, "chunks": ["c1"]})
    monkeypatch.setattr(parse_pdf, "record_archive_container",
                        lambda p: calls.append(("record", p.archive_types)) or "p1")
    batch = parse_pdf.pdf_extract_batch(_params([BatchFile(
        item_hash="p1", file_path="/x/p1", page_count=pages, pdf_size_bytes=size)]))

    result = batch.results[0]
    if small:
        assert calls == [("small", pages), ("record", ["pdf"])]
        assert result.task_name == "pdf_small_extract_text_and_images"
        assert result.value == {"out_dir": out_dir, "member_count": 2}
    else:
        assert calls == [("large", pages, size), ("record", ["pdf"])]
        assert result.task_name == "pdf_large_split_to_chunks"
        assert result.value == {"out_dir": out_dir, "chunks": ["c1"], "member_count": 2}


def test_pdf_extract_failure_records_nothing(monkeypatch):
    recorded = []

    def small(_p):
        raise ApplicationError("broken pdf", non_retryable=True)

    monkeypatch.setattr(parse_pdf, "pdf_small_extract_text_and_images", small)
    monkeypatch.setattr(parse_pdf, "record_archive_container", recorded.append)
    batch = parse_pdf.pdf_extract_batch(_params([BatchFile(item_hash="p2", file_path="/x")]))

    assert batch.results[0].status == "failed"
    assert recorded == []


def test_pdf_metadata_value(monkeypatch):
    monkeypatch.setattr(parse_pdf, "pdf_get_metadata_and_store",
                        lambda p: {"page_count": 3, "size_bytes": 1000, "hash": p.pdf_hash})
    batch = parse_pdf.pdf_metadata_batch(_params([BatchFile(item_hash="p3", file_path="/x")]))

    assert batch.results[0].value == {"page_count": 3, "size_bytes": 1000, "hash": "p3"}
    assert batch.results[0].task_name == "pdf_get_metadata_and_store"


def test_ocr_pdf_passes_engine_and_op_id(monkeypatch):
    seen = []
    monkeypatch.setattr(parse_ocr_pdf, "run_ocr_pdf_and_store", lambda p: seen.append(p) or "ok")
    batch = parse_ocr_pdf.run_ocr_pdf_batch(_params(
        [BatchFile(item_hash="p4", file_path="/x/p4", file_size_bytes=1250)], engine="tesseract"))

    assert (seen[0].pdf_hash, seen[0].engine, seen[0].op_id) == ("p4", "tesseract", "op-1")
    assert seen[0].timeout_seconds == file_budget_seconds(1250)
    assert batch.results[0].task_name == "run_ocr_pdf_and_store"
    assert batch.stage == "run_ocr_pdf_batch"


# Video.

def test_video_probes_extracts_then_records(tmp_path, monkeypatch):
    calls = []
    out_dir = _folder_with(tmp_path / "video_v1", ["frames/f1.jpg", "subs.srt"])
    monkeypatch.setattr(parse_video, "video_ffprobe_and_store",
                        lambda p: calls.append("probe") or {"duration": 1.0})
    monkeypatch.setattr(parse_video, "video_extract_frames_and_subtitles",
                        lambda p: calls.append("frames") or {"out_dir": out_dir})
    monkeypatch.setattr(parse_video, "record_archive_container",
                        lambda p: calls.append(("record", p.archive_types)) or "v1")
    batch = parse_video.video_batch(_params([BatchFile(item_hash="v1", file_path="/x/v1")]))

    assert calls == ["probe", "frames", ("record", ["video"])]
    result = batch.results[0]
    assert result.task_name == "video_extract_frames_and_subtitles"
    assert result.value == {"out_dir": out_dir, "member_count": 2}


def test_video_failure_records_nothing(monkeypatch):
    recorded = []

    def probe(_p):
        raise ApplicationError("no streams", non_retryable=True)

    monkeypatch.setattr(parse_video, "video_ffprobe_and_store", probe)
    monkeypatch.setattr(parse_video, "record_archive_container", recorded.append)
    batch = parse_video.video_batch(_params([BatchFile(item_hash="v2", file_path="/x")]))

    assert batch.results[0].status == "failed"
    assert recorded == []
