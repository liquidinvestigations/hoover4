"""Result pages: the token-counted, self-describing envelope every new data tool returns.

A page is built once (:func:`build_page`), carried through the agent and the transcript as
plain text, and never parsed and re-serialized on the way. **The byte rule** is the reason
this module exists: the UTF-8 byte string this module serializes is the byte string the
transcript stores. A page is recognised with no side channel, by a fixed-point test
(:func:`is_canonical_page`): canonical JSON is idempotent under its own serialization, so a
text is a page when it parses to an object whose `kind` is `result_page` and re-serializing
that object, sorted and compact, reproduces the text byte for byte. Anything that
reformatted, reordered, escaped or re-parsed the page fails that test.

The caller supplies a source position after each possible returned prefix. A continuation
uses the position after the units in its page.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Literal

#: The `kind` value that marks an envelope as a result page.
KIND_RESULT_PAGE = "result_page"

#: A dead tokenizer endpoint fails within the connection timeout. A slow response fails
#: within the total timeout.
CONNECT_TIMEOUT = float(os.getenv("AGENT_TOKENIZER_CONNECT_TIMEOUT", "30"))
TOTAL_TIMEOUT = float(os.getenv("AGENT_TOKENIZER_TOTAL_TIMEOUT", "60"))

#: The safe-mode aggregate, in UTF-8 bytes, for one parallel batch of results. Used until
#: the probe confirms a token configuration, and whenever token counting fails. Equals the
#: storage cut in `website/common/src/chat_types.rs::TOOL_PAYLOAD_CHARS`.
SAFE_MODE_BATCH_BYTES = 24_000


# --------------------------------------------------------------------------------------
# Canonical JSON and the fixed-point test
# --------------------------------------------------------------------------------------


def canonical_json(value: object) -> str:
    """The one serialization every writer and reader of a page must agree on.

    Sorted keys, compact separators, non-ASCII characters left unescaped. Two documents
    with the same content in a different key order or spacing are different byte strings
    everywhere else in this codebase; here they must be the same one, because the digest
    and the fixed-point test both depend on there being exactly one canonical form.
    """
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_page_bytes(value: object) -> bytes:
    """The UTF-8 bytes of `value`'s canonical form. What the broker serializes and what
    the digest is computed over."""
    return canonical_json(value).encode("utf-8")


def page_digest(data: bytes) -> str:
    """SHA-256 hex digest of already-serialized page bytes. Never computed over anything
    the page itself carries: a value that describes the bytes cannot also be inside them."""
    return hashlib.sha256(data).hexdigest()


def is_canonical_page(text: str) -> bool:
    """True when `text` is a broker page: a `result_page` object whose canonical
    re-serialization is `text` itself, byte for byte.

    This is the fixed-point test the byte rule relies on: canonical JSON is idempotent
    under `canonical_json`, so anything that reformatted, reordered, escaped or re-parsed
    the page on its way through the transcript fails this test, which is what makes the
    test also the detector.
    """
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return False
    if not isinstance(value, dict) or value.get("kind") != KIND_RESULT_PAGE:
        return False
    return canonical_json(value) == text


# --------------------------------------------------------------------------------------
# Continuation
# --------------------------------------------------------------------------------------

#: The `v` field of every encoded continuation. A future incompatible shape bumps this
#: rather than reusing the number, so a stale client's token fails to decode instead of
#: decoding into the wrong fields.
CONTINUATION_VERSION = 1


class ContinuationInvalid(ValueError):
    """A continuation token did not decode, or did not decode to a v1 payload."""


def encode_continuation(
    tool: str,
    input: dict,
    position: dict,
    source: str,
    raw_artifact_id: str | None = None,
) -> str:
    """Base64url of the canonical JSON `{"v":1,"tool":...,"input":...,"position":...,
    "source":...}`.

    `raw_artifact_id` is accepted for symmetry with `PageInput`, but it never enters the
    encoded bytes as its own field. A position inside a stored window names its artifact
    in `position`, and `artifacts.read_range` checks the caller's ownership on each read,
    so an edited continuation cannot read another user's artifact.
    """
    del raw_artifact_id  # documented above: the position carries it.
    payload = {
        "v": CONTINUATION_VERSION,
        "tool": tool,
        "input": input,
        "position": position,
        "source": source,
    }
    data = canonical_page_bytes(payload)
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def decode_continuation(token: str) -> dict:
    """The inverse of :func:`encode_continuation`. Raises :class:`ContinuationInvalid`
    for anything that is not a base64url-encoded v1 payload with every required field."""
    try:
        padded = token + "=" * (-len(token) % 4)
        data = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(data.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - any decode failure is one refusal
        raise ContinuationInvalid(f"malformed continuation token: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContinuationInvalid("continuation token is not a JSON object")
    if payload.get("v") != CONTINUATION_VERSION:
        raise ContinuationInvalid(f"continuation token is not a v{CONTINUATION_VERSION} payload")
    missing = [key for key in ("tool", "input", "position", "source") if key not in payload]
    if missing:
        raise ContinuationInvalid(f"continuation token missing {missing}")
    return {
        "tool": payload["tool"],
        "input": payload["input"],
        "position": payload["position"],
        "source": payload["source"],
    }


# --------------------------------------------------------------------------------------
# Token counting
# --------------------------------------------------------------------------------------


class TokenCountFailed(RuntimeError):
    """The tokenizer endpoint could not be reached, or its answer did not check out."""


def _tokenize_url(base_url: str) -> str:
    """`{base without /v1}/tokenize`. The served base URL is an OpenAI-compatible
    `.../v1` path; the tokenizer route sits beside it, not under it."""
    base = (base_url or "").rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return f"{base}/tokenize"


class TokenCounter:
    """Counts tokens the served model would actually see, over `POST .../tokenize`.

    Never falls back to a character estimate: a wrong count either wastes budget or
    overfills a request, and a failure states that plainly instead of guessing. A failure
    raises, and the caller uses :class:`ByteLimit` (safe mode) instead.
    """

    def __init__(self, base_url: str, model: str, api_key: str | None = None) -> None:
        self._url = _tokenize_url(base_url)
        self._model = model
        self._api_key = api_key

    def count(self, text: str) -> int:
        import requests

        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        try:
            response = requests.post(
                self._url,
                json={"model": self._model, "prompt": text, "add_special_tokens": False},
                headers=headers,
                timeout=(CONNECT_TIMEOUT, TOTAL_TIMEOUT),
            )
        except Exception as exc:  # noqa: BLE001 - connect, read, and transport failures alike
            raise TokenCountFailed(f"tokenizer request failed: {exc}") from exc
        if response.status_code != 200:
            raise TokenCountFailed(
                f"tokenizer returned {response.status_code}: {response.text[:200]}"
            )
        try:
            body = response.json()
            count = int(body["count"])
            tokens = body["tokens"]
        except (ValueError, KeyError, TypeError) as exc:
            raise TokenCountFailed(f"tokenizer response malformed: {exc}") from exc
        if count != len(tokens):
            raise TokenCountFailed(
                f"tokenizer count {count} disagrees with len(tokens)={len(tokens)}"
            )
        return count


# --------------------------------------------------------------------------------------
# Allocation
# --------------------------------------------------------------------------------------


def allocate(
    fixed_request_tokens: int,
    empty_message_tokens: list[int],
    threshold: int,
    completion_reserve: int,
    max_page_tokens: int | None,
) -> list[int] | None:
    """One content token limit per parallel result, or `None` when even the empty
    messages plus the completion reserve do not fit.

    `threshold` is `H`, the compaction trigger (`floor(context_window *
    compaction_fraction)`). `completion_reserve` is `R`. `fixed_request_tokens` is
    `max(U, P)`: the larger of the previous call's billed prompt-plus-completion count and
    the tokenizer count of the next request before the pending results. `A = H - R` is the
    allocation ceiling, one reserve below the threshold, so a full allocation evicts
    nothing on the next call (compaction fires at `H`, not at `A`). Reserving `R` a second
    time inside the ceiling keeps the total request, once every result is filled, `R`
    tokens below `H` rather than exactly at it.

    Every one of the `K` empty (zero-content) messages is reserved before any page
    receives content: `fixed = fixed_request_tokens + sum(empty_message_tokens)`. `None`
    means the caller stores the `K` empty messages, makes no further model call, and ends
    the turn.
    """
    k = len(empty_message_tokens)
    if k == 0:
        return []
    ceiling = threshold - completion_reserve  # A
    fixed = fixed_request_tokens + sum(empty_message_tokens)
    if fixed + completion_reserve > ceiling:
        return None
    content_available = max(0, ceiling - completion_reserve - fixed)
    share = content_available // k
    if max_page_tokens is not None:
        share = min(share, max_page_tokens)
    return [share] * k


# --------------------------------------------------------------------------------------
# Page limits
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenLimit:
    """Size a page against a model-token budget, measured with `counter`."""

    max_tokens: int
    counter: TokenCounter


@dataclass(frozen=True)
class ByteLimit:
    """Size a page against a raw UTF-8 byte budget. Safe mode, and every fallback from a
    failed token count."""

    max_bytes: int


PageLimit = TokenLimit | ByteLimit


def _limit_value(limit: PageLimit) -> int:
    return limit.max_tokens if isinstance(limit, TokenLimit) else limit.max_bytes


def _measure(data: bytes, limit: PageLimit) -> int:
    if isinstance(limit, TokenLimit):
        return limit.counter.count(data.decode("utf-8"))
    return len(data)


# --------------------------------------------------------------------------------------
# Page input and measure
# --------------------------------------------------------------------------------------

PageShape = Literal["rows", "table", "tree", "blob"]


@dataclass(frozen=True)
class PageInput:
    """What one tool call has to page. `items` is the complete result the tool backend
    produced (whatever the broker did not already store as a raw artifact), and
    `build_page` fits as much of it as the budget allows.

    `position_after(n)` returns the source position after the first `n` items.
    For a blob, `n` counts UTF-8 bytes. It returns None at the source end.
    The backend must map each returned prefix to a stable source position.
    """

    tool_name: str
    shape: PageShape
    items: list  # rows, table rows, tree nodes, or [one string] for a blob
    columns: list | None  # table shape only, emitted once
    total_units: int
    position_start: dict  # where this read began in the source
    source: str  # fingerprint from the backend route
    input: dict  # the validated tool input, for the continuation
    raw_artifact_id: str | None
    position_after: Callable[[int], dict | None]  # None means the source is exhausted
    fields: dict[str, Any] | None = None  # response fields outside the paged units


@dataclass(frozen=True)
class PageMeasure:
    """What the broker records in its call measure, beside `page_sha256`."""

    page_bytes: int
    page_sha256: str
    page_tokens: int | None  # None when the page was sized with a ByteLimit
    returned_units: int
    total_units: int
    truncated: bool
    status: Literal["ok", "budget_exhausted"]


STATUS_OK = "ok"
STATUS_BUDGET_EXHAUSTED = "budget_exhausted"


def _envelope(
    tool_name: str,
    shape: PageShape,
    items: list,
    columns: list | None,
    returned_units: int,
    total_units: int,
    raw_artifact_id: str | None,
    continuation: str | None,
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "success": True,
        "kind": KIND_RESULT_PAGE,
        "tool_name": tool_name,
        "shape": shape,
        "items": items,
        "returned_units": returned_units,
        "total_units": total_units,
        "raw_artifact_id": raw_artifact_id,
        "continuation": continuation,
    }
    if shape == "table" and columns is not None:
        envelope["columns"] = columns
    if fields:
        envelope["fields"] = fields
    return envelope


def _budget_exhausted_envelope(
    tool_name: str, shape: PageShape, total_units: int, raw_artifact_id: str | None
) -> dict[str, Any]:
    """The smallest zero-content message: `success=false`, zero returned units, the raw
    artifact id when one exists, and no continuation, because nothing was read to resume
    from."""
    return {
        "success": False,
        "kind": KIND_RESULT_PAGE,
        "tool_name": tool_name,
        "shape": shape,
        "status": STATUS_BUDGET_EXHAUSTED,
        "items": [],
        "returned_units": 0,
        "total_units": total_units,
        "raw_artifact_id": raw_artifact_id,
        "continuation": None,
    }


def _finish(
    envelope: dict[str, Any],
    limit: PageLimit,
    returned_units: int,
    total_units: int,
    status: Literal["ok", "budget_exhausted"],
) -> tuple[str, PageMeasure]:
    data = canonical_page_bytes(envelope)
    text = data.decode("utf-8")
    measure = PageMeasure(
        page_bytes=len(data),
        page_sha256=page_digest(data),
        page_tokens=(limit.counter.count(text) if isinstance(limit, TokenLimit) else None),
        returned_units=returned_units,
        total_units=total_units,
        truncated=status == STATUS_BUDGET_EXHAUSTED or envelope["continuation"] is not None,
        status=status,
    )
    return text, measure


def _utf8_boundary(data: bytes, index: int) -> int:
    """The largest `n <= index` such that `data[:n]` ends on a UTF-8 character boundary."""
    n = max(0, min(index, len(data)))
    while 0 < n < len(data) and (data[n] & 0xC0) == 0x80:
        n -= 1
    return n


def _continuation(p: PageInput, returned_units: int) -> str | None:
    """Encode the source position after the returned prefix."""
    position = p.position_after(returned_units)
    if position is None:
        return None
    if not isinstance(position, dict) or position == p.position_start:
        raise ValueError("a continuation must advance the source position")
    return encode_continuation(p.tool_name, p.input, position, p.source)


def _build_units(p: PageInput, limit: PageLimit, max_allowed: int) -> tuple[list, int]:
    """The row, table and tree adapters: whole units, dropped from the end until the page
    fits. Dropping from the end rather than anywhere else is what keeps a tree adapter from
    ever emitting an orphan, given items ordered parent-before-child: a kept child's index
    is always past its parent's, so a kept prefix never excludes a kept child's parent."""
    columns = p.columns if p.shape == "table" else None
    items_full = list(p.items)

    items = items_full
    while items:
        continuation = _continuation(p, len(items))
        envelope = _envelope(
            p.tool_name, p.shape, items, columns, len(items), p.total_units,
            p.raw_artifact_id, continuation, p.fields,
        )
        if _measure(canonical_page_bytes(envelope), limit) <= max_allowed:
            return items, len(items)
        items = items[:-1]
    return items, 0


def _build_blob(p: PageInput, limit: PageLimit, max_allowed: int) -> tuple[str, int]:
    """The blob adapter: a byte-budget cut of the one string in `items`, aligned to a
    UTF-8 character boundary so a multi-byte character is never split."""
    full_text = p.items[0] if p.items else ""
    full_bytes = full_text.encode("utf-8")
    total_bytes = p.total_units

    lo, hi = 0, len(full_bytes)
    best_text, best_len = "", 0
    while lo <= hi:
        mid = (lo + hi) // 2
        cut = _utf8_boundary(full_bytes, mid)
        candidate = full_bytes[:cut].decode("utf-8")
        continuation = _continuation(p, cut) if cut else None
        envelope = _envelope(
            p.tool_name, "blob", [candidate], None, cut, total_bytes,
            p.raw_artifact_id, continuation, p.fields,
        )
        if _measure(canonical_page_bytes(envelope), limit) <= max_allowed:
            best_text, best_len = candidate, cut
            lo = mid + 1
        else:
            hi = mid - 1
    return best_text, best_len


def build_page(p: PageInput, limit: PageLimit) -> tuple[str, PageMeasure]:
    """Build the canonical page text and its measure record.

    Serializes, counts and removes whole units (or, for a blob, cuts at a UTF-8 boundary)
    until the page fits `limit`. When not even one unit fits, returns the zero-content
    `budget_exhausted` envelope instead of an empty-but-successful page.
    """
    max_allowed = _limit_value(limit)

    if p.shape == "blob":
        text, returned_units = _build_blob(p, limit, max_allowed)
        items: list = [text]
    else:
        items, returned_units = _build_units(p, limit, max_allowed)

    if returned_units <= 0 and p.total_units > 0:
        envelope = _budget_exhausted_envelope(p.tool_name, p.shape, p.total_units, p.raw_artifact_id)
        return _finish(envelope, limit, 0, p.total_units, STATUS_BUDGET_EXHAUSTED)

    continuation = _continuation(p, returned_units) if returned_units else None
    columns = p.columns if p.shape == "table" else None
    envelope = _envelope(
        p.tool_name, p.shape, items, columns, returned_units, p.total_units,
        p.raw_artifact_id, continuation, p.fields,
    )
    return _finish(envelope, limit, returned_units, p.total_units, STATUS_OK)


# --------------------------------------------------------------------------------------
# Unit cut
# --------------------------------------------------------------------------------------

#: The key of the marker on a unit that the broker cut inside one string field.
CUT_KEY = "cut"


def _pointer_token(key: object) -> str:
    return str(key).replace("~", "~0").replace("/", "~1")


def largest_string_field(unit: object, pointer: str = "") -> tuple[str, str] | None:
    """The JSON pointer and the value of the longest string inside `unit`, by UTF-8 bytes.

    The marker of an earlier cut is not a candidate. `None` means that the unit holds no
    string.
    """
    best: tuple[str, str] | None = None
    if isinstance(unit, str):
        return pointer, unit
    if isinstance(unit, dict):
        children = [(key, value) for key, value in unit.items() if not (pointer == "" and key == CUT_KEY)]
    elif isinstance(unit, list):
        children = list(enumerate(unit))
    else:
        return None
    for key, value in children:
        found = largest_string_field(value, f"{pointer}/{_pointer_token(key)}")
        if found is not None and (best is None or len(found[1].encode("utf-8")) > len(best[1].encode("utf-8"))):
            best = found
    return best


def replace_at_pointer(unit: object, pointer: str, value: object) -> object:
    """A copy of `unit` with the value at the JSON `pointer` replaced."""
    if pointer == "":
        return value
    head, _, rest = pointer[1:].partition("/")
    key = head.replace("~1", "/").replace("~0", "~")
    rest_pointer = "/" + rest if rest else ""
    if isinstance(unit, list):
        index = int(key)
        return [replace_at_pointer(item, rest_pointer, value) if i == index else item for i, item in enumerate(unit)]
    if isinstance(unit, dict):
        return {k: (replace_at_pointer(v, rest_pointer, value) if k == key else v) for k, v in unit.items()}
    raise ValueError(f"pointer {pointer} does not name a field")


def cut_unit(unit: dict, pointer: str, kept: bytes, total_bytes: int) -> dict:
    """The unit with the field at `pointer` cut to `kept`, which ends on a UTF-8 boundary,
    and the marker `{"cut": {"field", "returned_bytes", "total_bytes"}}` beside it."""
    cut = replace_at_pointer(unit, pointer, kept.decode("utf-8"))
    return {**cut, CUT_KEY: {"field": pointer, "returned_bytes": len(kept), "total_bytes": total_bytes}}


def utf8_prefix(data: bytes, limit: int) -> bytes:
    """The longest prefix of `data` of at most `limit` bytes that ends on a character
    boundary. `data` may itself end inside a character, as a byte range read does."""
    return data[:limit].decode("utf-8", errors="ignore").encode("utf-8")
