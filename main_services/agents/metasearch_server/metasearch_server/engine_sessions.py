"""The search engines that need more than one request for a result page.

* Bing: a cookie jar from `https://www4.bing.com/`, kept :data:`BING_COOKIE_TTL_S`, then
  `www4.bing.com/search?q=...&form=QBRE`. Without the cookies, one of two measured plain
  requests returned a full page of results about another subject.
* Google: each result links through `/goto?url=<token>`. :func:`resolve_google_links`
  sends one GET without redirects for each of the first :data:`GOOGLE_GOTO_LIMIT` links, and
  the `Location` header gives the target. These GETs have a rate cap of their own.
* Mojeek: an ALTCHA proof of work. `GET /captcha/challenge`, a PBKDF2 search in a thread,
  `POST /captcha/verify`, then the `chllg` cookie opens the result pages.
* Startpage: an Anubis proof of work. `GET /` gives the challenge, a SHA-256 search in
  worker processes, `GET .../pass-challenge` gives the cookies, then `POST /sp/search`.

The solvers support bounded proof-of-work challenges. Image and behaviour captchas remain
unsolved. Mojeek and Startpage use the direct route only: Mojeek does not accept connections
from the measured Tor exits, and Startpage shows a block page to them.

A solved cookie is kept in memory until the engine answers with its challenge again. Then
one new solve runs, and every request that waits for it uses its cookie. A solve runs in a
task of its own, so a source that reaches its deadline does not stop it, and the next search
gets the cookie.

The remote page sets the work of a challenge, so each solve has limits. A challenge above
:data:`MAX_ANUBIS_DIFFICULTY` or :data:`MAX_ALTCHA_COST` is refused without work. A solve
stops after :data:`SOLVE_TIMEOUT_S`. After a failed solve, the engine gets no new solve for
:data:`SOLVE_BACKOFF_S`, and its searches fail at once with the reason.
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import contextlib
import ctypes
import hashlib
import json
import logging
import multiprocessing
import os
import re
import signal
import time
from dataclasses import dataclass, field
import ipaddress
from typing import Awaitable, Callable
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from metasearch_server.fetch import FetchError, FetchResponse, fetch, status_block

log = logging.getLogger(__name__)


#: Seconds that one solve may take, with its requests. At the limit the solve stops, and
#: the Anubis worker processes close.
SOLVE_TIMEOUT_S = float(os.getenv("METASEARCH_SOLVE_TIMEOUT", "30"))

#: Seconds without a new solve after a failed solve of an engine.
SOLVE_BACKOFF_S = float(os.getenv("METASEARCH_SOLVE_BACKOFF", "300"))


@dataclass
class SolvedCookies:
    """The cookies of one engine and the count of solves that produced them."""

    name: str
    cookies: dict[str, str] = field(default_factory=dict)
    generation: int = 0
    task: asyncio.Task | None = None
    #: The `time.monotonic()` value before which no new solve starts, after a failure.
    failed_until: float = 0.0
    failure: str = ""


async def _solve_once(state: SolvedCookies, seen: int,
                      solve: Callable[[], Awaitable[dict[str, str]]]) -> None:
    """Run `solve` unless a solve after generation `seen` already ran or is running.

    Raises :class:`FetchError` when the solve fails, or at once while the engine waits
    after a failed solve.
    """
    if state.generation != seen:
        return
    loop = asyncio.get_running_loop()
    if state.task is None or state.task.done() or state.task.get_loop() is not loop:
        wait = state.failed_until - time.monotonic()
        if wait > 0:
            raise FetchError(f"the last {state.name} solve failed ({state.failure}); "
                             f"the next solve can start in {wait:.0f} s")

        async def run() -> None:
            try:
                state.cookies = await asyncio.wait_for(solve(), SOLVE_TIMEOUT_S)
            except asyncio.TimeoutError:
                state.failure = f"no solution within {SOLVE_TIMEOUT_S:g} s"
            except Exception as exc:  # noqa: BLE001 - every failure starts the back-off
                state.failure = str(exc)[:160]
            else:
                state.generation += 1
                return
            state.failed_until = time.monotonic() + SOLVE_BACKOFF_S
            raise FetchError(f"the {state.name} solve failed: {state.failure}")

        state.task = loop.create_task(run())
        # A solve whose waiters were all cancelled must not log an unread exception.
        state.task.add_done_callback(lambda task: task.cancelled() or task.exception())
    await asyncio.shield(state.task)


async def _step(step: str, request: Awaitable[FetchResponse]) -> FetchResponse:
    """Await `request`, and put `step` in front of the reason of a failure. A reason then
    names the request of a flow that failed, for example the Anubis pass."""
    try:
        return await request
    except FetchError as exc:
        raise FetchError(f"{step}: {exc}") from exc


# ------------------------------------------------------------------ Bing

BING_HOME = "https://www4.bing.com/"
BING_COOKIE_TTL_S = 1800.0

_BING: dict = {"cookies": {}, "at": float("-inf")}


async def bing_page(url: str, timeout: float) -> FetchResponse:
    """The result page at `url`, with the cookie jar of the Bing home page."""
    if time.monotonic() - _BING["at"] > BING_COOKIE_TTL_S:
        try:
            home = await fetch("bing", BING_HOME, timeout=timeout)
            _BING.update(cookies=home.cookies, at=time.monotonic())
        except FetchError as exc:
            # The search still runs, without the cookies.
            log.warning("bing home page for the cookie jar failed: %s", exc)
    return await fetch("bing", url, timeout=timeout, cookies=_BING["cookies"] or None)


# ------------------------------------------------------------------ Google

#: The result links of one Google page that are resolved.
GOOGLE_GOTO_LIMIT = 5

#: The target of a refresh or script redirect page.
_REDIRECT_TARGET = re.compile(
    r"""(?:url=|location\.replace\(|location\.href\s*=\s*)["']?(https?://[^"'>\s)]+)""",
    re.IGNORECASE,
)


#: Name suffixes of hosts that are not on the public internet.
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")


def is_public_host(host: str) -> bool:
    """False for an address literal that is not global, and for a local or single-label
    name. The name is not resolved."""
    host = host.strip("[]").lower().rstrip(".")
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    return ("." in host and host != "localhost"
            and not any(host.endswith(suffix) for suffix in _LOCAL_SUFFIXES))


def is_goto_link(url: str) -> bool:
    """True for a `https://www.google.com/goto?...` link, the only links that are resolved."""
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname == "www.google.com" and \
        parts.path == "/goto"


def goto_target(response: FetchResponse) -> str:
    """The target URL of an answer to a `/goto` link, or `""`.

    A target on Google or on a host that is not public is refused.
    """
    target = ""
    if 300 <= response.status < 400:
        target = response.headers.get("location", "")
    elif response.status == 200:
        match = _REDIRECT_TARGET.search(response.text[:20000])
        target = match.group(1) if match else ""
    parts = urlsplit(target)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not is_public_host(host):
        return ""
    if host == "google.com" or host.endswith(".google.com"):
        return ""
    return target


async def resolve_google_links(urls: list[str], timeout: float) -> list[str]:
    """`urls` with the first :data:`GOOGLE_GOTO_LIMIT` `/goto` links replaced by their target.

    A link that does not resolve keeps its `/goto` URL, which still opens the page.
    """
    async def one(url: str) -> str:
        try:
            response = await fetch("google_goto", url, timeout=timeout,
                                   follow_redirects=False, blocked=status_block)
        except FetchError as exc:
            log.info("google /goto link did not resolve: %s", exc)
            return url
        return goto_target(response) or url

    todo = [i for i, url in enumerate(urls) if is_goto_link(url)][:GOOGLE_GOTO_LIMIT]
    resolved = await asyncio.gather(*(one(urls[i]) for i in todo))
    out = list(urls)
    for i, url in zip(todo, resolved):
        out[i] = url
    return out


# ------------------------------------------------------------------ Mojeek ALTCHA

MOJEEK = "https://www.mojeek.com"

_MOJEEK = SolvedCookies("Mojeek ALTCHA")

#: The highest ALTCHA PBKDF2 cost that is solved. The measured cost was 8000.
MAX_ALTCHA_COST = int(os.getenv("METASEARCH_MAX_ALTCHA_COST", "50000"))

#: The most counters that one ALTCHA solve tries. The measured solutions were at counters
#: 233 and 293, with a one-byte key prefix.
MAX_ALTCHA_COUNTER = int(os.getenv("METASEARCH_MAX_ALTCHA_COUNTER", "20000"))


def is_mojeek_challenge(response: FetchResponse) -> bool:
    low = response.text.lower()
    return "altcha" in low or "captcha-wrap" in low


def solve_altcha(parameters: dict, max_counter: int = MAX_ALTCHA_COUNTER,
                 deadline: float = float("inf")) -> tuple[str, int] | None:
    """The derived key (hex) and the counter that solve an ALTCHA PBKDF2 challenge.

    The same search as `searx.utils.solve_altcha` of SearXNG: the first counter whose PBKDF2
    key starts with `keyPrefix`. The search stops at `max_counter`, at the `maxNumber` of the
    challenge, or at `deadline` (a `time.monotonic()` value), and then returns None.
    """
    nonce = bytes.fromhex(parameters["nonce"])
    salt = bytes.fromhex(parameters["salt"])
    prefix = bytes.fromhex(parameters["keyPrefix"])
    cost = int(parameters["cost"])
    length = int(parameters["keyLength"])
    algorithm = str(parameters["algorithm"]).split("/")[-1].replace("-", "").lower()
    limit = min(max_counter, int(parameters.get("maxNumber") or parameters.get("maxnumber")
                                 or max_counter))
    for counter in range(limit):
        if counter % 64 == 0 and time.monotonic() > deadline:
            return None
        key = hashlib.pbkdf2_hmac(algorithm, nonce + counter.to_bytes(4, "big"), salt, cost,
                                  length)
        if key[: len(prefix)] == prefix:
            return key.hex(), counter
    return None


async def _mojeek_solve(timeout: float) -> dict[str, str]:
    started = time.monotonic()
    answer = await _step("Mojeek challenge", fetch(
        "mojeek", f"{MOJEEK}/captcha/challenge", timeout=timeout, blocked=status_block))
    try:
        challenge = answer.json()
        parameters = challenge["parameters"]
    except (ValueError, KeyError, TypeError) as exc:
        raise FetchError(f"the Mojeek ALTCHA challenge is not readable: {exc}") from exc
    try:
        cost = int(parameters["cost"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FetchError(f"the Mojeek ALTCHA challenge has no cost: {exc}") from exc
    if cost > MAX_ALTCHA_COST:
        raise FetchError(f"the Mojeek ALTCHA cost {cost} is above the limit {MAX_ALTCHA_COST}")
    # The thread cannot be cancelled, so it gets the same time limit as the solve.
    solution = await asyncio.to_thread(solve_altcha, parameters, MAX_ALTCHA_COUNTER,
                                       started + SOLVE_TIMEOUT_S)
    if solution is None:
        raise FetchError("the Mojeek ALTCHA challenge has no solution within the limits")
    key, counter = solution
    payload = {"challenge": challenge,
               "solution": {"counter": counter, "derivedKey": key,
                            "time": round((time.monotonic() - started) * 1000)}}
    verify = await _step("Mojeek verify", fetch(
        "mojeek", f"{MOJEEK}/captcha/verify", method="POST", timeout=timeout,
        multipart={"altcha": base64.b64encode(json.dumps(payload).encode())},
        blocked=status_block))
    token = verify.cookies.get("chllg", "")
    if not token:
        raise FetchError(f"the Mojeek ALTCHA verify answered HTTP {verify.status} "
                         "without the chllg cookie")
    log.info("mojeek ALTCHA solved at counter %d in %.1f s", counter, time.monotonic() - started)
    return {"chllg": token}


#: The preference cookies of a Mojeek search: English interface, results from any region.
MOJEEK_PREFERENCES = {"lb": "en", "arc": "us"}


async def mojeek_page(url: str, timeout: float) -> FetchResponse:
    """The result page at `url`. A challenge answer starts one solve and one more request."""
    for attempt in (1, 2):
        seen = _MOJEEK.generation
        response = await _step("Mojeek search", fetch(
            "mojeek", url, timeout=timeout, blocked=status_block,
            cookies={**MOJEEK_PREFERENCES, **_MOJEEK.cookies}))
        if attempt == 2 or not is_mojeek_challenge(response):
            return response
        await _solve_once(_MOJEEK, seen, lambda: _mojeek_solve(timeout))
    raise AssertionError("unreachable")


# ------------------------------------------------------------------ Startpage Anubis

STARTPAGE = "https://www.startpage.com"

_STARTPAGE = SolvedCookies("Startpage Anubis")

#: The highest Anubis difficulty that is solved. Difficulty d needs 16**d hashes on
#: average: difficulty 6 takes about 2 s with 4 workers, difficulty 7 about 30 s.
MAX_ANUBIS_DIFFICULTY = int(os.getenv("METASEARCH_MAX_ANUBIS_DIFFICULTY", "7"))

#: The Anubis challenge of a page.
_ANUBIS = re.compile(r'<script id="anubis_challenge" type="application/json">(.*?)</script>', re.S)

#: The `preferences` cookie of SearXNG's Startpage engine: English, 10 results, any region.
STARTPAGE_PREFERENCES = "N1N".join(f"{k}EEE{v}" for k, v in [
    ("date_time", "world"), ("disable_family_filter", "0"), ("disable_open_in_new_window", "0"),
    ("enable_post_method", "1"), ("enable_proxy_safety_suggest", "1"), ("enable_stay_control", "1"),
    ("instant_answers", "1"), ("lang_homepage", "s/device/en/"), ("num_of_results", "10"),
    ("suggestions", "1"), ("wt_unit", "celsius"), ("language", "english"),
    ("language_ui", "english"), ("search_results_region", "all")])


def anubis_challenge(text: str) -> tuple[str, str, int] | None:
    """`(challenge id, random data, difficulty)` of an Anubis page, or None."""
    match = _ANUBIS.search(text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
        challenge = payload["challenge"]
        return str(challenge["id"]), str(challenge["randomData"]), int(payload["rules"]["difficulty"])
    except (ValueError, KeyError, TypeError):
        return None


def solve_anubis(random_data: str, difficulty: int, start: int, count: int
                 ) -> tuple[str, int] | None:
    """The SHA-256 hex digest and the nonce that solve an Anubis challenge, or None.

    A solution is a nonce whose `sha256(random_data + str(nonce))` starts with `difficulty`
    hex zeros. This searches the nonces `start` to `start + count - 1`. The loop holds the
    interpreter lock, so it runs in a worker process.
    """
    base = hashlib.sha256(random_data.encode())
    whole, half = divmod(difficulty, 2)
    zeros = bytes(whole)
    for nonce in range(start, start + count):
        hashed = base.copy()
        hashed.update(str(nonce).encode())
        digest = hashed.digest()
        if digest[:whole] == zeros and (not half or digest[whole] < 16):
            return digest.hex(), nonce
    return None


#: Worker processes for the Anubis solves. One worker hashes about 2.3 million times a
#: second here, and difficulty 6 needs 16.8 million hashes on average.
ANUBIS_WORKERS = max(1, int(os.getenv("METASEARCH_ANUBIS_WORKERS", "2")))

#: Nonces in one task of a worker, about 0.4 s of work.
ANUBIS_CHUNK = 1_000_000

#: The pool of the solve that runs now. It starts with each solve and closes after it,
#: because an idle worker holds about 90 MB and a solve is rare.
_POOL: concurrent.futures.ProcessPoolExecutor | None = None


def _stop_with_parent() -> None:
    """Make this worker process get SIGKILL when its parent stops (Linux `PR_SET_PDEATHSIG`).

    Without it, the workers of a metasearch process that got SIGKILL stay alive.
    """
    with contextlib.suppress(OSError, AttributeError):
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGKILL)


def _pool() -> concurrent.futures.ProcessPoolExecutor:
    global _POOL
    if _POOL is None:
        _POOL = concurrent.futures.ProcessPoolExecutor(
            max_workers=ANUBIS_WORKERS, mp_context=multiprocessing.get_context("spawn"),
            initializer=_stop_with_parent)
    return _POOL


def _close_pool() -> None:
    global _POOL
    if _POOL is not None:
        _POOL.shutdown(wait=False, cancel_futures=True)
        _POOL = None


async def _solve_anubis_in_pool(random_data: str, difficulty: int) -> tuple[str, int] | None:
    """Search chunks of nonces in the worker processes until one chunk has a solution.

    The search stops after 8 times the mean count of hashes, 8 * 16**difficulty.
    """
    loop = asyncio.get_running_loop()
    limit = 8 * 16 ** difficulty
    start = 0
    pending: set[asyncio.Future] = set()
    try:
        while True:
            while len(pending) < ANUBIS_WORKERS and start < limit:
                pending.add(loop.run_in_executor(_pool(), solve_anubis, random_data, difficulty,
                                                 start, ANUBIS_CHUNK))
                start += ANUBIS_CHUNK
            if not pending:
                return None
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for future in done:
                if future.result() is not None:
                    return future.result()
    finally:
        # A chunk that already runs ends by itself in about 0.4 s, and then its worker stops.
        for future in pending:
            future.cancel()
        _close_pool()


async def _startpage_solve(timeout: float) -> dict[str, str]:
    page = await _step("Startpage challenge page", fetch(
        "startpage", f"{STARTPAGE}/", timeout=timeout, blocked=status_block))
    challenge = anubis_challenge(page.text)
    if challenge is None:
        return dict(page.cookies)
    challenge_id, random_data, difficulty = challenge
    if difficulty > MAX_ANUBIS_DIFFICULTY:
        raise FetchError(f"the Startpage Anubis difficulty {difficulty} is above the limit "
                         f"{MAX_ANUBIS_DIFFICULTY}")
    started = time.monotonic()
    solution = await _solve_anubis_in_pool(random_data, difficulty)
    if solution is None:
        raise FetchError(f"the Startpage Anubis challenge (difficulty {difficulty}) has no solution")
    digest, nonce = solution
    elapsed_ms = round((time.monotonic() - started) * 1000)
    passed = await _step("Startpage Anubis pass", fetch(
        "startpage", f"{STARTPAGE}/.within.website/x/cmd/anubis/api/pass-challenge",
        params={"id": challenge_id, "response": digest, "nonce": str(nonce),
                "redir": f"{STARTPAGE}/", "elapsedTime": str(elapsed_ms)},
        cookies=page.cookies, follow_redirects=False, timeout=timeout, blocked=status_block))
    cookies = {**page.cookies, **passed.cookies}
    if passed.status >= 400 or not passed.cookies:
        raise FetchError(f"the Startpage Anubis pass answered HTTP {passed.status} "
                         "without cookies")
    log.info("startpage Anubis difficulty %d solved at nonce %d in %.1f s", difficulty, nonce,
             elapsed_ms / 1000)
    return cookies


def is_startpage_challenge(response: FetchResponse) -> bool:
    return 'id="anubis_challenge"' in response.text or "/sp/captcha" in response.url


def _startpage_sc(text: str) -> str:
    """The `sc` value of the search form of the home page, or `""`."""
    tree = HTMLParser(text)
    node = tree.css_first('form#search input[name="sc"]') or tree.css_first('input[name="sc"]')
    return (node.attributes.get("value") or "") if node is not None else ""


async def startpage_page(query: str, timeout: float) -> FetchResponse:
    """The result page of `query`: the home page for the form value `sc`, then the POST."""
    if not _STARTPAGE.cookies:
        await _solve_once(_STARTPAGE, _STARTPAGE.generation, lambda: _startpage_solve(timeout))
    for attempt in (1, 2):
        seen = _STARTPAGE.generation
        cookies = {**_STARTPAGE.cookies, "preferences": STARTPAGE_PREFERENCES}
        home = await _step("Startpage home page", fetch(
            "startpage", f"{STARTPAGE}/", timeout=timeout, cookies=cookies,
            blocked=status_block))
        form = {"query": query, "cat": "web", "t": "device", "sc": _startpage_sc(home.text),
                "with_date": "", "abd": "1", "abe": "1", "qsr": "all", "qadf": "moderate",
                "language": "english", "lui": "english", "segment": "startpage.udog"}
        response = await _step("Startpage search", fetch(
            "startpage", f"{STARTPAGE}/sp/search", method="POST", data=form, cookies=cookies,
            headers={"Origin": STARTPAGE, "Referer": f"{STARTPAGE}/"}, timeout=timeout,
            blocked=status_block))
        if attempt == 2 or not is_startpage_challenge(response):
            return response
        await _solve_once(_STARTPAGE, seen, lambda: _startpage_solve(timeout))
    raise AssertionError("unreachable")
