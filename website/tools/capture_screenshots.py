"""Drive the hoover4 UI in a real browser and capture a screenshot + snapshot per page.

Runs INSIDE `hoover4-mcp-browser`, which is the only container with a Chromium and
`nodriver` installed. It is invoked by `website/take-screenshots.sh`, which copies this
file and the ini in, runs it, and copies the output back out.

Why not the browser MCP endpoint
--------------------------------
That container's MCP router refuses internal hosts at two independent layers -- an
explicit deny-list in `urlcheck.py` and a PAC script handed to Chromium in `netfilter.py`
-- so `hoover4-website` is unreachable through it *by design*. This script launches its
own Chromium with neither, which is the same route a screenshot taken by hand would use.
It does not touch, relax or import the MCP server's filtering.

What comes out, per page
------------------------
* ``NN-name.png``          -- what a person would see
* ``NN-name.snapshot.txt`` -- a text outline of the rendered DOM: role, name and visible
  text, one element per line, indented by depth. Diffable, greppable, and the thing that
  says *why* a screenshot looks wrong.
* ``report.md``            -- the index, with each page's URL, actions, verdict and the
  reason behind it.

This is a gate, not a photographer
----------------------------------
A page fails, and the run exits non-zero, when any of these hold:

* **An error marker is in the DOM.** Every place the UI shows a user an error carries the
  class ``x-error-display`` (``frontend/src/components/error_boundary.rs``). Matching on a
  class rather than on words is what makes this reliable: "Error" is also a column header, and a
  raw ``ServerError { .. }`` debug string is not a phrase anyone can enumerate.
  Admin form errors carry ``x-error-bar`` instead and are reported as warnings, because a
  form rejecting bad input is the panel working.
* **A response was not 200** -- the main document, or any subresource. A broken server fn
  presents exactly as a ``POST /api/...`` that 500s, with a page that still looks fine.
* **A console error that no whitelist covers.** Console *warnings* are reported but never
  fail; one of them is a bad-CSS warning whose text starts with "Error:", which is why the
  report has to show warnings at all.

Per-page exemptions live in the ini: ``allow_error_markers``, ``allow_http_errors``,
``allow_console`` (a substring, one per line). Run-wide console exceptions live in
``console_whitelist.txt``; whitelisted matches still print, as warnings.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import configparser
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_BASE_URL = os.environ.get("HOOVER4_SITE_URL", "http://hoover4-website:8080")
DEFAULT_VIEWPORT = (1280, 900)
# Chromium in this image takes 5-6s to come up cold; nodriver's own budget is ~2.7s, so
# the first navigation is given room rather than the browser start.
PAGE_TIMEOUT_S = 30.0


# ---------------------------------------------------------------------------------
# The ini
# ---------------------------------------------------------------------------------

@dataclass
class Page:
    name: str
    url: str
    actions: list[tuple[str, str]] = field(default_factory=list)
    viewport: tuple[int, int] = DEFAULT_VIEWPORT
    full_page: bool = False
    settle_ms: int = 700
    # Opt-outs. A page that deliberately demonstrates a failure still has to be captured,
    # but it must say so in the ini rather than silently weakening the gate for everyone.
    allow_error_markers: bool = False
    allow_http_errors: bool = False
    allow_console: list[str] = field(default_factory=list)


def parse_pages(ini_path: Path) -> list[Page]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(ini_path, encoding="utf-8")

    defaults = parser["DEFAULT"] if parser.has_section("DEFAULT") else {}
    pages: list[Page] = []
    for name in parser.sections():
        section = parser[name]
        viewport = section.get("viewport", defaults.get("viewport", "1280x900"))
        width, _, height = viewport.partition("x")
        pages.append(
            Page(
                name=name,
                url=section.get("url", "/"),
                actions=parse_actions(section.get("actions", "")),
                viewport=(int(width), int(height)),
                full_page=section.getboolean("full_page", fallback=False),
                settle_ms=section.getint("settle_ms", fallback=700),
                allow_error_markers=section.getboolean("allow_error_markers", fallback=False),
                allow_http_errors=section.getboolean("allow_http_errors", fallback=False),
                allow_console=[
                    line.strip()
                    for line in section.get("allow_console", "").splitlines()
                    if line.strip()
                ],
            )
        )
    return pages


def parse_actions(raw: str) -> list[tuple[str, str]]:
    """One action per line: ``verb argument``. Blank lines and ``#`` comments ignored."""
    actions = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        verb, _, argument = line.partition(" ")
        actions.append((verb.strip(), argument.strip()))
    return actions


