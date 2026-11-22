"""Persist successful exact searches and provider results within one chat."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
import weakref
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import asdict

from agent_common import artifacts
from agent_common.fusion import SearchResult

log = logging.getLogger(__name__)
LOCKS = weakref.WeakValueDictionary()
MAX_BYTES = 16 * 1024 * 1024


def provider_profile():
    from metasearch_server import sources

    return [sources.PER_SOURCE_RESULTS, os.getenv("WIKIPEDIA_LANGUAGE", "en")]


def key_for(scope, kind, arguments):
    key = json.dumps([1, scope, kind, arguments], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()


def lock(key):
    return LOCKS.setdefault(key, asyncio.Lock())


@asynccontextmanager
async def serialized(key):
    """Coordinate a cache miss across search workers when the shared index is ready."""
    async with lock(key):
        endpoint = os.getenv("RESEARCH_CACHE_REDIS_URL")
        if not endpoint:
            yield
            return
        from redis.asyncio import Redis
        from redis.exceptions import RedisError

        client = Redis.from_url(endpoint, socket_connect_timeout=2, socket_timeout=2)
        claim = client.lock(f"hoover4:metasearch:{key}", timeout=120, blocking_timeout=70)
        owned = False
        try:
            try:
                owned = await claim.acquire()
            except RedisError:
                log.warning("The shared search index is unavailable.")
                yield
                return
            if not owned:
                raise TimeoutError("The active search did not finish before the cache deadline.")
            yield
        finally:
            if owned:
                try:
                    await claim.release()
                except RedisError:
                    log.warning("The search cache claim expired before release.")
            await client.aclose()


def read(scope, kind, key):
    rows = artifacts.query_rows(
        "SELECT artifact_id FROM chat_artifacts FINAL WHERE username = {owner:String} "
        "AND session_id = {session:String} AND kind = {kind:String} AND title = {key:String} "
        "AND is_deleted = 0 AND status = 'ok' ORDER BY detail DESC LIMIT 1",
        owner=scope[0], session=scope[1], kind=kind, key=key,
    )
    if not rows:
        return None
    body, size = artifacts.read_range(*scope, rows[0]["artifact_id"], 0, MAX_BYTES)
    return json.loads(body) if len(body) == size else None


def write(scope, kind, key, value):
    import time

    body = json.dumps(value, ensure_ascii=False).encode()
    if len(body) > MAX_BYTES:
        return
    artifact_id = str(uuid.uuid4())
    artifacts.write_required(
        artifacts.ArtifactRequest(scope[1], scope[0], kind, "web_search",
                                  title=key, detail=str(time.time_ns())),
        artifact_id, key, body, "application/json",
    )


async def cached(scope, kind, key):
    try:
        value = await asyncio.to_thread(read, scope, kind, key)
    except Exception:
        log.exception("could not read a retained search")
        return None
    if value is not None:
        log.info("web_search cache hit %s", kind)
    return value


async def retain(scope, kind, key, value):
    try:
        await asyncio.to_thread(write, scope, kind, key, value)
    except Exception:
        log.exception("could not retain a search result")


async def fetch_providers(scope, query, names, timelimit, timeout, refresh, fetch):
    from metasearch_server import sources

    kind = "web_provider_cache"
    keys = {name: key_for(scope, kind, [query, name, timelimit, provider_profile()])
            for name in names}
    results, latency, reasons, routes = {}, {}, {}, {}
    async with asyncio.timeout(timeout):
        # Acquire in lexical order so overlapping requests cannot deadlock.
        async with AsyncExitStack() as held:
            for key in sorted(keys.values()):
                await held.enter_async_context(serialized(key))
            missing = []
            for name in names:
                value = None if refresh else await cached(scope, kind, keys[name])
                if value is None:
                    missing.append(name)
                    continue
                results[name] = [SearchResult(**row) for row in value["results"]]
                latency[name] = 0
                routes[name] = value["route"]
                if not results[name]:
                    reasons[name] = sources.NO_RESULTS
            if missing:
                log.info("web_search provider dispatches %d", len(missing))
                found, seconds, _, degraded, used = await fetch(
                    query, missing, timelimit=timelimit, overall_timeout=timeout)
                results.update(found)
                latency.update(seconds)
                routes.update(used)
                reasons.update(degraded)
                for name in missing:
                    if name in found and degraded.get(name, "") in {"", sources.NO_RESULTS}:
                        await retain(scope, kind, keys[name],
                                     {"results": [asdict(item) for item in found[name]],
                                      "route": used.get(name, "")})
    # Preserve provider order for the existing rank fusion.
    return ({name: results[name] for name in names}, latency,
            [name for name in names if not results[name]], reasons, routes)
