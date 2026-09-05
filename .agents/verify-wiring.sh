#!/usr/bin/env bash
# Prove the wiring works, in well under a minute. Prints one line per check.
#
# A check that cannot run prints SKIP, never PASS: silence must not be
# indistinguishable from success.
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pass=0; fail=0; skip=0
serena_up=0
ok()   { echo "PASS  $*"; pass=$((pass+1)); }
no()   { echo "FAIL  $*"; fail=$((fail+1)); }
sk()   { echo "SKIP  $*"; skip=$((skip+1)); }

# 1. The four MCP endpoints answer an MCP initialize, not merely a TCP connect.
for entry in "serena 21940" "web-search 21931" "browser 21932" "whois 21934"; do
    set -- $entry
    name="$1" port="$2"
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
        -X POST "http://127.0.0.1:$port/mcp" \
        -H 'Content-Type: application/json' \
        -H 'Accept: application/json, text/event-stream' \
        -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"verify","version":"1"}}}')
    case "$code" in
        200) ok "$name /mcp answers initialize"; [ "$name" != "serena" ] || serena_up=1 ;;
        404) no "$name /mcp is 404 -- the server is still on the SSE-only transport" ;;
        000) sk "$name is not listening on $port" ;;
        *)   no "$name /mcp returned HTTP $code" ;;
    esac
done

# 2. Serena resolves a real symbol in this repo (the only proof that counts).
if [ "$serena_up" = 0 ]; then
    sk "serena symbol probe needs the local service"
elif python3 "$HERE/serena-probe.py" --transport http --url http://127.0.0.1:21940/mcp \
        --symbol insert_text_pages 2>/dev/null | grep -q parse_common.py; then
    ok "serena resolves insert_text_pages to parse_common.py"
else
    no "serena did not resolve a known symbol -- read 'docker logs hoover4-serena', not the harness error"
fi

# 3. The skills are reachable under every path a harness looks in.
for p in .agents/skills .claude/skills; do
    # -L on both, because .claude/skills is a symlink and an unfollowed find reports it
    # as empty -- which reads as "the skills are missing" for a wiring that is correct.
    if [ -d "$REPO_ROOT/$p" ] && [ -n "$(find -L "$REPO_ROOT/$p" -name SKILL.md -print -quit)" ]; then
        n=$(find -L "$REPO_ROOT/$p" -name SKILL.md | wc -l)
        ok "$p has $n SKILL.md files"
    else
        no "$p has no SKILL.md"
    fi
done

skill_metadata=$(python3 - "$REPO_ROOT/.agents/skills" <<'PY'
from pathlib import Path
import sys

missing = []
for path in Path(sys.argv[1]).glob("*/SKILL.md"):
    text = path.read_text(encoding="utf-8")
    head = text.split("---", 2)[1] if text.startswith("---") and text.count("---") >= 2 else ""
    if "\nname:" not in "\n" + head or "\ndescription:" not in "\n" + head:
        missing.append(path.name)
print(len(missing))
PY
)
if [ "$skill_metadata" = 0 ]; then
    ok "Codex skill files each declare a name and description"
else
    no "$skill_metadata Codex skill files lack required metadata"
fi

