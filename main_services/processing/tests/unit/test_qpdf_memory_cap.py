"""The qpdf memory cap, the page copy without resource analysis, and the cap error."""

import logging
import subprocess
from pathlib import Path

import pytest
from temporalio.exceptions import ApplicationError

from tasks.P3_parse_files import parse_pdf


def _recorder(monkeypatch, returncode=0, stderr=b""):
    calls = []

    def run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, returncode, b"1\n", stderr)

    monkeypatch.setattr(parse_pdf.sandbox, "run", run)
    return calls


def test_default_cap_prefixes_prlimit(monkeypatch, tmp_path):
    monkeypatch.delenv("HOOVER4_QPDF_MEM_LIMIT_BYTES", raising=False)
    calls = _recorder(monkeypatch)
    parse_pdf._run_qpdf(["--show-npages", str(tmp_path / "a.pdf")], "h1")
    assert calls == [["prlimit", f"--as={parse_pdf.DEFAULT_QPDF_MEM_LIMIT_BYTES}", "--",
                      "qpdf", "--show-npages", str(tmp_path / "a.pdf")]]


def test_setting_replaces_cap_and_zero_removes_it(monkeypatch, tmp_path):
    calls = _recorder(monkeypatch)
    monkeypatch.setenv("HOOVER4_QPDF_MEM_LIMIT_BYTES", "1048576")
    parse_pdf._run_qpdf(["--show-npages", "x.pdf"])
    monkeypatch.setenv("HOOVER4_QPDF_MEM_LIMIT_BYTES", "0")
    parse_pdf._run_qpdf(["--show-npages", "x.pdf"])
    assert calls[0][:3] == ["prlimit", "--as=1048576", "--"]
    assert calls[1] == ["qpdf", "--show-npages", "x.pdf"]
    monkeypatch.setenv("HOOVER4_QPDF_MEM_LIMIT_BYTES", "-1")
    with pytest.raises(ValueError):
        parse_pdf.qpdf_memory_limit()


def test_log_names_hash_size_and_pages_before_the_call(monkeypatch, tmp_path, caplog):
    source = tmp_path / "in.pdf"
    source.write_bytes(b"x" * 1234)
    _recorder(monkeypatch)
    with caplog.at_level(logging.INFO, logger=parse_pdf.log.name):
        parse_pdf._run_qpdf(["--empty", "--pages", str(source), "1-2", "--", str(tmp_path / "o.pdf")],
                            "hash-a", 7)
    message = next(r.getMessage() for r in caplog.records if "hash-a" in r.getMessage())
    assert "1234 bytes" in message and "7 pages" in message


@pytest.mark.parametrize("stderr", [b"qpdf: std::bad_alloc\n",
                                    b"qpdf: error while loading shared libraries: x: failed to map segment\n"])
def test_cap_hit_is_not_retried(monkeypatch, stderr):
    monkeypatch.delenv("HOOVER4_QPDF_MEM_LIMIT_BYTES", raising=False)
    _recorder(monkeypatch, returncode=2, stderr=stderr)
    with pytest.raises(ApplicationError) as excinfo:
        parse_pdf._run_qpdf(["--show-npages", "x.pdf"], "hash-b", 3)
    assert excinfo.value.type == parse_pdf.QPDF_MEMORY_CAP
    assert excinfo.value.non_retryable is True
    assert "hash-b" in str(excinfo.value)


def test_other_failures_and_kills_stay_ordinary_results(monkeypatch):
    monkeypatch.delenv("HOOVER4_QPDF_MEM_LIMIT_BYTES", raising=False)
    _recorder(monkeypatch, returncode=2, stderr=b"qpdf: x.pdf: not a PDF\n")
    assert parse_pdf._run_qpdf(["--show-npages", "x.pdf"]).returncode == 2
    _recorder(monkeypatch, returncode=-9, stderr=b"")
    assert parse_pdf._run_qpdf(["--show-npages", "x.pdf"]).returncode == -9


def test_metadata_does_not_read_a_cap_hit_as_damage(monkeypatch):
    def capped(path, file_hash=""):
        raise ApplicationError("cap", type=parse_pdf.QPDF_MEMORY_CAP, non_retryable=True)

    monkeypatch.setattr(parse_pdf, "_qpdf_show_npages", capped)
    monkeypatch.setattr(parse_pdf, "heartbeat_pump", lambda *_: _Null())
    with pytest.raises(ApplicationError) as excinfo:
        parse_pdf.pdf_get_metadata_and_store.__wrapped__(
            parse_pdf.PdfMetaParams("c", "c_d", "hash-c", "/nonexistent.pdf"))
    assert excinfo.value.type == parse_pdf.QPDF_MEMORY_CAP


