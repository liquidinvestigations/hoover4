#!/usr/bin/env python3
"""Install the tracked Kimi Code user settings into the live user configuration.

Merges .agents/harnesses/kimi-user.toml into $KIMI_CODE_HOME/config.toml (default
~/.kimi-code/config.toml), upserts disable_feedback_survey in tui.toml, and copies
the project .kimi-code/mcp.json over the user-level mcp.json. Provider and model
tables, and any permission rule or hook the template does not own, stay untouched.
"""

import argparse
import copy
import json
import os
from pathlib import Path
import re
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / ".agents" / "harnesses" / "kimi-user.toml"
PROJECT_MCP = ROOT / ".kimi-code" / "mcp.json"
BEGIN = "# BEGIN hoover4 harness"
END = "# END hoover4 harness"
SCALARS = ("telemetry", "default_permission_mode")
OWNED_REASON = "hoover4 harness"
TUI_KEY = "disable_feedback_survey"


def parse_toml(text, label):
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise SystemExit(f"invalid TOML in {label}: {error}") from error


def kimi_home():
    return Path(os.environ.get("KIMI_CODE_HOME") or Path.home() / ".kimi-code")


def template_parts():
    lines = TEMPLATE.read_text(encoding="utf-8").splitlines(keepends=True)
    begin = end = None
    for index, line in enumerate(lines):
        if line.startswith(BEGIN):
            begin = index
        if line.startswith(END):
            end = index
            break
    if begin is None or end is None:
        raise SystemExit(f"{TEMPLATE} has no {BEGIN} .. {END} block")
    scalars = [
        line for line in lines[:begin]
        if re.match(r"^[a-z_]+\s*=", line)
    ]
    if [s.split("=", 1)[0].strip() for s in scalars] != list(SCALARS):
        raise SystemExit(f"{TEMPLATE} scalars must be exactly: {', '.join(SCALARS)}")
    return scalars, lines[begin:end + 1]


def first_table_line(lines):
    for index, line in enumerate(lines):
        if re.match(r"^\s*\[", line):
            return index
    return len(lines)


def upsert_scalar(lines, key, value_line):
    assignment = re.compile(rf"^{re.escape(key)}\s*=")
    top = first_table_line(lines)
    matches = [index for index in range(top) if assignment.match(lines[index])]
    if len(matches) > 1:
        raise SystemExit(f"live config assigns {key} more than once")
    if matches:
        lines[matches[0]] = value_line
        return
    model = re.compile(r"^default_model\s*=")
    anchor = next((index for index in range(top) if model.match(lines[index])), None)
    if anchor is None:
        raise SystemExit("live config has no default_model line to anchor the scalars")
    lines.insert(anchor + 1, value_line)


def replace_block(lines, block):
    begin = end = None
    for index, line in enumerate(lines):
        if line.startswith(BEGIN):
            begin = index
        if line.startswith(END):
            end = index
            break
    if begin is not None and end is not None and end > begin:
        lines[begin:end + 1] = block
        return
    if begin is not None or end is not None:
        raise SystemExit("live config has one harness marker but not the other")
    if lines and lines[-1].strip():
        lines.append("\n")
    lines.extend(block)


def merge_config(source):
    scalars, block = template_parts()
    lines = source.splitlines(keepends=True)
    if source and not source.endswith("\n"):
        lines[-1] += "\n"
    for scalar in scalars:
        upsert_scalar(lines, scalar.split("=", 1)[0].strip(), scalar)
    replace_block(lines, block)
    merged = "".join(lines)
    parse_toml(merged, "merged config")

    before = unrelated_data(parse_toml(source, "live config") if source.strip() else {})
    after = unrelated_data(parse_toml(merged, "merged config"))
    if before != after:
        raise SystemExit("merge changed an unrelated setting")
    return merged


def unrelated_data(data):
    result = copy.deepcopy(data)
    for key in SCALARS:
        result.pop(key, None)
    background = result.get("background")
    if isinstance(background, dict):
        background.pop("max_running_tasks", None)
        if not background:
            result.pop("background")
    permission = result.get("permission")
    if isinstance(permission, dict):
        rules = permission.get("rules")
        if isinstance(rules, list):
            permission["rules"] = [
                rule for rule in rules
                if not isinstance(rule, dict) or rule.get("reason") != OWNED_REASON
            ]
            if not permission["rules"]:
                permission.pop("rules")
        if not permission:
            result.pop("permission")
    hooks = result.get("hooks")
    if isinstance(hooks, list):
        result["hooks"] = [
            hook for hook in hooks
            if not isinstance(hook, dict) or ".agents/hooks" not in hook.get("command", "")
        ]
        if not result["hooks"]:
            result.pop("hooks")
    return result


def merge_tui(source):
    lines = source.splitlines(keepends=True) if source else []
    if lines and not source.endswith("\n"):
        lines[-1] += "\n"
    assignment = re.compile(rf"^{TUI_KEY}\s*=")
    top = first_table_line(lines)
    matches = [index for index in range(top) if assignment.match(lines[index])]
    if len(matches) > 1:
        raise SystemExit(f"tui.toml assigns {TUI_KEY} more than once")
    replacement = f"{TUI_KEY} = true\n"
    if matches:
        lines[matches[0]] = replacement
    else:
        lines.insert(top, replacement)
    merged = "".join(lines)
    parse_toml(merged, "merged tui.toml")
    return merged


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


def backup(path):
    if path.exists():
        install(Path(str(path) + ".bak"), path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home",
        type=Path,
        default=kimi_home(),
        help="Kimi Code data directory (default: $KIMI_CODE_HOME or ~/.kimi-code)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write the merged settings")
    mode.add_argument("--check", action="store_true", help="exit 1 when settings differ")
    args = parser.parse_args()

    mcp_template = json.loads(PROJECT_MCP.read_text(encoding="utf-8"))
    mcp_template.pop("_comment", None)
    config_path = args.home / "config.toml"
    tui_path = args.home / "tui.toml"
    mcp_path = args.home / "mcp.json"

    current_config = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    merged_config = merge_config(current_config)
    current_tui = tui_path.read_text(encoding="utf-8") if tui_path.exists() else ""
    merged_tui = merge_tui(current_tui)
    current_mcp = mcp_path.read_text(encoding="utf-8") if mcp_path.exists() else None
    wanted_mcp = json.dumps(mcp_template, indent=2) + "\n"
    current_mcp_data = json.loads(current_mcp) if current_mcp else {}
    current_mcp_data.pop("_comment", None)
    mcp_drift = current_mcp_data != mcp_template

    drift = (
        merged_config != current_config
        or merged_tui != current_tui
        or mcp_drift
    )
    if not drift:
        print("Kimi Code user settings match the templates")
        return 0
    if not args.apply:
        print("Kimi Code user settings need an update")
        print(f"  config: {'drift' if merged_config != current_config else 'match'}")
        print(f"  tui:    {'drift' if merged_tui != current_tui else 'match'}")
        print(f"  mcp:    {'drift' if mcp_drift else 'match'}")
        return 1 if args.check else 0

    if merged_config != current_config:
        backup(config_path)
        install(config_path, merged_config)
        print(f"installed harness settings in {config_path}")
    if merged_tui != current_tui:
        backup(tui_path)
        install(tui_path, merged_tui)
        print(f"installed {TUI_KEY} in {tui_path}")
    if mcp_drift:
        backup(mcp_path)
        install(mcp_path, wanted_mcp)
        print(f"installed MCP servers in {mcp_path}")
    print("restart the session, because hooks and permission rules load at session start")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
