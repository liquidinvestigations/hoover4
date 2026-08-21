#!/usr/bin/env python3
"""PreToolUse(Bash): refuse `git commit` with a multi-line or over-long message.

House style is one line, lowercase, under ~50 characters, and `git log --oneline` is
the only view that matters. This hook is insurance, not a fix: the practice has been
compliant for a long stretch and every commit on `main` satisfies it.

Conservative by construction. It fires only when the message text is knowable
statically and unambiguously wrong:

  * more than one `-m`  (git joins them into paragraphs);
  * a message containing a newline;
  * a message longer than HARD_LIMIT characters.

It never fires on a message containing a shell substitution (`$(...)`, backticks,
`${...}`) because the final text is not knowable; it never fires on `-F/--file`,
`--amend --no-edit`, `-C/-c`, or an editor-driven commit; and it never fires on
anything it cannot parse.

HARD_LIMIT is deliberately well above the ~50-character style target: a hook that
argues about 54 versus 50 characters is a work stoppage, and the style is already
being followed. The rule teaches 50; the hook stops 80.
"""
import json
import re
import shlex
import sys

HARD_LIMIT = 80

MESSAGE_TEMPLATE = """Blocked: this commit message is not one short line.

{problem}

House style, and it is not negotiable: exactly one line, all lowercase, under ~50
characters, no body, no bullet list, no "Summary", no rationale, no trailer, no
co-author line, no issue link. `git log --oneline` is a table of contents, not a
changelog.

Re-run with a single short subject, for example:
  git commit -m "fix chat streaming"

If the change needs explaining, the explanation goes in the `Readme.md` next to the
code, as a present-tense statement about how the code works -- never in git."""


def split_segments(cmd):
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


DYNAMIC = re.compile(r"\$\(|\$\{|`")


def messages_of(segment):
    """Return the -m values of a `git commit`, or None if this is not our business."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return None
    tokens = [t for t in tokens if not re.match(r"^[0-9]*(>>|>|<)", t)]
    if not tokens:
        return None
    # Only a top-level git; `docker exec c git commit …` commits somewhere else.
    if tokens[0] != "git":
        return None
    rest = tokens[1:]
    while rest and rest[0] in ("-C", "-c", "--no-pager", "--git-dir", "--work-tree"):
        rest = rest[2:] if rest[0] in ("-C", "-c", "--git-dir", "--work-tree") else rest[1:]
    if not rest or rest[0] != "commit":
        return None
    if any(t in ("-F", "--file", "-C", "-c", "--reuse-message", "--squash", "--fixup")
           for t in rest):
        return None
    messages, i = [], 1
    while i < len(rest):
        t = rest[i]
        # `-m`, `--message`, and the bundled form `-am` / `-qm`, whose value is the
        # next token.
        if t == "--message" or re.match(r"^-[a-zA-Z]*m$", t):
            if i + 1 < len(rest):
                messages.append(rest[i + 1])
            i += 2
            continue
        if t.startswith("--message="):
            messages.append(t.split("=", 1)[1])
        elif t.startswith("-m") and len(t) > 2:
            messages.append(t[2:])
        i += 1
    return messages


def check(command):
    """Return a problem description, or None."""
    for segment in split_segments(command):
        if DYNAMIC.search(segment):
            continue                       # final text is not knowable: not our call
        messages = messages_of(segment)
        if not messages:
            continue
        if len(messages) > 1:
            return (f"It passes -m {len(messages)} times; git joins those into "
                    "paragraphs, which is a commit body.")
        text = messages[0]
        if "\n" in text:
            return "It spans multiple lines."
        if len(text) > HARD_LIMIT:
            return (f"Its subject is {len(text)} characters; the limit here is ~50 "
                    f"and this hook refuses anything over {HARD_LIMIT}.")
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    problem = check(payload.get("tool_input", {}).get("command", ""))
    if not problem:
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": MESSAGE_TEMPLATE.format(problem=problem),
        }
    }))
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        hit = check(sys.argv[2])
        print("DENY: " + hit if hit else "allow")
        sys.exit(0)
    sys.exit(main())