# 4. Direct hook probes check script input and output. They do not check Codex dispatch or
#    project-hook trust. A fresh Codex session and `/hooks` check those states.
h="$REPO_ROOT/.agents/hooks"
if [ -f "$h/deny-unscoped-search.py" ]; then
    bad=$(python3 "$h/deny-unscoped-search.py" --test 'grep -rn "foo" .')
    good=$(python3 "$h/deny-unscoped-search.py" --test "grep -rn 'foo' --include='*.py' .")
    [[ "$bad" == DENY* && "$good" == allow ]] \
        && ok "search hook configuration denies the unscoped case and allows the scoped one" \
        || no "search hook configuration decisions are wrong: bad=$bad good=$good"
    b2=$(python3 "$h/deny-long-commit-message.py" --test "git commit -m \"$(printf 'x%.0s' {1..100})\"")
    g2=$(python3 "$h/deny-long-commit-message.py" --test 'git commit -m "fix chat"')
    [[ "$b2" == DENY* && "$g2" == allow ]] \
        && ok "commit hook configuration denies the long message and allows the short one" \
        || no "commit hook configuration decisions are wrong: bad=$b2 good=$g2"
    b3=$(python3 "$h/deny-claudisms.py" --test 'The guard is load-bearing here.')
    g3=$(python3 "$h/deny-claudisms.py" --test 'The guard stops a second row being written.')
    [[ "$b3" == DENY* && "$g3" == allow ]] \
        && ok "register hook configuration denies a banned phrase and allows plain prose" \
        || no "register hook configuration decisions are wrong: bad=$b3 good=$g3"
    b4=$(python3 "$h/warn-tool-call-budget.py" --test 77 96)
    [[ "$b4" == *"19 left"* ]] \
        && ok "budget hook configuration reports the remaining tool calls" \
        || no "budget hook configuration output is wrong: $b4"

    bash_payload=$(printf '%s' '{"tool_name":"Bash","tool_input":{"command":"grep -rn foo ."},"cwd":"'"$REPO_ROOT"'"}' \
        | python3 "$h/deny-unscoped-search.py")
    [[ "$bash_payload" == *'"permissionDecision": "deny"'* ]] \
        && ok "Codex-form Bash fixture produces a search-hook denial" \
        || no "Codex-form Bash fixture does not produce a search-hook denial"

    patch_bad=$(printf '%s' '{"tool_name":"apply_patch","tool_input":{"command":"*** Begin Patch\n*** Update File: docs/probe.md\n@@\n+This is load-bearing.\n*** End Patch"}}' \
        | python3 "$h/deny-claudisms.py")
    patch_good=$(printf '%s' '{"tool_name":"apply_patch","tool_input":{"command":"*** Begin Patch\n*** Update File: docs/probe.md\n@@\n+This prevents a duplicate row.\n*** End Patch"}}' \
        | python3 "$h/deny-claudisms.py")
    patch_exempt=$(printf '%s' '{"tool_name":"apply_patch","tool_input":{"command":"*** Begin Patch\n*** Update File: AGENTS.md\n@@\n+This is load-bearing.\n*** End Patch"}}' \
        | python3 "$h/deny-claudisms.py")
    [[ "$patch_bad" == *'"permissionDecision": "deny"'* \
       && -z "$patch_good" && -z "$patch_exempt" ]] \
        && ok "Codex-form apply_patch fixture checks additions and exemptions" \
        || no "Codex-form apply_patch fixture produces incorrect decisions"

    claude_edit=$(printf '%s' '{"tool_name":"Edit","tool_input":{"file_path":"docs/probe.md","old_string":"old","new_string":"This is load-bearing."}}' \
        | python3 "$h/deny-claudisms.py")
    [[ "$claude_edit" == *'"permissionDecision": "deny"'* ]] \
        && ok "Claude-form Edit fixture produces a register-hook denial" \
        || no "Claude-form Edit fixture does not produce a register-hook denial"

    session_payload=$(printf '%s' '{"source":"compact"}' | "$h/session-start-orientation.sh")
    [[ "$session_payload" == *'"hookEventName": "SessionStart"'* \
       && "$session_payload" == *'Context was just compacted.'* ]] \
        && ok "Codex-form SessionStart fixture returns compacted context" \
        || no "Codex-form SessionStart fixture output is incorrect"
else
    no "hook scripts are missing from .agents/hooks"
fi

# 5. Codex uses one tracked project config and separate user privacy settings.
if cmp -s "$REPO_ROOT/.agents/harnesses/codex.toml" "$REPO_ROOT/.codex/config.toml"; then
    ok "Codex project config matches its tracked template"
else
    no "Codex project config differs from .agents/harnesses/codex.toml"
fi

