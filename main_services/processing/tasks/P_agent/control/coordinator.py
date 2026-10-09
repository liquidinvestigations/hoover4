"""Persist one decision for each chat event and apply its actions.

The opening row stores the pinned definition and agent assets. Each hook evaluates its rules under one deadline.
The coordinator merges actions in rule order and reserves message indexes and transcript sequence numbers.
It stores the decision before writing action rows. The workflow starts external calls after the activity returns.

A retry reuses the stored decision and writes missing rows at their reserved keys.
The coordinator re-reads the event row before storing a decision. A late attempt preserves an existing decision.

The opening human row holds the preparation decision. The batch or draft AI row holds its hook decision.
The coordinator owns the usage.control field. Model and tool writers finish before it updates that field.
Stored notes determine repair and discovery counts. An older citation note without a control record counts as one repair round.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import replace
from typing import Any, Optional

from tasks.P_agent.control import definitions, facts as F, registry
from tasks.P_agent.control.classifier import Classifier, Deadline
from tasks.P_agent.control.model import (
    Action, CheckResult, ControlEvent, PolicyContext, PolicyResult, action_id, check_dict,
    digest, freeze, plain,
)

log = logging.getLogger(__name__)

#: The `tool_name` of the transcript row of a note between two model steps.
BATCH_NOTE_NAME = "control_note"
#: The kinds of note that the coordinator writes.
BATCH_NOTE = "batch_note"
DRAFT_NOTE = "draft_note"
#: The prefix of a policy call id.
POLICY_CALL_PREFIX = "ctl-"
#: The most addresses that one `read_page` call reads. Mirrors `READ_PAGE_MAX_URLS` of the
#: browser server.
READ_PAGE_MAX_URLS = 6
PROFILES = {True: "full_research", False: "internal_search"}


def capabilities_of(tools) -> frozenset:
    names = set(tools)
    classes = {"none"}
    if "search_collections" in names:
        classes.update(("documents", "overview"))
    if names & {"web_search", "read_page"}:
        classes.add("web")
    if any(t.startswith("browser_") for t in names):
        classes.add("browser")
    if {"documents", "web"} <= classes:
        classes.add("both")
    return frozenset(classes)


def profile_of(internet_tools: bool, capabilities=None) -> str:
    profile = PROFILES[bool(internet_tools)]
    if capabilities is None:
        return profile
    return profile + (":web" if "web" in capabilities else ":documents")


def control_of(message) -> dict:
    value = message.usage.get("control") if message is not None else None
    return dict(value) if isinstance(value, dict) else {}


def decide_repair(has_defects: bool, rounds_started: int, model_limit_reached: bool,
                  limit: int = 2) -> bool:
    """Return whether the draft can start another repair round within `limit`."""
    return has_defects and rounds_started < limit and not model_limit_reached


def counters(messages) -> dict:
    """The repair rounds, the discovery notes and the applied actions of each rule."""
    from tasks.P_agent import citations

    out: dict[str, int] = {"repair_rounds": 0, "discovery_notes": 0,
                           "model_steps": sum(m.role == "ai" and F.origin_of(m) == "model" for m in messages)}
    for m in messages:
        control = control_of(m)
        if m.role == "human" and citations.is_citation_note(m):
            if not control or control.get("repair"):
                out["repair_rounds"] += 1
            if control.get("discovery"):
                out["discovery_notes"] += 1
        for decision in (control.get("decisions") or {}).values():
            for act in decision.get("actions") or []:
                key = f"rule:{act.get('rule_id')}"
                out[key] = out.get(key, 0) + 1
    return out


# ------------------------------------------------------------------------------ services


class Services:
    """`PolicyServices` of one event: classifier requests and stored message texts."""

    def __init__(self, classifier: Classifier, messages, row=None, params=None, trace=None):
        self.classifier = classifier
        self._messages = messages
        self._by_idx = {m.idx: m for m in messages}
        self.row, self.params = row, params
        self.trace = trace or {}

    def for_rule(self, rule):
        return Services(self.classifier, self._messages, self.row, self.params,
                        {"rule_id": rule.id, "handler": rule.handler.name})

    async def ask(self, state, questions, instructions=""):
        return await self.classifier.ask(state, questions, instructions, trace=self.trace)

    async def complete(self, prompt, max_tokens=300):
        return await self.classifier.complete(prompt, max_tokens, trace=self.trace)

    async def suggestions(self, names, kind="pages", collections=()):
        return await asyncio.to_thread(self._backend, "search/suggestions", {
            "collectionname": list(collections or (self.params.allowed_collections if self.params else [])),
            "words": list(names), "kind": kind})

    def _backend(self, path, body):
        import requests

        remaining = self.remaining()
        if remaining <= 0.05 or self.row is None:
            return {"partial": True, "word_counts": [], "suggestions": []}
        headers = {"x-hoover4-user": self.row.username,
                   "x-hoover4-collections": ",".join(self.params.allowed_collections or [])}
        base = os.getenv("AGENT_API_BASE_URL", "http://hoover4-website:8080").rstrip("/")
        try:
            response = requests.post(base + "/api/agent/v1/" + path, headers=headers,
                                     json=body, timeout=(min(3, remaining), remaining))
            if response.status_code == 200:
                return response.json()
        except requests.RequestException:
            pass
        return {"partial": True, "word_counts": [], "suggestions": []}

    def message_text(self, ref) -> str:
        message = self._by_idx.get(int(ref))
        return message.content if message is not None else ""

    def remaining(self) -> float:
        return self.classifier.deadline.remaining()


async def evaluate(definition, event: ControlEvent, context: PolicyContext,
                   services: Services, deadline: Deadline) -> list[tuple[Any, Optional[PolicyResult], dict]]:
    """Run the rules of one hook at the same time. Returns (rule, result, record) in rule
    order. A rule that fails or passes the deadline has no result and an error record."""
    handlers = registry.load()
    stale = set(definitions.stale_rules(definition))
    rules = definition.rules_for(event.hook)

    async def one(rule):
        started = time.monotonic()
        if set(rule.requires_tools) - context.callable_tools:
            return PolicyResult(checks=(CheckResult(rule.id, rule.id, "skipped", None, (),
                                                    "tool unavailable"),)), {"status": "skipped"}
        if rule.id in stale:
            return None, {"status": "error", "error": "the handler code changed after the turn started"}
        try:
            result = await handlers[rule.handler.name].handler.evaluate(
                event, context, rule.parameters, services.for_rule(rule) if hasattr(services, "for_rule") else services)
            if not isinstance(result, PolicyResult):
                raise TypeError("the handler returned no PolicyResult")
            return result, {"status": "ok", "duration_ms": int((time.monotonic() - started) * 1000)}
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a failed rule is recorded, the run goes on
            log.warning("control rule %s failed: %s", rule.id, exc, exc_info=True)
            return None, {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:300],
                          "duration_ms": int((time.monotonic() - started) * 1000)}

    tasks = [asyncio.ensure_future(one(rule)) for rule in rules]
    try:
        while True:
            pending = [t for t in tasks if not t.done()]
            if not pending:
                break
            if deadline.cancelled():
                raise asyncio.CancelledError()
            if deadline.remaining() <= 0:
                break
            await asyncio.wait(pending, timeout=min(0.5, deadline.remaining() + 0.05))
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    out = []
    for rule, task in zip(rules, tasks):
        if task.cancelled():
            out.append((rule, None, {"status": "timeout", "error": "the hook deadline passed"}))
        else:
            result, record = task.result()
            out.append((rule, result, record))
    return out


# ---------------------------------------------------------------------------- the store


def write_control(row, message, control: dict) -> None:
    """Rewrite one thread message with `control` in its usage. Every other usage key
    stays."""
    from database import agent_runs

    usage = {**message.usage, "control": control}
    agent_runs.write_message(row.username, row.session_id, row.thread_id, message.run_id or row.run_id,
                             replace(message, usage_json=json.dumps(usage, default=str)))


def _message(messages, idx: int):
    return next((m for m in messages if m.idx == idx), None)


# ------------------------------------------------------------------------- the activity


def _agent_post(params, path: str, body: dict, seconds: float) -> dict:
    from tasks.P_agent.activities import agent_url_for
    from tasks.P_agent.steps import _post_json

    return _post_json(f"{agent_url_for(params.internet_tools)}{path}", body, seconds)


def _step_body(row, params) -> dict:
    from tasks.P_agent.steps import _step_run

    return _step_run(row, params)


def _pin(row, messages, params) -> dict:
    """The control record of the turn. When the opening row has none, resolve the active
    definition and the agent's assets, and store both on the opening row."""
    opening = messages[0]
    control = control_of(opening)
    if control.get("definition"):
        return control
    snapshot = _agent_post(params, "/control_snapshot", {**_step_body(row, params)}, min(5, params.deadline_seconds))
    assets = {k: snapshot.get(k) for k in ("revision", "system_prompt", "system_prompt_digest",
                                           "prompt_override", "skills", "callable_tools",
                                           "catalogue_version", "profile")}
    capabilities = capabilities_of(assets.get("callable_tools") or [])
    definition = definitions.resolve(profile_of(params.internet_tools, capabilities))
    services = Services(Classifier(Deadline(2)), messages, row, params)
    listing = services._backend("collections/list", {}) if params.allowed_collections else {"collections": []}
    collections = [c["collectionname"] for c in listing.get("collections", []) if c.get("collectionname")]
    control = {"definition": definition.record(), "assets": assets,
               "capabilities": sorted(capabilities), "collections": collections,
               "conversation": _conversation(row),
               "revision": digest([definition.revision, assets.get("revision")]),
               "decisions": {}}
    write_control(row, opening, control)
    return control


