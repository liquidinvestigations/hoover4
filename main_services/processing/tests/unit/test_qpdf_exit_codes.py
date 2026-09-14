"""qpdf warnings return usable page and metadata output."""

import logging
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest
from temporalio.exceptions import ApplicationError

from tasks.P3_parse_files import parse_pdf


def _write_one_page_pdf(path: Path, trailer_size: int) -> None:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(pdf)
    pdf += b"xref\n0 4\n0000000000 65535 f \n"
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n".encode()
    pdf += (
        f"trailer\n<< /Size {trailer_size} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    path.write_bytes(pdf)


def test_qpdf_warning_exit_is_success_and_errors_do_not_retry(monkeypatch, caplog):
    temp_dir = Path(tempfile.mkdtemp())
    try:
        valid_pdf = temp_dir / "valid.pdf"
        warning_pdf = temp_dir / "warning.pdf"
        encrypted_pdf = temp_dir / "encrypted.pdf"
        invalid_pdf = temp_dir / "invalid.pdf"
        _write_one_page_pdf(valid_pdf, trailer_size=4)
        _write_one_page_pdf(warning_pdf, trailer_size=99)

        assert parse_pdf._qpdf_show_npages(str(valid_pdf), "valid-hash") == 1
        with caplog.at_level(logging.WARNING, logger=parse_pdf.log.name):
            assert parse_pdf._qpdf_show_npages(str(warning_pdf), "warning-hash") == 1
        warning_records = [
            record for record in caplog.records
            if "qpdf warning for file hash warning-hash" in record.getMessage()
        ]
        assert len(warning_records) == 1
        assert parse_pdf._qpdf_json(str(warning_pdf))["pages"]

        subprocess.run(
            [
                "qpdf", "--encrypt", "--user-password=secret", "--owner-password=o",
                "--bits=256", "--", str(valid_pdf), str(encrypted_pdf),
            ],
            check=True,
            capture_output=True,
        )
        with pytest.raises(ApplicationError) as excinfo:
            parse_pdf._qpdf_show_npages(str(encrypted_pdf), "encrypted-hash")
        assert excinfo.value.non_retryable is True

        invalid_pdf.write_bytes(b"this is not a PDF")
        with pytest.raises(ApplicationError) as excinfo:
            parse_pdf._qpdf_show_npages(str(invalid_pdf), "invalid-hash")
        assert excinfo.value.non_retryable is True

        monkeypatch.setattr(
            parse_pdf,
            "_run_qpdf",
            lambda args: subprocess.CompletedProcess(args, 3, b"not-a-number", b"warning"),
        )
        with pytest.raises(ApplicationError) as excinfo:
            parse_pdf._qpdf_show_npages("ignored", "invalid-count-hash")
        assert excinfo.value.non_retryable is True
    finally:
        shutil.rmtree(temp_dir)
