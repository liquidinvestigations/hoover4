#!/usr/bin/env python3
"""Merge the tracked Codex privacy settings into one user configuration file."""

import argparse
import copy
import os
from pathlib import Path
import re
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / ".agents" / "harnesses" / "codex-user.toml"
CONTROLLED = {
    "analytics": ("enabled",),
    "feedback": ("enabled",),
    "history": ("persistence",),
    "otel": ("exporter", "metrics_exporter", "trace_exporter", "log_user_prompt"),
}
HEADER = re.compile(r"^\s*\[([^\[\]]+)\]\s*(?:#.*)?$")
ANY_HEADER = re.compile(r"^\s*(?:\[[^\[\]]+\]|\[\[.+\]\])\s*(?:#.*)?$")


def parse_toml(text, label):
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise SystemExit(f"invalid TOML in {label}: {error}") from error


def toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    raise SystemExit(f"unsupported value in {TEMPLATE}: {value!r}")


def table_range(lines, table):
    start = None
    for index, line in enumerate(lines):
        match = HEADER.match(line.rstrip("\n"))
        if match and match.group(1).strip() == table:
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if ANY_HEADER.match(lines[index].rstrip("\n")):
            end = index
            break
    return start, end


def merge_text(source, wanted):
    lines = source.splitlines(keepends=True)
    if source and not source.endswith("\n"):
        lines[-1] += "\n"
    source_data = parse_toml(source, "target config") if source.strip() else {}

    for table, keys in CONTROLLED.items():
        span = table_range(lines, table)
        if span is None and table in source_data:
            raise SystemExit(
                f"cannot merge [{table}]: use a standard [{table}] table in the target config"
            )
        if span is None:
            if lines and lines[-1].strip():
                lines.append("\n")
            lines.append(f"[{table}]\n")
            lines.extend(f"{key} = {toml_value(wanted[table][key])}\n" for key in keys)
            continue

        start, end = span
        missing = []
        for key in keys:
            assignment = re.compile(rf"^\s*{re.escape(key)}\s*=")
            matches = [index for index in range(start + 1, end) if assignment.match(lines[index])]
            if len(matches) > 1:
                raise SystemExit(f"cannot merge [{table}].{key}: duplicate assignments")
            replacement = f"{key} = {toml_value(wanted[table][key])}\n"
            if matches:
                lines[matches[0]] = replacement
            else:
                missing.append(replacement)
        if missing:
            lines[end:end] = missing

    merged = "".join(lines)
    merged_data = parse_toml(merged, "merged config")
    before = unrelated_data(source_data)
    after = unrelated_data(merged_data)
    if before != after:
        raise SystemExit("merge changed an unrelated setting")
    return merged


def unrelated_data(data):
    result = copy.deepcopy(data)
    for table, keys in CONTROLLED.items():
        section = result.get(table)
        if not isinstance(section, dict):
            continue
        for key in keys:
            section.pop(key, None)
        if not section:
            result.pop(table, None)
    return result


def install(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home() / ".codex" / "config.toml",
        help="target config path",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write the merged settings")
    mode.add_argument("--check", action="store_true", help="exit 1 when settings differ")
    args = parser.parse_args()

    wanted = parse_toml(TEMPLATE.read_text(encoding="utf-8"), TEMPLATE)
    current = args.config.read_text(encoding="utf-8") if args.config.exists() else ""
    merged = merge_text(current, wanted)
    if merged == current:
        print("Codex user settings match the template")
        return 0
    if args.apply:
        install(args.config, merged)
        print(f"installed Codex user settings in {args.config}")
        return 0
    print(f"Codex user settings need an update in {args.config}")
    return 1 if args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