def _conversation(row) -> list[dict]:
    """Return bounded context from the last two ended turns of this session."""
    from database import agent_runs

    out = []
    for thread in agent_runs.read_earlier_threads(row.username, row.session_id, row.turn_seq)[-2:]:
        previous = agent_runs.read_messages(row.username, row.session_id, thread)
        if not previous:
            continue
        answer = next((m.content for m in reversed(previous)
                       if m.role == "ai" and m.content and not m.tool_calls), "")
        preparation = _turn_facts(previous).get("preparation") or {}
        out.append({"request": (previous[0].content or "")[:2000], "answer": answer[:3000],
                    "sources": (preparation.get("sources") or {}).get("choice")})
    return out


def _anchor(params, messages):
    """The row of the event: the opening row, the batch's `ai` message, or the draft's."""
    if params.hook == "turn_started":
        return messages[0]
    if params.anchor_idx >= 0:
        return _message(messages, params.anchor_idx)
    return next((m for m in reversed(messages) if m.role == "ai"
                 and F.origin_of(m) == "model"), None)


def _turn_facts(messages) -> dict:
    """The facts that the turn's preparation decision stored, by handler name."""
    decision = (control_of(messages[0]).get("decisions") or {}).get("turn_started") or {}
    facts = dict(decision.get("facts") or {})
    for message in messages:
        for recorded in (control_of(message).get("decisions") or {}).values():
            if recorded.get("event", {}).get("hook") == "tool_batch_completed":
                facts.update(recorded.get("facts") or {})
    return facts


