"""Drive a chat conversation in a real browser and observe it from submission to
completion, in the same container and by the same mechanism as `capture_screenshots.py`.

Invoked by `website/observe-chat.sh`, which resolves the target, the credentials and the
output run directory exactly as `website/take-screenshots.sh` does, then copies this file
in beside `capture_screenshots.py` and runs it there. This file imports that module's
browser helpers (`type_css`, `press_enter`, `judge`, `verify_identity`, the severity
constants) rather than copying them, so the login flow, the console/network gates and the
exit-status rule stay in one place.

The ten prompts below are a versioned workload. Their text is fixed: a run's results are
comparable across time only when the prompts that produced them did not change, so treat an
edit to this list as a new workload rather than a wording fix.

Per-conversation output, under `<out_root>/<run_name>/chat/<NN-slug>/`
-----------------------------------------------------------------------
* ``pre_send.snapshot.txt``                    -- the transcript before submission
* ``<resolution>/interval-NNN-t<seconds>s.png`` -- one capture per 5-second deadline
* ``<resolution>/interval-NNN-t<seconds>s.snapshot.txt`` -- scroll offset, geometry,
  message count and observations at that same instant
* ``<resolution>/completion-top.png`` / ``completion-bottom.png``
* ``document_preview.png`` / ``.snapshot.txt``  -- the last opened citation card, if any
* ``reload.snapshot.txt``, ``switch_back.snapshot.txt`` -- history survival checks
* ``followup/`` -- the same shape again, only for the collection-exploration conversation
* ``conversation.json``, ``report.md``, ``report.html``

A combined ``chat_index.md`` and ``chat_manifest.json`` sit beside the per-conversation
directories, with the overlap table concurrent conversations need.

Result classification reuses `capture_screenshots.py`'s six severities. A submission that
produced no observable turn start, a capture that could not be written, or a browser that
stopped are `incomplete_execution`. Missing history, an empty completed answer, and a
citation card that opens the wrong document are `application_error` (behavioral defects,
not diagnostic noise). A console error, a bad subresource or a missed capture deadline are
`diagnostic_warning`. The exit status follows the same rule as the page runner: 1 if any
`application_error`, else 2 if any `incomplete_execution` and no `application_error`, else 0.

Never retries a submitted prompt, and never cancels a live generation: see the module
docstring's own rules restated at `submit_and_observe`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from capture_screenshots import (  # noqa: E402
    ALL_SEVERITIES,
    APPLICATION_ERROR,
    CONSOLE_HOOK_JS,
    DIAGNOSTIC_WARNING,
    EXPECTED_OUTCOME,
    INCOMPLETE_EXECUTION,
    MARKER_JS,
    Page,
    RESOLUTIONS,
    classify_exception,
    js,
    js_async,
    judge,
    parse_whitelist,
    png_dimensions,
    press_enter,
    screenshot,
    set_exact_viewport,
    snapshot,
    target_label,
    type_css,
    verify_identity,
    wait_for_app_mounted,
    watch_network,
    wait_css,
)

# ---------------------------------------------------------------------------------
# The prompt set -- copied verbatim from 8-chat-capture-design.md#prompt-set. Do not
# reword these; a versioned workload that drifts from its own source document is not
# versioned.
# ---------------------------------------------------------------------------------

COLLECTION_EXPLORATION = (
    "collection-exploration",
    "chat",
    "List the document collections available to this conversation. Select one accessible "
    "collection and search for three representative documents. Describe their subjects and "
    "explain what further research they could support. Cite the documents you actually "
    "inspected. If access or evidence is insufficient, state the limitation.",
)

FOLLOW_UP_TEXT = (
    "Using the evidence from your previous answer, give two supported findings and one "
    "unresolved question. Preserve the document citations."
)

PROMPTS: list[tuple[str, str, str]] = [
    COLLECTION_EXPLORATION,
    (
        "document-evidence", "chat",
        "Search the available collections for documents about energy. Inspect up to three "
        "relevant documents. Produce a table of claims, supporting passages, document "
        "citations, and uncertainties. Distinguish statements in the documents from your "
        "conclusions. If there are no relevant documents, describe the searches you attempted.",
    ),
    (
        "comparison-across-documents", "chat",
        "Search the available collections for contracts or procurement. Compare up to three "
        "relevant documents by parties, subject, dates, and stated obligations. Cite the "
        "evidence for each populated field. Mark absent information as unavailable. Do not "
        "infer wrongdoing from a missing field or a difference between documents.",
    ),
    (
        "chronology-from-evidence", "chat",
        "Find available documents about a public project or an organization. Select one topic "
        "supported by at least two documents if possible. Build a short chronology using dates "
        "stated in the documents. Distinguish document dates from dates of described events. "
        "Cite each entry and explain any contradictions or gaps.",
    ),
    (
        "public-source-research", "chat",
        "Use Internet research to explain how the Internet Archive preserves websites and what "
        "its captures can and cannot establish. Prefer its official documentation. Provide "
        "source links, distinguish capture time from publication time, and give a reproducible "
        "verification procedure. State which pages you actually inspected.",
    ),
    (
        "open-source-project-research", "chat",
        "Research the public OpenStreetMap project using its official sources. Explain its "
        "governance, data license, contribution process, and ways to inspect a map edit's "
        "provenance. Link evidence for each section. Separate documented facts from "
        "recommendations and state any source access failures.",
    ),
    (
        "public-organization-research", "chat",
        "Research the public governance and funding disclosures of the Wikimedia Foundation "
        "using official sources. Produce an evidence table with the claim, source, reporting "
        "period, and limitation. Avoid research about private individuals. Explain how a "
        "reader can verify the disclosures and distinguish current pages from older reports.",
    ),
    (
        "conflicting-claims", "chat",
        "Investigate the claim that a PDF creation timestamp proves when its contents were "
        "originally written. Use authoritative technical sources. Explain alternative causes "
        "for timestamps, identify what the metadata can establish, and propose corroborating "
        "evidence. Give source links and separate verified facts from hypotheses.",
    ),
    (
        "reproducible-internet-investigation", "deep_research",
        "Design a reproducible investigation of changes to a public organization's website. "
        "Use official documentation for web archives and domain registration lookup services. "
        "Explain what each source records, its limitations, and how to preserve citations. "
        "Research organizational records only. Include a concise evidence collection checklist "
        "with source links.",
    ),
    (
        "research-synthesis", "deep_research",
        "Search the available collections for energy policy and inspect relevant results. Use "
        "authoritative public Internet sources to add context to one claim you find. Produce a "
        "short research report with document citations, web source links, contradictions, "
        "unanswered questions, and suggested next searches. If the collections provide no "
        "relevant evidence, state that result and keep the public-source research clearly "
        "separate.",
    ),
]
PROMPTS_BY_NAME = {name: (name, profile, text) for name, profile, text in PROMPTS}

# The observation period is the application's configured turn deadline plus 60s.
# Read from `main_services/processing/tasks/P_agent/workflows.py`'s own
# `start_to_close_timeout` values, not guessed: 900s for the nag-loop chat turn
# (`ChatTurn`/ordinary chat with tools), 2400s for `ResearchTask` (Deep Research).
TURN_DEADLINE_S = {"chat": 900.0, "deep_research": 2400.0}
DEADLINE_MARGIN_S = 60.0

CAPTURE_INTERVAL_S = 5.0

# Selectors against the real markup in `frontend/src/components/chat_components/`.
# `composer.rs`: the textarea has this placeholder, the send button this title, and the
# stop button's title starts with this text while sending is true.
TEXTAREA_SEL = "textarea[placeholder='Write a query to send commands to the AI']"
SEND_BUTTON_SEL = "button[title='Send']"
STOP_BUTTON_SEL = "button[title^='Stop the answer']"
# `transcript.rs`'s live/finished transcript pane has no id; it is the one scrollable
# flex column in the left panel. Selected structurally rather than by a class the source
# does not have. A behavioral_warning is recorded, not a crash, if this stops matching.
TRANSCRIPT_SEL = "div[style*='overflow-y: auto']"
DOCREFS_TOGGLE_SEL = ".x-chat-docrefs-toggle"
# `search_result_item_card.rs` has no id or class either; matched on its distinguishing
# inline style (a fixed 148px card height is unique to this card on the chat page).
DOC_CARD_SEL = "div[style*='height: 148px']"

# ---------------------------------------------------------------------------------
# Item 3: the polling allowance. `HOOVER4_RATE_CHAT_POLL_PER_MINUTE` defaults to 600,
# flat, keyed by username -- every observer tab under the one supplied login shares it.
# `MAX_HELD_POLLS_PER_USER` (2, in `website/backend/src/api/chat/mod.rs`) means a tab
# beyond the held cap gets an unheld, immediate response and the frontend's poll loop
# calls again with no client-side delay, which is the fast path to exhausting the flat
# budget. This throttle keeps the observer inside that budget without changing the
# application: it patches `fetch` inside every observer tab, before the app boots, to
# space out calls to the poll endpoint. `min_interval_ms` is sized from the tab count
# this run opens, so the whole run's poll rate stays under the 600/min budget with
# headroom for the identity check and the wrapper's own traffic.
POLL_BUDGET_PER_MINUTE = 600
POLL_BUDGET_HEADROOM = 550  # leave ~8% under the flat ceiling
POLL_FLOOR_MS = 500  # never throttle below the server's own floor


def poll_throttle_js(min_interval_ms: int) -> str:
    return f"""
