"""`POST /internal/fetch`: one HTTP GET through the special session `_metasearch`.

The metasearch server sends browser-backed source requests here.
Each request uses Chromium. It is a route of this server, not an MCP tool, so no MCP client sees it.

How one request runs:

1. The URL with its query `params` must pass :func:`.urlcheck.check_url`.
2. The request takes one slot of `_metasearch` and one new tab. The wait for the slot counts
   against `timeout_s`.
3. The tab navigates to the URL. The CDP `Network` domain reports the response of the main
   document: its status, its final URL after redirects and its headers. When the document
   has loaded, `Network.getResponseBody` gives the raw body. The tab then closes.

Why a navigation with the `Network` domain:

* A navigation is the request a person's browser makes, with the browser's own user agent,
  client hints and cookies. A source that tells a script from a browser sees a browser.
* `Network.getResponseBody` returns the body as the server sent it, also for a JSON API
  and for a status such as 202, 429 or 500. The text that a page shows is not that body: a
  JSON response is shown inside an HTML document, and an empty error response is replaced
  by an error page of Chromium.
* A `fetch()` call from a script in the page is a cross-origin request from `about:blank`.
  CORS hides the body of most such responses. The `Fetch` domain can also give the body,
  but it holds each request until the client continues it, which adds a step for every
  request of the page.

The page scripts run until the tab closes. The result does not wait for them, and it does
not wait for a bot check to clear.

Headers: the browser sends its own headers. Of the caller's headers, only
`Accept-Language` is sent (with `Network.setExtraHTTPHeaders`), and `Referer` becomes the
referrer of the navigation. A `User-Agent` or any other header is dropped, because a
second user agent string that differs from the client hints of the browser marks the
request as a script. Chromium keeps its own `Accept` header for a navigation, also when the
extra headers name one, so an `Accept` header of the caller is dropped too.

A navigation that Chromium reports as failed with a response, for example a 404 or 429
with an empty body, shows an error page of Chromium. Its body is not the server's body,
so the result has the status and an empty body.

`body` chooses what the answer holds:

* `raw` (the default): the response body of the first main document, as described above.
* `dom`: `document.documentElement.outerHTML` of the last main document, after the DOM had
  no new main document for `DOM_QUIET_S` and its load ended. The status, the URL and the
  content type are those of that last document. Use it for a page that replaces itself with
  a script. Google answers the first search of a new browser with a page whose script
  loads the same search again. That new document commits before `Network.getResponseBody`
  is sent, and Chromium then no longer holds the body of the first one. The `raw` answer
  is then the error "the body is not available: No resource with given identifier found".
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from dataclasses import asdict, dataclass
from urllib.parse import urlencode, urlsplit, urlunsplit

from browser_use_server.special_browser import SlotWaitTimeout
from browser_use_server.urlcheck import UrlNotAllowed, check_url

log = logging.getLogger(__name__)

#: The longest `timeout_s` of one request. A larger value is reduced to this.
MAX_TIMEOUT_S = float(os.getenv("METASEARCH_FETCH_MAX_TIMEOUT_S", "60"))

#: The default `timeout_s`.
DEFAULT_TIMEOUT_S = 15.0

#: A body larger than this is cut to this size, and `truncated` is true.
MAX_BODY_BYTES = int(os.getenv("METASEARCH_FETCH_MAX_BODY_BYTES", str(8 * 1024 * 1024)))

#: How long after its deadline a request still waits for its answer. The steps before the
#: navigation, such as the creation of the tab, have no deadline of their own.
ANSWER_GRACE_S = 1.0

#: The caller headers that the browser sends. Lower case.
PASSED_HEADERS = ("accept-language",)

#: The statuses of a response without a body. `Network.getResponseBody` can fail for them.
BODYLESS_STATUSES = frozenset({204, 304})

#: The values of `body`. See the module text.
RAW_BODY = "raw"
DOM_BODY = "dom"
BODY_KINDS = (RAW_BODY, DOM_BODY)

#: With `body` `dom`, the main frame must have no new document for this long.
DOM_QUIET_S = 1.0

#: How often the `dom` wait looks at the main frame.
DOM_POLL_S = 0.2

#: The values of `error_kind`.
REFUSED = "refused"
NO_SLOT = "no_slot"
TIMEOUT = "timeout"
NAVIGATION = "navigation"
BROWSER = "browser"


@dataclass
class FetchOutcome:
    """The answer of `POST /internal/fetch`. `error` is empty when a response arrived."""

    status: int = 0
    url: str = ""
    content_type: str = ""
    body: str = ""
    truncated: bool = False
    error: str = ""
    error_kind: str = ""
    #: Seconds that the request waited for a free slot.
    slot_wait_s: float = 0.0
    #: Seconds from the slot to a tab that answers: a cold start of the browser, the
    #: creation of the tab and the watchdog probe.
    tab_open_s: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def build_url(url: str, params: dict | None) -> str:
    """`url` with `params` added to its query, in the order given."""
    if not params:
        return url
    parts = urlsplit(url)
    extra = urlencode([(str(k), str(v)) for k, v in params.items() if v is not None])
    query = f"{parts.query}&{extra}" if parts.query and extra else (parts.query or extra)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def passed_headers(headers: dict | None) -> tuple[dict[str, str], str]:
    """`(headers the browser sends, referrer)` from the caller's headers. See the module text."""
    sent: dict[str, str] = {}
    referrer = ""
    for name, value in (headers or {}).items():
        key = str(name).strip().lower()
        if key in PASSED_HEADERS:
            sent[key.title()] = str(value)
        elif key == "referer":
            referrer = str(value)
    return sent, referrer


