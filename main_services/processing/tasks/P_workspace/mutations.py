"""The write and patch rules of workspace files, without storage.

`prepare` takes one command, the current version of its file and the citation evidence of
the session, and returns either a failure result or the new version and its result. The
writer workflow (`workflows.py`) commits what it returns. Nothing here reads or writes a
table, so a retry of the preparation gives the same answer for the same input.

**A write** replaces the whole file. An existing file needs `expected_version`, the version
that the agent read, so a write from a stale copy is refused. Content that repeats the read
gutter is refused. A write that keeps most lines of a large file gets the Hermes hint to use
a patch.

**A patch** replaces one region through the Hermes matcher (`hermes/fuzzy_match.py`). It
reports the strategy that matched, refuses an ambiguous match, and returns the closest lines
when nothing matches. When the old text is gone and the new text is present, the patch
succeeds as already applied and stores no version.

**Validation** checks every citation handle of the candidate (`references.check`). A
finding leaves the file unchanged and is the result of the call. A content without handles
passes.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from database.chat_workspace import (
    MAX_FILE_CHARS, FileVersion, looks_like_read_output, valid_name,
)
from tasks.P_workspace import references
from tasks.P_workspace.hermes import fuzzy_match

#: The Hermes thresholds of the rewrite hint.
REWRITE_HINT_MIN_CHARS = 20_000
REWRITE_HINT_MIN_UNCHANGED = 0.80
REWRITE_HINT_MAX_CHARS = 400_000

WRITE = "workspace_write"
PATCH = "workspace_patch"
READ = "workspace_read"
#: The upstream tool names and punctuation in the Hermes messages, and what the agent reads.
UPSTREAM_NAMES = (("write_file", WRITE), ("read_file", READ),
                  ("replace_all=True", "replace_all true"), (" " + chr(0x2014) + " ", ", "))


@dataclass
class Command:
    """One write or patch of the agent, as the session tool server forwards it."""

    username: str
    session_id: str
    operation_id: str
    run_id: str
    op: str
    name: str
    content: str = ""
    expected_version: Optional[int] = None
    old_string: str = ""
    new_string: str = ""
    replace_all: bool = False


@dataclass
class Prepared:
    """The outcome of one command. `version` is the row to commit, or None when the command
    stores no version. `result` is what the agent reads, and `ok` is its success.
    `found_version` is the version that the result names. `replay` is true when a stored
    receipt gave the result."""

    ok: bool
    result: dict
    version: Optional[FileVersion] = None
    name: str = ""
    found_version: int = 0
    replay: bool = False
    extra: dict = field(default_factory=dict)


def ours(text: str) -> str:
    """A Hermes message with the tool names of this agent."""
    for upstream, own in UPSTREAM_NAMES:
        text = text.replace(upstream, own)
    return text


def failure(cmd: Command, error: str, head: Optional[FileVersion], **extra: Any) -> Prepared:
    version = head.version if head else 0
    result = {"success": False, "name": cmd.name, "error": error,
              "file_changed": False, **extra}
    if version:
        result["current_version"] = version
    return Prepared(ok=False, result=result, name=cmd.name, found_version=version)


def rewrite_hint(old: str, new: str) -> str:
    """The Hermes hint for a write that keeps most lines of a large file, or empty."""
    if not (REWRITE_HINT_MIN_CHARS <= len(new) <= REWRITE_HINT_MAX_CHARS):
        return ""
    if not (REWRITE_HINT_MIN_CHARS <= len(old) <= REWRITE_HINT_MAX_CHARS):
        return ""
    old_lines, new_lines = old.splitlines(), new.splitlines()
    if not old_lines:
        return ""
    unchanged = sum((Counter(old_lines) & Counter(new_lines)).values())
    ratio = unchanged / max(len(old_lines), len(new_lines))
    if ratio < REWRITE_HINT_MIN_UNCHANGED:
        return ""
    changed = max(len(old_lines), len(new_lines)) - unchanged
    return (f"{unchanged:,} of {len(new_lines):,} lines were already in the file ({ratio:.0%} "
            f"unchanged), and about {changed:,} lines changed. For an edit like this use "
            f"{PATCH} with old_string and new_string, which sends only the changed region.")


def _candidate(cmd: Command, head: Optional[FileVersion]) -> tuple[Optional[str], dict, Optional[Prepared]]:
    """The candidate content, the patch record and a failure, of one command."""
    if cmd.op == "write":
        if not isinstance(cmd.content, str):
            return None, {}, failure(cmd, "Give the whole text of the file in content.", head)
        if looks_like_read_output(cmd.content):
            return None, {}, failure(cmd, (
                f"The content repeats the line numbers of a {READ} result. Send the text of "
                "the file without the N| prefix of each line."), head)
        if head is None and cmd.expected_version:
            return None, {}, failure(cmd, (
                f"{cmd.name} does not exist. Leave out expected_version to create it."), head)
        if head is not None and cmd.expected_version != head.version:
            sent = ("no expected_version" if cmd.expected_version is None
                    else f"expected_version {cmd.expected_version}")
            return None, {}, failure(cmd, (
                f"{cmd.name} is at version {head.version}, and the call sent {sent}. Read the "
                f"file with {READ}, then write it with expected_version {head.version}, or "
                f"change one region with {PATCH}."), head)
        return cmd.content, {}, None
    if cmd.op == "patch":
        if head is None:
            return None, {}, failure(cmd, f"{cmd.name} does not exist. Create it with {WRITE}.", head)
        new, count, strategy, error = fuzzy_match.fuzzy_find_and_replace(
            head.content, cmd.old_string, cmd.new_string, bool(cmd.replace_all))
        if error:
            if count == 0 and fuzzy_match.is_already_applied(head.content, cmd.old_string, cmd.new_string):
                return head.content, {"already_applied": True}, None
            hint = fuzzy_match.format_no_match_hint(error, count, cmd.old_string, head.content)
            return None, {}, failure(cmd, ours(error + hint), head)
        record = {"old_string": cmd.old_string, "new_string": cmd.new_string,
                  "replace_all": bool(cmd.replace_all), "strategy": strategy, "matches": count}
        return new, record, None
    return None, {}, failure(cmd, f"Unknown operation {cmd.op!r}.", head)


def prepare(cmd: Command, head: Optional[FileVersion], entries: Iterable[dict]) -> Prepared:
    """The outcome of one command against the current version `head` of its file."""
    problem = valid_name(cmd.name)
    if problem:
        return failure(cmd, problem, None)
    content, record, failed = _candidate(cmd, head)
    if failed is not None:
        return failed
    assert content is not None
    if len(content) > MAX_FILE_CHARS:
        return failure(cmd, (f"The file would have {len(content):,} characters, above the limit "
                             f"of {MAX_FILE_CHARS:,}. Split it into several files."), head)
    if head is not None and content == head.content:
        result = {"success": True, "name": cmd.name, "version": head.version, "unchanged": True,
                  "citations": [c.get("handle") for c in head.citations if c.get("handle")]}
        if record.get("already_applied"):
            result["note"] = "The edit appears to be already applied. The file did not change."
        else:
            result["note"] = "The content equals the current version. The file did not change."
        return Prepared(ok=True, result=result, name=cmd.name, found_version=head.version)
    findings, resolved = references.check(cmd.name, content, entries)
    if findings:
        return failure(cmd, ("The file was not changed, because a citation handle does not "
                             "resolve. Correct each finding and send the call again."),
                       head, findings=findings)
    number = (head.version if head else 0) + 1
    version = FileVersion(
        username=cmd.username, session_id=cmd.session_id, name=cmd.name, version=number,
        parent_version=head.version if head else 0, run_id=cmd.run_id,
        operation_id=cmd.operation_id, operation=cmd.op, content=content,
        citations=resolved, patch=record)
    result: dict[str, Any] = {"success": True, "name": cmd.name, "version": number,
                              "lines": len(content.splitlines()), "chars": len(content),
                              "citations": [c["handle"] for c in resolved]}
    if record.get("strategy") and record["strategy"] != "exact":
        result["match"] = record["strategy"]
        note = fuzzy_match.boundary_note([record["strategy"]])
        if note:
            result["note"] = ours(note)
    hint = rewrite_hint(head.content, content) if head is not None and cmd.op == "write" else ""
    if hint:
        result["hint"] = hint
    return Prepared(ok=True, result=result, version=version, name=cmd.name, found_version=number)


__all__ = ["Command", "PATCH", "Prepared", "READ", "WRITE", "ours", "prepare", "rewrite_hint"]
