#!/usr/bin/env python3
"""Read every harness's own transcripts and write one normalized record per pass.

    extract.py [--out passes.jsonl] [--repo /home/gabriel/work/hoover4]

Four harnesses have run against this repository and each keeps its history in its own
format. This reads all four and emits one JSON object a line, so every later script reads
one shape instead of four.

    claude   ~/.claude/projects/<slug>/<session>.jsonl
             sub-agents at <session>/subagents/agent-*.jsonl
    codex    ~/.codex/sessions/<yyyy>/<mm>/<dd>/rollout-*.jsonl
    kimi     ~/.kimi-code/sessions/wd_<slug>/session_*/agents/*/wire.jsonl
    cursor   ~/.config/Cursor/User/globalStorage/state.vscdb
             tables cursorDiskKV (composerData:*, bubbleId:*) and composerHeaders
             plus ~/.cursor/ai-tracking/ai-code-tracking.db for model attribution

WHAT A RECORD HOLDS

Every record carries the same fields, and a field a harness cannot supply is null. A null
is not a zero: `report.py` drops a null from its distribution and counts how many it
dropped, so a thin harness cannot quietly pull a median.

    harness kind id session project model models
    start end minutes
    turns tool_calls write_calls shell_calls infra_shell_calls
    code_writes prose_writes written_paths
    peak_context input_tokens output_tokens cache_read cache_write compactions
    bucket

HOW A PASS IS BUCKETED

By what it produced, never by what it was called. A description regex disagrees with this
rule on about a third of passes, because prose written through a shell redirect looks like
no write at all.

    1. a file written by a redirect, a heredoc, `sed -i` or `apply_patch` counts as a write
    2. it wrote a file that is not .md, .txt or .csv          -> implementation
    3. it wrote no such file and drove docker, a server or a
       sweep in at least three shell calls, being a tenth or
       more of them                                           -> operational
    4. it wrote no file at all                                -> read-only review
    5. it wrote only prose                                    -> documentation

WHAT A TOOL CALL IS

One call to one tool, counted the same way everywhere. Codex routes almost everything
through a single `exec` tool, so an `exec` carrying an `apply_patch` is one call that is
also a write. Cursor counts a bubble that carries `toolFormerData`.

WHAT A PASS IS

One sub-agent invocation where the harness records one, and one conversation otherwise.
`kind` says which, so a later script never mixes them.

    claude   kind=pass for subagents/agent-*.jsonl, kind=session for the session file
    codex    kind=pass when session_meta.thread_source is `subagent`, else kind=session
    kimi     kind=pass for agents/<name>/wire.jsonl where name is not main, else session
    cursor   kind=pass when composerHeaders.isSubagent is set, else kind=session

A third kind exists. Codex runs an automatic `guardian_review` thread against a proposed
action, and 17 of its 38 recorded threads are one. A guardian thread is not work and it is
recorded as `kind=guard`, so a later script drops it by default. Counting one as a pass
halves every codex median.

Model names are normalized. Cursor records the same model twice, once as `grok-4.6` from
its write tracker and once as `cursor-grok-4.6-high` from the conversation configuration,
so the reasoning effort is split into its own field and the names then agree.

This script reads and prints. It writes only the file named by --out.
"""

import argparse
import json
import os
import pathlib
import re
import sqlite3
import sys
from datetime import datetime, timezone

REPO = "/home/gabriel/work/hoover4"

#: A prompt that falls by more than this between consecutive turns was compacted.
COMPACTION_DROP = 50_000

#: Extensions that make a written file prose rather than code.
PROSE_SUFFIXES = {".md", ".txt", ".csv", ".rst"}

#: A shell call that drives infrastructure rather than checking a file.
INFRA_RE = re.compile(
    r"\b(docker|podman|docker-compose|\./deploy|systemctl|ssh\s|scp\s|uvicorn|vite|"
    r"npm\s+run|cargo\s+run|temporal|clickhouse-client|searchd|garage)\b"
)

#: A shell call that writes a file. Group 1 or 2 is the path it wrote.
SHELL_WRITE_RES = (
    re.compile(r"(?:^|[;&|]\s*)(?:cat|tee|printf|echo)\b[^>]*>>?\s*['\"]?([^\s'\"|;&]+)"),
    re.compile(r"\bsed\s+-i\b[^\n]*?\s(['\"]?)([^\s'\";|&]+)\1\s*$", re.M),
    re.compile(r"(?:^|\s)>>?\s*['\"]?([^\s'\"|;&]+)"),
)

