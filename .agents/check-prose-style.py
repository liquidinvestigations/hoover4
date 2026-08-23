#!/usr/bin/env python3
"""Check prose register: the banned phrases and punctuation from AGENTS.md, "How to write".

The repository writes in Simplified Technical English (ASD-STE100) and meets ISO 24495-1.
Two levels are reported:

  error    a banned phrase, or an em dash
  warning  a structural shape the rule discourages: a `, not <clause>.` closer, a verbless
           sentence of eight words or fewer, a sentence over 25 words, a semicolon in a
           markdown paragraph, a second colon in a paragraph

Errors are mechanical and always real. Warnings are heuristic, because no regular expression
can tell a rhetorical fragment from a table caption, so they inform and never gate.

In markdown the scan skips fenced code blocks, inline code spans, link targets and table
separator rows. In a source file it reads comments only, and it reads them through a
deliberately narrow lens: `#` line comments, `//` line comments (`///` and `//!` included),
`--` line comments in SQL, and Python docstrings. A Rust `/* */` block and a shell heredoc
are not inspected, so a banned phrase inside one is missed.

Four documents have to quote the banned words in order to ban them. They are exempt from the
phrase check and are still checked for em dashes. RULE_DOCS holds them, and the same list
appears in `.agents/hooks/deny-claudisms.py`.

Usage:
    .agents/check-prose-style.py [path ...]     # default: whole repository
    .agents/check-prose-style.py --stats        # report counts instead of failing
    .agents/check-prose-style.py --errors-only  # hide the heuristic warnings

Exit status is 1 when any error is found, so it can gate a commit.
"""

import os
import re
import subprocess
import sys

# Vendored, generated, or third-party trees, plus the two frozen migration directories.
# The migration exclusion is not a preference: the runner records an md5 of the whole file,
# so correcting one word in an applied migration refuses to start on every deployment that
# already ran it. `plans/` is gitignored scratch that gets wiped.
EXCLUDE = (
    "/.git/", "/node_modules/", "/website/target/", "/target/debug/", "/target/release/",
    "/.venv/", "/.container/cargo/", "/vendored/", "/tmp/stage/", "/__pycache__/",
    "/site-packages/", "/bx/",
    "/db_global_migrations/", "/db_collection_migrations/",
    "/website/backend/pdf-viewer/_server/dist/", "/website/frontend/assets/embed-pdf/",
    "/website/frontend/assets/", "/components/pdf-viewer/",
    "/plans/",
)

EXCLUDE_SUFFIX = (".map", ".min.js", ".lock")

# Paths that define the rule and therefore quote every word it bans.
RULE_DOCS = (
    "AGENTS.md",
    ".agents/check-prose-style.py",
    ".agents/hooks/deny-claudisms.py",
    ".agents/skills/writing-project-docs/SKILL.md",
    "docs/development/Documentation_Standards.md",
    # It probes the hook, so it has to hold a phrase the hook rejects.
    ".agents/verify-wiring.sh",
)

COMMENT_MARK = {
    ".py": "#", ".sh": "#", ".bash": "#", ".toml": "#", ".yaml": "#", ".yml": "#",
    ".rs": "//", ".ts": "//", ".tsx": "//", ".js": "//",
    ".sql": "--",
}

EM_DASH = "—"

# Every entry is (name, compiled pattern). A pattern matches the banned use only: `full
# stop` as an emphasis particle is banned, and `a full stop` naming the punctuation mark is
# the correct term for it.
_PHRASES = [
    # metaphor where a plain word exists
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
    # emphasis particles and preambles
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
    # antithesis worn as a phrase
    r"is ?n[o']t just\b",
    r"are ?n[o']t just\b",
    r"it'?s not (?:a |an |the )?\w+, it'?s\b",
    r"this is not (?:a |an |the )?\w+, it is\b",
]
PHRASE_RE = [(p, re.compile(p, re.I)) for p in _PHRASES]

