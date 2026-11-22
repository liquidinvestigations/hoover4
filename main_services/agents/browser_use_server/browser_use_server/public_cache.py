"""Reuse eligible public reader captures within seven days of their origin fetch."""

from __future__ import annotations

import asyncio
import base64
import re
import hashlib
import json
import logging
import os
import time
import uuid
from urllib.parse import parse_qsl, unquote, urlsplit

from agent_common import artifacts, s3_store

log = logging.getLogger(__name__)
PREFIX = "derived/public-page-cache/"
TTL = 168 * 3600
LEASE = 180
MAX_BYTES = 64 * 1024 * 1024

PUBLISH = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('SET', KEYS[2], ARGV[2], 'PX', ARGV[3])
  redis.call('DEL', KEYS[1])
  return 1
end
return 0
"""
RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


_PUBLIC_PARAMETERS = frozenset({
    "a", "b", "q", "query", "s", "search", "lang", "language", "locale", "page", "paged",
    "offset", "limit", "sort", "order", "format", "year", "month", "date", "p", "id", "v",
    "category", "tag", "type", "view", "name", "slug", "ref", "print",
    "utm_campaign", "utm_content", "utm_medium", "utm_source", "utm_term",
})
_PRIVATE_SEGMENT = re.compile(r"(?:^|/)(?:account|admin|auth|login|logout|oauth|session|token|sign-in)(?:/|$)", re.I)
_OPAQUE_VALUE = re.compile(r"^[A-Fa-f0-9]{32,}$|^(?=.*[A-Z])(?=.*[a-z])(?=.*[0-9])[A-Za-z0-9_~+.=-]{32,}$")


def candidate(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.fragment or len(url) > 4096
                or _PRIVATE_SEGMENT.search(unquote(parsed.path))):
            return False
        pairs = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=20, errors="strict")
        return all(
            key.casefold() in _PUBLIC_PARAMETERS
            and len(value) <= 160 and "@" not in value and not _OPAQUE_VALUE.fullmatch(value)
            for key, value in pairs
        ) and not any(_OPAQUE_VALUE.fullmatch(part) for part in unquote(parsed.path).split("/"))
    except (ValueError, UnicodeError):
        return False


def key_for(url, links, page_start):
    # The PDF body supports all of its page windows. HTML has no PDF page selection.
    key = json.dumps([2, url, links])
    return "hoover4:public-page:" + hashlib.sha256(key.encode()).hexdigest()


def eligible(page, requested):
    chain = page.public_chain or (requested, page.final_url)
    lifetime = page.public_lifetime if page.public_lifetime is not None else (TTL if page.public_response else 0)
    return (candidate(requested) and all(candidate(url) for url in chain)
            and page.route == "direct" and page.status == 200 and lifetime > 0
            and not page.challenge_signal and not page.error and not page.blocked and bool(page.full_text))


def prepare(page, fetched, lifetime):
    def encode(value):
        return base64.b64encode(value).decode() if value else None

    return json.dumps({
        "url": page.url, "final_url": page.final_url, "title": page.title,
        "full_text": page.full_text, "extent": page.extent, "expires": fetched + lifetime,
        "chain": page.public_chain or (page.url, page.final_url), "page_start": page.page_start,
        "pdf": encode(page.pdf_data), "html": encode(page.shared_body), "thumb": encode(page.shared_thumb),
    }, ensure_ascii=False).encode("utf-8")


async def prepare_hit(captured, url, page_start, check):
    from browser_use_server.read_page import PageRead, pdf_text

    if captured["expires"] <= time.time() or captured["url"] != url:
        return None
    chain = captured["chain"]
    if not chain or chain[-1] != captured["final_url"] or any(not candidate(hop) for hop in chain):
        return None
    if check is not None:
        for hop in dict.fromkeys([url, *chain]):
            await asyncio.to_thread(check, hop)
    page = PageRead(url=url, final_url=captured["final_url"], title=captured["title"],
                    full_text=captured["full_text"], extent=captured["extent"], page_start=page_start)
    def decode(key):
        return base64.b64decode(captured[key], validate=True) if captured.get(key) else None

    page.public_chain = tuple(chain)
    page.shared_body, page.shared_thumb = decode("html"), decode("thumb")
    page.pdf_data = decode("pdf")
    if page.extent and page_start != captured["page_start"]:
        raw = page.pdf_data
        if not raw:
            return None
        page.title, page.full_text, page.error, page.extent = await asyncio.to_thread(pdf_text, raw, page_start)
    page.status = 200
    return page


def copy_representation(page, owner, session):
    """Write a receiving chat's own copy of the archived page and screenshot."""
    if page.artifact or not (page.shared_body or page.shared_thumb):
        return
    from browser_use_server import capture

    status = artifacts.STATUS_OK if page.shared_body else artifacts.STATUS_TOO_LARGE
    detail = "" if page.shared_body else "The saved capture has no archived page."
    artifact_id = artifacts.write(artifacts.ArtifactRequest(
        username=owner, session_id=session, kind=artifacts.KIND_PAGE_CAPTURE,
        tool_name="read_page", url=page.final_url, title=page.title,
        body=("page.html", page.shared_body, "text/html; charset=utf-8") if page.shared_body else None,
        thumb=("thumb.webp", page.shared_thumb, "image/webp") if page.shared_thumb else None,
        status=status, detail=detail,
    ))
    if not artifact_id:
        return
    page.artifact = {"artifact_id": artifact_id, "kind": artifacts.KIND_PAGE_CAPTURE,
                     "status": status, "title": page.title, "url": page.final_url, **({"detail": detail} if detail else {})}
    if page.shared_thumb:
        page.image = {"kind": "capture", "artifact_id": artifact_id, "label": page.title or page.final_url,
                      "width": capture.THUMB_WIDTH, "height": capture.THUMB_HEIGHT}