def parse_whitelist(path: Path) -> list[tuple[str, object]]:
    """Console-error exceptions: one plain substring per line, or ``re:`` + a regex.

    Returned as (source line, matcher) so the report can name the rule that excused a
    message -- a whitelist you cannot attribute is a whitelist nobody dares to shrink.
    """
    rules: list[tuple[str, object]] = []
    if not path.exists():
        return rules
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("re:"):
            rules.append((line, re.compile(line[3:].strip())))
        else:
            rules.append((line, line))
    return rules


def whitelist_hit(text: str, rules: list[tuple[str, object]]) -> str | None:
    for source, matcher in rules:
        if isinstance(matcher, str):
            if matcher in text:
                return source
        elif matcher.search(text):
            return source
    return None


# ---------------------------------------------------------------------------------
# Browser helpers
#
# Everything goes through one `eval` that returns a JSON string. That is not a style
# choice: nodriver's evaluate returns the raw value only when the expression produces a
# JSON-serialisable primitive, and anything else comes back as a RemoteObject that reads
# as "the script did not run". A JSON string round-trips predictably.
# ---------------------------------------------------------------------------------

async def js(tab, expression: str):
    payload = await tab.evaluate(
        f"JSON.stringify((() => {{ {expression} }})())", await_promise=False
    )
    if not isinstance(payload, str):
        raise RuntimeError(f"script did not return a JSON string: {payload!r}")
    return json.loads(payload)


async def click_text(tab, needle: str, scope: str = "body") -> None:
    """Click the deepest visible element whose text contains `needle`.

    `scope` changes the result: a modal renders OVER the page, and text like a
    dataset name is on screen both inside the dialog and on the result cards behind it.
    A document-wide search finds the card, clicks straight through the overlay, and the
    failure is a page that looks almost right.
    """
    found = await js(tab, """
const needle = %s;
const root = document.querySelector(%s) || document.body;
const nodes = Array.from(root.querySelectorAll('button, a, div, span, input, td, th, li, label'));
const visible = nodes.filter(n => n.offsetParent !== null);
const matches = visible.filter(n => (n.innerText || '').trim().includes(needle));
const deepest = matches.filter(n => !matches.some(m => m !== n && n.contains(m)));
const target = deepest[0] || matches[0];
// Diagnostics, not decoration: "no element containing X" is unactionable, while
// "the scope holds 0 nodes" and "the scope holds 400 nodes, none matching" point at
// two completely different mistakes.
if (!target) return {ok: false, scoped: !!document.querySelector(%s), nodes: nodes.length, visible: visible.length};
target.scrollIntoView({block: 'center'});
target.click();
return {ok: true, tag: target.tagName};
""" % (json.dumps(needle), json.dumps(scope), json.dumps(scope)))
    if not found.get("ok"):
        raise RuntimeError(
            f"no visible element containing {needle!r} inside {scope!r} "
            f"(scope found: {found.get('scoped')}, {found.get('nodes')} nodes, "
            f"{found.get('visible')} visible)"
        )


async def click_css(tab, selector: str) -> None:
    found = await js(tab, """
const el = document.querySelector(%s);
if (!el) return {ok: false};
el.scrollIntoView({block: 'center'});
el.click();
return {ok: true};
""" % json.dumps(selector))
    if not found.get("ok"):
        raise RuntimeError(f"no element matching {selector!r}")


