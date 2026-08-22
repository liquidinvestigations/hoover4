#!/usr/bin/env bash
# Prove the wiring works, in well under a minute. Prints one line per check.
#
# A check that cannot run prints SKIP, never PASS: silence must not be
# indistinguishable from success.
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pass=0; fail=0; skip=0
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
        200) ok "$name /mcp answers initialize" ;;
        404) no "$name /mcp is 404 -- the server is still on the SSE-only transport" ;;
        000) no "$name is not listening on $port" ;;
        *)   no "$name /mcp returned HTTP $code" ;;
    esac
done

# 2. Serena resolves a real symbol in this repo (the only proof that counts).
if python3 "$HERE/serena-probe.py" --transport http --url http://127.0.0.1:21940/mcp \
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

# 4. The hooks decide correctly on a known-bad and a known-good command line.
h="$REPO_ROOT/.agents/hooks"
if [ -f "$h/deny-unscoped-search.py" ]; then
    bad=$(python3 "$h/deny-unscoped-search.py" --test 'grep -rn "foo" .')
    good=$(python3 "$h/deny-unscoped-search.py" --test "grep -rn 'foo' --include='*.py' .")
    [[ "$bad" == DENY* && "$good" == allow ]] \
        && ok "search hook denies the unscoped case and allows the scoped one" \
        || no "search hook verdicts wrong: bad=$bad good=$good"
    b2=$(python3 "$h/deny-long-commit-message.py" --test "git commit -m \"$(printf 'x%.0s' {1..100})\"")
    g2=$(python3 "$h/deny-long-commit-message.py" --test 'git commit -m "fix chat"')
    [[ "$b2" == DENY* && "$g2" == allow ]] \
        && ok "commit hook denies the long message and allows the short one" \
        || no "commit hook verdicts wrong: bad=$b2 good=$g2"
else
    no "hook scripts are missing from .agents/hooks"
fi

# 5. The harness actually declares them. A hook that exists and is not declared is a hook
#    that never runs, and the two states look identical from the filesystem.
if grep -q 'deny-unscoped-search' "$REPO_ROOT/.claude/settings.json" 2>/dev/null; then
    ok "settings.json declares the PreToolUse hooks"
else
    no "settings.json does not declare the hooks -- merge the block from .agents/harnesses/claude-settings.json"
fi

# 6. The five path-scoped rules are present and each declares the paths it covers.
rules=$(find "$REPO_ROOT/.agents/rules" -name '*.md' 2>/dev/null | wc -l)
unpathed=$(grep -L '^paths:' "$REPO_ROOT"/.agents/rules/*.md 2>/dev/null | wc -l)
if [ "$rules" -gt 0 ] && [ "$unpathed" -eq 0 ]; then
    ok "$rules rules, each with a paths: glob"
else
    no "rules: $rules found, $unpathed without a paths: glob"
fi

# 7. The tag checker decides correctly on a known-bad and a known-good document. Its own
#    exit status is what a person relies on, so prove it rather than that the file exists.
tagdir=$(mktemp -d)
mkdir -p "$tagdir/plans/probe"
printf '# probe\n\nThe cut described in X3 is reopened here.\n' > "$tagdir/plans/probe/bad.md"
printf '# probe\n\n## Key\n\n| tag | what | where |\n|---|---|---|\n| X3 | the cut | elsewhere |\n\nThe cut described in X3 is reopened here.\n' > "$tagdir/plans/probe/good.md"
if ! "$REPO_ROOT/.agents/check-doc-ids.py" "$tagdir/plans/probe/bad.md" >/dev/null 2>&1 \
   && "$REPO_ROOT/.agents/check-doc-ids.py" "$tagdir/plans/probe/good.md" >/dev/null 2>&1; then
    ok "tag checker denies an undeclared tag and allows one with a Key entry"
else
    no "tag checker does not decide correctly on its own probe documents"
fi
rm -rf "$tagdir"

echo "---- $pass passed, $fail failed, $skip skipped"
[ "$fail" -eq 0 ]