codex_config=$(python3 - "$REPO_ROOT/.codex/config.toml" <<'PY'
import sys
import tomllib

with open(sys.argv[1], "rb") as handle:
    data = tomllib.load(handle)
expected = {"serena", "hoover4-web-search", "hoover4-browser", "hoover4-whois"}
headers = data.get("mcp_servers", {}).get("hoover4-browser", {}).get("http_headers", {})
hooks = data.get("hooks", {})
session_hooks = hooks.get("SessionStart", [])
pre_hooks = hooks.get("PreToolUse", [])
commands = [
    handler.get("command", "")
    for event in session_hooks + pre_hooks
    for handler in event.get("hooks", [])
]
valid = (
    data.get("features", {}).get("hooks") is True
    and "experimental_use_rmcp_client" not in data.get("features", {})
    and data.get("agents", {}).get("max_concurrent_threads_per_session") == 1
    and set(data.get("mcp_servers", {})) == expected
    and headers.get("x-hoover4-chat-session") == "host-mcp-client"
    and headers.get("x-hoover4-user") == "host"
    and [event.get("matcher") for event in session_hooks]
        == ["^(startup|resume|clear|compact)$"]
    and {event.get("matcher") for event in pre_hooks} == {"^Bash$", "^(Edit|Write)$"}
    and any("session-start-orientation.sh" in command for command in commands)
    and any("deny-unscoped-search.py" in command for command in commands)
    and any("deny-long-commit-message.py" in command for command in commands)
    and any("deny-claudisms.py" in command for command in commands)
    and all("git rev-parse --show-toplevel" in command for command in commands)
)
print("ok" if valid else "fail")
PY
)
[ "$codex_config" = ok ] \
    && ok "Codex config declares hooks, four MCP servers, headers, and one-agent concurrency" \
    || no "Codex config has an incorrect project setting"

if command -v codex >/dev/null 2>&1; then
    codex_mcp=$(codex -C "$REPO_ROOT" mcp list 2>&1)
    codex_status=$?
    if [ "$codex_status" = 0 ] \
       && printf '%s' "$codex_mcp" | grep -q 'hoover4-browser' \
       && printf '%s' "$codex_mcp" | grep -q 'serena'; then
        ok "Codex loads the project config and lists its MCP servers"
    else
        no "Codex did not load the project MCP configuration"
    fi
else
    sk "Codex CLI is not installed"
fi

privacy_template=$(python3 - "$REPO_ROOT/.agents/harnesses/codex-user.toml" <<'PY'
import sys
import tomllib

with open(sys.argv[1], "rb") as handle:
    data = tomllib.load(handle)
valid = (
    data.get("analytics", {}).get("enabled") is False
    and data.get("feedback", {}).get("enabled") is False
    and data.get("history", {}).get("persistence") == "save-all"
    and data.get("otel", {}).get("exporter") == "none"
    and data.get("otel", {}).get("metrics_exporter") == "none"
    and data.get("otel", {}).get("trace_exporter") == "none"
    and data.get("otel", {}).get("log_user_prompt") is False
)
print("ok" if valid else "fail")
PY
)
[ "$privacy_template" = ok ] \
    && ok "Codex user template declares the required privacy settings" \
    || no "Codex user template has an incorrect privacy setting"

if python3 "$REPO_ROOT/.agents/update-codex-config.py" --check >/dev/null 2>&1; then
    ok "live Codex user privacy settings match the template"
else
    sk "live Codex user privacy settings need installation after review"
fi

codex_agents=$(python3 - "$REPO_ROOT/.codex/agents" <<'PY'
from pathlib import Path
import sys
import tomllib

expected = {"executor": "medium", "reviewer": "high"}
valid = True
for name, effort in expected.items():
    with (Path(sys.argv[1]) / f"{name}.toml").open("rb") as handle:
        data = tomllib.load(handle)
    valid = valid and data.get("name") == name
    valid = valid and data.get("model") == "gpt-5.6-sol"
    valid = valid and data.get("model_reasoning_effort") == effort
    valid = valid and bool(data.get("description")) and bool(data.get("developer_instructions"))
print("ok" if valid else "fail")
PY
)
[ "$codex_agents" = ok ] \
    && ok "Codex executor and reviewer pin their selected models" \
    || no "Codex executor or reviewer has an incorrect definition"