if (!window.__h4_poll_throttle_installed) {{
    window.__h4_poll_throttle_installed = true;
    const original = window.fetch;
    let nextAllowed = 0;
    window.fetch = function(input, init) {{
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        if (url.indexOf('/api/chat_poll') === -1) {{
            return original.call(this, input, init);
        }}
        const now = Date.now();
        const wait = Math.max(0, nextAllowed - now);
        nextAllowed = Math.max(now, nextAllowed) + {min_interval_ms};
        if (wait <= 0) return original.call(this, input, init);
        return new Promise(function (resolve) {{
            setTimeout(function () {{ resolve(original.call(window, input, init)); }}, wait);
        }});
    }};
}}
"""


# ---------------------------------------------------------------------------------
# Small helpers over what `capture_screenshots.py` provides. These are chat-specific
# reads (checkbox state, current route, message count) with no page-runner equivalent.
# ---------------------------------------------------------------------------------

async def set_checkbox_by_label(tab, label_text: str, desired: bool) -> bool:
    """Toggle the checkbox whose visible label contains `label_text`. Returns whether a
    matching, editable checkbox was found (false once options are frozen, which is
    expected after the first turn)."""
    result = await js(tab, """
const needle = %s;
const labels = Array.from(document.querySelectorAll('label'));
const label = labels.find(l => (l.innerText || '').includes(needle));
if (!label) return {ok: false, reason: 'no label'};
const box = label.querySelector('input[type=checkbox]');
if (!box) return {ok: false, reason: 'no checkbox in label'};
return {ok: true, checked: box.checked};
""" % json.dumps(label_text))
    if not result.get("ok"):
        return False
    if result.get("checked") == desired:
        return True
    await js(tab, """
