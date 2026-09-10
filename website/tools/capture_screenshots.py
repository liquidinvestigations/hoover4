"""Drive the hoover4 UI in a real browser and capture PNGs and DOM snapshots for a scenario list.

Runs INSIDE `hoover4-mcp-browser`, which is the only container with a Chromium and
`nodriver` installed. It is invoked by `website/take-screenshots.sh`, which copies this
file and the scenario files in, runs it, and copies the output back out. Read
`website/take-screenshots.sh` first: it resolves the target, the credentials, the output
run directory and the run lock, and passes the results here through arguments and
environment variables. This file never reads ``TEST_LOGIN.env`` itself. The wrapper exports
``HOOVER4_TEST_USERNAME`` and ``HOOVER4_TEST_PASSWORD`` and passes those names
to Docker without values.

Why not the browser MCP endpoint
--------------------------------
That container's MCP router refuses internal hosts at two independent layers -- an
explicit deny-list in `urlcheck.py` and a PAC script handed to Chromium in `netfilter.py`
-- so `hoover4-development-auth-backdoor` is unreachable through it *by design*. This
script launches its own Chromium with neither, which is the same route a screenshot
taken by hand would use. It does not touch, relax or import the MCP server's filtering.

What comes out, per run directory
----------------------------------
* ``<resolution>/NN-name.png``          -- what a person would see, at an exact pixel size
* ``<resolution>/NN-name.snapshot.txt`` -- a text outline of the rendered DOM plus the
  page's observations
* ``<resolution>/NN-name.FAILED.png``   -- the state at the moment an action raised
* ``<resolution>/NN-name.FAILED.snapshot.txt`` -- the rendered DOM outline at that same
  moment, same shape as the passing snapshot
* ``<resolution>/NN-name.full_page.png``-- present only when the scenario asks for it, a
  supplementary image taller than the requested size
* ``diagnostics/<resolution>__NN-name.json`` -- console and network records for that
  capture, written whether the capture passed or raised
* ``diagnostics/<resolution>__NN-name.exception.txt`` -- present only when the capture
  raised: the exception and its full traceback
* ``manifest.json``, ``report.md``, ``report.html`` -- see their own generators below

This is a gate, not a photographer
-----------------------------------
Every observation on a page is classified into one of six severities, and the run's exit
status follows from the worst one seen:

* ``application_error``    -- an unexpected missing page, a non-200 main document, an
  ``.x-error-display`` marker, or an ``.x-error-bar`` no scenario declared -- exit 1
* ``expected_outcome``     -- a negative state a scenario declared with ``expect`` (or the
  older ``allow_error_markers``) -- exit 0
* ``trace``                -- a count or a selected document that differs from an earlier
  run -- exit 0 (no producer in this runner yet; adaptive selection lands in a later pass)
* ``behavioral_warning``   -- a find term with no match, or a control with no observable
  effect -- exit 0 (no producer in this runner yet, same reason)
* ``diagnostic_warning``   -- a console error or warning, a failed or non-200 subresource
  request, or a request to an origin outside the site -- exit 0
* ``incomplete_execution`` -- no suitable document, a missing fixture, a failed login, a stopped browser, or a
  capture that could not be written -- exit 2, unless an application error also occurred

Per-page exemptions live in the scenario file: ``allow_error_markers``, ``allow_http_errors``,
``allow_console`` (a substring, one per line) demote a specific observation the way they
always have. ``expect`` (values ``missing_page``, ``error_display``, ``error_bar``) is the
newer, explicit form: it asserts a scenario expects that negative state, and reclassifies
it as ``expected_outcome`` rather than merely suppressing it. Use ``expect`` for a scenario
built to demonstrate the state; keep ``allow_*`` for a known, unrelated exemption.

Run-wide console exceptions live in ``console_whitelist.txt``; a whitelisted match is still
a ``diagnostic_warning`` (every console entry is, under this table) but is labelled with the
rule that excused it.

A page tied to a fixture dataset names it in ``requires_dataset``, exactly as before. Away
from that corpus such a page is recorded as ``incomplete_execution`` and the rest of the
run continues. A missing fixture never counts as a successful assertion.

``document_fixture`` names a contract fixture whose current document identity replaces
the ``/view_document/`` identity segment. The resolved profile supplies that identity.
An unmet fixture is ``incomplete_execution``.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import configparser
import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from capture_credentials import (
    IMAGE_REVIEW_PENDING,
    capture_revision,
    collect_image_inventory,
    read_credentials,
    CredentialError,
)

# Dials the backdoor by name, so this needs hoover4.ini.development
# (development_auth_backdoor_enabled = true). Release mode has no identity source
# this script can use.
DEFAULT_BASE_URL = os.environ.get(
    "HOOVER4_SITE_URL", "http://hoover4-development-auth-backdoor:8080"
)

# Chromium in this image takes 5-6s to come up cold; nodriver's own budget is ~2.7s, so
# the first navigation is given room rather than the browser start.
PAGE_TIMEOUT_S = 30.0

# Named sizes `--resolutions` may select. `set_device_metrics_override` is what makes
# these exact -- `tab.set_window_size` sets the OUTER window and does not establish the
# image size; a 1280x900 request measured 1280x813 through that path.
RESOLUTIONS: dict[str, tuple[int, int]] = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}
DEFAULT_RESOLUTIONS = "720p,1080p"

# The four datasets `main_services/verify-stack.sh` always ingests. A page's
# `requires_dataset = any` is satisfied by any one of these.
CORPUS_DATASETS = ("testdata_testfiles", "testdata_zips", "testdata_shapes", "other_emails")

# The six severities a capture can report, in the order the report lists them.
# Exit status: 1 if any APPLICATION_ERROR, else 2 if any INCOMPLETE_EXECUTION, else 0.
APPLICATION_ERROR = "application_error"
EXPECTED_OUTCOME = "expected_outcome"
TRACE = "trace"
BEHAVIORAL_WARNING = "behavioral_warning"
DIAGNOSTIC_WARNING = "diagnostic_warning"
INCOMPLETE_EXECUTION = "incomplete_execution"
ALL_SEVERITIES = (
    APPLICATION_ERROR,
    EXPECTED_OUTCOME,
    TRACE,
    BEHAVIORAL_WARNING,
    DIAGNOSTIC_WARNING,
    INCOMPLETE_EXECUTION,
)
EXPECT_VALUES = ("missing_page", "error_display", "error_bar")


class IncompleteCapture(OSError):
    """A required fixture or operation row is absent. Later pages still run."""


# ---------------------------------------------------------------------------------
# Scenario files
# ---------------------------------------------------------------------------------

SCENARIO_FILE = re.compile(r"^(\d+)-.+\.ini$")
DIRECTORY_DEFAULTS = {"settle_ms": "800"}

@dataclass
class Page:
    name: str
    url: str
    actions: list[tuple[str, str]] = field(default_factory=list)
    full_page: bool = False
    settle_ms: int = 700
    # Opt-outs. A page that deliberately demonstrates a failure still has to be captured,
    # but it must say so in the ini rather than silently weakening the gate for everyone.
    allow_error_markers: bool = False
    allow_http_errors: bool = False
    allow_console: list[str] = field(default_factory=list)
    # The newer, explicit form of the same idea: which negative states this scenario
    # expects to observe. See the module docstring for how this differs from `allow_*`.
    expect: list[str] = field(default_factory=list)
    # Extra captures at recorded scroll offsets (pixels), for a page taller than the
    # viewport. Each runs at the same exact size as the primary capture.
    scroll_captures: list[int] = field(default_factory=list)
    # A declared WIDTHxHEIGHT that replaces the run's resolution list for this one
    # scenario, such as a narrow-width layout test. `None` means the run's resolution
    # list applies, unchanged.
    viewport: tuple[int, int] | None = None
    # The stable filename docs/user-manual/User_Manual.md links for this scenario's
    # capture, when it produces one of the manual's images. Empty means this scenario
    # produces no manual image.
    manual_asset: str = ""
    # Datasets this page's route or assertions are tied to. Several means all of them are
    # needed; the literal "any" means one of CORPUS_DATASETS, unnamed. Empty means the page
    # renders without the fixture corpus.
    requires_dataset: list[str] = field(default_factory=list)
    # The browser media preference applied before navigation. Empty uses the browser default.
    color_scheme: str = ""
    procedure: str = ""
    init_script: str = ""
    document_fixture: str = ""
    summary: str = ""
    slug: str = ""


def parse_pages(ini_path: Path, defaults: dict[str, str] | None = None) -> list[Page]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    if defaults:
        parser.read_dict({"DEFAULT": defaults})
    parser.read(ini_path, encoding="utf-8")

    pages: list[Page] = []
    for name in parser.sections():
        section = parser[name]
        expect = [
            v.strip()
            for v in section.get("expect", "").split(",")
            if v.strip()
        ]
        for value in expect:
            if value not in EXPECT_VALUES:
                raise SystemExit(
                    f"scenario {name!r}: expect={value!r} is not one of {EXPECT_VALUES}"
                )
        viewport_raw = section.get("viewport", "").strip()
        viewport: tuple[int, int] | None = None
        if viewport_raw:
            vw, _, vh = viewport_raw.partition("x")
            if not vw.isdigit() or not vh.isdigit():
                raise SystemExit(
                    f"scenario {name!r}: viewport={viewport_raw!r} is not WIDTHxHEIGHT"
                )
            viewport = (int(vw), int(vh))
        color_scheme = section.get("color_scheme", "").strip()
        if color_scheme not in ("", "light", "dark"):
            raise SystemExit(
                f"scenario {name!r}: color_scheme={color_scheme!r} is not light or dark"
            )
        pages.append(
            Page(
                name=name,
                procedure=section.get("procedure", "").strip(),
                init_script=section.get("init_script", "").strip(),
                url=section.get("url", "/"),
                actions=parse_actions(section.get("actions", "")),
                full_page=section.getboolean("full_page", fallback=False),
                settle_ms=section.getint("settle_ms", fallback=700),
                allow_error_markers=section.getboolean("allow_error_markers", fallback=False),
                allow_http_errors=section.getboolean("allow_http_errors", fallback=False),
                allow_console=[
                    line.strip()
                    for line in section.get("allow_console", "").splitlines()
                    if line.strip()
                ],
                expect=expect,
                scroll_captures=[
                    int(v.strip())
                    for v in section.get("scroll_captures", "").split(",")
                    if v.strip()
                ],
                requires_dataset=[
                    d.strip()
                    for d in section.get("requires_dataset", "").split(",")
                    if d.strip()
                ],
                viewport=viewport,
                manual_asset=section.get("manual_asset", "").strip(),
                color_scheme=color_scheme,
                document_fixture=section.get("document_fixture", "").strip(),
                summary=section.get("summary", "").strip(),
            )
        )
    return pages


def default_scenarios_path() -> Path:
    """Directory of per-slug scenario files, or a concatenated ini copied beside the tools."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "browser-tests", here.parent / "browser-tests"):
        if candidate.is_dir() and any(SCENARIO_FILE.match(child.name) for child in candidate.iterdir()):
            return candidate
    raise FileNotFoundError(
        "browser scenario files are missing; copy website/browser-tests next to the capture tools"
    )