async def fetch(pool, url: str, params: dict | None = None, headers: dict | None = None,
                timeout_s: float = DEFAULT_TIMEOUT_S, body: str = RAW_BODY) -> FetchOutcome:
    """GET `url` in a tab of `pool`. Never raises, except on cancellation.

    `timeout_s` is the deadline of the whole request, counted from now. The wait for a
    slot and a cold start of the browser count against it. The answer comes before the
    tab closes, and the slot is free when the close ends. The answer comes at most
    `ANSWER_GRACE_S` after the deadline, also when the browser does not answer. `body` is
    `RAW_BODY` or `DOM_BODY`. See the module text.
    """
    timeout_s = min(max(0.1, float(timeout_s)), MAX_TIMEOUT_S)
    asked = time.monotonic()
    deadline = asked + timeout_s
    full = url
    try:
        full = build_url(url, params)
        # The check resolves the host. A slow resolver must not stop the event loop.
        await asyncio.to_thread(check_url, full)
    except (UrlNotAllowed, ValueError) as exc:  # a refusal, or a URL that does not parse
        return FetchOutcome(url=full, error=f"refused: {exc}", error_kind=REFUSED)
    sent, referrer = passed_headers(headers)
    answer: asyncio.Future = asyncio.get_running_loop().create_future()
    task = asyncio.ensure_future(
        _lease_and_fetch(pool, full, sent, referrer, asked, deadline, timeout_s, answer,
                         body))
    # The task closes the tab after the answer is set. A reference keeps it alive until then.
    _CLOSING.add(task)
    task.add_done_callback(_CLOSING.discard)
    # When the caller goes away, the task still ends by the deadline and closes its tab.
    try:
        return await asyncio.wait_for(asyncio.shield(answer),
                                      max(0.0, deadline - time.monotonic()) + ANSWER_GRACE_S)
    except asyncio.CancelledError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    except asyncio.TimeoutError:
        log.warning("internal fetch of %s: no answer %gs after the deadline", full,
                    ANSWER_GRACE_S)
        return FetchOutcome(url=full, error_kind=TIMEOUT, error=(
            f"no answer within {timeout_s:g} s: the {pool.name} browser did not open a tab "
            "or did not answer"))


#: The fetch tasks that are still running, mostly to close their tabs.
_CLOSING: set[asyncio.Task] = set()


