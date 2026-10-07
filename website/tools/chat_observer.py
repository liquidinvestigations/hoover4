"""Drive a chat conversation in a real browser and observe it from submission to
completion, in the same container and by the same mechanism as `capture_screenshots.py`.

Invoked by `website/observe-chat.sh`, which resolves the target, the credentials and the
output run directory exactly as `website/take-screenshots.sh` does, then copies this file
in beside `capture_screenshots.py` and runs it there. This file imports that module's
browser helpers (`type_css`, `press_enter`, `judge`, `verify_identity`, the severity
constants) rather than copying them, so the login flow, the console/network gates and the
exit-status rule stay in one place.

The chat prompts below are a versioned workload. Their text is fixed: a run's
results are comparable across time only when the prompts that produced them did not change, so
treat an edit to this list as a new workload rather than a wording fix. Four extra chat names
reuse an existing prompt's text so a twelve-conversation run stays on chat turns.

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
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from capture_credentials import (
    IMAGE_REVIEW_PENDING,
    capture_revision,
    collect_image_inventory,
    read_credentials,
    CredentialError,
)

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
        "public-source-research-2", "chat",
        "Use Internet research to explain how the Internet Archive preserves websites and what "
        "its captures can and cannot establish. Prefer its official documentation. Provide "
        "source links, distinguish capture time from publication time, and give a reproducible "
        "verification procedure. State which pages you actually inspected.",
    ),
    (
        "open-source-project-research-2", "chat",
        "Research the public OpenStreetMap project using its official sources. Explain its "
        "governance, data license, contribution process, and ways to inspect a map edit's "
        "provenance. Link evidence for each section. Separate documented facts from "
        "recommendations and state any source access failures.",
    ),
    (
        "public-organization-research-2", "chat",
        "Research the public governance and funding disclosures of the Wikimedia Foundation "
        "using official sources. Produce an evidence table with the claim, source, reporting "
        "period, and limitation. Avoid research about private individuals. Explain how a "
        "reader can verify the disclosures and distinguish current pages from older reports.",
    ),
    (
        "conflicting-claims-2", "chat",
        "Investigate the claim that a PDF creation timestamp proves when its contents were "
        "originally written. Use authoritative technical sources. Explain alternative causes "
        "for timestamps, identify what the metadata can establish, and propose corroborating "
        "evidence. Give source links and separate verified facts from hypotheses.",
    ),
    (
        "reproducible-internet-investigation", "chat_internet",
        "Design a reproducible investigation of changes to a public organization's website. "
        "Use official documentation for web archives and domain registration lookup services. "
        "Explain what each source records, its limitations, and how to preserve citations. "
        "Research organizational records only. Include a concise evidence collection checklist "
        "with source links.",
    ),
    (
        "research-synthesis", "chat_internet",
        "Search the available collections for energy policy and inspect relevant results. Use "
        "authoritative public Internet sources to add context to one claim you find. Produce a "
        "short research report with document citations, web source links, contradictions, "
        "unanswered questions, and suggested next searches. If the collections provide no "
        "relevant evidence, state that result and keep the public-source research clearly "
        "separate.",
    ),
]
# The requests of the chat audit that the acceptance cases repeat, with their follow-ups.
# The text is the stored text of the audited sessions. `--prompts all` does not select them,
# so the workload of `all` stays the list above.
ACCEPTANCE_PROMPTS: list[tuple[str, str, str]] = [
    ("ux-synthetic-cannabinoids", "chat",
     "what company is the biggest producer of Synthetic Cannabinoids in Europe ?"),
    ("ux-genocide-sources", "chat",
     "which state is currently committing a genocide and according to who ?"),
    ("ux-weed-documents", "chat",
     "show me all our documents related to weed or marijuana"),
    ("general-question", "chat_local", "What is the capital of France?"),
    ("number-game", "chat_local",
     "I am thinking of a number. You may ask if it is bigger or smaller until you find it."),
    ("connection-diagnosis", "chat_local",
     "My Python program says connection refused. What should I check first?"),
    ("document-comparison", "chat_local",
     "Compare how the other and testdata collections discuss energy. Give cited document "
     "examples."),
    ("gitlab-chief-of-station", "chat",
     "go to https://gitlab.com/jack_poulson/widely-reported/-/tree/master/data?ref_type=heads "
     "and extract and list all the names of chief of station and sort them by year and "
     "mention location"),
    # A follow-up for `--continue`. It asks for a source of the earlier turns of a
    # conversation whose context the next model step compacts.
    ("compacted-source-followup", "chat",
     "Which document says that Jane Porter approved lease L-17? Give the first 16 "
     "characters of its file hash and its citation label. Answer from the conversation, "
     "and do not search."),
]
PROMPTS_BY_NAME = {name: (name, profile, text)
                   for name, profile, text in PROMPTS + ACCEPTANCE_PROMPTS}

# The second turn of a conversation, sent once after the first turn ends.
FOLLOW_UPS = {
    "collection-exploration": FOLLOW_UP_TEXT,
    "general-question": "Give one fact about it.",
    "number-game": "bigger",
    "connection-diagnosis": "The service is listening on a different port.",
    "gitlab-chief-of-station": "which of these years has the most names?",
}


def register_story_prompts(root: Path) -> None:
    """Read acceptance prompts and internet settings from their source documents."""
    for path in sorted(root.glob("[0-9][0-9]-*.md")):
        source = path.read_text(encoding="utf-8")
        mode = re.search(r"^\| mode \| chat, internet tools (on|off) \|$", source, re.M)
        section = source.split("## Prompt\n", 1)[1].split("\n## ", 1)[0]
        turns = re.findall(r"```text\n(.*?)\n```", section, re.S)
        if mode is None or len(turns) not in (1, 2):
            raise ValueError(f"The story mode or prompts are invalid in {path.name}.")
        name = "story-" + path.name[:2]
        profile = "chat_local" if mode[1] == "off" else "chat"
        PROMPTS_BY_NAME[name] = (name, profile, turns[0])
        if len(turns) == 2:
            FOLLOW_UPS[name] = turns[1]

# The longest observation of one turn. The observer stops earlier when the page shows
# the turn as ended. `AgentRun` sets no time limit on a run: `RUN_MODEL_STEPS` in
# `main_services/processing/tasks/P_agent/model_timeouts.py` bounds its steps, and each
# step can wait up to the model call timeout. So no finite value covers every run that the
# workflow allows. Four hours is four times the longest measured chat turn (59 minutes).
TURN_CEILING_S = 14_400.0

CAPTURE_INTERVAL_S = 5.0

# Selectors against the real markup in `frontend/src/components/chat_components/`.
# `composer.rs`: the textarea has this placeholder and the send button this title.
TEXTAREA_SEL = "textarea[placeholder='Write a query to send commands to the AI']"
SEND_BUTTON_SEL = "button[title='Send']"
# `transcript.rs` gives the transcript pane this id and the `data-chat-turn` state.
TRANSCRIPT_SEL = "#x-chat-transcript"
DOCREFS_TOGGLE_SEL = ".x-chat-docrefs-toggle"
# `search_result_item_card.rs` has no id or class either; matched on its distinguishing
# inline style (a fixed 148px card height is unique to this card on the chat page).
DOC_CARD_SEL = "div[style*='height: 148px']"

# ---------------------------------------------------------------------------------
# Item 3: the polling allowance. `HOOVER4_RATE_CHAT_POLL_PER_MINUTE` defaults to 1800,
# flat, keyed by username -- every observer tab under the one supplied login shares it.
# `MAX_HELD_POLLS_PER_USER` (8, in `website/backend/src/api/chat/mod.rs`) means a tab
# beyond the held cap gets an unheld, immediate response and the frontend's poll loop
# calls again with no client-side delay, which is the fast path to exhausting the flat
# budget. This throttle keeps the observer inside that budget without changing the
# application: it patches `fetch` inside every observer tab, before the app boots, to
# space out calls to the poll endpoint. `min_interval_ms` is sized from the tab count
# this run opens, so the whole run's poll rate stays under the 1800/min budget with
# headroom for the identity check and the wrapper's own traffic.
POLL_BUDGET_PER_MINUTE = 1800
POLL_BUDGET_HEADROOM = 1650  # leave ~8% under the flat ceiling
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
    turn: matched ? (root.dataset.chatTurn || '') : '',
    user_seqs: [...root.querySelectorAll('[data-chat-user]')].map(e=>Number(e.dataset.chatUser)),
    assistant_answers: [...root.querySelectorAll('[data-chat-answer]')].map(e=>({seq:e.dataset.chatAnswer,text:e.textContent})),
    asked: [...root.querySelectorAll('[data-chat-asked]')].map(e=>({seq:e.dataset.chatAsked,text:e.textContent})),
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
# Turn identity
# ---------------------------------------------------------------------------------

# `session_page.rs` writes the state of the newest turn on the transcript root as
# `data-chat-turn`. These values mean that the turn has not ended.
RUNNING_TURNS = ("active", "queued-model", "queued-tool")
# The seconds that an ended turn can show no answer row before the observer records
# an empty answer. The last poll can end the turn before the answer row renders.
LATE_ANSWER_S = 15.0
# The seconds that one page script or capture can take. A call that takes longer is
# stopped, and its interval is recorded as a missed capture. A long turn can load the
# browser container, for example when the agent's own browser reads a large file there,
# and one capture then takes more than this.
PAGE_CALL_TIMEOUT_S = 60.0
# The seconds that the page can fail every call before the observer records an unknown
# outcome. A browser connection can stop answering while the page itself is idle, and the
# observer then does not wait for the whole turn ceiling.
UNRESPONSIVE_LIMIT_S = 300.0


def newest_user_seq(state: dict) -> int:
    """The seq of the newest user message on the page, or -1 when there is none."""
    return max((int(seq) for seq in state.get("user_seqs", [])), default=-1)


def saved_answers(state: dict) -> list[dict]:
    """The answer rows on the page. An answer that repeats a question to the user renders
    as the question card, and the page keeps its text in a hidden `data-chat-asked`."""
    return list(state.get("assistant_answers", [])) + list(state.get("asked", []))


def turn_phase(state: dict, before_seq: int, after_answer_seq: int = -1) -> str:
    """The phase of the turn that the user message after `before_seq` started.

    `not_started` means that the page shows no user message after `before_seq`. `running`
    means that the turn is active or waits for a slot. A queued turn adds no text, so a
    silent queue is `running`. `interrupted` means that the page shows the turn as
    interrupted. `answered` means that the turn ended and an answer or a question to the
    user after its user message has text. `ended_empty` means that the turn ended and no such answer exists
    yet. The last state can change to `answered` when the answer row renders late.

    """
    own = [int(seq) for seq in state.get("user_seqs", []) if int(seq) > before_seq]
    if not own:
        return "not_started"
    turn = state.get("turn", "")
    start = min(own)
    if turn in RUNNING_TURNS:
        return "running"
    if turn == "interrupted":
        return "interrupted"
    for answer in saved_answers(state):
        try:
            seq = int(answer.get("seq", ""))
        except ValueError:
            continue
        if seq > max(start, after_answer_seq) and answer.get("text", "").strip():
            return "answered"
    return "ended_empty"


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
    turn_phase: str = ""
    turn_ended_at_s: float | None = None
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


async def submit_followup(tab, text: str) -> tuple[int, str]:
    """Type `text` into the composer of the open conversation and press Enter once.

    Returns the newest user seq before the submission and an empty string, or that seq
    and the reason that the submission failed. This function never submits a second
    time. A failed submission is recorded, because a second submission starts a second
    turn in the same conversation.
    """
    before_seq = newest_user_seq(await transcript_state(tab))
    try:
        await type_css(tab, TEXTAREA_SEL, text)
        await press_enter(tab)
    except Exception as exc:  # noqa: BLE001
        return before_seq, f"could not submit the follow-up: {exc}"
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if newest_user_seq(await transcript_state(tab)) > before_seq:
            return before_seq, ""
        await asyncio.sleep(0.5)
    return before_seq, "the page showed no new user message within 30 s of the follow-up"


async def follow_turn(tab, before_seq: int, deadline_s: float, interval_s: float, capture,
                      after_answer_seq: int = -1) -> tuple[str, float]:
    """Observe the turn after `before_seq` until it ends or `deadline_s` elapses.

    `capture(index, target_s, actual_s)` records one interval. The intervals are timed
    from the start, so a slow capture does not delay the later intervals. Returns the
    last phase from `turn_phase` and the seconds until the observer saw the turn end.
    The seconds value is -1 when the turn did not end. A page call that takes longer than
    `PAGE_CALL_TIMEOUT_S` skips its interval. The phase is `unresponsive` when every call
    failed for `UNRESPONSIVE_LIMIT_S`.
    """
    t0 = time.monotonic()
    index = 0
    ended_at = -1.0
    empty_since = None
    failing_since = None
    phase = "running"
    while True:
        try:
            state = await asyncio.wait_for(transcript_state(tab), PAGE_CALL_TIMEOUT_S)
            phase = turn_phase(state, before_seq, after_answer_seq)
            now = time.monotonic() - t0
            await asyncio.wait_for(capture(index, index * interval_s, now), PAGE_CALL_TIMEOUT_S)
            failing_since = None
        except asyncio.TimeoutError:
            now = time.monotonic() - t0
            if now >= deadline_s:
                return phase, ended_at
            failing_since = now if failing_since is None else failing_since
            if now - failing_since >= UNRESPONSIVE_LIMIT_S:
                return "unresponsive", ended_at
            index += 1
            continue
        if phase in ("answered", "interrupted"):
            return phase, now
        if phase == "ended_empty":
            if empty_since is None:
                empty_since = now
                ended_at = now
            elif now - empty_since >= LATE_ANSWER_S:
                return phase, ended_at
        else:
            empty_since = None
            ended_at = -1.0
        if now >= deadline_s:
            return phase, ended_at
        index += 1
        wait = t0 + index * interval_s - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)


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
    mode: str,
    run_started: float,
) -> ConversationResult:
    """Submit or join one turn, capture at each interval, and verify its end, on one tab
    at one resolution.

    `mode` is `new`, `join` or `followup`. `new` opens the chat home page and submits
    the prompt as a new conversation. `join` opens the conversation that the `new` tab
    publishes in `page_probe.url`, and never submits. `followup` submits the prompt once
    into the conversation that is already open on `tab`.

    The observer follows one turn: the turn that the first user message after the
    submission started. A turn that ended before the tab loaded is recorded as ended.
    The observer never submits a prompt again and never stops a live generation. A missed
    deadline or a capture failure is recorded and observation stops.
    """
    result = ConversationResult(name=name, profile=profile, prompt_text=prompt_text)
    result.started_monotonic = time.monotonic()
    res_dir = out_dir / resolution_name
    res_dir.mkdir(parents=True, exist_ok=True)
    await set_exact_viewport(tab, *size)
    before_seq = -1

    if mode == "new":
        await tab.get(base_url + "/ai_chat")
        await wait_for_app_mounted(tab)
        await asyncio.sleep(1.0)
        await set_checkbox_by_label(tab, "Internet tools", profile != "chat_local")

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

        # The home page creates the session and opens it after it accepts the message.
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
        # Published now, so the `join` tab observes the same live turn.
        page_probe.url = route
    elif mode == "join":
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
    elif mode == "followup":
        result.session_url = await current_route(tab)
        before_seq, problem = await submit_followup(tab, prompt_text)
        if problem:
            result.incomplete = True
            result.incomplete_reason = problem
            result.observations.append((INCOMPLETE_EXECUTION, problem))
            return result
        result.submission_ok = True
    else:
        raise ValueError(f"unknown observation mode {mode!r}")

    # The turn starts when the page shows its user message.
    start_deadline = time.monotonic() + 30.0
    while time.monotonic() < start_deadline:
        if turn_phase(await transcript_state(tab), before_seq) != "not_started":
            result.turn_started = True
            break
        await asyncio.sleep(0.5)
    if not result.turn_started:
        result.incomplete = True
        result.incomplete_reason = "the page showed no user message for the submitted turn"
        result.observations.append((INCOMPLETE_EXECUTION, result.incomplete_reason))
        return result
    result.generating_started_s = time.monotonic() - run_started

    # Scroll position is read but never changed between intervals, so a capture cannot
    # conceal an unexpected scroll.
    captures: list[dict] = []

    async def capture(index: int, target_s: float, actual_s: float) -> None:
        captures.append(await capture_interval(
            tab, network, whitelist, page_probe_page(page_probe, name), res_dir,
            target_s, actual_s, index,
        ))

    phase, ended_at = await follow_turn(tab, before_seq, deadline_s, CAPTURE_INTERVAL_S, capture)
    result.turn_phase = phase
    if ended_at >= 0:
        result.turn_ended_at_s = ended_at
    if phase == "running":
        result.observations.append((
            DIAGNOSTIC_WARNING,
            f"observation reached its {deadline_s:g}s ceiling with the turn still running; "
            f"the conversation was left running, not cancelled",
        ))
    result.generating_ended_s = time.monotonic() - run_started
    result.captures[resolution_name] = captures
    if phase == "unresponsive":
        result.incomplete = True
        result.incomplete_reason = (
            f"every page call of the observer took more than {PAGE_CALL_TIMEOUT_S:g}s for "
            f"{UNRESPONSIVE_LIMIT_S:g}s, so the outcome of the turn is unknown")
        result.observations.append((INCOMPLETE_EXECUTION, result.incomplete_reason))
        return result

    # The top and the bottom of the transcript after the turn.
    try:
        await asyncio.wait_for(completion_captures(tab, res_dir), 2 * PAGE_CALL_TIMEOUT_S)
    except asyncio.TimeoutError:
        result.observations.append((
            INCOMPLETE_EXECUTION,
            f"the completion captures took more than {2 * PAGE_CALL_TIMEOUT_S:g}s",
        ))

    result.completed_answer_present = phase == "answered"
    if phase == "running":
        result.observations.append((
            APPLICATION_ERROR,
            "the turn did not end during the observed window: this is not recorded as a "
            "completed answer",
        ))
    elif phase == "interrupted":
        result.observations.append((APPLICATION_ERROR, "the page shows the turn as interrupted"))
    elif phase == "ended_empty":
        result.observations.append((
            APPLICATION_ERROR, "the turn ended and the page shows no answer text for it",
        ))

    return result


async def completion_captures(tab, res_dir: Path) -> None:
    """Capture the top and the bottom of the transcript."""
    await scroll_transcript(tab, "top")
    await asyncio.sleep(0.3)
    (res_dir / "completion-top.png").write_bytes(await screenshot(tab, False))
    await scroll_transcript(tab, "bottom")
    await asyncio.sleep(0.3)
    (res_dir / "completion-bottom.png").write_bytes(await screenshot(tab, False))


# The seconds that the history check of one tab can take. It waits up to 30 s twice.
HISTORY_TIMEOUT_S = 180.0


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
        f"turn state: {state.get('turn')}",
        f"plan states: {state.get('plans')}",
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
        "turn": state.get("turn"),
        "plans": state.get("plans"),
        "observations": [{"severity": s, "message": m} for s, m in observations],
    }


async def check_history(tab, base_url: str, other_session_url: str | None, timeout_s: float = 30) -> dict:
    """Step 9: pre-send vs during vs after-completion vs after-reload vs after switching
    away and back. Pre/during/after-completion are read by the caller from the interval
    captures already taken; this covers the two DOM-destroying actions."""
    before_reload = await transcript_state(tab)
    await tab.reload()
    await wait_for_app_mounted(tab)
    deadline = time.monotonic() + timeout_s
    after_reload = await transcript_state(tab)
    while time.monotonic() < deadline and saved_answers(after_reload) != saved_answers(before_reload):
        await asyncio.sleep(0.25)
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
        deadline = time.monotonic() + timeout_s
        after_switch = await transcript_state(tab)
        while time.monotonic() < deadline and saved_answers(after_switch) != saved_answers(before_reload):
            await asyncio.sleep(0.25)
            after_switch = await transcript_state(tab)
        switch_result["text_length_after_switch_back"] = after_switch.get("text_length")
        switch_result["survived"] = bool(saved_answers(before_reload)) and saved_answers(after_switch) == saved_answers(before_reload)

    return {
        "before_reload_text_length": before_reload.get("text_length"),
        "after_reload_text_length": after_reload.get("text_length"),
        "reload_survived": bool(saved_answers(before_reload)) and saved_answers(after_reload) == saved_answers(before_reload),
        "before_answers": saved_answers(before_reload),
        "after_answers": saved_answers(after_reload),
        "switch": switch_result,
    }


def history_failure_reason(history: dict) -> str:
    """Name the first failed history transition."""
    if not history.get("before_answers"):
        return "No saved answer was visible before navigation."
    if history.get("reload_survived") is not True:
        return "Saved answers changed or disappeared after reload."
    switch = history.get("switch", {})
    if switch.get("attempted") and switch.get("survived") is not True:
        return "Saved answers changed or disappeared after switching conversations."
    return ""


def history_is_preserved(history: dict) -> bool:
    """Require an observed answer match for every attempted history transition."""
    return not history_failure_reason(history)


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
        f"turn phase: {result.turn_phase}  turn ended at: {result.turn_ended_at_s}",
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
            "turn_phase": result.turn_phase,
            "turn_ended_at_s": result.turn_ended_at_s,
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
    inventory = collect_image_inventory(out_dir, "", capture_revision())
    (out_dir / "image_inventory.json").write_text(
        json.dumps({"review_state_default": IMAGE_REVIEW_PENDING, "images": inventory}, indent=2) + "\n",
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
    history_only: str = "",
    continue_path: str = "",
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

    from browser_lifecycle import start_browser, stop_browser

    browser = await start_browser(
        out_dir / "chromium.log",
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

        if history_only:
            if not history_only.startswith("/ai_chat/c/"):
                raise ValueError("The history path must identify a saved conversation.")
            result = ConversationResult(name="history-only", profile="chat", prompt_text="")
            result.session_url = base_url + history_only
            result.history = {"by_resolution": {}}
            destination = out_dir / result.name
            destination.mkdir()
            for resolution, size in resolutions:
                await set_exact_viewport(identity_tab, *size)
                await identity_tab.get(result.session_url)
                await wait_css(identity_tab, "#x-chat-transcript [data-chat-answer], #x-chat-transcript [data-chat-asked]")
                history = await check_history(identity_tab, base_url, base_url + "/ai_chat")
                result.history["by_resolution"][resolution] = history
                reason = history_failure_reason(history)
                if reason:
                    result.observations.append((APPLICATION_ERROR, f"{resolution}: {reason}"))
                filename = f"{resolution}.png"
                (destination / filename).write_bytes(await screenshot(identity_tab, False))
                result.captures[resolution] = [{"file": filename}]
            result.completed_answer_present = all(h["reload_survived"] for h in result.history["by_resolution"].values())
            write_conversation_report(destination, result)
            exit_status = 1 if result.observations else 0
            write_run_index(out_dir, [result], exit_status)
            return [result], exit_status

        if continue_path:
            # One prompt, sent once as the next turn of a saved conversation.
            if not continue_path.startswith("/ai_chat/c/") or len(prompt_names) != 1:
                raise ValueError("--continue needs a saved conversation path and one prompt.")
            name = prompt_names[0]
            _, profile, prompt_text = PROMPTS_BY_NAME[name]
            destination = out_dir / name
            destination.mkdir(parents=True, exist_ok=True)
            await identity_tab.get(base_url + continue_path)
            await wait_for_app_mounted(identity_tab)
            await wait_css(identity_tab, "#x-chat-transcript [data-chat-user]")
            result = await submit_and_observe(
                identity_tab, base_url, identity_network, whitelist, Page(name=name, url=""),
                name, profile, prompt_text, resolutions[0][0], resolutions[0][1], destination,
                TURN_CEILING_S, mode="followup",
                run_started=run_started,
            )
            write_conversation_report(destination, result)
            exit_status = (1 if any(sev == APPLICATION_ERROR for sev, _ in result.observations)
                           else 2 if result.incomplete else 0)
            write_run_index(out_dir, [result], exit_status)
            return [result], exit_status

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
            deadline_s = TURN_CEILING_S

            async def observe_one(i: int) -> ConversationResult:
                res_name, size = resolutions[i]
                return await submit_and_observe(
                    tabs[i], base_url, networks[i], whitelist, page_probe, name, profile,
                    prompt_text, res_name, size, conv_dir, deadline_s,
                    mode="new" if i == 0 else "join",
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
                    merged.document_preview = await asyncio.wait_for(
                        open_last_document_card(tabs[0]), PAGE_CALL_TIMEOUT_S)
                    if merged.document_preview.get("reason") != "no_cards":
                        await asyncio.sleep(0.6)
                        doc_shot = await asyncio.wait_for(screenshot(tabs[0], False), PAGE_CALL_TIMEOUT_S)
                        (conv_dir / "document_preview.png").write_bytes(doc_shot)
                        if merged.document_preview.get("ok") is False:
                            merged.observations.append((
                                DIAGNOSTIC_WARNING,
                                f"a document card exists but would not open: {merged.document_preview}",
                            ))
                except Exception as exc:  # noqa: BLE001
                    merged.observations.append((DIAGNOSTIC_WARNING, f"document preview step failed: {exc}"))

                # Use the conversation list when no other session has completed.
                other_url = next((u for n, u in session_urls.items() if n != name and u), base_url + "/ai_chat")
                try:
                    histories = {}
                    for index, (resolution, _) in enumerate(resolutions):
                        histories[resolution] = await asyncio.wait_for(
                            check_history(tabs[index], base_url, other_url), HISTORY_TIMEOUT_S)
                    merged.history = {"by_resolution": histories}
                    for resolution, history in histories.items():
                        reason = history_failure_reason(history)
                        if reason:
                            merged.observations.append((APPLICATION_ERROR, f"{resolution}: {reason}"))
                except Exception as exc:  # noqa: BLE001
                    merged.observations.append((INCOMPLETE_EXECUTION, f"history check failed: {exc}"))

                if run_followup and name in FOLLOW_UPS and primary.turn_phase != "answered":
                    # A turn in progress keeps the composer closed. The follow-up waits for
                    # an answered first turn, so it is not sent into a running one.
                    merged.observations.append((
                        INCOMPLETE_EXECUTION,
                        f"follow-up not sent: the first turn ended as {primary.turn_phase!r}",
                    ))
                elif run_followup and name in FOLLOW_UPS:
                    followup_dir = conv_dir / "followup"
                    followup_dir.mkdir(exist_ok=True)
                    try:
                        # Opened again after the history check. `submit_and_observe`
                        # submits the follow-up once.
                        await tabs[0].get(merged.session_url)
                        await wait_for_app_mounted(tabs[0])
                        followup_probe = Page(name=f"{name}-followup", url="")
                        fu_deadline = TURN_CEILING_S
                        fu_result = await submit_and_observe(
                            tabs[0], base_url, networks[0], whitelist, followup_probe,
                            f"{name}-followup", profile, FOLLOW_UPS[name], resolutions[0][0],
                            resolutions[0][1], followup_dir, fu_deadline, mode="followup",
                            run_started=run_started,
                        )
                        write_conversation_report(followup_dir, fu_result)
                        # The follow-up result counts toward the conversation verdict.
                        for severity, message in fu_result.observations:
                            merged.observations.append((severity, f"follow-up: {message}"))
                    except Exception as exc:  # noqa: BLE001
                        merged.incomplete = True
                        merged.observations.append((INCOMPLETE_EXECUTION, f"follow-up turn failed: {exc}"))

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
        await stop_browser(browser)

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
    parser.add_argument("--history-only", default="")
    parser.add_argument(
        "--continue", dest="continue_path", default="",
        help="a saved conversation path; the one selected prompt is sent once as its next turn",
    )
    args = parser.parse_args()

    try:
        register_story_prompts(Path(__file__).with_name("chat-acceptance"))
    except (IndexError, ValueError) as error:
        sys.stderr.write(f"error: {error}\n")
        return 2

    try:
        username, password = read_credentials()
    except CredentialError as error:
        sys.stderr.write(f"error: {error}\n")
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
            username, password, not args.no_followup, args.history_only, args.continue_path,
        ))
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"incomplete execution: {type(exc).__name__}: {exc}\n")
        return 2

    print(f"{len(results)} conversation(s) observed; output in {out_dir}; exit {exit_status}")
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