def _passages(entries) -> list[dict]:
    out = []
    for entry in entries:
        ref = entry.get("reference") or {}
        if entry.get("kind") != "citation" or entry.get("status") != "ok" or not ref.get("handle"):
            continue
        quotes = [q for q in ([ref.get("quote")] + list(ref.get("quotes") or [])
                              + list(ref.get("terms") or [])) if isinstance(q, str) and q]
        out.append({"handle": ref["handle"], "source": ref.get("url") or ref.get("path") or "",
                    "quotes": quotes[:6]})
    return out


def _visible_skills(row, params, messages) -> Optional[set]:
    from tasks.P_agent.steps import _earlier_turns
    from tasks.P_agent.stream_writer import run_message

    try:
        answer = _agent_post(params, "/control_snapshot", {
            **_step_body(row, params), "visibility_only": True,
            "messages": [run_message(m, row.thread_id) for m in messages],
            "earlier": _earlier_turns(row)}, 30)
    except Exception as exc:  # noqa: BLE001 - no visibility means no load
        log.warning("[P_agent] run %s: skill visibility was not read: %s", row.run_id, exc)
        return None
    return set(answer.get("visible_skills") or [])


def _next_positions(row, messages) -> tuple[int, int]:
    """The first free thread index and transcript seq. Every row of the thread, the call
    results of every reply and the compaction rows reserve their indexes."""
    from tasks.P_agent.steps import reply_end_idx

    idx = 0
    for m in messages:
        idx = max(idx, m.idx + 1)
        if m.role == "ai":
            idx = max(idx, reply_end_idx(m))
    return idx, row.next_seq