#: Codex routes a file write through `apply_patch` inside its one `exec` tool.
APPLY_PATCH_RE = re.compile(r"\*\*\* (?:Update|Add|Delete) File:\s*(\S+)")

#: Cursor prefixes a configured model and suffixes its reasoning effort. The tracker writes
#: the bare name for the same model, so both are reduced to the bare name plus an effort.
CURSOR_MODEL_RE = re.compile(
    r"^(?:cursor-)?(.*?)(?:-(low|medium|high|xhigh|max|fast))?$")


def split_model(name):
    """Return the bare model name and the reasoning effort a harness folded into it."""
    if not name:
        return None, None
    match = CURSOR_MODEL_RE.match(name)
    if not match:
        return name, None
    return match.group(1) or name, match.group(2)


def iso(value):
    """Parse any of the three timestamp shapes the four harnesses use."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Milliseconds since the epoch, which kimi and cursor both use.
        seconds = value / 1000.0 if value > 1e11 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def rows(path):
    """Yield every parsable JSON object in a JSON-lines file."""
    try:
        handle = open(path, errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


class Pass:
    """One pass under construction, in the normalized shape every harness produces."""

    def __init__(self, harness, kind, ident, session=None, project=None, agent=None):
        self.harness = harness
        self.kind = kind
        self.id = ident
        self.session = session
        self.project = project
        self.agent = agent
        self.efforts = {}
        self.first = None
        self.last = None
        self.turns = 0
        self.tool_calls = 0
        self.write_calls = 0
        self.shell_calls = 0
        self.infra_shell_calls = 0
        self.written = []
        self.prompts = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read = 0
        self.cache_write = 0
        self.models = {}
        self.final_context = None
        self.first_write_at = None
        self.last_write_at = None
        self.first_code_write_at = None
        self.last_code_write_at = None

    def stamp(self, value):
        moment = iso(value)
        if moment is None:
            return
        if self.first is None or moment < self.first:
            self.first = moment
        if self.last is None or moment > self.last:
            self.last = moment

    def model(self, name, count=1):
        bare, effort = split_model(name)
        if bare:
            self.models[bare] = self.models.get(bare, 0) + count
        if effort:
            self.efforts[effort] = self.efforts.get(effort, 0) + count

    def wrote(self, path):
        """Record one written path, and where in the call sequence the write happened.

        The position is what makes the fixed cost of a pass measurable. Calls before the
        first write are the pass reading its package and orienting. Calls after the last
        write are the pass checking and reporting. Neither produces work.

        The code position is tracked apart from the write position because a pass's own
        report is a prose write. Measuring against every write puts the report inside the
        work and leaves an epilogue of one call, which is an artefact of the deliverable
        rather than a measurement of reporting.
        """
        if not path:
            return
        self.written.append(str(path))
        if self.first_write_at is None:
            self.first_write_at = self.tool_calls
        self.last_write_at = self.tool_calls
        if pathlib.PurePath(path).suffix.lower() not in PROSE_SUFFIXES:
            if self.first_code_write_at is None:
                self.first_code_write_at = self.tool_calls
            self.last_code_write_at = self.tool_calls

    def shell(self, command):
        """Count one shell call, and every file it wrote."""
        self.shell_calls += 1
        if not command:
            return
        if INFRA_RE.search(command):
            self.infra_shell_calls += 1
        for pattern in SHELL_WRITE_RES:
            for match in pattern.finditer(command):
                self.wrote(match.group(match.lastindex or 1))

    @property
    def code_writes(self):
        return sum(1 for p in self.written
                   if pathlib.PurePath(p).suffix.lower() not in PROSE_SUFFIXES)

    @property
    def prose_writes(self):
        return sum(1 for p in self.written
                   if pathlib.PurePath(p).suffix.lower() in PROSE_SUFFIXES)

    def bucket(self):
        if self.code_writes:
            return "implementation"
        if (self.infra_shell_calls >= 3
                and self.shell_calls
                and self.infra_shell_calls >= 0.1 * self.shell_calls):
            return "operational"
        if not self.written:
            return "read-only review"
        return "documentation"

    def record(self):
        minutes = None
        if self.first and self.last:
            minutes = (self.last - self.first).total_seconds() / 60.0
        peak = max(self.prompts) if self.prompts else self.final_context
        compactions = sum(
            1 for i in range(1, len(self.prompts))
            if self.prompts[i - 1] - self.prompts[i] > COMPACTION_DROP
        )
        primary = max(self.models, key=self.models.get) if self.models else None
        effort = max(self.efforts, key=self.efforts.get) if self.efforts else None
        return {
            "harness": self.harness,
            "kind": self.kind,
            "id": self.id,
            "session": self.session,
            "project": self.project,
            "agent": self.agent,
            "model": primary,
            "effort": effort,
            "models": self.models or None,
            "start": self.first.isoformat() if self.first else None,
            "end": self.last.isoformat() if self.last else None,
            "minutes": round(minutes, 2) if minutes is not None else None,
            "turns": self.turns or None,
            "tool_calls": self.tool_calls,
            "write_calls": self.write_calls,
            "shell_calls": self.shell_calls,
            "infra_shell_calls": self.infra_shell_calls,
            "code_writes": self.code_writes,
            "prose_writes": self.prose_writes,
            "written_paths": len(set(self.written)) or None,
            "peak_context": peak,
            "first_context": self.prompts[0] if self.prompts else None,
            "peak_is_final_only": bool(not self.prompts and self.final_context),
            "calls_before_first_write": self.first_write_at,
            "calls_after_last_write": (
                self.tool_calls - self.last_write_at
                if self.last_write_at is not None else None),
            "calls_before_first_code_write": self.first_code_write_at,
            "calls_after_last_code_write": (
                self.tool_calls - self.last_code_write_at
                if self.last_code_write_at is not None else None),
            "input_tokens": self.input_tokens or None,
            "output_tokens": self.output_tokens or None,
            "cache_read": self.cache_read or None,
            "cache_write": self.cache_write or None,
            "compactions": compactions if self.prompts else None,
            "bucket": self.bucket(),
        }


# ---------------------------------------------------------------- claude code

CLAUDE_WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}


def claude_consume(pas, seq):
    for row in seq:
        pas.stamp(row.get("timestamp"))
        if row.get("type") != "assistant":
            continue
        pas.turns += 1
        message = row.get("message") or {}
        pas.model(message.get("model"))
        usage = message.get("usage") or {}
        if usage:
            prompt = (usage.get("input_tokens", 0)
                      + usage.get("cache_read_input_tokens", 0)
                      + usage.get("cache_creation_input_tokens", 0))
            pas.prompts.append(prompt)
            pas.input_tokens += usage.get("input_tokens", 0)
            pas.output_tokens += usage.get("output_tokens", 0)
            pas.cache_read += usage.get("cache_read_input_tokens", 0)
            pas.cache_write += usage.get("cache_creation_input_tokens", 0)
        for block in message.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            pas.tool_calls += 1
            name = block.get("name")
            args = block.get("input") or {}
            if name in CLAUDE_WRITE_TOOLS:
                pas.write_calls += 1
                pas.wrote(args.get("file_path") or args.get("notebook_path"))
            elif name == "Bash":
                pas.shell(args.get("command"))


def claude_passes(repo):
    slug = "-" + repo.strip("/").replace("/", "-")
    root = pathlib.Path(os.path.expanduser("~/.claude/projects")) / slug
    if not root.is_dir():
        return
    for session in sorted(root.glob("*.jsonl")):
        pas = Pass("claude", "session", session.stem, session.stem, repo)
        claude_consume(pas, rows(session))
        if pas.turns:
            yield pas.record()
    for agent in sorted(root.glob("*/subagents/agent-*.jsonl")):
        # The sidecar names the agent type the pass ran as, which is what decides its
        # tool-call budget. It is absent on older passes.
        meta = agent.with_suffix("").with_suffix(".meta.json")
        kind_of_agent = None
        if meta.exists():
            try:
                loaded = json.loads(meta.read_text())
                kind_of_agent = loaded.get("agentType") or loaded.get("description")
            except (ValueError, OSError):
                pass
        pas = Pass("claude", "pass", agent.stem, agent.parent.parent.name, repo,
                   kind_of_agent)
        claude_consume(pas, rows(agent))
        if pas.turns:
            yield pas.record()


# ---------------------------------------------------------------------- codex

def codex_passes(repo):
    root = pathlib.Path(os.path.expanduser("~/.codex/sessions"))
    if not root.is_dir():
        return
    for rollout in sorted(root.rglob("rollout-*.jsonl")):
        pas = None
        for row in rows(rollout):
            kind = row.get("type")
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            if kind == "session_meta":
                if payload.get("cwd") != repo:
                    break
                thread = payload.get("thread_source")
                # A guardian thread judges one proposed action. It is not work, and
                # counting it as a pass halves every codex median.
                record_kind = {"guardian_review": "guard",
                               "subagent": "pass"}.get(thread, "session")
                pas = Pass("codex", record_kind,
                           payload.get("id") or rollout.stem,
                           payload.get("session_id"), repo,
                           payload.get("agent_nickname") or payload.get("agent_role"))
                pas.stamp(row.get("timestamp"))
                continue
            if pas is None:
                continue
            pas.stamp(row.get("timestamp"))
            if kind == "turn_context":
                pas.model(payload.get("model"))
            elif kind == "token_usage_record":
                usage = payload.get("usage") or {}
                # `input_tokens` is the whole prompt here, cached part included.
                pas.prompts.append(usage.get("input_tokens", 0))
                pas.input_tokens += usage.get("input_tokens", 0)
                pas.output_tokens += usage.get("output_tokens", 0)
                pas.cache_read += usage.get("cached_input_tokens", 0)
                pas.cache_write += usage.get("cache_write_input_tokens", 0)
                pas.turns += 1
            elif kind == "response_item" and payload.get("type") in (
                    "custom_tool_call", "function_call"):
                pas.tool_calls += 1
                name = payload.get("name")
                body = payload.get("input") or payload.get("arguments") or ""
                if name == "exec":
                    patched = APPLY_PATCH_RE.findall(body)
                    if patched:
                        pas.write_calls += 1
                        for path in patched:
                            pas.wrote(path)
                    else:
                        pas.shell(body)
        if pas is not None and (pas.turns or pas.tool_calls):
            yield pas.record()


# ----------------------------------------------------------------- kimi code

KIMI_WRITE_TOOLS = {"Edit", "Write", "MultiEdit"}


def kimi_passes(repo):
    root = pathlib.Path(os.path.expanduser("~/.kimi-code/sessions"))
    index = pathlib.Path(os.path.expanduser("~/.kimi-code/session_index.jsonl"))
    wanted = set()
    for row in rows(index):
        if row.get("workDir") == repo:
            wanted.add(row.get("sessionDir"))
    for wire in sorted(root.rglob("agents/*/wire.jsonl")):
        session_dir = str(wire.parent.parent.parent)
        if wanted and session_dir not in wanted:
            continue
        agent = wire.parent.name
        pas = Pass("kimi", "session" if agent == "main" else "pass",
                   f"{pathlib.Path(session_dir).name}/{agent}",
                   pathlib.Path(session_dir).name, repo)
        for row in rows(wire):
            pas.stamp(row.get("time"))
            kind = row.get("type")
            if kind == "llm.request":
                pas.model(row.get("modelAlias") or row.get("model"))
            elif kind == "usage.record":
                pas.model(row.get("model"))
            elif kind == "context.append_loop_event":
                event = row.get("event") or {}
                etype = event.get("type")
                if etype == "tool.call":
                    pas.tool_calls += 1
                    name = event.get("name")
                    args = event.get("args") or {}
                    if name in KIMI_WRITE_TOOLS:
                        pas.write_calls += 1
                        pas.wrote(args.get("path") or args.get("file_path"))
                    elif name == "Bash":
                        pas.shell(args.get("command") or args.get("cmd"))
                elif etype == "step.end":
                    pas.turns += 1
                    usage = event.get("usage") or {}
                    prompt = (usage.get("inputOther", 0)
                              + usage.get("inputCacheRead", 0)
                              + usage.get("inputCacheCreation", 0))
                    if prompt:
                        pas.prompts.append(prompt)
                    pas.input_tokens += usage.get("inputOther", 0)
                    pas.output_tokens += usage.get("output", 0)
                    pas.cache_read += usage.get("inputCacheRead", 0)
                    pas.cache_write += usage.get("inputCacheCreation", 0)
        if pas.turns or pas.tool_calls:
            yield pas.record()


# -------------------------------------------------------------------- cursor

CURSOR_WRITE_TOOLS = {"edit_file_v2", "edit_file", "delete_file", "create_file",
                      "search_replace", "write_file"}
CURSOR_SHELL_TOOLS = {"run_terminal_command_v2", "run_terminal_cmd"}


def cursor_models(repo):
    """Model per conversation, from the tracking database that records every AI write."""
    path = pathlib.Path(os.path.expanduser("~/.cursor/ai-tracking/ai-code-tracking.db"))
    found = {}
    if not path.exists():
        return found
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        query = ("SELECT conversationId, model, count(*) FROM ai_code_hashes "
                 "WHERE conversationId IS NOT NULL AND model IS NOT NULL "
                 "AND (fileName IS NULL OR fileName LIKE ?) GROUP BY 1, 2")
        for conversation, model, count in con.execute(query, (repo + "%",)):
            found.setdefault(conversation, {})[model] = count
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return found


def cursor_passes(repo):
    path = pathlib.Path(os.path.expanduser(
        "~/.config/Cursor/User/globalStorage/state.vscdb"))
    if not path.exists():
        return
    con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    tracked = cursor_models(repo)
    headers = {}
    try:
        for row in con.execute("SELECT composerId, createdAt, lastUpdatedAt, isSubagent "
                               "FROM composerHeaders"):
            headers[row[0]] = row
    except sqlite3.Error:
        pass

    # One pass per conversation. Bubbles carry the tool calls and the timestamps.
    bubbles = {}
    for key, value in con.execute(
            "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'"):
        parts = key.split(":")
        if len(parts) < 3:
            continue
        bubbles.setdefault(parts[1], []).append(value)

    for key, value in con.execute(
            "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'"):
        try:
            data = json.loads(value)
        except ValueError:
            continue
        composer = key.split(":", 1)[1]
        header = headers.get(composer)
        is_sub = bool(header and header[3])
        pas = Pass("cursor", "pass" if is_sub else "session", composer, composer, repo)
        if header:
            pas.stamp(header[1])
            pas.stamp(header[2])
        config = data.get("modelConfig") or {}
        name = config.get("modelName")
        if name and name != "default":
            pas.model(name)
        for model, count in (tracked.get(composer) or {}).items():
            pas.model(model, count)
        pas.final_context = data.get("contextTokensUsed")

        touched_repo = False
        for raw in bubbles.get(composer, ()):
            try:
                bubble = json.loads(raw)
            except ValueError:
                continue
            pas.turns += 1
            pas.stamp(bubble.get("createdAt"))
            info = bubble.get("modelInfo") or {}
            pas.model(info.get("modelName"))
            tool = bubble.get("toolFormerData")
            if not tool:
                continue
            pas.tool_calls += 1
            tname = tool.get("name")
            params = tool.get("params") or tool.get("rawArgs") or "{}"
            try:
                args = json.loads(params) if isinstance(params, str) else params
            except ValueError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            target = (args.get("targetFile") or args.get("path")
                      or args.get("effectiveUri") or args.get("file"))
            if target and repo in str(target):
                touched_repo = True
            if tname in CURSOR_WRITE_TOOLS:
                pas.write_calls += 1
                pas.wrote(target)
            elif tname in CURSOR_SHELL_TOOLS:
                pas.shell(args.get("command") or args.get("cmd"))
        if not touched_repo and composer not in tracked:
            continue
        if pas.turns or pas.tool_calls:
            yield pas.record()
    con.close()


# ----------------------------------------------------------------------- main

HARNESSES = {
    "claude": claude_passes,
    "codex": codex_passes,
    "kimi": kimi_passes,
    "cursor": cursor_passes,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="passes.jsonl")
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--harness", action="append", choices=sorted(HARNESSES))
    args = parser.parse_args()

    chosen = args.harness or sorted(HARNESSES)
    out = pathlib.Path(args.out)
    counts = {}
    with out.open("w") as handle:
        for name in chosen:
            found = 0
            for record in HARNESSES[name](args.repo):
                handle.write(json.dumps(record) + "\n")
                found += 1
            counts[name] = found
    for name in chosen:
        print(f"{name:8s} {counts[name]:5d} records", file=sys.stderr)
    print(f"wrote {out} with {sum(counts.values())} records", file=sys.stderr)


if __name__ == "__main__":
    main()
