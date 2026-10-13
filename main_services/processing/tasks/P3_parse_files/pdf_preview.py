"""Convert supported Office documents to stored PDF sources on the preview queue."""

import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from temporalio import activity

from tasks.heartbeat import with_heartbeat, heartbeat_pump, stop_if_worker_is_stopping
from tasks.P3_parse_files.batch_runner import StageBatchParams, BatchResult, run_batch
from tasks.task_timing import SkippedOutcome

OFFICE_PREVIEW_MIMES = frozenset({
    "application/msword", "application/vnd.ms-word.document.macroenabled.12",
    "application/vnd.ms-word.template.macroenabled.12",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
    "application/vnd.oasis.opendocument.text", "application/vnd.oasis.opendocument.text-template",
    "application/vnd.ms-powerpoint", "application/vnd.ms-powerpoint.presentation.macroenabled.12",
    "application/vnd.ms-powerpoint.slideshow.macroenabled.12",
    "application/vnd.ms-powerpoint.template.macroenabled.12",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.presentationml.slideshow",
    "application/vnd.openxmlformats-officedocument.presentationml.template",
    "application/vnd.oasis.opendocument.presentation",
    "application/vnd.oasis.opendocument.presentation-template",
})


def preview_timeout(size: int) -> int:
    return min(1800, 120 + max(size, 0) // 100_000)


def convert_office(source: str, folder: str, timeout: int) -> str:
    """Convert with a separate profile and stop the process group on interruption."""
    profile = Path(folder, "profile").as_uri()
    process = subprocess.Popen(
        ["soffice", f"-env:UserInstallation={profile}", "--headless", "--norestore",
         "--convert-to", "pdf", "--outdir", folder, source],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout
    try:
        while True:
            stop_if_worker_is_stopping()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired("soffice", timeout)
            try:
                _, error = process.communicate(timeout=min(0.5, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        outputs = list(Path(folder).glob("*.pdf"))
        if process.returncode or len(outputs) != 1 or outputs[0].stat().st_size == 0:
            raise RuntimeError(f"Office PDF conversion failed: {error[:200]!r}")
        return str(outputs[0])
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()


def make_pdf_preview(params: StageBatchParams, file):
    from database.clickhouse import get_collection_client
    from database.s3 import get_s3_client, collection_bucket
    from tasks.P3_parse_files.pdf_parts import live_hashes, write_row
    from tasks.P3_parse_files.parse_pdf import _qpdf_show_npages
    from tasks.ocr_targets import record_ocr_skips
    with get_collection_client(params.collectionname) as client:
        if file.item_hash not in live_hashes(client, params.collection_dataset, [file.item_hash]):
            return SkippedOutcome("pdf_source_removed")
        rows = client.query("SELECT page_count, size_bytes FROM pdf_previews FINAL "
                            "WHERE collection_dataset = {cd:String} AND hash = {h:String}",
                            parameters={"cd": params.collection_dataset, "h": file.item_hash}).result_rows
        if rows:
            return {"page_count": rows[0][0], "size_bytes": rows[0][1], "source_kind": "preview"}
        with tempfile.TemporaryDirectory(prefix="hoover4-office-preview-") as folder:
            names = [name for name in file.file_names if os.path.splitext(name)[1]]
            suffix = os.path.splitext(names[0])[1] if names else ".docx"
            source = os.path.join(folder, f"source{suffix}")
            shutil.copyfile(file.file_path, source)
            try:
                with heartbeat_pump(f"Office preview {file.item_hash[:8]}"):
                    output = convert_office(source, folder, preview_timeout(file.file_size_bytes))
                    count = _qpdf_show_npages(output, file.item_hash)
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                record_ocr_skips(client, params.collection_dataset, file.item_hash,
                                 "pdf_preview", "", [""], str(exc), params.op_id)
                return SkippedOutcome("pdf_preview_failed")
            bucket = collection_bucket(params.collectionname)
            key = f"derived/pdf-preview/{params.collection_dataset}/{file.item_hash}.pdf"
            size = os.path.getsize(output)
            get_s3_client().fput_object(bucket, key, output, content_type="application/pdf")
            write_row(client, "pdf_previews", dict(collection_dataset=params.collection_dataset,
                      hash=file.item_hash, s3_path=f"s3://{bucket}/{key}", page_count=count, size_bytes=size))
        return {"page_count": count, "size_bytes": size, "source_kind": "preview"}


@activity.defn
@with_heartbeat
def make_pdf_preview_batch(params: StageBatchParams) -> BatchResult:
    """Create each missing Office PDF preview in the group."""
    return run_batch("make_pdf_preview_batch", params.files, key=lambda f: f.item_hash,
                     size=lambda f: f.file_size_bytes, step=lambda f: make_pdf_preview(params, f),
                     task_name="make_pdf_preview")