def _merge(definition, evaluated, event, control, counts, visible, listed) -> tuple[list, list, dict]:
    """The actions of one event in rule order, with duplicates and repeats removed."""
    actions: list[dict] = []
    checks: list[dict] = []
    facts: dict = {}
    seen_skills: set = set()
    for rule, result, record in evaluated:
        if result is None:
            checks.append({"rule_id": rule.id, "target_id": rule.id, "status": "error",
                           "score": None, "input_refs": [], "reason": record.get("error", ""),
                           "detail": {}})
            continue
        checks.extend({**check_dict(c), "rule_id": rule.id} for c in result.checks)
        if result.facts:
            facts[rule.handler.name] = plain(result.facts)
        if rule.frequency == "turn" and counts.get(f"rule:{rule.id}", 0):
            continue
        for position, act in enumerate(result.actions):
            item = {"id": action_id(event.id, rule.revision, act.target_id, position),
                    "rule_id": rule.id, "kind": act.kind, "target": act.target_id,
                    "arguments": plain(act.arguments)}
            if act.kind == "load_skill":
                skill = str(act.arguments.get("skill") or act.target_id)
                if skill in seen_skills or skill not in listed:
                    continue
                if visible is None or skill in visible:
                    continue
                seen_skills.add(skill)
            actions.append(item)
    return actions, checks, facts


def _policy_calls(actions, assets) -> list[dict]:
    """Convert load and call actions into tool calls.

    Each skill uses read_skill. Page addresses share one read_page call.
    """
    calls = []
    pages: list[str] = []
    page_action = None
    for act in actions:
        if act["kind"] == "load_skill":
            calls.append({"action_id": act["id"], "name": "read_skill",
                          "args": {"name": act["arguments"].get("skill") or act["target"]}})
        elif act["kind"] == "call_tools":
            for call in act["arguments"].get("calls") or []:
                if call.get("name") == "read_page":
                    page_action = page_action or act["id"]
                    for url in (call.get("args") or {}).get("urls") or []:
                        if url not in pages:
                            pages.append(url)
                else:
                    calls.append({"action_id": act["id"], "name": call["name"],
                                  "args": dict(call.get("args") or {})})
    if pages:
        calls.append({"action_id": page_action, "name": "read_page",
                      "args": {"urls": pages[:READ_PAGE_MAX_URLS]}})
    for position, call in enumerate(calls):
        call["id"] = f"{POLICY_CALL_PREFIX}{call['action_id'][:20]}-{position}"
    return calls


HOOK_LIMITS = {"turn_started": "preparation_seconds", "tool_batch_completed": "batch_seconds",
               "answer_drafted": "answer_seconds"}
FAMILY_ORDER = ("supported", "requirements", "names", "markers")
FINAL_LINE = "Write the complete answer again with the sources that support its claims."


def draft_note_text(citation: dict, checks: list[dict], discovery: str,
                    allow_repair: bool, allow_discovery: bool) -> tuple[str, list[dict]]:
    """One combined note for a draft, and the findings that it names, in answer order."""
    from tasks.P_agent import citations

    parts = []
    findings = []
    if allow_discovery and discovery:
        parts.append(discovery)
    if allow_repair:
        if citation.get("needed"):
            parts.append(citations.repair_note(citation.get("check") or {}))
        findings = [c for c in checks if c["status"] == "defect" and (c.get("detail") or {}).get("mandatory")]
        findings.sort(key=lambda c: (FAMILY_ORDER.index(c["detail"].get("family", "markers"))
                                     if c["detail"].get("family") in FAMILY_ORDER else 9,
                                     len(c["target_id"]), c["target_id"]))
        lines = []
        for c in findings:
            detail = c["detail"]
            quoted = (detail.get("text") or "").replace("\n", " ")[:240]
            handles = (" Sources: " + ", ".join(c["input_refs"]) + ".") if c["input_refs"] else ""
            lines.append(f"- {quoted!r}: {c['reason']}.{handles} {detail.get('correction', '')}".rstrip())
        if lines:
            parts.append("Correct these parts of the answer:\n" + "\n".join(lines))
            if FINAL_LINE not in "\n".join(parts):
                parts.append(FINAL_LINE)
    return "\n\n".join(p for p in parts if p), findings


