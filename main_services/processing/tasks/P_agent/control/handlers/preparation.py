"""The `turn_started` handler: the source class, the skill picks and the requirements.

Structured requests classify sources, effort, skills and named things. A completion lists answer requirements.
These requests run together under the hook deadline. Each request preserves its result when another request fails.

The handler proposes at most `max_loads` skills whose scores reach their thresholds.
It sorts by full-precision score and then by name.
A skill tied to source classes is proposed only when its classes include the selected source class.
A documents-only request receives no web skill. A failed request proposes nothing.

A requirement is explicit only when its `words` occur in the request. A generated condition
that the request does not state, such as an invented ranking measure, stays inferred.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

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

    async def evaluate(self, event, context, parameters, services) -> PolicyResult:
        import asyncio

        limit = int(parameters.get("request_chars", 6000))
        request = context.request
        truncated = len(request) > limit
        shown = request[:limit]
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
        questions["effort="] = {"type": "choice", "criteria": {
            "fact": "one fact or a short direct lookup", "list": "a list, count or comparison",
            "research": "research that needs several questions and sources"},
            "instructions": "What type of work does the request need?"}
        if "web" not in context.capabilities:
            questions["web_only="] = {"type": "noul", "instructions":
                "Does the request require only current public web information or opening a public website?"}
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
            if not parameters.get("requirements", True):
                return None
            return await services.complete(REQUIREMENT_PROMPT + shown, 400)

        async def extract_names():
            return await services.ask({"text": shown}, {"names=": {
                "type": "spans",
                "instructions": "Find names of specific people, organisations, document collections, folders or documents in text."}})

        asked, completed, named = await asyncio.gather(ask(), complete(), extract_names(), return_exceptions=True)
        checks = []
        facts: dict[str, Any] = {"request_truncated": truncated}
        actions = []
        if isinstance(asked, BaseException):
            checks.append(CheckResult(event.id, "preparation", "error", None, (), repr(asked)[:300]))
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
            effort = (asked.answers.get("effort=") or {}).get("choice", "research")
            facts["effort"] = effort
            facts["call_budget"] = {"fact": 10, "list": 20, "research": 40}.get(effort, 40)
            choice = (facts["sources"] or {}).get("choice")
            source_note = ""
            if choice in ("documents", "both"):
                source_note = "Search the permitted document collections first. Read their relevant documents. "
                if "web" in context.capabilities:
                    source_note += "Read those documents before using the web. "
            actions.append(Action("append_note", "effort", freeze({"text":
                source_note +
                f"Use 3 to 10 calls for a fact, 10 to 20 for a list, count or comparison, and 20 to 40 for research. "
                f"This request is classed as {effort}, with guidance of {facts['call_budget']} calls. "
                "Cite at least 3 sources when available, or 1 for a single fact. Cite at most 10 sources. "
                "Before an absence answer, run at least 4 distinct searches with 2 tools. "
                "Search each name as a phrase, then as words and variants. Run one search without filters."})))
            web_only = noul(asked, "web_only=")
            if "web" not in context.capabilities and web_only is not None and web_only >= 0.9:
                facts["web_unavailable"] = True
                facts["sources"] = {"choice": "none", "probabilities": {"none": 1.0}}
                actions.append(Action("append_note", "web-unavailable", freeze({"text":
                    "This deployment has no web access. Tell the person that this request needs web access."})))
            choice = (facts["sources"] or {}).get("choice")
            gates = parameters.get("source_skills") or {}
            picks = []
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
            for name, score in ranked(picks)[:int(parameters.get("max_loads", 3))]:
                actions.append(Action("load_skill", name, freeze({"skill": name, "score": score})))
        if completed is None:
            facts["requirements_status"] = "disabled"
        elif isinstance(completed, BaseException):
            facts["requirements_status"] = "error"
        else:
            facts["requirements_status"] = completed.status
            facts["requirements"] = _requirements(completed.text, request) if completed.status == "ok" else []
            if truncated:
                facts["requirements_status"] = "partial: the request was cut for the questions"
        names = []
        if not isinstance(named, BaseException):
            for item in (named.answers.get("names=") or {}).get("items", [])[:8]:
                name = str(item.get("text") or "").strip()
                name = re.sub(r"\s+(?:collection|dataset)$", "", name, flags=re.I)
                if name and name.casefold() in shown.casefold():
                    names.append(name)
        for match in re.finditer(r"\b(?:folder|collection)\s+(?:called|named)\s+(?:[\"']([^\"'\n]+)[\"']|([\w./-]+))", shown, re.I):
            names.append((match.group(1) or match.group(2)).rstrip("."))
        facts["names"] = list(dict.fromkeys(names))[:8]
        if hasattr(services, "suggestions"):
            records = await check_names(facts["names"], context, services)
            facts["absence_records"] = records
            actions.extend(note_action(records, context))
        return PolicyResult(checks=tuple(checks), actions=tuple(actions), facts=freeze(facts))