def load_scenario_pages(path: Path) -> list[Page]:
    """Read one concatenated ini, or every numbered ini in a directory in slug-number order."""
    path = Path(path)
    if path.is_file():
        pages = parse_pages(path)
        for page in pages:
            if not page.slug:
                page.slug = page.name
        return pages
    if not path.is_dir():
        raise SystemExit(f"scenario path {path} is not a file or directory")
    files: list[tuple[int, str, Path]] = []
    for child in path.iterdir():
        match = SCENARIO_FILE.match(child.name)
        if match:
            files.append((int(match.group(1)), child.name, child))
    files.sort()
    pages = []
    for _number, _filename, child in files:
        parsed = parse_pages(child, defaults=DIRECTORY_DEFAULTS)
        if len(parsed) != 1:
            raise SystemExit(f"{child} must contain exactly one scenario section")
        page = parsed[0]
        page.slug = child.stem
        pages.append(page)
    return pages


def missing_datasets(page: Page, present: set[str]) -> list[str]:
    """The datasets `page` needs that are not in `present`, or `[]` if it can run."""
    if not page.requires_dataset:
        return []
    if page.requires_dataset == ["any"]:
        return [] if present & set(CORPUS_DATASETS) else ["any of " + ", ".join(CORPUS_DATASETS)]
    return [d for d in page.requires_dataset if d not in present]


def load_fixture_profile(profile_path: Path, contract_path: Path) -> tuple[dict, dict]:
    """Read the resolved profile and the tracked fixture contract, or empty maps."""
    profile: dict = {}
    contract: dict = {}
    if profile_path.is_file():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if contract_path.is_file():
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    return profile, contract


def resolve_document_url(page: Page, profile: dict, contract: dict) -> str:
    """Replace a view_document identity from the current profile, or return page.url."""
    if not page.document_fixture:
        return page.url
    fixtures = contract.get("fixtures") or []
    item = next((row for row in fixtures if row.get("name") == page.document_fixture), None)
    if item is None:
        raise IncompleteCapture(f"unknown document_fixture {page.document_fixture}")
    rows = profile.get("datasets", {}).get(item["dataset"], [])
    match = next((row for row in rows if row.get("path") == item.get("path")), None)
    if match is None:
        raise IncompleteCapture(f"document_fixture {page.document_fixture} has no resolved document")
    from manual_qa_runtime import route
    identity = route({"collection_dataset": item["dataset"], "file_hash": match["hash"]})
    parts = page.url.strip("/").split("/")
    if parts[:1] != ["view_document"] or len(parts) < 2:
        raise IncompleteCapture(f"document_fixture {page.document_fixture} needs a /view_document/ url")
    parts[1] = identity
    return "/" + "/".join(parts)


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
    """Console-error exceptions: one plain substring per line, or ``re:`` + a regex."""
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


