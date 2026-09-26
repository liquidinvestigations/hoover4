"""Agent activities must name the queue they run on.

A workflow that omits ``task_queue`` runs on the workflow's own queue. Chat model
calls and transcript writes then share slots again, and a deep-research turn addressed
to a queue nothing polls waits for ever with no error anywhere.
"""

import ast
from pathlib import Path

import tasks.P_agent.workflows as agent_workflows

WORKFLOWS_PATH = Path(agent_workflows.__file__)


def _is_execute_activity(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr == "execute_activity"


def _kwarg(call: ast.Call, name: str) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _name(node: ast.AST) -> str | None:
    return node.id if isinstance(node, ast.Name) else None


def _iter_execute_activity():
    tree = ast.parse(WORKFLOWS_PATH.read_text(), filename=str(WORKFLOWS_PATH))
    for node in ast.walk(tree):
        if _is_execute_activity(node):
            yield node


def test_queue_name_constants():
    assert agent_workflows.CHAT_TASK_QUEUE == "chat-queue"
    assert agent_workflows.CHAT_MODEL_TASK_QUEUE == "chat-model-queue"
    assert agent_workflows.RESEARCH_TASK_QUEUE == "research-queue"


def _queue(call: ast.Call) -> str | None:
    """The queue a call site names: a constant, or the row's queue for the agent call."""
    value = _kwarg(call, "task_queue")
    if isinstance(value, ast.Attribute) and value.attr == "queue":
        return "row"
    return _name(value)


def test_agent_activities_declare_their_task_queue():
    missing = []
    for call in _iter_execute_activity():
        activity = _name(call.args[0]) if call.args else None
        if _queue(call) is None:
            missing.append(f"{WORKFLOWS_PATH.name}:{call.lineno} {activity}")
    assert not missing, (
        "execute_activity call site(s) without task_queue -- these run on the "
        "workflow's queue and share slots with the wrong kind of work:\n  "
        + "\n  ".join(missing)
    )


def test_the_model_step_goes_to_the_queue_in_the_run_row():
    queues = [_queue(call) for call in _iter_execute_activity()
              if _name(call.args[0]) == "model_step"]
    assert queues == ["row"], queues


def test_the_tool_call_goes_to_the_tool_queue():
    queues = [_queue(call) for call in _iter_execute_activity()
              if _name(call.args[0]) == "tool_call"]
    assert queues == ["AGENT_TOOL_TASK_QUEUE"], queues


def test_plan_runs_go_to_the_research_queue():
    from database import agent_runs
    from tasks.P_agent import workflows

    assert agent_runs.LEAD_QUEUES["planner"] == workflows.RESEARCH_TASK_QUEUE
    assert agent_runs.LEAD_QUEUES["organizer"] == workflows.RESEARCH_TASK_QUEUE


def test_short_agent_activities_go_to_the_low_latency_queue():
    for activity in ("open_run", "append_nag", "write_ending", "read_chat_todo",
                     "summarize_if_first_turn", "delegate_step", "prepare_continuation",
                     "record_step_failure", "plan_has_sections"):
        queues = [
            _name(_kwarg(call, "task_queue"))
            for call in _iter_execute_activity()
            if _name(call.args[0]) == activity
        ]
        assert queues, f"{activity} is not scheduled"
        assert all(q == "CHAT_TASK_QUEUE" for q in queues), (activity, queues)


RUN_WORKER_PATH = WORKFLOWS_PATH.resolve().parent.parent / "run_worker.py"


def _chat_worker_slot_defaults() -> dict[str, int]:
    """The code default of each `worker_concurrency` call in `run_chat_worker`."""
    tree = ast.parse(RUN_WORKER_PATH.read_text(), filename=str(RUN_WORKER_PATH))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_chat_worker")
    defaults = {}
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and _name(node.func) == "worker_concurrency"
                and len(node.args) == 2):
            defaults[node.args[0].value] = node.args[1].value
    return defaults


def test_an_empty_slot_key_gives_three_model_slots_and_sixteen_tool_slots(monkeypatch):
    from tasks.run_worker import worker_concurrency

    defaults = _chat_worker_slot_defaults()
    assert defaults == {"chat_model": 3, "chat_low_latency": 8, "research": 3,
                        "agent_tool": 16}
    for name in ("chat_model", "research", "agent_tool"):
        monkeypatch.setenv(f"HOOVER4_{name.upper()}_CONCURRENCY", "")
        assert worker_concurrency(name, defaults[name]) == defaults[name]
