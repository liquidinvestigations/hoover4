#!/usr/bin/env python3
"""PreToolUse(Bash): refuse `git push` in every form.

`AGENTS.md` states that git runs on the host and that the agent does not push. A person has
repeated that instruction eight times across seven sessions, in phrasings such as "commit but
do not push" and "leave the commit unpushed". An instruction repeated that often is one that
prose does not hold, so this hook refuses the action instead of asking again.

A push cannot be taken back, which is why this is a refusal and never a warning. It fires on
`git push` alone, including `--force`, `-u`, an explicit remote and refspec, and `git push`
inside a compound command such as `cd website && git push`. It does not fire on `git status`,
`git commit`, `git log`, or any other git subcommand.

Reads the hook payload on stdin, writes a JSON permission decision on stdout.
"""
import json
import re
import shlex
import sys

MESSAGE = """Blocked: this session does not push.

Git runs on the host and the agent commits to the working branch and stops there. A push
cannot be taken back, so this is refused rather than warned about.

Leave the commit on the branch. If the change is ready to publish, say so and let the person
push it."""


def split_segments(cmd):
    """Split a command line into top-level segments on ; && || | and newlines.

    Quote-aware: a segment inside quotes (`sh -lc '...'`) stays part of its parent segment,
    which is what we want -- that push runs somewhere else's shell, not this one.
    """
    segments, current, quote, i = [], [], None, 0
    while i < len(cmd):
        c = cmd[i]
        if quote:
            current.append(c)
            if c == quote and cmd[i - 1] != "\\":
                quote = None
        elif c in "'\"":
            quote = c
            current.append(c)
        elif c in ";\n|":
            segments.append("".join(current))
            current = []
        elif c == "&" and cmd[i:i + 2] == "&&":
            segments.append("".join(current))
            current = []
            i += 1
        else:
            current.append(c)
        i += 1
    segments.append("".join(current))
    return segments


PREFIXES = {"sudo", "time", "nice", "ionice", "command", "exec", "nohup"}
GIT_OPTS_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
GIT_OPTS_BARE = {"--no-pager", "--paginate", "-p", "--bare", "--literal-pathspecs",
                  "--no-literal-pathspecs"}


def is_git_push(segment):
    """Return True if this segment's top-level command is `git ... push ...`."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return False           # unbalanced quotes: not ours to judge
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
            i += 1
        elif t in PREFIXES:
            i += 1
        else:
            break
    tokens = tokens[i:]
    if not tokens or tokens[0] != "git":
        return False
    rest = tokens[1:]
    while rest:
        if rest[0] in GIT_OPTS_WITH_ARG:
            rest = rest[2:]
        elif rest[0] in GIT_OPTS_BARE or rest[0].startswith("--git-dir=") \
                or rest[0].startswith("--work-tree=") or rest[0].startswith("--namespace="):
            rest = rest[1:]
        else:
            break
    return bool(rest) and rest[0] == "push"


def check(command):
    """Return the offending segment, or None."""
    for segment in split_segments(command):
        if is_git_push(segment):
            return segment.strip()
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    offender = check(payload.get("tool_input", {}).get("command", ""))
    if not offender:
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"{MESSAGE}\n\nThe segment that triggered this:\n  {offender[:300]}"
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        hit = check(sys.argv[2])
        print("DENY: " + hit if hit else "allow")
        sys.exit(0)
    sys.exit(main())
