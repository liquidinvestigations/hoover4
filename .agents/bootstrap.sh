#!/usr/bin/env bash
# Wire this checkout's shared agent instructions into every harness on this machine.
#
# One source of truth: .agents/. The pieces git carries (the two .claude symlinks and the
# skills, rules and hooks themselves) are already in the checkout. What this script creates
# is the per-harness adapters, which are machine-local and generated rather than tracked.
#
#   ./.agents/bootstrap.sh            report what is wired and what is missing, change nothing
#   ./.agents/bootstrap.sh --apply    create the links and adapter files
#
# Idempotent: re-running changes nothing and prints what it found. Symlinks are used wherever
# a harness follows them, because a copy drifts. Where a harness needs a different file format
# the adapter is generated and carries a banner saying so.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && git rev-parse --show-toplevel)"
HARNESSES="$REPO_ROOT/.agents/harnesses"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

note() { printf '  %s\n' "$*"; }
act()  { if [ "$APPLY" = 1 ]; then "$@"; else note "WOULD: $*"; fi }

# link <target-relative-to-the-link> <link-path-relative-to-repo>
link() {
    local target="$1" linkpath="$2"
    local abs="$REPO_ROOT/$linkpath"
    if [ -L "$abs" ]; then
        local current; current="$(readlink "$abs")"
        if [ "$current" = "$target" ]; then note "ok      $linkpath -> $target"; return; fi
        note "RELINK  $linkpath -> $current (want $target)"
        act rm -f "$abs"
    elif [ -e "$abs" ]; then
        note "CONFLICT $linkpath exists and is not a symlink -- left alone, resolve by hand"
        return
    else
        note "MISSING $linkpath"
    fi
    act mkdir -p "$(dirname "$abs")"
    act ln -s "$target" "$abs"
}

echo "repo: $REPO_ROOT"

echo "[1] shared source of truth"
for d in .agents/skills .agents/rules .agents/hooks; do
    if [ -d "$REPO_ROOT/$d" ]; then note "ok      $d"; else note "MISSING $d"; fi