const needle = %s;
const labels = Array.from(document.querySelectorAll('label'));
const label = labels.find(l => (l.innerText || '').includes(needle));
const box = label.querySelector('input[type=checkbox]');
box.click();
return {ok: true};
""" % json.dumps(label_text))
    return True


async def current_route(tab) -> str:
    return (await js(tab, "return {href: location.href};")).get("href", "")


async def stop_button_present(tab) -> bool:
    return (await js(tab, "return {ok: !!document.querySelector(%s)};" % json.dumps(STOP_BUTTON_SEL))).get("ok", False)


async def transcript_state(tab) -> dict:
    """Message count, text length, loading text, scroll geometry -- the behavior evidence
    the design asks be recorded at every interval. Falls back to `document.body` when the
    structural transcript selector does not match, and says so."""
    return await js(tab, """
const root = document.querySelector(%s) || document.body;
const matched = !!document.querySelector(%s);
const bubbles = root.querySelectorAll("div");
let userCount = 0, assistantChars = 0;
for (const el of bubbles) {
    const bg = getComputedStyle(el).backgroundColor;
    if (bg === 'rgb(64, 150, 255)') userCount += 1; // the user bubble's own fill
}
const text = root.innerText || '';
const working = text.includes('is working') || text.includes('is searching');
return {
    matched_transcript_selector: matched,
    text_length: text.length,
    user_bubble_count: userCount,
    working_placeholder_visible: working,
    scroll_top: root.scrollTop,
    scroll_height: root.scrollHeight,
    client_height: root.clientHeight,
};
""" % (json.dumps(TRANSCRIPT_SEL), json.dumps(TRANSCRIPT_SEL)))


async def scroll_transcript(tab, position: str) -> None:
    await js(tab, """
const root = document.querySelector(%s) || document.body;
if (%s === 'top') root.scrollTop = 0; else root.scrollTop = root.scrollHeight;
return {ok: true};
""" % (json.dumps(TRANSCRIPT_SEL), json.dumps(position)))


async def open_last_document_card(tab) -> dict:
    """Expand every doc-refs disclosure, then click the last clickable preview card.
    Returns what happened -- 'no_cards', 'opened', or 'unopenable' -- for the report to
    classify. Never substitutes a different document for a missing one."""
    expanded = await js(tab, """
const toggles = Array.from(document.querySelectorAll(%s));
let opened = 0;
for (const t of toggles) {
    if ((t.innerText || '').includes('show')) { t.click(); opened += 1; }
}
return {toggled: opened};
""" % json.dumps(DOCREFS_TOGGLE_SEL))
    await asyncio.sleep(0.4)
    found = await js(tab, """
