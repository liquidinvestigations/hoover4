"""The `turn_started` handler: the report skill trigger and the active source rules.

The handler makes no model request. A task that asks for a file as its output loads the
`report` skill before the first write (`asks_for_file`), when `report_skill` is true. The
output groups of the task record decide (`task_state`): a deliverable of a structured task,
an output action such as "write a report", a file destination such as "in a short report",
or a named output such as "save it as notes.md". A report title, an input file, a
prohibited write or a question about the files of a folder loads nothing. The
`first_write` and `workspace_error` result triggers stay the fallback for the requests that
the record cannot interpret.

The active source restrictions of the task record become one note, so the model reads them
as instructions of the turn.
"""

from __future__ import annotations

from typing import Any, Mapping

from tasks.P_agent.control.model import API_VERSION, Action, CheckResult, PolicyResult, freeze


def task_record(context) -> Mapping[str, Any]:
    """The task record of the turn (`task_state`), or the record of its structured task
    when the context holds no record."""
    from tasks.P_agent.control import task_state

    if context.task_state:
        return context.task_state
    task = context.task or {"objective": {"text": context.request, "source": "user"}}
    return task_state.from_structured(task)


def requested_output(task: Mapping[str, Any], state: Mapping[str, Any] | None = None) -> dict:
    """The file outputs that a task requests: `{"file": bool, "names": [...], "count": n}`.

    The output groups of the task record decide (`task_state.requirements`). Without
    `state`, the record of the structured task `task` is used. `count` is the sum of the
    exact counts of the active groups, at least the count of the names, and 0 when no group
    states an exact count. `names` are the requested file names in text order."""
    from tasks.P_agent.control import task_state

    required = task_state.requirements(state if state else task_state.from_structured(task or {}))
    return {"file": required["file"], "names": required["names"], "count": required["count"]}


def asks_for_file(task: Mapping[str, Any], state: Mapping[str, Any] | None = None) -> bool:
    """Whether the report skill loads before the first write. With a task record, an
    unresolved record loads it only for an output clause of its newest unresolved message
    (`task_state.proactive_file`). Without one, the task asks for a file as its output
    (`requested_output`)."""
    from tasks.P_agent.control import task_state

    if state:
        return task_state.proactive_file(state)
    return requested_output(task, state)["file"]


class Handler:
    api_version = API_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        if not isinstance(parameters.get("report_skill", True), bool):
            raise ValueError("report_skill must be true or false")

    async def evaluate(self, event, context, parameters, services) -> PolicyResult:
        task = context.task or {"objective": {"text": context.request, "source": "user"}}
        record = task_record(context)
        checks: list = []
        actions: list = []
        restrictions = [rule["text"] for rule in record.get("source_rules", [])
                        if rule.get("status") == "active" and rule.get("effect") == "restrict"]
        if restrictions:
            actions.append(Action("append_note", "active-source-rules",
                                  freeze({"text": "\n".join(restrictions)})))
        if (parameters.get("report_skill", True) and "report" in context.listed_skills
                and asks_for_file(task, record)):
            checks.append(CheckResult(event.id, "skill:report", "pass", None, (), "the task names a file"))
            actions.append(Action("load_skill", "report", freeze({"skill": "report", "score": 1.0})))
        return PolicyResult(checks=tuple(checks), actions=tuple(actions))
