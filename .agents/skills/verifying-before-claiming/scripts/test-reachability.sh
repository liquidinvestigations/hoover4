#!/usr/bin/env bash
# Confirm every test directory this repository owns is executed by a runner.
#
# A test suite that ships inside an image but that no script ever invokes fails
# silently. It looks covered, and it is not.
#
# This script enumerates the leaf test directories under version control. It
# checks each against a table of known runners. That table comes from reading
# the runners themselves: a Dockerfile COPY line, a script's default pytest
# target, a `cargo test` invocation. It fails loudly and names the directory
# when one has no entry, or when its evidence no longer holds.
#
# A directory this script has never seen reports UNREACHED. It is not silently
# skipped. That is what catches a third suite shipped and never run.
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
V=".agents/skills/verifying-before-claiming/scripts"

unreached=0
reached=0

report() {
    local status="$1" dir="$2" detail="$3"
    if [ "$status" = "OK" ]; then
        echo "OK    $dir -> $detail"
        reached=$((reached + 1))
    else
        echo "UNREACHED  $dir  ($detail)"
        unreached=$((unreached + 1))
    fi
}

# ---------------------------------------------------------------------------
# 1. Enumerate the "tests" directories this repository owns.
#
# Vendored trees, the cargo registry cache, node_modules, .venv and plans/ are
# excluded. An unfiltered search returns roughly a hundred directories from
# dependency source, and this repository cannot wire any of them into a runner.
# ---------------------------------------------------------------------------
mapfile -t test_roots < <(find . -type d -name tests \
    -not -path "*/vendored/*" \
    -not -path "*/.container/*" \
    -not -path "*/node_modules/*" \
    -not -path "*/.venv/*" \
    -not -path "*/plans/*" \
    -not -path "*/target/*" \
    2>/dev/null | sed 's|^\./||' | sort)

if [ "${#test_roots[@]}" -eq 0 ]; then
    echo "FAIL  no test directories found -- the exclusions above are almost certainly too wide"
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Split each root into the leaf directories that actually hold test files.
#
# A leaf is the root itself when it holds test files directly: test_*.py,
# *_test.py, or a *.rs file (cargo compiles each top-level tests/*.rs as its
# own integration-test binary). When the root holds no test files of its own,
# but a subdirectory does (main_services/processing/tests/unit and
# .../integration), each such subdirectory is its own leaf. A runner that
# reaches one does not necessarily reach the other. That split is the exact
# shape of gap this check exists to find.
# ---------------------------------------------------------------------------
has_direct_tests() {
    local dir="$1"
    find "$dir" -maxdepth 1 -type f \( -name 'test_*.py' -o -name '*_test.py' -o -name '*.rs' \) \
        -print -quit 2>/dev/null | grep -q .
}

leaves=()
for root in "${test_roots[@]}"; do
    if has_direct_tests "$root"; then
        leaves+=("$root")
        continue
    fi
    found_sub=0
    while IFS= read -r sub; do
        if has_direct_tests "$sub"; then
            leaves+=("$sub")
            found_sub=1
        fi
    done < <(find "$root" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
    if [ "$found_sub" -eq 0 ]; then
        # A "tests" directory with no direct test files and no test-bearing
        # subdirectory (fixtures/, __pycache__, ...) is data, not a suite.
        :
    fi
done

# ---------------------------------------------------------------------------
# 3. The reached table, one row per leaf, built by reading the runner named.
#    Each row's evidence command re-confirms the mapping still holds. It checks
#    that the runner still names the directory, not only that the directory
#    exists.
# ---------------------------------------------------------------------------
declare -A RUNNER_OF
declare -A EVIDENCE_OF

add() { RUNNER_OF["$1"]="$2"; EVIDENCE_OF["$1"]="$3"; }

add "main_services/agents/agent_common/tests" \
    "$V/pytest-agents.sh (vendored into tests/shared in the five MCP server images)" \
    'grep -l "agent_common/tests/" main_services/agents/*/Dockerfile | wc -l | grep -qv "^0$"'

add "main_services/agents/agent_todo_server/tests" "$V/pytest-agents.sh (hoover4-mcp-todo)" \
    'grep -q "hoover4-mcp-todo" '"$V"'/pytest-agents.sh'
add "main_services/agents/browser_use_server/tests" "$V/pytest-agents.sh (hoover4-mcp-browser)" \
    'grep -q "hoover4-mcp-browser" '"$V"'/pytest-agents.sh'
add "main_services/agents/collection_search_server/tests" "$V/pytest-agents.sh (hoover4-mcp-collections)" \
    'grep -q "hoover4-mcp-collections" '"$V"'/pytest-agents.sh'
add "main_services/agents/metasearch_server/tests" "$V/pytest-agents.sh (hoover4-mcp-metasearch)" \
    'grep -q "hoover4-mcp-metasearch" '"$V"'/pytest-agents.sh'
add "main_services/agents/whois_search_server/tests" "$V/pytest-agents.sh (hoover4-mcp-whois)" \
    'grep -q "hoover4-mcp-whois" '"$V"'/pytest-agents.sh'
add "main_services/agents/research_agent/tests" "$V/pytest-research-agent.sh" \
    'grep -q "target=\"\${1:-tests}\"" '"$V"'/pytest-research-agent.sh'
add "main_services/processing/tests/unit" "$V/pytest-unit.sh (default target tests/unit)" \
    'grep -q "target=\"\${1:-tests/unit}\"" '"$V"'/pytest-unit.sh'
add "main_services/regex_entity_scanner/tests" "main_services/regex_entity_scanner/test.sh" \
    'grep -q "cargo test" main_services/regex_entity_scanner/test.sh'
add "website/backend/tests" "website/run-stack-tests.sh" \
    'grep -q "stack_integration" website/run-stack-tests.sh'
add "main_services/ocr_pdf/tests" "$V/pytest-ocr-pdf.sh" \
    'grep -q "hoover4-ocr-pdf" '"$V"'/pytest-ocr-pdf.sh'

# The runners searched, named in every failure message so a miss is
# actionable rather than a bare non-zero exit.
RUNNERS_SEARCHED="$V/pytest-unit.sh, $V/pytest-agents.sh, $V/pytest-research-agent.sh, \
$V/pytest-ocr-pdf.sh, main_services/verify-stack.sh, website/run-stack-tests.sh, \
main_services/regex_entity_scanner/test.sh, and each agent image's Dockerfile"

echo "== test directories owned by this repository (${#leaves[@]} leaves under ${#test_roots[@]} roots) =="
for leaf in "${leaves[@]}"; do
    runner="${RUNNER_OF[$leaf]:-}"
    if [ -z "$runner" ]; then
        report FAIL "$leaf" "no known runner reaches it -- searched $RUNNERS_SEARCHED"
        continue
    fi
    evidence="${EVIDENCE_OF[$leaf]}"
    if eval "$evidence" >/dev/null 2>&1; then
        report OK "$leaf" "$runner"
    else
        report FAIL "$leaf" "was mapped to $runner but that evidence no longer holds -- re-check the mapping"
    fi
done

echo "---- $reached reached, $unreached unreached"
[ "$unreached" -eq 0 ]
