"""Verify the production builder, resource limits, and request compatibility."""
import asyncio
import io
from contextlib import closing
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ocr_pdf  # noqa: E402
import render_worker  # noqa: E402


class TestValidateDestKey:
    def test_accepts_a_derived_key(self):
        key = "derived/ocr-pdf/testdata_testfiles/abc123/tesseract+eng.pdf"
        assert ocr_pdf.validate_dest_key(key) == key

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "blobs/testdata/abc.pdf",
            "testdata_testfiles/abc.pdf",
            "/derived/x.pdf",
            "derived/../blobs/x.pdf",
            "derived/ocr-pdf/",
            "DERIVED/x.pdf",
        ],
    )
    def test_refuses_anything_the_walker_could_see(self, bad):
        """A key outside `derived/` gets ingested, OCR'd and re-derived, forever."""
        with pytest.raises(ValueError):
            ocr_pdf.validate_dest_key(bad)

    def test_strips_surrounding_whitespace_before_judging(self):
        assert ocr_pdf.validate_dest_key("  derived/a/b.pdf  ") == "derived/a/b.pdf"


class TestHealth:
    def test_reports_the_renderer_it_can_actually_load(self):
        """The version came off a module attribute that pypdfium2 5.x removed, so
        `/health` said `unavailable` on a perfectly working renderer, which is a health check
        reporting on its own guess rather than on the thing it checks."""
        body = asyncio.run(ocr_pdf.health())
        assert body["status"] == "healthy"
        assert body["renderer"].startswith("pypdfium2 ")
        assert body["renderer"] != "pypdfium2 "
        # Configured, not reachable: an unreachable tier changes between two health
        # checks and would make this service's health flap with someone else's.
        assert set(body["engines"]) == {"tesseract", "easyocr"}
        assert body["http_threads"] == ocr_pdf.HTTP_THREADS

    def test_handler_threads_cover_the_admission(self):
        """FastAPI runs a `def` handler on AnyIO's thread limiter, 40 by default. Above
        that, admitted requests waited for a thread with no answer, and `/health` with them."""
        import anyio.to_thread

        async def limit_inside_lifespan():
            async with ocr_pdf.lifespan(ocr_pdf.app):
                return anyio.to_thread.current_default_thread_limiter().total_tokens

        assert asyncio.run(limit_inside_lifespan()) == (
            ocr_pdf.OCR_PDF_CONCURRENCY + ocr_pdf.OCR_PDF_QUEUE_DEPTH + 4)



import base64
import hashlib
import json
import os
import subprocess
import re
from types import SimpleNamespace

import pypdfium2 as pdfium
import pypdfium2.raw as raw
from fastapi import HTTPException, Response
from PIL import Image, ImageChops, ImageOps
from reportlab.pdfgen import canvas as pdfcanvas

from overlay_fixtures import base_pdf, image_box, text_image, variant


def native_pdf(count=2):
    buffer = io.BytesIO()
    canvas = pdfcanvas.Canvas(buffer, pagesize=(612, 792))
    for number in range(count):
        canvas.drawString(72, 700, "NATIVEWORD page %d" % (number + 1))
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def page_text(document, index):
    with closing(document[index]) as page, closing(page.get_textpage()) as text:
        return text.get_text_range()


def page_pixels(document, index):
    with closing(document[index]) as page:
        bitmap = page.render(scale=1)
        try:
            return bitmap.to_pil().convert("RGB")
        finally:
            bitmap.close()


def image_data(page):
    import ctypes
    streams = []
    for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE], max_depth=50):
        size = raw.FPDFImageObj_GetImageDataRaw(obj.raw, None, 0)
        buffer = ctypes.create_string_buffer(size)
        raw.FPDFImageObj_GetImageDataRaw(obj.raw, buffer, size)
        streams.append(buffer.raw)
    return streams


