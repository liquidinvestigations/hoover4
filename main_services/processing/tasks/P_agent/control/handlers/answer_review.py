"""The `answer_drafted` handler: citation findings and semantic checks of one draft.

Deterministic findings come from code. The coordinator runs the existing citation check
(`citations.needs_repair`) and gives its result in `context.turn["citation"]`. This handler
adds one more code rule: a bracketed word such as `[newspaste]` at the end of a sentence,
which looks like a source marker and is not a handle that a citation returned. A bracket
that holds a link, a number or more than one word is ordinary text.

Semantic checks ask systemone about the draft and the verified passages of the session:

* `supported`: for each factual block with handles, whether the passages of its handles
  state every claim. A block without a handle has no associated evidence, so its result is
  `unknown`, never a defect.
* `names`: a `spans` question copies person names that the passages spell differently. Code
  keeps a name only when a passage holds a close spelling, which is the proposed correction.
* `requirements`: each explicit requirement of the preparation. An `evidence` requirement
  asks whether the passages establish it, an `output_form` requirement whether the answer
  meets it. An inferred requirement is not checked.

A score at or below `threshold` is a defect. Each family has a `repair` switch. A defect of a
family whose switch is off is recorded and starts no round. Scores are not calibrated
probabilities. A failed request gives `error` or `unknown` results, and the deterministic
findings still apply.
"""

from __future__ import annotations

import asyncio
import difflib
import re
from typing import Any, Mapping

from tasks.P_agent.control.facts import justified_absence
from tasks.P_agent.control.handlers_common import answer_blocks
from tasks.P_agent.control.model import (
    API_VERSION, CheckResult, PolicyResult, freeze, noul,
)

INSTRUCTIONS = ("A research agent wrote the answer below to an investigator's request. "
                "verified_passages are the exact source texts that the citation tool confirmed "
                "for this conversation. Judge the answer only against the request and these "
                "passages.")
MARKER = re.compile(r"\[([A-Za-z][\w.&-]{1,40})\](?!\()(?=[\s.,;:!?)]|$)")
HANDLE = re.compile(r"^[DW]\d+$")
NAME_WORDS = re.compile(r"\b[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+){0,3}")
FAMILIES = ("supported", "names", "requirements")


def unissued_markers(answer: str) -> list[str]:
    """Bracketed source-like words that are not citation handles."""
    out = []
    for match in MARKER.finditer(answer or ""):
        word = match.group(1)
        if HANDLE.match(word) or word.lower() in ("sic", "edit", "note", "citation", "source"):
            continue
        if word not in out:
            out.append(word)
    return out


def _passages_of(handles, passages) -> list[dict]:
    return [p for p in passages if p.get("handle") in handles]


def proposed_spelling(name: str, passages) -> str:
    """A spelling of `name` that a passage holds and that differs from it, or empty."""
    text = " ".join(q for p in passages for q in p.get("quotes") or [])
    if name.lower() in text.lower():
        return ""
    best, score = "", 0.0
    for candidate in set(NAME_WORDS.findall(text)):
        ratio = difflib.SequenceMatcher(None, name.lower(), candidate.lower()).ratio()
        if ratio > score:
            best, score = candidate, ratio
    return best if score >= 0.8 else ""