def _context(row, params, messages, control, event, anchor) -> PolicyContext:
    assets = control.get("assets") or {}
    results = F.result_facts(messages)
    batch = F.batch_of(results, anchor.idx) if params.hook == "tool_batch_completed" else []
    listed = {name: {k: skill.get(k) for k in ("description", "group", "tools", "terms", "not_for")}
              for name, skill in (assets.get("skills") or {}).items()}
    turn = _turn_facts(messages)
    turn["conversation"] = control.get("conversation") or []
    if params.hook == "answer_drafted":
        from tasks.P_agent import citations, reports
        from tasks.P_agent.steps import _citation_messages

        entries = reports.session_citation_entries(row.username, row.session_id)
        needed, check = citations.needs_repair(row.result or "", _citation_messages(row, messages),
                                               entries)
        structural = check.get("unresolved") or check.get("conflicting") or check.get("page_zero")
        turn["citation"] = {"needed": bool(needed) and (event.draft_kind == "answer" or bool(structural)), "check": check}
        turn["passages"] = _passages(entries)
    context = PolicyContext(
        run_id=row.run_id, thread_id=row.thread_id, profile=profile_of(params.internet_tools),
        definition_revision=control["definition"]["revision"], request=messages[0].content or "",
        callable_tools=frozenset(assets.get("callable_tools") or []), listed_skills=freeze(listed),
        visible_skills=frozenset(), results=tuple(results), batch=tuple(batch),
        turn=freeze(json.loads(json.dumps(turn, default=str))), counters=freeze(counters(messages)),
        draft=row.result or "",
        capabilities=frozenset(control.get("capabilities") or capabilities_of(assets.get("callable_tools") or [])),
        collections=tuple(control.get("collections", params.allowed_collections) or []),
        recent_steps=F.render_steps(messages))
    if params.hook == "answer_drafted" and F.justified_absence(context):
        citation = plain(context.turn.get("citation") or {})
        check = citation.get("check") or {}
        if not check.get("labels") and not citations.URL_PATTERN.search(context.draft) and not check.get("page_zero"):
            turn["citation"] = {**citation, "needed": False, "reason": "verified absence needs no source handle"}
            context = replace(context, turn=freeze(turn))
    return context