@pytest.mark.parametrize("name,rotation", [
    ("base", 0), ("rotate90", 90), ("rotate180", 180),
    ("rotate270_crop", 270), ("crop", 0), ("mediabox_offset", 0),
])
def test_production_overlay_geometry_and_native_content(tmp_path, monkeypatch, name, rotation):
    source = variant(base_pdf(text_image(), rotation), name, str(tmp_path))
    destination = str(tmp_path / "output.pdf")
    calls = []

    def ocr(engine, languages, raster):
        with Image.open(io.BytesIO(raster)) as image:
            gray = image.convert("L")
            bounds = ImageOps.invert(gray).point(lambda value: 255 if value > 100 else 0).getbbox()
            assert bounds is not None
            # The displayed native lines occupy the upper page. Only the image remains.
            assert bounds[1] > image.height * (0.15 if name == "crop" else 0.3)
            assert bounds[3] < image.height * 0.9
            left, top, right, bottom = bounds
            words = [{"text": "OCRMARK", "left": left, "top": top,
                      "width": right - left, "height": bottom - top}]
            calls.append(words)
            return {"text": "OCRMARK", "words": words, "confidence": 0.9}

    monkeypatch.setattr(render_worker, "_ocr_page", ocr)
    result = render_worker.build_pdf(source, destination, "tesseract", "eng", 100, [1])
    assert len(calls) == 1
    assert result["pages"] == [{"page": 1, "text": "OCRMARK", "words": calls[0], "confidence": 0.9}]
    assert result["pages_with_text"] == 1
    streams = lambda data: re.findall(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S)
    original_streams = streams(Path(source).read_bytes())
    output_streams = streams(Path(destination).read_bytes())
    assert original_streams
    assert all(stream in output_streams for stream in original_streams)
    with pdfium.PdfDocument(source) as before, pdfium.PdfDocument(destination) as after:
        assert "NATIVEWORD" in page_text(after, 0)
        assert "FORMWORD" in page_text(after, 0)
        assert "OCRMARK" in page_text(after, 0)
        with closing(before[0]) as original, closing(after[0]) as output, closing(output.get_textpage()) as text:
            assert output.get_mediabox() == original.get_mediabox()
            assert output.get_cropbox() == original.get_cropbox()
            assert output.get_rotation() == original.get_rotation()
            assert image_data(output) == image_data(original)
            search = text.search("OCRMARK")
            try:
                start, count = search.get_next()
                boxes = [text.get_charbox(index) for index in range(start, start + count)]
            finally:
                search.close()
            x = sum((box[0] + box[2]) / 2 for box in boxes) / len(boxes)
            y = sum((box[1] + box[3]) / 2 for box in boxes) / len(boxes)
            x0, y0, x1, y1 = image_box(rotation)
            assert x0 <= x <= x1
            assert y0 <= y <= y1
        with page_pixels(before, 0) as a, page_pixels(after, 0) as b:
            assert ImageChops.difference(a, b).getbbox() is None


