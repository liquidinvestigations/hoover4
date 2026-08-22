#!/usr/bin/env python3
"""Check short tag references in markdown: every tag a document uses must be resolvable
without leaving the document.

A *tag* is the letter-and-number shorthand plan documents use for a scope item, a
decision, a question or a cut -- one or two capitals, one or two digits, optionally
dotted or letter-suffixed.

Two rules, and they are the whole tool:

1. **A tag never appears outside a plan folder.** `docs/`, `.agents/` and any Readme
   beside code are read by people who have no way to resolve one.
2. **Inside a plan folder, a tag must be resolvable in the file that cites it** -- either
   defined there (a table row, a heading, a bolded list item) or declared in that
   document's Key table.

A Key table is a section whose heading starts with `Key`, followed by a table whose first
cell carries the tag. See AGENTS.md.

Usage:
    .agents/check-doc-ids.py [path ...]     # default: whole repository
    .agents/check-doc-ids.py --stats        # report counts instead of failing

Exit status is 1 when any error is found, so it can gate a commit.
"""

import os
import re
import subprocess
import sys

# Vendored, generated, or third-party trees. Their markdown is not ours, and Rust generic
# parameters, SIMD mask names and state-machine labels all match the tag shape without
# being tags -- see NOT_TAGS_SOURCE for the ones that survive into our own files.
EXCLUDE = (
    "/.git/", "/node_modules/", "/website/target/", "/target/debug/", "/target/release/",
    "/.venv/", "/.container/cargo/", "/vendored/", "/tmp/stage/", "/__pycache__/",
    "/components/pdf-viewer/embed-pdf-viewer/", "/components/pdf-viewer/pdfjs/",
    "/bx/", "/site-packages/", "/plans/tmp/",
)

# Source files whose comments are checked too. A tag is no more resolvable in a Rust
# comment than in a public Readme, and `plans/` is gitignored, so a tag cited from
# shipped source is unresolvable for anyone who clones this repository.
COMMENT_MARK = {
    ".py": "#", ".sh": "#", ".toml": "#", ".yaml": "#", ".yml": "#",
    ".rs": "//", ".sql": "--",
}

# "Phase 1", "Stage F", "Part C" -- the same failure wearing prose. Checked only in plan
# documents and only across documents: a "Step 2:" marker inside one function indexes a
# structure the reader can see from where they stand, and is fine.
WORDED_NOUNS = ("Phase", "Chapter", "Workstream", "Milestone", "Tier", "Wave", "Track")
WORDED_RE = re.compile(r"\b(" + "|".join(WORDED_NOUNS) + r")\s+([A-Z]\b|\d{1,2}\b)")

# The shape a tag takes. Anything longer is a chipset, a checksum or a standard.
TAG_RE = re.compile(r"\b([A-Z]{1,2}\d{1,2}(?:\.\d)?[a-z]?)\b")

# Matches the tag shape but is domain vocabulary. Each one occurs in this tree.
NOT_TAGS = {
    "S3",                                   # the object store
    "P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7",   # pipeline stages
    "H1", "H2", "H3", "H4", "H5", "H6",     # heading levels
    "E5",                                   # the embedding model
    "FP4", "FP8",                           # numeric formats
    "MP3", "MP4", "AV1", "MD5",
    "P01",                                  # a Manticore error code
    "P4.5", "P4b",                          # discussed as stages that do not exist
    "BM25",                                 # the ranking function
    "CC0",                                  # the licence
    "MV3",                                  # Chrome manifest version
    "FP16",                                 # numeric format
    "GB10",                                 # the Spark's chip
    "RE2", "SHA3", "CRC32", "SSE2", "TC39", "MSP430", "ESP32",
}

# Tokens that are data or units in source but are genuine tags in a plan document, so
# they are excused only on the source side. `A4` is a paper size next to a dpi constant
# and a scope item in a plan; the surface decides which.
NOT_TAGS_SOURCE = {
    "A4", "A3", "A5",        # paper sizes
    "GB82", "LC55", "AL47",  # canonical IBAN samples
    "W09", "W35", "W53",     # ISO week dates
    "T1", "K0", "K1", "A0", "B0", "S0", "C0", "C11", "V8", "O2", "O3",
    "ES6", "VP9", "X11", "S7b", "C1.5", "P08",
}

KEY_HEADING_RE = re.compile(r"^#{1,4}\s+Key\b", re.I)

# `T1-T6`, `A1 - A7`, `Q1–Q7` in a Key row: one entry standing for a whole series.
RANGE_RE = re.compile(r"\b([A-Z]{1,2})(\d{1,2})\s*[–—-]\s*(?:[A-Z]{1,2})?(\d{1,2})\b")


def is_plan_doc(rel):
    return rel.startswith("plans/") or "/plans/" in rel


def strip_noise(lines):
    """Yield (lineno, text) with fenced blocks dropped and inline code blanked.

    A tag inside code is data or an API name -- an IBAN sample, an ISO week, a generic
    parameter -- never a citation.
    """
    fence = False
    code = False
    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            if not fence:
                # A fence that names a language holds code, and a tag inside it is a
                # variable or a sample. A bare fence holds a diagram or a transcript,
                # which a reader still has to resolve -- so it is scanned.
                code = bool(stripped[3:].strip())
            fence = not fence
            continue
        if fence and code:
            continue
        yield i, re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line)