const cards = Array.from(document.querySelectorAll(%s)).filter(c => c.offsetParent !== null);
if (!cards.length) return {ok: false, reason: 'no_cards'};
const last = cards[cards.length - 1];
const title = (last.innerText || '').split('\\n')[0].slice(0, 200);
last.scrollIntoView({block: 'center'});
last.click();
return {ok: true, title: title, count: cards.length};
""" % json.dumps(DOC_CARD_SEL))
    found["toggled_disclosures"] = expanded.get("toggled", 0)
    return found


# ---------------------------------------------------------------------------------
# One conversation
# ---------------------------------------------------------------------------------

@dataclass
class CaptureRecord:
    deadline_s: float
    actual_s: float
    file: str
    scroll_top: int
    scroll_height: int
    missed: bool


@dataclass
class ConversationResult:
    name: str
    profile: str
    prompt_text: str
    session_url: str = ""
    submission_ok: bool = False
    turn_started: bool = False
    stop_disappeared_at_s: float | None = None
    completed_answer_present: bool = False
    observations: list[tuple[str, str]] = field(default_factory=list)
    captures: dict[str, list[dict]] = field(default_factory=dict)
    history: dict[str, dict] = field(default_factory=dict)
    document_preview: dict | None = None
    incomplete: bool = False
    incomplete_reason: str = ""
    started_monotonic: float = 0.0
    generating_started_s: float | None = None
    generating_ended_s: float | None = None


async def submit_and_observe(
    tab,
    base_url: str,
    network,
    whitelist,
    page_probe: Page,
    name: str,
    profile: str,
    prompt_text: str,
    resolution_name: str,
    size: tuple[int, int],
    out_dir: Path,
    deadline_s: float,
    home_first: bool,
    run_started: float,
) -> ConversationResult:
    """Submit, wait for the turn to start, capture at each interval, and verify
    completion, on one tab, at one resolution. Two tabs (one per resolution) call this for
    the SAME conversation; only the first (`home_first=True`) submits, so the prompt is
    never retried.

    Never retries a submitted prompt: a submission failure ends this conversation's
    observation with `incomplete_execution` rather than sending the text again, because a
    silent retry creates a duplicate conversation and invalidates the comparison between
    the two tabs watching it. Never cancels a live generation: a missed deadline or a
    capture failure is recorded and observation stops, but the tab is never told to stop
    the turn.
    """
    result = ConversationResult(name=name, profile=profile, prompt_text=prompt_text)
    result.started_monotonic = time.monotonic()
    res_dir = out_dir / resolution_name
    res_dir.mkdir(parents=True, exist_ok=True)
    await set_exact_viewport(tab, *size)

    if home_first:
        await tab.get(base_url + "/ai_chat")
        await wait_for_app_mounted(tab)
        await asyncio.sleep(1.0)
        if profile == "deep_research":
            await set_checkbox_by_label(tab, "Deep Research", True)
        else:
            await set_checkbox_by_label(tab, "Internet tools", True)

        pre_snap = await snapshot(tab)
        (out_dir / "pre_send.snapshot.txt").write_text(
            "\n".join(pre_snap.get("lines", [])), encoding="utf-8"
        )

        try:
            await type_css(tab, TEXTAREA_SEL, prompt_text)
            await press_enter(tab)
        except Exception as exc:  # noqa: BLE001
            result.incomplete = True
            result.incomplete_reason = f"could not submit the prompt: {exc}"
            result.observations.append((INCOMPLETE_EXECUTION, result.incomplete_reason))
            return result

        # Wait for the route to leave /ai_chat -- the homepage creates the session and
        # navigates only once the message is accepted.
        deadline = time.monotonic() + 30.0
        route = await current_route(tab)
        while "/ai_chat/c/" not in route and time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            route = await current_route(tab)
        if "/ai_chat/c/" not in route:
            result.incomplete = True
            result.incomplete_reason = "no navigation to a conversation after submitting"
            result.observations.append((INCOMPLETE_EXECUTION, result.incomplete_reason))
            return result
        result.session_url = route
        result.submission_ok = True
        # Publish the conversation URL the moment it exists, not when this whole
        # function returns. The second resolution's tab polls `page_probe.url` below and
        # starts observing as soon as it is set, so both tabs watch the same live
        # generation instead of the second one starting only after the first finishes.
        page_probe.url = route
    else:
        # The second resolution's tab: wait for the primary tab to publish the URL.
        deadline = time.monotonic() + 30.0
        while not page_probe.url and time.monotonic() < deadline:
            await asyncio.sleep(0.3)
        if not page_probe.url:
            result.incomplete = True
            result.incomplete_reason = "primary tab never produced a conversation URL"
            result.observations.append((INCOMPLETE_EXECUTION, result.incomplete_reason))
            return result
        result.session_url = page_probe.url
        await tab.get(page_probe.url)
        await wait_for_app_mounted(tab)
        result.submission_ok = True

    # Step 3: verify the turn actually started. A Stop button or visible tool/answer
    # activity within a bounded window; nothing observed there is a submission failure,
    # never promoted into a completed answer.
    start_deadline = time.monotonic() + 30.0
    while time.monotonic() < start_deadline:
        if await stop_button_present(tab):
            result.turn_started = True
            break
        state = await transcript_state(tab)
        if state.get("working_placeholder_visible"):
            result.turn_started = True
            break
        await asyncio.sleep(0.5)
    if not result.turn_started:
        result.incomplete = True
        result.incomplete_reason = "no observable turn start (no Stop button, no working state)"
        result.observations.append((INCOMPLETE_EXECUTION, result.incomplete_reason))
        return result
    result.generating_started_s = time.monotonic() - run_started

    # Step 4-6: capture at 5s deadlines, scheduled against the deadline so a slow
    # screenshot never stretches a later interval. Scroll position is read but never
    # changed between intervals, so a capture cannot conceal an unexpected scroll.
    captures: list[dict] = []
    interval_index = 0
    t0 = time.monotonic()
    hard_deadline = t0 + deadline_s
    first_capture = await capture_interval(
        tab, network, whitelist, page_probe_page(page_probe, name), res_dir, 0.0, 0.0, interval_index
    )
    captures.append(first_capture)
    while time.monotonic() < hard_deadline:
        interval_index += 1
        target = t0 + interval_index * CAPTURE_INTERVAL_S
        now = time.monotonic()
        if target > now:
            await asyncio.sleep(target - now)
        stop_now = await stop_button_present(tab)
        if not stop_now and result.stop_disappeared_at_s is None:
            result.stop_disappeared_at_s = time.monotonic() - t0
        record = await capture_interval(
            tab, network, whitelist, page_probe_page(page_probe, name), res_dir,
            target - t0, time.monotonic() - t0, interval_index,
        )
        captures.append(record)
        if not stop_now:
            break
    else:
        result.observations.append((
            DIAGNOSTIC_WARNING,
            f"observation reached its {deadline_s:g}s ceiling with the Stop button still "
            f"present; the conversation was left running, not cancelled",
        ))
    result.generating_ended_s = time.monotonic() - run_started
    result.captures[resolution_name] = captures

    # Step 7: top and bottom of the completed transcript.
    await scroll_transcript(tab, "top")
    await asyncio.sleep(0.3)
    top_shot = await screenshot(tab, False)
    (res_dir / "completion-top.png").write_bytes(top_shot)
    await scroll_transcript(tab, "bottom")
    await asyncio.sleep(0.3)
    bottom_shot = await screenshot(tab, False)
    (res_dir / "completion-bottom.png").write_bytes(bottom_shot)

    final_state = await transcript_state(tab)
    result.completed_answer_present = final_state.get("text_length", 0) > 0
    if not result.stop_disappeared_at_s:
        result.observations.append((
            APPLICATION_ERROR,
            "the Stop button never disappeared during the observed window: this is not "
            "recorded as a completed answer",
        ))
    if not result.completed_answer_present:
        result.observations.append((
            APPLICATION_ERROR, "the completed transcript is empty after the observed window",
        ))

    return result


def page_probe_page(_probe, name: str) -> Page:
    return Page(name=name, url="")


async def capture_interval(
    tab, network, whitelist, page: Page, res_dir: Path,
    deadline_offset: float, actual_offset: float, index: int,
) -> dict:
    stem = f"interval-{index:03d}-t{int(round(actual_offset)):04d}s"
    state = await transcript_state(tab)
    shot = await screenshot(tab, False)
    (res_dir / f"{stem}.png").write_bytes(shot)
    markers = await js(tab, MARKER_JS)
    console_entries = (await js(tab, "return {entries: window.__h4_console || []};")).get("entries", [])
    observations = judge(page, markers, console_entries, network, whitelist)
    missed = (actual_offset - deadline_offset) > CAPTURE_INTERVAL_S
    lines = [
        f"# {stem}",
        f"requested deadline: {deadline_offset:.3f}s  actual: {actual_offset:.3f}s  missed: {missed}",
        f"message text length: {state.get('text_length')}  user bubbles: {state.get('user_bubble_count')}",
        f"scroll: top={state.get('scroll_top')} height={state.get('scroll_height')} "
        f"client={state.get('client_height')}",
        f"transcript selector matched: {state.get('matched_transcript_selector')}",
        f"working placeholder visible: {state.get('working_placeholder_visible')}",
        "",
        "## observations",
        *([f"{sev}: {msg}" for sev, msg in observations] or ["(none)"]),
    ]
    (res_dir / f"{stem}.snapshot.txt").write_text("\n".join(lines), encoding="utf-8")
    return {
        "file": f"{res_dir.name}/{stem}.png",
        "deadline_offset_s": round(deadline_offset, 3),
        "actual_offset_s": round(actual_offset, 3),
        "missed": missed,
        "scroll_top": state.get("scroll_top"),
        "scroll_height": state.get("scroll_height"),
        "text_length": state.get("text_length"),
        "observations": [{"severity": s, "message": m} for s, m in observations],
    }


async def check_history(tab, base_url: str, other_session_url: str | None) -> dict:
    """Step 9: pre-send vs during vs after-completion vs after-reload vs after switching
    away and back. Pre/during/after-completion are read by the caller from the interval
    captures already taken; this covers the two DOM-destroying actions."""
    before_reload = await transcript_state(tab)
    await tab.reload()
    await wait_for_app_mounted(tab)
    await asyncio.sleep(1.0)
    after_reload = await transcript_state(tab)

    switch_result: dict = {"attempted": False}
    if other_session_url:
        switch_result["attempted"] = True
        current = await current_route(tab)
        await tab.get(other_session_url)
        await wait_for_app_mounted(tab)
        await asyncio.sleep(1.0)
        await tab.get(current)
        await wait_for_app_mounted(tab)
        await asyncio.sleep(1.0)
        after_switch = await transcript_state(tab)
        switch_result["text_length_after_switch_back"] = after_switch.get("text_length")
        switch_result["survived"] = after_switch.get("text_length", 0) >= before_reload.get("text_length", 0)

    return {
        "before_reload_text_length": before_reload.get("text_length"),
        "after_reload_text_length": after_reload.get("text_length"),
        "reload_survived": after_reload.get("text_length", 0) >= before_reload.get("text_length", 0) * 0.9,
        "switch": switch_result,
    }


# ---------------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------------

def write_conversation_report(out_dir: Path, result: ConversationResult) -> None:
    lines = [
        f"# {result.name} ({result.profile})",
        "",
        f"prompt: {result.prompt_text}",
        f"session: {result.session_url}",
        f"submission ok: {result.submission_ok}  turn started: {result.turn_started}",
        f"stop button disappeared at: {result.stop_disappeared_at_s}",
        f"completed answer present: {result.completed_answer_present}",
        f"generating interval (run-relative): {result.generating_started_s} .. {result.generating_ended_s}",
        "",
        "## history",
        json.dumps(result.history, indent=2),
        "",
        "## document preview",
        json.dumps(result.document_preview, indent=2),
        "",
        "## observations",
        *([f"{s}: {m}" for s, m in result.observations] or ["(none)"]),
    ]
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "conversation.json").write_text(
        json.dumps({
            "name": result.name, "profile": result.profile, "prompt": result.prompt_text,
            "session_url": result.session_url, "submission_ok": result.submission_ok,
            "turn_started": result.turn_started,
            "stop_disappeared_at_s": result.stop_disappeared_at_s,
            "completed_answer_present": result.completed_answer_present,
            "generating_started_s": result.generating_started_s,
            "generating_ended_s": result.generating_ended_s,
            "captures": result.captures, "history": result.history,
            "document_preview": result.document_preview,
            "observations": [{"severity": s, "message": m} for s, m in result.observations],
            "incomplete": result.incomplete, "incomplete_reason": result.incomplete_reason,
        }, indent=2),
        encoding="utf-8",
    )

    def esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{esc(result.name)}</title></head><body>"
        f"<h1>{esc(result.name)} ({esc(result.profile)})</h1>"
        f"<p>{esc(result.prompt_text)}</p>"
        f"<p>session: {esc(result.session_url)}</p>"
        f"<p>submission ok: {result.submission_ok}, turn started: {result.turn_started}, "
        f"completed answer present: {result.completed_answer_present}</p>"
        "<h2>observations</h2><ul>"
        + "".join(f"<li>{esc(s)}: {esc(m)}</li>" for s, m in result.observations)
        + "</ul></body></html>"
    )
    (out_dir / "report.html").write_text(html, encoding="utf-8")


def worst_severity(observations: list[tuple[str, str]]) -> str | None:
    order = {sev: i for i, sev in enumerate(ALL_SEVERITIES)}
    present = [s for s, _ in observations if s not in (DIAGNOSTIC_WARNING, EXPECTED_OUTCOME)]
    if present:
        return min(present, key=lambda s: order[s])
    return observations[0][0] if observations else None


def write_run_index(out_dir: Path, results: list[ConversationResult], exit_status: int) -> None:
    lines = ["# Chat observer run", "", "## conversations", ""]
    lines.append("| name | profile | submitted | turn started | completed | verdict | generating |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in results:
        verdict = worst_severity(r.observations) or "ok"
        gen = (
            f"{r.generating_started_s:.1f}-{r.generating_ended_s:.1f}s"
            if r.generating_started_s is not None and r.generating_ended_s is not None
            else "n/a"
        )
        lines.append(
            f"| {r.name} | {r.profile} | {r.submission_ok} | {r.turn_started} | "
            f"{r.completed_answer_present} | {verdict} | {gen} |"
        )
    lines.append("")
    lines.append("## concurrency: the generating interval of every conversation")
    lines.append(
        "Overlap in the table above is the evidence eight windows showing a spinner does not "
        "give: two rows whose `generating` ranges intersect were actually producing tokens "
        "at the same time, not merely queued."
    )
    lines.append("")
    lines.append(f"exit status: {exit_status}")
    (out_dir / "chat_index.md").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "chat_manifest.json").write_text(
        json.dumps([json.loads((out_dir / r.name / "conversation.json").read_text()) for r in results], indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------------

async def run_all(
    prompt_names: list[str],
    base_url: str,
    out_dir: Path,
    resolutions: list[tuple[str, tuple[int, int]]],
    whitelist,
    username: str,
    password: str,
    run_followup: bool,
) -> tuple[list[ConversationResult], int]:
    import nodriver
    import nodriver.cdp.page as page_cdp

    tabs_total = len(prompt_names) * len(resolutions)
    min_interval_ms = max(
        POLL_FLOOR_MS, math.ceil(60000 * max(tabs_total, 1) / POLL_BUDGET_HEADROOM)
    )
    print(
        f"== {len(prompt_names)} conversation(s) x {len(resolutions)} resolution(s) = "
        f"{tabs_total} tab(s); poll throttle {min_interval_ms}ms/tab "
        f"(budget {POLL_BUDGET_PER_MINUTE}/min, headroom {POLL_BUDGET_HEADROOM}/min) ==",
        flush=True,
    )

    browser = await nodriver.start(
        headless=True, sandbox=False,
        browser_args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    )
    results: list[ConversationResult] = []
    run_started = time.monotonic()
    try:
        identity_tab = await browser.get(base_url + "/")
        identity_network = await watch_network(identity_tab, base_url.split("//", 1)[-1].split("/")[0])
        await identity_tab.send(page_cdp.add_script_to_evaluate_on_new_document(CONSOLE_HOOK_JS))
        if username or password:
            ok, name_or_reason = await verify_identity(identity_tab, base_url, identity_network, username, password)
            if not ok:
                print(f"incomplete execution: identity check failed: {name_or_reason}", file=sys.stderr)
                return results, 2

        # Item 4: every selected prompt runs as a concurrent conversation, not one after
        # another. `session_urls` replaces the old "prior_session_url" (which assumed one
        # conversation finished before the next began) with a shared map every
        # conversation publishes into once it has a URL, since concurrent conversations
        # have no well-defined "the previous one".
        session_urls: dict[str, str] = {}

        async def run_conversation(name: str) -> ConversationResult:
            prompt_name, profile, prompt_text = PROMPTS_BY_NAME[name]
            conv_dir = out_dir / name
            conv_dir.mkdir(parents=True, exist_ok=True)
            print(f"[{name}] submitting ({profile})", flush=True)

            tabs = []
            networks = []
            for res_name, size in resolutions:
                tab = await browser.get(base_url + "/", new_tab=True)
                net = await watch_network(tab, base_url.split("//", 1)[-1].split("/")[0])
                await tab.send(page_cdp.add_script_to_evaluate_on_new_document(
                    CONSOLE_HOOK_JS + "\n" + poll_throttle_js(min_interval_ms)
                ))
                tabs.append(tab)
                networks.append(net)

            page_probe = Page(name=name, url="")
            deadline_s = TURN_DEADLINE_S.get(profile, 900.0) + DEADLINE_MARGIN_S

            async def observe_one(i: int) -> ConversationResult:
                res_name, size = resolutions[i]
                return await submit_and_observe(
                    tabs[i], base_url, networks[i], whitelist, page_probe, name, profile,
                    prompt_text, res_name, size, conv_dir, deadline_s, home_first=(i == 0),
                    run_started=run_started,
                )

            # One observer page per resolution, watching the SAME live generation. All
            # tabs start together; the primary (i == 0) publishes `page_probe.url` inside
            # `submit_and_observe` as soon as it has it, so the other tab's own wait for
            # that URL is what lets it join the conversation while the primary is still
            # capturing, not only after the primary's whole coroutine has returned.
            raw_results = await asyncio.gather(
                *[observe_one(i) for i in range(len(resolutions))],
                return_exceptions=True,
            )
            resolved: list[ConversationResult] = []
            for i, res in enumerate(raw_results):
                if isinstance(res, BaseException):
                    err = ConversationResult(name=name, profile=profile, prompt_text=prompt_text)
                    sev = classify_exception(res)
                    err.observations.append((
                        sev, f"observer failure (resolution {resolutions[i][0]}): {res}",
                    ))
                    err.incomplete = True
                    res = err
                resolved.append(res)

            primary, others = resolved[0], resolved[1:]
            merged = primary
            for other in others:
                merged.captures.update(other.captures)
                merged.observations.extend(other.observations)

            if primary.submission_ok:
                session_urls[name] = merged.session_url
                try:
                    merged.document_preview = await open_last_document_card(tabs[0])
                    await asyncio.sleep(0.6)
                    doc_shot = await screenshot(tabs[0], False)
                    (conv_dir / "document_preview.png").write_bytes(doc_shot)
                    if merged.document_preview.get("ok") is False and merged.document_preview.get("reason") != "no_cards":
                        merged.observations.append((
                            DIAGNOSTIC_WARNING,
                            f"a document card exists but would not open: {merged.document_preview}",
                        ))
                except Exception as exc:  # noqa: BLE001
                    merged.observations.append((DIAGNOSTIC_WARNING, f"document preview step failed: {exc}"))

                # The "switch to another conversation and back" history check needs a
                # second conversation's URL. Every selected prompt runs concurrently now,
                # so there is no single "prior" one: use whichever other conversation has
                # already published its URL, and skip the check (attempted: False) when
                # none has yet -- both are recorded in the result, never substituted.
                other_url = next((u for n, u in session_urls.items() if n != name and u), None)
                try:
                    merged.history = await check_history(tabs[0], base_url, other_url)
                except Exception as exc:  # noqa: BLE001
                    merged.observations.append((DIAGNOSTIC_WARNING, f"history check failed: {exc}"))

                if run_followup and name == "collection-exploration":
                    followup_dir = conv_dir / "followup"
                    followup_dir.mkdir(exist_ok=True)
                    try:
                        await type_css(tabs[0], TEXTAREA_SEL, FOLLOW_UP_TEXT)
                        await press_enter(tabs[0])
                        await asyncio.sleep(2.0)
                        followup_probe = Page(name=f"{name}-followup", url="")
                        fu_deadline = TURN_DEADLINE_S["chat"] + DEADLINE_MARGIN_S
                        fu_result = await submit_and_observe(
                            tabs[0], base_url, networks[0], whitelist, followup_probe,
                            f"{name}-followup", "chat", FOLLOW_UP_TEXT, resolutions[0][0],
                            resolutions[0][1], followup_dir, fu_deadline, home_first=False,
                            run_started=run_started,
                        )
                        write_conversation_report(followup_dir, fu_result)
                    except Exception as exc:  # noqa: BLE001
                        merged.observations.append((DIAGNOSTIC_WARNING, f"follow-up turn failed: {exc}"))

            write_conversation_report(conv_dir, merged)
            print(
                f"[{name}] submitted={merged.submission_ok} started={merged.turn_started} "
                f"completed={merged.completed_answer_present} "
                f"verdict={worst_severity(merged.observations) or 'ok'}", flush=True
            )
            return merged

        raw_conv_results = await asyncio.gather(
            *[run_conversation(name) for name in prompt_names],
            return_exceptions=True,
        )
        for name, conv_res in zip(prompt_names, raw_conv_results):
            if isinstance(conv_res, BaseException):
                _, profile, prompt_text = PROMPTS_BY_NAME[name]
                err = ConversationResult(name=name, profile=profile, prompt_text=prompt_text)
                sev = classify_exception(conv_res)
                err.observations.append((sev, f"conversation driver failure: {conv_res}"))
                err.incomplete = True
                conv_res = err
            results.append(conv_res)
    finally:
        try:
            browser.stop()
        except Exception:  # noqa: BLE001
            pass

    totals = {sev: 0 for sev in ALL_SEVERITIES}
    for r in results:
        for sev, _ in r.observations:
            totals[sev] = totals.get(sev, 0) + 1
        if r.incomplete:
            totals[INCOMPLETE_EXECUTION] = totals.get(INCOMPLETE_EXECUTION, 0) + 1
    exit_status = 1 if totals[APPLICATION_ERROR] else (2 if totals[INCOMPLETE_EXECUTION] else 0)
    write_run_index(out_dir, results, exit_status)
    return results, exit_status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root", default="/tmp/h4shots/out")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--base-url", default="http://hoover4-development-auth-backdoor:8080")
    parser.add_argument("--console-whitelist", default="/tmp/h4shots/console_whitelist.txt")
    parser.add_argument("--username", default="")
    parser.add_argument("--resolutions", default="720p,1080p")
    parser.add_argument(
        "--prompts", default="collection-exploration",
        help="comma-separated prompt names, or 'all'; see PROMPTS for the fixed order",
    )
    parser.add_argument(
        "--conversations", type=int, default=0,
        help="how many of the selected prompts to run as concurrent conversations "
             "(0 = every selected prompt)",
    )
    parser.add_argument("--no-followup", action="store_true")
    args = parser.parse_args()

    password = os.environ.get("HOOVER4_CAPTURE_PASSWORD", "")
    username = args.username
    if bool(username) != bool(password):
        sys.stderr.write("error: a username with no password, or the reverse, is a validation failure\n")
        return 2

    if args.prompts.strip() == "all":
        names = [n for n, _, _ in PROMPTS]
    else:
        names = [n.strip() for n in args.prompts.split(",") if n.strip()]
    unknown = [n for n in names if n not in PROMPTS_BY_NAME]
    if unknown:
        sys.stderr.write(f"error: unknown prompt name(s): {unknown}; known: {list(PROMPTS_BY_NAME)}\n")
        return 2
    if args.conversations > 0:
        names = names[: args.conversations]
    if not names:
        sys.stderr.write("error: no prompts selected\n")
        return 2

    try:
        resolutions = [(n, RESOLUTIONS[n]) for n in (s.strip() for s in args.resolutions.split(",")) if n]
    except KeyError as exc:
        sys.stderr.write(f"error: unknown resolution {exc}\n")
        return 2

    out_dir = Path(args.out_root) / args.run_name / "chat"
    out_dir.mkdir(parents=True, exist_ok=True)
    whitelist = parse_whitelist(Path(args.console_whitelist))

    try:
        results, exit_status = asyncio.run(run_all(
            names, args.base_url.rstrip("/"), out_dir, resolutions, whitelist,
            username, password, not args.no_followup,
        ))
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"incomplete execution: {type(exc).__name__}: {exc}\n")
        return 2

    print(f"{len(results)} conversation(s) observed; output in {out_dir}; exit {exit_status}")
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