def test_selected_pages_empty_text_and_unchanged_unselected_page(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    source.write_bytes(native_pdf())
    destination = tmp_path / "output.pdf"
    calls = []
    monkeypatch.setattr(render_worker, "_ocr_page", lambda *args: calls.append(args) or {"words": [], "text": ""})
    result = render_worker.build_pdf(str(source), str(destination), "tesseract", "eng", 72, [2])
    assert len(calls) == 1
    assert result == {"page_count": 2, "pages_with_text": 0,
                      "pages": [{"page": 2, "text": "", "words": [], "confidence": None}]}
    with pdfium.PdfDocument(source) as before, pdfium.PdfDocument(destination) as after:
        assert page_text(before, 0) == page_text(after, 0)
        assert page_text(before, 1) == page_text(after, 1)
        with page_pixels(before, 0) as a, page_pixels(after, 0) as b:
            assert ImageChops.difference(a, b).getbbox() is None
    calls.clear()
    result = render_worker.build_pdf(str(source), str(destination), "tesseract", "eng", 72, [])
    assert result["pages"] == []
    assert calls == []
    result = render_worker.build_pdf(str(source), str(destination), "tesseract", "eng", 72)
    assert [page["page"] for page in result["pages"]] == [1, 2]


def test_unextractable_text_object_stays_active(tmp_path, monkeypatch):
    with pdfium.PdfDocument(native_pdf(1)) as doc, closing(doc[0]) as page:
        kept = list(render_worker.text_objects(page.raw))[0]
        monkeypatch.setattr(raw, "FPDFTextObj_GetText",
                            lambda obj, *args: 2)
        image, deactivated, retained = render_worker.text_free_render(page, 72)
        try:
            assert retained == 1
            assert deactivated == 0
            assert ImageOps.invert(image.convert("L")).getbbox() is not None
        finally:
            image.close()
        active = __import__("ctypes").c_int()
        assert raw.FPDFPageObj_GetIsActive(kept, __import__("ctypes").byref(active))
        assert active.value == 1


@pytest.mark.parametrize("pages", [[0], [3], [1, 1], [-1], [True]])
def test_invalid_page_selection_fails_before_ocr(tmp_path, monkeypatch, pages):
    monkeypatch.setattr(render_worker, "_ocr_page", lambda *args: pytest.fail("unexpected OCR"))
    with pytest.raises(HTTPException) as exc:
        render_worker.build_pdf(native_pdf(), str(tmp_path / "out.pdf"), "tesseract", "eng", 72, pages)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("fmt", ["JPEG", "PNG"])
def test_image_mode_preserves_image_and_uses_stored_words(tmp_path, monkeypatch, fmt):
    monkeypatch.setattr(render_worker, "MAX_PAGE_PIXELS", 40000)
    source = tmp_path / ("input." + fmt.lower())
    with Image.new("RGB", (400, 300), "white") as image:
        image.save(source, format=fmt, dpi=(150, 150))
    words = [{"text": "stored", "left": 10, "top": 20, "width": 100, "height": 25}]
    monkeypatch.setattr(render_worker, "_ocr_page", lambda *args: pytest.fail("unexpected OCR"))
    destination = str(tmp_path / "output.pdf")
    result = render_worker.build_image(str(source), destination, words)
    assert result["pages"][0]["text"] == "stored"
    with pdfium.PdfDocument(destination) as doc:
        assert "stored" in page_text(doc, 0)
        with closing(doc[0]) as page:
            assert page.get_size() == pytest.approx((192, 144), rel=0.001)
            streams = image_data(page)
            assert len(streams) == 1
            if fmt == "JPEG":
                assert base64.a85decode(streams[0], adobe=True) == source.read_bytes()


class FakeStore:
    def __init__(self, source):
        self.source = source
        self.uploaded = None
        self.paths = []
        self.downloads = 0
        self.bucket_calls = []

    def stat_object(self, bucket, key):
        self.bucket_calls.append(("stat", bucket))
        return SimpleNamespace(size=len(self.source))

    def fget_object(self, bucket, key, path):
        self.bucket_calls.append(("get", bucket))
        self.paths.append(path)
        self.downloads += 1
        Path(path).write_bytes(self.source)

    def fput_object(self, bucket, key, path, content_type):
        self.bucket_calls.append(("put", bucket))
        self.paths.append(path)
        self.uploaded = Path(path).read_bytes()
        assert content_type == "application/pdf"


@pytest.mark.parametrize("inline_field,pages", [("pdf_b64", None), ("source_b64", []), ("source_key", [])])
def test_http_source_contract_and_streamed_cleanup(tmp_path, monkeypatch, inline_field, pages):
    store = FakeStore(native_pdf())
    monkeypatch.setattr(ocr_pdf, "_s3", lambda: store)
    # Real child path exercises the production source loaded from the mount.
    if pages is None:
        # No OCR endpoint is needed for this legacy request test.
        def renderer(source, destination, *args):
            assert args[-2] is None
            Path(destination).write_bytes(Path(source).read_bytes())
            return {"page_count": 2, "pages_with_text": 0, "pages": []}
        monkeypatch.setattr(ocr_pdf, "run_renderer", renderer)
    payload = {"dest_key": "derived/test.pdf"}
    payload[inline_field] = "source.pdf" if inline_field == "source_key" else base64.b64encode(store.source).decode()
    if pages is not None:
        payload["ocr_pages"] = pages
    result = ocr_pdf.ocr_pdf(ocr_pdf.OcrPdfRequest(**payload), Response())
    assert result.page_count == 2
    assert result.pages == []
    assert result.blob_hash == hashlib.sha3_256(store.uploaded).hexdigest()
    assert store.downloads == int(inline_field == "source_key")
    assert all(not Path(path).exists() for path in store.paths)


@pytest.mark.parametrize("source_bucket", ["", "stored-source-bucket"])
def test_source_bucket_does_not_change_output_ownership(monkeypatch, source_bucket):
    store = FakeStore(native_pdf())
    monkeypatch.setattr(ocr_pdf, "_s3", lambda: store)
    result = ocr_pdf.ocr_pdf(ocr_pdf.OcrPdfRequest(
        bucket="owned-output-bucket", source_bucket=source_bucket,
        source_key="source.pdf", dest_key="derived/output.pdf", ocr_pages=[]), Response())
    assert result.page_count == 2
    assert store.bucket_calls == [
        ("stat", source_bucket or "owned-output-bucket"),
        ("get", source_bucket or "owned-output-bucket"),
        ("put", "owned-output-bucket"),
    ]


def test_large_stored_word_list_uses_file_child_contract(tmp_path, monkeypatch):
    source = tmp_path / "source.jpg"
    with Image.new("RGB", (200, 200), "white") as image:
        image.save(source, "JPEG")
    words = [{"text": "stored", "left": 10, "top": 10, "width": 50, "height": 10}] * 2200
    assert len(json.dumps(words)) > 128 * 1024
    result = ocr_pdf.run_renderer(str(source), str(tmp_path / "out.pdf"), "tesseract", "eng", 72, "image", None, words)
    assert result["page_count"] == 1
    assert len(result["pages"][0]["words"]) == 2200
    assert not (tmp_path / "out.pdf.request.json").exists()


@pytest.mark.parametrize("failure", ["timeout", "signal", "invalid", "transient"])
def test_child_failures_keep_status_and_clean_options(tmp_path, monkeypatch, failure):
    def run(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args[0], 1)
        if failure == "signal":
            return SimpleNamespace(returncode=-9, stdout="")
        if failure == "invalid":
            return SimpleNamespace(returncode=1, stdout="")
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": False, "status": 503,
                               "detail": "busy", "headers": {"Retry-After": "17"}}))
    monkeypatch.setattr(ocr_pdf.subprocess, "run", run)
    destination = str(tmp_path / "out.pdf")
    with pytest.raises(HTTPException) as exc:
        ocr_pdf.run_renderer("source", destination, "tesseract", "eng", 72)
    assert exc.value.status_code == {"timeout": 504, "signal": 422, "invalid": 500, "transient": 503}[failure]
    if failure == "transient":
        assert exc.value.headers == {"Retry-After": "17"}
    assert not Path(destination + ".request.json").exists()


