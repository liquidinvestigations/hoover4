#!/usr/bin/env python3
"""Adapt the shared hook scripts to Cursor's hook JSON.

Cursor sends a different payload shape than Claude Code and Codex, and it expects
`permission` / `additional_context` on stdout. The deny logic stays in the shared
scripts. This file only translates.

Reads the Cursor payload on stdin. The event name is argv[1]. Writes Cursor JSON
on stdout. A failClosed hook must always emit valid JSON, so the allow path prints
`{"permission": "allow"}` rather than staying silent.
"""
from __future__ import annotations

import json
import fcntl
import os
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
HARNESS = ROOT / ".agents" / "harnesses" / "cursor.json"


def python_bin():
    """Return CPython because Cursor can set sys.executable to its AppImage."""
    for path in ("/usr/bin/python3", "/usr/local/bin/python3"):
        if os.access(path, os.X_OK):
            return path
    found = shutil.which("python3")
    if found and "AppImage" not in found:
        return found
    return "python3"


EDIT_TOOLS = {
    "Write": "Write",
    "StrReplace": "Edit",
    "Edit": "Edit",
    "MultiEdit": "MultiEdit",
}
SHELL_TOOLS = {"Shell", "Bash"}
PASSTHROUGH_DEFAULT = ("explore", "shell", "bash", "browser")


def load_harness():
    try:
        return json.loads(HARNESS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def emit(payload):
    sys.stdout.write(json.dumps(payload))
    return 0


def allow():
    return emit({"permission": "allow"})


def deny(reason):
    text = reason or "Denied by a project hook."
    return emit({
        "permission": "deny",
        "user_message": text,
        "agent_message": text,
    })


def run_hook(script, payload):
    """Run a shared hook with a Claude-shaped payload. Return its stdout bytes."""
    proc = subprocess.run(
        [python_bin(), str(HERE / script)],
        input=json.dumps(payload).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    return proc.stdout.decode("utf-8", errors="replace").strip()


def claude_reason(stdout):
    if not stdout:
        return None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    specific = data.get("hookSpecificOutput") or {}
    if specific.get("permissionDecision") == "deny":
        return specific.get("permissionDecisionReason") or "Denied by a project hook."
    return None


def claude_context(stdout):
    if not stdout:
        return None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    specific = data.get("hookSpecificOutput") or {}
    return specific.get("additionalContext") or None


def bash_payload(command, cwd):
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command or ""},
        "cwd": cwd,
    }


def check_shell(command, cwd):
    payload = bash_payload(command, cwd)
    for script in ("deny-unscoped-search.py", "deny-long-commit-message.py"):
        reason = claude_reason(run_hook(script, payload))
        if reason:
            return reason
    return None


def edit_payload(cursor):
    """Translate a Cursor edit tool call into the Claude Edit/Write shape."""
    name = cursor.get("tool_name") or ""
    mapped = EDIT_TOOLS.get(name)
    if not mapped:
        return None
    raw = cursor.get("tool_input") or {}
    if not isinstance(raw, dict):
        return None
    path = raw.get("file_path") or raw.get("path") or ""
    tool_input = dict(raw)
    tool_input["file_path"] = path
    if mapped == "Write" and "content" not in tool_input:
        if "contents" in tool_input:
            tool_input["content"] = tool_input.get("contents") or ""
    return {
        "tool_name": mapped,
        "tool_input": tool_input,
        "cwd": cursor.get("cwd"),
    }


def session_orientation(source):
    proc = subprocess.run(
        [str(HERE / "session-start-orientation.sh")],
        input=json.dumps({"source": source}).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return claude_context(proc.stdout.decode("utf-8", errors="replace").strip())


def max_concurrent(harness):
    raw = os.environ.get("HOOVER4_MAX_SUBAGENTS")
    if raw and raw.strip().isdigit() and int(raw.strip()) > 0:
        return int(raw.strip())
    value = harness.get("max_concurrent_subagents", 2)
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 2
    return value if value > 0 else 2


def passthrough_types(harness):
    listed = harness.get("passthrough_subagent_types") or PASSTHROUGH_DEFAULT
    return {str(item).lower() for item in listed}


def state_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
    directory = pathlib.Path(runtime) / "hoover4-cursor-subagents"
    directory.mkdir(parents=True, exist_ok=True)
    key = os.environ.get("CURSOR_PROJECT_DIR") or str(ROOT)
    safe = "".join(c for c in key if c.isalnum() or c in "-_")[-64:] or "workspace"
    return directory / f"{safe}.count"


def read_count(handle):
    try:
        handle.seek(0)
        value = int(handle.read().strip())
    except ValueError:
        return 0
    return value if value > 0 else 0


def write_count(handle, value):
    handle.seek(0)
    handle.truncate()
    handle.write(str(max(0, value)))
    handle.flush()


def handle_session_start(_payload, harness):
    context = session_orientation("startup") or ""
    env = {"HOOVER4_MAX_SUBAGENTS": str(max_concurrent(harness))}
    out = {"env": env}
    if context:
        out["additional_context"] = context
    return emit(out)


def handle_before_shell(payload, _harness):
    reason = check_shell(payload.get("command", ""), payload.get("cwd"))
    if reason:
        return deny(reason)
    return allow()


def handle_pre_tool_use(payload, _harness):
    name = payload.get("tool_name") or ""
    if name in SHELL_TOOLS:
        raw = payload.get("tool_input") or {}
        command = payload.get("command") or (raw.get("command") if isinstance(raw, dict) else "")
        cwd = payload.get("cwd") or (
            raw.get("working_directory") if isinstance(raw, dict) else None
        )
        reason = check_shell(command, cwd)
        if reason:
            return deny(reason)
        return allow()
    translated = edit_payload(payload)
    if translated:
        reason = claude_reason(run_hook("deny-claudisms.py", translated))
        if reason:
            return deny(reason)
    return allow()


def handle_post_tool_use(payload, _harness):
    agent_id = payload.get("agent_id") or payload.get("subagent_id")
    if not agent_id:
        return 0
    claude = dict(payload)
    claude["agent_id"] = agent_id
    context = claude_context(run_hook("warn-tool-call-budget.py", claude))
    if context:
        return emit({"additional_context": context})
    return 0


def handle_subagent_start(payload, harness):
    kind = str(payload.get("subagent_type") or "").lower()
    if kind in passthrough_types(harness):
        return allow()
    path = state_path()
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        current = read_count(handle)
        limit = max_concurrent(harness)
        if current >= limit:
            return deny(
                f"Blocked: this workspace already has {current} counted sub-agents, "
                f"and the cap is {limit}. Wait for one to finish, then launch again."
            )
        write_count(handle, current + 1)
    return allow()


def handle_subagent_stop(payload, harness):
    kind = str(payload.get("subagent_type") or "").lower()
    if kind in passthrough_types(harness):
        return 0
    path = state_path()
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        write_count(handle, read_count(handle) - 1)
    return 0


HANDLERS = {
    "session-start": handle_session_start,
    "before-shell": handle_before_shell,
    "pre-tool-use": handle_pre_tool_use,
    "post-tool-use": handle_post_tool_use,
    "subagent-start": handle_subagent_start,
    "subagent-stop": handle_subagent_stop,
}


def main(argv):
    if len(argv) < 2 or argv[1] not in HANDLERS:
        return 2
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return HANDLERS[argv[1]](payload, load_harness()) or 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
