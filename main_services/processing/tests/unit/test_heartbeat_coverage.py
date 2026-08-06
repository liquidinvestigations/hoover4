"""Every execute_activity call site must declare a heartbeat_timeout.

This is the regression guard for the 2026-08-06 incident: an activity task was
lost between the Temporal matching service and the worker, and because the only
timeout on that call site was the whole-file ``start_to_close_timeout`` (1583 s),
the stall lasted 26 minutes. The heartbeat clock starts at
``ActivityTaskStarted`` -- exactly the state the lost task was stuck in -- so a
``heartbeat_timeout`` turns that into a ~30 s stall.

An AST test rather than a grep: these calls span multiple lines with nested
dataclass constructors, and a regex over that is a false-negative generator.
"""

import ast
from pathlib import Path

TASKS_ROOT = Path(__file__).resolve().parents[2] / "tasks"


def _is_execute_activity(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "execute_activity"
    if isinstance(func, ast.Name):
        return func.id == "execute_activity"
    return False


def _has_kwarg(call: ast.Call, name: str) -> bool:
    return any(kw.arg == name for kw in call.keywords)


def _iter_call_sites():
    for path in sorted(TASKS_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if _is_execute_activity(node):
                yield path, node


def test_every_execute_activity_declares_a_heartbeat_timeout():
    missing = [
        f"{path.relative_to(TASKS_ROOT)}:{call.lineno}"
        for path, call in _iter_call_sites()
        if not _has_kwarg(call, "heartbeat_timeout")
    ]
    assert not missing, (
        "execute_activity call site(s) without heartbeat_timeout -- a lost or "
        "wedged activity here is detected only after its start_to_close_timeout, "
        "which is up to 4 hours:\n  " + "\n  ".join(missing)
    )


def test_the_sweep_actually_found_call_sites():
    """Guard the guard: an import rename that made _is_execute_activity match
    nothing would turn the test above into a vacuous pass."""
    assert sum(1 for _ in _iter_call_sites()) >= 50


def _iter_activity_defs():
    for path in sorted(TASKS_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(isinstance(d, ast.Attribute) and d.attr == "defn"
                   and isinstance(d.value, ast.Name) and d.value.id == "activity"
                   for d in node.decorator_list):
                yield path, node


def test_every_activity_body_heartbeats():
    """The other half of the contract, and the one that bites hardest.

    HEARTBEAT_TIMEOUT is 30 s and every call site declares it, so an activity
    whose real work legitimately takes minutes -- ffprobe on a large video, a
    Manticore batch write, a dataset purge -- gets killed at 30 s unless
    something beats for it. The retry is just as slow, so it is killed again:
    a permanent retry loop that looks exactly like a broken pipeline.

    @with_heartbeat on every body removes the question. Auditing 44 bodies for
    "can this exceed 30 s?" gets the answer wrong eventually, and again the next
    time someone adds an activity.
    """
    def decorator_names(node):
        names = []
        for d in node.decorator_list:
            if isinstance(d, ast.Name):
                names.append(d.id)
            elif isinstance(d, ast.Attribute):
                names.append(d.attr)
        return names

    missing = [
        f"{path.relative_to(TASKS_ROOT)}:{node.lineno} {node.name}"
        for path, node in _iter_activity_defs()
        if "with_heartbeat" not in decorator_names(node)
    ]
    assert not missing, (
        "@activity.defn without @with_heartbeat -- these will be killed at the "
        f"{30}s heartbeat deadline if their body ever runs longer:\n  "
        + "\n  ".join(missing)
    )


def test_the_activity_sweep_actually_found_activities():
    assert sum(1 for _ in _iter_activity_defs()) >= 40


def test_no_bare_integer_timeout_on_outbound_http():
    """``requests`` measures timeouts in SECONDS.

    ``timeout=3000`` in the NER client was a 50-minute budget applied to both
    connect and read; it read like milliseconds. Every outbound call must pass
    the ``(connect, read)`` two-tuple, because the two failure modes need
    completely different numbers -- a dead host must be caught in ~2 s while a
    live host chewing through a batch legitimately needs minutes.
    """
    offenders = []
    for path in sorted(TASKS_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "timeout":
                    continue
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, (int, float)):
                    # subprocess.run(timeout=N) is fine and must be KEPT (see
                    # plans/1-part-3.md 2.5); only HTTP calls are in scope.
                    func = node.func
                    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                    if name in ("post", "get", "put", "patch", "delete", "request"):
                        offenders.append(f"{path.relative_to(TASKS_ROOT)}:{node.lineno}")
    assert not offenders, (
        "outbound HTTP call(s) with a scalar timeout; use (connect, read):\n  "
        + "\n  ".join(offenders)
    )
