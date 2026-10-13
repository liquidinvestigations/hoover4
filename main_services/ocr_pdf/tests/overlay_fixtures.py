"""Create source pages for production overlay geometry tests."""
import io
import json
import os
import sys

import pypdfium2 as pdfium
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas

W, H = 612.0, 792.0
IMAGE_BOX = (100.0, 300.0, 500.0, 420.0)  # x0, y0, x1, y1 in user space


def text_image():
    """A 200 dpi raster of the image words, made by rendering a ReportLab page."""
    buf = io.BytesIO()
    width_pt, height_pt = IMAGE_BOX[2] - IMAGE_BOX[0], IMAGE_BOX[3] - IMAGE_BOX[1]
    c = pdfcanvas.Canvas(buf, pagesize=(width_pt, height_pt))
    c.setFont("Helvetica-Bold", 26)
    c.drawString(12, height_pt - 45, "IMAGEWORD QUOKKA")
    c.drawString(12, height_pt - 90, "ZEPHYR Straße")
    c.showPage()
    c.save()
    doc = pdfium.PdfDocument(buf.getvalue())
    image = doc[0].render(scale=200 / 72).to_pil().convert("L")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


#: /Rotate value -> (MediaBox size, translate, rotate) that keeps the displayed page upright.
TURNS = {0: ((W, H), (0, 0), 0), 90: ((H, W), (H, 0), 90),
         180: ((W, H), (W, H), 180), 270: ((H, W), (0, W), -90)}


def to_user(rotation, x, y):
    """User-space point of a point of the upright page drawn under TURNS[rotation]."""
    import math
    _, (tx, ty), degrees = TURNS[rotation]
    a = math.radians(degrees)
    return (round(tx + x * math.cos(a) - y * math.sin(a), 3),
            round(ty + x * math.sin(a) + y * math.cos(a), 3))


def image_box(rotation):
    xs, ys = zip(*(to_user(rotation, x, y) for x in IMAGE_BOX[0::2] for y in IMAGE_BOX[1::2]))
    return (min(xs), min(ys), max(xs), max(ys))


def base_pdf(png, rotation=0):
    buf = io.BytesIO()
    size, shift, degrees = TURNS[rotation]
    c = pdfcanvas.Canvas(buf, pagesize=size)
    c.translate(*shift)
    c.rotate(degrees)
    c.setFont("Helvetica", 14)
    c.drawString(72, 720, "NATIVEWORD native line of text")
    c.beginForm("nested")
    c.setFont("Helvetica", 18)
    c.drawString(72, 640, "FORMWORD confidential stamp")
    c.endForm()
    c.beginForm("stamp")
    c.doForm("nested")
    c.endForm()
    c.doForm("stamp")
    c.drawImage(ImageReader(io.BytesIO(png)), IMAGE_BOX[0], IMAGE_BOX[1],
                width=IMAGE_BOX[2] - IMAGE_BOX[0], height=IMAGE_BOX[3] - IMAGE_BOX[1])
    t = c.beginText(72, 200)
    t.setFont("Helvetica", 12)
    t.textOut("")
    c.drawText(t)
    c.showPage()
    c.save()
    return buf.getvalue()


def variant(data, name, folder):
    doc = pdfium.PdfDocument(data)
    page = doc[0]
    if name == "rotate90":
        page.set_rotation(90)
    elif name == "rotate180":
        page.set_rotation(180)
    elif name == "rotate270_crop":
        page.set_rotation(270)
        page.set_cropbox(60, 40, 760, 560)
    elif name == "crop":
        page.set_cropbox(50, 250, 560, 740)
    elif name == "mediabox_offset":
        page.set_mediabox(50, 50, 662, 842)
    path = os.path.join(folder, name + ".pdf")
    doc.save(path)
    return path


def main(folder):
    os.makedirs(folder, exist_ok=True)
    png = text_image()
    rotations = {"base": 0, "rotate90": 90, "rotate180": 180, "rotate270_crop": 270,
                 "crop": 0, "mediabox_offset": 0}
    for name, rotation in rotations.items():
        variant(base_pdf(png, rotation), name, folder)
    with open(os.path.join(folder, "expected.json"), "w") as handle:
        json.dump({"image_box": {name: image_box(r) for name, r in rotations.items()},
                   "image_words": ["imageword", "quokka", "zephyr", "straße"],
                   "native_words": ["nativeword", "formword"], "fixtures": list(rotations)}, handle)
    print("wrote", len(rotations), "fixtures to", folder)


if __name__ == "__main__":
    main(sys.argv[1])
