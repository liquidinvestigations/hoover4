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

**Classifier signals.** With `signals` true, three classifier questions read the structured
task (`facts.task_text`) and the recent steps: `stuck`, `answered` and `absent`. A signal
fires after its number of consecutive positive answers. The deterministic ledger (units,
level, progress identities, the strongest-note step and the ending) is computed from the
operation facts before any signal is read.

* `stuck_units` true lets a fired `stuck` signal add one unit to a batch without progress,
  so the classifier advances the levels and the ending. Its default is `not advice`. An
  advisory definition (`advice` true) therefore never changes the ledger, and identical
  operation facts give identical levels and endings for every classifier answer. The
  ledger records the units that the signal added in `signal_units`, and the cause of an
  ending in `stop_cause`.

* `completion` selects what the `answered` signal can do. `none` ignores it. `evidence`
  adds advice to a level note only when the thread holds delivery evidence. When the task
  names its output files or their count (`preparation.requested_output`), the evidence is
  a successful new version of every named file, or of as many distinct files as the count.
  One file of three is not evidence. When the task names no file, completeness stays
  unknown, and a stored file version or a verified citation of a successful read is the
  evidence. The signal is recomputed for every batch and is never kept from an earlier
  batch. The ledger records the comparison in `delivery`.
* `advice` true adds an advice note, whose text names the chat check as its origin, the
  first time in the turn that `stuck` or `absent` fires. The advice proposes a method. It
  states no completion and no quota.
* With `completion` `evidence`, a fired `absent` signal at level 2 or above checks the named
  things of the preparation in the indexes (`absence.check_names`).

No fixed search count or call budget applies.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping

from tasks.P_agent.control import facts as F
from tasks.P_agent.control.handlers.absence import check_names, note_action
from tasks.P_agent.control.model import API_VERSION, Action, CheckResult, PolicyResult, freeze, noul, plain

SEARCH_TOOLS = {"search_collections", "search_passages", "web_search", "folder_search",
                "search_facet_values", "search_histogram", "search_entity_explainer", "doc_search_text", "pdf_search", "table_search_cells"}
METADATA_TOOLS = {"list_collections", "search_facet_values", "search_histogram", "folder_overview"}

SIGNALS = {
    "stuck": ("stuck_w3=", 0.9, 2, "In `steps`, do the searches return no results, or the same results again, step after step?"),
    "answered": ("answered_w4=", 0.3, 1, "Does a result in `steps` give the fact, the list or the count that `request` asks for, even if the agent has not written its answer yet?"),
    "absent": ("absent_w1=", 0.5, 2, "Do the results show that the documents do not contain what `request` asks for?"),
}
COMPLETIONS = ("none", "evidence")

#: The advice notes. Each names its origin, so the agent can tell advice from the task.
STUCK_ADVICE = ("A chat check estimates that the recent searches repeat their results. "
                "The no_results skill describes other forms of a search.")
ABSENT_ADVICE = ("A chat check estimates that the results do not hold what the task asks for. "
                 "State the searched scope before you report an absence.")
COMPLETION_ADVICE = ("A chat check estimates that the results can answer the task. Compare each "
                     "requested part with the sources that you read before you answer.")


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


def delivery(task, results) -> dict:
    """The requested file outputs of `task` compared with the stored file versions.

    `state` is `complete` when the task names its files or their count and the thread
    stored a new version of each, `incomplete` when one is missing, and `unknown` when the
    task names no file or no count. `evidence` is what the completion advice may rely on.
    """
    from tasks.P_agent.control.handlers.preparation import requested_output

    requested = requested_output(task or {})
    delivered = list(dict.fromkeys(f.file_version[0] for f in results
                                   if f.status == "ok" and f.file_version and f.file_version[2]))
    names, count = requested["names"], requested["count"]
    if names or count:
        missing = [n for n in names if n not in delivered]
        complete = not missing and len(delivered) >= count
        return {"state": "complete" if complete else "incomplete", "requested": names,
                "requested_count": count, "delivered": delivered, "missing": missing,
                "evidence": complete}
    evidence = bool(delivered) or (bool(F.satisfactory_reads(results))
                                   and any(f.verified_citations for f in results))
    return {"state": "unknown", "requested": [], "requested_count": 0, "delivered": delivered,
            "missing": [], "evidence": evidence}