def defines(line, tag):
    """Does this line define the tag rather than merely cite it?"""
    s = line.strip()
    if s.startswith("#"):
        # A heading defines its own SUBJECT, not every tag it happens to mention.
        # A heading like `### Q1 -- does chat chapter 3 (X3) come back?` defines the
        # question and merely cites the cut; counting the whole heading as a definition
        # is what let the cut through unnamed.
        subject = re.split(r"[-—–:(]", s.lstrip("# "), maxsplit=1)[0]
        return bool(re.search(r"\b" + re.escape(tag) + r"\b", subject))
    if s.startswith("|"):
        cells = s.split("|")
        if len(cells) > 1 and tag in cells[1]:
            return True
    if re.match(r"^[-*]\s", s) and re.search(
            r"\*\*[^*]*\b" + re.escape(tag) + r"\b[^*]*\*\*", s[:60]):
        return True
    if re.match(r"^\*\*[^*]{0,30}\b" + re.escape(tag) + r"\b", s):
        return True
    return False


def key_table_tags(lines):
    """Tags declared in the document's Key section."""
    declared, in_key = set(), False
    for raw in lines:
        s = raw.strip()
        if s.startswith("#"):
            in_key = bool(KEY_HEADING_RE.match(s))
            continue
        if in_key and s.startswith("|"):
            cells = s.split("|")
            if len(cells) > 1:
                declared.update(TAG_RE.findall(cells[1]))
                # A Key row usually declares a range -- `T1-T6`, `A1-A7`. Expand it, or
                # only the two endpoints count as declared and the middle reads as
                # undefined.
                for pre, lo, hi in RANGE_RE.findall(cells[1]):
                    for n in range(int(lo), int(hi) + 1):
                        declared.add(f"{pre}{n}")
    return declared


def check_source(path, rel):
    """Comments in shipped source may not cite a plan tag: `plans/` is gitignored, so
    the reference is unresolvable for anyone who clones the repository."""
    mark = COMMENT_MARK[os.path.splitext(path)[1]]
    errors = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return [], 0
    count = 0
    for i, line in enumerate(lines, 1):
        m = re.search(re.escape(mark), line)
        if not m:
            continue
        text = re.sub(r"`[^`]*`", lambda x: " " * len(x.group(0)), line[m.end():])
        for tag in TAG_RE.findall(text):
            if tag in NOT_TAGS or tag in NOT_TAGS_SOURCE:
                continue
            count += 1
            errors.append((rel, i, tag,
                           "plan tag in shipped source -- state the fact instead"))
    return errors, count


def check_file(path, rel):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return [], 0

    declared = key_table_tags(lines)
    seen, defined, errors, count = {}, set(), [], 0

    for lineno, text in strip_noise(lines):
        for tag in TAG_RE.findall(text):
            if tag in NOT_TAGS:
                continue
            count += 1
            seen.setdefault(tag, lineno)
            if defines(text, tag):
                defined.add(tag)

    if not seen:
        return [], 0

    if not is_plan_doc(rel):
        for tag, lineno in sorted(seen.items()):
            errors.append((rel, lineno, tag,
                           "tag outside a plan folder -- name it instead"))
        return errors, count

    for tag, lineno in sorted(seen.items()):
        if tag not in defined and tag not in declared:
            errors.append((rel, lineno, tag,
                           "cited but not defined here and not in the Key table"))

    # Worded references index the same invisible structure. A document may use them
    # freely once it says, somewhere in it, what they are.
    worded, worded_defined = {}, set()
    for lineno, text in strip_noise(lines):
        for noun, idx in WORDED_RE.findall(text):
            phrase = f"{noun} {idx}"
            worded.setdefault(phrase, lineno)
            s = text.strip()
            if s.startswith("#") or re.match(r"^\*\*", s) or s.startswith("|"):
                worded_defined.add(phrase)
    for phrase, lineno in sorted(worded.items()):
        if phrase not in worded_defined and phrase not in declared:
            errors.append((rel, lineno, phrase,
                           "worded reference with no heading, row or Key entry naming it"))

    return errors, count


def walk(roots):
    for root in roots:
        if os.path.isfile(root):
            yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            if any(p in dirpath + "/" for p in EXCLUDE):
                dirnames[:] = []
                continue
            for fn in filenames:
                ext = os.path.splitext(fn)[1]
                if ext == ".md" or ext in COMMENT_MARK:
                    p = os.path.join(dirpath, fn)
                    if not any(x in p for x in EXCLUDE):
                        yield p


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    stats = "--stats" in sys.argv
    try:
        repo = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True).strip()
    except Exception:
        repo = os.getcwd()
    roots = args or [repo]

    all_errors, total, files = [], 0, 0
    for path in walk(roots):
        rel = os.path.relpath(path, repo)
        if os.path.splitext(path)[1] != ".md":
            # A script inside a plan folder is scratch, not shipped: it may name tags as
            # freely as the documents beside it.
            if is_plan_doc(rel):
                continue
            errs, n = check_source(path, rel)
        else:
            errs, n = check_file(path, rel)
        if n:
            files += 1
        total += n
        all_errors.extend(errs)

    if stats:
        print(f"files with tags: {files}   tag occurrences: {total}   "
              f"unresolvable: {len(all_errors)}")
        return 0

    for rel, lineno, tag, why in all_errors:
        print(f"{rel}:{lineno}: {tag}: {why}")
    if all_errors:
        print(f"\n{len(all_errors)} unresolvable tag reference(s).")
        print("Give each one a Key table entry, or write the name instead of the tag.")
        return 1
    print(f"OK  {files} file(s) with tags, {total} occurrence(s), all resolvable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