def test_input_limit_prevents_object_download(monkeypatch):
    store = FakeStore(native_pdf())
    monkeypatch.setattr(ocr_pdf, "MAX_PDF_BYTES", 1)
    monkeypatch.setattr(ocr_pdf, "_s3", lambda: store)
    with pytest.raises(HTTPException) as exc:
        ocr_pdf.ocr_pdf(ocr_pdf.OcrPdfRequest(source_key="input.pdf", dest_key="derived/out.pdf"), Response())
    assert exc.value.status_code == 413
    assert store.downloads == 0


@pytest.mark.parametrize("encoded", ["@@@", "YQ==" + "A" * 65536])
def test_bad_inline_input_fails_and_releases_admission(monkeypatch, encoded):
    monkeypatch.setattr(ocr_pdf, "_s3", lambda: FakeStore(b""))
    with pytest.raises(HTTPException) as exc:
        ocr_pdf.ocr_pdf(ocr_pdf.OcrPdfRequest(source_b64=encoded, dest_key="derived/out.pdf"), Response())
    assert exc.value.status_code == 400
    assert ocr_pdf._inflight.acquire(blocking=False)
    ocr_pdf._inflight.release()


def test_image_http_mode_with_unconfigured_ocr_endpoint(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with Image.new("RGB", (200, 150), "white") as image:
        image.save(buffer, "JPEG")
    store = FakeStore(buffer.getvalue())
    monkeypatch.setattr(ocr_pdf, "_s3", lambda: store)
    monkeypatch.setenv("OCR_TESSERACT_URL", "")
    monkeypatch.setitem(ocr_pdf.OCR_ENDPOINTS, "tesseract", "")
    result = ocr_pdf.ocr_pdf(ocr_pdf.OcrPdfRequest(
        source_b64=base64.b64encode(store.source).decode(), dest_key="derived/image.pdf", mode="image",
        words=[{"text": "stored", "left": 10, "top": 10, "width": 50, "height": 10}],
    ), Response())
    assert result.page_count == 1
    assert result.pages[0]["text"] == "stored"
    assert all(not Path(path).exists() for path in store.paths)


def test_actual_timeout_kills_child_and_cleans_request(tmp_path, monkeypatch):
    child = tmp_path / "sleep.py"
    marker = tmp_path / "child.pid"
    child.write_text("import os, time\nfrom pathlib import Path\nPath(%r).write_text(str(os.getpid()))\ntime.sleep(60)\n" % str(marker))
    monkeypatch.setattr(ocr_pdf, "RENDER_WORKER_COMMAND", [sys.executable, str(child)])
    monkeypatch.setattr(ocr_pdf, "RENDER_TIMEOUT_SECONDS", 0.3)
    destination = str(tmp_path / "out.pdf")
    with pytest.raises(HTTPException) as exc:
        ocr_pdf.run_renderer("input", destination, "tesseract", "eng", 72)
    assert exc.value.status_code == 504
    pid = int(marker.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert not Path(destination + ".request.json").exists()


def test_renderer_failure_cleans_server_temporary_files(monkeypatch):
    store = FakeStore(native_pdf())
    monkeypatch.setattr(ocr_pdf, "_s3", lambda: store)
    def fail(*args):
        raise HTTPException(503, "busy", headers={"Retry-After": "12"})
    monkeypatch.setattr(ocr_pdf, "run_renderer", fail)
    with pytest.raises(HTTPException) as exc:
        ocr_pdf.ocr_pdf(ocr_pdf.OcrPdfRequest(source_key="input", dest_key="derived/out.pdf"), Response())
    assert exc.value.status_code == 503
    assert exc.value.headers == {"Retry-After": "12"}
    assert store.uploaded is None
    assert all(not Path(path).exists() for path in store.paths)


def test_independent_page_and_pixel_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(render_worker, "MAX_PAGES", 1)
    with pytest.raises(HTTPException) as exc:
        render_worker.build_pdf(native_pdf(2), str(tmp_path / "out.pdf"), "tesseract", "eng", 72, [])
    assert exc.value.status_code == 413
    monkeypatch.setattr(render_worker, "MAX_PAGE_PIXELS", 40000)
    with pdfium.PdfDocument(native_pdf(1)) as doc, closing(doc[0]) as page:
        image, _, _ = render_worker.text_free_render(page, 400)
        try:
            assert image.width * image.height < 40500
        finally:
            image.close()


@pytest.mark.parametrize("word", [
    {"text": "x"}, {"text": "x", "left": "nope", "top": 0, "width": 10, "height": 10},
    {"text": "x", "left": 0, "top": 0, "width": float("nan"), "height": 10},
    {"text": "x", "left": 0, "top": 0, "width": 0, "height": 10},
])
def test_bad_word_box_does_not_fail_page(word):
    _, drawn = render_worker.overlay_page([word], lambda x, y: (x, y), (0, 0, 100, 100))
    assert drawn == 0


def test_source_above_split_target_has_no_builder_cutoff(tmp_path):
    source = tmp_path / "large.pdf"
    source.write_bytes(native_pdf(1) + b"\n%" + b" " * 26_000_000)
    result = ocr_pdf.run_renderer(str(source), str(tmp_path / "out.pdf"), "tesseract", "eng", 72, ocr_pages=[])
    assert result["page_count"] == 1
    assert result["pages"] == []


def test_queue_full_returns_retry_after_before_store_access(monkeypatch):
    class FullAdmission:
        def acquire(self, blocking):
            return False
    monkeypatch.setattr(ocr_pdf, "_inflight", FullAdmission())
    monkeypatch.setattr(ocr_pdf, "_s3", lambda: pytest.fail("unexpected storage access"))
    with pytest.raises(HTTPException) as exc:
        ocr_pdf.ocr_pdf(ocr_pdf.OcrPdfRequest(dest_key="derived/out.pdf"), Response())
    assert exc.value.status_code == 503
    assert exc.value.headers == {"Retry-After": "10"}


def test_upload_failure_cleans_server_temporary_files(monkeypatch):
    store = FakeStore(native_pdf())
    monkeypatch.setattr(ocr_pdf, "_s3", lambda: store)
    def upload(bucket, key, path, **kwargs):
        store.paths.append(path)
        raise RuntimeError("upload failed")
    monkeypatch.setattr(store, "fput_object", upload)
    with pytest.raises(RuntimeError, match="upload failed"):
        ocr_pdf.ocr_pdf(ocr_pdf.OcrPdfRequest(source_key="input", ocr_pages=[], dest_key="derived/out.pdf"), Response())
    assert all(not Path(path).exists() for path in store.paths)


@pytest.mark.parametrize("inline_field,selection,wanted", [
    ("pdf_b64", None, [1, 2]), ("source_b64", [2], [2]), ("source_b64", [], []),
])
def test_actual_child_http_contract_with_stub_ocr(monkeypatch, inline_field, selection, wanted):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert payload["languages"] == "eng"
            with Image.open(io.BytesIO(base64.b64decode(payload["image_b64"]))) as image:
                assert ImageOps.invert(image.convert("L")).getbbox() is None
            calls.append(payload)
            body = json.dumps({"text": "OCR only", "words": [
                {"text": "OCR", "left": 10, "top": 10, "width": 50, "height": 20},
            ], "confidence": 0.8}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("OCR_TESSERACT_URL", "http://127.0.0.1:%d" % server.server_port)
        store = FakeStore(native_pdf())
        monkeypatch.setattr(ocr_pdf, "_s3", lambda: store)
        payload = {inline_field: base64.b64encode(store.source).decode(), "dest_key": "derived/contract.pdf"}
        if selection is not None:
            payload["ocr_pages"] = selection
        result = ocr_pdf.ocr_pdf(ocr_pdf.OcrPdfRequest(**payload), Response())
        assert [page["page"] for page in result.pages] == wanted
        assert len(calls) == len(wanted)
        assert all(page["text"] == "OCR only" for page in result.pages)
        assert result.pages_with_text == len(wanted)
        with pdfium.PdfDocument(store.uploaded) as output:
            for index in range(2):
                text = page_text(output, index)
                assert "NATIVEWORD" in text
                assert ("OCR" in text) == (index + 1 in wanted)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
