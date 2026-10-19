"""The `turn_started` handler: the source class, the skill picks and the named things.

Three independent children can run. `ask` is one structured request that classifies the
sources, the skills and the flags. `names` extracts the named things of the request and
checks them in the indexes. `requirements` is a completion that lists answer conditions. It
runs only when the definition enables it, because no live hook reads its result.

Each child records a typed outcome in the facts (`children`): `ok`, `timeout`, `error`,
`cancelled`, `skipped` or `disabled`. The handler waits for the children until shortly
before the hook deadline, then cancels and awaits the unfinished ones, and returns the
results of the completed ones. So a slow child cannot discard the skill picks of another.

The handler proposes at most `max_loads` skills whose scores reach their thresholds.
It sorts by full-precision score and then by name.
A skill tied to source classes is proposed only when its classes include the selected source class.
A documents-only request receives no web skill. A failed request proposes nothing.

With `classifier` false the handler makes no classifier request. The deterministic report
trigger (`report_skill`) applies in both modes: a task that names a file, a report or a
draft as its output loads the `report` skill before the first write.

The classifier input is the structured task of the turn (`facts.task_text`), so the focused
objective of a board explore comes first and a cut request is marked as cut.

A requirement is explicit only when its `words` occur in the request. A generated condition
that the request does not state, such as an invented ranking measure, stays inferred.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Mapping

from tasks.P_agent.control import facts as F
from tasks.P_agent.control.handlers.absence import check_names, note_action
from tasks.P_agent.control.model import (
    API_VERSION, Action, CheckResult, PolicyResult, freeze, noul, ranked,
)

DEFAULT_SOURCES = {
    "documents": "First search the selected collections for a requested message, invitation, document, attachment or fact, unless the request explicitly requires web sources.",
    "web": "The request explicitly requires public web sources, a public website or current web information, and asks for no stored document.",
    "both": "First read requested documents from the selected collections, then check explicitly requested public web sources.",
    "browser": "driving a web browser on a named address: open, click, type",
    "overview": "counts, types, sizes or folders of what the collections hold",
    "none": "no source: a greeting, a question about the agent, or arithmetic",
}

REQUIREMENT_PROMPT = (
    "List the conditions that a correct answer to this request must meet, as a JSON array of "
    "2 to 6 objects. Each object has the keys condition, scope, basis and words. condition is "
    "one short checkable sentence. scope is whole for the answer as a whole, item for each "
    "listed item, or relation for a comparison between items. basis is output_form for the "
    "layout or the count of the answer, source for the kind of source that it may use, or "
    "evidence for a fact that sources must establish. words copies the exact words of the "
    "request that state the condition, or is empty when the request does not state it. Write "
    "only the JSON array.\n\nRequest: ")

SCOPES = ("whole", "item", "relation")
BASES = ("output_form", "source", "evidence")

#: The words of a task that asks for a file as its output. The match is deterministic.
REPORT_REQUEST = re.compile(
    r"\b(?:reports?|files?|memos?|drafts?|write-?ups?|markdown|dossiers?|briefing notes?)\b"
    r"|\.md\b", re.IGNORECASE)

#: The seconds before the hook deadline at which the handler stops waiting for children.
RETURN_MARGIN_SECONDS = 0.75


def _requirements(text: str, request: str) -> list[dict]:
    match = re.search(r"\[.*\]", text or "", re.S)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except ValueError:
        return []
    out = []
    lowered = request.lower()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("condition"), str):
            continue
        words = str(item.get("words") or "").strip()
        out.append({
            "text": item["condition"].strip()[:300],
            "scope": item.get("scope") if item.get("scope") in SCOPES else "whole",
            "basis": item.get("basis") if item.get("basis") in BASES else "evidence",
            "words": words[:200],
            "explicit": bool(words) and words.lower() in lowered,
        })
    return out[:6]


def asks_for_file(task: Mapping[str, Any]) -> bool:
    """Whether the objective, the deliverables or the corrections of a task name a file."""
    texts = []
    for key in ("objective", "deliverables", "corrections"):
        value = task.get(key)
        if isinstance(value, Mapping):
            texts.append(str(value.get("text") or ""))
        elif isinstance(value, (list, tuple)):
            texts.extend(str(v.get("text") or "") for v in value if isinstance(v, Mapping))
    return any(REPORT_REQUEST.search(t) for t in texts)


async def gather_children(children: dict, services, margin: float = RETURN_MARGIN_SECONDS):
    """Run named coroutines at once. Return `(results, outcomes)`.

    The wait ends when every child ends, or `margin` seconds before the hook deadline. An
    unfinished child is cancelled and awaited, so no late result arrives after the return.
    `results` holds the value of each child that ended without an exception. `outcomes`
    holds `{"status", "duration_ms"}` for every child."""
    started = time.monotonic()
    clock = getattr(services, "remaining", None)

    def remaining() -> float:
        return float(clock()) if callable(clock) else float("inf")

    tasks = {name: asyncio.ensure_future(coro) for name, coro in children.items()}
    ended_at: dict[str, int] = {}

    def mark(name):
        return lambda _task: ended_at.setdefault(name, int((time.monotonic() - started) * 1000))

    for name, task in tasks.items():
        task.add_done_callback(mark(name))
    try:
        if tasks:
            left = remaining()
            await asyncio.wait(list(tasks.values()),
                               timeout=None if left == float("inf") else max(0.0, left - margin))
    finally:
        late = [t for t in tasks.values() if not t.done()]
        for task in late:
            task.cancel()
        if late:
            await asyncio.gather(*late, return_exceptions=True)
    results, outcomes = {}, {}
    for name, task in tasks.items():
        ms = ended_at.get(name, int((time.monotonic() - started) * 1000))
        if task.cancelled():
            status = "timeout" if remaining() <= margin + 0.05 else "cancelled"
            outcomes[name] = {"status": status, "duration_ms": ms}
        elif task.exception() is not None:
            exc = task.exception()
            outcomes[name] = {"status": "error", "duration_ms": ms,
                              "error": f"{type(exc).__name__}: {exc}"[:300]}
        else:
            results[name] = task.result()
            outcomes[name] = {"status": "ok", "duration_ms": ms}
    return results, outcomes


class Handler:
    api_version = API_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        skills = parameters.get("skills") or {}
        if not isinstance(skills, Mapping):
            raise ValueError("skills must map skill names to settings")
        for name, setting in skills.items():
            threshold = (setting or {}).get("threshold", 0.9)
            if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
                raise ValueError(f"the threshold of skill {name!r} must be between 0 and 1")
        if not isinstance(parameters.get("max_loads", 3), int):
            raise ValueError("max_loads must be an integer")
        if not isinstance(parameters.get("flags") or {}, Mapping):
            raise ValueError("flags must map flag names to questions")
        if not isinstance(parameters.get("request_chars", 6000), int):
            raise ValueError("request_chars must be an integer")
        for key in ("classifier", "report_skill", "names", "source_note", "requirements"):
            if not isinstance(parameters.get(key, True), bool):
                raise ValueError(f"{key} must be true or false")

    async def evaluate(self, event, context, parameters, services) -> PolicyResult:
        limit = int(parameters.get("request_chars", 6000))
        task = context.task or {"objective": {"text": context.request, "source": "user"}}
        shown, omitted = F.task_text(task, limit)
        request = context.request
        checks: list = []
        facts: dict[str, Any] = {"request_truncated": bool(omitted), "task_omitted_chars": omitted}
        actions: list = []
        picks: list = []
        if (parameters.get("report_skill", True) and "report" in context.listed_skills
                and asks_for_file(task)):
            picks.append(("report", 1.0))
            checks.append(CheckResult(event.id, "skill:report", "pass", None, (), "the task names a file"))
        if not parameters.get("classifier", True):
            facts["children"] = {"ask": {"status": "disabled"}, "names": {"status": "disabled"},
                                 "requirements": {"status": "disabled"}}
            for name, score in picks:
                actions.append(Action("load_skill", name, freeze({"skill": name, "score": score})))
            return PolicyResult(checks=tuple(checks), actions=tuple(actions), facts=freeze(facts))

        sources = {k: v for k, v in (parameters.get("sources") or DEFAULT_SOURCES).items()
                   if k in context.capabilities and (k not in ("documents", "overview", "both") or context.collections)}
        sources.setdefault("none", DEFAULT_SOURCES["none"])
        if "web" not in context.capabilities and "documents" in sources:
            sources["documents"] = "Search and read the selected document collections."
        available = [v for k, v in sources.items() if k != "none"]
        web_guidance = ("Choose web when the request requires public web sources or a named website. "
                        if "web" in context.capabilities else "")
        instructions = ("An investigator sends the request below to a research agent. "
                        "Judge only what the request asks the agent to find or read. "
                        "Use the previous conversation to resolve references in the current request. "
                        "An explicit new source restriction takes precedence. "
                        "Writing an answer as a table does not require the table skill. "
                        "When collections exist, choose documents for a request about a message, invitation, document or attachment. "
                        + web_guidance +
                        f"Available sources: {', '.join(available) or 'none'}. "
                        f"Selected collections: {', '.join(context.collections) or 'none'}.")
        questions: dict[str, Any] = {
            "sources=": {"type": "choice", "criteria": sources,
                         "instructions": "Which available sources does this request explicitly require? An invitation or document means documents first."
                         + (" A later web check means both." if "both" in sources else "")}}
        if "web" not in context.capabilities:
            questions["web_only="] = {"type": "noul", "instructions":
                "Does the request ask for public information or a public website, without asking about stored documents? Include past events and public court decisions."}
        candidates = {}
        for name, setting in (parameters.get("skills") or {}).items():
            skill = context.listed_skills.get(name)
            if skill is None:
                continue
            text = " ".join(p for p in (skill.get("description"), skill.get("terms"),
                                        skill.get("not_for")) if p)
            questions[f"skill_{name}="] = {
                "type": "noul",
                "instructions": f"Should the agent read the skill `{name}` before it starts? "
                                f"It teaches: {text}"}
            candidates[name] = dict(setting or {})
        flags = dict(parameters.get("flags") or {})
        for flag, question in flags.items():
            questions[f"flag_{flag}="] = {"type": "noul", "instructions": str(question)}

        async def ask():
            return await services.ask({"request": shown, "conversation": context.turn.get("conversation") or []}, questions,
                                      str(parameters.get("instructions") or instructions))

        async def complete():
            return await services.complete(REQUIREMENT_PROMPT + shown, 400)

        async def names():
            named = await services.ask({"text": shown}, {"names=": {
                "type": "spans",
                "instructions": "Find names of specific people, organisations, document collections, folders or documents in text."}})
            found = []
            for item in (named.answers.get("names=") or {}).get("items", [])[:8]:
                name = str(item.get("text") or "").strip()
                name = re.sub(r"\s+(?:collection|dataset)$", "", name, flags=re.I)
                if name and name.casefold() in shown.casefold():
                    found.append(name)
            for match in re.finditer(r"\b(?:folder|collection)\s+(?:called|named)\s+(?:[\"']([^\"'\n]+)[\"']|([\w./-]+))", shown, re.I):
                found.append((match.group(1) or match.group(2)).rstrip("."))
            found = list(dict.fromkeys(found))[:8]
            records = await check_names(found, context, services) if hasattr(services, "suggestions") else []
            return found, records

        children = {"ask": ask()}
        if parameters.get("names", True):
            children["names"] = names()
        if parameters.get("requirements", False):
            children["requirements"] = complete()
        results, outcomes = await gather_children(children, services)
        for name in ("names", "requirements"):
            outcomes.setdefault(name, {"status": "disabled"})
        facts["children"] = outcomes

        asked = results.get("ask")
        if asked is None:
            checks.append(CheckResult(event.id, "preparation", "error", None, (),
                                      outcomes["ask"]["status"]))
        else:
            status = "pass" if asked.status == "ok" else ("skipped" if asked.status == "skipped" else "error")
            source = asked.answers.get("sources=")
            facts["sources"] = ({"choice": source["choice"],
                                 "probabilities": dict(source.get("probabilities") or {})}
                                if source else None)
            checks.append(CheckResult(event.id, "sources", status if source else "unknown",
                                      float(source["probabilities"][source["choice"]]) if source else None,
                                      (), asked.status, freeze(facts["sources"] or {})))
            facts["flags"] = {}
            for flag in flags:
                score = noul(asked, f"flag_{flag}=")
                facts["flags"][flag] = score
                checks.append(CheckResult(event.id, f"flag:{flag}",
                                          "pass" if score is not None else "unknown", score, (),
                                          asked.status))
            web_only = noul(asked, "web_only=")
            if "web_only=" in questions:
                facts["requested_web_score"] = web_only
                checks.append(CheckResult(event.id, "web_only", "pass" if web_only is not None else "unknown",
                                          web_only, (), asked.status))
            if "web" not in context.capabilities and web_only is not None and web_only >= 0.9:
                facts["web_unavailable"] = True
                facts["sources"] = {"choice": "none", "probabilities": {"none": 1.0}}
                actions.append(Action("append_note", "web-unavailable", freeze({"text":
                    "This deployment has no web access. Tell the person that this request needs web access."})))
            choice = (facts["sources"] or {}).get("choice")
            # The source order of a chat turn. A board brief gives its own source rules.
            if (parameters.get("source_note", True) and choice in ("documents", "both")
                    and not facts.get("web_unavailable") and context.run_kind != "board"):
                text = "Search the permitted document collections first. Read their relevant documents."
                if "web" in context.capabilities:
                    text += " Read those documents before using the web."
                actions.append(Action("append_note", "sources", freeze({"text": text})))
            gates = parameters.get("source_skills") or {}
            for name, setting in candidates.items():
                score = noul(asked, f"skill_{name}=")
                threshold = float(setting.get("threshold", 0.9))
                classes = set(gates.get(name) or []) & context.capabilities
                allowed = name not in gates or bool(classes) and (choice is None or choice in classes)
                if score is not None and score >= threshold and allowed:
                    picks.append((name, score))
                checks.append(CheckResult(event.id, f"skill:{name}",
                                          "pass" if score is not None else "unknown", score, (),
                                          "picked" if (name, score) in picks else
                                          ("gated by source class" if not allowed else asked.status)))
        seen = set()
        for name, score in ranked(picks)[:int(parameters.get("max_loads", 3)) + (1 if ("report", 1.0) in picks else 0)]:
            if name in seen:
                continue
            seen.add(name)
            actions.append(Action("load_skill", name, freeze({"skill": name, "score": score})))
        completed = results.get("requirements")
        if outcomes["requirements"]["status"] == "disabled":
            facts["requirements_status"] = "disabled"
        elif completed is None:
            facts["requirements_status"] = outcomes["requirements"]["status"]
        else:
            facts["requirements_status"] = completed.status
            facts["requirements"] = _requirements(completed.text, request) if completed.status == "ok" else []
            if omitted:
                facts["requirements_status"] = "partial: the request was cut for the questions"
        named = results.get("names")
        facts["names"] = named[0] if named else []
        if named:
            facts["absence_records"] = named[1]
            actions.extend(note_action(named[1], context))
        return PolicyResult(checks=tuple(checks), actions=tuple(actions), facts=freeze(facts))