def _decide(row, params, messages, control, anchor, samples) -> dict:
    """Evaluate the rules of the event and return its decision, positions reserved."""
    from tasks.P_agent.steps import _raise_if_cancelled, _step_event

    definition = definitions.pinned(control["definition"])
    event = ControlEvent(
        id=f"{params.hook}:{row.thread_id}:{anchor.idx}", hook=params.hook, anchor_idx=anchor.idx,
        origin="runtime" if params.hook == "turn_started" else F.origin_of(anchor) if anchor.role == "ai" else "model",
        draft_kind=(params.draft_kind or "answer") if params.hook == "answer_drafted" else None)
    limit = float(definition.limits.get(HOOK_LIMITS[params.hook], params.deadline_seconds))
    deadline = Deadline(min(limit, params.deadline_seconds),
                        cancelled=lambda: _cancelled())
    context = _context(row, params, messages, control, event, anchor)
    classifier = Classifier(deadline)
    samples.update(row=row, event={"id": event.id, "hook": event.hook},
                   definition_revision=definition.revision, events=classifier.events)
    started = time.monotonic()
    with _step_event(row, "control", params.hook, mode=definition.id) as step:
        evaluated = asyncio.run(evaluate(definition, event, context, Services(classifier, messages, row, params),
                                         deadline))
        step.ok = all(record.get("status") == "ok" for _, _, record in evaluated)
        step.error_class = "" if step.ok else "rule_error"
    _raise_if_cancelled()
    loads = any(a.kind == "load_skill" for _, r, _ in evaluated if r for a in r.actions)
    visible = _visible_skills(row, params, messages) if loads else set()
    counts = counters(messages)
    actions, checks, facts = _merge(definition, evaluated, event, control, counts, visible,
                                    set((control.get("assets") or {}).get("skills") or {}))
    idx, seq = _next_positions(row, messages)
    decision = {
        "event": {"id": event.id, "hook": event.hook, "anchor_idx": event.anchor_idx,
                  "origin": event.origin, "draft_kind": event.draft_kind},
        "definition_revision": definition.revision,
        "rules": [{"id": rule.id, "revision": rule.revision, **record}
                  for rule, _, record in evaluated],
        "checks": checks, "facts": facts, "classifier": classifier.log,
        "evaluated_ms": int((time.monotonic() - started) * 1000),
        "status": "prepared", "round": False, "rows": {"ai_idx": None, "calls": [], "note": None},
        "actions": [],
    }
    ending = next((a for a in actions if a["kind"] == "end_turn"), None)
    decision["end_turn"] = ending["arguments"].get("text", "") if ending else ""
    notes = [a for a in actions if a["kind"] == "append_note"]
    calls = [a for a in actions if a["kind"] in ("load_skill", "call_tools")] \
        if params.hook != "answer_drafted" else []
    kept = []
    if calls:
        planned = _policy_calls(calls, control.get("assets") or {})
        entries = _agent_post(params, "/policy_calls", {
            **_step_body(row, params),
            "calls": [{"id": c["id"], "name": c["name"], "args": c["args"]} for c in planned]}, 30
        ).get("entries") or []
        by_id = {e.get("id"): e for e in entries}
        rows_calls = []
        for call in planned:
            entry = by_id.get(call["id"])
            if entry is None:
                continue
            entry = {**entry, "action_id": call["action_id"], "position": len(rows_calls),
                     "seq": seq + len(rows_calls)}
            rows_calls.append(entry)
        if rows_calls:
            decision["rows"]["ai_idx"] = idx
            decision["rows"]["calls"] = rows_calls
            kept = [a for a in calls if any(c["action_id"] == a["id"] for c in rows_calls)]
            idx += 1 + len(rows_calls)
            seq += len(rows_calls)
    if params.hook == "answer_drafted":
        limits = definition.limits
        citation = plain(context.turn.get("citation") or {})
        mandatory = [c for c in checks if c["status"] == "defect" and (c.get("detail") or {}).get("mandatory")]
        has_defects = bool(citation.get("needed")) or bool(mandatory)
        allow_repair = decide_repair(has_defects, counts["repair_rounds"], params.model_limit_reached,
                                     int(limits["repair_rounds"]))
        discovery = next((a for a in notes if a["arguments"].get("discovery")), None)
        allow_discovery = (discovery is not None and not params.model_limit_reached
                           and counts["discovery_notes"] < int(limits["discovery_notes"]))
        text, findings = draft_note_text(citation, checks,
                                         discovery["arguments"]["text"] if discovery else "",
                                         allow_repair, allow_discovery)
        decision["repair"] = {"has_defects": has_defects, "rounds_started": counts["repair_rounds"],
                              "allowed": allow_repair, "discovery": allow_discovery,
                              "model_limit_reached": params.model_limit_reached,
                              "citation_needed": bool(citation.get("needed")),
                              "findings": [f["target_id"] for f in findings]}
        if text:
            from tasks.P_agent import citations
            from tasks.P_agent.steps import CITATION_NOTE_NAME

            decision["round"] = True
            decision["rows"]["note"] = {
                "idx": idx, "seq": seq, "text": text, "tool_name": CITATION_NOTE_NAME,
                "usage": {citations.REPAIR_MARKER_KEY: citations.REPAIR_MARKER,
                          "citation_check": citation.get("check") if allow_repair else {},
                          "control": {"kind": DRAFT_NOTE, "event_id": event.id,
                                      "repair": allow_repair, "discovery": allow_discovery,
                                      "definition_revision": definition.revision}}}
            kept += ([discovery] if allow_discovery else []) + (
                [{"id": action_id(event.id, "repair", "draft", 0), "rule_id": "repair",
                  "kind": "repair", "target": "draft", "arguments": {"findings": len(findings)}}]
                if allow_repair else [])
            seq += 1
    elif notes:
        text = "\n\n".join(a["arguments"]["text"] for a in notes)
        decision["rows"]["note"] = {
            "idx": idx, "seq": seq, "text": text, "tool_name": BATCH_NOTE_NAME,
            "usage": {"control": {"kind": BATCH_NOTE, "event_id": event.id,
                                  "action_ids": [a["id"] for a in notes],
                                  "definition_revision": definition.revision}}}
        kept += notes
        seq += 1
    decision["actions"] = kept + ([ending] if ending else [])
    decision["next_seq"] = seq
    events = []
    attributed = set()
    rules = {r.id: r for r in definition.rules}
    for sample in sorted(classifier.events, key=lambda e: e["sequence"]):
        item = dict(sample)
        rid = item.get("rule_id", "")
        rule = rules.get(rid)
        positive = 0
        scored = 0
        for qid, value in zip(item["question_ids"], item["answer_values"]):
            if value is None:
                continue
            scored += 1
            parameter = rule.parameters if rule else {}
            threshold = 0.5
            if qid.startswith("skill_"):
                threshold = (parameter.get("skills", {}).get(qid[6:-1]) or {}).get("threshold", 0.9)
            if rule and rule.handler.name == "progress":
                from tasks.P_agent.control.handlers.progress import SIGNALS
                threshold = next((spec[1] for spec in SIGNALS.values() if spec[0] == qid), threshold)
            if rule and rule.handler.name == "capture_check":
                threshold = parameter.get({"facts=": "facts_below", "boilerplate=": "boilerplate_above",
                                           "not_found=": "not_found_above"}.get(qid, ""), threshold)
            if "supported" in qid:
                threshold = (parameter.get("supported") or {}).get("threshold", 0.05)
            if qid.startswith("req"):
                threshold = (parameter.get("requirements") or {}).get("threshold", 0.05)
            positive += int(value >= threshold)
        item["positive_answers"], item["scored_answers"] = positive, scored
        item["actions"] = sum(a["rule_id"] == rid for a in decision["actions"]) if rid not in attributed else 0
        attributed.add(rid)
        events.append(item)
    decision["classifier_events"] = events
    return decision


