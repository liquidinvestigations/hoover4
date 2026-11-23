"""Shared pacing of outbound requests for each remote.

Every automated request to a public site gets a permit from :func:`admit` immediately
before it starts. The metasearch fetches and the reader attempts of the browser server use
the same permits, through the same Redis store, so every replica, chat and route shares one
limit for each remote.

Policy key: the normalized host of the URL. A provider that shares one quota across several
hosts has one key for all of them (:data:`PROVIDER_GROUPS`), for example `wikimedia` for the
pages of Wikipedia, Wikidata and Wikimedia Commons. The API requests of a group have a key
of their own (:data:`API_PATHS`), for example `wikimedia-api`, because the provider limits
them apart from page reads. A 429 answer to a page read then does not stop the API searches.

Pacing: starts of one key are at least the interval of the key apart
(`OUTBOUND_INTERVAL_SECONDS`, 6 s by default, `OUTBOUND_POLICY_INTERVALS` for each key). An
idle key gives one immediate start. An unused interval gives no burst credit. Another key
starts independently. A started request can still run when the next start comes.

A permit reserves the next free start time of its key. When that start is later than the
deadline of the caller, :func:`admit` raises :class:`Deferred` and reserves nothing. The
exception names the remote, the reason and the next eligible time.

Provider cooldown: :func:`record` reads each answer. A 429 or 503 answer sets a cooldown on
the key until the later of the `Retry-After` time (seconds or an HTTP date) and the next
paced start. Without `Retry-After`, the cooldown is a bounded exponential backoff with
jitter. A later answer below 400 resets the backoff.

Redirects: the HTTP clients and the browser follow a redirect inside one request, so a
redirect to another key starts without a permit. :func:`follow` counts that start on the
key of the final URL (:func:`charge`), and the next start of that key waits one interval.

Counters: the Redis hash `outbound:stats:<key>` counts `starts`, `redirect_starts`,
`deferred`, `waited_ms` and `status_<code>` for each key. The log has one line for each start, deferral and
cooldown.

Without Redis, the module keeps the same state in this process and logs a warning once.
"""

from __future__ import annotations

import asyncio
import email.utils
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

#: The host suffixes of providers that share one quota across their hosts.
PROVIDER_GROUPS = {
    "wikipedia.org": "wikimedia", "wikidata.org": "wikimedia", "wikimedia.org": "wikimedia",
    "mediawiki.org": "wikimedia", "wiktionary.org": "wikimedia", "wikisource.org": "wikimedia",
    "archive.org": "archive",
}

#: The path starts of the API requests of a provider group. Their key is `<group>-api`.
API_PATHS = {"wikimedia": ("/w/api.php", "/api/", "/sparql", "/bigdata/")}

#: The most seconds of a backoff after a 429 or 503 answer without `Retry-After`.
BACKOFF_MAX_S = 600.0

_KEY = "outbound:next:"
_COOL = "outbound:cool:"
_FAILS = "outbound:fails:"
_STATS = "outbound:stats:"

#: Reserve the next start of one key. KEYS: next, cooldown, stats. ARGV: interval ms, most
#: wait ms. The result is {0, wait ms, ""} for a permit, or {1, wait ms, reason} for a
#: deferral that reserves nothing.
RESERVE = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local nxt = tonumber(redis.call('GET', KEYS[1]) or '0')
local cool = tonumber(redis.call('GET', KEYS[2]) or '0')
local start = math.max(now, nxt, cool)
local wait = start - now
if wait > tonumber(ARGV[2]) then
  redis.call('HINCRBY', KEYS[3], 'deferred', 1)
  local reason = 'pacing'
  if cool > nxt and cool > now then reason = 'provider cooldown' end
  return {1, wait, reason}
end
local interval = tonumber(ARGV[1])
redis.call('SET', KEYS[1], start + interval, 'PX', wait + interval + 60000)
redis.call('HINCRBY', KEYS[3], 'starts', 1)
redis.call('HINCRBY', KEYS[3], 'waited_ms', wait)
return {0, wait, ''}
"""

#: Extend the cooldown of one key to at least ARGV[1] ms from now. KEYS: cooldown.
COOL = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local untilms = now + tonumber(ARGV[1])
local cool = tonumber(redis.call('GET', KEYS[1]) or '0')
if untilms > cool then
  redis.call('SET', KEYS[1], untilms, 'PX', tonumber(ARGV[1]) + 60000)
end
return untilms
"""