async def js_async(tab, expression: str):
    """Like `js`, for an expression that needs `await` -- a `fetch`, for instance.

    `await` only appears inside the IIFE body; the outer expression is the async
    function's own call, chained into `JSON.stringify` so CDP's `awaitPromise` resolves
    the whole thing to a string. A bare top-level `await` is a `ReferenceError` in a
    classic (non-module) `Runtime.evaluate`, which is what an outer `await` produced here.
    """
    payload = await tab.evaluate(
        f"(async () => {{ {expression} }})().then(JSON.stringify)", await_promise=True
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
    `KeyboardEvent` from JS does not trigger in the same way. CDP is the correct route."""
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
    """Wait for text to appear, optionally only inside `scope`."""
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


async def run_action(tab, base_url: str, verb: str, argument: str):
    if verb == "goto":
        await tab.get(base_url + argument)
    elif verb == "wait_text":
        await wait_text(tab, argument)
    elif verb == "wait_text_in":
        scope, _, needle = argument.partition("::")
        await wait_text(tab, needle.strip(), scope.strip())
    elif verb == "wait_css":
        await wait_css(tab, argument)
    elif verb == "wait_eval":
        return await wait_eval(tab, argument)
    elif verb == "click_text":
        await click_text(tab, argument)
    elif verb == "click_text_in":
        scope, _, needle = argument.partition("::")
        await click_text(tab, needle.strip(), scope.strip())
    elif verb == "click_css":
        await click_css(tab, argument)
    elif verb == "pointer_click_css":
        return await pointer_click_css(tab, argument)
    elif verb == "type_css":
        selector, _, text = argument.partition("::")
        await type_css(tab, selector.strip(), text.strip())
    elif verb == "press_enter":
        await press_enter(tab)
    elif verb == "press_key":
        await press_key(tab, argument)
    elif verb == "history_back":
        await navigate_history(tab, -1)
    elif verb == "history_forward":
        await navigate_history(tab, 1)
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
        return await js(tab, argument)
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
        // A password value is never written into a snapshot, even redacted-length: the
        // length alone leaks something about the credential.
        if (el.value) bits.push('[value=' + (el.type === 'password' ? '(redacted)' : el.value.slice(0, 60)) + ']');
        if (el.placeholder) bits.push('[placeholder=' + el.placeholder + ']');
    }
    if (el.tagName === 'A' && el.getAttribute('href')) bits.push('[href=' + el.getAttribute('href').slice(0, 120) + ']');
    return bits.join('');
}
function own(el) {
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


def png_dimensions(data: bytes) -> tuple[int, int]:
    """Read width and height straight out of the PNG's own `IHDR` chunk.

    This is the only check that holds: `tab.set_window_size` measured 1280x813 for a
    1280x900 request, so the outer window size proves nothing about the saved image.
    """
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("not a PNG, or has no leading IHDR chunk")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


async def set_exact_viewport(tab, width: int, height: int) -> None:
    """The CDP device-metrics override, not the outer window. See `png_dimensions`."""
    import nodriver.cdp.emulation as emulation_cdp

    await tab.send(
        emulation_cdp.set_device_metrics_override(
            width=width, height=height, device_scale_factor=1, mobile=False,
        )
    )


async def wait_eval(tab, expression: str, timeout: float = PAGE_TIMEOUT_S):
    """Wait until an expression returns `true` or an object with `ok: true`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await js(tab, expression)
        if result is True or (isinstance(result, dict) and result.get("ok") is True):
            return result
        if isinstance(result, dict) and result.get("incomplete"):
            raise IncompleteCapture(result.get("reason") or "unmet fixture")
        await asyncio.sleep(0.25)
    raise RuntimeError(f"timed out waiting for expression {expression!r}")


async def set_color_scheme(tab, color_scheme: str) -> None:
    """Apply one color-scheme preference before a scenario navigation."""
    import nodriver.cdp.emulation as emulation_cdp

    features = []
    if color_scheme:
        features.append(
            emulation_cdp.MediaFeature(name="prefers-color-scheme", value=color_scheme)
        )
    await tab.send(emulation_cdp.set_emulated_media(features=features))


async def pointer_click_css(tab, selector: str) -> dict:
    """Click the center of `selector` through Chrome DevTools Protocol pointer events."""
    import nodriver.cdp.input_ as input_cdp

    point = await js(tab, """
const el = document.querySelector(%s);
if (!el) return {ok: false};
const box = el.getBoundingClientRect();
if (!box.width || !box.height) return {ok: false};
const x = box.left + box.width / 2;
const y = box.top + box.height / 2;
if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return {ok: false};
const hit = document.elementFromPoint(x, y);
const describe = node => node ? {
    tag: node.tagName,
    role: node.getAttribute('role'),
    aria_label: node.getAttribute('aria-label'),
} : null;
return {ok: true, x, y, selector_target: describe(el), hit_target: describe(hit), hit_matches_selector: hit === el || el.contains(hit)};
""" % json.dumps(selector))
    if not point.get("ok"):
        raise RuntimeError(f"cannot pointer click visible selector {selector!r}")
    await js(tab, "window.__h4_pointer_click = %s; return {ok: true};" % json.dumps(point))
    common = {"x": point["x"], "y": point["y"], "pointer_type": "mouse"}
    await tab.send(input_cdp.dispatch_mouse_event(type_="mouseMoved", **common))
    await tab.send(input_cdp.dispatch_mouse_event(
        type_="mousePressed", button=input_cdp.MouseButton.LEFT, buttons=1, click_count=1, **common,
    ))
    await tab.send(input_cdp.dispatch_mouse_event(
        type_="mouseReleased", button=input_cdp.MouseButton.LEFT, buttons=0, click_count=1, **common,
    ))
    return point


async def press_key(tab, key_name: str) -> None:
    """Send one declared navigation or focus key through Chrome DevTools Protocol."""
    import nodriver.cdp.input_ as input_cdp

    key_spec = {
        "Escape": ("Escape", "Escape", 27, 0),
        "Tab": ("Tab", "Tab", 9, 0),
        "Shift+Tab": ("Tab", "Tab", 9, 8),
    }.get(key_name)
    if key_spec is None:
        raise RuntimeError(f"unsupported key {key_name!r}")
    key, code, virtual_key, modifiers = key_spec
    common = {
        "key": key,
        "code": code,
        "windows_virtual_key_code": virtual_key,
        "native_virtual_key_code": virtual_key,
        "modifiers": modifiers or None,
    }
    await tab.send(input_cdp.dispatch_key_event(type_="keyDown", **common))
    await tab.send(input_cdp.dispatch_key_event(type_="keyUp", **common))


async def navigate_history(tab, offset: int) -> None:
    """Navigate to an adjacent entry in the browser's actual history."""
    import nodriver.cdp.page as page_cdp

    current, entries = await tab.send(page_cdp.get_navigation_history())
    target = current + offset
    if not 0 <= target < len(entries):
        raise RuntimeError(f"browser history has no entry at offset {offset}")
    await tab.send(page_cdp.navigate_to_history_entry(entries[target].id_))


async def measured_viewport(tab) -> tuple[int, int]:
    size = await js(tab, "return {w: window.innerWidth, h: window.innerHeight};")
    return size["w"], size["h"]


# ---------------------------------------------------------------------------------
# The gates
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
    const outer = all.filter(n => !all.some(m => m !== n && m.contains(n)));
    return outer.map(n => (n.innerText || n.textContent || '').replace(/\s+/g, ' ').trim());
}
return {displays: texts('.x-error-display'), bars: texts('.x-error-bar')};
"""


@dataclass
class NetworkLog:
    """Per-page HTTP record, cleared before each navigation."""

    document: tuple[str, int] | None = None
    #: subresource-level problems: a bad status, a failed request, or a request outside
    #: the site's own origin. Always a `diagnostic_warning` -- see `judge`.
    bad: list[str] = field(default_factory=list)
    api_calls: dict[str, int] = field(default_factory=dict)
    #: server-function name -> (method, first full URL seen for it). NOT reset by
    #: `clear()`, because the identity check runs once, before the per-page loop starts
    #: clearing everything else, and still needs to find `whoami`'s call afterwards. The
    #: method matters: a server function Dioxus mounts as POST answers a GET with 405.
    known_urls: dict[str, tuple[str, str]] = field(default_factory=dict)

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
    """The server-function name in a `/api/<name><hash>` URL, or None."""
    path = urlsplit(url).path
    if not path.startswith("/api/"):
        return None
    segment = path[len("/api/"):].split("/")[0]
    return segment.rstrip("0123456789") or segment


async def watch_network(tab, site_host: str) -> NetworkLog:
    """Record response statuses through CDP for the life of the tab."""
    import nodriver.cdp.network as network_cdp

    log = NetworkLog()
    sent: dict[str, str] = {}

    def on_request(event, _connection=None):
        url = event.request.url
        sent[str(event.request_id)] = f"{event.request.method} {url}"
        name = api_function_name(url)
        if name is not None:
            log.api_calls[name] = log.api_calls.get(name, 0) + 1
            log.known_urls.setdefault(name, (event.request.method, url))
        host = urlsplit(url).hostname
        if host is not None and host != site_host:
            log.bad.append(f"outbound request to {url}")

    def on_response(event, _connection=None):
        if event.type_ is network_cdp.ResourceType.DOCUMENT and log.document is None:
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
) -> list[tuple[str, str]]:
    """Turn everything observed on one capture into a list of (severity, message)."""
    out: list[tuple[str, str]] = []

    for text in markers.get("displays", []):
        line = f"error marker: {text[:300] or '(empty)'}"
        if page.allow_error_markers or "error_display" in page.expect:
            out.append((EXPECTED_OUTCOME, line))
        else:
            out.append((APPLICATION_ERROR, line))

    for text in markers.get("bars", []):
        line = f"admin error bar: {text[:300] or '(empty)'}"
        # `allow_error_markers` and `allow_http_errors` do not reach an error bar: an
        # administrative panel rejecting bad input is only "the panel working" when the
        # scenario says so with `expect = error_bar`.
        if "error_bar" in page.expect:
            out.append((EXPECTED_OUTCOME, line))
        else:
            out.append((APPLICATION_ERROR, line))

    if network.document is not None and network.document[1] != 200:
        url, status = network.document
        line = f"main document returned HTTP {status} ({path_and_query(url)})"
        if "missing_page" in page.expect and status == 404:
            out.append((EXPECTED_OUTCOME, line))
        elif page.allow_http_errors:
            out.append((DIAGNOSTIC_WARNING, line))
        else:
            out.append((APPLICATION_ERROR, line))

    # Subresource-level problems and cross-origin requests are always diagnostic: the
    # result table demotes "a failed external request, or an optional asset 404" and "a
    # request to an origin outside the expected origins" unconditionally, so neither
    # `allow_http_errors` nor `expect` changes this bucket. `network.bad` entries carry the
    # full URL, including the target's host, so `redact_urls` strips the origin before the
    # line reaches a report: the diagnostics record keeps the whole address, this does not.
    for line in network.bad:
        out.append((DIAGNOSTIC_WARNING, redact_urls(line)))

    for entry in console:
        text = entry.get("text", "")
        if entry.get("level") != "error":
            out.append((DIAGNOSTIC_WARNING, f"console warning: {text[:300]}"))
            continue
        excused = whitelist_hit(text, whitelist) or next(
            (rule for rule in page.allow_console if rule in text), None
        )
        label = f" (allowed by {excused!r})" if excused else ""
        out.append((DIAGNOSTIC_WARNING, f"console error{label}: {text[:300]}"))

    return out


def classify_exception(exc: BaseException) -> str:
    """`incomplete_execution` for a browser or filesystem failure, `application_error`
    for everything else (a timed-out wait, an element that was never there -- the
    ordinary shape of "this page is broken"). This keeps the pre-existing gate strength
    for an ordinary action failure while giving the incomplete-execution status to a
    stopped browser and a capture that cannot be written.
    """
    if isinstance(exc, IncompleteCapture):
        return INCOMPLETE_EXECUTION
    if isinstance(exc, OSError):
        return INCOMPLETE_EXECUTION
    text = str(exc).lower()
    markers = (
        "did not mount", "connection", "target closed", "browser has been stopped",
        "websocket", "no such file", "permission denied", "disconnected",
    )
    if any(m in text for m in markers):
        return INCOMPLETE_EXECUTION
    return APPLICATION_ERROR


# ---------------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------------

# `dx serve` KEEPS SERVING THE PREVIOUS BUNDLE while it recompiles. A run started right
# after an edit therefore screenshots the old code and looks like the change did nothing,
# which is exactly how an hour goes missing.
APP_MOUNT_TIMEOUT_S = 600.0

# How long a tab may boot undisturbed before the mount wait reloads it. See
# `wait_for_app_mounted` for why reloading on every failed poll prevents the boot.
MOUNT_RELOAD_GRACE_S = 60.0

# A page that never finishes loading has to be a failure, not a stalled run.
PAGE_BUDGET_S = 180.0


async def wait_for_app_mounted(tab) -> None:
    """Wait until the wasm bundle has booted and taken over the server-rendered page.

    Polls without reloading for `MOUNT_RELOAD_GRACE_S`, then reloads at that interval.
    Reloading on every failed poll interrupts the boot it is waiting for: each reload
    re-fetches and re-instantiates the whole bundle, so several tabs booting at once
    keep restarting one another and none of them ever finishes. A four-tab observer run
    stayed unmounted for over ten minutes that way, where a two-tab run mounted in
    seconds. The grace period is the fix; a reload is still available for the case the
    dev server really did serve a page that will never boot.
    """
    deadline = time.monotonic() + APP_MOUNT_TIMEOUT_S
    announced = False
    next_reload = time.monotonic() + MOUNT_RELOAD_GRACE_S
    while time.monotonic() < deadline:
        state = await js(tab, """
