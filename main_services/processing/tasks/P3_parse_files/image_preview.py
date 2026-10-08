"""JPEG previews of uncommon images and of video first frames, and their stage activity.

The browser and both OCR engines read JPEG, PNG, BMP and WebP. Every other image (SVG,
HEIC, TIFF, PSD and the rest that ImageMagick reads) gets one JPEG preview at its own
resolution. An SVG preview fits in `SVG_PREVIEW_PX` by `SVG_PREVIEW_PX`, because most SVG
files are logos and have no pixel size of their own. A video gets its first frame.

The preview goes to the collection bucket under `PREVIEW_KEY_PREFIX` and gets one row in
`image_previews`. The OCR stages read the preview in place of the original when the row
exists, and the website shows it in the Image source and as the video poster.

A preview that cannot be made is a skipped outcome and writes no Error row. The OCR
stages then read the original file, and they record their own failure.

Untrusted input reaches two converters, so each call runs in its own empty folder:

* `rsvg-convert` loads files that an SVG names only from the folder of the SVG and below.
  The SVG is copied alone into the folder, so it can reach nothing else.
* `magick` gets a policy file in the folder that refuses every path outside it, except
  the input file. Without it an SVG or MVG reference reads any image on the worker, for
  example a temporary copy that belongs to another collection.
"""

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import List, Optional, Tuple

from temporalio import activity

from tasks.heartbeat import with_heartbeat
from tasks.P3_parse_files.batch_runner import (
    BatchFile, BatchResult, StageBatchParams, run_batch, try_budget_seconds,
)
from tasks.task_timing import SkippedOutcome

log = logging.getLogger(__name__)

PREVIEW_KEY_PREFIX = "derived/image-preview/"
SVG_PREVIEW_PX = 480
JPEG_QUALITY = "90"

#: The first bytes of the formats that the browser and both OCR engines read unchanged.
_DIRECT_MAGIC: Tuple[bytes, ...] = (
    b"\xff\xd8\xff",            # JPEG
    b"\x89PNG\r\n\x1a\n",       # PNG
    b"BM",                      # BMP
)


def preview_kind(head: bytes, mime_types: List[str], routes: List[str]) -> str:
    """`video`, `svg`, `raster`, or an empty string when the file needs no preview."""
    if "video" in routes:
        return "video"
    if "image/svg+xml" in mime_types or b"<svg" in head[:4096]:
        return "svg"
    if head.startswith(_DIRECT_MAGIC) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
        return ""
    return "raster"


def _policy(work_dir: str, input_path: str) -> str:
    # The last matching rule decides. Base64 `data:` images inside an SVG reach the
    # path check as `image/<type>;base64,...`, and the run starts in `work_dir`, so such
    # a name cannot leave the folder.
    return (
        "<policymap>\n"
        '  <policy domain="path" rights="none" pattern="*"/>\n'
        f'  <policy domain="path" rights="read|write" pattern="{work_dir}/*"/>\n'
        f'  <policy domain="path" rights="read" pattern="{input_path}"/>\n'
        '  <policy domain="path" rights="read" pattern="image/*;base64,*"/>\n'
        "</policymap>\n"
    )


def _run(cmd: List[str], work_dir: str, timeout_seconds: int, env: Optional[dict] = None) -> None:
    res = subprocess.run(cmd, cwd=work_dir, capture_output=True, timeout=timeout_seconds,
                         env=env)
    if res.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {res.stderr[:300]!r}")


def _magick_to_jpeg(source: str, out_path: str, work_dir: str, timeout_seconds: int) -> None:
    with open(os.path.join(work_dir, "policy.xml"), "w") as handle:
        handle.write(_policy(work_dir, source))
    env = {**os.environ, "MAGICK_CONFIGURE_PATH": work_dir, "MAGICK_TEMPORARY_PATH": work_dir}
    # `[0]` is the first frame or page. A transparent area becomes white, because JPEG
    # has no alpha and the OCR engines read dark text on a light page.
    _run(["magick", f"{source}[0]", "-auto-orient", "-background", "white",
          "-alpha", "remove", "-alpha", "off", "-quality", JPEG_QUALITY,
          f"jpg:{out_path}"], work_dir, timeout_seconds, env)


def make_preview_file(file_path: str, kind: str, work_dir: str, timeout_seconds: int) -> str:
    """Write the JPEG preview of `file_path` in `work_dir` and return its path."""
    out_path = os.path.join(work_dir, "preview.jpg")
    if kind == "video":
        _run(["ffmpeg", "-nostdin", "-v", "error", "-i", file_path, "-frames:v", "1",
              "-an", "-q:v", "2", "-y", out_path], work_dir, timeout_seconds)
    elif kind == "svg":
        svg_path = os.path.join(work_dir, "source.svg")
        shutil.copyfile(file_path, svg_path)
        png_path = os.path.join(work_dir, "rendered.png")
        _run(["rsvg-convert", "--keep-aspect-ratio", "-w", str(SVG_PREVIEW_PX),
              "-h", str(SVG_PREVIEW_PX), "-b", "white", "-f", "png", "-o", png_path,
              svg_path], work_dir, timeout_seconds)
        _magick_to_jpeg(png_path, out_path, work_dir, timeout_seconds)
    else:
        _magick_to_jpeg(file_path, out_path, work_dir, timeout_seconds)
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError("the converter wrote no preview")
    return out_path


