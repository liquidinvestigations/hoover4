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


def test_agent_activities_declare_their_task_queue():
    missing = []
    for call in _iter_execute_activity():
        activity = _name(call.args[0]) if call.args else None
        queue = _name(_kwarg(call, "task_queue"))
        if queue is None:
            missing.append(f"{WORKFLOWS_PATH.name}:{call.lineno} {activity}")
    assert not missing, (
        "execute_activity call site(s) without task_queue -- these run on the "
        "workflow's queue and share slots with the wrong kind of work:\n  "
        + "\n  ".join(missing)
    )


def test_chat_model_calls_go_to_the_model_queue():
    queues = [
        _name(_kwarg(call, "task_queue"))
        for call in _iter_execute_activity()
        if _name(call.args[0]) == "run_research_agent"
        and call.lineno < _research_task_lineno()
    ]
    assert queues, "ChatTurn has no run_research_agent call"
    assert all(q == "CHAT_MODEL_TASK_QUEUE" for q in queues), queues


def test_research_model_calls_go_to_the_research_queue():
    queues = [
        _name(_kwarg(call, "task_queue"))
        for call in _iter_execute_activity()
        if _name(call.args[0]) == "run_research_agent"
        and call.lineno >= _research_task_lineno()
    ]
    assert queues, "ResearchTask has no run_research_agent call"
    assert all(q == "RESEARCH_TASK_QUEUE" for q in queues), queues


def test_writes_todo_and_title_go_to_the_low_latency_queue():
    for activity in ("write_chat_message", "read_chat_todo", "summarize_session"):
        queues = [
            _name(_kwarg(call, "task_queue"))
            for call in _iter_execute_activity()
            if _name(call.args[0]) == activity
        ]
        assert queues, f"{activity} is not scheduled"
        assert all(q == "CHAT_TASK_QUEUE" for q in queues), (activity, queues)


def _research_task_lineno() -> int:
    tree = ast.parse(WORKFLOWS_PATH.read_text(), filename=str(WORKFLOWS_PATH))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ResearchTask":
            return node.lineno
    raise AssertionError("ResearchTask not found")
