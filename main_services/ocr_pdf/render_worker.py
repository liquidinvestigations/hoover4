"""One searchable-PDF render in a child process."""

import ctypes
import base64
import io
from contextlib import closing
import json
import math
import os
import sys

import requests
import pypdfium2 as pdfium
import pypdfium2.raw as raw
from fastapi import HTTPException

MAX_PAGES = int(os.getenv("OCR_PDF_MAX_PAGES", "2000"))
MAX_PAGE_PIXELS = int(os.getenv("OCR_PDF_MAX_PAGE_PIXELS", "40000000"))
JPEG_QUALITY = int(os.getenv("OCR_PDF_JPEG_QUALITY", "75"))
OCR_READ_TIMEOUT = float(os.getenv("OCR_READ_TIMEOUT_SECONDS", "600"))
OCR_ENDPOINTS = {
    "tesseract": (os.getenv("OCR_TESSERACT_URL") or "").strip(),
    "easyocr": (os.getenv("OCR_EASYOCR_URL") or "").strip(),
}


def _ocr_page(engine, languages, image_bytes):
    url = OCR_ENDPOINTS.get(engine, "")
    if not url:
        raise HTTPException(501, "OCR engine %r has no endpoint configured" % engine)
    try:
        response = requests.post(url, json={
            "image_b64": base64.b64encode(image_bytes).decode("ascii"),
            "languages": languages,
        }, timeout=(5, OCR_READ_TIMEOUT))
    except requests.RequestException as exc:
        raise HTTPException(503, "OCR tier unreachable: %s" % exc)
    if response.status_code == 503:
        raise HTTPException(503, "OCR tier queue is full",
                            headers={"Retry-After": response.headers.get("Retry-After", "5")})
    if response.status_code >= 400:
        raise HTTPException(422, "OCR tier said %d: %s" % (response.status_code, response.text[:300]))
    return response.json()


FONT = "Helvetica"


def text_objects(page):
    """Visit text objects through every nested form."""
    def visit(obj):
        kind = raw.FPDFPageObj_GetType(obj)
        if kind == raw.FPDF_PAGEOBJ_TEXT:
            yield obj
        elif kind == raw.FPDF_PAGEOBJ_FORM:
            for index in range(raw.FPDFFormObj_CountObjects(obj)):
                yield from visit(raw.FPDFFormObj_GetObject(obj, index))
    for index in range(raw.FPDFPage_CountObjects(page)):
        yield from visit(raw.FPDFPage_GetObject(page, index))


def device_to_page_affine(page, size_x, size_y):
    """Map render pixels to page coordinates from three device corners."""
    def point(dx, dy):
        x, y = ctypes.c_double(), ctypes.c_double()
        ok = raw.FPDF_DeviceToPage(page.raw, 0, 0, size_x, size_y, 0, dx, dy,
                                   ctypes.byref(x), ctypes.byref(y))
        if not ok:
            raise RuntimeError("FPDF_DeviceToPage failed")
        return x.value, y.value
    o, ex, ey = point(0, 0), point(size_x, 0), point(0, size_y)
    ax, bx = (ex[0] - o[0]) / size_x, (ex[1] - o[1]) / size_x
    ay, by = (ey[0] - o[0]) / size_y, (ey[1] - o[1]) / size_y

    def apply(dx, dy):
        return o[0] + ax * dx + ay * dy, o[1] + bx * dx + by * dy
    return apply


def text_free_render(page, dpi):
    """Deactivate text objects with Unicode text, render, and return the raster and counts."""
    with closing(page.get_textpage()) as textpage:
        deactivated = kept = 0
        for obj in text_objects(page.raw):
            # The length includes the two-byte terminator.
            if raw.FPDFTextObj_GetText(obj, textpage.raw, None, 0) > 2:
                if not raw.FPDFPageObj_SetIsActive(obj, False):
                    raise RuntimeError("could not deactivate a Unicode text object")
                deactivated += 1
            else:
                kept += 1
        width, height = page.get_size()
        scale = dpi / 72.0
        pixels = width * scale * height * scale
        if pixels > MAX_PAGE_PIXELS:
            scale *= math.sqrt(MAX_PAGE_PIXELS / pixels)
        bitmap = page.render(scale=scale, may_draw_forms=False, draw_annots=False)
        try:
            return bitmap.to_pil().convert("RGB"), deactivated, kept
        finally:
            bitmap.close()


