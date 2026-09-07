#!/usr/bin/env python3
"""Merge tracked Cursor user settings into the live user configuration files.

Host-specific auto-run text is copied from the live Claude user settings, never from
a tracked file. The tracked template has only the four MCP servers, git, and local
container work.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
import tempfile


ROOT = Path(__file__).resolve().parent.parent
PERMISSIONS_TEMPLATE = ROOT / ".agents" / "harnesses" / "cursor-user-permissions.json"
SETTINGS_TEMPLATE = ROOT / ".agents" / "harnesses" / "cursor-user-settings.json"
CLI_ALLOW = [
    "Shell(git)",
    "Shell(docker)",
    "Mcp(serena:*)",
    "Mcp(hoover4-web-search:*)",
    "Mcp(hoover4-browser:*)",
    "Mcp(hoover4-whois:*)",
]
SKIP_AUTOMODE = {"$defaults"}
JSONC_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', re.DOTALL)
JSONC_COMMA = re.compile(r'("(?:\\.|[^"\\])*")|,(?=\s*[}\]])')


def without_comments(text):
    """Replace JSONC comments with spaces while preserving strings and offsets."""
    return JSONC_TOKEN.sub(
        lambda match: match[0] if match[0].startswith('"') else re.sub(r"[^\n]", " ", match[0]),
        text,
    )


def parse_json_object(text, label):
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        stripped = JSONC_COMMA.sub(lambda match: match[1] or "", without_comments(text))
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise SystemExit(f"invalid JSON in {label}: {error}") from error
    if not isinstance(data, dict):
        raise SystemExit(f"{label} is not a JSON object")
    return data


def load_json(path, label, default=None):
    if not path.is_file():
        return {} if default is None else copy.deepcopy(default)
    return parse_json_object(path.read_text(encoding="utf-8"), label)


def dump_json(data):
    return json.dumps(data, indent=4) + "\n"


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


def claude_autorun_lines(claude_settings):
    auto = claude_settings.get("autoMode") or {}
    lines = []
    for key in ("environment", "allow"):
        values = auto.get(key) or []
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, str) and item not in SKIP_AUTOMODE:
                lines.append(item)
    return lines


def merge_permissions(current, template, extra_allow):
    merged = copy.deepcopy(current)
    merged["mcpAllowlist"] = list(template["mcpAllowlist"])
    auto = copy.deepcopy(merged.get("autoRun") or {})
    if not isinstance(auto, dict):
        auto = {}
    existing = auto.get("allow_instructions") or []
    if not isinstance(existing, list):
        existing = []
    wanted = []
    seen = set()
    for item in list(template.get("autoRun", {}).get("allow_instructions") or []) + extra_allow:
        if not isinstance(item, str) or item in seen:
            continue
        seen.add(item)
        wanted.append(item)
    for item in existing:
        if isinstance(item, str) and item not in seen:
            wanted.append(item)
            seen.add(item)
    auto["allow_instructions"] = wanted
    merged["autoRun"] = auto
    return merged


def merge_settings(current, template):
    merged = copy.deepcopy(current)
    merged.update(template)
    return merged


def merge_cli(current):
    merged = copy.deepcopy(current) if current else {}
    merged["version"] = int(merged.get("version") or 1)
    editor = merged.get("editor")
    if not isinstance(editor, dict):
        editor = {}
    editor.setdefault("vimMode", False)
    merged["editor"] = editor
    permissions = merged.get("permissions")
    if not isinstance(permissions, dict):
        permissions = {}
    allow = permissions.get("allow")
    if not isinstance(allow, list):
        allow = []
    seen = {item for item in allow if isinstance(item, str)}
    for item in CLI_ALLOW:
        if item not in seen:
            allow.append(item)
            seen.add(item)
    deny = permissions.get("deny")
    if not isinstance(deny, list):
        deny = []
    permissions["allow"] = allow
    permissions["deny"] = deny
    merged["permissions"] = permissions
    merged["approvalMode"] = "auto-review"
    attribution = merged.get("attribution")
    if not isinstance(attribution, dict):
        attribution = {}
    attribution["attributeCommitsToAgent"] = False
    attribution["attributePRsToAgent"] = False
    merged["attribution"] = attribution
    return merged


ARGV_FLAG = re.compile(r'("enable-crash-reporter"\s*:\s*)(?:true|false)')


def argv_text(path):
    if not path.is_file():
        return '{\n\t"enable-crash-reporter": false\n}\n'
    text = path.read_text(encoding="utf-8")
    parse_json_object(text, path)
    stripped = without_comments(text)
    match = ARGV_FLAG.search(stripped)
    if match:
        start = match.start() + len(match[1])
        return text[:start] + "false" + text[match.end():]
    end = stripped.rfind("}")
    previous = len(stripped[:end].rstrip())
    comma = "" if stripped[previous - 1] in "{," else ","
    return (
        text[:previous] + comma + text[previous:end]
        + '\n\t"enable-crash-reporter": false\n' + text[end:]
    )


def argv_is_off(path):
    if not path.is_file():
        return False
    return load_json(path, path).get("enable-crash-reporter") is False


def permissions_match(current, wanted):
    return (
        current.get("mcpAllowlist") == wanted.get("mcpAllowlist")
        and (current.get("autoRun") or {}).get("allow_instructions")
        == (wanted.get("autoRun") or {}).get("allow_instructions")
    )


def cli_match(current, wanted):
    allow = current.get("permissions", {}).get("allow") or []
    if not isinstance(allow, list):
        return False
    have = {item for item in allow if isinstance(item, str)}
    attribution = current.get("attribution") or {}
    return (
        current.get("approvalMode") == wanted.get("approvalMode")
        and attribution.get("attributeCommitsToAgent") is False
        and attribution.get("attributePRsToAgent") is False
        and all(item in have for item in CLI_ALLOW)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--permissions",
        type=Path,
        default=Path.home() / ".cursor" / "permissions.json",
    )
    parser.add_argument(
        "--settings",
        type=Path,
        default=Path.home() / ".config" / "Cursor" / "User" / "settings.json",
    )
    parser.add_argument(
        "--cli-config",
        type=Path,
        default=Path.home() / ".cursor" / "cli-config.json",
    )
    parser.add_argument(
        "--argv",
        type=Path,
        default=Path.home() / ".cursor" / "argv.json",
    )
    parser.add_argument(
        "--claude-settings",
        type=Path,
        default=Path.home() / ".claude" / "settings.json",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write the merged settings")
    mode.add_argument("--check", action="store_true", help="exit 1 when settings differ")
    args = parser.parse_args()

    template = load_json(PERMISSIONS_TEMPLATE, PERMISSIONS_TEMPLATE)
    settings_template = load_json(SETTINGS_TEMPLATE, SETTINGS_TEMPLATE)
    try:
        claude = load_json(args.claude_settings, args.claude_settings, default={})
        extra = claude_autorun_lines(claude)
    except SystemExit:
        extra = []

    permissions_current = load_json(args.permissions, args.permissions, default={})
    settings_current = load_json(args.settings, args.settings, default={})
    cli_current = load_json(args.cli_config, args.cli_config, default={})
    argv_wanted_text = argv_text(args.argv)

    permissions_wanted = merge_permissions(permissions_current, template, extra)
    settings_wanted = merge_settings(settings_current, settings_template)
    cli_wanted = merge_cli(cli_current)

    matching = (
        permissions_match(permissions_current, permissions_wanted)
        and settings_current.get("telemetry.telemetryLevel") == "off"
        and cli_match(cli_current, cli_wanted)
        and argv_is_off(args.argv)
    )
    if matching:
        print("Cursor user settings match the template")
        return 0
    if args.apply:
        install(args.permissions, dump_json(permissions_wanted))
        install(args.settings, dump_json(settings_wanted))
        install(args.cli_config, dump_json(cli_wanted))
        install(args.argv, argv_wanted_text)
        print("installed Cursor user settings")
        return 0
    print("Cursor user settings need an update")
    return 1 if args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
