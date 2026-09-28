"""The reads at the start of a run, for `POST /preload`.

A run that starts a thread reads its role skill and its general skills before its first
model call (`skill_store.always_read`). The worker writes these reads into the thread as
synthetic `read_skill` calls, so the model sees them as calls of its own.

The first turn of a chat also asks the classifier three things about the request, at the
same time: the request type and the technique and stumble skills that the run should read.
A planner run asks the request type only. The
classifier is the `systemone` route of the structured model server, at
`LLM_CLASSIFIER_URL`. Each form holds the bytes that were calibrated
(`preload_forms.json`), so a change to a form text or a threshold moves the answers.

A failed classifier request gives no picks for its part, and the run still reads its
always-read skills. `/preload` fails only when the step context cannot be built.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple

import httpx
from pydantic import Field

from research_agent import skill_store
from research_agent.skill_store import SkillContext, always_read, listed_skills
from research_agent.skill_tools import READ_SKILL, read_skill_result
from research_agent.steps import StepRun, _context

log = logging.getLogger(__name__)

#: The classifier forms, with the bytes of the calibration: the instructions, the question
#: template, and the classes and skill names of each form.
FORMS: Dict[str, Any] = json.loads(
    (Path(__file__).parent / "preload_forms.json").read_text(encoding="utf-8"))

#: The classes of the type form, in the order of the form. A tie goes to the earlier class.
CLASS_ORDER: Tuple[str, ...] = tuple(FORMS["types"]["classes"])

#: The classifier reads at most this many characters of the request, as calibrated.
REQUEST_MAX_CHARS = 1500
#: The limits of one classifier request.
CLASSIFIER_TIMEOUT_SECONDS = 5.0
CLASSIFIER_CONNECT_SECONDS = 2.0

#: A second class is kept when its score is at least this.
SECOND_CLASS_MIN = 0.5
#: A technique skill is read when its score is at least this, at most `TECHNIQUE_CAP`.
TECHNIQUE_MIN = 0.7
TECHNIQUE_CAP = 3
#: A stumble skill is read when its score is at least this, at most `STUMBLE_CAP`.
STUMBLE_MIN = 0.9
STUMBLE_CAP = 2

#: The parts of the classifier that each value of `classify` asks.
PARTS = {"none": (), "types": ("types",), "all": ("types", "skills")}


class PreloadRequest(StepRun):
    """The body of `POST /preload`."""

    request_text: str = Field(description="The opening request of the run")
    classify: Literal["none", "types", "all"] = "none"
    already_read: List[str] = Field(
        default_factory=list, description="The skills that earlier turns of the chat read")


@dataclass
class Classification:
    """The answers of the classifier for one request."""

    state: str = "off"                       # off, ok, partial or failed
    error: str = ""
    ms: int = 0
    scores: Dict[str, Dict[str, float]] = field(default_factory=dict)   # part -> id -> p


# ------------------------------------------------------------------------ the forms


def classifier_url() -> str:
    return os.getenv("LLM_CLASSIFIER_URL", "").strip()


def types_body(text: str, model: str) -> Dict[str, Any]:
    form = FORMS["types"]
    questions = {
        f"{name}=": {"type": "noul",
                     "instructions": form["question"].format(name=name, definition=definition)}
        for name, definition in form["classes"].items()
    }
    return _body(form["instructions"], text, questions, model)


def skills_body(text: str, model: str, skills: Dict[str, skill_store.Skill]) -> Dict[str, Any]:
    form = FORMS["skills"]
    questions = {
        f"{name}=": {"type": "noul", "instructions": form["question"].format(
            name=name, description=skills[name].description)}
        for name in form["names"] if name in skills
    }
    return _body(form["instructions"], text, questions, model)


def _body(instructions: str, text: str, questions: Dict[str, Any], model: str) -> Dict[str, Any]:
    # Each question id ends with `=`, because the server refuses a bare word as an id (422).
    return {"model": model, "instructions": instructions,
            "state": {"request": (text or "")[:REQUEST_MAX_CHARS]}, "questions": questions}


def scores_of(answer: Dict[str, Any]) -> Dict[str, float]:
    """The probability of yes of each `noul` answer, by the id without its trailing `=`."""
    out: Dict[str, float] = {}
    for qid, value in (answer.get("answers") or {}).items():
        if isinstance(value, dict) and isinstance(value.get("noul"), (int, float)):
            out[qid[:-1] if qid.endswith("=") else qid] = float(value["noul"])
    return out


# ------------------------------------------------------------------------ the picks


def request_classes(scores: Dict[str, float]) -> List[str]:
    """The top class, and the second when its score is at least `SECOND_CLASS_MIN`."""
    known = [(name, p) for name, p in scores.items() if name in CLASS_ORDER]
    if not known:
        return []
    ranked = sorted(known, key=lambda kv: (-kv[1], CLASS_ORDER.index(kv[0])))
    kept = [ranked[0][0]]
    if len(ranked) > 1 and ranked[1][1] >= SECOND_CLASS_MIN:
        kept.append(ranked[1][0])
    return kept


def _ranked(pairs: Iterable[Tuple[float, str]], cap: int) -> List[Tuple[str, float]]:
    return [(n, p) for p, n in sorted(pairs, key=lambda x: (-x[0], x[1]))][:cap]


def skill_picks(scores: Dict[str, float], ctx: SkillContext, group: str, threshold: float,
                cap: int) -> List[Tuple[str, float]]:
    """The listed skills of one group to read, best first."""
    listed = {s.name for s in listed_skills(ctx) if s.group == group}
    return _ranked(((p, n) for n, p in scores.items() if n in listed and p >= threshold), cap)


# ------------------------------------------------------------------------ the requests


def _client() -> httpx.AsyncClient:
    """The client of the classifier requests. A test replaces it with a stub transport."""
    return httpx.AsyncClient(timeout=httpx.Timeout(CLASSIFIER_TIMEOUT_SECONDS,
                                                   connect=CLASSIFIER_CONNECT_SECONDS))


async def _ask(client: httpx.AsyncClient, url: str, key: str, body: Dict[str, Any]) -> Dict[str, float]:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    response = await client.post(url, json=body, headers=headers)
    response.raise_for_status()
    return scores_of(response.json())


async def classify(text: str, parts: Sequence[str], summaries: Dict[str, str],
                   skills: Optional[Dict[str, skill_store.Skill]] = None) -> Classification:
    """Send the requests of `parts` at the same time, and return their scores."""
    url = classifier_url()
    if not url or not parts:
        return Classification()
    from research_agent.agent import _read_secret

    key = _read_secret("LLM_API_KEY")
    model = os.getenv("LLM_MODEL", "")
    skills = skill_store.SKILLS if skills is None else skills
    bodies = {"types": lambda: types_body(text, model),
              "skills": lambda: skills_body(text, model, skills)}
    started = time.monotonic()
    async with _client() as client:
        answers = await asyncio.gather(
            *(_ask(client, url, key, bodies[part]()) for part in parts), return_exceptions=True)
    result = Classification(ms=int((time.monotonic() - started) * 1000))
    errors = []
    for part, answer in zip(parts, answers):
        if isinstance(answer, BaseException):
            log.warning("preload: the %s request of the classifier failed: %s", part, answer)
            errors.append(f"{part}: {type(answer).__name__}: {answer}"[:300])
        else:
            result.scores[part] = answer
    result.error = "; ".join(errors)
    result.state = ("ok" if not errors else "failed" if len(errors) == len(parts)
                    else "partial")
    return result


# ------------------------------------------------------------------------ the route


def _read(name: str, args: Dict[str, Any], content: str, status: str) -> Dict[str, Any]:
    return {"id": "", "name": name, "args": args, "content": content, "status": status,
            "error_class": "tool_error" if status == "error" else ""}


async def run_preload(agent: Any, request: PreloadRequest) -> Dict[str, Any]:
    """The reads of one run start, and the answers of the classifier."""
    context = await _context(agent, request)
    snapshot = context.snapshot
    ctx = getattr(context, "skill_context", None) or snapshot.skill_context
    parts = PARTS[request.classify]
    found = await classify(request.request_text, parts, dict(snapshot.summaries))
    type_scores = found.scores.get("types", {})
    classes = request_classes(type_scores)
    # Only a planner renders its skill with the classes and its model's window, which set the
    # packing numbers of `method_planner`. For every other run kind, a synthetic read is the
    # same text as a later read of the model. The copy is stored nowhere.
    read_ctx = (replace(ctx, request_classes=tuple(classes),
                        model_id=getattr(context, "model_id", "") or "")
                if request.kind == "planner" else ctx)

    skill_scores = found.scores.get("skills", {})
    technique = skill_picks(skill_scores, ctx, "technique", TECHNIQUE_MIN, TECHNIQUE_CAP)
    stumble = skill_picks(skill_scores, ctx, "stumble", STUMBLE_MIN, STUMBLE_CAP)

    seen = set(request.already_read)
    reads: List[Dict[str, Any]] = []
    listed = {s.name for s in listed_skills(ctx)}
    for name in always_read(ctx) + [n for n, _ in technique] + [n for n, _ in stumble]:
        # A skill that the run does not list would give a refusal, so it is not read.
        if name in seen or name not in listed:
            continue
        seen.add(name)
        reads.append(_read(READ_SKILL, {"name": name}, read_skill_result(name, read_ctx), "ok"))
    return {
        "request_classes": classes,
        "class_scores": type_scores,
        "picks": {"technique": [list(p) for p in technique],
                  "stumble": [list(p) for p in stumble]},
        "reads": reads,
        "classifier": {"state": found.state, "error": found.error, "ms": found.ms},
    }


__all__ = [
    "CLASS_ORDER", "Classification", "FORMS", "PreloadRequest", "REQUEST_MAX_CHARS",
    "classifier_url", "classify", "request_classes", "run_preload", "scores_of",
    "skill_picks", "skills_body", "types_body",
]
