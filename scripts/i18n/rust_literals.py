"""List the interface text literals of Rust files that are not in a catalog.

Usage, from the repository root:

    python3 scripts/i18n/rust_literals.py website/frontend/src [--check] [--json]

The tool reads each `.rs` file, skips comments, tests and `#[cfg(test)]` modules, and
reports string literals in two places:

* `rsx` text: a string literal that is a child node inside `rsx! { … }`, or the value of
  an attribute that a person reads (`title`, `placeholder`, `alt`, `aria-label`, `label`
  and the other names in `TEXT_ATTRIBUTES`).
* `code` text: a literal outside `rsx!` that looks like a sentence or a label, such as an
  argument of `.to_string()` that starts with a capital letter and has a space.
* `format` text: the template of a `format!` call that has a space and a word.

A literal stays in the source when it is not interface text. Mark its line, or the line
above it, with the comment `// i18n: data` and give the reason, for example a protocol
value. CSS values, booleans and identifiers are skipped without a mark.
`--check` exits with status 1 when a reported literal remains.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

#: Attribute and property names whose value a person reads.
TEXT_ATTRIBUTES = {
    "title", "placeholder", "alt", "aria-label", "\"aria-label\"", "label", "summary", "text",
    "message", "heading", "description", "tooltip", "hint", "caption", "empty_text", "button_label",
    "confirm_label", "cancel_label", "aria_label", "\"aria-description\"", "\"data-tooltip\"",
}

#: Marks a line whose literal is not interface text.
DATA_MARK = "i18n: data"


@dataclass
class Literal:
    path: str
    line: int
    kind: str
    text: str
    start: int = 0
    end: int = 0
    attribute: str = ""


def tokens(source: str):
    """Yield (kind, text, offset) for strings, comments and other characters."""
    i, n = 0, len(source)
    while i < n:
        c = source[i]
        if source.startswith("//", i):
            j = source.find("\n", i)
            j = n if j < 0 else j
            yield "comment", source[i:j], i
            i = j
        elif source.startswith("/*", i):
            j = source.find("*/", i + 2)
            j = n if j < 0 else j + 2
            yield "comment", source[i:j], i
            i = j
        elif c == "r" and re.match(r'r#*"', source[i:i + 10]) and (i == 0 or not (source[i - 1].isalnum() or source[i - 1] == "_")):
            hashes = re.match(r'r(#*)"', source[i:]).group(1)
            end = source.find('"' + hashes, i + len(hashes) + 2)
            end = n if end < 0 else end + 1 + len(hashes)
            yield "string", source[i:end], i
            i = end
        elif c == '"' or (c == "b" and source.startswith('b"', i)):
            j = i + (2 if c == "b" else 1)
            while j < n and source[j] != '"':
                j += 2 if source[j] == "\\" else 1
            yield "string", source[i:j + 1], i
            i = j + 1
        elif c == "'" and re.match(r"'(\\.|[^\\'])'", source[i:i + 12]):
            m = re.match(r"'(\\.|[^\\'])'", source[i:])
            yield "char", m.group(0), i
            i += len(m.group(0))
        else:
            yield "other", c, i
            i += 1


def string_value(literal: str) -> str:
    if literal.startswith("r"):
        return literal.lstrip("r#")[1:].rstrip("#")[:-1]
    if literal.startswith("b"):
        literal = literal[1:]
    return literal[1:-1]


#: CSS declarations, colours, booleans and identifiers, which are never interface text.
NOT_TEXT = re.compile(
    r"^\s*(true|false|none|transparent|pointer|not-allowed|inherit|auto)\s*$"
    r"|^\s*(rgba?|var|hsl)\(.*\)\s*$"
    r"|^\s*#[0-9a-fA-F]{3,8}\s*$"
    r"|[a-z-]+\s*:\s*[^;]+;"
    r"|^[a-z0-9]+([_-][a-z0-9]+)+$"
)


def looks_like_text(value: str) -> bool:
    if NOT_TEXT.search(value):
        return False
    words = re.findall(r"[A-Za-z]{2,}", re.sub(r"\{[^}]*\}", " ", value))
    return bool(words)


def looks_like_sentence(value: str) -> bool:
    plain = re.sub(r"\{[^}]*\}", "x", value).strip()
    return bool(re.match(r"^[A-Z][a-z]+[ ,'][A-Za-z]", plain)) or bool(re.match(r"^[A-Z][a-z]+$", plain) and len(plain) > 3)


def test_ranges(source: str) -> list[tuple[int, int]]:
    """The offsets of `#[cfg(test)]` items and `#[test]` functions."""
    ranges = []
    for match in re.finditer(r"#\[cfg\(test\)\]|#\[test\]", source):
        brace = source.find("{", match.end())
        if brace < 0:
            continue
        depth, j = 0, brace
        for kind, text, offset in tokens(source[brace:]):
            if kind != "other":
                continue
            if text == "{":
                depth += 1
            elif text == "}":
                depth -= 1
                if depth == 0:
                    j = brace + offset
                    break
        ranges.append((match.start(), j))
    return ranges


def scan(path: Path) -> list[Literal]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    skip = test_ranges(source)
    found: list[Literal] = []
    stream = list(tokens(source))
    rsx_depth: list[int] = []
    depth = 0
    previous_code = ""
    for index, (kind, text, offset) in enumerate(stream):
        if any(start <= offset <= end for start, end in skip):
            continue
        if kind == "other":
            if text == "{":
                depth += 1
                if previous_code.endswith("rsx!"):
                    rsx_depth.append(depth)
            elif text == "}":
                if rsx_depth and rsx_depth[-1] == depth:
                    rsx_depth.pop()
                depth -= 1
            if not text.isspace():
                previous_code = (previous_code + text)[-40:]
            continue
        if kind != "string":
            continue
        value = string_value(text)
        line_no = source.count("\n", 0, offset) + 1
        line = lines[line_no - 1] if line_no - 1 < len(lines) else ""
        previous_line = lines[line_no - 2] if line_no >= 2 else ""
        if DATA_MARK in line or DATA_MARK in previous_line or not looks_like_text(value):
            previous_code = (previous_code + '""')[-40:]
            continue
        after = next((t for k, t, _ in stream[index + 1:index + 40] if k == "other" and not t.isspace()), "")
        if after == ":" and not source.startswith("::", stream[index + 1][2] if index + 1 < len(stream) else 0):
            # A quoted attribute name, such as "data-chat-turn": value.
            previous_code = (previous_code + '""')[-40:]
            continue
        following = "".join(t for _, t, _ in stream[index + 1:index + 6])
        if following.lstrip().startswith("=>") or following.lstrip().startswith("|") or previous_code.rstrip().endswith("["):
            previous_code = (previous_code + '""')[-40:]
            continue
        before = previous_code.rstrip()
        if re.search(r"format!\($", before.replace(" ", "")) and " " in value.strip() and not re.search(r"(info|warn|error|debug|trace)!", line):
            found.append(Literal(str(path), line_no, "format", value, offset, offset + len(text)))
            previous_code = (previous_code + '""')[-40:]
            continue
        attribute = re.search(r"([A-Za-z_][A-Za-z0-9_]*|\"[a-z-]+\")\s*:\s*$", before)
        if rsx_depth:
            if attribute:
                if attribute.group(1) in TEXT_ATTRIBUTES:
                    found.append(Literal(str(path), line_no, "rsx", value, offset, offset + len(text), attribute.group(1)))
            elif re.search(r"[{},]\s*$|^\s*$", before) or before.endswith(")"):
                if not re.search(r"(format|write|tr|println|info|warn|error|debug)!\($", before):
                    found.append(Literal(str(path), line_no, "rsx", value, offset, offset + len(text)))
        elif looks_like_sentence(value) and not re.search(r"(info|warn|error|debug|trace|log|println|eprintln|panic|expect|unreachable|assert[a-z_]*)!?\($", before.replace(" ", "")):
            if not before.endswith(".expect(") and "tracing::" not in line:
                found.append(Literal(str(path), line_no, "code", value, offset, offset + len(text)))
        previous_code = (previous_code + '""')[-40:]
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    found: list[Literal] = []
    for root in args.paths:
        files = [root] if root.is_file() else sorted(root.rglob("*.rs"))
        for path in files:
            found.extend(scan(path))
    if args.json:
        print(json.dumps([{k: v for k, v in literal.__dict__.items() if k not in ("start", "end")} for literal in found], ensure_ascii=False, indent=1))
    else:
        for literal in found:
            print(f"{literal.path}:{literal.line}: {literal.kind}: {literal.text}")
        print(f"{len(found)} literals", file=sys.stderr)
    return 1 if args.check and found else 0


if __name__ == "__main__":
    raise SystemExit(main())