def _cancelled() -> bool:
    from temporalio import activity

    return activity.in_activity() and activity.is_cancelled()


def _apply(row, messages, decision, params) -> None:
    """Write each row of the decision that the thread does not hold yet."""
    from database import agent_runs
    from tasks.P_agent.activities import _insert_chat_row
    from tasks.P_agent.steps import NOTE_ROLE, _raise_if_cancelled

    rows = decision["rows"]
    event_id = decision["event"]["id"]
    if rows.get("ai_idx") is not None:
        current = _message(messages, rows["ai_idx"])
        if current is None or control_of(current).get("event_id") != event_id:
            _raise_if_cancelled()
            usage = {"origin": "policy", "control": {
                "event_id": event_id, "definition_revision": decision["definition_revision"],
                "action_ids": sorted({c["action_id"] for c in rows["calls"]})}}
            agent_runs.write_message(row.username, row.session_id, row.thread_id, row.run_id,
                                     agent_runs.RunMessageRow(
                                         idx=rows["ai_idx"], role="ai", content="",
                                         tool_calls_json=json.dumps(rows["calls"]),
                                         usage_json=json.dumps(usage), run_id=row.run_id))
    note = rows.get("note")
    if note:
        current = _message(messages, note["idx"])
        if current is None:
            _raise_if_cancelled()
            agent_runs.write_message(row.username, row.session_id, row.thread_id, row.run_id,
                                     agent_runs.RunMessageRow(
                                         idx=note["idx"], role="human", content=note["text"],
                                         usage_json=json.dumps(note["usage"], default=str),
                                         run_id=row.run_id))
        _insert_chat_row(row.username, row.session_id, note["seq"], NOTE_ROLE,
                         content=note["text"], tool_name=note["tool_name"],
                         usage_json=json.dumps({"origin": "policy", "event_id": event_id}))
    if decision["next_seq"] > row.next_seq:
        agent_runs.write_run(row, next_seq=decision["next_seq"])