async def type_css(tab, selector: str, text: str) -> None:
    """Set an input's value the way Dioxus will notice.

    Assigning `.value` directly is invisible to the framework: React and Dioxus both read
    through the prototype's setter and listen for a bubbling `input` event. Setting the
    property without the setter updates the DOM and not the signal, which looks exactly
    like a page that ignored you.
    """
    result = await js(tab, """
const el = document.querySelector(%s);
if (!el) return {ok: false};
const setter = Object.getOwnPropertyDescriptor(
    el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype
                              : window.HTMLInputElement.prototype, 'value').set;
el.focus();
setter.call(el, %s);
el.dispatchEvent(new Event('input', {bubbles: true}));
el.dispatchEvent(new Event('change', {bubbles: true}));
return {ok: true, value: el.value};
""" % (json.dumps(selector), json.dumps(text)))
    if not result.get("ok"):
        raise RuntimeError(f"no input matching {selector!r}")


async def press_enter(tab) -> None:
    """A real key event. The home box submits on `onkeypress`, which a synthetic
    `KeyboardEvent` from JS does not trigger in the same way. CDP is the honest route."""
    import nodriver.cdp.input_ as input_cdp

    for kind in ("keyDown", "char", "keyUp"):
        await tab.send(
            input_cdp.dispatch_key_event(
                type_=kind,
                key="Enter",
                code="Enter",
                windows_virtual_key_code=13,
                native_virtual_key_code=13,
                text="\r" if kind == "char" else None,
            )
        )


async def wait_text(tab, needle: str, scope: str = "body", timeout: float = PAGE_TIMEOUT_S) -> None:
    """Wait for text to appear, optionally only inside `scope`.

    The scoped form is what a modal needs. Its panes load over the network while the page
    behind it already shows the same words, so an unscoped wait is satisfied instantly by
    the wrong element and the click that follows lands on an empty pane.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hit = await js(tab, """
const root = document.querySelector(%s);
return {found: !!root && (root.innerText || '').includes(%s)};
""" % (json.dumps(scope), json.dumps(needle)))
        if hit.get("found"):
            return
        await asyncio.sleep(0.25)
    raise RuntimeError(f"timed out waiting for text {needle!r} inside {scope!r}")


async def wait_css(tab, selector: str, timeout: float = PAGE_TIMEOUT_S) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hit = await js(tab, "return {found: !!document.querySelector(%s)};" % json.dumps(selector))
        if hit.get("found"):
            return
        await asyncio.sleep(0.25)
    raise RuntimeError(f"timed out waiting for selector {selector!r}")


async def run_action(tab, base_url: str, verb: str, argument: str) -> None:
    if verb == "goto":
        await tab.get(base_url + argument)
    elif verb == "wait_text":
        await wait_text(tab, argument)
    elif verb == "wait_text_in":
        scope, _, needle = argument.partition("::")
        await wait_text(tab, needle.strip(), scope.strip())
    elif verb == "wait_css":
        await wait_css(tab, argument)
    elif verb == "click_text":
        await click_text(tab, argument)
    elif verb == "click_text_in":
        scope, _, needle = argument.partition("::")
        await click_text(tab, needle.strip(), scope.strip())
    elif verb == "click_css":
        await click_css(tab, argument)
    elif verb == "type_css":
        selector, _, text = argument.partition("::")
        await type_css(tab, selector.strip(), text.strip())
    elif verb == "press_enter":
        await press_enter(tab)
    elif verb == "sleep":
        await asyncio.sleep(int(argument) / 1000.0)
    elif verb == "scroll":
        await js(tab, f"window.scrollBy(0, {int(argument)}); return {{ok: true}};")
    elif verb == "hover_css":
        await js(tab, """