# `full stop` is only a Claudism when it closes a sentence on its own. Naming the
# punctuation mark ("use a comma, a full stop, or brackets") is the correct usage.
FULL_STOP_RE = re.compile(r"(?:^|[.,;:]\s*)full stop\s*[.!]", re.I)

# `, not <clause>.` used as a closer. A plain correction of fact ("by column name, not
# position") is legal, so this is a warning and not an error.
NOT_CLOSER_RE = re.compile(r",\s+not\s+[^,.;:]{4,60}[.!]\s*$")

TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")

# A sentence with none of these, and no word that inflects like a verb, is read as verbless.
VERBS = {
    "is", "are", "was", "were", "be", "been", "being", "am",
    "do", "does", "did", "done", "has", "have", "had",
    "can", "cannot", "could", "will", "would", "shall", "should", "may", "might", "must",
    "get", "gets", "got", "go", "goes", "went", "make", "makes", "made", "let", "lets",
    "run", "runs", "ran", "read", "reads", "write", "writes", "wrote", "use", "uses",
    "keep", "keeps", "kept", "say", "says", "said", "see", "sees", "saw", "know", "knows",
    "take", "takes", "took", "give", "gives", "gave", "put", "puts", "set", "sets",
    "add", "adds", "find", "finds", "found", "hold", "holds", "held", "leave", "leaves",
    "come", "comes", "came", "want", "wants", "need", "needs", "call", "calls",
    "fix", "fixes", "check", "checks", "stop", "stops", "start", "starts",
    "never", "always", "not", "no", "don't", "doesn't", "isn't", "aren't", "won't",
}
VERBISH_RE = re.compile(r"\w+(?:ed|ing|es|s)$")
NOT_VERBISH = {
    "this", "its", "his", "hers", "yours", "theirs", "as", "is", "was", "has",
    "process", "class", "less", "unless", "thus", "always", "perhaps", "series",
}


def strip_markdown_noise(lines):
    """Yield (lineno, text, is_table_row) with fences dropped and code spans blanked."""
    fence = None
    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        marker = None
        if stripped.startswith("```"):
            marker = "```"
        elif stripped.startswith("~~~"):
            marker = "~~~"
        if marker:
            fence = None if fence == marker else (fence or marker)
            continue
        if fence:
            continue
        if TABLE_SEP_RE.match(line) and "|" in line:
            continue
        text = re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line)
        # Link targets and autolinks are addresses, not prose.
        text = re.sub(r"\]\([^)]*\)", lambda m: " " * len(m.group(0)), text)
        text = re.sub(r"<https?://[^>]*>", lambda m: " " * len(m.group(0)), text)
        text = re.sub(r"^\s*\[[^\]]+\]:\s*\S+", lambda m: " " * len(m.group(0)), text)
        yield i, text, line.lstrip().startswith("|")


DOC_OPEN = re.compile(r'^\s*[rRbBuUfF]*("""|\'\'\')')


def triple_quotes(line, quote):
    """Yield (index, token) for every triple quote that is code punctuation.

    A triple quote inside an ordinary string literal is data. Walking the line character by
    character is what tells the two apart, and a regular expression cannot: a SQL block
    opened mid-line, or an apostrophe run inside a double-quoted sample, both fool one and
    invert the docstring state for every line after it.
    """
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if quote is not None:
            if line.startswith(quote, i):
                yield i, quote
                quote = None
                i += 3
                continue
            i += 1
            continue
        if line.startswith('"""', i) or line.startswith("'''", i):
            tok = line[i:i + 3]
            yield i, tok
            quote = tok
            i += 3
            continue
        if c == "#":
            return
        if c in "\"'":
            i += 1
            while i < n:
                if line[i] == "\\":
                    i += 2
                    continue
                if line[i] == c:
                    i += 1
                    break
                i += 1
            continue
        i += 1


