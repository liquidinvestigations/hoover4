"""The HTTP requests of every source: a client for each source, routes in order, block checks.

All source requests go through :func:`fetch`. No other module opens an HTTP connection to a
source. :data:`TRANSPORTS` gives each source its client, its route order and its rate cap.

Clients:

* `wreq`: wreq with the `Chrome153` emulation. Its TLS and HTTP/2 fingerprint is the one of
  the Chromium 154 of the browser server. Brave refuses every other client of this module.
* `curl_cffi:<target>`: curl_cffi with an impersonation target. Yahoo accepts `chrome150` and
  refuses wreq and httpx. Bing uses `edge`, the target of the measured Bing request shape.
* `httpx`: the API sources. They send the API user agent of this server.
* `browser`: `POST /internal/fetch` of the browser server (`BROWSER_FETCH_URL`). The request
  runs in a tab of the special browser session `_metasearch`. Only Google needs it, because
  its result page needs script. The browser sends its own user agent and headers. Of the
  caller's headers it sends only `Accept-Language`, and it uses `Referer` as the referrer.

The wreq and curl_cffi clients send the headers of their browser. The callers add no user
agent to them, because a second user agent that differs from the TLS fingerprint marks the
request as a script.

Routes: `direct` is this host. The Tor routes are the SOCKS ports of the Tor instances in
the same container, from `METASEARCH_TOR_ROUTES`. Each request over Tor sends a new SOCKS
user name, so Tor builds a new circuit for it. A source has one route order: direct only,
direct then Tor, or Tor only. The Tor routes come in a new random order for each request.

Attempts: :func:`fetch` tries the routes in order, at most :data:`MAX_ATTEMPTS`. An answer is
a block when :func:`block_reason` names a cause: the status 403, 429, 451 or 5xx, the status
202, a Google `/sorry/` page, or a challenge marker in the body. After a block or a transport
failure, the next route gets the request. A block also puts the pair (route, host) in
cooldown for :data:`COOLDOWN_S`, and the next requests to that host skip that route. A
source with one route has no cooldown, because a skipped route would leave it no route.

Contract:

* :func:`fetch` returns the first :class:`FetchResponse` that is not a block. Its `route`
  names the route that gave it.
* :func:`fetch` raises :class:`FetchError` when no route gave such an answer. The message
  names each attempt and its cause, for example `direct: HTTP 429; tor-de: ConnectTimeout`.
* Redirects are followed unless `follow_redirects` is false. `FetchResponse.url` is the
  final URL.

Rate caps: each search engine has one token bucket (:data:`CAPS`) for all its routes
together. Each attempt takes one token. A request that gets no token before the deadline of
its source fails with the reason "rate cap of <engine>".

The deadline: `timeout` is in seconds. :func:`source_deadline` sets the end of the time that a
source has, as a `time.monotonic()` value, for the fetches of that source. An attempt gets at
most the time left before that end, less :data:`DEADLINE_MARGIN_S`. The source is cancelled
:data:`ANSWER_GRACE_S` after its deadline, so a fetch reports its own cause first.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import datetime
import json
import logging
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx

log = logging.getLogger(__name__)

#: The route without a proxy.
DIRECT = "direct"


def _tor_routes(raw: str) -> dict[str, str]:
    """`name=host:port,...` as a dict. An item without `=` is ignored."""
    routes: dict[str, str] = {}
    for item in raw.split(","):
        route, sep, address = item.strip().partition("=")
        if sep and route.strip() and address.strip():
            routes[route.strip()] = address.strip()
    return routes


#: Configured Tor route names and SOCKS addresses. Empty disables Tor.
TOR_ROUTES = _tor_routes(os.getenv(
    "METASEARCH_TOR_ROUTES",
    "",
))

#: The route orders.
DIRECT_ONLY = "direct only"
DIRECT_THEN_TOR = "direct, then Tor"
TOR_ONLY = "Tor only"

#: The clients.
WREQ = "wreq"
CURL_CHROME = "curl_cffi:chrome150"
CURL_EDGE = "curl_cffi:edge"
HTTPX = "httpx"
BROWSER = "browser"


@dataclass(frozen=True)
class Transport:
    client: str
    routes: str
    #: The name of the rate cap in :data:`CAPS`, or `""` for no cap.
    cap: str = ""


#: The client, the route order and the rate cap of each source. The evidence for each
#: choice is in the README section "Source fetches".
TRANSPORTS: dict[str, Transport] = {
    "ddg": Transport(WREQ, DIRECT_THEN_TOR, "duckduckgo"),
    "ddg_api": Transport(WREQ, DIRECT_THEN_TOR, "duckduckgo"),
    "ddg_news": Transport(CURL_CHROME, DIRECT_THEN_TOR, "duckduckgo"),
    "brave": Transport(WREQ, DIRECT_THEN_TOR, "brave"),
    "yahoo": Transport(CURL_CHROME, DIRECT_THEN_TOR, "yahoo"),
    "bing": Transport(CURL_EDGE, DIRECT_THEN_TOR, "bing"),
    "google": Transport(BROWSER, DIRECT_ONLY, "google"),
    "google_goto": Transport(CURL_CHROME, DIRECT_ONLY, "google_goto"),
    "mojeek": Transport(CURL_CHROME, DIRECT_ONLY, "mojeek"),
    "startpage": Transport(CURL_CHROME, DIRECT_ONLY, "startpage"),
    "gdelt": Transport(HTTPX, DIRECT_ONLY),
    "crossref": Transport(HTTPX, DIRECT_THEN_TOR),
    "wikipedia": Transport(HTTPX, DIRECT_THEN_TOR),
    "wikidata": Transport(HTTPX, DIRECT_THEN_TOR),
    "wayback": Transport(HTTPX, DIRECT_THEN_TOR),
    "factcheck": Transport(HTTPX, DIRECT_ONLY),
    "archive_today": Transport(WREQ, DIRECT_THEN_TOR),
}

#: The most routes that one request tries.
MAX_ATTEMPTS = 3

#: Seconds for one attempt when a later route can still take the request. The last attempt
#: gets all the time that is left.
ATTEMPT_TIMEOUT_S = float(os.getenv("METASEARCH_ATTEMPT_TIMEOUT", "6"))

#: Seconds that a route stays in cooldown for a host after a block.
COOLDOWN_S = float(os.getenv("METASEARCH_COOLDOWN_SECONDS", "600"))

#: The internal fetch endpoint of the browser server.
BROWSER_FETCH_URL = os.getenv("BROWSER_FETCH_URL", "")

#: The time between the end of an attempt and the deadline of the source, in seconds.
DEADLINE_MARGIN_S = 1.0

#: Seconds that a source may run past its deadline, to receive the answer of its last
#: attempt. Under load the browser answer arrives up to about 1 s after the browser's
#: deadline, and the event loop of this server can add more.
ANSWER_GRACE_S = 2.0

#: Extra seconds for the HTTP call to the browser server, past the browser's own deadline.
#: The browser closes the tab after its deadline, which takes at most 5 s.
BROWSER_ANSWER_GRACE_S = 6.0

#: Extra seconds for an attempt past the timeout of its client, before it is cancelled.
CLIENT_GRACE_S = 1.0

#: The end of the time of the current source, or None. See :func:`source_deadline`.
_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "metasearch_source_deadline", default=None)

#: The routes of the answers of the current source, or None. See :func:`record_routes`.
_ROUTES_USED: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "metasearch_routes_used", default=None)


class FetchError(RuntimeError):
    """No route gave an answer that is not a block. The message names each cause."""


@dataclass
class FetchResponse:
    status: int
    text: str
    url: str
    route: str = DIRECT
    #: The response headers, with lower-case names.
    headers: dict[str, str] = field(default_factory=dict)
    #: The cookies that the answer set, by name.
    cookies: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        """The body parsed as JSON. Raises `ValueError` when the body is not JSON."""
        return json.loads(self.text)


@contextlib.contextmanager
def source_deadline(deadline: float) -> Iterator[None]:
    """Let the fetches inside the block end by `deadline`, a `time.monotonic()` value."""
    token = _DEADLINE.set(deadline)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


@contextlib.contextmanager
def record_routes() -> Iterator[list[str]]:
    """Collect the route of each answer that :func:`fetch` returns inside the block."""
    used: list[str] = []
    token = _ROUTES_USED.set(used)
    try:
        yield used
    finally:
        _ROUTES_USED.reset(token)


# ------------------------------------------------------------------ rate caps


class RateCap:
    """A token bucket: `rate` requests a second, with a burst of `burst` requests."""

    def __init__(self, rate: float, burst: float) -> None:
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.at = time.monotonic()
        self._lock: tuple[asyncio.AbstractEventLoop, asyncio.Lock] | None = None

    def _refill(self) -> None:
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now - self.at) * self.rate)
        self.at = now

    async def take(self, deadline: float) -> bool:
        """Wait for one token. False when no token comes before `deadline`."""
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock[0] is not loop:
            self._lock = (loop, asyncio.Lock())
        # The lock makes the waiters take their tokens in order of arrival.
        async with self._lock[1]:
            self._refill()
            if self.tokens < 1:
                wait = (1 - self.tokens) / self.rate
                if time.monotonic() + wait > deadline:
                    return False
                await asyncio.sleep(wait)
                self._refill()
            self.tokens -= 1
            return True


#: Requests each second for each engine, across all routes.
ENGINE_RATE = float(os.getenv("METASEARCH_ENGINE_RATE", "3"))

#: Requests a second for the resolution of Google `/goto` links. It is a cap of its own, so
#: the resolutions do not take the tokens of the Google searches.
GOOGLE_GOTO_RATE = float(os.getenv("METASEARCH_GOOGLE_GOTO_RATE", "3"))

CAPS: dict[str, RateCap] = {
    **{name: RateCap(ENGINE_RATE, max(1.0, ENGINE_RATE))
       for name in ("duckduckgo", "brave", "yahoo", "bing", "google", "mojeek", "startpage")},
    "google_goto": RateCap(GOOGLE_GOTO_RATE, max(1.0, GOOGLE_GOTO_RATE)),
}


# ------------------------------------------------------------------ cooldowns

#: (route, host) -> the `time.monotonic()` value at which the cooldown ends.
_COOLDOWN: dict[tuple[str, str], float] = {}


def cooldown_left(route: str, host: str) -> float:
    """Seconds left of the cooldown of `route` for `host`, or 0."""
    return max(0.0, _COOLDOWN.get((route, host), 0.0) - time.monotonic())


def cooldowns() -> dict[str, int]:
    """The routes in cooldown now, as `"<route> <host>" -> seconds left`, for `/health`."""
    now = time.monotonic()
    return {f"{route} {host}": round(until - now)
            for (route, host), until in sorted(_COOLDOWN.items()) if until > now}


# ------------------------------------------------------------------ blocks

#: Statuses that mean the remote refused this route. A status of 500 or more counts too:
#: Yahoo answers HTTP 500 to a client whose fingerprint it refuses.
BLOCK_STATUSES = frozenset({403, 429, 451})

#: Texts of challenge pages: DuckDuckGo, DataDome, Anubis, Cloudflare, Mojeek, Startpage.
CHALLENGE_MARKERS = (
    "anomaly-modal",
    "captcha-delivery",
    "anubis_challenge",
    'id="challenge-form"',
    "captcha-wrap",
    "Startpage Blocked",
)


def status_block(response: FetchResponse) -> str:
    """The block cause from the status alone, or `""`."""
    if response.status in BLOCK_STATUSES or response.status >= 500:
        return f"HTTP {response.status}"
    return ""


def block_reason(response: FetchResponse) -> str:
    """Why an answer is a block, or `""` when it is not one."""
    reason = status_block(response)
    if reason:
        return reason
    if response.status == 202:
        # DuckDuckGo answers a refused request with HTTP 202 and a captcha page.
        return "HTTP 202 (a bot challenge page)"
    if "/sorry/" in response.url:
        return "a Google /sorry/ page"
    for marker in CHALLENGE_MARKERS:
        if marker in response.text:
            return f"HTTP {response.status} with the challenge marker {marker!r}"
    return ""


# ------------------------------------------------------------------ fetch

#: The longest text of one attempt cause, in characters.
NOTE_CHARS = 160


def _route_order(transport: Transport, prefer: str) -> list[str]:
    tor = random.sample(list(TOR_ROUTES), len(TOR_ROUTES))
    if transport.client == BROWSER or transport.routes == DIRECT_ONLY:
        order = [DIRECT]
    elif transport.routes == TOR_ONLY:
        order = tor
    else:
        order = [DIRECT, *tor]
    if prefer in order:
        order.remove(prefer)
        order.insert(0, prefer)
    return order


def _short(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= NOTE_CHARS else text[: NOTE_CHARS - 3] + "..."


async def fetch(
    source: str,
    url: str,
    *,
    timeout: float,
    method: str = "GET",
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
    multipart: dict[str, bytes] | None = None,
    follow_redirects: bool = True,
    blocked: Callable[[FetchResponse], str] | None = block_reason,
    circuit: str = "",
    prefer: str = "",
) -> FetchResponse:
    """Send one request of `source` to `url` and return the first answer that is not a block.

    `timeout` is in seconds, for the whole request when no source deadline is set. `data` is
    a form body. `multipart` is a multipart body and needs a curl_cffi client. `cookies`
    needs a curl_cffi or wreq client. `blocked` names the block cause of an answer, see
    :func:`block_reason`. A Tor attempt with `circuit` uses that SOCKS user name, so two
    requests with the same `circuit` and route share one Tor circuit. `prefer` names a route
    to try first.
    """
    transport = TRANSPORTS[source]
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"
    host = (urlsplit(url).hostname or "").lower()
    end = _DEADLINE.get()
    if end is None:
        end = time.monotonic() + float(timeout)
    order = _route_order(transport, prefer)
    several = len(order) > 1
    notes: list[str] = []
    attempts = 0
    for index, route in enumerate(order):
        if attempts >= MAX_ATTEMPTS:
            break
        if several:
            left = cooldown_left(route, host)
            if left > 0:
                notes.append(f"{route}: in cooldown for {left:.0f} s after a block")
                continue
        last = attempts == MAX_ATTEMPTS - 1 or index == len(order) - 1
        budget = min(float(timeout), end - time.monotonic() - DEADLINE_MARGIN_S)
        if budget <= 0:
            notes.append("no time was left in the deadline of the source")
            break
        if transport.cap:
            if not await CAPS[transport.cap].take(time.monotonic() + budget):
                notes.append(f"rate cap of {transport.cap}: no request slot within {budget:.1f} s")
                break
            budget = min(budget, end - time.monotonic() - DEADLINE_MARGIN_S)
        if several and not last and transport.client != BROWSER:
            budget = min(budget, ATTEMPT_TIMEOUT_S)
        attempts += 1
        try:
            response = await _send(transport.client, route, method, url, headers, cookies, data,
                                   multipart, budget, follow_redirects, circuit)
        except Exception as exc:  # noqa: BLE001 - every transport failure is a note
            cause = str(exc) if isinstance(exc, FetchError) else f"{type(exc).__name__}: {exc}"
            notes.append(f"{route}: {_short(cause)}")
            continue
        why = blocked(response) if blocked else ""
        if why:
            notes.append(f"{route}: {why}")
            if several:
                _COOLDOWN[(route, host)] = time.monotonic() + COOLDOWN_S
            continue
        response.route = route
        used = _ROUTES_USED.get()
        if used is not None:
            used.append(route)
        return response
    if not attempts and notes and all("in cooldown" in note for note in notes):
        raise FetchError(f"every route is in cooldown for {host}: " + "; ".join(notes))
    raise FetchError("; ".join(notes) or "no route was tried")


async def _send(client, route, method, url, headers, cookies, data, multipart, budget,
                follow_redirects, circuit) -> FetchResponse:
    proxy = None
    if route != DIRECT:
        # A new SOCKS user name gives a new circuit (IsolateSOCKSAuth in the torrc files).
        proxy = f"socks5h://{circuit or uuid.uuid4().hex}:x@{TOR_ROUTES[route]}"
    if client == BROWSER:
        return await _send_browser(url, headers, budget)
    if client == HTTPX:
        call = _send_httpx(proxy, method, url, headers, data, budget, follow_redirects)
    elif client == WREQ:
        call = _send_wreq(proxy, method, url, headers, cookies, data, budget, follow_redirects)
    elif client.startswith("curl_cffi:"):
        call = _send_curl(client.split(":", 1)[1], proxy, method, url, headers, cookies, data,
                          multipart, budget, follow_redirects)
    else:
        raise ValueError(f"unknown client {client!r}")
    try:
        return await asyncio.wait_for(call, budget + CLIENT_GRACE_S)
    except asyncio.TimeoutError:
        raise FetchError(f"no answer within {budget:.1f} s") from None


#: The httpx client for the direct route and the event loop it belongs to. One client
#: serves all direct API requests and the browser endpoint: a new client builds a TLS
#: context, which takes about 6 ms of the event loop.
_HTTPX: tuple[asyncio.AbstractEventLoop, httpx.AsyncClient] | None = None


def _httpx_client() -> httpx.AsyncClient:
    global _HTTPX
    loop = asyncio.get_running_loop()
    if _HTTPX is None or _HTTPX[0] is not loop:
        _HTTPX = (loop, httpx.AsyncClient(limits=httpx.Limits(max_connections=256)))
    return _HTTPX[1]


def _httpx_response(response: httpx.Response) -> FetchResponse:
    return FetchResponse(
        status=response.status_code, text=response.text, url=str(response.url),
        headers={k.lower(): v for k, v in response.headers.items()},
        cookies=dict(response.cookies.items()))


async def _send_httpx(proxy, method, url, headers, data, budget, follow_redirects):
    if proxy is None:
        response = await _httpx_client().request(
            method, url, headers=headers, data=data, timeout=budget,
            follow_redirects=follow_redirects)
        return _httpx_response(response)
    async with httpx.AsyncClient(proxy=proxy, timeout=budget) as client:
        response = await client.request(method, url, headers=headers, data=data,
                                        follow_redirects=follow_redirects)
        return _httpx_response(response)


async def _send_wreq(proxy, method, url, headers, cookies, data, budget, follow_redirects):
    import wreq

    options: dict[str, Any] = {
        "emulation": wreq.Emulation.Chrome153,
        "timeout": datetime.timedelta(seconds=budget),
        "redirect": wreq.redirect.Policy.limited(10) if follow_redirects
        else wreq.redirect.Policy.none(),
    }
    if proxy:
        options["proxies"] = [wreq.Proxy.all(proxy)]
    client = wreq.Client(**options)
    try:
        request: dict[str, Any] = {}
        if headers:
            request["headers"] = headers
        if cookies:
            request["cookies"] = cookies
        if data:
            request["form"] = list(data.items())
        if method == "POST":
            response = await client.post(url, **request)
        else:
            response = await client.get(url, **request)
        text = await response.text()
        return FetchResponse(
            status=response.status.as_int(), text=text, url=str(response.url),
            # A wreq header map yields (name, value) pairs of bytes.
            headers={_header_text(k).lower(): _header_text(v) for k, v in response.headers},
            cookies={c.name: c.value for c in response.cookies})
    finally:
        client.close()


def _header_text(value: Any) -> str:
    return value.decode("latin-1") if isinstance(value, (bytes, bytearray)) else str(value)


async def _send_curl(target, proxy, method, url, headers, cookies, data, multipart, budget,
                     follow_redirects):
    from curl_cffi import CurlMime
    from curl_cffi.requests import AsyncSession

    options: dict[str, Any] = {"impersonate": target, "timeout": budget,
                               "allow_redirects": follow_redirects}
    if proxy:
        options["proxy"] = proxy
    mime = None
    if multipart:
        mime = CurlMime()
        for part, value in multipart.items():
            mime.addpart(name=part, data=value)
    try:
        async with AsyncSession(**options) as session:
            # The cookies go into the session jar for the site domain of the URL (the last
            # two labels of the host), which is the domain that Bing, Mojeek and Startpage
            # set. Measured on Bing: the same cookies as the `cookies` argument of the
            # request, or in the jar for the full host name, gave the results of a request
            # without cookies.
            labels = (urlsplit(url).hostname or "").split(".")
            for name, value in (cookies or {}).items():
                session.cookies.set(name, value, domain="." + ".".join(labels[-2:]))
            response = await session.request(method, url, headers=headers, data=data,
                                             multipart=mime)
            return FetchResponse(
                status=response.status_code, text=response.text, url=str(response.url),
                headers={k.lower(): v for k, v in response.headers.items()},
                # The session jar holds the cookies of every answer, redirects included.
                cookies={c.name: c.value for c in session.cookies.jar})
    finally:
        if mime is not None:
            mime.close()


def browser_headers() -> dict[str, str]:
    """Read the mounted internal fetch token without recording its value."""
    path = os.getenv("BROWSER_FETCH_TOKEN_FILE", "")
    try:
        token = Path(path).read_text().strip() if path else ""
    except OSError:
        token = ""
    return {"Authorization": "Bearer " + token} if token else {}


async def _send_browser(url, headers, budget) -> FetchResponse:
    request = {
        "url": url,
        "method": "GET",
        "params": {},
        "headers": dict(headers or {}),
        "timeout_s": round(budget, 3),
        # Google starts a second navigation from a script, so the raw body of the first
        # document is gone. "dom" returns the last document's HTML.
        "body": "dom",
    }
    if not BROWSER_FETCH_URL:
        raise FetchError("The browser fetch endpoint is not configured.")
    try:
        answer = await _httpx_client().post(BROWSER_FETCH_URL, json=request, headers=browser_headers(),
                                            timeout=budget + BROWSER_ANSWER_GRACE_S)
    except Exception as exc:  # noqa: BLE001
        raise FetchError(
            f"the browser fetch endpoint {BROWSER_FETCH_URL} did not answer: "
            f"{type(exc).__name__}: {exc}") from exc
    try:
        data = answer.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise FetchError(f"the browser fetch endpoint answered HTTP {answer.status_code} "
                         f"without a JSON object: {answer.text.strip()[:160]}")
    if answer.status_code != 200 or data.get("error"):
        kind = data.get("error_kind") or f"HTTP {answer.status_code}"
        raise FetchError(f"browser fetch {kind}: {data.get('error') or 'no detail'}")
    return FetchResponse(status=int(data.get("status") or 0), text=str(data.get("body") or ""),
                         url=str(data.get("url") or url))


# ------------------------------------------------------------------ health

#: Seconds that each `/health` probe waits for an answer.
PROBE_TIMEOUT_S = 2.0


async def probe_browser() -> str:
    """Send an empty request to the browser fetch endpoint. Returns `""` when it answers.

    The browser server refuses the empty body with HTTP 400 and a JSON object, and it opens
    no tab for it. Any JSON object in the answer shows that the endpoint is served. Otherwise
    the return value names the cause.
    """
    try:
        answer = await _httpx_client().post(BROWSER_FETCH_URL, json={}, headers=browser_headers(), timeout=PROBE_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - the cause goes into the health answer
        return (f"the browser fetch endpoint {BROWSER_FETCH_URL} did not answer: "
                f"{type(exc).__name__}: {exc}")
    try:
        data = answer.json()
    except ValueError:
        data = None
    if answer.status_code not in (200, 400):
        return f"The browser fetch endpoint answered HTTP {answer.status_code}."
    if not isinstance(data, dict):
        return "The browser fetch endpoint did not return a JSON object."
    return ""


async def probe_tor_routes() -> dict[str, bool]:
    """Whether the SOCKS port of each Tor route accepts a TCP connection."""

    async def accepts(address: str) -> bool:
        host, _, port = address.rpartition(":")
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, int(port)),
                                               PROBE_TIMEOUT_S)
        except (OSError, ValueError, asyncio.TimeoutError):
            return False
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        return True

    names = list(TOR_ROUTES)
    results = await asyncio.gather(*(accepts(TOR_ROUTES[name]) for name in names))
    return dict(zip(names, results))