async def _lease_and_fetch(pool, url: str, headers: dict[str, str], referrer: str,
                           asked: float, deadline: float, timeout_s: float,
                           answer: asyncio.Future, body: str = RAW_BODY) -> None:
    """Fetch `url` in a leased tab and set `answer`, then close the tab.

    The answer is set before the tab closes. A close can take up to
    `special_browser.CLOSE_TIMEOUT_S` in a busy browser, and the caller must get the answer
    by its deadline.
    """
    def give(outcome: FetchOutcome) -> None:
        if not answer.done():
            answer.set_result(outcome)

    try:
        async with pool.lease(deadline) as lease:
            outcome = await _fetch_in(lease, url, headers, referrer, deadline, body)
            outcome.slot_wait_s = round(lease.slot_wait_s, 3)
            outcome.tab_open_s = round(lease.tab_open_s, 3)
            if outcome.error_kind == TIMEOUT:
                outcome.error = (f"no complete response within {timeout_s:g} s, after a wait "
                                 f"of {lease.slot_wait_s:.1f} s for a free tab and "
                                 f"{lease.tab_open_s:.1f} s to open the tab")
            give(outcome)
    except SlotWaitTimeout:
        give(FetchOutcome(
            url=url, error_kind=NO_SLOT, slot_wait_s=round(time.monotonic() - asked, 3),
            error=(f"no free tab of the {pool.name} browser within {timeout_s:g} s: all "
                   f"{pool.slots} slots were in use"),
        ))
    except asyncio.TimeoutError:
        give(FetchOutcome(url=url, error_kind=TIMEOUT,
                          error=f"the {pool.name} browser did not start within {timeout_s:g} s"))
    except asyncio.CancelledError:
        give(FetchOutcome(url=url, error_kind=BROWSER, error="the request was cancelled"))
        raise
    except Exception as exc:  # noqa: BLE001 - a browser that did not start or is gone
        log.warning("internal fetch of %s failed: %s", url, exc)
        give(FetchOutcome(url=url, error_kind=BROWSER, error=f"no tab could be opened: {exc}"))


