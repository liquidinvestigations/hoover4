#!/usr/bin/env python3
"""PreToolUse(Bash): refuse a recursive text search that would walk build output.

`grep` here is shimmed to ugrep, which does not skip build trees and runs at an
elevated priority. `website/target` alone is tens of gigabytes, so a recursive search
rooted at the repo (or at a directory that contains it) burns a core for over an hour
and reports as "no output" -- indistinguishable from a search that found nothing.

The predicate is deliberately narrow. It fires only when ALL of these hold for one
top-level command in the pipeline:

  * the command word is a text-search binary (grep family, rg, ag, ack);
  * it searches recursively (an -r/-R flag, or the tool recurses by default);
  * it carries no filter of any kind (--include/--exclude-dir/--glob/--type/…);
  * every path operand is a build-bearing directory: the repo root, `.`, or one of
    the directories that contains a build tree.

Anything it cannot parse, anything behind `docker exec`/`ssh`, anything reading a
pipe, and any search naming a specific subdirectory or file is allowed. A false
negative costs one slow search; a false positive stops the session.

Reads the hook payload on stdin, writes a JSON permission decision on stdout.
"""
import json
import os
import re
import shlex
import sys

SEARCH_BINARIES = {"grep", "egrep", "fgrep", "ugrep", "ug", "rg", "ripgrep", "ag", "ack"}
# These recurse with no -r flag at all.
RECURSIVE_BY_DEFAULT = {"rg", "ripgrep", "ag", "ack"}

# Any one of these makes the walk bounded enough to allow.
FILTER_FLAGS = (
    "--include", "--exclude", "--exclude-dir", "--exclude-from",
    "-g", "--glob", "--iglob", "--type", "--type-not", "-t", "-T",
    "--files-from", "--include-dir", "--ignore-file", "--max-depth", "-d", "--depth",
    "--file-type", "-O", "-M", "-N",  # ugrep's file-type selectors
)

# Directories whose subtree contains a build tree on this checkout. A recursive
# search rooted at any of these is the expensive case.
BUILD_BEARING = {"", ".", "./", "/", "website", "website/", "./website", "website/target",
                 "node_modules", "target"}

# The checkout's path is not written down anywhere: it is the harness's project directory
# when the harness sets one, and otherwise the directory two levels above this hook.
REPO_ROOT = os.environ.get(
    "CLAUDE_PROJECT_DIR",
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
).rstrip("/")

MESSAGE = """Blocked: recursive search with no filter, rooted at a directory that contains build output.

`grep` is shimmed to ugrep and does not skip build trees; `website/target` is tens of
gigabytes, so this burns a core for over an hour and returns "no output", which looks
exactly like a search that found nothing.

Re-run it scoped, any one of these is enough:
  grep -rn 'PATTERN' --include='*.rs' --include='*.py' .
  grep -rn 'PATTERN' --exclude-dir=target --exclude-dir=node_modules --exclude-dir=__pycache__ .
  grep -rn 'PATTERN' main_services/processing/tasks
  rg 'PATTERN' -t rust website/backend/src

To find a symbol rather than a string, ask serena (find_symbol,
find_referencing_symbols) instead -- it answers from an index, not a walk."""


