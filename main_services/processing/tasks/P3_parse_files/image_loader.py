"""Robust image decoding for OCR: OpenCV first, Pillow fallback.

Follow-up (plan 2, part 1 deferred a third decoder until a second undecodable
format showed up — several did). Observed in testdata_testfiles, decodable by
neither OpenCV nor Pillow and therefore currently skipped:
TIFF with "old JPEG" compression, OpenEXR, MNG, XWD, HEIF. `tifffile` (already
present transitively via scikit-image/imageio) covers the TIFF case and
`pillow-heif` the HEIF case; an ImageMagick subprocess would cover the rest.
"""

import logging
import os

log = logging.getLogger(__name__)

# Refuse to decode images with more pixels than this (decompression-bomb guard).
MAX_IMAGE_PIXELS = 200_000_000


def load_image_rgb(file_path: str):
    """Return an HxWx3 RGB uint8 array, or None if the image cannot be decoded.

    Order: cv2.imread (fast, handles the common cases) -> PIL.Image.open().convert("RGB")
    (handles TIFF compressions OpenCV's libtiff lacks, plus a wider format set).
    Never raises for a bad image; raises only for a missing/unreadable path.
    """
    import numpy as np
    import cv2

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"image path does not exist: {file_path}")

    # cv2.imread returns None for codecs it cannot decode, but *raises* cv2.error
    # for codecs compiled out entirely (e.g. OpenEXR). Both mean "try Pillow".
    try:
        img = cv2.imread(file_path, cv2.IMREAD_COLOR)
    except Exception as e:
        log.warning("cv2.imread failed for %s (%s)", file_path, type(e).__name__)
        img = None
    if img is not None:
        return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # OpenCV could not decode it (e.g. TIFF compression its libtiff lacks, or a
    # codec disabled at build time); fall back to Pillow, which supports a wider
    # set of codecs.
    try:
        from PIL import Image
        with Image.open(file_path) as pil_img:
            width, height = pil_img.size
            if width * height > MAX_IMAGE_PIXELS:
                log.warning(
                    "Refusing to decode %s: %dx%d exceeds %d pixels",
                    file_path, width, height, MAX_IMAGE_PIXELS,
                )
                return None
            return np.asarray(pil_img.convert("RGB"))
    except (FileNotFoundError, PermissionError):
        raise
    except Exception as e:
        log.warning("Could not decode image %s (%s)", file_path, type(e).__name__)
        return None