def overlay_page(words, to_page, mediabox):
    """Create invisible words relative to the MediaBox origin."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas as pdfcanvas

    x0, y0, x1, y1 = mediabox
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=(x1 - x0, y1 - y0))
    drawn = 0
    for word in words:
        text = (word.get("text") or "").strip()
        if not text:
            continue
        try:
            left, top = float(word["left"]), float(word["top"])
            width, height = float(word["width"]), float(word["height"])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in (left, top, width, height)):
            continue
        if width <= 0 or height <= 0:
            continue
        origin = to_page(left, top + height)
        end = to_page(left + width, top + height)
        up = to_page(left, top)
        along = (end[0] - origin[0], end[1] - origin[1])
        rise = (up[0] - origin[0], up[1] - origin[1])
        length, size = math.hypot(*along), math.hypot(*rise)
        natural = stringWidth(text, FONT, size)
        if length <= 0 or size <= 0 or natural <= 0:
            continue
        t = c.beginText()
        t.setTextRenderMode(3)
        t.setFont(FONT, size)
        t.setHorizScale(100.0 * length / natural)
        t.setTextTransform(along[0] / length, along[1] / length, rise[0] / size, rise[1] / size,
                           origin[0] - x0, origin[1] - y0)
        t.textOut(text)
        c.drawText(t)
        drawn += 1
    c.showPage()
    c.save()
    return buf.getvalue(), drawn


def selected_pages(count, pages):
    """Resolve omitted pages and verify explicit local page numbers."""
    if pages is None:
        return list(range(1, count + 1))
    if any(type(page) is not int or page < 1 or page > count for page in pages):
        raise HTTPException(400, "ocr_pages must contain local page numbers within the source")
    if len(set(pages)) != len(pages):
        raise HTTPException(400, "ocr_pages must not contain duplicates")
    return sorted(pages)


def build_pdf(source, destination, engine, languages, dpi, ocr_pages=None):
    """Add invisible OCR overlays to selected source pages and save the complete PDF."""
    with pdfium.PdfDocument(source) as render_doc, pdfium.PdfDocument(source) as output_doc:
        count = len(render_doc)
        if not count:
            raise HTTPException(422, "the PDF has no pages")
        if count > MAX_PAGES:
            raise HTTPException(413, "the PDF has %d pages, limit is %d" % (count, MAX_PAGES))
        pages = []
        with_text = 0
        for number in selected_pages(count, ocr_pages):
            with closing(render_doc[number - 1]) as page:
                image, _, _ = text_free_render(page, dpi)
                try:
                    to_page = device_to_page_affine(page, image.width, image.height)
                    jpeg = io.BytesIO()
                    image.save(jpeg, format="JPEG", quality=JPEG_QUALITY, optimize=True)
                finally:
                    image.close()
            result = _ocr_page(engine, languages, jpeg.getvalue())
            words = result.get("words") or []
            with closing(output_doc[number - 1]) as target:
                mediabox = target.get_mediabox()
                layer_bytes, drawn = overlay_page(words, to_page, mediabox)
                if drawn:
                    with pdfium.PdfDocument(layer_bytes) as layer:
                        xobject = layer.page_as_xobject(0, output_doc)
                        try:
                            form = xobject.as_pageobject()
                            form.set_matrix(pdfium.PdfMatrix().translate(mediabox[0], mediabox[1]))
                            target.insert_obj(form)
                            target.gen_content()
                        finally:
                            xobject.close()
                    with_text += 1
            pages.append({"page": number, "text": result.get("text") or "",
                          "words": words, "confidence": result.get("confidence")})
        output_doc.save(destination, flags=0)
    return {"page_count": count, "pages_with_text": with_text, "pages": pages}


def build_image(source, destination, words, ocr_pages=None):
    """Create an image PDF from stored word boxes without an OCR request."""
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as pdfcanvas

    wanted = selected_pages(1, ocr_pages)
    with Image.open(source) as image:
        width, height = image.size
        resolution = image.info.get("dpi", (150.0, 150.0))[0] or 150.0
        if not math.isfinite(float(resolution)) or resolution <= 0:
            resolution = 150.0
        scale = 72.0 / resolution
        page_width, page_height = width * scale, height * scale
        if image.format == "JPEG":
            reader = source
        else:
            with image.convert("RGB" if image.mode not in ("L", "RGB") else image.mode) as plain:
                candidates = []
                for fmt, options in (("PNG", {}), ("JPEG", {"quality": 85})):
                    buffer = io.BytesIO()
                    plain.save(buffer, format=fmt, **options)
                    candidates.append(buffer.getvalue())
                reader = ImageReader(io.BytesIO(min(candidates, key=len)))
        canvas = pdfcanvas.Canvas(destination, pagesize=(page_width, page_height))
        canvas.drawImage(reader, 0, 0, width=page_width, height=page_height)
        layer_bytes, drawn = overlay_page(words if wanted else [],
                                         lambda x, y: (x * scale, page_height - y * scale),
                                         (0, 0, page_width, page_height))
        canvas.showPage()
        canvas.save()
    if drawn:
        with pdfium.PdfDocument(destination) as output, pdfium.PdfDocument(layer_bytes) as layer:
            with closing(output[0]) as target:
                xobject = layer.page_as_xobject(0, output)
                try:
                    target.insert_obj(xobject.as_pageobject())
                    target.gen_content()
                finally:
                    xobject.close()
            # Save to another path because PDFium retains the source file handle.
            temporary = destination + ".overlay"
            try:
                output.save(temporary, flags=0)
                os.replace(temporary, destination)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    text = " ".join((word.get("text") or "").strip() for word in words).strip()
    return {"page_count": 1, "pages_with_text": int(bool(drawn)),
            "pages": [{"page": 1, "text": text, "words": words, "confidence": None}] if wanted else []}


def build_searchable_pdf(pdf_bytes, engine, languages, dpi):
    """Support direct callers of the former byte-based helper."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="ocr-pdf-helper-") as folder:
        destination = os.path.join(folder, "result.pdf")
        result = build_pdf(pdf_bytes, destination, engine, languages, dpi)
        with open(destination, "rb") as handle:
            return handle.read(), result["page_count"], result["pages_with_text"]


def main(argv):
    source, destination, engine, languages, dpi = argv[1:6]
    options = {}
    if len(argv) > 6:
        with open(argv[6]) as handle:
            options = json.load(handle)
    try:
        if options.get("mode", "pdf") == "image":
            result = build_image(source, destination, options.get("words") or [], options.get("ocr_pages"))
        else:
            result = build_pdf(source, destination, engine, languages, int(dpi), options.get("ocr_pages"))
        print(json.dumps({"ok": True, **result}))
    except HTTPException as exc:
        print(json.dumps({"ok": False, "status": exc.status_code, "detail": exc.detail,
                          "headers": exc.headers or {}}))
    except Exception as exc:
        print(json.dumps({"ok": False, "status": 422, "detail": "could not assemble the PDF: %s" % exc}))


if __name__ == "__main__":
    main(sys.argv)