class _Null:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _shared_forms_pdf(path: Path, count: int) -> None:
    """One page that draws `count` Form XObjects. The page and every form share one
    resource dictionary that lists every form and one graphics state for each form."""
    names = b" ".join(f"/X{i} {6 + i} 0 R".encode() for i in range(count))
    states = b" ".join(f"/G{i} << /CA 0.5 >>".encode() for i in range(count))
    content = b" ".join(f"/X{i} Do".encode() for i in range(count))
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources 5 0 R /Contents 4 0 R >>",
               b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
               b"<< /XObject << " + names + b" >> /ExtGState << " + states + b" >> >>"]
    for i in range(count):
        form = f"/G{i} gs /X{(i + 1) % count} Do".encode()
        objects.append(b"<< /Type /XObject /Subtype /Form /BBox [0 0 1 1] /Resources 5 0 R "
                       b"/Length %d >>\nstream\n" % len(form) + form + b"\nendstream")
    pdf, offsets = b"%PDF-1.4\n", []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    pdf += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(pdf)


def test_copy_retries_without_resource_analysis_after_its_cap(monkeypatch):
    monkeypatch.setenv("HOOVER4_QPDF_MEM_LIMIT_BYTES", str(3 * 1024 ** 3))
    calls = []

    def run(args, file_hash="", page_count=None, limit=None):
        calls.append((args, limit))
        if len(calls) == 1:
            raise ApplicationError("cap", type=parse_pdf.QPDF_MEMORY_CAP, non_retryable=True)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(parse_pdf, "_run_qpdf", run)
    parse_pdf.qpdf_copy_pages(["--warning-exit-0"], ["in.pdf", "1-32"], "out.pdf", "h", 35)
    assert calls == [
        (["--empty", "--warning-exit-0", "--remove-unreferenced-resources=auto",
          "--pages", "in.pdf", "1-32", "--", "out.pdf"], parse_pdf.RESOURCE_ANALYSIS_LIMIT_BYTES),
        (["--empty", "--warning-exit-0", "--remove-unreferenced-resources=no",
          "--pages", "in.pdf", "1-32", "--", "out.pdf"], None),
    ]


def test_copy_does_not_retry_other_errors(monkeypatch):
    def run(args, file_hash="", page_count=None, limit=None):
        raise ApplicationError("other", type="Other", non_retryable=True)

    monkeypatch.setattr(parse_pdf, "_run_qpdf", run)
    with pytest.raises(ApplicationError) as excinfo:
        parse_pdf.qpdf_copy_pages([], ["in.pdf", "1"], "out.pdf")
    assert excinfo.value.type == "Other"


def test_analysis_budget_never_exceeds_the_cap(monkeypatch):
    monkeypatch.setenv("HOOVER4_QPDF_MEM_LIMIT_BYTES", str(64 * 1024 ** 2))
    limits = []

    def run(args, file_hash="", page_count=None, limit=None):
        limits.append(limit)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(parse_pdf, "_run_qpdf", run)
    parse_pdf.qpdf_copy_pages([], ["in.pdf", "1"], "out.pdf")
    assert limits == [64 * 1024 ** 2]


def test_split_of_shared_form_resources_stays_under_the_budget(monkeypatch, tmp_path, caplog):
    """1,000 forms that share the page resources make the analysis use about 870 MiB
    without a cap. The split reaches the 512 MiB budget and copies the page without it."""
    from tasks.P3_parse_files.pdf_parts import split_pdf
    monkeypatch.delenv("HOOVER4_QPDF_MEM_LIMIT_BYTES", raising=False)
    source = tmp_path / "forms.pdf"
    _shared_forms_pdf(source, 1000)
    with caplog.at_level(logging.WARNING, logger=parse_pdf.log.name):
        split_pdf(str(source), str(tmp_path / "part.pdf"), 1, 1, file_hash="hash-e", page_count=1)
    assert parse_pdf._qpdf_show_npages(str(tmp_path / "part.pdf")) == 1
    assert any("resource analysis reached" in r.getMessage() and "hash-e" in r.getMessage()
               for r in caplog.records)


def test_split_of_a_normal_pdf_keeps_resource_removal(monkeypatch, tmp_path, caplog):
    from tasks.P3_parse_files.pdf_parts import split_pdf
    monkeypatch.delenv("HOOVER4_QPDF_MEM_LIMIT_BYTES", raising=False)
    source = tmp_path / "forms.pdf"
    _shared_forms_pdf(source, 20)
    with caplog.at_level(logging.WARNING, logger=parse_pdf.log.name):
        split_pdf(str(source), str(tmp_path / "part.pdf"), 1, 1)
    assert parse_pdf._qpdf_show_npages(str(tmp_path / "part.pdf")) == 1
    assert not any("resource analysis reached" in r.getMessage() for r in caplog.records)