done
# Restoring a checkout on a filesystem that loses the mode bit is the one moment this is
# commonly lost, and a hook that is not executable fails silently as "no hook configured".
for h in "$REPO_ROOT"/.agents/hooks/*; do
    [ -e "$h" ] || continue
    [ -x "$h" ] || { note "not executable: ${h#$REPO_ROOT/}"; act chmod +x "$h"; }
done

echo "[2] Claude Code"
link "../.agents/skills" ".claude/skills"
link "../.agents/rules"  ".claude/rules"
if grep -q 'deny-unscoped-search' "$REPO_ROOT/.claude/settings.json" 2>/dev/null; then
    note "ok      .claude/settings.json declares the hooks"
else
    note "MISSING hooks in .claude/settings.json -- merge the hooks block from"
    note "        .agents/harnesses/claude-settings.json by hand and restart the session."
    note "        Run .agents/update-configs.sh to install it, then restart the session."
fi

echo "[3] opencode"
# opencode reads .agents/skills/<name>/SKILL.md natively -- nothing to link. Only the MCP
# block needs installing.
if [ -f "$REPO_ROOT/opencode.json" ]; then note "ok      opencode.json present"
else note "MISSING opencode.json -- copy .agents/harnesses/opencode.json to the repo root"; fi

echo "[4] Codex"
if [ -f "$REPO_ROOT/.codex/config.toml" ] \
   && cmp -s "$REPO_ROOT/.agents/harnesses/codex.toml" "$REPO_ROOT/.codex/config.toml"; then
    note "ok      .codex/config.toml matches its tracked template"
else
    note "MISSING or changed .codex/config.toml -- copy .agents/harnesses/codex.toml"
fi
if [ -f "$REPO_ROOT/.codex/agents/executor.toml" ] \
   && [ -f "$REPO_ROOT/.codex/agents/reviewer.toml" ]; then
    note "ok      .codex/agents has the executor and reviewer"
else
    note "MISSING executor or reviewer in .codex/agents"
fi
if python3 "$REPO_ROOT/.agents/update-codex-config.py" --check >/dev/null 2>&1; then
    note "ok      Codex user privacy settings match the tracked template"
else
    note "REVIEW  Codex user privacy settings need an update"
    note "        Run python3 .agents/update-codex-config.py, then add --apply after review."
fi
note "Codex reads AGENTS.md and .agents/skills directly from this checkout"
note "Codex has no loader for the path-scoped Markdown files in .agents/rules"
note "REVIEW  Start a fresh Codex session after a project hook changes"
note "        Run /hooks and inspect each changed project hook."
note "        Trust each exact definition before you test the hooks."

echo "[5] Gemini CLI"
if [ -f "$REPO_ROOT/.gemini/settings.json" ]; then note "ok      .gemini/settings.json present"
else note "MISSING .gemini/settings.json -- start from .agents/harnesses/gemini-settings.json"; fi
# Gemini's context file is GEMINI.md unless the installed build supports naming others.
link "AGENTS.md" "GEMINI.md"

echo "[6] Cursor"
copy_cursor_json() {
    local template="$1" live="$2" strip_comment="$3"
    if [ "$strip_comment" = 1 ]; then
        python3 - "$template" "$live" "$APPLY" <<'PY'
import json, sys
from pathlib import Path
template, live, apply_flag = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] == "1"
wanted = json.loads(template.read_text(encoding="utf-8"))
wanted.pop("_comment", None)
text = json.dumps(wanted, indent=2) + "\n"
current = live.read_text(encoding="utf-8") if live.is_file() else ""
rel = ".cursor/" + live.name
if current == text:
    print(f"  ok      {rel}")
    raise SystemExit(0)
if apply_flag:
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_text(text, encoding="utf-8")
    print(f"  wrote   {rel}")
else:
    print(f"  WOULD copy {rel}")
PY
        return
    fi
    if [ -f "$live" ] && cmp -s "$template" "$live"; then
        note "ok      ${live#$REPO_ROOT/}"
    elif [ "$APPLY" = 1 ]; then
        mkdir -p "$(dirname "$live")"
        cp "$template" "$live"
        note "wrote   ${live#$REPO_ROOT/}"
    else
        note "MISSING or changed ${live#$REPO_ROOT/} -- copy $template"
    fi
}
copy_cursor_json "$HARNESSES/cursor-mcp.json" "$REPO_ROOT/.cursor/mcp.json" 1
copy_cursor_json "$HARNESSES/cursor-hooks.json" "$REPO_ROOT/.cursor/hooks.json" 0
copy_cursor_json "$HARNESSES/cursor-permissions.json" "$REPO_ROOT/.cursor/permissions.json" 0
copy_cursor_json "$HARNESSES/cursor-cli.json" "$REPO_ROOT/.cursor/cli.json" 0
if [ -x "$REPO_ROOT/.agents/hooks/cursor-wrap.py" ]; then
    note "ok      .agents/hooks/cursor-wrap.py is executable"
else
    note "not executable: .agents/hooks/cursor-wrap.py"
    act chmod +x "$REPO_ROOT/.agents/hooks/cursor-wrap.py"
fi
# Cursor rules are .mdc with their own frontmatter; generate, never duplicate.
if [ -d "$REPO_ROOT/.agents/rules" ]; then
    for rule in "$REPO_ROOT"/.agents/rules/*.md; do
        [ -e "$rule" ] || continue
        base="$(basename "$rule" .md)"
        out="$REPO_ROOT/.cursor/rules/$base.mdc"
        if [ "$APPLY" = 1 ]; then
            mkdir -p "$(dirname "$out")"
            {
                echo "---"
                # Carry the shared rule's own paths: line through as Cursor's globs:.
                awk '/^paths:/{print "globs: " substr($0, index($0,$2))} /^description:/{print}' "$rule"
                echo "alwaysApply: false"
                echo "---"
                echo "<!-- generated by .agents/bootstrap.sh from .agents/rules/$base.md; edit that file -->"
                sed '1{/^---$/!q}; 1,/^---$/d' "$rule"
            } > "$out"
            note "wrote   .cursor/rules/$base.mdc"
        else
            note "WOULD generate .cursor/rules/$base.mdc"
        fi
    done
fi
if [ "$APPLY" = 1 ]; then
    python3 "$HARNESSES/render_cursor_agents.py" --apply
else
    if python3 "$HARNESSES/render_cursor_agents.py" --check >/dev/null 2>&1; then
        note "ok      .cursor/agents matches the shared definitions"
    else
        note "MISSING or changed .cursor/agents -- run with --apply"
    fi
fi
if python3 "$REPO_ROOT/.agents/update-cursor-config.py" --check >/dev/null 2>&1; then
    note "ok      Cursor user privacy and MCP allow settings match the tracked template"
else
    note "REVIEW  Cursor user settings need an update"
    note "        Run python3 .agents/update-cursor-config.py, then add --apply after review."
fi
note "Cursor reads AGENTS.md and .agents/skills directly from this checkout"

echo "[7] Kimi Code"
# Kimi reads AGENTS.md, .agents/skills and ~/.agents/skills without an adapter, so
# only the user-level settings and MCP servers need installing.
if python3 "$REPO_ROOT/.agents/update-kimi-config.py" --check >/dev/null 2>&1; then
    note "ok      Kimi user settings and MCP connections match the tracked templates"
else
    note "REVIEW  Kimi user settings need an update"
    note "        Run python3 .agents/update-kimi-config.py, then add --apply after review."
fi
note "Kimi reads AGENTS.md and .agents/skills directly from this checkout"
note "Start a fresh Kimi session after a settings change, because hooks and permission rules load at session start"

echo "[8] harnesses needing a manual check on this machine"
note "Google Antigravity: config location and MCP shape not established -- check its own docs"

echo
if [ "$APPLY" = 1 ]; then
    echo "applied. now run .agents/verify-wiring.sh"
else
    echo "dry run. re-run with --apply to make these changes."
fi
