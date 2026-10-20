"""The `tool_batch_completed` handler that loads skills after result events.

An object trigger fires when a result of the batch holds a hit of a named type, or a path
with a table or e-mail extension (`facts.is_table_hit`, `facts.is_email_hit`). An event
trigger fires on the first event that makes a method necessary, for example the first
successful read for the citation skill. Code decides both from structured result fields,
so no classifier request is made.

The events:

* `first_read`: the first successful read of the turn.
* `web_search`: a successful web search of the model.
* `browser`: a call of a browser tool by the model.
* `page_read_recovery`: a `read_page` result that failed, or that holds a page without
  text, a cut page or a find result, so the next call needs the web method. It includes
  the automatic page reads of a policy, which the model did not request. A refused
  argument error is not one.
* `first_write`: the first successful workspace write or patch of the turn, so later edits
  have the file method.
* `workspace_error`: a failed workspace write or patch, such as a citation finding or a
  version mismatch.
* `argument_error`: a call whose arguments the agent service, a tool server or a website
  route refused (`facts.ARGUMENT_ERRORS`, `facts.VALIDATION_TEXT`).
* `unknown_document`: a document or table call that named no readable document.


**Method events.** Every definition maps the tool results of a method to its skill
(`METHOD_EVENTS`): a successful web search and a page read that needs recovery load
`web_research`, and a browser call loads `browser_use`. A definition can map the same skill
in `events`, which replaces the method mapping of that skill, and `methods` false turns the
method mapping off. A skill loads only when the turn lists it, so a turn without the tool of
a method loads none of its text.

The handler proposes the load. The coordinator drops a skill whose pinned text is still
visible in the model input, and merges two proposals for one skill. A policy batch can load
a skill, and it never starts another batch.
"""

from __future__ import annotations

from typing import Any, Mapping

from tasks.P_agent.control import facts as F
from tasks.P_agent.control.model import API_VERSION, Action, CheckResult, PolicyResult, freeze

OBJECTS = {"table": F.is_table_hit, "email": F.is_email_hit}
EVENTS = ("first_read", "web_search", "browser", "page_read_recovery", "first_write",
          "workspace_error", "argument_error", "unknown_document")
#: The skill of each method and the result events that make it necessary.
METHOD_EVENTS = {"web_research": ("web_search", "page_read_recovery"), "browser_use": ("browser",)}
#: The tools that name a document by its hash.
DOCUMENT_TOOLS = ("read_documents", "doc_metadata", "doc_email", "doc_sources", "doc_search_text",
                  "list_document_entities", "cite_documents", "table_overview", "table_page",
                  "table_cell", "table_column_values", "table_search_cells")


def _writes(facts) -> list:
    return [f for f in facts if f.name in F.MUTATION_TOOLS and f.status == "ok" and f.file_version]


def _event(kind: str, batch, earlier) -> bool:
    if kind == "first_read":
        return bool(F.satisfactory_reads(batch)) and not F.satisfactory_reads(earlier)
    if kind == "web_search":
        return any(f.name == "web_search" and f.status == "ok" and f.origin == "model" for f in batch)
    if kind == "browser":
        return any(f.name.startswith("browser_") and f.origin == "model" for f in batch)
    if kind == "page_read_recovery":
        # An argument error is `refused` and loads the argument skill instead.
        return any(f.name == "read_page" and (f.status == "error" or any(status in ("error", "partial")
                                                                          for _, status in f.reads))
                   for f in batch)
    if kind == "first_write":
        return bool(_writes(batch)) and not _writes(earlier)
    if kind == "workspace_error":
        return any(f.name in F.MUTATION_TOOLS and f.status in ("error", "refused") for f in batch)
    if kind == "argument_error":
        return any(f.error_code in F.ARGUMENT_ERRORS for f in batch)
    if kind == "unknown_document":
        return any(f.name in DOCUMENT_TOOLS and f.error_code == "not_found" for f in batch)
    return False


class Handler:
    api_version = API_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        for name, kinds in (parameters.get("objects") or {}).items():
            unknown = set(kinds) - set(OBJECTS)
            if unknown:
                raise ValueError(f"skill {name!r} names unknown object kinds {sorted(unknown)}")
        for name, kinds in (parameters.get("events") or {}).items():
            kinds = [kinds] if isinstance(kinds, str) else list(kinds)
            unknown = [k for k in kinds if k not in EVENTS]
            if unknown or not kinds:
                raise ValueError(f"skill {name!r} names the unknown event {unknown or kinds!r}")
        if not isinstance(parameters.get("methods", True), bool):
            raise ValueError("methods must be true or false")

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
        events = dict(METHOD_EVENTS) if parameters.get("methods", True) else {}
        events.update(parameters.get("events") or {})
        for name, kinds in events.items():
            kinds = [kinds] if isinstance(kinds, str) else list(kinds)
            kind = next((k for k in kinds if _event(k, batch, earlier)), None)
            if name in context.listed_skills and kind:
                actions.append(Action("load_skill", name, freeze({"skill": name, "trigger": kind})))
                checks.append(CheckResult(event.id, f"skill:{name}", "pass", None, (), f"event {kind}"))
        searches = [f for f in context.results if f.name in ("search_collections", "search_passages", "web_search")
                    and f.status == "ok"]
        if (len(searches) >= 2 and not any(f.keyword_sources for f in searches[-2:])
                and "no_results" in context.listed_skills):
            actions.append(Action("load_skill", "no_results", freeze({"skill": "no_results", "trigger": "no_keyword_match"})))
        return PolicyResult(checks=tuple(checks), actions=tuple(actions))
