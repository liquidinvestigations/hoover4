#!/usr/bin/env python3
"""Check prose register: the banned phrases and punctuation from AGENTS.md, "How to write".

The repository writes in Simplified Technical English (ASD-STE100) and meets ISO 24495-1.
Two levels are reported:

  error    a banned phrase, or an em dash, in a comment, a docstring or markdown
  warning  a structural shape the rule discourages: a `, not <clause>.` closer, a verbless
           sentence of eight words or fewer, a sentence over 25 words, a semicolon in a
           markdown paragraph, a second colon in a paragraph
  copy     a banned phrase, or an em dash, inside a string literal, which is text the
           product shows a person

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
    .agents/check-prose-style.py [path ...]      # default: whole repository
    .agents/check-prose-style.py --stats         # report counts instead of failing
    .agents/check-prose-style.py --errors-only   # hide the heuristic warnings
    .agents/check-prose-style.py --no-strings    # comments and markdown only
    .agents/check-prose-style.py --copy-only     # only the string-literal findings

Only an error sets the exit status. A copy finding is reported and does not gate, because
rewriting what the product says is a change a person has to read in place.

Exit status is 1 when any error is found, so it can gate a commit.
"""

import os
import re
import subprocess
import sys
import tokenize

# Vendored, generated, or third-party trees, plus the two migration directories. The runner
# `plans/` is gitignored scratch that gets wiped. The migration directories are scanned like
# any other source: editing an applied migration is a breaking change the owner decides on,
# and when it happens the register applies to those files too.
EXCLUDE = (
    "/.git/", "/node_modules/", "/website/target/", "/target/debug/", "/target/release/",
    "/.venv/", "/.container/cargo/", "/vendored/", "/tmp/stage/", "/__pycache__/",
    "/site-packages/", "/bx/",
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


# ---------------------------------------------------------------- string literals
#
# Comments say how the code works. String literals say what the product says, and until
# this mode existed the product's own copy was never measured. The two are reported apart,
# because a banned phrase in a comment is a defect now and a banned phrase in copy is a
# rewrite that has to be read in place.

# A string a test compares against is exempt until the test moves with it, and separating an
# expected value from an ordinary literal needs the assertion, which is more than a scanner
# can see. Whole paths are exempted instead. This hides real copy that only appears in a
# fixture, which is the trade the AGENTS.md carve-out asks for.
TEST_PATH_MARKS = ("/tests/", "/test/", "/testdata/", "/fixtures/", "/conformance/")
TEST_FILE_RE = re.compile(
    r"(^test_.*\.py$|_test\.(py|rs)$|\.(test|spec)\.(ts|tsx|js)$|^conftest\.py$)")

# A pattern is code. Its character classes and escapes are not prose, and an em dash inside
# one selects a character.
REGEX_CALL_RE = re.compile(
    r"(?:re\.(?:compile|sub|subn|match|search|findall|finditer|split|fullmatch)|"
    r"Regex(?:Set|Builder)?::new|regex::Regex::new|new\s+RegExp)\s*\(\s*$")
REGEX_NAME_RE = re.compile(r"^\s*(?:pub\s+|static\s+|const\s+|let\s+)*"
                           r"[A-Za-z_][A-Za-z0-9_]*(?:_RE|_REGEX|_PATTERN|_PAT)\b"
                           r"\s*(?::[^=]*)?=\s*$", re.I)
REGEX_META_RE = re.compile(r"\\[dwsbAZ]|\[\^|\(\?|\\\\b")

STRING_EXTS = (".py", ".rs", ".ts", ".tsx", ".js")


def is_test_path(rel):
    p = "/" + rel.replace("\\", "/")
    return any(m in p for m in TEST_PATH_MARKS) or bool(TEST_FILE_RE.search(
        os.path.basename(rel)))


def is_pattern(context, literal, ext):
    """Is this literal a regular expression rather than prose?

    `context` is the source text just before the literal, the previous line included, so a
    call split across lines is still recognised.
    """
    tail = context.rstrip()
    if REGEX_CALL_RE.search(tail) or REGEX_NAME_RE.search(tail):
        return True
    if ext == ".py" and literal.startswith(("r", "R", "rb", "br", "Rb", "bR")) \
            and REGEX_META_RE.search(literal):
        return True
    return False


def python_strings(path, lines):
    """(lineno, text, context, raw) for each Python string literal outside a docstring."""
    docs = docstring_spans(lines)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            toks = list(tokenize.generate_tokens(fh.readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, OSError):
        return
    wanted = {tokenize.STRING}
    for name in ("FSTRING_MIDDLE",):
        if hasattr(tokenize, name):
            wanted.add(getattr(tokenize, name))
    for tok in toks:
        if tok.type not in wanted:
            continue
        row, col = tok.start
        if row in docs:
            continue
        prev = lines[row - 2] if row >= 2 else ""
        context = prev + "\n" + tok.line[:col]
        yield row, tok.string, context, tok.string


def braced_strings(text, ext):
    """(lineno, body, context, raw) for each string literal in Rust, TypeScript or JS.

    A hand scanner rather than a regular expression, because it has to keep `//` in a URL
    inside a literal and a Rust lifetime `'a` outside one.
    """
    i, n, line = 0, len(text), 1
    single_is_string = ext in (".ts", ".tsx", ".js")
    line_start = 0
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            line_start = i
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j < 0:
                return
            line += text.count("\n", i, j)
            i = j + 2
            continue
        if ext == ".rs" and (text.startswith('r"', i) or text.startswith("r#", i)):
            k = i + 1
            hashes = 0
            while k < n and text[k] == "#":
                hashes += 1
                k += 1
            if k < n and text[k] == '"':
                close = '"' + "#" * hashes
                j = text.find(close, k + 1)
                if j < 0:
                    return
                body = text[k + 1:j]
                yield line, body, prev_context(text, line_start, i), "r" + body
                line += body.count("\n")
                i = j + len(close)
                continue
        if c == '"' or (single_is_string and c == "'") or (
                ext in (".ts", ".tsx", ".js") and c == "`"):
            quote = c
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote:
                    break
                j += 1
            body = text[i + 1:j]
            yield line, body, prev_context(text, line_start, i), body
            line += body.count("\n")
            i = j + 1
            continue
        i += 1


def prev_context(text, line_start, pos):
    """The current line up to `pos`, with the line before it, for the pattern test."""
    before = text.rfind("\n", 0, max(line_start - 1, 0))
    return text[before + 1:pos] if before >= 0 else text[:pos]


# `echo` and `printf` print, and so does every local helper a script wraps them in. Without
# the helpers a message a person reads is invisible to this scan.
SHELL_ECHO_RE = re.compile(
    r"(?:^|[;&|]|\bthen\b|\bdo\b|\{)\s*(?:echo|printf|fail|die|warn|note|abort|usage)\s+")


def shell_strings(lines):
    """(lineno, body, context, raw) for the quoted text a script prints."""
    for i, line in enumerate(lines, 1):
        if not SHELL_ECHO_RE.search(line):
            continue
        for m in re.finditer(r"'([^']*)'|\"([^\"]*)\"", line):
            body = m.group(1) if m.group(1) is not None else m.group(2)
            if body.strip():
                yield i, body, line[:m.start()], body


def copy_findings(path, rel, ext, lines):
    """Banned phrases and em dashes inside string literals, as `copy` findings."""
    if rel in RULE_DOCS or is_test_path(rel):
        return []
    if ext in STRING_EXTS:
        source = "\n".join(lines)
        items = (python_strings(path, lines) if ext == ".py"
                 else braced_strings(source, ext))
    elif ext in (".sh", ".bash"):
        items = shell_strings(lines)
    else:
        return []
    out = []
    for lineno, body, context, raw in items:
        if not body or EM_DASH not in body and not any(
                rx.search(body) for _n, rx in PHRASE_RE) and not FULL_STOP_RE.search(body):
            continue
        if is_pattern(context, raw, ext):
            continue
        for rel_, ln, _level, what, why in phrase_errors(rel, lineno, body, False):
            out.append((rel_, ln, "copy", what, why + ", in a string the product shows"))
    return out


def check_source(path, rel, exempt, want_warnings, want_copy=True):
    ext = os.path.splitext(path)[1]
    items = list(comment_lines(path, ext))
    out = []
    for lineno, text in items:
        out.extend(phrase_errors(rel, lineno, text, exempt))
    if want_warnings:
        out.extend(structural_warnings(rel, paragraphs_from(items)))
    if want_copy:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.read().split("\n")
        except OSError:
            return out
        out.extend(copy_findings(path, rel, ext, lines))
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
    want_copy = "--no-strings" not in sys.argv
    copy_only = "--copy-only" in sys.argv
    if copy_only:
        want_copy, want_warnings = True, False
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
            findings.extend(check_source(path, rel, exempt, want_warnings, want_copy))

    errors = [f for f in findings if f[2] == "error"]
    warnings = [f for f in findings if f[2] == "warning"]
    # One line holding two literals with an em dash in each reports twice, because an
    # f-string arrives as several tokens. The work list wants one row per place a person
    # has to look, so identical copy rows collapse. Errors and warnings are left alone.
    copy = sorted({f for f in findings if f[2] == "copy"})
    findings = sorted(errors + warnings + copy)
    if copy_only:
        findings = copy

    if stats:
        files = len({f[0] for f in errors})
        cfiles = len({f[0] for f in copy})
        print(f"files scanned: {scanned}   errors: {len(errors)} in {files} file(s)   "
              f"warnings: {len(warnings)}   copy: {len(copy)} in {cfiles} file(s)")
        return 0

    for rel, lineno, level, what, why in findings:
        print(f"{rel}:{lineno}: {level}: {what}: {why}")
    if errors:
        print(f"\n{len(errors)} error(s), {len(warnings)} warning(s), "
              f"{len(copy)} copy finding(s).")
        print("Errors are the phrase list and the em dash in AGENTS.md, \"How to write\".")
        return 1
    print(f"OK  {scanned} file(s) scanned, no errors, {len(warnings)} warning(s), "
          f"{len(copy)} copy finding(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