def split_segments(cmd):
    """Split a command line into top-level segments on ; && || | and newlines.

    Quote-aware and parenthesis-blind: a segment inside quotes (`sh -lc '...'`) stays
    part of its parent segment, which is what we want -- that search runs somewhere
    else's filesystem.
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
        elif c in ";\n":
            segments.append("".join(current))
            current = []
        elif c == "&" and cmd[i:i + 2] == "&&":
            segments.append("".join(current))
            current = []
            i += 1
        elif c == "|":
            if cmd[i:i + 2] == "||":
                i += 1
            segments.append("".join(current))
            current = []
            # Mark the next segment as reading a pipe: a search on stdin is not a walk.
            current.append("\0PIPED\0")
        else:
            current.append(c)
        i += 1
    segments.append("".join(current))
    return segments


def command_word(tokens):
    """Drop leading env assignments and harmless prefixes; return (word, rest)."""
    prefixes = {"sudo", "time", "nice", "ionice", "command", "exec", "nohup", "timeout"}
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
            i += 1
        elif t in prefixes:
            i += 1
            # `timeout 30 grep …` -- skip its numeric argument too.
            while i < len(tokens) and re.match(r"^[0-9]+[smhd]?$", tokens[i]):
                i += 1
        else:
            break
    if i >= len(tokens):
        return None, []
    return os.path.basename(tokens[i]), tokens[i + 1:]


# grep options that consume the following argument, so it is not a path operand.
OPT_TAKES_ARG = {"-e", "-f", "--regexp", "--file", "-m", "--max-count", "-A", "-B", "-C",
                 "--after-context", "--before-context", "--context", "-D", "--devices",
                 "--color", "--colour", "--binary-files", "-J", "--jobs", "-P"}


def is_unscoped_recursive(segment):
    if "\0PIPED\0" in segment:
        return False
    segment = segment.replace("\0PIPED\0", "").strip()
    if not segment:
        return False
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return False           # unbalanced quotes: not ours to judge
    word, args = command_word(tokens)
    if word not in SEARCH_BINARIES:
        return False
    # Redirections survive shlex as ordinary tokens and would otherwise be read as
    # path operands ("rg --version 2>/dev/null" is not a walk of the repo).
    cleaned, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if re.match(r"^[0-9]*(>>|>|<)", a):
            if re.match(r"^[0-9]*(>>|>|<)$", a):
                skip = True
            continue
        cleaned.append(a)
    args = cleaned

    recursive = word in RECURSIVE_BY_DEFAULT
    filtered = False
    paths, pattern_taken, i = [], False, 0
    while i < len(args):
        a = args[i]
        if a == "--":
            paths.extend(args[i + 1:])
            break
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            if name in FILTER_FLAGS:
                filtered = True
            if name in ("--recursive", "--dereference-recursive"):
                recursive = True
            if name in OPT_TAKES_ARG and "=" not in a:
                i += 1
            if name in ("--regexp", "--file"):
                pattern_taken = True
        elif a.startswith("-") and len(a) > 1:
            if a in FILTER_FLAGS:
                filtered = True
                if a in ("-g", "--glob", "-t", "--type", "-d", "--depth", "-O", "-M", "-N"):
                    i += 1
            elif a in OPT_TAKES_ARG:
                if a in ("-e", "-f", "--regexp", "--file"):
                    pattern_taken = True
                i += 1
            else:
                # Bundled short flags: -rn, -rIn, -Ri …
                body = a[1:]
                if "r" in body or "R" in body:
                    recursive = True
                # A bundled flag whose last letter takes an argument eats the next token.
                if body and ("-" + body[-1]) in OPT_TAKES_ARG:
                    if body[-1] in "ef":
                        pattern_taken = True
                    i += 1
        else:
            if not pattern_taken:
                pattern_taken = True     # first bare operand is the pattern
            else:
                paths.append(a)
        i += 1

    if not recursive or filtered:
        return False
    if not pattern_taken:
        return False

    if not paths:
        paths = ["."]                     # implicit cwd
    for p in paths:
        norm = p.rstrip("/") or "/"
        if norm.startswith(REPO_ROOT):
            norm = norm[len(REPO_ROOT):].lstrip("/")
        norm = norm.lstrip("./") if norm.startswith("./") else norm
        if norm not in BUILD_BEARING and (norm + "/") not in BUILD_BEARING:
            return False                  # names a real subdirectory: allowed
    return True


def cwd_is_build_bearing(cwd):
    """`cd website/frontend/src && grep -rn X .` is scoped; the bare `.` is not.

    Without this the predicate reads every post-`cd` dot as the repo root, which is the
    single largest source of false positives -- it is how a search of one component
    directory gets mistaken for a walk of the whole checkout.
    """
    if cwd is None:
        return True                       # no cd: the session's cwd is the repo root
    norm = cwd.rstrip("/")
    if norm.startswith(REPO_ROOT):
        norm = norm[len(REPO_ROOT):].lstrip("/")
    return norm in BUILD_BEARING


def check(command, session_cwd=None):
    """Return the offending segment, or None.

    `session_cwd` is the hook payload's `cwd`: the Bash tool keeps its working
    directory between calls, so a `cd` from an earlier call is invisible in this
    command line and only the payload can say where `.` points.
    """
    cwd = None if cwd_is_build_bearing(session_cwd) else session_cwd
    for segment in split_segments(command):
        body = segment.replace("\0PIPED\0", "").strip()
        try:
            tokens = shlex.split(body)
        except ValueError:
            tokens = []
        word, args = command_word(tokens) if tokens else (None, [])
        if word == "cd" and args:
            cwd = args[0]
            continue
        if is_unscoped_recursive(segment) and cwd_is_build_bearing(cwd):
            return body
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    command = payload.get("tool_input", {}).get("command", "")
    offender = check(command, payload.get("cwd"))
    if not offender:
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"{MESSAGE}\n\nThe segment that triggered this:\n  {offender.strip()[:300]}\n"
                "If the rest of the command line was fine, re-send it with only that "
                "segment scoped."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        hit = check(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
        print("DENY: " + hit if hit else "allow")
        sys.exit(0)
    sys.exit(main())
