"""Record progress and apply bounded escalation during a turn.

The handler reads the facts of a batch that the model requested. A policy batch, such as a
skill load or an automatic page read, changes no count and gets no note, so policy actions
never count as repeated work of the model.

**Progress** is any of these operation facts: a new keyword-matched source, a successful
read, a useful metadata listing, a verified citation, or a workspace write or patch that
stored a new version. An unchanged patch, a repeated call and a failed call are no progress.
A batch without progress adds units. `units_per_level` units raise the level by one, up to
3. A batch with progress sets the level to 0. Each raise writes a note with the searches
run and the available search steps. At level 3, `steps_after_strongest` further model steps
without progress end the turn when `end_turn` is true. The ending keeps the delivered files
and names the searches.

**Method advice.** A level note names only the search steps of the relevant methods
(`methods`): the source rules of the task record and the operations of the turn decide
them, and the callable tools alone decide nothing. A turn that read a web page gets no
collection step, and a turn whose task forbids the web gets no web step. A turn without
method evidence gets no step list.

No fixed search count or call budget applies.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from tasks.P_agent.control.model import API_VERSION, Action, CheckResult, PolicyResult, freeze, plain
from tasks.P_agent.notes import note

SEARCH_TOOLS = {"search_collections", "search_passages", "web_search", "folder_search",
                "search_facet_values", "search_histogram", "search_entity_explainer", "doc_search_text", "pdf_search", "table_search_cells"}
METADATA_TOOLS = {"list_collections", "search_facet_values", "search_histogram", "folder_overview"}

#: The tools of each method, for the method evidence of a turn.
WEB_TOOLS = {"web_search", "read_page", "cite_pages"}
COLLECTION_TOOLS = {"search_collections", "search_passages", "folder_search", "folder_list",
                    "folder_overview", "search_facet_values", "search_histogram",
                    "search_entity_explainer", "read_documents", "doc_search_text", "pdf_search",
                    "table_overview", "table_page", "table_cell", "table_search_cells",
                    "table_column_values", "cite_documents", "list_collections"}


def methods(context, results) -> set:
    """The methods that the advice of a turn may name: `collections`, `web`, both or none.

    The active source rules of the task record decide first: a forbidden source gets no
    step. Then the operations of the turn decide: a method that the turn used is relevant.
    A web address in the task, an explicit permission, or a rule that forbids the only
    other method also selects a method. Callable tools alone select none, so an
    uncertain turn gets no method advice and keeps its tool results as they are."""
    from tasks.P_agent.control import task_state

    state = context.task_state or {}
    scope = task_state.source_scope(state)
    tools = context.callable_tools
    web_ok = bool(tools & {"web_search", "read_page"}) and scope["web"] != "forbidden"
    collections_ok = "search_collections" in tools and scope["collections"] != "forbidden"
    web_used = any(f.name in WEB_TOOLS or f.name.startswith("browser_") for f in results)
    collections_used = any(f.name in COLLECTION_TOOLS for f in results)
    direct = bool(task_state.urls(state))
    out = set()
    if web_ok and (web_used or direct or scope["web"] == "allowed"
                   or (scope["collections"] == "forbidden" and not collections_ok)):
        out.add("web")
    if collections_ok and (collections_used or scope["collections"] == "allowed"
                           or scope["web"] == "forbidden"):
        out.add("collections")
    return out


def ladder(context, results):
    """The available search steps of the relevant methods (`methods`) that the stored calls
    have not yet covered."""
    tools = context.callable_tools
    language = getattr(context, "language", "en")
    relevant = methods(context, results)
    searches = [f for f in results if f.name in SEARCH_TOOLS]
    forms = [str(q) for f in searches for q in (list(f.args.get("queries") or []) + [f.args.get("query", "")]) if q]
    pending = []
    collection_searches = [f for f in searches if f.name in COLLECTION_TOOLS]
    if "collections" in relevant:
        if "search_collections" in tools:
            if not any('"' in q for q in forms):
                pending.append(note(language, "note-progress-step-quoted"))
            if not any('"' not in q for q in forms):
                pending.append(note(language, "note-progress-step-variants"))
            filtered = any(any(f.args.get(k) for k in ("facet_filters", "date_after", "date_before", "size_min", "folder_term_id")) for f in collection_searches)
            if not collection_searches or (filtered and not any(not any(f.args.get(k) for k in ("facet_filters", "date_after", "date_before", "size_min", "size_max", "folder_term_id", "filename_only")) for f in collection_searches)):
                pending.append(note(language, "note-progress-step-filters"))
            if "search_facet_values" in tools and filtered and not any(f.name == "search_facet_values" for f in searches):
                pending.append(note(language, "note-progress-step-facets"))
            if "search_histogram" in tools and any(f.args.get("date_after") or f.args.get("date_before") for f in collection_searches) and not any(f.name == "search_histogram" for f in searches):
                pending.append(note(language, "note-progress-step-dates"))
        if "search_passages" in tools and not any(f.name == "search_passages" for f in searches):
            pending.append(note(language, "note-progress-step-passages"))
        folder_request = any(w in context.request.lower() for w in ("folder", "path", "file"))
        for name in ("folder_search", "folder_list"):
            if folder_request and name in tools and not any(f.name == name for f in results):
                pending.append(note(language, "note-progress-step-folder", tool=name))
        if any(f.keyword_sources for f in collection_searches) and not any(f.reads for f in results if f.name in COLLECTION_TOOLS):
            reader = next((t for t in ("read_documents", "doc_search_text") if t in tools), None)
            if reader:
                pending.append(note(language, "note-progress-step-read-hits", tool=reader))
    if "web" in relevant:
        pages = [f for f in results if f.name == "read_page"]
        if "web_search" in tools and not any(f.name == "web_search" for f in searches):
            pending.append(note(language, "note-progress-step-web-search"))
        if any(f.continuation for f in pages) and not any(f.args.get("find") for f in pages):
            pending.append(note(language, "note-progress-step-page-find"))
        if any(f.status == "error" or any(status == "error" for _, status in f.reads) for f in pages):
            pending.append(note(language, "note-progress-step-page-retry"))
    return pending


def summary(searches, language: str = "en"):
    return "\n".join("- " + note(language, "note-progress-search", name=s["name"],
                                  args=json.dumps(s["args"], ensure_ascii=False), items=s["items"],
                                  matches=s["keyword_matches"]) for s in searches[-30:])


def new_versions(batch, seen: set) -> set:
    """The `name@version` keys of the new file versions that the batch stored."""
    return {f"{f.file_version[0]}@{f.file_version[1]}" for f in batch
            if f.status == "ok" and f.file_version and f.file_version[2]} - seen


class Handler:
    api_version = API_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        for key, default in (("units_per_level", 3), ("steps_after_strongest", 6)):
            value = parameters.get(key, default)
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"{key} must be a positive integer")
        if not 5 <= parameters.get("steps_after_strongest", 6) <= 10:
            raise ValueError("steps_after_strongest must be between 5 and 10")
        if not isinstance(parameters.get("end_turn", True), bool):
            raise ValueError("end_turn must be true or false")

    async def evaluate(self, event, context, parameters, services):
        previous = plain(context.turn.get("progress") or {})
        if event.origin == "policy":
            # A policy batch is not work of the model: the ledger stays as it is.
            return PolicyResult(checks=(CheckResult(event.id, "progress", "skipped", None, (),
                                                    "policy batch"),),
                                facts=freeze(previous))
        level, units = int(previous.get("level", 0)), int(previous.get("units", 0))
        seen = set(previous.get("sources", []))
        new = {s for f in context.batch for s in f.keyword_sources} - seen
        searches = list(previous.get("searches", []))
        for f in context.batch:
            if f.name in SEARCH_TOOLS:
                searches.append({"call_id": f.call_id, "name": f.name, "args": plain(f.args),
                                 "items": f.item_count, "keyword_matches": len(f.keyword_sources),
                                 "word_counts": plain(f.word_counts), "status": f.status})
        repeats = sum(f.repeated for f in context.batch)
        refused = sum(f.status == "refused" for f in context.batch)
        todo = [f for f in context.batch if f.name == "update_plan"]
        churn = sum(bool(previous.get("todo_goal"))
                    and f.todo_goal == previous.get("todo_goal", "")
                    and f.todo_closed <= previous.get("todo_closed", 0) for f in todo)
        progress_seen = set(previous.get("progress_seen", []))
        useful = {json.dumps([f.name, plain(f.args)], sort_keys=True) for f in context.batch
                  if (f.status == "ok" and ((f.name in METADATA_TOOLS and (f.item_count or 0) > 0)
                                            or any(status in ("ok", "partial") for _, status in f.reads)))
                  or f.verified_citations > 0}
        versions = new_versions(context.batch, set(previous.get("file_versions", [])))
        gained_results = (useful - progress_seen) | versions
        progress_seen.update(useful - progress_seen)
        made_progress = bool(new or gained_results)
        gained = 0 if made_progress else 1 + refused + churn
        units = 0 if made_progress else units + gained
        if made_progress:
            level = 0
        seen.update(new)
        actions = []
        raised = units >= parameters.get("units_per_level", 3)
        if raised and level < 3:
            level += 1
            units = 0
            pending = ladder(context, context.results)
            language = context.language
            text = (note(language, "note-progress-level", level=level) + "\n"
                    + note(language, "note-progress-searches") + "\n" + summary(searches, language) + "\n")
            if level == 1 and pending:
                text += note(language, "note-progress-available") + "\n" + "\n".join(pending)
            elif level == 1 and methods(context, context.results):
                text += note(language, "note-progress-complete")
            elif level == 2:
                text += (pending[0] if pending else note(language, "note-progress-write-now"))
            else:
                text += note(language, "note-progress-answer-next")
            actions.append(Action("append_note", f"progress-{level}", freeze({"text": text, "level": level})))
        model_steps = context.counters.get("model_steps", 0)
        strongest = None if made_progress else previous.get("strongest_step")
        if level == 3 and strongest is None:
            strongest = model_steps
        if (parameters.get("end_turn", True) and level == 3 and strongest is not None
                and model_steps - strongest >= parameters.get("steps_after_strongest", 6)):
            language = context.language
            source_text = (note(language, "note-progress-ended-none") if not seen else
                           note(language, "note-progress-ended-some", count=len(seen)))
            actions.append(Action("end_turn", "progress-end", freeze({"text": (
                note(language, "note-progress-ended") + " " + source_text + "\n\n"
                + note(language, "note-progress-ended-searches") + "\n" + summary(searches, language))})))
        ledger = {"progress_seen": sorted(progress_seen), "level": level, "units": units, "sources": sorted(seen), "searches": searches,
                  "file_versions": sorted(set(previous.get("file_versions", [])) | versions),
                  "repeats": previous.get("repeats", 0) + repeats,
                  "empty_results": previous.get("empty_results", 0) + sum(f.item_count == 0 for f in context.batch),
                  "refused_repeats": previous.get("refused_repeats", 0) + refused,
                  "todo_churn": previous.get("todo_churn", 0) + churn,
                  "todo_goal": todo[-1].todo_goal if todo else previous.get("todo_goal", ""),
                  "todo_closed": todo[-1].todo_closed if todo else previous.get("todo_closed", 0),
                  "strongest_step": strongest}
        return PolicyResult(actions=tuple(actions), facts=freeze(ledger))