# 6. The Claude harness declares its hooks. A hook that exists and is not declared is a hook
#    that never runs, and the two states look identical from the filesystem.
if grep -q 'deny-unscoped-search' "$REPO_ROOT/.claude/settings.json" 2>/dev/null; then
    ok "settings.json declares the PreToolUse hooks"
else
    no "settings.json does not declare the hooks -- merge the block from .agents/harnesses/claude-settings.json"
fi
if "$REPO_ROOT/.agents/update-configs.sh" --check >/dev/null 2>&1; then
    ok "the live settings match the harness template"
else
    no "the live settings differ from .agents/harnesses/claude-settings.json -- run .agents/update-configs.sh"
fi
if grep -q 'warn-tool-call-budget' "$REPO_ROOT/.claude/settings.json" 2>/dev/null; then
    ok "settings.json declares the PostToolUse budget hook"
else
    no "settings.json does not declare the budget hook -- merge the block from .agents/harnesses/claude-settings.json"
fi

# 7. The Claude agent definitions are reachable, and each one pins a model. A definition with no
#     model field runs on whatever the organizer runs, which is the expensive default.
if [ -n "$(find -L "$REPO_ROOT/.claude/agents" -name '*.md' -print -quit 2>/dev/null)" ]; then
    n=$(find -L "$REPO_ROOT/.claude/agents" -name '*.md' | wc -l)
    unpinned=$(grep -L '^model:' "$REPO_ROOT"/.agents/agents/*.md 2>/dev/null | wc -l)
    [ "$unpinned" -eq 0 ] \
        && ok ".claude/agents resolves to $n definitions, each pinning a model" \
        || no "$unpinned agent definition(s) do not pin a model"
else
    no ".claude/agents has no definitions -- the symlink into .agents/agents is missing"
fi

# 8. The five path-scoped rules are present and each declares the paths it covers.
rules=$(find "$REPO_ROOT/.agents/rules" -name '*.md' 2>/dev/null | wc -l)
unpathed=$(grep -L '^paths:' "$REPO_ROOT"/.agents/rules/*.md 2>/dev/null | wc -l)
if [ "$rules" -gt 0 ] && [ "$unpathed" -eq 0 ]; then
    ok "$rules rules, each with a paths: glob"
else
    no "rules: $rules found, $unpathed without a paths: glob"
fi

# 9. The tag checker decides correctly on a known-bad and a known-good document. Its own
#    exit status is what a person relies on, so prove it rather than that the file exists.
tagdir=$(mktemp -d)
mkdir -p "$tagdir/plans/probe"
printf '# probe\n\nThe cut described in X3 is reopened here.\n' > "$tagdir/plans/probe/bad.md"
printf '# probe\n\n## Key\n\n| tag | what | where |\n|---|---|---|\n| X3 | the cut | elsewhere |\n\nThe cut described in X3 is reopened here.\n' > "$tagdir/plans/probe/good.md"
if ! "$REPO_ROOT/.agents/check-doc-ids.py" "$tagdir/plans/probe/bad.md" >/dev/null 2>&1 \
   && "$REPO_ROOT/.agents/check-doc-ids.py" "$tagdir/plans/probe/good.md" >/dev/null 2>&1; then
    ok "tag checker denies an undeclared tag and allows one with a Key entry"
    prose="$tagdir/probe.md"
    printf 'The guard is load-bearing here.\n' > "$prose"
    if ! "$REPO_ROOT/.agents/check-prose-style.py" "$prose" >/dev/null 2>&1; then
        printf 'The guard stops a second row being written.\n' > "$prose"
        "$REPO_ROOT/.agents/check-prose-style.py" "$prose" >/dev/null 2>&1 \
            && ok "prose checker denies a banned phrase and allows plain prose" \
            || no "prose checker rejects a clean sentence"
    else
        no "prose checker does not report a banned phrase"
    fi
else
    no "tag checker does not decide correctly on its own probe documents"
fi
rm -rf "$tagdir"

# 10. The hook's PHRASES and the checker's _PHRASES stay the same list. A term added to one
#    and not the other produces a hook that refuses text the checker accepts. Proved both
#    ways: the real files match, and a deliberately mismatched copy does not.
parity_check() {
    python3 - "$1" "$2" <<'PY'
import importlib.util, sys

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

hook = load(sys.argv[1], "hook_probe")
checker = load(sys.argv[2], "checker_probe")
sys.exit(0 if hook.PHRASES == checker._PHRASES else 1)
PY
}
if parity_check "$REPO_ROOT/.agents/hooks/deny-claudisms.py" "$REPO_ROOT/.agents/check-prose-style.py"; then
    ok "hook PHRASES and checker _PHRASES are the same list"
else
    no "hook PHRASES and checker _PHRASES differ"
fi

pdir=$(mktemp -d)
cp "$REPO_ROOT/.agents/hooks/deny-claudisms.py" "$pdir/hook_bad.py"
cp "$REPO_ROOT/.agents/check-prose-style.py" "$pdir/checker_bad.py"
printf '\nPHRASES.append(r"zzz_mismatch_probe_only")\n' >> "$pdir/hook_bad.py"
if parity_check "$pdir/hook_bad.py" "$pdir/checker_bad.py"; then
    no "parity check does not fail on a deliberately mismatched copy"
else
    ok "parity check fails on a deliberately mismatched copy"
fi
rm -rf "$pdir"

# 11. Identifier-safe matching. `_` is a word character, so `\b` finds no boundary between
#    a banned word and an underscore. The five `easy` spellings are pinned against the same
#    `\bword\b` construction the hook uses, rather than through the hook, so the pin holds
#    whether or not that word is on the list. `underscore` and `novel` are narrowed
#    patterns and are pinned through the real hook. `underscore` denies the past and
#    present participle only, so the plural noun and the third-person verb ("underscores
#    the point") are both legal, and only `underscored` and `underscoring` deny.
idtest=$(python3 - <<'PY'
import re
easy = re.compile(r"\beasy\b", re.I)
safe = ["easy_ocr", "easyocr_server", "EasyOCR", "EASY_OCR",
        "ai_services/easyocr_server/easyocr_server.py"]
print("ok" if all(not easy.search(s) for s in safe) and easy.search("the easy path")
      else "fail")
PY
)
u1=$(python3 "$REPO_ROOT/.agents/hooks/deny-claudisms.py" --test "the easy_ocr container")
u2=$(python3 "$REPO_ROOT/.agents/hooks/deny-claudisms.py" --test "this underscored the point")
u2b=$(python3 "$REPO_ROOT/.agents/hooks/deny-claudisms.py" --test "underscores the point")
u3=$(python3 "$REPO_ROOT/.agents/hooks/deny-claudisms.py" --test "an underscore in the name")
u4=$(python3 "$REPO_ROOT/.agents/hooks/deny-claudisms.py" --test "a novel approach to parsing")
u5=$(python3 "$REPO_ROOT/.agents/hooks/deny-claudisms.py" --test "read the novel.")
if [ "$idtest" = "ok" ] && [ "$u1" = "allow" ] && [[ "$u2" == DENY* ]] \
   && [ "$u2b" = "allow" ] && [ "$u3" = "allow" ] && [[ "$u4" == DENY* ]] && [ "$u5" = "allow" ]; then
    ok "identifier-safe matching: easy_ocr family, underscore participle-only, novel adjective-only"
else
    no "identifier-safe matching failed: easy=$idtest u1=$u1 u2=$u2 u2b=$u2b u3=$u3 u4=$u4 u5=$u5"
fi

echo "---- $pass passed, $fail failed, $skip skipped"
[ "$fail" -eq 0 ]