const el = document.querySelector(%s);
if (!el) return {ok: false};
el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
el.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
return {ok: true};
""" % json.dumps(argument))
    elif verb == "eval":
        await js(tab, argument)
    else:
        raise RuntimeError(f"unknown action {verb!r}")


# ---------------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------------

SNAPSHOT_JS = r"""
const out = [];
const skip = new Set(['SCRIPT', 'STYLE', 'SVG', 'PATH', 'LINK', 'META', 'HEAD']);
function label(el) {
    const bits = [el.tagName.toLowerCase()];
    if (el.id) bits.push('#' + el.id);
    const role = el.getAttribute('role'); if (role) bits.push('[role=' + role + ']');
    const aria = el.getAttribute('aria-label'); if (aria) bits.push('[label=' + aria + ']');
    const title = el.getAttribute('title'); if (title) bits.push('[title=' + title.slice(0, 120) + ']');
    if (el.tagName === 'INPUT') {
        bits.push('[type=' + (el.type || '') + ']');
        if (el.value) bits.push('[value=' + el.value.slice(0, 60) + ']');
        if (el.placeholder) bits.push('[placeholder=' + el.placeholder + ']');
    }
    if (el.tagName === 'A' && el.getAttribute('href')) bits.push('[href=' + el.getAttribute('href').slice(0, 120) + ']');
    return bits.join('');
}
function own(el) {
    // Text belonging to this element and not to a child, so a nested tree does not
    // repeat every leaf's words at every level above it.
    let text = '';
    for (const node of el.childNodes) {
        if (node.nodeType === 3) text += node.textContent;
    }
    return text.replace(/\s+/g, ' ').trim();
}
function walk(el, depth) {
    if (skip.has(el.tagName)) return;
    if (el.offsetParent === null && el.tagName !== 'BODY' && getComputedStyle(el).position !== 'fixed') return;
    const text = own(el);
    const line = '  '.repeat(depth) + label(el) + (text ? '  "' + text.slice(0, 200) + '"' : '');
    out.push(line);
    for (const child of el.children) walk(child, depth + 1);
}
walk(document.body, 0);
return {title: document.title, url: location.href, lines: out};
"""


async def snapshot(tab) -> dict:
    return await js(tab, SNAPSHOT_JS)


async def screenshot(tab, full_page: bool) -> bytes:
    import nodriver.cdp.page as page_cdp

    data = await tab.send(
        page_cdp.capture_screenshot(format_="png", capture_beyond_viewport=full_page)
    )
    return base64.b64decode(data) if isinstance(data, str) else bytes(data)


# ---------------------------------------------------------------------------------
# The three gates
# ---------------------------------------------------------------------------------

# Installed as a new-document script, so it is in place before the WASM bundle boots and
# catches a panic during startup -- the loudest failure there is, and the one a hook
# installed after the page settles would miss entirely.
CONSOLE_HOOK_JS = r"""
window.__h4_console = window.__h4_console || [];
if (!window.__h4_console_hooked) {
    window.__h4_console_hooked = true;
    for (const level of ['error', 'warn']) {
        const original = console[level];
        console[level] = function (...args) {
            window.__h4_console.push({level: level, text: args.map(String).join(' ')});
            return original.apply(this, args);
        };
    }
    window.addEventListener('error', e =>
        window.__h4_console.push({level: 'error', text: 'uncaught: ' + e.message}));
    window.addEventListener('unhandledrejection', e =>
        window.__h4_console.push({level: 'error', text: 'unhandled rejection: ' + e.reason}));
}
"""

MARKER_JS = r"""
function texts(selector) {
    const all = Array.from(document.querySelectorAll(selector));
    // An error box nested inside another would otherwise be counted, and quoted, twice.
    const outer = all.filter(n => !all.some(m => m !== n && m.contains(n)));
    return outer.map(n => (n.innerText || n.textContent || '').replace(/\s+/g, ' ').trim());
}
return {displays: texts('.x-error-display'), bars: texts('.x-error-bar')};
"""


@dataclass
class NetworkLog:
    """Per-page HTTP record, cleared before each navigation."""

    document: tuple[str, int] | None = None
    bad: list[str] = field(default_factory=list)
    #: server-function name -> requests issued while this page was being captured.
    #: Not a gate (a page that legitimately loads more is not a failure) but the number
    #: that makes a query storm visible: a tree that fetched per row rather than per
    #: expansion showed up here as tens of identical calls before it showed up anywhere
    #: else.
    api_calls: dict[str, int] = field(default_factory=dict)

    def clear(self) -> None:
        self.document = None
        self.bad.clear()
        self.api_calls.clear()

    def api_total(self) -> int:
        return sum(self.api_calls.values())

    def api_summary(self) -> str:
        if not self.api_calls:
            return "0"
        parts = ", ".join(
            f"{name} x{count}"
            for name, count in sorted(self.api_calls.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        return f"{self.api_total()} ({parts})"


def api_function_name(url: str) -> str | None:
    """The server-function name in a `/api/<name><hash>` URL, or None.

    Dioxus mounts server functions at the function name followed by a decimal content
    hash, so the trailing digits are stripped to keep one bucket per function across
    rebuilds.
    """
    path = urlsplit(url).path
    if not path.startswith("/api/"):
        return None
    segment = path[len("/api/"):].split("/")[0]
    return segment.rstrip("0123456789") or segment


async def watch_network(tab) -> NetworkLog:
    """Record response statuses through CDP for the life of the tab.

    Resource-timing entries would be simpler, but they do not exist for a request that
    never got a response, and "the server fn connection died" is a failure worth naming.
    """
    import nodriver.cdp.network as network_cdp

    log = NetworkLog()
    # requestId -> "METHOD url", so a failure line says which call broke rather than
    # quoting an opaque id. ResponseReceived carries no method of its own.
    sent: dict[str, str] = {}

    def on_request(event, _connection=None):
        sent[str(event.request_id)] = f"{event.request.method} {event.request.url}"
        name = api_function_name(event.request.url)
        if name is not None:
            log.api_calls[name] = log.api_calls.get(name, 0) + 1

    def on_response(event, _connection=None):
        if event.type_ is network_cdp.ResourceType.DOCUMENT and log.document is None:
            # The top-level navigation, reported on its own line; everything after it is
            # a subresource and would otherwise say the same thing twice.
            log.document = (event.response.url, event.response.status)
            return
        if event.response.status >= 400:
            label = sent.get(str(event.request_id), f"GET {event.response.url}")
            log.bad.append(f"HTTP {event.response.status} on {label}")

    def on_failed(event, _connection=None):
        if event.canceled:
            return
        label = sent.get(str(event.request_id), "(unknown request)")
        log.bad.append(f"request failed ({event.error_text}) on {label}")

    tab.add_handler(network_cdp.RequestWillBeSent, on_request)
    tab.add_handler(network_cdp.ResponseReceived, on_response)
    tab.add_handler(network_cdp.LoadingFailed, on_failed)
    await tab.send(network_cdp.enable())
    return log


def judge(
    page: Page,
    markers: dict,
    console: list[dict],
    network: NetworkLog,
    whitelist: list[tuple[str, object]],
) -> tuple[list[str], list[str]]:
    """Turn everything observed on one page into (failures, warnings)."""
    problems: list[str] = []
    warnings: list[str] = []

    for text in markers.get("displays", []):
        line = f"error marker: {text[:300] or '(empty)'}"
        (warnings if page.allow_error_markers else problems).append(line)
    for text in markers.get("bars", []):
        warnings.append(f"admin error bar: {text[:300] or '(empty)'}")

    if network.document is not None and network.document[1] != 200:
        url, status = network.document
        line = f"main document returned HTTP {status} ({url})"
        (warnings if page.allow_http_errors else problems).append(line)
    for line in network.bad:
        (warnings if page.allow_http_errors else problems).append(line)

    for entry in console:
        text = entry.get("text", "")
        if entry.get("level") != "error":
            warnings.append(f"console warning: {text[:300]}")
            continue
        excused = whitelist_hit(text, whitelist) or next(
            (rule for rule in page.allow_console if rule in text), None
        )
        if excused:
            warnings.append(f"console error (allowed by {excused!r}): {text[:300]}")
        else:
            problems.append(f"console error: {text[:300]}")

    return problems, warnings


# ---------------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------------

# `dx serve` shows this while it is recompiling, and KEEPS SERVING THE PREVIOUS BUNDLE
# until it finishes. A run started right after an edit therefore screenshots the old code
# and looks like the change did nothing, which is exactly how an hour goes missing. It
# also puts a dev overlay in the corner of every image.
DEV_REBUILD_TIMEOUT_S = 600.0

# A page that never finishes loading has to be a failure, not a stalled run. Without this
# the whole gate hangs on the first request the server does not answer -- and a server fn
# that never returns is exactly the class of defect this run exists to find.
PAGE_BUDGET_S = 180.0


async def wait_for_dev_rebuild(tab) -> None:
    deadline = time.monotonic() + DEV_REBUILD_TIMEOUT_S
    announced = False
    while time.monotonic() < deadline:
        # The toast keeps its text after the build finishes and is hidden by collapsing to
        # zero height, so the text alone reads as "rebuilding forever", which is a ten
        # minute wait per run, or a whole run refused, for a banner nobody can see.
        state = await js(tab, """