def docstring_spans(lines):
    """{lineno: column where the prose starts} for every line inside a Python docstring.

    A triple-quoted block is a docstring only when its opener is the first thing on its
    line. Everything else is data.
    """
    spans, quote, is_doc, opener_col = {}, None, False, 0
    for i, line in enumerate(lines, 1):
        opened_here = False
        for pos, tok in triple_quotes(line, quote):
            if quote is None:
                quote = tok
                dm = DOC_OPEN.match(line)
                is_doc = bool(dm) and dm.end() == pos + 3
                opened_here, opener_col = True, pos + 3
            elif tok == quote:
                if is_doc:
                    spans[i] = opener_col if opened_here else 0
                quote, is_doc, opened_here = None, False, False
        if quote is not None and is_doc:
            spans[i] = opener_col if opened_here else 0
    return spans


def comment_lines(path, ext):
    """Yield (lineno, comment text) for a source file. Line comments and Python docstrings.

    String literals are blanked before the marker search, so a `#` inside `printf '# probe'`
    and the `//` in a URL are not read as comments.
    """
    mark = COMMENT_MARK[ext]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return
    blank = lambda x: " " * len(x.group(0))
    docs = docstring_spans(lines) if ext == ".py" else {}
    for i, line in enumerate(lines, 1):
        if i in docs:
            yield i, re.sub(r"`[^`]*`", blank, line[docs[i]:])
            continue
        masked = re.sub(r"'[^']*'|\"[^\"]*\"", blank, line)
        pos = masked.find(mark)
        if pos < 0:
            continue
        yield i, re.sub(r"`[^`]*`", blank, line[pos + len(mark):])


def phrase_errors(rel, lineno, text, exempt):
    out = []
    if EM_DASH in text:
        out.append((rel, lineno, "error", "em dash",
                    "use a comma, a full stop, or brackets"))
    if exempt:
        return out
    for name, rx in PHRASE_RE:
        m = rx.search(text)
        if m:
            out.append((rel, lineno, "error", m.group(0).strip(),
                        "banned phrase, see AGENTS.md \"How to write\""))
    m = FULL_STOP_RE.search(text)
    if m:
        out.append((rel, lineno, "error", "full stop",
                    "emphasis particle, delete it"))
    return out


def sentences(paragraph):
    for s in re.split(r"(?<=[.!?])\s+", paragraph.strip()):
        s = s.strip()
        if s:
            yield s


def looks_verbless(sentence):
    words = re.findall(r"[A-Za-z']+", sentence)
    if not words or len(words) > 8:
        return False
    for w in words:
        lw = w.lower()
        if lw in VERBS:
            return False
        if lw not in NOT_VERBISH and VERBISH_RE.match(lw):
            return False
    return True


def structural_warnings(rel, blocks):
    """blocks is a list of (start_lineno, paragraph text)."""
    out = []
    for lineno, para in blocks:
        body = re.sub(r"^\s*[-*+]\s+|^\s*\d+\.\s+|^#+\s+|^>\s*", "", para).strip()
        if not body:
            continue
        if ";" in body:
            out.append((rel, lineno, "warning", ";",
                        "semicolon in prose, use a full stop or a conjunction"))
        if body.count(":") > 1:
            out.append((rel, lineno, "warning", ":",
                        "more than one colon in a paragraph"))
        for s in sentences(body):
            plain = re.sub(r"\*\*|\*|_", "", s)
            n = len(re.findall(r"[A-Za-z0-9'`/.-]+", plain))
            if n > 25:
                out.append((rel, lineno, "warning", f"{n}-word sentence",
                            "a description runs to 25 words"))
            if NOT_CLOSER_RE.search(plain):
                out.append((rel, lineno, "warning", "\", not ...\" closer",
                            "write what is true, and correct the false reading separately"))
            if looks_verbless(plain):
                out.append((rel, lineno, "warning", plain[:40],
                            "verbless sentence"))
    return out


