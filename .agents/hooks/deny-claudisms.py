#!/usr/bin/env python3
"""PreToolUse(Edit|Write|MultiEdit): refuse text that adds a banned phrase or an em dash.

`AGENTS.md`, "How to write", sets the register: Simplified Technical English (ASD-STE100)
and plain language (ISO 24495-1). Two of its rules are mechanical, so a hook can hold them.
The rest are judgement and belong to the reader.

Only the text being ADDED is inspected. Deleting a banned phrase, or moving a file that
contains one, is allowed. `Edit` compares `new_string` against `old_string`, so a rewrite
that keeps an existing occurrence in place is not blocked.

Narrow by construction:

  * it fires on `.md`, `.rs`, `.py`, `.sh`, `.sql`, `.toml` and `.yaml` only;
  * it exempts the documents that define the rule, which have to quote every word they ban;
  * it exempts the two frozen migration directories, the vendored trees and `plans/`;
  * it never fires on anything it cannot parse.

`.agents/check-prose-style.py` reports the same phrases over the whole tree, plus the
structural shapes no hook should block. The two share this list by copy, and the copy is
deliberate: a hook that imports a checker fails closed when the checker moves.

Reads the hook payload on stdin, writes a JSON permission decision on stdout.
"""
import json
import os
import re
import sys

EM_DASH = "—"

EXTENSIONS = (".md", ".rs", ".py", ".sh", ".sql", ".toml", ".yaml", ".yml")

# Paths whose text may hold a banned word. The first six define the rule and have to quote
# it. The rest are vendored or generated, or are gitignored scratch. The migration
# directories are not here: a new migration is written in the register like anything else.
EXEMPT = (
    "AGENTS.md",
    ".agents/check-prose-style.py",
    ".agents/hooks/deny-claudisms.py",
    ".agents/skills/writing-project-docs/SKILL.md",
    "docs/development/Documentation_Standards.md",
    # It probes this hook, so it has to hold a phrase the hook rejects.
    ".agents/verify-wiring.sh",
    # `nice` is banned in prose, but this file holds it as the Unix command, in the
    # prefix set beside `ionice` and `nohup`.
    ".agents/hooks/deny-unscoped-search.py",
    "/plans/",
    "/website/backend/pdf-viewer/_server/dist/",
    "/website/frontend/assets/",
    "/website/target/",
    "/node_modules/",
    "/vendored/",
)

PHRASES = [
    r"load[- ]bearing",
    r"\bseams?\b",
    r"blast radius",
    r"surface area",
    r"guardrails?\b",
    r"tripwires?\b",
    r"footguns?\b",
    r"escape hatch",
    r"north star",
    r"moving parts",
    r"\bplumbing\b",
    r"glue code",
    r"happy path",
    r"sharp edges?\b",
    r"quality gates?\b",
    r"long pole",
    r"table stakes",
    r"paper cuts?\b",
    r"chesterton's fence",
    r"worth stating plainly",
    r"(?:it is|it's|its)? ?worth noting",
    r"to be clear\b",
    r"the honest (?:answer|take)",
    r"here's the thing",
    r"make no mistake",
    r"the whole point",
    r"what matters is",
    r"earns? its keep",
    r"does the work\b",
    r"carries the argument",
    r"\bcrucially\b",
    r"\bnotably\b",
    r"\bimportantly\b",
    r"\bfundamentally\b",
    r"\bultimately\b",
    r"is ?n[o']t just\b",
    r"are ?n[o']t just\b",
    r"it'?s not (?:a |an |the )?\w+, it'?s\b",
    r"this is not (?:a |an |the )?\w+, it is\b",
    # five pre-emptive classes, absent or near-absent in the tree today
    r"\bunfortunately\b", r"\bfortunately\b", r"\bluckily\b", r"\bthankfully\b",
    r"\bsadly\b", r"\bhappily\b", r"\btragically\b", r"\bhopefully\b",
    r"\bpainful\b", r"\bpainless\b", r"\bbeautiful\b", r"\belegant\b",
    r"\blovely\b", r"\bawesome\b", r"\bnice\b", r"\bneat\b", r"\bslick\b",
    r"\bannoying\b", r"\bfrustrating\b", r"\btedious\b", r"\bbrutal\b",
    r"\bsavage\b", r"\bafraid\b", r"\bworried\b", r"\bscary\b", r"\bterrifying\b",
    r"\bseamless\b", r"\bpowerful\b", r"best practices?\b",
    r"state[- ]of[- ]the[- ]art", r"cutting[- ]edge", r"world[- ]class",
    r"best[- ]in[- ]class", r"industry[- ]leading", r"\bunprecedented\b",
    r"\bgroundbreaking\b", r"\brevolutionary\b", r"game[- ]changers?\b",
    r"paradigm shifts?\b", r"\brobust\b", r"\bcomprehensive\b",
    r"\bdelve\b", r"\bintricate\b", r"\bmeticulous\b", r"\bpivotal\b",
    r"\brealm\b", r"\blandscape\b", r"\bshowcase\b", r"\bleverage\b",
    r"\butilize\b", r"\bfoster\b", r"\bstreamline\b", r"\bempower\b",
    r"\btestament\b", r"\btapestry\b", r"\bembark\b", r"\bjourney\b",
    r"deep dive", r"dive into",
    r"\bbasically\b", r"\bessentially\b", r"\barguably\b", r"\binterestingly\b",
    r"\bstuff\b", r"\bgotcha\b", r"tons of\b", r"bunch of\b", r"loads of\b",
    r"\bnuke\b", r"blow away", r"at the end of the day", r"let(?:'|’)s\b",
    # `mad` is scoped case-sensitive: `MAD`, the ISO 4217 code for the Moroccan dirham,
    # stays legal. Every other word on this line matches case-insensitively.
    r"\bcrazy\b", r"\binsane\b", r"(?-i:\bmad\b)", r"\blunatic\b", r"\bbonkers\b",
    r"\bloony\b",
    # narrower than the plain word: `underscore` bans the past and present participle
    # only, so `underscored` and `underscoring` match. The bare noun and its plural
    # ("alphanumerics and underscores") stay legal, because that spelling is identical to
    # the third-person verb ("this underscores the point"), which the tree does not use.
    # `novel` bans the adjective only, so it does not catch the noun for a book.
    r"\bunderscor(?:ed|ing)\b",
    r"\bnovel\b(?!\s*[.,;:!?]|\s+(?:by|about|titled|called|is|was))",
    # The `honest` family and the `lie` family, banned outright.
    r"\bhonest(y|ly)?\b",
    r"\b(lie|lies|lied|lying)\b",
]
COMPILED = [re.compile(p, re.I) for p in PHRASES]