async def _fetch_in(lease, url: str, headers: dict[str, str], referrer: str,
                    deadline: float, body: str = RAW_BODY) -> FetchOutcome:
    """Run `_navigate` in the tab of `lease` until the deadline or a stop of the browser."""
    reading = asyncio.ensure_future(_navigate(lease.tab, url, headers, referrer, body))
    died = asyncio.ensure_future(lease.died.wait())
    try:
        await asyncio.wait({reading, died}, timeout=max(0.0, deadline - time.monotonic()),
                           return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (reading, died):
            if not task.done():
                task.cancel()
    if reading.done() and not reading.cancelled():
        return reading.result()
    if died.done() and not died.cancelled():
        return FetchOutcome(url=url, error_kind=BROWSER,
                            error="the browser stopped during the request")
    return FetchOutcome(url=url, error_kind=TIMEOUT,
                        error="no complete response before the deadline")


async def _navigate(tab, url: str, headers: dict[str, str], referrer: str,
                    body: str = RAW_BODY) -> FetchOutcome:
    """Navigate `tab` to `url` and return the main document's response, or its DOM with
    `body` `dom`. Never raises, except on cancellation."""
    from nodriver import cdp

    responses: dict[str, object] = {}
    documents: list[tuple[str, str, object]] = []
    ended: dict[str, str] = {}
    changed = asyncio.Event()

    def on_response(event, _tab=None) -> None:
        request_id = str(event.request_id)
        responses[request_id] = event.response
        if event.type_ == cdp.network.ResourceType.DOCUMENT:
            documents.append((request_id, str(event.frame_id or ""), event.response))
        changed.set()

    def on_finished(event, _tab=None) -> None:
        ended[str(event.request_id)] = ""
        changed.set()

    def on_failed(event, _tab=None) -> None:
        ended[str(event.request_id)] = str(event.error_text or "the request failed")
        changed.set()

    try:
        tab.add_handler(cdp.network.ResponseReceived, on_response)
        tab.add_handler(cdp.network.LoadingFinished, on_finished)
        tab.add_handler(cdp.network.LoadingFailed, on_failed)
        await tab.send(cdp.network.enable(max_resource_buffer_size=MAX_BODY_BYTES * 2,
                                          max_total_buffer_size=MAX_BODY_BYTES * 4))
        if headers:
            await tab.send(cdp.network.set_extra_http_headers(cdp.network.Headers(headers)))
        frame_id, loader_id, error_text, is_download = await tab.send(
            cdp.page.navigate(url, referrer=referrer or None))
    except Exception as exc:  # noqa: BLE001 - CDP raises a protocol error per failure
        return FetchOutcome(url=url, error_kind=NAVIGATION, error=f"navigation failed: {exc}")

    # A navigation request has the id of its loader. Match the frame when it does not.
    request_id = str(loader_id) if loader_id else ""

    def main_document() -> tuple[str, object] | None:
        if request_id and request_id in responses:
            return request_id, responses[request_id]
        for rid, frame, response in documents:
            if frame == str(frame_id):
                return rid, response
        return None

    if is_download:
        return FetchOutcome(url=url, error_kind=NAVIGATION,
                            error="the URL starts a download and shows no document")
    if error_text and main_document() is None:
        return FetchOutcome(url=url, error_kind=NAVIGATION,
                            error=f"navigation failed: {error_text}")

    while True:
        found = main_document()
        if found is not None and found[0] in ended:
            break
        changed.clear()
        await changed.wait()

    rid, response = found
    outcome = FetchOutcome(
        status=int(getattr(response, "status", 0) or 0),
        url=str(getattr(response, "url", "") or url),
        content_type=_content_type(response),
    )
    if error_text:
        # The tab shows an error page of Chromium. See the module text.
        return outcome
    if body == DOM_BODY:
        return await _dom(tab, url, str(frame_id), documents, ended, outcome)
    try:
        body, encoded = await tab.send(cdp.network.get_response_body(cdp.network.RequestId(rid)))
    except Exception as exc:  # noqa: BLE001 - an empty error response has no body
        log.debug("no body for %s: %s", url, exc)
        if ended.get(rid):
            outcome.error_kind = NAVIGATION
            outcome.error = f"the response body did not arrive: {ended[rid]}"
        elif outcome.status not in BODYLESS_STATUSES:
            # Chromium no longer holds the body, for example because it was larger than
            # the buffer of the tab. An empty body would read as an empty answer.
            outcome.error_kind = NAVIGATION
            outcome.error = f"the body is not available: {exc}"
        return outcome
    outcome.body, outcome.truncated = _text(body, encoded, getattr(response, "charset", ""))
    return outcome


async def _dom(tab, url: str, frame: str, documents: list, ended: dict,
               outcome: FetchOutcome) -> FetchOutcome:
    """The DOM of the last main document of `frame`, after it is quiet. See the module text."""
    seen, quiet_since = 0, time.monotonic()
    while True:
        main = [(rid, response) for rid, owner, response in documents if owner == frame]
        if len(main) != seen:
            seen, quiet_since = len(main), time.monotonic()
        if main and main[-1][0] in ended and time.monotonic() - quiet_since >= DOM_QUIET_S:
            if await _evaluate(tab, "document.readyState") == "complete":
                break
        await asyncio.sleep(DOM_POLL_S)
    rid, response = main[-1]
    outcome.status = int(getattr(response, "status", 0) or 0)
    outcome.url = str(getattr(response, "url", "") or url)
    outcome.content_type = _content_type(response)
    if ended.get(rid):
        outcome.error_kind = NAVIGATION
        outcome.error = f"the last document did not arrive: {ended[rid]}"
        return outcome
    html = await _evaluate(
        tab, "document.documentElement ? document.documentElement.outerHTML : ''")
    if html is None:
        outcome.error_kind = NAVIGATION
        outcome.error = "the DOM of the document could not be read"
        return outcome
    outcome.body, outcome.truncated = _text(html, False, "")
    log.debug("dom of %s after %d main documents", url, len(main))
    return outcome


async def _evaluate(tab, expression: str):
    """The value of `expression` in the page, or None when the page did not answer."""
    from nodriver import cdp

    try:
        remote, exception = await tab.send(
            cdp.runtime.evaluate(expression=expression, return_by_value=True))
    except Exception:  # noqa: BLE001 - the context is replaced during a navigation
        return None
    return None if exception else getattr(remote, "value", None)


def _content_type(response) -> str:
    for name, value in dict(getattr(response, "headers", None) or {}).items():
        if str(name).lower() == "content-type":
            return str(value)
    return str(getattr(response, "mime_type", "") or "")


def _text(body: str, encoded: bool, charset: str) -> tuple[str, bool]:
    """The body as text, cut to `MAX_BODY_BYTES`. A base64 body is decoded with `charset`."""
    if encoded:
        data = base64.b64decode(body or "")
        truncated = len(data) > MAX_BODY_BYTES
        try:
            text = data[:MAX_BODY_BYTES].decode(charset or "utf-8", "replace")
        except LookupError:
            text = data[:MAX_BODY_BYTES].decode("utf-8", "replace")
        return text, truncated
    data = (body or "").encode("utf-8")
    if len(data) <= MAX_BODY_BYTES:
        return body or "", False
    return data[:MAX_BODY_BYTES].decode("utf-8", "ignore"), True