def run_hook(params):
    """The body of the `control_event` activity. See the module docstring."""
    from tasks.P_agent.control.classifier import write_events

    samples = {}
    try:
        return _run_hook(params, samples)
    finally:
        if samples and not samples.get("written"):
            write_events(samples["row"], {"event": samples["event"],
                         "definition_revision": samples["definition_revision"],
                         "classifier_events": [{**event, "actions": 0, "positive_answers": 0,
                                                "scored_answers": 0} for event in samples["events"]]})


def _run_hook(params, samples):
    """Persist the decision and apply it while retaining the request samples."""
    from database import agent_runs
    from tasks.P_agent.activities import CallRef
    from tasks.P_agent.steps import _raise_if_cancelled, _read_row, _read_thread

    from tasks.P_agent.control_steps import ControlOutcome

    row = _read_row(params)
    if agent_runs.is_terminal(row):
        return ControlOutcome(closed=True, next_seq=row.next_seq)
    if params.hook == "answer_drafted" and row.end_reason:
        # A run that ended at a limit has a result that code wrote, and gets no review.
        return ControlOutcome(next_seq=row.next_seq)
    messages = _read_thread(row)
    if not messages or messages[0].role != "human":
        return ControlOutcome(next_seq=row.next_seq)
    if params.hook == "turn_started":
        pin_started = time.monotonic()
        control = _pin(row, messages, params)
        params = replace(params, deadline_seconds=max(0, params.deadline_seconds - (time.monotonic() - pin_started)))
        messages = _read_thread(row)
    else:
        control = control_of(messages[0])
        if not control.get("definition"):
            # A turn that started before the control records existed keeps its behavior.
            return ControlOutcome(next_seq=row.next_seq)
    anchor = _anchor(params, messages)
    if anchor is None:
        return ControlOutcome(next_seq=row.next_seq)
    decision = (control_of(anchor).get("decisions") or {}).get(params.hook)
    if decision is None:
        decision = _decide(row, params, messages, control, anchor, samples)
        _raise_if_cancelled()
        # Read again: a late attempt never replaces a decision that another attempt stored.
        messages = _read_thread(row)
        anchor = _message(messages, anchor.idx)
        stored = (control_of(anchor).get("decisions") or {}).get(params.hook)
        if stored is not None:
            decision = stored
        else:
            mine = control_of(anchor)
            mine.setdefault("decisions", {})[params.hook] = decision
            write_control(row, anchor, mine)
            messages = _read_thread(row)
            anchor = _message(messages, anchor.idx)
    row = _read_row(params)
    if agent_runs.is_terminal(row):
        return ControlOutcome(closed=True, next_seq=row.next_seq)
    _apply(row, messages, decision, params)
    if decision.get("status") != "applied":
        from tasks.P_agent.control.classifier import write_events

        write_events(row, decision)
        samples["written"] = True
        mine = control_of(_message(_read_thread(row), anchor.idx))
        mine.setdefault("decisions", {})[params.hook] = {**decision, "status": "applied"}
        write_control(row, _message(_read_thread(row), anchor.idx), mine)
    answered = {m.tool_call_id for m in _read_thread(row) if m.role == "tool"}
    calls = [CallRef(ai_idx=decision["rows"]["ai_idx"], position=int(c["position"]),
                     call_id=c["id"], name=c["name"], kind=str(c.get("kind") or "parallel"),
                     seq=int(c["seq"]), retry=bool(c.get("retry", True)))
             for c in decision["rows"].get("calls") or [] if c["id"] not in answered]
    return ControlOutcome(calls=calls, round=bool(decision.get("round")),
                          next_seq=max(int(decision.get("next_seq") or 0), row.next_seq),
                          end_turn=bool(decision.get("end_turn")))