def store(body, token):
    if len(body) > MAX_BYTES:
        raise ValueError("The capture exceeds the shared storage limit.")
    path = PREFIX + token + ".json"
    s3_store.put_bytes(path, body, "application/json")
    return json.dumps([path, len(body)])


def load(pointer):
    path, size = json.loads(pointer)
    if not path.startswith(PREFIX) or size > MAX_BYTES:
        raise ValueError("Invalid public capture.")
    return json.loads(s3_store.get_range(path, 0, size))


def index(key, pointer, fetched, lifetime):
    body_key, body_bytes = json.loads(pointer)
    artifacts.query_rows(
        "INSERT INTO public_page_cache SELECT {key:String}, {body:String}, {size:UInt64}, "
        "{fetched:UInt64}, fromUnixTimestamp64Milli({expires:Int64})",
        key=key, body=body_key, size=str(body_bytes), fetched=str(int(fetched * 1000)),
        expires=str(int((fetched + lifetime) * 1000)),
    )


def indexed(key):
    rows = artifacts.query_rows(
        "SELECT body_key, body_bytes FROM public_page_cache FINAL "
        "WHERE cache_key = {key:String} AND expires_at > now64(3) LIMIT 1", key=key,
    )
    if rows:
        return json.dumps([rows[0]["body_key"], rows[0]["body_bytes"]])
    return None


async def read(url, links, page_start, deadline, fetch, *, check=None):
    """Run one origin fetch under a fixed index lifetime and a bounded claim."""
    from browser_use_server.read_page import PageRead

    if not candidate(url):
        return await fetch()
    from redis.asyncio import Redis

    redis = Redis.from_url(os.getenv("RESEARCH_CACHE_REDIS_URL", "redis://redis:6379/0"),
                           socket_connect_timeout=2, socket_timeout=2)
    key = key_for(url, links, page_start)
    claim = key + ":claim"
    token = uuid.uuid4().hex
    owned = False
    async def lookup(*, durable=False):
        pointer = await redis.get(key)
        try:
            if pointer is None and durable:
                pointer = await asyncio.to_thread(indexed, key)
            if pointer is None:
                return None
            captured = await asyncio.to_thread(load, pointer)
            page = await prepare_hit(captured, url, page_start, check)
        except Exception:
            log.exception("public capture is unavailable")
            return None
        if page is not None:
            log.info("read_page cache shared hit")
        return page

    try:
        try:
            while time.monotonic() < deadline:
                cached = await lookup()
                if cached is not None:
                    return cached
                owned = bool(await redis.set(claim, token, ex=LEASE, nx=True))
                if owned:
                    cached = await lookup(durable=True)
                    if cached is not None:
                        return cached
                    break
                await asyncio.sleep(0.25)
            if not owned:
                return PageRead(url=url, error="The shared page read reached its deadline.", outcome="timeout")
        except Exception:
            log.exception("public capture index is unavailable")

        log.info("read_page cache origin miss")
        started = time.time()
        page = await fetch()
        if owned and eligible(page, url):
            fetched = time.time()
            lifetime = page.public_lifetime if page.public_lifetime is not None else TTL
            lifetime = max(0, min(TTL, lifetime - (fetched - started)))
            if not lifetime:
                return page
            try:
                pointer = await asyncio.to_thread(store, prepare(page, fetched, lifetime), token)
                ttl_ms = int((fetched + lifetime - time.time()) * 1000)
                if ttl_ms > 0:
                    published = await redis.eval(PUBLISH, 2, claim, key, token, pointer, ttl_ms)
                    if published:
                        await asyncio.to_thread(index, key, pointer, fetched, lifetime)
            except Exception:
                log.exception("could not publish a public page capture")
        return page
    finally:
        if owned:
            try:
                await redis.eval(RELEASE, 1, claim, token)
            except Exception:
                log.exception("could not release the public capture claim")
        await redis.aclose()
