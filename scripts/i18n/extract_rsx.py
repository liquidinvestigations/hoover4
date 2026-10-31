"""Move the `rsx!` text literals of the website frontend into the English catalogs.

Usage, from the repository root:

    python3 scripts/i18n/extract_rsx.py website/frontend [--dry-run] [files...]

For each text literal that `rust_literals.py` reports as `rsx`, the tool adds a message to
`i18n/en/<area>.ftl` and replaces the literal with `tr!("<key>", …)`. A Rust interpolation
`{expr}` becomes a Fluent variable, and the call passes the expression. Edge spaces become
`{" "}` placeables, so the English text stays the same. A literal with a line break, a
format width or a nested quote in an interpolation stays in the source for a manual change.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rust_literals import scan  # noqa: E402

AREAS = [
    ("admin", ("pages/admin/", "components/admin_components/")),
    ("chat", ("pages/ai_chat/", "components/chat_components/", "components/board_graph.rs")),
    ("search", ("components/search_components/", "pages/search_page.rs", "components/search_input.rs")),
    ("document", ("components/document_view_components/", "pages/view_document_page.rs", "components/pdf_viewer/", "pages/email_graph_page.rs")),
    ("storage", ("pages/file_browser_page.rs", "pages/uploads/")),
]

#: Variable names whose value the call passes as a number, so plural selectors work.
NUMERIC = re.compile(r"(^|_)(count|total|len|number|n|pages|page|done|remaining|files|rows|columns|size|bytes|limit|max|min|shown|selected_count|hits|matches)$")


def area(relative: str) -> str:
    for name, prefixes in AREAS:
        if relative.startswith(prefixes):
            return name
    return "main"


def module_prefix(relative: str) -> str:
    stem = relative.removesuffix(".rs").removesuffix("/mod")
    parts = [p for p in stem.split("/") if p not in ("pages", "components", "src")]
    words = []
    for part in parts[-2:]:
        part = part.replace("_components", "").replace("_page", "").replace("doc_preview_for_search", "preview")
        words.extend(w for w in part.split("_") if w)
    out = []
    for word in words:
        if not out or out[-1] != word:
            out.append(word)
    return "-".join(out[-3:]) or "app"


def slug(text: str) -> str:
    text = re.sub(r"\{[^}]*\}", " ", text)
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words[:5]) or "text"


def unescape(value: str) -> str | None:
    if "\\n" in value or "\\t" in value or "\\r" in value:
        return None
    # A backslash at a line end continues the literal without the next indentation. A
    # plain line break renders as one space in HTML text.
    value = re.sub(r"\\\n\s*", "", value)
    value = re.sub(r"\s*\n\s*", " ", value)
    value = re.sub(r"\\u\{([0-9a-fA-F]+)\}", lambda m: chr(int(m.group(1), 16)), value)
    return value.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")


def variable_name(expr: str) -> str:
    name = re.sub(r"[^A-Za-z0-9]+", "_", expr).strip("_").lower()
    name = re.sub(r"_(to_string|clone|as_str|unwrap|unwrap_or_default|read|get)$", "", name)
    name = re.sub(r"^(self_|item_|props_)", "", name)
    if not name or not name[0].isalpha():
        name = "value_" + name
    return name[:40]


def convert(value: str) -> tuple[str, list[tuple[str, str]]] | None:
    """The Fluent pattern of a Rust literal and the (name, Rust value) arguments."""
    value = unescape(value)
    if value is None:
        return None
    args: list[tuple[str, str]] = []
    names: dict[str, str] = {}
    pattern = ""
    i = 0
    while i < len(value):
        if value.startswith("{{", i):
            pattern += '{"{"}'
            i += 2
        elif value.startswith("}}", i):
            pattern += '{"}"}'
            i += 2
        elif value[i] == "{":
            j = value.find("}", i)
            if j < 0:
                return None
            inner = value[i + 1:j]
            if '"' in inner or "{" in inner:
                return None
            expr, _, spec = inner.partition(":")
            expr = expr.strip()
            if spec and spec not in ("?",):
                return None
            if spec == "?":
                rust = f'format!("{{:?}}", {expr})'
            else:
                rust = expr
            name = names.get(rust)
            if name is None:
                name = variable_name(expr)
                while name in names.values():
                    name += "_2"
                names[rust] = name
                simple = re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*(\(\))?", expr) is not None
                wrapped = expr if simple else f"({expr})"
                if spec == "?" or not NUMERIC.search(name):
                    rust_value = rust if spec == "?" else f"{wrapped}.to_string()"
                else:
                    rust_value = wrapped
                args.append((name, rust_value))
            pattern += f"{{ ${name} }}"
            i = j + 1
        elif value[i] == "}":
            return None
        else:
            pattern += value[i]
            i += 1
    stripped = pattern.strip(" ")
    if not stripped:
        return None
    lead = len(pattern) - len(pattern.lstrip(" "))
    trail = len(pattern) - len(pattern.rstrip(" "))
    pattern = ('{" "}' * min(lead, 1)) + stripped + ('{" "}' * min(trail, 1))
    if lead > 1 or trail > 1:
        return None
    # A pattern that starts with `[`, `*` or `.` would read as Fluent syntax.
    if pattern[0] in "[*.":
        pattern = '{"' + pattern[0] + '"}' + pattern[1:]
    return pattern, args


def code_position(source: str, literal):
    """Whether a literal outside `rsx!` is a plain value that `tr!` can replace.

    The literal and a following `.to_string()`, `.into()` or `.to_owned()` become one
    call. A literal in a macro argument list, such as `format!`, needs a manual change.
    """
    before = source[max(0, literal.start - 120):literal.start].rstrip()
    if re.search(r"[a-z_]!\s*[\(\[]\s*$", before) or re.search(r"[a-z_]!\s*\([^()]*,\s*$", before):
        return "macro argument", literal
    after = source[literal.end:literal.end + 20]
    m = re.match(r"\.(to_string|into|to_owned)\(\)", after)
    if m:
        literal.end += m.end()
    elif re.match(r"\s*(==|!=|\.)", after):
        return "comparison or method call", literal
    if re.search(r"(==|!=)\s*$", before):
        return "comparison", literal
    if re.search(r"String::from\(\s*$", before):
        return "String::from", literal
    return "", literal


CSS = re.compile(r"(^|;)\s*[a-z-]+\s*:\s*[^;]+;")


def not_text(source: str, literal) -> str:
    """Why a reported literal needs a manual decision, or an empty string."""
    text = literal.text
    if CSS.search(text):
        return "style"
    window = source[max(0, literal.start - 400):literal.start]
    if re.search(r"(:|=)\s*if\b[^;,]*$", window, re.S) and not literal.attribute:
        return "conditional value"
    plain = re.sub(r"\{[^}]*\}", "", text).strip()
    if " " not in plain and not re.match(r"^[A-Z]", plain) and not re.search(r"[.…:?!]$", plain):
        return "single lowercase word"
    return ""


def call(key: str, args: list[tuple[str, str]]) -> str:
    if not args:
        return f'tr!("{key}")'
    joined = ", ".join(f"{name}: {value}" for name, value in args)
    return f'tr!("{key}", {joined})'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("frontend", type=Path)
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--code", action="store_true", help="convert literals outside rsx! in plain value positions")
    parser.add_argument("--force", type=Path, help="a file of `relative/path.rs<TAB>literal` lines to convert after a manual check")
    args = parser.parse_args()
    src = args.frontend / "src"
    catalogs: dict[str, dict[str, str]] = {}
    existing: dict[str, str] = {}
    for path in (args.frontend / "i18n" / "en").glob("*.ftl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([a-z][a-z0-9-]*) = (.*)$", line)
            if m:
                existing[m.group(1)] = m.group(2)
    forced = set(args.force.read_text().splitlines()) if args.force else set()
    files = args.files or sorted(src.rglob("*.rs"))
    skipped = 0
    changed = 0
    for path in files:
        relative = str(path.relative_to(src))
        if relative in ("i18n.rs",) or relative.startswith("pages/browser_fixtures"):
            continue
        literals = [lit for lit in scan(path) if lit.kind == ("code" if args.code else "rsx")]
        if not literals:
            continue
        source = path.read_text(encoding="utf-8")
        prefix = module_prefix(relative)
        by_text: dict[str, str] = {}
        edits = []
        for literal in literals:
            if args.code:
                reason, literal = code_position(source, literal)
                if reason:
                    skipped += 1
                    print(f"manual ({reason}): {relative}:{literal.line}: {literal.text[:100]}")
                    continue
                converted = convert(literal.text) if "{" not in literal.text else None
                if converted is None:
                    skipped += 1
                    print(f"manual (braces): {relative}:{literal.line}: {literal.text[:100]}")
                    continue
                pattern, call_args = converted
                key = by_text.get(pattern) or f"{prefix}-{slug(literal.text)}"
                while key in existing and existing[key] != pattern:
                    key += "-2"
                existing[key] = pattern
                by_text[pattern] = key
                catalogs.setdefault(area(relative), {})[key] = pattern
                edits.append((literal.start, literal.end, call(key, call_args)))
                continue
            reason = "" if f"{relative}\t{literal.text[:100]}" in forced else not_text(source, literal)
            if reason:
                skipped += 1
                print(f"manual ({reason}): {relative}:{literal.line}: {literal.text[:100]}")
                continue
            converted = convert(literal.text)
            if converted is None:
                skipped += 1
                print(f"manual: {relative}:{literal.line}: {literal.text[:100]}")
                continue
            pattern, call_args = converted
            key = by_text.get(pattern)
            if key is None:
                base = f"{prefix}-{slug(literal.text)}"
                key = base
                number = 2
                while key in existing and existing[key] != pattern:
                    key = f"{base}-{number}"
                    number += 1
                existing[key] = pattern
                by_text[pattern] = key
                catalogs.setdefault(area(relative), {})[key] = pattern
            replacement = call(key, call_args)
            if not literal.attribute:
                replacement = "{" + replacement + "}"
            edits.append((literal.start, literal.end, replacement))
        for start, end, replacement in sorted(edits, reverse=True):
            source = source[:start] + replacement + source[end:]
        if edits:
            changed += 1
            if "use crate::tr;" not in source:
                source = add_import(source)
            if not args.dry_run:
                path.write_text(source, encoding="utf-8")
    for name, messages in catalogs.items():
        path = args.frontend / "i18n" / "en" / f"{name}.ftl"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        present = {line.split(" = ")[0] for line in text.splitlines() if " = " in line}
        addition = "".join(f"{key} = {pattern}\n" for key, pattern in messages.items() if key not in present)
        if not args.dry_run:
            path.write_text(text + addition, encoding="utf-8")
        print(f"{name}.ftl: {len(messages)} messages")
    print(f"{changed} files changed, {skipped} literals left for a manual change")
    return 0


def add_import(source: str) -> str:
    """Add `use crate::tr;` after the first block of `use` lines."""
    lines = source.split("\n")
    last_use = -1
    for index, line in enumerate(lines):
        if line.startswith("use ") or line.startswith("pub use "):
            last_use = index
            j = index
            while not lines[j].rstrip().endswith(";"):
                j += 1
            last_use = j
        elif last_use >= 0 and line.strip() and not line.startswith(("use ", "pub use ", "    ", "}")):
            break
    insert_at = last_use + 1 if last_use >= 0 else 0
    if last_use < 0:
        while insert_at < len(lines) and lines[insert_at].startswith("//"):
            insert_at += 1
    lines.insert(insert_at, "use crate::tr;")
    return "\n".join(lines)




def split_args(text: str) -> list[str]:
    """Split a macro argument list at its top-level commas."""
    parts, depth, current, i = [], 0, "", 0
    while i < len(text):
        c = text[i]
        if c == '"':
            j = i + 1
            while j < len(text) and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            current += text[i:j + 1]
            i = j + 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += c
        i += 1
    if current.strip():
        parts.append(current.strip())
    return parts


FORMAT_CALL = re.compile(r"\bformat!\(")


def convert_format_calls(source: str, prefix: str, existing: dict[str, str], catalog: dict[str, str]) -> tuple[str, list[str]]:
    """Replace `format!` calls whose template is interface text with `tr!` calls."""
    from rust_literals import looks_like_text, test_ranges
    skip = test_ranges(source)
    out, i, manual = [], 0, []
    while True:
        m = FORMAT_CALL.search(source, i)
        if not m:
            out.append(source[i:])
            break
        start = m.start()
        line = source[source.rfind("\n", 0, start) + 1:source.find("\n", start)]
        depth, j = 0, m.end() - 1
        while j < len(source):
            if source[j] == '"':
                k = j + 1
                while k < len(source) and source[k] != '"':
                    k += 2 if source[k] == "\\" else 1
                j = k + 1
                continue
            if source[j] == "(":
                depth += 1
            elif source[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        args = split_args(source[m.end():j])
        template = args[0] if args else ""
        in_test = any(a <= start <= b for a, b in skip)
        if (in_test or "i18n: data" in line or not template.startswith('"') or not looks_like_text(template[1:-1])
                or re.search(r"(info|warn|error|debug|trace)!", line)):
            out.append(source[i:m.end()])
            i = m.end()
            continue
        value = unescape(template[1:-1])
        if value is None:
            manual.append(template)
            out.append(source[i:m.end()])
            i = m.end()
            continue
        positional = iter(args[1:])
        named = {}
        for extra in args[1:]:
            if re.match(r"^[a-z_][a-z0-9_]*\s*=", extra):
                name, _, expr = extra.partition("=")
                named[name.strip()] = expr.strip()
        positional = iter([a for a in args[1:] if not re.match(r"^[a-z_][a-z0-9_]*\s*=", a)])
        pattern, call_args, names, k = "", [], {}, 0
        ok = True
        while k < len(value):
            if value.startswith("{{", k):
                pattern += '{"{"}'; k += 2; continue
            if value.startswith("}}", k):
                pattern += '{"}"}'; k += 2; continue
            if value[k] == "{":
                end = value.find("}", k)
                inner = value[k + 1:end]
                expr, _, spec = inner.partition(":")
                expr = expr.strip()
                if not expr:
                    try:
                        expr = next(positional)
                    except StopIteration:
                        ok = False
                        break
                elif expr in named:
                    expr = named[expr]
                rust = f'format!("{{:{spec}}}", {expr})' if spec else expr
                if rust not in names:
                    name = variable_name(expr)
                    while name in names.values():
                        name += "_2"
                    names[rust] = name
                    simple = re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*(\(\))?", expr) is not None
                    wrapped = expr if simple else f"({expr})"
                    call_args.append((name, rust if spec else f"{wrapped}.to_string()"))
                pattern += f"{{ ${names[rust]} }}"
                k = end + 1
                continue
            pattern += value[k]
            k += 1
        if not ok or "\n" in pattern:
            manual.append(template)
            out.append(source[i:m.end()])
            i = m.end()
            continue
        stripped = pattern.strip(" ")
        lead = len(pattern) - len(pattern.lstrip(" "))
        trail = len(pattern) - len(pattern.rstrip(" "))
        pattern = ('{" "}' if lead else "") + stripped + ('{" "}' if trail else "")
        key = f"{prefix}-{slug(value)}"
        while key in existing and existing[key] != pattern:
            key += "-2"
        existing[key] = pattern
        catalog[key] = pattern
        out.append(source[i:start] + call(key, call_args))
        i = j + 1
    return "".join(out), manual


def format_main() -> int:
    parser = argparse.ArgumentParser(description="Replace interface text in format! calls with tr! calls.")
    parser.add_argument("frontend", type=Path)
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    src = args.frontend / "src"
    existing: dict[str, str] = {}
    for path in (args.frontend / "i18n" / "en").glob("*.ftl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([a-z][a-z0-9-]*) = (.*)$", line)
            if m:
                existing[m.group(1)] = m.group(2)
    catalogs: dict[str, dict[str, str]] = {}
    for path in args.files:
        relative = str(path.relative_to(src))
        source = path.read_text(encoding="utf-8")
        new, manual = convert_format_calls(source, module_prefix(relative), existing, catalogs.setdefault(area(relative), {}))
        for template in manual:
            print(f"manual: {relative}: {template[:100]}")
        if new != source:
            if "use crate::tr;" not in new:
                new = add_import(new)
            path.write_text(new, encoding="utf-8")
            print(f"changed: {relative}")
    for name, messages in catalogs.items():
        if not messages:
            continue
        path = args.frontend / "i18n" / "en" / f"{name}.ftl"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        present = {line.split(" = ")[0] for line in text.splitlines() if " = " in line}
        path.write_text(text + "".join(f"{k} = {v}\n" for k, v in messages.items() if k not in present), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(format_main() if "--format" in sys.argv and sys.argv.remove("--format") is None else main())
