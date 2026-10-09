"""L1: page captures that hold no content, after a batch with `read_page` results.

Structured failures come first. A section that gave no text already has the evidence status
`error` (`reports._read_page`), and the model reads that failure in the result. The other
sections are ambiguous only when their body is shorter than `max_body_chars`, because the
measured empty captures (cookie notices, reference stubs, not-found pages) are short. One
systemone request asks the three measured questions for each such section, and a section
is flagged when it has no fact about its title or is only boilerplate or a not-found page.

A flag adds one note that names the page and asks for another source. It changes no source
text and refuses no call. A failed request flags nothing.
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

from tasks.P_agent.control.handlers_common import page_sections
from tasks.P_agent.control.model import (
    API_VERSION, Action, CheckResult, PolicyResult, freeze, noul,
)

INSTRUCTIONS = ("A research agent read a web page. `title` is the page title. `body` is the "
                "captured text of the page, without its title.")
QUESTIONS = {
    "facts": "Does `body` contain at least one sentence that states a fact about the subject in `title`?",
    "boilerplate": ("Is `body` only a cookie notice, a privacy notice, a menu, a reference list "
                    "heading, repository navigation, or a not-found message?"),
    "not_found": "Does `body` say that the requested item or page was not found?",
}
NOTE = "The capture of {urls} holds no article text. Read another source. Do not cite this page."


class Handler:
    api_version = API_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        for key in ("facts_below", "boilerplate_above", "not_found_above"):
            value = parameters.get(key, 0.5)
            if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValueError(f"{key} must be between 0 and 1")
        if not isinstance(parameters.get("max_body_chars", 2500), int):
            raise ValueError("max_body_chars must be an integer")

    async def evaluate(self, event, context, parameters, services) -> PolicyResult:
        limit = int(parameters.get("max_body_chars", 2500))
        sections = []
        for fact in context.batch:
            if fact.name != "read_page" or fact.status != "ok":
                continue
            ok = {key for key, status in fact.reads if status in ("ok", "partial")}
            for title, url, body in page_sections(services.message_text(fact.idx)):
                if url in ok and len(body) < limit:
                    sections.append((fact.idx, title, url, body))
        if not sections:
            return PolicyResult()
        questions = {f"{key}=": {"type": "noul", "instructions": text}
                     for key, text in QUESTIONS.items()}
        results = await asyncio.gather(*(
            services.ask({"title": title, "body": body[:3000]}, questions, INSTRUCTIONS)
            for _, title, _, body in sections))
        checks, flagged = [], []
        for (idx, title, url, body), result in zip(sections, results):
            scores = {key: noul(result, f"{key}=") for key in QUESTIONS}
            if any(v is None for v in scores.values()):
                checks.append(CheckResult(event.id, url, "unknown", None, (str(idx),),
                                          result.status, freeze(scores)))
                continue
            flag = (scores["facts"] < float(parameters.get("facts_below", 0.05))
                    or scores["boilerplate"] > float(parameters.get("boilerplate_above", 0.95))
                    or scores["not_found"] > float(parameters.get("not_found_above", 0.95)))
            checks.append(CheckResult(event.id, url, "defect" if flag else "pass",
                                      scores["facts"], (str(idx),), "short capture",
                                      freeze(scores)))
            if flag:
                flagged.append(url)
        actions = ()
        if flagged:
            actions = (Action("append_note", "L1", freeze({"text": NOTE.format(urls=", ".join(flagged)),
                                                            "urls": flagged})),)
        return PolicyResult(checks=tuple(checks), actions=actions)
