"""Record search progress and apply bounded escalation during a turn."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping

from tasks.P_agent.control.handlers.absence import check_names, note_action
from tasks.P_agent.control.model import API_VERSION, Action, CheckResult, PolicyResult, freeze, noul, plain

SEARCH_TOOLS = {"search_collections", "search_passages", "web_search", "folder_search",
                "search_facet_values", "search_histogram", "search_entity_explainer", "doc_search_text", "pdf_search", "table_search_cells"}
SIGNALS = {
    "stuck": ("stuck_w3=", 0.9, 2, "In `steps`, do the searches return no results, or the same results again, step after step?"),
    "answered": ("answered_w4=", 0.3, 1, "Does a result in `steps` give the fact, the list or the count that `request` asks for, even if the agent has not written its answer yet?"),
    "absent": ("absent_w1=", 0.5, 2, "Do the results show that the documents do not contain what `request` asks for?"),
}


def ladder(context, results):
    """The available search steps that the stored calls have not yet covered."""
    tools = context.callable_tools
    searches = [f for f in results if f.name in SEARCH_TOOLS]
    forms = [str(q) for f in searches for q in (list(f.args.get("queries") or []) + [f.args.get("query", "")]) if q]
    pending = []
    if "search_collections" in tools:
        if not any('"' in q for q in forms):
            pending.append("Search each name as a quoted phrase with search_collections.")
        if not any('"' not in q for q in forms):
            pending.append("Search unquoted words and name variants. Read word counts and spelling candidates.")
        filtered = any(any(f.args.get(k) for k in ("facet_filters", "date_after", "date_before", "size_min", "folder_term_id")) for f in searches)
        if not searches or (filtered and not any(not any(f.args.get(k) for k in ("facet_filters", "date_after", "date_before", "size_min", "size_max", "folder_term_id", "filename_only")) for f in searches)):
            pending.append("Remove filters one at a time and run a search without filters.")
        if "search_facet_values" in tools and filtered and not any(f.name == "search_facet_values" for f in searches):
            pending.append("Verify filter values with search_facet_values.")
        if "search_histogram" in tools and any(f.args.get("date_after") or f.args.get("date_before") for f in searches) and not any(f.name == "search_histogram" for f in searches):
            pending.append("Verify dates with search_histogram.")
    if "search_passages" in tools and not any(f.name == "search_passages" for f in searches):
        pending.append("Search a content description with search_passages.")
    folder_request = any(w in context.request.lower() for w in ("folder", "path", "file"))
    for name in ("folder_search", "folder_list"):
        if folder_request and name in tools and not any(f.name == name for f in results):
            pending.append(f"Use {name} for the requested folder, path or file.")
    if any(f.keyword_sources for f in searches) and not any(f.reads for f in results):
        reader = next((t for t in ("read_documents", "doc_search_text") if t in tools), None)
        if reader:
            pending.append(f"Read the best 1 to 3 hits with {reader}.")
    source = ((context.turn.get("preparation") or {}).get("sources") or {}).get("choice")
    if source in ("web", "both", "browser") and "web_search" in tools and not any(f.name == "web_search" for f in searches):
        pending.append("Search the web and read the best pages when the request allows the web.")
    return pending


def summary(searches):
    return "\n".join(f"- {s['name']} {json.dumps(s['args'], ensure_ascii=False)}: "
                     f"{s['items']} items, {s['keyword_matches']} keyword matches." for s in searches[-30:])


class Handler:
    api_version = API_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        for key, default in (("units_per_level", 3), ("steps_after_strongest", 6)):
            value = parameters.get(key, default)
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"{key} must be a positive integer")
        if not 5 <= parameters.get("steps_after_strongest", 6) <= 10:
            raise ValueError("steps_after_strongest must be between 5 and 10")

    async def evaluate(self, event, context, parameters, services):
        previous = plain(context.turn.get("progress") or {})
        level, units = int(previous.get("level", 0)), int(previous.get("units", 0))
        seen = set(previous.get("sources", []))
        new = {s for f in context.batch for s in f.keyword_sources} - seen
        searches = list(previous.get("searches", []))
        for f in context.batch:
            if f.name in SEARCH_TOOLS:
                searches.append({"call_id": f.call_id, "name": f.name, "args": plain(f.args),
                                 "items": f.item_count, "keyword_matches": len(f.keyword_sources),
                                 "word_counts": plain(f.word_counts), "status": f.status})
        replies = {}
        async def signal(label, spec):
            qid, threshold, needed, text = spec
            result = await services.ask({"request": context.request[:1500], "steps": context.recent_steps},
                                        {qid: {"type": "noul", "instructions": text}})
            return label, noul(result, qid)
        if parameters.get("signals", True):
            answers = await asyncio.gather(*(signal(k, v) for k, v in SIGNALS.items()), return_exceptions=True)
            replies = dict(a for a in answers if not isinstance(a, BaseException))
        signals, checks = {}, []
        for label, (qid, threshold, needed, _) in SIGNALS.items():
            score = replies.get(label)
            streak = int((previous.get("signals", {}).get(label) or {}).get("streak", 0)) + 1 if score is not None and score >= threshold else 0
            signals[label] = {"score": score, "streak": streak, "fired": streak >= needed}
            checks.append(CheckResult(event.id, qid, "pass" if score is not None else "unknown", score, (),
                                      "signal fired" if streak >= needed else "no signal", freeze({"threshold": threshold})))
        repeats = sum(f.repeated for f in context.batch)
        refused = sum(f.status == "refused" for f in context.batch)
        todo = [f for f in context.batch if f.name in ("write_todo", "edit_todo", "mark_todo")]
        churn = sum(f.name == "write_todo" and bool(previous.get("todo_goal"))
                    and f.todo_goal == previous.get("todo_goal", "")
                    and f.todo_closed <= previous.get("todo_closed", 0) for f in todo)
        gained = 0 if new else 1 + refused + churn + int(signals["stuck"]["fired"])
        units = 0 if new else units + gained
        seen.update(new)
        actions = []
        over_budget = len([f for f in context.results if f.origin == "model"]) > int((context.turn.get("preparation") or {}).get("call_budget", 40))
        budget_raised = bool(previous.get("budget_raised"))
        raised = units >= parameters.get("units_per_level", 3) or (over_budget and not budget_raised)
        if raised and level < 3:
            level += 1
            units = 0
            budget_raised |= over_budget
            pending = ladder(context, context.results)
            text = f"Search progress level {level}.\nSearches already run:\n{summary(searches)}\n"
            if level == 1:
                text += "Search steps still available:\n" + ("\n".join(pending) or "The available search steps are complete.")
            elif level == 2:
                text += (pending[0] if pending else "Write the answer now. State what the collections do not hold and name the searches.")
            else:
                text += "The next reply must be the answer. State the missing facts and the searches that you ran."
            if signals["answered"]["fired"] or previous.get("answered"):
                text += " A result already gives what the request asks for. Write the answer."
            actions.append(Action("append_note", f"progress-{level}", freeze({"text": text, "level": level})))
        model_steps = context.counters.get("model_steps", 0)
        strongest = previous.get("strongest_step")
        if level == 3 and strongest is None:
            strongest = model_steps
        if level == 3 and strongest is not None and model_steps - strongest >= parameters.get("steps_after_strongest", 6):
            source_text = ("No keyword-matched source was found." if not seen else
                           f"The searches found {len(seen)} keyword-matched sources. The agent did not complete its answer.")
            actions.append(Action("end_turn", "progress-end", freeze({"text": "The run ended after repeated searches without progress. " + source_text + "\n\nSearches run:\n" + summary(searches)})))
        absence_records = previous.get("absence_records", [])
        absent_checked = previous.get("absent_checked", False)
        if level >= 2 and signals["absent"]["fired"] and not absent_checked:
            names = (context.turn.get("preparation") or {}).get("names", [])
            absence_records = await check_names(names, context, services)
            actions.extend(note_action(absence_records, context))
            absent_checked = True
        ledger = {"level": level, "units": units, "sources": sorted(seen), "searches": searches,
                  "repeats": previous.get("repeats", 0) + repeats,
                  "empty_results": previous.get("empty_results", 0) + sum(f.item_count == 0 for f in context.batch),
                  "refused_repeats": previous.get("refused_repeats", 0) + refused,
                  "todo_churn": previous.get("todo_churn", 0) + churn,
                  "todo_goal": todo[-1].todo_goal if todo else previous.get("todo_goal", ""),
                  "todo_closed": todo[-1].todo_closed if todo else previous.get("todo_closed", 0),
                  "signals": signals, "strongest_step": strongest,
                  "answered": bool(previous.get("answered") or signals["answered"]["fired"]),
                  "budget_raised": budget_raised, "absent_checked": absent_checked,
                  "absence_records": absence_records}
        return PolicyResult(checks=tuple(checks), actions=tuple(actions), facts=freeze(ledger))