def delivery_evidence(results, task=None) -> bool:
    """Whether the thread holds the delivery evidence of `delivery`."""
    return delivery(task, results)["evidence"]


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
        if parameters.get("completion", "evidence") not in COMPLETIONS:
            raise ValueError(f"completion must be one of {', '.join(COMPLETIONS)}")
        for key in ("signals", "advice", "end_turn"):
            if not isinstance(parameters.get(key, key != "advice"), bool):
                raise ValueError(f"{key} must be true or false")
        if not isinstance(parameters.get("stuck_units", False), bool):
            raise ValueError("stuck_units must be true or false")
        if not isinstance(parameters.get("request_chars", 6000), int):
            raise ValueError("request_chars must be an integer")

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
        completion = parameters.get("completion", "evidence")
        replies = {}
        task_text, omitted = F.task_text(context.task or {"objective": {"text": context.request, "source": "user"}},
                                         int(parameters.get("request_chars", 6000)))

        async def signal(label, spec):
            qid, threshold, needed, text = spec
            result = await services.ask({"request": task_text, "steps": context.recent_steps},
                                        {qid: {"type": "noul", "instructions": text}})
            return label, noul(result, qid)
        asked = {k: v for k, v in SIGNALS.items() if completion != "none" or k != "answered"}
        if parameters.get("signals", True):
            answers = await asyncio.gather(*(signal(k, v) for k, v in asked.items()), return_exceptions=True)
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
        # Only a definition that lets the classifier control the ledger adds its unit.
        stuck_units = parameters.get("stuck_units", not parameters.get("advice", False))
        signal_unit = int(bool(stuck_units) and signals["stuck"]["fired"] and not made_progress)
        gained = 0 if made_progress else 1 + refused + churn + signal_unit
        units = 0 if made_progress else units + gained
        if made_progress:
            level = 0
        seen.update(new)
        actions = []
        delivered = delivery(context.task or {"objective": {"text": context.request, "source": "user"}},
                             context.results)
        evidence = delivered["evidence"]
        raised = units >= parameters.get("units_per_level", 3)
        if raised and level < 3:
            level += 1
            units = 0
            pending = ladder(context, context.results)
            text = f"Search progress level {level}.\nSearches already run:\n{summary(searches)}\n"
            if level == 1:
                text += "Search steps still available:\n" + ("\n".join(pending) or "The available search steps are complete.")
            elif level == 2:
                text += (pending[0] if pending else "Write the answer or the report now. State what the collections do not hold and name the searches.")
            else:
                text += "The next reply must be the answer. State the missing facts and the searches that you ran."
            if completion == "evidence" and signals["answered"]["fired"] and evidence:
                text += "\n" + COMPLETION_ADVICE
            actions.append(Action("append_note", f"progress-{level}", freeze({"text": text, "level": level})))
        if parameters.get("advice", False):
            advice = []
            if signals["stuck"]["fired"] and not made_progress and not previous.get("stuck_advised"):
                advice.append(STUCK_ADVICE)
            if signals["absent"]["fired"] and not previous.get("absent_advised"):
                advice.append(ABSENT_ADVICE)
            if advice:
                actions.append(Action("append_note", "progress-advice", freeze({"text": " ".join(advice)})))
        model_steps = context.counters.get("model_steps", 0)
        strongest = None if made_progress else previous.get("strongest_step")
        if level == 3 and strongest is None:
            strongest = model_steps
        stop_cause = ""
        if (parameters.get("end_turn", True) and level == 3 and strongest is not None
                and model_steps - strongest >= parameters.get("steps_after_strongest", 6)):
            stop_cause = ("operations and classifier" if int(previous.get("signal_units", 0)) + signal_unit
                          else "operations")
            source_text = ("No keyword-matched source was found." if not seen else
                           f"The searches found {len(seen)} keyword-matched sources. The agent did not complete its answer.")
            actions.append(Action("end_turn", "progress-end", freeze({"text": "The run ended after repeated searches without progress. " + source_text + "\n\nSearches run:\n" + summary(searches)})))
        absence_records = previous.get("absence_records", [])
        absent_checked = previous.get("absent_checked", False)
        if completion == "evidence" and level >= 2 and signals["absent"]["fired"] and not absent_checked:
            names = (context.turn.get("preparation") or {}).get("names", [])
            absence_records = await check_names(names, context, services)
            actions.extend(note_action(absence_records, context))
            absent_checked = True
        ledger = {"progress_seen": sorted(progress_seen), "level": level, "units": units, "sources": sorted(seen), "searches": searches,
                  "file_versions": sorted(set(previous.get("file_versions", [])) | versions),
                  "repeats": previous.get("repeats", 0) + repeats,
                  "empty_results": previous.get("empty_results", 0) + sum(f.item_count == 0 for f in context.batch),
                  "refused_repeats": previous.get("refused_repeats", 0) + refused,
                  "todo_churn": previous.get("todo_churn", 0) + churn,
                  "todo_goal": todo[-1].todo_goal if todo else previous.get("todo_goal", ""),
                  "todo_closed": todo[-1].todo_closed if todo else previous.get("todo_closed", 0),
                  "signals": signals, "strongest_step": strongest,
                  # The units that a classifier signal added since the last progress.
                  "signal_units": 0 if made_progress else int(previous.get("signal_units", 0)) + signal_unit,
                  "stop_cause": stop_cause,
                  # Recomputed for each batch. An earlier positive answer is not kept.
                  "answered": bool(signals["answered"]["fired"]),
                  "delivery_evidence": evidence, "delivery": delivered, "task_omitted_chars": omitted,
                  "absent_checked": absent_checked, "absence_records": absence_records,
                  "absent_advised": bool(previous.get("absent_advised")
                                         or (parameters.get("advice", False) and signals["absent"]["fired"])),
                  "stuck_advised": bool(previous.get("stuck_advised")
                                        or (parameters.get("advice", False) and signals["stuck"]["fired"]
                                            and not made_progress))}
        return PolicyResult(checks=tuple(checks), actions=tuple(actions), facts=freeze(ledger))