const toast = document.querySelector('#__dx-toast');
const text = toast ? (toast.innerText || '') : '';
const showing = !!toast && toast.getBoundingClientRect().height > 0;
return {rebuilding: showing && (text.includes('being rebuilt') || text.includes('rebuild'))};
""")
        if not state.get("rebuilding"):
            if announced:
                # Give the fresh bundle a moment to boot before the first action.
                await asyncio.sleep(3.0)
            return
        if not announced:
            print("    waiting for the dev server to finish rebuilding…", flush=True)
            announced = True
        await asyncio.sleep(3.0)
        await tab.reload()
        await asyncio.sleep(1.0)
    raise RuntimeError(f"dx serve was still rebuilding after {DEV_REBUILD_TIMEOUT_S:g}s")


async def capture_all(
    pages: list[Page],
    base_url: str,
    out_dir: Path,
    whitelist: list[tuple[str, object]],
) -> int:
    import nodriver
    import nodriver.cdp.page as page_cdp

    browser = await nodriver.start(
        headless=True,
        sandbox=False,
        browser_args=[
            "--no-sandbox",
            # /dev/shm is small in containers and Chromium fills it on content-heavy
            # pages; compose raises it but the flag is free insurance.
            "--disable-dev-shm-usage",
            "--disable-gpu",
            f"--window-size={DEFAULT_VIEWPORT[0]},{DEFAULT_VIEWPORT[1]}",
        ],
    )
    failed_pages: list[str] = []
    warned_pages: list[str] = []
    report: list[str] = [
        "# Screenshot run",
        "",
        f"Site: `{base_url}`  |  pages: {len(pages)}",
        "",
    ]
    try:
        tab = await browser.get(base_url + "/")
        network = await watch_network(tab)
        await tab.send(page_cdp.add_script_to_evaluate_on_new_document(CONSOLE_HOOK_JS))
        await wait_for_dev_rebuild(tab)
        for index, page in enumerate(pages):
            stem = f"{index:02d}-{page.name}"
            print(f"[{index + 1}/{len(pages)}] {stem}", flush=True)
            try:
                async def capture() -> tuple[dict, dict, list]:
                    await tab.set_window_size(0, 0, page.viewport[0], page.viewport[1])
                    network.clear()
                    await tab.get(base_url + page.url)
                    # The SPA boots into an empty shell; wait for it to render something
                    # before the actions start looking for elements.
                    await wait_css(tab, "body *")
                    await asyncio.sleep(page.settle_ms / 1000.0)
                    for verb, argument in page.actions:
                        await run_action(tab, base_url, verb, argument)
                    await asyncio.sleep(page.settle_ms / 1000.0)

                    shot = await screenshot(tab, page.full_page)
                    (out_dir / f"{stem}.png").write_bytes(shot)
                    snap = await snapshot(tab)
                    markers = await js(tab, MARKER_JS)
                    # The hook is a new-document script, but a page reached by an SPA
                    # route change never got one; re-running it is idempotent and never
                    # clears what has already been collected.
                    await js(tab, CONSOLE_HOOK_JS + "\nreturn {ok: true};")
                    console = await js(tab, "return {entries: window.__h4_console || []};")
                    return snap, markers, console.get("entries", [])

                snap, markers, entries = await asyncio.wait_for(capture(), PAGE_BUDGET_S)
                problems, warnings = judge(page, markers, entries, network, whitelist)

                verdict = "FAILED" if problems else "ok"
                lines = [
                    f"# {stem}",
                    f"url:     {snap.get('url', '')}",
                    f"title:   {snap.get('title', '')}",
                    f"actions: {'; '.join(f'{v} {a}' for v, a in page.actions) or '(none)'}",
                    f"api calls: {network.api_summary()}",
                    f"verdict: {verdict}",
                    "",
                    "## failures",
                    *(problems or ["(none)"]),
                    "",
                    "## warnings",
                    *(warnings or ["(none)"]),
                    "",
                    "## rendered outline",
                    *snap.get("lines", []),
                ]
                (out_dir / f"{stem}.snapshot.txt").write_text("\n".join(lines), encoding="utf-8")

                if problems:
                    failed_pages.append(stem)
                    print(f"    FAILED: {'; '.join(problems)[:400]}", flush=True)
                    report.append(f"- `{stem}` — `{page.url}` — **FAILED**")
                elif warnings:
                    warned_pages.append(stem)
                    report.append(
                        f"- `{stem}` — `{page.url}` — ok ({len(warnings)} warning(s))"
                    )
                else:
                    report.append(f"- `{stem}` — `{page.url}` — ok")
                report.append(f"    - api calls: {network.api_summary()}")
                for problem in problems:
                    report.append(f"    - **{problem}**")
                for warning in warnings:
                    report.append(f"    - warn: {warning}")
            except Exception as exc:  # noqa: BLE001
                reason = (
                    f"the page did not finish within {PAGE_BUDGET_S:g}s"
                    if isinstance(exc, asyncio.TimeoutError)
                    else str(exc)
                )
                failed_pages.append(stem)
                print(f"    FAILED: {reason}", flush=True)
                report.append(f"- `{stem}` — `{page.url}` — **FAILED: {reason}**")
                try:
                    await tab.send(page_cdp.stop_loading())
                except Exception:  # noqa: BLE001
                    pass
                # Still take a picture: the screenshot of a failed step is usually the
                # fastest explanation of why the step failed.
                try:
                    (out_dir / f"{stem}.FAILED.png").write_bytes(await screenshot(tab, False))
                except Exception:  # noqa: BLE001
                    pass
    finally:
        try:
            browser.stop()
        except Exception:  # noqa: BLE001
            pass

    report.append("")
    report.append(
        f"{len(pages) - len(failed_pages)}/{len(pages)} pages passed; "
        f"{len(failed_pages)} failed, {len(warned_pages)} passed with warnings."
    )
    if failed_pages:
        report.append("")
        report.append("## failed pages")
        report.extend(f"- `{stem}`" for stem in failed_pages)
    (out_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return len(failed_pages)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ini", default="/tmp/h4shots/screenshots.ini")
    parser.add_argument("--out", default="/tmp/h4shots/out")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--only", default="", help="capture only sections whose name contains this")
    parser.add_argument("--console-whitelist", default="/tmp/h4shots/console_whitelist.txt")
    args = parser.parse_args()

    out_dir = Path(args.out)
    # Deleting here rather than in the shell wrapper: the run that produced the files is
    # the run that knows they are stale, and a half-deleted directory from a killed shell
    # is worse than none.
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    pages = parse_pages(Path(args.ini))
    if args.only:
        pages = [p for p in pages if args.only in p.name]
    if not pages:
        print("no pages selected", file=sys.stderr)
        return 2

    whitelist = parse_whitelist(Path(args.console_whitelist))
    failures = asyncio.run(
        capture_all(pages, args.base_url.rstrip("/"), out_dir, whitelist)
    )
    print(
        f"{len(pages) - failures}/{len(pages)} pages passed the gate; "
        f"output in {out_dir} (see report.md)"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