def preview_key(file_hash: str) -> str:
    return f"{PREVIEW_KEY_PREFIX}{file_hash}.jpg"


def split_s3_path(s3_path: str) -> Tuple[str, str]:
    """`(bucket, key)` of a stored preview path, or empty strings for any other path."""
    if not isinstance(s3_path, str) or not s3_path.startswith("s3://"):
        return "", ""
    bucket, _, key = s3_path[len("s3://"):].partition("/")
    if not bucket or not key.startswith(PREVIEW_KEY_PREFIX):
        return "", ""
    return bucket, key


def read_preview_bytes(client, collection_dataset: str,
                       file_hash: str) -> Optional[bytes]:
    """The stored preview of one document, or `None` when it has no preview row."""
    from database.s3 import get_s3_client

    rows = client.query(
        "SELECT argMax(s3_path, updated_at) FROM image_previews "
        "WHERE collection_dataset = {cd:String} AND hash = {h:String} "
        "GROUP BY collection_dataset, hash",
        parameters={"cd": collection_dataset, "h": file_hash},
    ).result_rows
    bucket, key = split_s3_path(rows[0][0] if rows and rows[0] else "")
    if not bucket:
        return None
    response = get_s3_client().get_object(bucket, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


@dataclass
class ImagePreviewParams:
    collectionname: str
    collection_dataset: str
    file_hash: str
    file_path: str
    mime_types: List[str]
    routes: List[str]
    timeout_seconds: int


def make_image_preview(params: ImagePreviewParams) -> str | SkippedOutcome:
    import pyarrow as pa
    from PIL import Image, UnidentifiedImageError

    from database.clickhouse import get_collection_client, insert_parser_arrow
    from database.s3 import collection_bucket, get_s3_client

    with open(params.file_path, "rb") as handle:
        head = handle.read(4096)
    kind = preview_kind(head, params.mime_types, params.routes)
    if not kind:
        return SkippedOutcome("preview_not_needed")

    with get_collection_client(params.collectionname) as client:
        existing = client.query(
            "SELECT count() FROM image_previews "
            "WHERE collection_dataset = {cd:String} AND hash = {h:String}",
            parameters={"cd": params.collection_dataset, "h": params.file_hash},
        ).result_rows
        if existing and int(existing[0][0]) > 0:
            return SkippedOutcome("preview_exists")

    with tempfile.TemporaryDirectory(prefix="hoover4-preview-") as work_dir:
        try:
            out_path = make_preview_file(params.file_path, kind, work_dir,
                                         params.timeout_seconds)
            with Image.open(out_path) as img:
                width, height = img.size
        # A missing converter binary raises `FileNotFoundError` and fails the step, so
        # an image without the binary does not read as a file without a preview.
        except (RuntimeError, subprocess.TimeoutExpired, UnidentifiedImageError) as exc:
            log.info("[P3] no %s preview for %s: %s", kind, params.file_hash, exc)
            return SkippedOutcome(f"preview_failed_{kind}")
        size_bytes = os.path.getsize(out_path)
        bucket = collection_bucket(params.collectionname)
        key = preview_key(params.file_hash)
        get_s3_client().fput_object(bucket, key, out_path, content_type="image/jpeg")

    made_from = "video_frame" if kind == "video" else kind
    with get_collection_client(params.collectionname) as client:
        insert_parser_arrow(client, "image_previews", pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "hash": pa.array([params.file_hash], type=pa.string()),
            "s3_path": pa.array([f"s3://{bucket}/{key}"], type=pa.string()),
            "width": pa.array([int(width)], type=pa.uint32()),
            "height": pa.array([int(height)], type=pa.uint32()),
            "size_bytes": pa.array([int(size_bytes)], type=pa.uint64()),
            "made_from": pa.array([made_from], type=pa.string()),
        }))
    return f"preview_{made_from}"


@activity.defn
@with_heartbeat
def make_image_preview_batch(params: StageBatchParams) -> BatchResult:
    """The preview of each image or video of a group, one `make_image_preview` call a file."""
    def step(file: BatchFile) -> str | SkippedOutcome:
        return make_image_preview(ImagePreviewParams(
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
            file_hash=file.item_hash,
            file_path=file.file_path,
            mime_types=list(file.mime_types),
            routes=list(file.routes),
            timeout_seconds=try_budget_seconds("make_image_preview_batch", file.file_size_bytes),
        ))

    return run_batch("make_image_preview_batch", params.files, key=lambda f: f.item_hash,
                     size=lambda f: f.file_size_bytes, step=step,
                     task_name="make_image_preview")