const main = document.querySelector('#main');
const booted = typeof window.hydration_callback === 'function';
return {mounted: !!main && main.childElementCount > 0 && booted};
""")
        if state.get("mounted"):
            if announced:
                await asyncio.sleep(3.0)
            return
        if not announced:
            print("    waiting for the dev server to serve a mounted app…", flush=True)
            announced = True
        await asyncio.sleep(3.0)
        if time.monotonic() >= next_reload:
            await tab.reload()
            next_reload = time.monotonic() + MOUNT_RELOAD_GRACE_S
            await asyncio.sleep(1.0)
    raise RuntimeError(f"the application had not mounted after {APP_MOUNT_TIMEOUT_S:g}s")


async def navigate_document(tab, url: str, init_script: str = "") -> None:
    """Wait for the new mounted document in the current protocol session."""
    import nodriver.cdp.page as page_cdp

    await tab.send(page_cdp.enable())
    token = await tab.send(page_cdp.add_script_to_evaluate_on_new_document(source=init_script)) if init_script else None
    previous_origin = await js(tab, "return performance.timeOrigin;")
    try:
        await tab.send(page_cdp.navigate(url))
        await wait_eval(tab, "return performance.timeOrigin!==%s&&document.readyState==='complete';" % json.dumps(previous_origin))
        await wait_for_app_mounted(tab)
    finally:
        if token is not None:
            await tab.send(page_cdp.remove_script_to_evaluate_on_new_document(identifier=token))


async def discover_present_datasets(tab, base_url: str, needed: set[str]) -> set[str]:
    """Which of `needed` are registered on the running site."""
    override = os.environ.get("HOOVER4_SCREENSHOT_PRESENT_DATASETS")
    if override is not None:
        return {d.strip() for d in override.split(",") if d.strip()}
    if not needed:
        return set()
    await navigate_document(tab, base_url + "/file_browser")
    await wait_eval(tab, "const e=document.querySelector('#x-storage-tree');return !!e&&(!!e.querySelector('[id^=x-tree-d-]')||e.innerText.includes('No collections.')); ")
    present: set[str] = set()
    for dataset in needed:
        found = await js(
            tab, "return {ok: Array.from(document.querySelectorAll('#x-storage-tree .x-facet-list-item')).some(row => row.title === %s)};" % json.dumps(dataset)
        )
        if found.get("ok"):
            present.add(dataset)
    return present


async def verify_identity(tab, base_url: str, network: NetworkLog, username: str, password: str) -> tuple[bool, str]:
    """Log in when the page asks, then read the account name back from the site's own
    identity route. Returns (ok, name-or-reason). A password never appears in the
    returned reason string.

    The default local target authenticates through headers a reverse proxy asserts, so it
    shows no login form at all (`frontend/src/components/session_context.rs`'s own
    doc comment says as much); the form-fill path below exists for a target that fronts
    the site with a real one, and is exercised generically rather than against a
    known markup, because this repository has no login form to develop it against.
    """
    await tab.get(base_url + "/")
    await wait_css(tab, "body *")

    has_password_field = await js(tab, "return {ok: !!document.querySelector('input[type=password]')};")
    if has_password_field.get("ok"):
        try:
            await type_css(tab, "input[type=text], input[type=email], input:not([type])", username)
            await type_css(tab, "input[type=password]", password)
            await press_enter(tab)
        except Exception as exc:  # noqa: BLE001
            return False, f"a login form is on the page but could not be filled: {exc}"

        # A short, bounded wait for the form to clear, rather than the long app-mount
        # retry loop below: a login that failed leaves the password field on the page,
        # and spending minutes to discover that is not what a fast failure means.
        cleared = False
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            still_there = await js(tab, "return {ok: !!document.querySelector('input[type=password]')};")
            if not still_there.get("ok"):
                cleared = True
                break
            await asyncio.sleep(1.0)
        if not cleared:
            return False, "the login form is still on the page 20s after submitting it"

    try:
        await wait_for_app_mounted(tab)
    except Exception as exc:  # noqa: BLE001
        return False, f"the application did not mount after authentication: {exc}"

    known = network.known_urls.get("whoami")
    if not known:
        return False, "no whoami request was observed after navigation"
    whoami_method, whoami_url = known

    result = await js_async(tab, """
