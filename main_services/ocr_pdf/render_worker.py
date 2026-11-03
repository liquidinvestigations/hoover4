"""One searchable-PDF render in a child process."""

import ctypes
import base64
import io
from contextlib import closing
import json
import math
import os
import sys
import unicodedata

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


#: The width of every glyph of the text layer font, in thousandths of the font size.
GLYPH_WIDTH = 500
#: Tesseract's glyphless TrueType font (Apache-2.0). Glyph 1 is an empty glyph with the
#: full em height, so PDFium gives each character the box of its OCR word.
GLYPHLESS_FONT = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdf.ttf"), "rb").read()


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


def _number(value):
    """Write a PDF real without an exponent."""
    text = ("%.4f" % value).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _to_unicode_cmap(characters):
    """Map each two-byte code to its character, in blocks of the 100 entries that a CMap allows."""
    lines = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
             "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
             "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
             "1 begincodespacerange", "<0000> <FFFF>", "endcodespacerange"]
    entries = list(characters.items())
    for start in range(0, len(entries), 100):
        block = entries[start:start + 100]
        lines.append("%d beginbfchar" % len(block))
        lines += ["<%04X> <%s>" % (code, char.encode("utf-16-be").hex().upper()) for char, code in block]
        lines.append("endbfchar")
    lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return "\n".join(lines).encode("ascii")


def _text_layer_pdf(width, height, content, characters):
    """A one-page PDF whose font gives each code one constant width and its character.

    Every code maps to the one glyph of the embedded glyphless font. Text extraction
    reads the ToUnicode map, so it returns every Unicode character.
    """
    import zlib

    def stream(data, extra=b""):
        packed = zlib.compress(data)
        return b"<< /Length %d /Filter /FlateDecode%s >>\nstream\n%s\nendstream" % (len(packed), extra, packed)

    glyph_map = b"\x00\x01" * (len(characters) + 1)

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %s %s] /Resources << /Font << /F1 5 0 R >> >> "
         "/Contents 4 0 R >>" % (_number(width), _number(height))).encode("ascii"),
        stream(content),
        b"<< /Type /Font /Subtype /Type0 /BaseFont /GlyphLessFont /Encoding /Identity-H "
        b"/DescendantFonts [6 0 R] /ToUnicode 8 0 R >>",
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /GlyphLessFont "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        b"/FontDescriptor 7 0 R /DW %d /CIDToGIDMap 10 0 R >>" % GLYPH_WIDTH,
        b"<< /Type /FontDescriptor /FontName /GlyphLessFont /Flags 4 /FontBBox [0 0 %d 1000] "
        b"/ItalicAngle 0 /Ascent 1000 /Descent 0 /CapHeight 1000 /StemV 80 /FontFile2 9 0 R >>" % GLYPH_WIDTH,
        stream(_to_unicode_cmap(characters)),
        stream(GLYPHLESS_FONT, b" /Length1 %d" % len(GLYPHLESS_FONT)),
        stream(glyph_map),
    ]
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def visual_order(text):
    """Return a word with right-to-left letters in the left-to-right order of a PDF.

    PDF readers apply the Unicode bidirectional algorithm to the stored order. A run of
    digits keeps its order, and the other runs are reversed.
    """
    kinds = [unicodedata.bidirectional(char) for char in text]
    if not any(kind in ("R", "AL") for kind in kinds):
        return text
    runs = []
    for char, kind in zip(text, kinds):
        digit = kind in ("EN", "AN")
        if runs and runs[-1][0] == digit:
            runs[-1][1].append(char)
        else:
            runs.append((digit, [char]))
    return "".join("".join(chars if digit else reversed(chars)) for digit, chars in reversed(runs))


def overlay_page(words, to_page, mediabox):
    """Create invisible words relative to the MediaBox origin."""
    x0, y0, x1, y1 = mediabox
    characters = {}
    content = []
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
        natural = len(text) * size * GLYPH_WIDTH / 1000.0
        if length <= 0 or size <= 0 or natural <= 0:
            continue
        # Code 0 stays unused, so a page can map 65535 distinct characters.
        if len(characters) + len(set(text) - characters.keys()) > 0xFFFF:
            continue
        codes = "".join("%04X" % characters.setdefault(char, len(characters) + 1)
                        for char in visual_order(text))
        matrix = (along[0] / length, along[1] / length, rise[0] / size, rise[1] / size,
                  origin[0] - x0, origin[1] - y0)
        content.append("BT 3 Tr /F1 %s Tf %s Tz %s Tm <%s> Tj ET" % (
            _number(size), _number(100.0 * length / natural), " ".join(_number(v) for v in matrix), codes))
        drawn += 1
    return _text_layer_pdf(x1 - x0, y1 - y0, "\n".join(content).encode("ascii"), characters), drawn


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