class Handler:
    api_version = API_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        for family in FAMILIES:
            setting = parameters.get(family) or {}
            if not isinstance(setting, Mapping):
                raise ValueError(f"{family} must be an object")
            threshold = setting.get("threshold", 0.05)
            if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
                raise ValueError(f"the threshold of {family} must be between 0 and 1")
        unknown = set(parameters) - set(FAMILIES) - {"markers"}
        if unknown:
            raise ValueError(f"unknown parameters {sorted(unknown)}")

    async def evaluate(self, event, context, parameters, services) -> PolicyResult:
        answer = context.draft
        passages = list(context.turn.get("passages") or [])
        checks = []
        if (parameters.get("markers") or {}).get("enabled", True):
            for word in unissued_markers(answer):
                checks.append(CheckResult(event.id, f"marker:{word}", "defect", None, (),
                                          "a bracketed source name that no citation returned",
                                          freeze({"mandatory": bool((parameters.get("markers") or {}).get("repair", True)),
                                                  "family": "markers",
                                                  "correction": f"Replace [{word}] with a handle that cite_documents or cite_pages returned, or remove it."})))
        blocks = [b for b in answer_blocks(answer) if b["claim"]]
        settings = {f: dict(parameters.get(f) or {}) for f in FAMILIES}
        questions: dict[str, Any] = {}
        targets: dict[str, tuple] = {}
        if settings["supported"].get("enabled", True):
            for block in blocks:
                handles = re.findall(r"[DW]\d+", " ".join(re.findall(r"\[[^\]]*\]", block["text"])))
                own = _passages_of({f"[{h}]" for h in handles}, passages)
                if not own:
                    checks.append(CheckResult(event.id, block["id"], "unknown", None, (),
                                              "no verified passage is associated with the block",
                                              freeze({"family": "supported", "text": block["text"][:300]})))
                    continue
                qid = f"{block['id']}_supported="
                questions[qid] = {"type": "noul", "instructions":
                                  f"Is every factual claim in answer block {block['id']} stated by a verified passage?"}
                targets[qid] = ("supported", block, [p["handle"] for p in own])
        if settings["requirements"].get("enabled", True):
            requirements = (context.turn.get("preparation") or {}).get("requirements") or []
            for k, req in enumerate(r for r in requirements if r.get("explicit")):
                if req["basis"] == "evidence" and justified_absence(context):
                    checks.append(CheckResult(event.id, f"req{k + 1}", "pass", None, (),
                                              "the answer states the absence that searches establish",
                                              freeze({"family": "requirements", "mandatory": False})))
                    continue
                qid = f"req{k + 1}_" + ("met=" if req["basis"] == "output_form" else "established=")
                if req["basis"] == "output_form":
                    text = f"Does the answer meet the condition '{req['text']}'?"
                else:
                    text = f"Do the verified passages establish that the answer meets the condition '{req['text']}'?"
                questions[qid] = {"type": "noul", "instructions": text}
                targets[qid] = ("requirements", {"id": f"req{k + 1}", "text": req["text"]}, [])
        state = {"request": context.request[:1500],
                 "answer_blocks": {b["id"]: b["text"][:900] for b in blocks},
                 "verified_passages": [{"handle": p.get("handle"), "source": p.get("source"),
                                        "quotes": list(p.get("quotes") or [])[:4]}
                                       for p in passages[:16]]}

        async def ask_main():
            return await services.ask(state, questions, INSTRUCTIONS) if questions else None

        async def ask_names():
            if not settings["names"].get("enabled", True) or not passages:
                return None
            return await services.ask(
                {"text": answer[:6000], "verified_passages": state["verified_passages"]},
                {"mismatch=": {"type": "spans", "criteria": {"max_tokens": 10, "max_items": 10},
                               "instructions": "Copy every person name in `text` that the verified passages spell differently."}},
                "`text` is an answer that a research agent wrote. `verified_passages` are its confirmed sources.")

        main, names = await asyncio.gather(ask_main(), ask_names(), return_exceptions=True)
        if isinstance(main, BaseException):
            checks.append(CheckResult(event.id, "semantic", "error", None, (), repr(main)[:300]))
        elif main is not None:
            for qid, (family, target, handles) in targets.items():
                score = noul(main, qid)
                threshold = float(settings[family].get("threshold", 0.05))
                if score is None:
                    checks.append(CheckResult(event.id, target["id"], "unknown", None, tuple(handles),
                                              main.status, freeze({"family": family})))
                    continue
                defect = score <= threshold
                correction = ("Cite a passage that states this claim, correct the claim to what the passage states, or remove it."
                              if family == "supported" else
                              f"Make the answer meet this condition with sources that establish it, or state that the sources do not establish it: {target['text']}")
                checks.append(CheckResult(event.id, target["id"], "defect" if defect else "pass",
                                          score, tuple(handles), family, freeze({
                                              "family": family, "mandatory": defect and bool(settings[family].get("repair", False)),
                                              "text": target["text"][:300], "correction": correction})))
        if isinstance(names, BaseException):
            checks.append(CheckResult(event.id, "names", "error", None, (), repr(names)[:300]))
        elif names is not None:
            items = ((names.answers.get("mismatch=") or {}).get("items") or []) if names.status == "ok" else []
            if names.status != "ok":
                checks.append(CheckResult(event.id, "names", "unknown", None, (), names.status))
            for item in items:
                name = str(item.get("text") or "").strip()
                proposal = proposed_spelling(name, passages) if name else ""
                status = "defect" if proposal else "unknown"
                checks.append(CheckResult(event.id, f"name:{name}", status, None, (),
                                          "the passages spell the name differently" if proposal
                                          else "no passage holds a close spelling", freeze({
                                              "family": "names",
                                              "mandatory": bool(proposal) and bool(settings["names"].get("repair", False)),
                                              "text": name, "proposal": proposal,
                                              "correction": f"Spell {name} as the source does: {proposal}." if proposal else ""})))
        return PolicyResult(checks=tuple(checks))