const r = await fetch(%s, {method: %s, credentials: 'same-origin'});
if (!r.ok) return {ok: false, status: r.status};
let body;
try { body = await r.json(); } catch (e) { return {ok: false, parse_error: String(e)}; }
return {ok: true, username: body.username || null, fullname: body.fullname || null};
""" % (json.dumps(whoami_url), json.dumps(whoami_method)))

    if not result.get("ok"):
        return False, f"the identity route did not return an authenticated identity: {result}"
    name = result.get("fullname") or result.get("username")
    if not name:
        return False, "the identity route returned no account name"
    return True, name


def target_label(url: str) -> str:
    """A label safe for a published report. Never the URL itself.

    `host.startswith("hoover4-")` matches this deployment's OWN container names inside
    the podman network (`hoover4-website`, `hoover4-development-auth-backdoor`), not a
    plain substring: an online host can legitimately be named `hoover4.<anything>` too,
    as the demo deployment is, and that is not "local".
    """
    host = urlsplit(url).hostname or ""
    if host in ("localhost", "127.0.0.1") or host.startswith("hoover4-") or host.endswith(".local"):
        return "local development target"
    return "the configured target"


def path_and_query(url: str) -> str:
    """`url` with the scheme, host and port removed. Never the origin.

    A report is publishable, so an observation naming a request must stay as safe as the
    header, which uses `target_label` instead of the URL for the same reason.
    """
    parts = urlsplit(url)
    tail = parts.path or "/"
    return f"{tail}?{parts.query}" if parts.query else tail


_URL_RE = re.compile(r"https?://\S+")


def redact_urls(text: str) -> str:
    """`text` with every http(s) URL replaced by its path and query. See `path_and_query`.

    Applied only to what reaches `report.md` and `report.html`. The diagnostics record
    stays verbatim, because it is written into the ignored `diagnostics/` directory and
    may hold the whole address.
    """
    return _URL_RE.sub(lambda m: path_and_query(m.group(0)), text)


def run_gitignore_text() -> str:
    return (
        "# Generated by capture_screenshots.py. Governs only this run directory.\n"
        "manifest.json\n"
        "diagnostics/\n"
        "*.steps.json\n"
    )


async def run_recorded_actions(tab, base_url: str, actions, path: Path, network=None) -> list[dict]:
    """Record each completed action and retain prior steps when a later action fails."""
    steps = []
    for index, (verb, argument) in enumerate(actions):
        step = {"index": index, "action": verb, "argument": argument, "started_at": time.time()}
        try:
            step["before"] = await js(tab, "return {url: location.href};")
            step["observed"] = await run_action(tab, base_url, verb, argument)
            step["status"] = "completed"
        except BaseException as error:
            step["status"] = "failed"
            step["error"] = str(error)
            raise
        finally:
            step["finished_at"] = time.time()
            if network is not None:
                step["api_calls"] = dict(network.api_calls)
            steps.append(step)
            pending = path.with_suffix(".pending.json")
            pending.write_text(json.dumps(steps, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            pending.replace(path)
    return steps


async def capture_one(
    tab,
    base_url: str,
    network: NetworkLog,
    page: Page,
    resolution_name: str,
    size: tuple[int, int],
    res_dir: Path,
    stem: str,
    whitelist: list[tuple[str, object]],
) -> tuple[list[dict], list[tuple[str, str]], dict]:
    """Run one scenario at one resolution. Returns (captures, observations, diagnostics)."""
    rw, rh = size
    diagnostics: dict = {"console": [], "network_bad": [], "api_calls": {}}
    captures: list[dict] = []

    await set_exact_viewport(tab, rw, rh)
    await set_color_scheme(tab, page.color_scheme)
    network.clear()
    await navigate_document(tab, base_url + page.url, page.init_script)
    await wait_css(tab, "body *")
    await asyncio.sleep(page.settle_ms / 1000.0)
    await run_recorded_actions(tab, base_url, page.actions, res_dir / f"{stem}.steps.json", network)
    if page.procedure:
        from manual_qa_runtime import run_procedure
        await run_procedure(page.procedure, tab, base_url, network, res_dir, stem, sys.modules[__name__])
    await asyncio.sleep(page.settle_ms / 1000.0)

    actual_w, actual_h = await measured_viewport(tab)
    shot = await screenshot(tab, False)
    (res_dir / f"{stem}.png").write_bytes(shot)
    pw, ph = png_dimensions(shot)

    observations: list[tuple[str, str]] = []
    if (actual_w, actual_h) != (rw, rh):
        observations.append((
            DIAGNOSTIC_WARNING,
            f"viewport mismatch: window reports {actual_w}x{actual_h}, requested {rw}x{rh}",
        ))
    if (pw, ph) != (rw, rh):
        observations.append((
            DIAGNOSTIC_WARNING,
            f"image size mismatch: saved PNG is {pw}x{ph}, requested {rw}x{rh}",
        ))
    captures.append({
        "file": f"{resolution_name}/{stem}.png",
        "resolution": resolution_name,
        "requested": [rw, rh],
        "actual_window": [actual_w, actual_h],
        "actual_png": [pw, ph],
        "scroll_offset": 0,
    })

    snap = await snapshot(tab)
    markers = await js(tab, MARKER_JS)
    # The hook is a new-document script, but a page reached by an SPA route change never
    # got one; re-running it is idempotent and never clears what has already been
    # collected.
    await js(tab, CONSOLE_HOOK_JS + "\nreturn {ok: true};")
    console_entries = (await js(tab, "return {entries: window.__h4_console || []};")).get("entries", [])

    observations.extend(judge(page, markers, console_entries, network, whitelist))

    if page.full_page:
        full_shot = await screenshot(tab, True)
        (res_dir / f"{stem}.full_page.png").write_bytes(full_shot)
        captures.append({
            "file": f"{resolution_name}/{stem}.full_page.png",
            "resolution": resolution_name,
            "supplementary": True,
        })

    for offset in page.scroll_captures:
        await js(tab, f"window.scrollTo(0, {int(offset)}); return {{ok: true}};")
        await asyncio.sleep(0.3)
        scrolled = await screenshot(tab, False)
        (res_dir / f"{stem}.scroll{offset}.png").write_bytes(scrolled)
        sw, sh = png_dimensions(scrolled)
        if (sw, sh) != (rw, rh):
            observations.append((
                DIAGNOSTIC_WARNING,
                f"scrolled capture at offset {offset} is {sw}x{sh}, requested {rw}x{rh}",
            ))
        captures.append({
            "file": f"{resolution_name}/{stem}.scroll{offset}.png",
            "resolution": resolution_name,
            "requested": [rw, rh],
            "actual_png": [sw, sh],
            "scroll_offset": offset,
        })

    snapshot_lines = [
        f"# {stem} ({resolution_name})",
        f"url:      {snap.get('url', '')}",
        f"title:    {snap.get('title', '')}",
        f"actions:  {'; '.join(f'{v} {a}' for v, a in page.actions) or '(none)'}",
        f"api calls: {network.api_summary()}",
        "",
        "## observations",
        *([f"{sev}: {msg}" for sev, msg in observations] or ["(none)"]),
        "",
        "## rendered outline",
        *snap.get("lines", []),
    ]
    (res_dir / f"{stem}.snapshot.txt").write_text("\n".join(snapshot_lines), encoding="utf-8")

    diagnostics["console"] = console_entries
    diagnostics["network_bad"] = list(network.bad)
    diagnostics["api_calls"] = dict(network.api_calls)
    return captures, observations, diagnostics


async def write_failure_diagnostics(
    tab,
    network: NetworkLog,
    res_dir: Path,
    diagnostics_dir: Path,
    res_name: str,
    stem: str,
    exc: BaseException,
) -> None:
    """Save everything still available after an action raises, in the same shape a
    passing capture writes: the rendered DOM outline (`page state`), the console and
    network records (the same `diagnostics/<res>__<stem>.json` a pass writes), and the
    exception's full traceback. The caller writes the failure PNG; this covers the rest
    of the contract that an action that raises still saves everything available at that
    moment. Every step is independent and best-effort, so one failed read (a stopped
    browser, a page that no longer responds) does not blank out the others.
    """
    try:
        snap = await snapshot(tab)
    except Exception:  # noqa: BLE001
        snap = {}
    try:
        console_entries = (
            await js(tab, "return {entries: window.__h4_console || []};")
        ).get("entries", [])
    except Exception:  # noqa: BLE001
        console_entries = []

    try:
        (res_dir / f"{stem}.FAILED.snapshot.txt").write_text(
            "\n".join([
                f"# {stem} ({res_name}) -- FAILED",
                f"url:      {snap.get('url', '')}",
                f"title:    {snap.get('title', '')}",
                "",
                "## rendered outline",
                *snap.get("lines", []),
            ]),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass

    try:
        (diagnostics_dir / f"{res_name}__{stem}.json").write_text(
            json.dumps({
                "console": console_entries,
                "network_bad": list(network.bad),
                "api_calls": dict(network.api_calls),
            }, indent=2),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass

    try:
        (diagnostics_dir / f"{res_name}__{stem}.exception.txt").write_text(
            f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}", encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        pass


async def capture_all(
    pages: list[Page],
    base_url: str,
    run_dir: Path,
    resolutions: list[tuple[str, tuple[int, int]]],
    whitelist: list[tuple[str, object]],
    username: str,
    password: str,
    profile: dict | None = None,
    contract: dict | None = None,
) -> tuple[dict, int]:
    """Runs the whole scenario list. Returns (manifest, exit_status)."""
    import nodriver
    import nodriver.cdp.page as page_cdp

    diagnostics_dir = run_dir / "diagnostics"
    diagnostics_dir.mkdir(exist_ok=True)
    for res_name, _size in resolutions:
        (run_dir / res_name).mkdir(exist_ok=True)

    totals = {sev: 0 for sev in ALL_SEVERITIES}
    manifest: dict = {
        "target_label": target_label(base_url),
        "resolutions": {name: list(size) for name, size in resolutions},
        "identity": "anonymous",
        "revision": capture_revision(),
        "pages": [],
        "totals": totals,
    }
    page_reports: list[str] = []

    def record(sev: str) -> None:
        totals[sev] = totals.get(sev, 0) + 1

    from browser_lifecycle import start_browser, stop_browser

    browser = await start_browser(
        diagnostics_dir / "chromium.log",
        browser_args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            f"--window-size={resolutions[0][1][0]},{resolutions[0][1][1]}",
        ],
    )
    try:
        tab = await browser.get(base_url + "/")
        network = await watch_network(tab, urlsplit(base_url).hostname)
        await tab.send(page_cdp.add_script_to_evaluate_on_new_document(CONSOLE_HOOK_JS))

        if username or password:
            # `verify_identity` does its own navigation and its own mount-wait, because a
            # target that shows a login form does not mount hoover4's own app until after
            # it is filled -- waiting for the mount signal first spins for the full
            # `APP_MOUNT_TIMEOUT_S` on a page that will never produce it.
            ok, name_or_reason = await verify_identity(tab, base_url, network, username, password)
            if not ok:
                record(INCOMPLETE_EXECUTION)
                manifest["identity"] = f"login failed: {name_or_reason}"
                manifest["incomplete_reason"] = name_or_reason
                page_reports.append(
                    f"- **incomplete execution**: authentication did not produce an "
                    f"identity ({name_or_reason})"
                )
                return manifest, 2
            manifest["identity"] = name_or_reason
        else:
            await wait_for_app_mounted(tab)

        needed_datasets: set[str] = set(CORPUS_DATASETS)
        for page in pages:
            needed_datasets.update(d for d in page.requires_dataset if d != "any")
        present_datasets = await discover_present_datasets(tab, base_url, needed_datasets)

        for index, page in enumerate(pages):
            stem = f"{index:02d}-{page.name}"
            missing = missing_datasets(page, present_datasets)
            if missing:
                reason = f"dataset(s) not on this site: {', '.join(missing)}"
                print(f"[{index + 1}/{len(pages)}] {stem}: incomplete ({reason})", flush=True)
                record(INCOMPLETE_EXECUTION)
                manifest["pages"].append({
                    "stem": stem, "slug": page.slug or page.name, "summary": page.summary,
                    "url": page.url, "skipped": reason,
                    "verdict": INCOMPLETE_EXECUTION,
                })
                page_reports.append(f"- `{stem}` (`{page.url}`): {INCOMPLETE_EXECUTION} ({reason})")
                continue
            try:
                page.url = resolve_document_url(page, profile or {}, contract or {})
            except IncompleteCapture as error:
                reason = str(error)
                print(f"[{index + 1}/{len(pages)}] {stem}: incomplete ({reason})", flush=True)
                record(INCOMPLETE_EXECUTION)
                manifest["pages"].append({
                    "stem": stem, "slug": page.slug or page.name, "summary": page.summary,
                    "url": page.url, "skipped": reason,
                    "verdict": INCOMPLETE_EXECUTION,
                })
                page_reports.append(f"- `{stem}` (`{page.url}`): {INCOMPLETE_EXECUTION} ({reason})")
                continue

            print(f"[{index + 1}/{len(pages)}] {stem}", flush=True)
            page_captures: list[dict] = []
            page_observations: list[tuple[str, str]] = []
            # A declared `viewport` replaces the run's resolution list for this one
            # scenario, at a directory named for the declared size, so a narrow-width
            # layout test keeps testing the width it declares rather than the run's
            # selected resolutions.
            if page.viewport is not None:
                vw, vh = page.viewport
                page_resolutions = [(f"{vw}x{vh}", (vw, vh))]
                size_source = "viewport"
                (run_dir / page_resolutions[0][0]).mkdir(exist_ok=True)
            else:
                page_resolutions = resolutions
                size_source = "resolution_list"
            for res_name, size in page_resolutions:
                res_dir = run_dir / res_name
                try:
                    captures, observations, diags = await asyncio.wait_for(
                        capture_one(tab, base_url, network, page, res_name, size, res_dir, stem, whitelist),
                        600.0 if page.procedure else PAGE_BUDGET_S,
                    )
                    for capture in captures:
                        capture["size_source"] = size_source
                    page_captures.extend(captures)
                    page_observations.extend(observations)
                    (diagnostics_dir / f"{res_name}__{stem}.json").write_text(
                        json.dumps(diags, indent=2), encoding="utf-8"
                    )
                except Exception as exc:  # noqa: BLE001
                    reason = (
                        f"the page did not finish within {600.0 if page.procedure else PAGE_BUDGET_S:g}s"
                        if isinstance(exc, asyncio.TimeoutError)
                        else str(exc)
                    )
                    severity = classify_exception(exc)
                    page_observations.append((severity, f"[{res_name}] {reason}"))
                    print(f"    {severity}: {reason}", flush=True)
                    try:
                        await tab.send(page_cdp.stop_loading())
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        (res_dir / f"{stem}.FAILED.png").write_bytes(await screenshot(tab, False))
                    except Exception:  # noqa: BLE001
                        pass
                    await write_failure_diagnostics(
                        tab, network, res_dir, diagnostics_dir, res_name, stem, exc
                    )

            for sev, _msg in page_observations:
                record(sev)
            worst = _worst_severity([sev for sev, _ in page_observations])
            page_entry = {
                "stem": stem,
                "slug": page.slug or page.name,
                "summary": page.summary,
                "url": page.url,
                "captures": page_captures,
                "observations": [{"severity": s, "message": m} for s, m in page_observations],
                "verdict": worst or "ok",
            }
            if page.manual_asset:
                page_entry["manual_asset"] = page.manual_asset
            manifest["pages"].append(page_entry)
            page_reports.append(f"- `{stem}` (`{page.url}`): {worst or 'ok'}")
            for sev, msg in page_observations:
                page_reports.append(f"    - {sev}: {msg}")
    finally:
        await stop_browser(browser)

    manifest["page_reports"] = page_reports
    exit_status = 1 if totals[APPLICATION_ERROR] else (2 if totals[INCOMPLETE_EXECUTION] else 0)
    return manifest, exit_status


def _worst_severity(severities: list[str]) -> str | None:
    order = {sev: i for i, sev in enumerate(ALL_SEVERITIES)}
    present = [s for s in severities if s not in (DIAGNOSTIC_WARNING, EXPECTED_OUTCOME, TRACE)]
    if not present:
        return severities[0] if severities else None
    return min(present, key=lambda s: order[s])


# ---------------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------------

REPORT_VERDICT_PASS = "PASS"
REPORT_VERDICT_FAIL = "FAIL"
REPORT_VERDICT_WARNING = "WARNING"
REPORT_VERDICT_INCOMPLETE = "INCOMPLETE"

SEVERITY_TO_REPORT_VERDICT = {
    APPLICATION_ERROR: REPORT_VERDICT_FAIL,
    EXPECTED_OUTCOME: REPORT_VERDICT_PASS,
    TRACE: REPORT_VERDICT_PASS,
    BEHAVIORAL_WARNING: REPORT_VERDICT_WARNING,
    DIAGNOSTIC_WARNING: REPORT_VERDICT_WARNING,
    INCOMPLETE_EXECUTION: REPORT_VERDICT_INCOMPLETE,
}


def report_verdict(severity: str | None) -> str:
    """Map a recorded severity to a report word. An unknown severity raises."""
    if severity is None or severity in ("", "ok"):
        return REPORT_VERDICT_PASS
    try:
        return SEVERITY_TO_REPORT_VERDICT[severity]
    except KeyError as exc:
        raise ValueError(f"unmapped severity {severity!r}") from exc


def inventory_images_for_stem(inventory: list[dict], stem: str) -> list[str]:
    """PNG paths from the inventory that belong to this page stem."""
    prefix = f"{stem}."
    return [
        item["path"]
        for item in inventory
        if Path(item["path"]).name.startswith(prefix)
    ]


def snapshot_href(run_dir: Path, stem: str, image_paths: list[str]) -> str:
    """Relative snapshot path beside the first matching image, if that file exists."""
    for path in image_paths:
        candidate = Path(path).parent / f"{stem}.snapshot.txt"
        if (run_dir / candidate).is_file():
            return candidate.as_posix()
    return ""


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def inline_image_html(path: str, alt: str) -> str:
    """A 500-pixel preview that links to the original file."""
    safe_path = _esc(path)
    return (
        f'<a href="{safe_path}">'
        f'<img src="{safe_path}" width="500" alt="{_esc(alt)}">'
        f"</a>"
    )


def _resolution_label(resolutions: object) -> str:
    if isinstance(resolutions, dict):
        return ", ".join(str(name) for name in resolutions)
    if isinstance(resolutions, (list, tuple)):
        return ", ".join(str(name) for name in resolutions)
    return str(resolutions)


def write_reports(run_dir: Path, run_name: str, manifest: dict, exit_status: int) -> None:
    totals = manifest["totals"]
    inventory = collect_image_inventory(
        run_dir,
        manifest.get("target_label", ""),
        manifest.get("revision") or capture_revision(),
    )
    pages = list(manifest.get("pages") or [])
    pages.sort(key=lambda page: 1 if report_verdict(page.get("verdict")) == REPORT_VERDICT_INCOMPLETE else 0)

    def image_cell(stem: str, slug: str, image_paths: list[str]) -> str:
        return " ".join(
            inline_image_html(path, f"{slug} {Path(path).parent.as_posix()}")
            for path in image_paths
        )

    md_rows = []
    html_rows = []
    for page in pages:
        stem = page.get("stem") or ""
        slug = page.get("slug") or stem
        summary = page.get("summary") or ""
        verdict = report_verdict(page.get("verdict"))
        image_paths = inventory_images_for_stem(inventory, stem)
        images = image_cell(stem, slug, image_paths)
        snapshot = snapshot_href(run_dir, stem, image_paths)
        snapshot_md = f"[snapshot]({snapshot})" if snapshot else ""
        snapshot_html = f'<a href="{_esc(snapshot)}">snapshot</a>' if snapshot else ""
        md_rows.append(
            f"| `{slug}` | {_esc(summary).replace('|', '\\|')} | {verdict} | {images} | {snapshot_md} |"
        )
        html_rows.append(
            "<tr>"
            f"<td><code>{_esc(slug)}</code></td>"
            f"<td>{_esc(summary)}</td>"
            f"<td class=\"verdict-{verdict.lower()}\">{verdict}</td>"
            f"<td>{images}</td>"
            f"<td>{snapshot_html}</td>"
            "</tr>"
        )

    totals_md = "\n".join(f"- {sev}: {totals.get(sev, 0)}" for sev in ALL_SEVERITIES)
    resolution_label = _resolution_label(manifest.get("resolutions") or [])
    lines = [
        "# Screenshot run",
        "",
        f"Target: {manifest['target_label']}  |  identity: {manifest['identity']}",
        f"Resolutions: {resolution_label}",
        "",
        "## totals",
        totals_md,
        f"- exit status: {exit_status}",
        "",
        "## pages",
        "",
        "| slug | summary | verdict | images | snapshot |",
        "| --- | --- | --- | --- | --- |",
        *md_rows,
    ]
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    totals_html = "".join(f"<li>{_esc(sev)}: {totals.get(sev, 0)}</li>" for sev in ALL_SEVERITIES)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Screenshot run</title>
<style>
body {{ font-family: sans-serif; margin: 2em; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 0.5em; vertical-align: top; }}
th {{ text-align: left; }}
img {{ width: 500px; height: auto; }}
.verdict-fail {{ color: #a40000; font-weight: bold; }}
.verdict-warning {{ color: #8a6d00; font-weight: bold; }}
.verdict-incomplete {{ color: #555; }}
.verdict-pass {{ color: #1a7f37; }}
</style>
</head>
<body>
<h1>Screenshot run</h1>
<p>Target: {_esc(manifest['target_label'])}. Identity: {_esc(manifest['identity'])}.</p>
<p>Resolutions: {_esc(resolution_label)}</p>
<h2>Totals</h2>
<ul>{totals_html}</ul>
<p>Exit status: {exit_status}</p>
<h2>Pages</h2>
<table>
<thead><tr><th>slug</th><th>summary</th><th>verdict</th><th>images</th><th>snapshot</th></tr></thead>
<tbody>
{"".join(html_rows)}
</tbody>
</table>
</body>
</html>
"""
    (run_dir / "report.html").write_text(html, encoding="utf-8")

    index = (
        "# Screenshot output\n\n"
        f"Latest run: `{run_name}`\n\n"
        f"Target: {manifest['target_label']}  |  identity: {manifest['identity']}\n\n"
        f"Exit status: {exit_status}\n\n"
        f"See [`{run_name}/report.md`]({run_name}/report.md) for the full run.\n"
    )
    (run_dir.parent / "index.md").write_text(index, encoding="utf-8")

    (run_dir / ".gitignore").write_text(run_gitignore_text(), encoding="utf-8")
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (run_dir / "image_inventory.json").write_text(
        json.dumps({
            "review_state_default": IMAGE_REVIEW_PENDING,
            "images": inventory,
        }, indent=2) + "\n",
        encoding="utf-8",
    )


