"""The image-size gate in front of OCR.

An icon, a bullet or a rule carries no text, and a corpus of PDFs is mostly those. The
gate reads the image header rather than decoding, so it costs a few hundred bytes.
"""

import io

import pytest

from tasks.P3_parse_files.image_loader import image_dimensions
from tasks.text_sources import MIN_OCR_IMAGE_PX


def _png(width: int, height: int) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("width,height,gated", [
    (16, 16, True),
    (MIN_OCR_IMAGE_PX - 1, 400, True),
    (400, MIN_OCR_IMAGE_PX - 1, True),
    (MIN_OCR_IMAGE_PX, MIN_OCR_IMAGE_PX, False),
    (1024, 768, False),
])
def test_the_gate_uses_the_shorter_edge(width, height, gated):
    size = image_dimensions(_png(width, height))
    assert size == (width, height)
    assert (min(size) < MIN_OCR_IMAGE_PX) is gated


def test_an_unreadable_header_is_not_gated():
    """A format Pillow cannot open still goes to the engines, which read more of them.

    Skipping on "cannot read the header" would silently drop whole formats from OCR;
    `ocr_skipped_unreadable` is what this reports when neither side can read the file.
    """
    assert image_dimensions(b"not an image at all") is None
