"""One searchable-PDF render in a child process."""

import base64
import io
import json
import math
import os
import sys

import requests
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


def _draw_invisible_words(canvas, words, scale, page_height_pt):
    from reportlab.pdfbase.pdfmetrics import stringWidth

    drawn = 0
    canvas.setFillColorRGB(0, 0, 0)
    for word in words:
        text = (word.get("text") or "").strip()
        if not text:
            continue
        try:
            left = float(word["left"]) * scale
            top = float(word["top"]) * scale
            width = float(word["width"]) * scale
            height = float(word["height"]) * scale
        except (KeyError, TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        font_size = max(height, 1.0)
        natural = stringWidth(text, "Helvetica", font_size)
        if natural <= 0:
            continue
        obj = canvas.beginText()
        obj.setTextRenderMode(3)
        obj.setFont("Helvetica", font_size)
        obj.setHorizScale(100.0 * width / natural)
        obj.setTextOrigin(left, page_height_pt - top - height)
        obj.textOut(text)
        canvas.drawText(obj)
        drawn += 1
    return drawn


def build_searchable_pdf(pdf_bytes, engine, languages, dpi):
    """Render, OCR, and assemble one PDF."""
    import pypdfium2 as pdfium
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as pdfcanvas

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        count = len(document)
        if count == 0:
            raise HTTPException(422, "the PDF has no pages")
        if count > MAX_PAGES:
            raise HTTPException(413, "the PDF has %d pages, limit is %d" % (count, MAX_PAGES))
        buffer = io.BytesIO()
        canvas = None
        pages_with_text = 0
        for index in range(count):
            page = document[index]
            bitmap = image = None
            try:
                width_pt, height_pt = page.get_size()
                scale = dpi / 72.0
                pixels = width_pt * scale * height_pt * scale
                if pixels > MAX_PAGE_PIXELS:
                    scale *= math.sqrt(MAX_PAGE_PIXELS / pixels)
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil().convert("RGB")
                jpeg = io.BytesIO()
                image.save(jpeg, format="JPEG", quality=JPEG_QUALITY, optimize=True)
                if canvas is None:
                    canvas = pdfcanvas.Canvas(buffer, pagesize=(width_pt, height_pt))
                else:
                    canvas.setPageSize((width_pt, height_pt))
                canvas.drawImage(ImageReader(jpeg), 0, 0, width=width_pt, height=height_pt)
                words = (_ocr_page(engine, languages, jpeg.getvalue()).get("words") or [])
                if _draw_invisible_words(canvas, words, width_pt / image.width, height_pt):
                    pages_with_text += 1
                canvas.showPage()
            finally:
                if image is not None:
                    image.close()
                if bitmap is not None:
                    bitmap.close()
                page.close()
        canvas.save()
        return buffer.getvalue(), count, pages_with_text
    finally:
        document.close()


def main(argv):
    source, destination, engine, languages, dpi = argv[1:6]
    try:
        output, pages, with_text = build_searchable_pdf(open(source, "rb").read(), engine, languages, int(dpi))
        with open(destination, "wb") as target:
            target.write(output)
        print(json.dumps({"ok": True, "page_count": pages, "pages_with_text": with_text}))
    except HTTPException as exc:
        print(json.dumps({"ok": False, "status": exc.status_code, "detail": exc.detail,
                          "headers": exc.headers or {}}))


if __name__ == "__main__":
    main(sys.argv)
