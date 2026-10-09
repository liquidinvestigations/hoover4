"""Workflow definitions: the rules, limits and asset references of a chat profile.

A definition is one JSON file in `definitions/` beside this file, or in `definitions/` under
the configured control directory (`registry.CONTROL_DIR_ENV`):

    {"id": "chat-default", "schema_version": 1, "profile": "*",
     "limits": {"repair_rounds": 2, "preparation_seconds": 15, ...},
     "rules": [{"id": "prepare", "hook": "turn_started", "handler": "preparation",
                "priority": 10, "frequency": "turn", "parameters": {...}}]}

`active.json` maps a profile name to a definition id. The configured directory's
`active.json` wins over the built-in one, key by key. `resolve` validates the active
definition of a profile and returns it with its revision: the digest of the definition and
of the code identity of each handler that it names. A run stores the resolved definition
when its turn starts and reads that copy for the rest of the turn (`pinned`), so a later
activation changes new turns only. An unknown handler, an invalid parameter, an unknown
hook or a duplicate rule id raises `ControlConfigError` with the exact fault.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from tasks.P_agent.control import registry
from tasks.P_agent.control.model import (
    FREQUENCIES, HOOKS, HandlerRef, Rule, canonical_json, digest, freeze, plain,
)
from tasks.P_agent.control.registry import ControlConfigError

SCHEMA_VERSION = 1

#: The limits of a definition and their defaults. D5 sets two repair rounds, and D7 a
#: preparation deadline of 15 seconds. The other values are experiment parameters.
DEFAULT_LIMITS: Dict[str, float] = {
    "repair_rounds": 2,
    "preparation_seconds": 15.0,
    "batch_seconds": 10.0,
    "answer_seconds": 60.0,
    "preparation_skill_loads": 3,
    "discovery_notes": 1,
}


@dataclass(frozen=True)
class Definition:
    id: str
    revision: str
    schema_version: int
    profile: str
    rules: tuple
    limits: Mapping[str, float]
    runtime_identity: str
    source: str

    def rules_for(self, hook: str) -> list[Rule]:
        """The rules of one hook, by priority and then by id."""
        return sorted((r for r in self.rules if r.hook == hook),
                      key=lambda r: (r.priority, r.id))

    def record(self) -> dict:
        """The plain form that a run stores."""
        return {
            "id": self.id, "revision": self.revision, "schema_version": self.schema_version,
            "profile": self.profile, "limits": dict(self.limits),
            "runtime_identity": self.runtime_identity, "source": self.source,
            "rules": [{"id": r.id, "hook": r.hook, "priority": r.priority,
                       "frequency": r.frequency, "revision": r.revision,
                       "requires_tools": list(r.requires_tools),
                       "parameters": plain(r.parameters),
                       "handler": {"name": r.handler.name, "api_version": r.handler.api_version,
                                   "code_digest": r.handler.code_digest}}
                      for r in self.rules],
        }


def _definition_files() -> Dict[str, Path]:
    files: Dict[str, Path] = {}
    for root in registry.control_dirs():
        for path in sorted((root / "definitions").glob("*.json")):
            if path.name == "active.json":
                continue
            try:
                ident = json.loads(path.read_text()).get("id")
            except ValueError as exc:
                raise ControlConfigError(f"{path} is not JSON: {exc}") from None
            if not isinstance(ident, str) or not ident:
                raise ControlConfigError(f"{path} has no id")
            if ident in files:
                raise ControlConfigError(f"the definition id {ident!r} is defined twice "
                                         f"({files[ident]} and {path})")
            files[ident] = path
    return files


def active_ids() -> Dict[str, str]:
    """The active definition id of each profile."""
    out: Dict[str, str] = {}
    for root in registry.control_dirs():
        path = root / "definitions" / "active.json"
        if path.exists():
            try:
                value = json.loads(path.read_text())
            except ValueError as exc:
                raise ControlConfigError(f"{path} is not JSON: {exc}") from None
            if not isinstance(value, dict):
                raise ControlConfigError(f"{path} must map profiles to definition ids")
            out.update({str(k): str(v) for k, v in value.items()})
    return out


def validate(raw: Mapping[str, Any], source: str = "") -> Definition:
    """A checked definition, or `ControlConfigError` naming the first fault."""
    handlers = registry.load()
    where = f"definition {raw.get('id')!r}" + (f" ({source})" if source else "")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ControlConfigError(f"{where}: schema_version must be {SCHEMA_VERSION}")
    limits = dict(DEFAULT_LIMITS)
    for key, value in (raw.get("limits") or {}).items():
        if key not in DEFAULT_LIMITS:
            raise ControlConfigError(f"{where}: unknown limit {key!r}")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ControlConfigError(f"{where}: limit {key!r} must be a number of 0 or more")
        limits[key] = value
    rules = []
    seen = set()
    for item in raw.get("rules") or []:
        rid = str(item.get("id") or "")
        if not rid or rid in seen:
            raise ControlConfigError(f"{where}: rule id {rid!r} is empty or repeated")
        seen.add(rid)
        hook = item.get("hook")
        if hook not in HOOKS:
            raise ControlConfigError(f"{where}: rule {rid!r} has the unknown hook {hook!r}")
        name = item.get("handler")
        if name not in handlers:
            raise ControlConfigError(f"{where}: rule {rid!r} names the unknown handler {name!r}")
        frequency = item.get("frequency", "event")
        if frequency not in FREQUENCIES:
            raise ControlConfigError(f"{where}: rule {rid!r} has the unknown frequency {frequency!r}")
        priority = item.get("priority", 100)
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise ControlConfigError(f"{where}: rule {rid!r} needs an integer priority")
        try:
            parameters = freeze(json.loads(canonical_json(item.get("parameters") or {})))
        except ValueError as exc:
            raise ControlConfigError(f"{where}: rule {rid!r} has invalid parameters: {exc}") from None
        ref = handlers[name].ref
        try:
            handlers[name].handler.validate(parameters)
        except (ValueError, TypeError, KeyError) as exc:
            raise ControlConfigError(f"{where}: rule {rid!r} ({name}): {exc}") from None
        required = item.get("requires_tools", [])
        if not isinstance(required, (list, tuple)) or not all(isinstance(t, str) and t for t in required):
            raise ControlConfigError(f"{where}: rule {rid!r} needs a list of tool names")
        revision = digest([[ref.name, ref.api_version, ref.code_digest], plain(parameters),
                           hook, frequency, list(required)])
        rules.append(Rule(rid, hook, ref, parameters, priority, frequency, revision, tuple(required)))
    body = {"id": raw.get("id"), "schema_version": SCHEMA_VERSION,
            "profile": raw.get("profile") or "*", "limits": limits,
            "rules": [[r.id, r.revision, r.priority] for r in rules]}
    return Definition(
        id=str(raw.get("id")), revision=digest(body), schema_version=SCHEMA_VERSION,
        profile=str(raw.get("profile") or "*"), rules=tuple(rules), limits=freeze(limits),
        runtime_identity=registry.runtime_identity(), source=source)


def resolve(profile: str) -> Definition:
    """The validated active definition of a profile, else of `*`."""
    active = active_ids()
    ident = active.get(profile) or active.get("*")
    if not ident:
        raise ControlConfigError(f"no active definition for the profile {profile!r}")
    files = _definition_files()
    if ident not in files:
        raise ControlConfigError(f"the active definition {ident!r} of {profile!r} has no file")
    path = files[ident]
    definition = validate(json.loads(path.read_text()), source=str(path.name))
    if definition.profile not in ("*", profile):
        raise ControlConfigError(f"definition {ident!r} is for the profile "
                                 f"{definition.profile!r}, not {profile!r}")
    return definition


def pinned(record: Mapping[str, Any]) -> Definition:
    """The definition that a run stored. A rule whose handler code changed since keeps
    its stored identity, and `stale_rules` names it."""
    rules = []
    for item in record.get("rules") or []:
        h = item["handler"]
        rules.append(Rule(item["id"], item["hook"],
                          HandlerRef(h["name"], int(h["api_version"]), h["code_digest"]),
                          freeze(item.get("parameters") or {}), int(item["priority"]),
                          item["frequency"], item.get("revision", ""), tuple(item.get("requires_tools") or [])))
    return Definition(
        id=record["id"], revision=record["revision"],
        schema_version=int(record.get("schema_version") or SCHEMA_VERSION),
        profile=record.get("profile", "*"), rules=tuple(rules),
        limits=freeze({**DEFAULT_LIMITS, **(record.get("limits") or {})}),
        runtime_identity=record.get("runtime_identity", ""), source=record.get("source", ""))


def stale_rules(definition: Definition) -> list[str]:
    """The rules whose handler is missing or whose code differs from the pinned digest."""
    handlers = registry.load()
    out = []
    for rule in definition.rules:
        current: Optional[registry.Registered] = handlers.get(rule.handler.name)
        if current is None or current.ref != rule.handler:
            out.append(rule.id)
    return out
