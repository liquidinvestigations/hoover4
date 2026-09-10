#!/usr/bin/env python3
"""Split the concatenated screenshot ini and the procedure registry into per-slug files.

Re-run against the concatenated ini. If that file is gone, restore it from git
and pass the restored path as ``--ini``.

    python3 website/tools/split_browser_tests.py \\
        --ini website/screenshots.ini \\
        --runtime website/tools/manual_qa_runtime.py \\
        --out website/browser-tests
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path


BLOCK_BASES = (0, 100, 200, 300, 400, 500, 600, 700, 800)

PROCEDURE_FUNCTIONS = {
    "shipping": "manual-shipping",
    "mail_search": "manual-mail-search",
    "size_filters": "manual-size-filters",
    "type_filters": "manual-type-filters",
    "dates": "manual-dates",
    "email_tabs": "manual-email-filters",
    "entity_filter": "manual-entity-filter",
    "email_viewer": "manual-email-viewer",
    "sort_dates": "manual-sort-dates",
    "sort_sizes": "manual-sort-size",
    "sort_names": "manual-sort-name",
    "relevance": "manual-relevance",
    "tables": "manual-table",
    "pdf": "manual-pdf",
    "folder_search": "manual-folder-search",
    "archive_viewer": "manual-archive-viewer",
    "archive_storage": "manual-archive-storage",
    "entities": "manual-entities",
    "tree": "manual-tree",
}

HELPER_IMPORTS = (
    "ABSENT",
    "FIND",
    "UnmetPrerequisite",
    "email_envelope",
    "folder_route",
    "pdf_state",
    "query",
    "route",
    "sort_results",
    "viewer_state",
)

STDLIB_IMPORTS = ("json", "time", "asyncio")

HEADER_RE = re.compile(r"^\[([^\]]+)\]\s*$")
WORD_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")


def assign_block(name: str) -> int:
    """Return the hundred-block base for a section name, or raise."""
    if name == "home" or name.startswith("bad-url-"):
        return 0
    if name.startswith(("search-", "filter-", "sort-", "qa-sort-")):
        return 100
    if name.startswith("view-doc-table-") or name.startswith("qa-table-"):
        return 400
    if name.startswith("view-doc-"):
        return 200
    if name.startswith(("storage-", "qa-storage-")):
        return 300
    if name.startswith("ai-chat"):
        return 500
    if name.startswith("admin-"):
        return 600
    if name.startswith("manual-"):
        return 700
    if name.startswith("qa-pdf-"):
        return 800
    raise ValueError(f"no prefix block for {name!r}")


def number_sections(names: list[str]) -> list[tuple[str, int, str]]:
    """Map each original name to (block, slug), keeping original relative order inside a block."""
    buckets: dict[int, list[str]] = {base: [] for base in BLOCK_BASES}
    for name in names:
        buckets[assign_block(name)].append(name)
    numbered: list[tuple[str, int, str]] = []
    for base in BLOCK_BASES:
        for offset, name in enumerate(buckets[base], start=1):
            number = base + offset
            numbered.append((name, base, f"{number:03d}-{name}"))
    return numbered


def leading_comment_start(lines: list[str], header_at: int, floor: int) -> int:
    """Index of the comment or blank run that sits immediately before a section header."""
    index = header_at - 1
    while index >= floor and lines[index].strip() == "":
        index -= 1
    while index >= floor and (lines[index].lstrip().startswith(";") or lines[index].strip() == ""):
        index -= 1
    return index + 1


def iter_named_sections(text: str) -> list[tuple[str, str]]:
    """Split concatenated ini text into (name, raw block) pairs, excluding DEFAULT."""
    lines = text.splitlines(keepends=True)
    headers: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = HEADER_RE.match(line)
        if match:
            headers.append((index, match.group(1)))
    blocks: list[tuple[str, str]] = []
    for index, (header_at, name) in enumerate(headers):
        if name == "DEFAULT":
            continue
        floor = headers[index - 1][0] + 1 if index > 0 else 0
        start = leading_comment_start(lines, header_at, floor)
        if index + 1 < len(headers):
            next_at = headers[index + 1][0]
            end = leading_comment_start(lines, next_at, header_at + 1)
        else:
            end = len(lines)
        blocks.append((name, "".join(lines[start:end])))
    return blocks


def summarize(name: str) -> str:
    return f"Exercises the {name.replace('-', ' ')} case."


def inject_summary(block: str, summary: str) -> str:
    lines = block.splitlines(keepends=True)
    out: list[str] = []
    injected = False
    for line in lines:
        out.append(line)
        if not injected and HEADER_RE.match(line):
            out.append(f"summary = {summary}\n")
            injected = True
    if not injected:
        raise ValueError("section block has no header")
    return "".join(out)


def write_scenarios(ini_text: str, out_dir: Path) -> list[tuple[str, int, str]]:
    blocks = {name: block for name, block in iter_named_sections(ini_text)}
    names = [name for name, _ in iter_named_sections(ini_text)]
    if len(blocks) != len(names):
        raise SystemExit("duplicate section names in the concatenated ini")
    numbered = number_sections(names)
    out_dir.mkdir(parents=True, exist_ok=True)
    for child in out_dir.glob("*.ini"):
        child.unlink()
    for name, _base, slug in numbered:
        path = out_dir / f"{slug}.ini"
        path.write_text(inject_summary(blocks[name], summarize(name)), encoding="utf-8")
    return numbered


def used_names(source: str) -> set[str]:
    return set(WORD_RE.findall(source))


def procedure_module_text(proc_name: str, function_source: str) -> str:
    body = function_source
    match = re.match(r"async def \w+\(", body)
    if not match:
        raise ValueError(f"procedure {proc_name} is not an async function")
    body = "async def run(" + body[match.end() :]
    names = used_names(body)
    stdlib = [name for name in STDLIB_IMPORTS if name in names]
    helpers = [name for name in HELPER_IMPORTS if name in names]
    lines = [
        f'"""Manual procedure {proc_name}."""',
        "",
        "from __future__ import annotations",
        "",
    ]
    if stdlib:
        lines.append("import " + ", ".join(stdlib))
        lines.append("")
    if "Path" in names:
        lines.append("from pathlib import Path")
        lines.append("")
    if helpers:
        lines.append("from manual_qa_runtime import (")
        for name in helpers:
            lines.append(f"    {name},")
        lines.append(")")
        lines.append("")
    lines.append(f"PROCEDURE_NAME = {proc_name!r}")
    lines.append("")
    lines.append("")
    lines.append(body.rstrip())
    lines.append("")
    return "\n".join(lines)


def write_procedures(runtime_path: Path, out_dir: Path) -> list[str]:
    source = runtime_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name in PROCEDURE_FUNCTIONS:
            segment = ast.get_source_segment(source, node)
            if segment is None:
                raise SystemExit(f"cannot read source for {node.name}")
            functions[node.name] = segment
    missing = set(PROCEDURE_FUNCTIONS) - set(functions)
    if missing:
        raise SystemExit(f"runtime is missing procedure functions: {sorted(missing)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    for child in out_dir.glob("*.py"):
        child.unlink()
    written: list[str] = []
    for function_name, proc_name in PROCEDURE_FUNCTIONS.items():
        path = out_dir / f"{proc_name}.py"
        path.write_text(procedure_module_text(proc_name, functions[function_name]), encoding="utf-8")
        written.append(proc_name)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ini", type=Path, required=True)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--map", type=Path, help="write old-name, block, slug as TSV")
    args = parser.parse_args()
    ini_text = args.ini.read_text(encoding="utf-8")
    numbered = write_scenarios(ini_text, args.out)
    procedures: list[str] = []
    if args.runtime is not None:
        procedures = write_procedures(args.runtime, args.out / "procedures")
    if args.map is not None:
        rows = ["old_name\tblock\tslug"]
        rows.extend(f"{name}\t{base}\t{slug}" for name, base, slug in numbered)
        args.map.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"wrote {len(numbered)} scenario files to {args.out}")
    if procedures:
        print(f"wrote {len(procedures)} procedure files to {args.out / 'procedures'}")
    for name, base, slug in numbered:
        print(f"{name}\t{base}\t{slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
