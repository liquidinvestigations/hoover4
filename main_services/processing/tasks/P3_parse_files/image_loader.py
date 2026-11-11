"""Image decoding for OCR: OpenCV first, Pillow fallback.

A third decoder is not wired up. Observed in testdata_testfiles, decodable by
neither OpenCV nor Pillow and therefore skipped:
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


def _header_size(source):
    try:
        from PIL import Image

        with Image.open(source) as img:
            width, height = img.size
        return int(width), int(height)
    except Exception:
        return None


def _sandboxed_sizes(args: list[str], data: bytes | None = None):
    """Run :func:`main` in the parser sandbox. Pillow is native code that reads an untrusted header."""
    import json
    import subprocess
    import sys

    from tasks import sandbox

    count = max(len(args), 1)
    try:
        out = sandbox.run([sys.executable, "-m", "tasks.P3_parse_files.image_loader", *args],
                          input=data if data is not None else b"", capture_output=True,
                          cwd="/app", timeout=60 + len(args))
    except subprocess.TimeoutExpired:
        log.warning("image header reader timed out for %d images", count)
        return [None] * count
    try:
        sizes = json.loads(out.stdout) if out.returncode == 0 else None
    except ValueError:
        sizes = None
    if not isinstance(sizes, list) or len(sizes) != count:
        log.warning("image header reader failed (%s): %s", out.returncode,
                    out.stderr[-300:].decode(errors="replace"))
        return [None] * count
    return [tuple(size) if size else None for size in sizes]


def image_dimensions(data: bytes):
    """`(width, height)` from an image's header alone, or `None` if it cannot be read.

    Header only: Pillow's `open` is lazy, so this costs a few hundred bytes rather than a
    full decode. That is the point. It is the gate in front of OCR, and a gate that has
    to decode the image to decide is not a saving. With the parser sandbox on
    (tasks/sandbox.py), a sandboxed child process reads the header.
    """
    import io

    from tasks import sandbox

    if sandbox.enabled():
        return _sandboxed_sizes(["-"], data)[0]
    return _header_size(io.BytesIO(data))


def image_sizes(paths: list[str]):
    """:func:`image_dimensions` for image files, with one sandboxed child process for all of them."""
    from tasks import sandbox

    if not paths:
        return []
    if sandbox.enabled():
        return _sandboxed_sizes([str(p) for p in paths])
    return [_header_size(p) for p in paths]


def main() -> None:
    """The child of the sandbox: print the sizes of the argument files, or of stdin for ``-``, as JSON."""
    import io
    import json
    import sys

    sizes = [_header_size(io.BytesIO(sys.stdin.buffer.read())) if arg == "-" else _header_size(arg)
             for arg in sys.argv[1:]]
    print(json.dumps(sizes))


if __name__ == "__main__":
    main()
