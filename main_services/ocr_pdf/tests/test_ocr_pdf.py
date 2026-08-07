"""Tests for the searchable-PDF assembler.

The two things worth pinning are the derived-prefix guard (the cheapest possible defence
against the infinite-ingest loop, plan 2 §11.1) and the geometry of the invisible text
layer — a text layer that is off by a page height is invisible in both senses, and no
integration test would notice because the PDF still opens.
"""

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ocr_pdf  # noqa: E402


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


class _FakeCanvas:
    """Records what would have been drawn, so the geometry can be asserted on."""

    def __init__(self):
        self.texts = []
        self._current = None

    def setFillColorRGB(self, *args):
        pass

    def beginText(self):
        canvas = self

        class _Text:
            def __init__(self):
                self.mode = None
                self.size = None
                self.scale = None
                self.origin = None
                self.body = None

            def setTextRenderMode(self, mode):
                self.mode = mode

            def setFont(self, _name, size):
                self.size = size

            def setHorizScale(self, scale):
                self.scale = scale

            def setTextOrigin(self, x, y):
                self.origin = (x, y)

            def textOut(self, text):
                self.body = text
                canvas._current = self

        return _Text()

    def drawText(self, text_object):
        self.texts.append(text_object)


class TestInvisibleWords:
    def test_words_are_invisible_and_placed_bottom_left(self):
        canvas = _FakeCanvas()
        words = [{"text": "hello", "left": 100, "top": 50, "width": 60, "height": 20}]
        # A 1000 px wide raster of a 500 pt page: one point is two pixels.
        drawn = ocr_pdf._draw_invisible_words(canvas, words, scale=0.5, page_height_pt=800.0)

        assert drawn == 1
        (text,) = canvas.texts
        assert text.mode == 3, "render mode 3 is what makes the layer invisible"
        assert text.body == "hello"
        # x: 100 px * 0.5 = 50 pt. y: the raster's top-left origin flipped into the PDF's
        # bottom-left one -- 800 - (50 + 20) * 0.5.
        assert text.origin == (50.0, 800.0 - 35.0)
        assert text.size == pytest.approx(10.0)

    def test_each_word_is_stretched_to_its_own_box(self):
        canvas = _FakeCanvas()
        words = [{"text": "iiii", "left": 0, "top": 0, "width": 400, "height": 20}]
        ocr_pdf._draw_invisible_words(canvas, words, scale=1.0, page_height_pt=100.0)
        (text,) = canvas.texts
        # "iiii" in Helvetica is far narrower than 400 pt, so the scale must open it up
        # rather than leaving the selection rectangle a fraction of the visible ink.
        assert text.scale > 100.0

    @pytest.mark.parametrize(
        "word",
        [
            {"text": "  ", "left": 0, "top": 0, "width": 10, "height": 10},
            {"text": "x", "left": 0, "top": 0, "width": 0, "height": 10},
            {"text": "x", "left": 0, "top": 0, "width": 10, "height": 0},
            {"text": "x", "left": "nope", "top": 0, "width": 10, "height": 10},
            {"text": "x"},
        ],
    )
    def test_unusable_boxes_are_skipped_not_fatal(self, word):
        """OCR output is data, not a contract: one bad box must not lose the page."""
        canvas = _FakeCanvas()
        assert ocr_pdf._draw_invisible_words(canvas, [word], 1.0, 100.0) == 0
        assert canvas.texts == []


class TestHealth:
    def test_reports_the_renderer_it_can_actually_load(self):
        """The version came off a module attribute that pypdfium2 5.x removed, so
        `/health` said `unavailable` on a perfectly working renderer — a health check
        reporting on its own guess rather than on the thing it checks."""
        body = ocr_pdf.health()
        assert body["status"] == "healthy"
        assert body["renderer"].startswith("pypdfium2 ")
        assert body["renderer"] != "pypdfium2 "
        # Configured, not reachable: an unreachable tier changes between two health
        # checks and would make this service's health flap with someone else's.
        assert set(body["engines"]) == {"tesseract", "easyocr"}


class TestBuildSearchablePdf:
    def _one_page_pdf(self) -> bytes:
        from reportlab.pdfgen import canvas as pdfcanvas

        buffer = io.BytesIO()
        canvas = pdfcanvas.Canvas(buffer, pagesize=(612, 792))
        canvas.drawString(72, 700, "scanned text")
        canvas.showPage()
        canvas.save()
        return buffer.getvalue()

    def test_round_trips_a_page_and_keeps_its_size(self, monkeypatch):
        monkeypatch.setattr(
            ocr_pdf,
            "_ocr_page",
            lambda *a, **k: {"words": [
                {"text": "scanned", "left": 200, "top": 250, "width": 200, "height": 40},
            ]},
        )
        out, pages, with_text = ocr_pdf.build_searchable_pdf(
            self._one_page_pdf(), "tesseract", "eng", 100
        )
        assert pages == 1
        assert with_text == 1
        assert out.startswith(b"%PDF-")

        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(out)
        try:
            assert len(document) == 1
            width, height = document[0].get_size()
            # Page geometry has to survive: the viewer's page jump and the stored
            # `text_content.page_id` rows are matched against this file.
            assert (round(width), round(height)) == (612, 792)
        finally:
            document.close()

    def test_a_page_the_engine_read_nothing_on_is_still_a_page(self, monkeypatch):
        monkeypatch.setattr(ocr_pdf, "_ocr_page", lambda *a, **k: {"words": []})
        out, pages, with_text = ocr_pdf.build_searchable_pdf(
            self._one_page_pdf(), "tesseract", "eng", 72
        )
        assert (pages, with_text) == (1, 0)
        assert out.startswith(b"%PDF-")