# `full stop` naming the punctuation mark is the correct term for it. Only the emphasis
# particle, which closes a sentence on its own, is banned.
FULL_STOP = re.compile(r"(?:^|[.,;:]\s*)full stop\s*[.!]", re.I)

MESSAGE = """Blocked: this text adds {what}.

{detail}

AGENTS.md, "How to write", sets the register for every Readme, docstring, comment, plan and
report here: Simplified Technical English (ASD-STE100) and plain language (ISO 24495-1).

For a banned phrase, say what depends on what and what breaks without it. "The guard is
load-bearing" says nothing; "without the guard a re-parse writes two rows for one segment"
says the same thing and is checkable.

For an em dash, read the sentence and pick the punctuation it needs:
  a comma, when the clause is an aside inside the sentence;
  a full stop and a new sentence, when the second half is an independent claim;
  brackets, when the aside is genuinely parenthetical;
  a colon, when the second half is a list or a literal.

`.agents/check-prose-style.py` reports the same over the whole tree."""


def is_exempt(path):
    if not path:
        return True
    norm = "/" + path.replace("\\", "/").lstrip("/")
    for e in EXEMPT:
        if e.startswith("/"):
            if e in norm:
                return True
        elif norm.endswith("/" + e):
            return True
    return False


def added_text(tool_name, tool_input):
    """The text this call ADDS, as one string, or None when there is nothing to judge."""
    if tool_name == "Write":
        return tool_input.get("content", "")
    if tool_name == "Edit":
        return diff_of(tool_input.get("old_string", ""), tool_input.get("new_string", ""))
    if tool_name == "MultiEdit":
        parts = []
        for edit in tool_input.get("edits", []):
            if isinstance(edit, dict):
                parts.append(diff_of(edit.get("old_string", ""),
                                     edit.get("new_string", "")))
        return "\n".join(parts)
    return None


def diff_of(old, new):
    """The lines of `new` that are not already in `old`.

    Line-granular on purpose. A rewrite that carries an existing banned phrase through
    unchanged keeps that line identical, so it is not read as an addition.
    """
    old_lines = set(old.split("\n"))
    return "\n".join(line for line in new.split("\n") if line not in old_lines)


def check(text):
    """Return (what, detail), or None."""
    if not text:
        return None
    if EM_DASH in text:
        for line in text.split("\n"):
            if EM_DASH in line:
                return ("an em dash", f"The line:\n  {line.strip()[:200]}")
    for rx in COMPILED:
        m = rx.search(text)
        if m:
            line = next((l for l in text.split("\n") if rx.search(l)), "")
            return (f'the banned phrase "{m.group(0).strip()}"',
                    f"The line:\n  {line.strip()[:200]}")
    m = FULL_STOP.search(text)
    if m:
        return ('the emphasis particle "full stop"',
                "Delete it. The sentence already says what it says.")
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    tool_name = payload.get("tool_name")
    if tool_name not in ("Edit", "Write", "MultiEdit"):
        return 0
    tool_input = payload.get("tool_input", {}) or {}
    path = tool_input.get("file_path", "")
    if os.path.splitext(path)[1] not in EXTENSIONS:
        return 0
    if is_exempt(path):
        return 0
    found = check(added_text(tool_name, tool_input))
    if not found:
        return 0
    what, detail = found
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": MESSAGE.format(what=what, detail=detail),
        }
    }))
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--test":
        hit = check(sys.argv[2])
        print("DENY: " + hit[0] if hit else "allow")
        sys.exit(0)
    sys.exit(main())