def paragraphs_from(items):
    """Group (lineno, text) into paragraph blocks, splitting on blank lines and list bullets."""
    blocks, cur, start = [], [], None
    def flush():
        if cur:
            blocks.append((start, " ".join(cur)))
    for lineno, text in items:
        stripped = text.strip()
        starts_item = bool(re.match(r"^([-*+]\s|\d+\.\s|#|\|)", stripped))
        if not stripped or starts_item:
            flush()
            cur, start = [], None
        if not stripped:
            continue
        if start is None:
            start = lineno
        cur.append(stripped)
    flush()
    return blocks


def check_markdown(path, rel, exempt, want_warnings):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    out, prose = [], []
    for lineno, text, is_row in strip_markdown_noise(lines):
        out.extend(phrase_errors(rel, lineno, text, exempt))
        if not is_row:
            prose.append((lineno, text))
    if want_warnings:
        out.extend(structural_warnings(rel, paragraphs_from(prose)))
    return out


def check_source(path, rel, exempt, want_warnings):
    ext = os.path.splitext(path)[1]
    items = list(comment_lines(path, ext))
    out = []
    for lineno, text in items:
        out.extend(phrase_errors(rel, lineno, text, exempt))
    if want_warnings:
        out.extend(structural_warnings(rel, paragraphs_from(items)))
    return out


def tracked_files(repo):
    """The set of files git tracks, as absolute paths.

    Walking the filesystem instead would scan `plans/`, `INFRASTRUCTURE_INVENTORY.md` and
    every build tree. Those are gitignored, they are local scratch or local secrets, and the
    rule governs what ships.
    """
    try:
        out = subprocess.check_output(["git", "-C", repo, "ls-files", "-z"], text=True)
    except Exception:
        return None
    return {os.path.join(repo, p) for p in out.split("\0") if p}


def walk(roots, tracked):
    # Absolute paths throughout: the exclusion patterns are anchored with a leading slash,
    # so a relative root would match none of them and scan the tree it is meant to skip.
    for root in (os.path.abspath(r) for r in roots):
        if os.path.isfile(root):
            yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            if any(p in dirpath + "/" for p in EXCLUDE):
                dirnames[:] = []
                continue
            for fn in sorted(filenames):
                ext = os.path.splitext(fn)[1]
                if ext != ".md" and ext not in COMMENT_MARK:
                    continue
                if fn.endswith(EXCLUDE_SUFFIX):
                    continue
                p = os.path.join(dirpath, fn)
                if tracked is not None and p not in tracked:
                    continue
                if not any(x in p for x in EXCLUDE):
                    yield p


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    stats = "--stats" in sys.argv
    want_warnings = "--errors-only" not in sys.argv
    try:
        repo = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True).strip()
    except Exception:
        repo = os.getcwd()
    roots = args or [repo]

    findings, scanned = [], 0
    for path in walk(roots, tracked_files(repo)):
        rel = os.path.relpath(path, repo)
        exempt = rel in RULE_DOCS
        scanned += 1
        if os.path.splitext(path)[1] == ".md":
            findings.extend(check_markdown(path, rel, exempt, want_warnings))
        else:
            findings.extend(check_source(path, rel, exempt, want_warnings))

    errors = [f for f in findings if f[2] == "error"]
    warnings = [f for f in findings if f[2] == "warning"]

    if stats:
        files = len({f[0] for f in errors})
        print(f"files scanned: {scanned}   errors: {len(errors)} in {files} file(s)   "
              f"warnings: {len(warnings)}")
        return 0

    for rel, lineno, level, what, why in sorted(findings):
        print(f"{rel}:{lineno}: {level}: {what}: {why}")
    if errors:
        print(f"\n{len(errors)} error(s), {len(warnings)} warning(s).")
        print("Errors are the phrase list and the em dash in AGENTS.md, \"How to write\".")
        return 1
    print(f"OK  {scanned} file(s) scanned, no errors, {len(warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
