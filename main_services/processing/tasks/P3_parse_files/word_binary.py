"""Read binary Word text through a bounded DOCX conversion."""

import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

import olefile

from tasks.P3_parse_files.parse_office_xml import extract_office_xml_text


MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_OUTPUT_BYTES = 128 * 1024 * 1024
CONVERSION_SECONDS = 45


def is_binary_word(file_path: str) -> bool:
    """Require the WordDocument OLE stream before starting LibreOffice."""
    try:
        if Path(file_path).stat().st_size > MAX_INPUT_BYTES or not olefile.isOleFile(file_path):
            return False
        with olefile.OleFileIO(file_path) as document:
            return document.exists("WordDocument")
    except (OSError, ValueError, TypeError):
        return False


def _run_conversion(command: list[str]) -> int:
    from tasks.heartbeat import worker_is_stopping

    try:
        process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise RuntimeError("binary Word converter is unavailable") from exc
    deadline = time.monotonic() + CONVERSION_SECONDS
    try:
        while True:
            if worker_is_stopping():
                raise RuntimeError("binary Word conversion stopped with its worker")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("binary Word conversion timed out")
            try:
                return process.wait(timeout=min(0.5, remaining))
            except subprocess.TimeoutExpired:
                continue
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def extract_binary_word_text(file_path: str) -> str | None:
    """Return Word text, or None when conversion cannot give a readable source."""
    if not is_binary_word(file_path):
        return None
    with tempfile.TemporaryDirectory(prefix="hoover4-word-") as work_dir:
        work = Path(work_dir)
        source = work / "input.doc"
        source.symlink_to(Path(file_path).resolve())
        output = work / "input.docx"
        command = [
            "soffice", f"-env:UserInstallation={(work / 'profile').as_uri()}",
            "--headless", "--convert-to", "docx", "--outdir", str(work), str(source),
        ]
        result = _run_conversion(command)
        if result != 0 or not output.is_file():
            raise RuntimeError("binary Word conversion failed")
        if output.stat().st_size > MAX_OUTPUT_BYTES:
            raise RuntimeError("binary Word conversion exceeded its output limit")
        converted = extract_office_xml_text(str(output))
        if not converted.ok:
            raise RuntimeError("converted binary Word document has no readable text")
        if converted.dropped:
            raise RuntimeError("converted binary Word document has unreadable XML parts")
        return converted.text