def _intervals(raw: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in raw.split(","):
        key, sep, value = item.strip().partition("=")
        if sep and key.strip():
            out[key.strip().lower()] = float(value)
    return out


def default_interval() -> float:
    """The seconds between starts of a key without its own setting."""
    return float(os.getenv("OUTBOUND_INTERVAL_SECONDS", "6"))


def interval_of(key: str) -> float:
    """The seconds between two starts of `key`."""
    return _intervals(os.getenv("OUTBOUND_POLICY_INTERVALS", "")).get(key, default_interval())


def policy_key(url: str) -> str:
    """The pacing key of a URL or a host: its provider group, with `-api` for an API path
    of the group, else its normalized host."""
    parts = urlsplit(url) if "/" in url else None
    host = (parts.hostname if parts else url) or ""
    host = host.strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    for suffix, group in PROVIDER_GROUPS.items():
        if host == suffix or host.endswith("." + suffix):
            if parts and parts.path.startswith(API_PATHS.get(group, ())):
                return group + "-api"
            return group
    return host


class Deferred(Exception):
    """The next permit of a remote comes after the caller's deadline."""

    def __init__(self, key: str, reason: str, wait_s: float) -> None:
        self.key = key
        self.reason = reason
        self.wait_s = wait_s
        self.next_at = time.time() + wait_s
        when = time.strftime("%H:%M:%S", time.gmtime(self.next_at))
        super().__init__(f"deferred: {key} has no request slot before the deadline "
                         f"({reason}). The next request can start at {when} UTC.")


@dataclass
class _Local:
    nxt: float = 0.0
    cool: float = 0.0
    fails: int = 0


_LOCAL: dict[str, _Local] = {}
_LOCAL_LOCK: Optional[tuple[asyncio.AbstractEventLoop, asyncio.Lock]] = None
_WARNED = False
_REDIS = None


def _redis():
    global _REDIS
    loop = asyncio.get_running_loop()
    if _REDIS is None or _REDIS[0] is not loop:
        from redis.asyncio import Redis

        _REDIS = (loop, Redis.from_url(
            os.getenv("RESEARCH_CACHE_REDIS_URL", "redis://redis:6379/0"),
            socket_connect_timeout=2, socket_timeout=2))
    return _REDIS[1]


def _fallback(exc: Exception) -> None:
    global _WARNED
    if not _WARNED:
        log.warning("outbound pacing uses process state, because Redis failed: %s", exc)
        _WARNED = True


def _lock() -> asyncio.Lock:
    global _LOCAL_LOCK
    loop = asyncio.get_running_loop()
    if _LOCAL_LOCK is None or _LOCAL_LOCK[0] is not loop:
        _LOCAL_LOCK = (loop, asyncio.Lock())
    return _LOCAL_LOCK[1]


async def _reserve(key: str, interval_s: float, max_wait_s: float) -> tuple[bool, float, str]:
    # An immediate start is always granted. Only a wait is compared with the deadline.
    max_wait_s = max(0.0, max_wait_s)
    try:
        ok, wait_ms, reason = await _redis().eval(
            RESERVE, 3, _KEY + key, _COOL + key, _STATS + key,
            int(interval_s * 1000), int(max_wait_s * 1000))
        reason = reason.decode() if isinstance(reason, bytes) else str(reason or "")
        return int(ok) == 0, int(wait_ms) / 1000, reason
    except Exception as exc:  # noqa: BLE001 - any store failure selects process state
        _fallback(exc)
    async with _lock():
        state = _LOCAL.setdefault(key, _Local())
        now = time.time()
        start = max(now, state.nxt, state.cool)
        wait = start - now
        if wait > max_wait_s:
            reason = "provider cooldown" if state.cool > state.nxt and state.cool > now else "pacing"
            return False, wait, reason
        state.nxt = start + interval_s
        return True, wait, ""


async def admit(url: str, deadline: float, *, route: str = "") -> float:
    """Wait for the permit of the remote of `url` and return the seconds waited.

    `deadline` is a `time.monotonic()` value. Raises :class:`Deferred` when the permit comes
    after it. Call this immediately before the request starts, after every cache.
    """
    key = policy_key(url)
    if not key:
        return 0.0
    ok, wait, reason = await _reserve(key, interval_of(key), deadline - time.monotonic())
    if not ok:
        log.info("outbound deferred key=%s route=%s reason=%s wait_s=%.1f", key, route, reason, wait)
        raise Deferred(key, reason, wait)
    if wait > 0:
        await asyncio.sleep(wait)
    log.info("outbound start key=%s route=%s waited_s=%.1f", key, route, wait)
    return wait


#: Move the next start of one key to at least ARGV[1] ms from now. KEYS: next, stats.
CHARGE = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local nxt = tonumber(redis.call('GET', KEYS[1]) or '0')
local start = math.max(now, nxt)
redis.call('SET', KEYS[1], start + tonumber(ARGV[1]), 'PX', start - now + tonumber(ARGV[1]) + 60000)
redis.call('HINCRBY', KEYS[2], 'redirect_starts', 1)
return start - now
"""


async def charge(url: str, *, route: str = "") -> None:
    """Count a start that a redirect made to the remote of `url`. The HTTP clients and the
    browser follow a redirect inside one request, so this start had no permit. The next
    start of its key comes one interval later."""
    key = policy_key(url)
    if not key:
        return
    interval = interval_of(key)
    try:
        await _redis().eval(CHARGE, 2, _KEY + key, _STATS + key, int(interval * 1000))
    except Exception as exc:  # noqa: BLE001 - any store failure selects process state
        _fallback(exc)
        async with _lock():
            state = _LOCAL.setdefault(key, _Local())
            state.nxt = max(time.time(), state.nxt) + interval
    log.info("outbound redirect start key=%s route=%s", key, route)


async def follow(start_url: str, final_url: str, *, route: str = "") -> None:
    """Charge the remote of a final URL when a redirect left the key of the start URL."""
    if final_url and policy_key(final_url) != policy_key(start_url):
        await charge(final_url, route=route)


def retry_after_seconds(value: object) -> Optional[float]:
    """The seconds of a `Retry-After` value: a number of seconds or an HTTP date."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    text = str(value).strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - time.time())


def backoff_seconds(fails: int, base: float) -> float:
    """The cooldown after `fails` consecutive 429 or 503 answers without `Retry-After`."""
    delay = min(BACKOFF_MAX_S, base * (2 ** max(0, fails - 1)))
    return delay * random.uniform(0.8, 1.2)


async def record(url: str, status: Optional[int], retry_after: object = None, *,
                 route: str = "") -> Optional[float]:
    """Record the answer of one request. A 429 or 503 starts a provider cooldown, and its
    seconds are returned. Any other answer below 400 resets the backoff."""
    key = policy_key(url)
    if not key or status is None:
        return None
    try:
        redis = _redis()
        await redis.hincrby(_STATS + key, f"status_{int(status)}", 1)
        if status not in (429, 503):
            if status < 400:
                await redis.delete(_FAILS + key)
            return None
        fails = int(await redis.incr(_FAILS + key))
        await redis.expire(_FAILS + key, int(BACKOFF_MAX_S * 2))
    except Exception as exc:  # noqa: BLE001 - any store failure selects process state
        _fallback(exc)
        redis = None
        state = _LOCAL.setdefault(key, _Local())
        if status not in (429, 503):
            if status < 400:
                state.fails = 0
            return None
        state.fails += 1
        fails = state.fails
    delay = retry_after_seconds(retry_after)
    if delay is None:
        delay = backoff_seconds(fails, interval_of(key))
    delay = min(delay, BACKOFF_MAX_S)
    if redis is not None:
        try:
            await redis.eval(COOL, 1, _COOL + key, int(delay * 1000))
        except Exception as exc:  # noqa: BLE001
            _fallback(exc)
            redis = None
    if redis is None:
        state = _LOCAL.setdefault(key, _Local())
        state.cool = max(state.cool, time.time() + delay)
    log.info("outbound cooldown key=%s route=%s status=%s seconds=%.1f", key, route, status, delay)
    return delay


__all__ = [
    "API_PATHS", "BACKOFF_MAX_S", "Deferred", "PROVIDER_GROUPS", "admit", "backoff_seconds", "charge",
    "default_interval", "follow", "interval_of", "policy_key", "record", "retry_after_seconds",
]