def select_pages(pages: list[Page], only: str, names_csv: str) -> list[Page]:
    """Select named pages and fail if an exact name is absent."""
    if only:
        pages = [page for page in pages if only in page.name]
    if names_csv:
        names = {name.strip() for name in names_csv.split(",") if name.strip()}
        pages = [page for page in pages if page.name in names]
        missing = names - {page.name for page in pages}
        if missing:
            raise ValueError(f"unknown pages selected: {', '.join(sorted(missing))}")
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ini",
        default="/tmp/h4shots/browser-tests",
        help="concatenated scenario ini, or a directory of numbered per-slug ini files",
    )
    parser.add_argument("--out-root", default="/tmp/h4shots/out")
    parser.add_argument("--run-name", required=True, help="the run-<stamp>-<pid> directory name")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--only", default="", help="capture only sections whose name contains this")
    parser.add_argument("--names", default="", help="capture exactly these comma-separated section names")
    parser.add_argument("--console-whitelist", default="/tmp/h4shots/console_whitelist.txt")
    parser.add_argument("--resolutions", default=DEFAULT_RESOLUTIONS)
    parser.add_argument(
        "--profile",
        default=str(Path(__file__).with_name("manual_qa_profile.json")),
    )
    parser.add_argument(
        "--contract",
        default=str(Path(__file__).with_name("manual_qa_fixtures.json")),
    )
    args = parser.parse_args()

    try:
        username, password = read_credentials()
    except CredentialError as error:
        sys.stderr.write(f"error: {error}\n")
        return 2

    try:
        resolutions = [(name, RESOLUTIONS[name]) for name in
                        (n.strip() for n in args.resolutions.split(",")) if name]
    except KeyError as exc:
        sys.stderr.write(f"error: unknown resolution {exc}; known: {', '.join(RESOLUTIONS)}\n")
        return 2
    if not resolutions:
        sys.stderr.write("error: no resolutions selected\n")
        return 2

    out_root = Path(args.out_root)
    run_dir = out_root / args.run_name
    # This directory is fresh, ephemeral container scratch (`/tmp/h4shots`, wiped by the
    # wrapper before every invocation) -- not the persistent host output tree, which the
    # wrapper never deletes. Creating it here does not touch anything the wrapper owns.
    run_dir.mkdir(parents=True, exist_ok=True)

    pages = load_scenario_pages(Path(args.ini))
    try:
        pages = select_pages(pages, args.only, args.names)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    if not pages:
        print("no pages selected", file=sys.stderr)
        return 2

    whitelist = parse_whitelist(Path(args.console_whitelist))
    profile, contract = load_fixture_profile(
        Path(args.profile), Path(args.contract) if args.contract else Path()
    )
    try:
        manifest, exit_status = asyncio.run(
            capture_all(
                pages, args.base_url.rstrip("/"), run_dir, resolutions, whitelist,
                username, password, profile, contract,
            )
        )
    except Exception as exc:  # noqa: BLE001
        # A browser that never started, or another catastrophic setup failure. Still
        # leave a report behind rather than nothing at all.
        manifest = {
            "target_label": target_label(args.base_url),
            "resolutions": {name: list(size) for name, size in resolutions},
            "identity": "anonymous",
            "revision": capture_revision(),
            "pages": [],
            "page_reports": [f"- **incomplete execution**: {type(exc).__name__}: {exc}"],
            "totals": {sev: (1 if sev == INCOMPLETE_EXECUTION else 0) for sev in ALL_SEVERITIES},
        }
        write_reports(run_dir, args.run_name, manifest, 2)
        print(f"incomplete execution: {exc}", file=sys.stderr)
        return 2

    write_reports(run_dir, args.run_name, manifest, exit_status)
    totals = manifest["totals"]
    print(
        f"{len(manifest['pages'])} pages: "
        + ", ".join(f"{sev}={totals.get(sev, 0)}" for sev in ALL_SEVERITIES)
        + f"; output in {run_dir} (see report.md); exit {exit_status}"
    )
    return exit_status


if __name__ == "__main__":
    sys.exit(main())
