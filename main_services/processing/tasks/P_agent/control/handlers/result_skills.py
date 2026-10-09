"""The `tool_batch_completed` handler that loads skills after result events.

An object trigger fires when a result of the batch holds a hit of a named type, or a path
with a table or e-mail extension (`facts.is_table_hit`, `facts.is_email_hit`). An event
trigger fires on the first event that makes a method necessary, for example the first
successful read for the citation skill. Code decides both from structured result fields,
so no classifier request is made.

The handler proposes the load. The coordinator drops a skill whose pinned text is still
visible in the model input, and merges two proposals for one skill. A policy batch can load
a skill, and it never starts another batch.
"""

from __future__ import annotations

from typing import Any, Mapping

from tasks.P_agent.control import facts as F
from tasks.P_agent.control.model import API_VERSION, Action, CheckResult, PolicyResult, freeze

OBJECTS = {"table": F.is_table_hit, "email": F.is_email_hit}
EVENTS = ("first_read", "web_search", "browser")


def _event(kind: str, batch, earlier) -> bool:
    if kind == "first_read":
        return bool(F.satisfactory_reads(batch)) and not F.satisfactory_reads(earlier)
    if kind == "web_search":
        return any(f.name == "web_search" and f.status == "ok" for f in batch)
    if kind == "browser":
        return any(f.name.startswith("browser_") for f in batch)
    return False


class Handler:
    api_version = API_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        for name, kinds in (parameters.get("objects") or {}).items():
            unknown = set(kinds) - set(OBJECTS)
            if unknown:
                raise ValueError(f"skill {name!r} names unknown object kinds {sorted(unknown)}")
        for name, kind in (parameters.get("events") or {}).items():
            if kind not in EVENTS:
                raise ValueError(f"skill {name!r} names the unknown event {kind!r}")

    async def evaluate(self, event, context, parameters, services) -> PolicyResult:
        batch = list(context.batch)
        earlier = [f for f in context.results if f.ai_idx < event.anchor_idx]
        actions, checks = [], []
        for name, kinds in (parameters.get("objects") or {}).items():
            if name not in context.listed_skills:
                continue
            hit = next((k for k in kinds if any(OBJECTS[k](f) for f in batch if f.status == "ok")), None)
            if hit:
                actions.append(Action("load_skill", name, freeze({"skill": name, "trigger": hit})))
                checks.append(CheckResult(event.id, f"skill:{name}", "pass", None, (), f"object {hit}"))
        for name, kind in (parameters.get("events") or {}).items():
            if name in context.listed_skills and _event(kind, batch, earlier):
                actions.append(Action("load_skill", name, freeze({"skill": name, "trigger": kind})))
                checks.append(CheckResult(event.id, f"skill:{name}", "pass", None, (), f"event {kind}"))
        searches = [f for f in context.results if f.name in ("search_collections", "search_passages", "web_search")
                    and f.status == "ok"]
        if (len(searches) >= 2 and not any(f.keyword_sources for f in searches[-2:])
                and "no_results" in context.listed_skills):
            actions.append(Action("load_skill", "no_results", freeze({"skill": "no_results", "trigger": "no_keyword_match"})))
        return PolicyResult(checks=tuple(checks), actions=tuple(actions))
