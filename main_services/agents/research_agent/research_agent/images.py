"""Images in tool results.

A tool that has an image adds the embedded resource `IMAGE_REFS_URI` to its MCP result.
The resource holds one reference for each image. A reference names the source and holds no
bytes.

| Field | Document image or video frame | `read_page` screenshot |
|---|---|---|
| `kind` | `document` | `capture` |
| identity | `collection`, `file_hash` | `artifact_id` |
| `label` | the file name, with `video: true` for a video frame | the page title and URL |
| `width`, `height` | the size of the image | the screenshot size |

`/tool_call` returns the references as `image_refs`. The worker stores them in the usage of
the tool message, and each step request sends them on the `RunMessage`. The content of the
message stays text, so a restart builds the same image input from the stored references.

**Request construction.** `load` reads the bytes from the agent routes `images/document`
and `images/capture` with the identity of the run. The website checks collection access or
capture ownership on every read. `prepare` decodes the bytes and limits the long side to
`MAX_SIDE` pixels and the encoded size to `MAX_BYTES`. It gives PNG, or JPEG when PNG is
too large. `parts_for` appends one label line and one `image_url` part for each image after
the text part of the tool message. An image that cannot be read gives a line with the
reason. A cached copy is sent only after the website answers `304` to a request that names
it. So a caller that lost access gets no cached image.

**A model that takes no images.** `supports_vision` reads `llm_models.supports_vision`.
For a model with 0, `hide` removes the references and adds `NO_VISION_TEXT` to the result.

**Cost.** `ref_tokens` estimates the tokens of one image from its area after the size
limit: `ceil(w / 32) * ceil(h / 32)` and `IMAGE_FRAME_TOKENS`. Request sizing, the
compaction trigger, the retained-history selection and the summary request use it.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import math
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

from research_agent.run_messages import RunMessage

log = logging.getLogger(__name__)

IMAGE_REFS_URI = "hoover4://image-refs"
#: The longest side of an image that a request sends, in pixels.
MAX_SIDE = 1568
#: The largest encoded image that a request sends.
MAX_BYTES = 256 * 1024
#: The side of the square that one image token covers, in pixels.
TOKEN_SIDE = 32
#: The tokens that the chat template adds around one image.
IMAGE_FRAME_TOKENS = 16
#: The prepared bytes that the cache keeps, over every run of this process.
CACHE_BYTES = 64 * 1024 * 1024
#: The (connect, read) timeout of one image request, in seconds.
REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=3.0)
#: How long a catalog value of `supports_vision` is used before it is read again.
VISION_TTL_SECONDS = 300

NO_VISION_TEXT = "Image not shown: the model of this chat takes no images."


class ImageError(ValueError):
    """An image that cannot be decoded. The message is the reason that the model reads."""


@dataclass(frozen=True)
class Loaded:
    """One prepared image as a data URL, or the reason why there is none."""

    data_url: str = ""
    reason: str = ""


# ------------------------------------------------------------------------ references


def image_refs_of(artifact: Any) -> Optional[List[Dict[str, Any]]]:
    """The image references of a tool message artifact, or `None` when it has none."""
    if not isinstance(artifact, list):
        return None
    for block in artifact:
        resource = getattr(block, "resource", None)
        if resource is None or str(getattr(resource, "uri", "")) != IMAGE_REFS_URI:
            continue
        try:
            value = json.loads(getattr(resource, "text", "") or "")
        except ValueError:
            return None
        refs = [ref for ref in value if isinstance(ref, dict)] if isinstance(value, list) else []
        return refs or None
    return None


def describe(ref: Dict[str, Any]) -> str:
    """The label of one image as the model and the summary read it."""
    label = str(ref.get("label") or "").strip()
    if ref.get("kind") == "capture":
        return f"read_page screenshot of {label or 'a page'}"
    if ref.get("video"):
        return f"first frame of the video document {label or ref.get('file_hash', '')}"
    return f"image document {label or ref.get('file_hash', '')}"


def ref_key(ref: Dict[str, Any]) -> Optional[Tuple[str, ...]]:
    """The source identity of one reference, or `None` when it names no source."""
    if ref.get("kind") == "capture" and ref.get("artifact_id"):
        return ("capture", str(ref["artifact_id"]))
    if ref.get("kind") == "document" and ref.get("collection") and ref.get("file_hash"):
        return ("document", str(ref["collection"]), str(ref["file_hash"]))
    return None


def ref_tokens(ref: Dict[str, Any]) -> int:
    """The estimated tokens of one image, from its area after the side limit. An image of
    unknown size counts as a square at the limit."""
    width, height = int(ref.get("width") or 0), int(ref.get("height") or 0)
    if width <= 0 or height <= 0:
        width = height = MAX_SIDE
    scale = min(1.0, MAX_SIDE / max(width, height))
    width, height = max(1, round(width * scale)), max(1, round(height * scale))
    return math.ceil(width / TOKEN_SIDE) * math.ceil(height / TOKEN_SIDE) + IMAGE_FRAME_TOKENS


def message_tokens(message: RunMessage) -> int:
    """The estimated tokens of the images of one message."""
    if message.role != "tool":
        return 0
    return sum(ref_tokens(ref) for ref in message.image_refs)


def list_tokens(messages: Sequence[RunMessage]) -> int:
    return sum(message_tokens(m) for m in messages)


def hide(messages: Sequence[RunMessage]) -> List[RunMessage]:
    """The messages for a model that takes no images: no references, and `NO_VISION_TEXT`
    after the text of each result that had images."""
    out = []
    for m in messages:
        if m.role == "tool" and m.image_refs:
            m = m.model_copy(update={"image_refs": [],
                                     "content": f"{m.content}\n\n{NO_VISION_TEXT}"})
        out.append(m)
    return out


# --------------------------------------------------------------------------- catalog

_vision_cache: Dict[str, Tuple[float, bool]] = {}


def supports_vision(model_id: str, *, now: Optional[float] = None) -> bool:
    """Whether the catalog marks the model `supports_vision`. A failed read gives False."""
    from research_agent import compaction

    model_id = (model_id or "").strip()
    if not model_id:
        return False
    clock = time.monotonic() if now is None else now
    cached = _vision_cache.get(model_id)
    if cached and cached[0] > clock:
        return cached[1]
    base = compaction._clickhouse_url()
    if not base:
        return False
    try:
        with httpx.Client(timeout=(2.0, 5.0), auth=compaction._auth()) as client:
            response = client.get(f"{base}/", params={
                "database": compaction.GLOBAL_DB,
                "query": ("SELECT max(supports_vision) FROM llm_models FINAL "
                          "WHERE model_id = {m:String} AND is_deleted = 0 FORMAT TSV"),
                "param_m": model_id,
            })
        value = response.status_code < 300 and (response.text or "0").strip() == "1"
    except Exception as exc:  # noqa: BLE001 - no images is a valid answer
        log.warning("could not read supports_vision for %s: %s", model_id, exc)
        return False
    _vision_cache[model_id] = (clock + VISION_TTL_SECONDS, value)
    return value


# ------------------------------------------------------------------------- preparing


def _encode(image: Any, fmt: str, **options: Any) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, fmt, **options)
    return buffer.getvalue()


def prepare(raw: bytes) -> Tuple[bytes, str]:
    """The bytes and the media type of one image within `MAX_SIDE` and `MAX_BYTES`.

    A JPEG source gives JPEG. Another raster format gives PNG, and JPEG when the PNG is
    larger than `MAX_BYTES`. A format that cannot be decoded raises `ImageError` with the
    reason. SVG needs the stored preview of the website, because Pillow does not rasterize
    it.
    """
    from PIL import Image, ImageOps

    try:
        image = Image.open(io.BytesIO(raw))
        source_format = image.format or ""
        image.load()
        image = ImageOps.exif_transpose(image)
    except Exception as exc:  # noqa: BLE001 - the reason goes to the model
        if b"<svg" in raw[:4096].lower():
            raise ImageError("the SVG image has no stored preview, and SVG is not decoded") from exc
        raise ImageError("the image format cannot be decoded") from exc
    alpha = image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info)
    image = image.convert("RGBA" if alpha else "RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    if source_format != "JPEG":
        data = _encode(image, "PNG", optimize=True)
        if len(data) <= MAX_BYTES:
            return data, "image/png"
    if alpha:
        flat = Image.new("RGB", image.size, (255, 255, 255))
        flat.paste(image, mask=image.getchannel("A"))
        image = flat
    while True:
        for quality in (85, 70, 55, 40):
            data = _encode(image, "JPEG", quality=quality, optimize=True)
            if len(data) <= MAX_BYTES:
                return data, "image/jpeg"
        if max(image.size) <= 64:
            raise ImageError("the image cannot be encoded within the size limit")
        image = image.resize((max(1, image.width * 3 // 4), max(1, image.height * 3 // 4)))


# --------------------------------------------------------------------------- loading


class _Cache:
    """Prepared data URLs by source identity, with the etag of the source, within
    `CACHE_BYTES`. The oldest entry goes first."""

    def __init__(self, limit: int):
        self.limit = limit
        self.entries: "OrderedDict[Tuple[str, ...], Tuple[str, str]]" = OrderedDict()
        self.size = 0
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            entry = self.entries.get(key)
            if entry is not None:
                self.entries.move_to_end(key)
            return entry

    def put(self, key, etag: str, data_url: str) -> None:
        with self.lock:
            old = self.entries.pop(key, None)
            if old is not None:
                self.size -= len(old[1])
            self.entries[key] = (etag, data_url)
            self.size += len(data_url)
            while self.size > self.limit and self.entries:
                _, (_, dropped) = self.entries.popitem(last=False)
                self.size -= len(dropped)


_cache = _Cache(CACHE_BYTES)


def _base_url() -> str:
    return (os.getenv("AGENT_API_BASE_URL") or "http://hoover4-website:8080").rstrip("/")


def _error_message(response: httpx.Response) -> str:
    try:
        return str(response.json().get("message") or response.text[:300])
    except ValueError:
        return response.text[:300] or f"status {response.status_code}"


def load(ref: Dict[str, Any], *, username: str, collections: Sequence[str],
         client: Optional[httpx.Client] = None) -> Loaded:
    """The prepared image of one reference, read with the identity of the run."""
    key = ref_key(ref)
    if key is None:
        return Loaded(reason="the image reference names no source")
    if key[0] == "capture":
        route, body = "images/capture", {"artifact_id": key[1]}
    else:
        route, body = "images/document", {"collectionname": key[1], "file_hash": key[2]}
    headers = {"x-hoover4-user": username, "X-Hoover4-Collections": ",".join(collections)}
    cached = _cache.get(key)
    if cached is not None:
        headers["If-None-Match"] = f'"{cached[0]}"'
    try:
        if client is not None:
            response = client.post(f"{_base_url()}/api/agent/v1/{route}", json=body, headers=headers)
        else:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as own:
                response = own.post(f"{_base_url()}/api/agent/v1/{route}", json=body, headers=headers)
    except httpx.HTTPError as exc:
        log.warning("could not read the image %s: %s", key, exc)
        return Loaded(reason=f"the image could not be read ({type(exc).__name__})")
    if response.status_code == 304 and cached is not None:
        return Loaded(data_url=cached[1])
    if response.status_code >= 300:
        return Loaded(reason=f"the image could not be read: {_error_message(response)}")
    try:
        data, media_type = prepare(response.content)
    except ImageError as exc:
        return Loaded(reason=str(exc))
    data_url = f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"
    etag = (response.headers.get("etag") or "").strip('"')
    if etag:
        _cache.put(key, etag, data_url)
    return Loaded(data_url=data_url)


def load_all(refs: Sequence[Dict[str, Any]], *, username: str,
             collections: Sequence[str]) -> List[Loaded]:
    """The prepared images of `refs`, in order, over one connection."""
    if not refs:
        return []
    with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        return [load(ref, username=username, collections=collections, client=client)
                for ref in refs]


def parts(text: str, refs: Sequence[Dict[str, Any]], loaded: Sequence[Loaded]) -> List[Dict[str, Any]]:
    """The content parts of one tool message: the text, then a label line and an image part
    for each image, or a line with the reason when the image could not be read."""
    out: List[Dict[str, Any]] = [{"type": "text", "text": text}]
    for ref, item in zip(refs, loaded):
        if item.data_url:
            out.append({"type": "text", "text": f"Image: {describe(ref)}"})
            out.append({"type": "image_url", "image_url": {"url": item.data_url}})
        else:
            out.append({"type": "text", "text": f"Image not attached: {describe(ref)}: {item.reason}"})
    return out


def parts_for(messages: Sequence[RunMessage], *, username: str,
              collections: Sequence[str]) -> Dict[int, List[Dict[str, Any]]]:
    """The content parts of each tool message with images, by its position in `messages`."""
    out: Dict[int, List[Dict[str, Any]]] = {}
    for index, m in enumerate(messages):
        if m.role != "tool" or not m.image_refs:
            continue
        loaded = load_all(m.image_refs, username=username, collections=collections)
        out[index] = parts(m.content, m.image_refs, loaded)
    return out


__all__ = [
    "CACHE_BYTES", "IMAGE_FRAME_TOKENS", "IMAGE_REFS_URI", "ImageError", "Loaded", "MAX_BYTES",
    "MAX_SIDE", "NO_VISION_TEXT", "describe", "hide", "image_refs_of", "list_tokens", "load",
    "load_all", "message_tokens", "parts", "parts_for", "prepare", "ref_key", "ref_tokens",
    "supports_vision",
]
