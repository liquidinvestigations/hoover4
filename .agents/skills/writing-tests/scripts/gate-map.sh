#!/usr/bin/env bash
# Route changed paths to the gates a change owes.
#
# It never selects inside a suite. The fast tier is 1,494 Python tests in
# about 17 seconds, so nothing in it is worth trimming, and the Rust suites
# are compilation-bound, so filtering them saves nothing either. What is
# worth routing is the three gates that cost minutes to tens of minutes, plus
# the couplings no language server can see. See ../reference/suites.md for
# the measurements and ../../reviewing-changes/SKILL.md for the couplings.
#
# Usage:
#   gate-map.sh [path ...]     Route the named paths.
#   gate-map.sh                Route `git diff --name-only HEAD`, the same
#                               fixed point `reviewing-changes` reads.
#   gate-map.sh --self-check   Verify the table instead of routing a change:
#                               every gate command named below exists, and
#                               every top-level tracked source directory is
#                               matched by at least one rule. Exits non-zero
#                               when either check fails.
set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
V=".agents/skills/verifying-before-claiming/scripts"

# One rule per block. A path can match more than one: a `.rs` file under
# `website/common/src/` owes both the type check and the stack suite.
route_path() {
    local p="$1" matched=0

    if [[ "$p" == main_services/agents/*.py ]]; then
        matched=1
        printf 'GATE\trebuild this agent'"'"'s image first (rule 2: the agent code is baked into it, so a source edit that skips the rebuild leaves the suite testing the old image and passing), then the fast tier: %s/pytest-unit.sh, %s/pytest-agents.sh (the agent suite)\n' "$V" "$V"
    elif [[ "$p" == main_services/*.py || "$p" == ai_services/*.py ]]; then
        matched=1
        printf 'GATE\tthe fast tier: %s/pytest-unit.sh, %s/pytest-agents.sh\n' "$V" "$V"
    fi

    if [[ "$p" == *.rs ]]; then
        matched=1
        printf 'GATE\t%s/cargo-check.sh (includes the test targets, not optional)\n' "$V"
    fi

    if [[ "$p" == website/frontend/* ]]; then
        matched=1
        printf 'GATE\t%s/dx-check.sh, then a screenshot of the page (driving-the-browser)\n' "$V"
    fi

    if [[ "$p" == website/backend/src/api/* ]]; then
        matched=1
        printf 'GATE\tthe stack integration suite: website/run-stack-tests.sh\n'
    fi

    if [[ "$p" == website/common/src/* ]]; then
        matched=1
        printf 'GATE\tthe stack integration suite: website/run-stack-tests.sh\n'
        printf 'HAND\tmirrored constant: confirm the Python-side counterpart moved too (.agents/skills/reviewing-changes/SKILL.md, "Mirrored constants moved on one side only")\n'
    fi

    if [[ "$p" == main_services/processing/tasks/P3_parse_files/* || "$p" == website/common/src/document_sources.rs ]]; then
        matched=1
        printf 'GATE\tthe whole-stack verification: main_services/verify-stack.sh (writer or extractor-key contract, .agents/skills/reviewing-changes/SKILL.md)\n'
    fi

    if [[ "$p" == main_services/processing/tasks/run_worker.py || "$p" == main_services/processing/tasks/heartbeat.py ]]; then
        matched=1
        printf 'GATE\tthe restart-resilience gate: main_services/verify-stack.sh --restart-resilience\n'
    fi

    if [[ "$p" == *db_global_migrations/* || "$p" == *db_collection_migrations/* ]]; then
        matched=1
        printf 'GATE\tthe migration parity test: %s/pytest-unit.sh tests/unit/test_migrations_parity.py\n' "$V"
        printf 'HAND\tnever edit an applied migration, because the runner'"'"'s md5 check then refuses every deployment that already ran it (AGENTS.md, Invariants)\n'
    fi

    if [[ "$p" == hoover4.ini* || "$p" == *.env* ]]; then
        matched=1
        printf 'GATE\ta deploy: nothing else re-reads hoover4.ini or a generated environment file (deploying-the-stack)\n'
    fi

    if [[ "$p" == testdata/* ]]; then
        matched=1
        printf 'GATE\tthe stack integration suite: website/run-stack-tests.sh\n'
        printf 'GATE\tthe browser acceptance pass: website/take-screenshots.sh\n'
        printf 'HAND\tboth fixture-driven suites are welded to this corpus, so a change here makes them fail by naming a dataset that does not exist, which reads as a broken site and is not (docs/development/Running_Checks.md)\n'
    fi

    if [[ "$p" == components/* ]]; then
        matched=1
        printf 'GATE\t%s/dx-check.sh, then a screenshot of the page that embeds it (driving-the-browser)\n' "$V"
    fi

    if [[ "$p" == docs/technical-specification/* ]]; then
        matched=1
        printf 'HAND\tnothing to run, and the paired code change must land in the same patch (AGENTS.md, Invariants)\n'
    fi

    if [[ "$matched" -eq 0 ]]; then
        printf 'HAND\tno rule matches %s, so run --self-check to see whether its directory is routed at all\n' "$p"
    fi
}

# Every gate named above, and every top-level tracked source directory a
# rule has to reach. A directory absent from the right column here is a
# package the table has never been told about.
self_check() {
    local fail=0

    echo "gate commands:"
    local cmd
    for cmd in \
        "$V/pytest-unit.sh" \
        "$V/pytest-agents.sh" \
        "$V/cargo-check.sh" \
        "$V/dx-check.sh" \
        "website/run-stack-tests.sh" \
        "website/take-screenshots.sh" \
        "main_services/verify-stack.sh" \
        "deploy"
    do
        if [[ -f "$repo_root/$cmd" ]]; then
            echo "  OK        $cmd"
        else
            echo "  MISSING   $cmd"
            fail=1
        fi
    done

    # Coverage is probed through the router itself, never restated as a
    # second list, because a list kept beside the rules is a list that
    # disagrees with them. A directory holding source files is covered when
    # at least one of them produces a rule. A directory holding no source is
    # not a source tree and owes nothing.
    echo "top-level tracked source directories:"
    local dir f hit total
    while IFS= read -r dir; do
        case "$dir" in
            .*) continue ;;
        esac
        hit="" total=0
        while IFS= read -r f; do
            total=$((total + 1))
            if [[ -z "$hit" ]] && route_path "$f" | grep -q '^GATE'; then
                hit="$f"
            fi
        done < <(cd "$repo_root" && git ls-files "$dir" \
                 | grep -E '\.(py|rs|sh|sql|toml|ini)$' | head -200)
        if [[ "$total" -eq 0 ]]; then
            echo "  SKIP        $dir   (no source files, nothing to route)"
        elif [[ -n "$hit" ]]; then
            echo "  OK          $dir   (probe: $hit)"
        else
            echo "  UNMATCHED   $dir   ($total source files and no rule reaches any of them)"
            fail=1
        fi
    done < <(cd "$repo_root" && git ls-files | awk -F/ 'NF>1 {print $1}' | sort -u)

    return "$fail"
}

if [[ "${1:-}" == "--self-check" ]]; then
    self_check
    exit $?
fi

paths=("$@")
if [[ "${#paths[@]}" -eq 0 ]]; then
    mapfile -t paths < <(cd "$repo_root" && git diff --name-only HEAD)
fi

if [[ "${#paths[@]}" -eq 0 ]]; then
    echo "No changed paths against HEAD."
    exit 0
fi

gates=()
hand=()
p=""
for p in "${paths[@]}"; do
    kind="" line=""
    while IFS=$'\t' read -r kind line; do
        [[ -z "$kind" ]] && continue
        if [[ "$kind" == "GATE" ]]; then
            gates+=("$line")
        else
            hand+=("$line")
        fi
    done < <(route_path "$p")
done

echo "Gates owed:"
if [[ "${#gates[@]}" -eq 0 ]]; then
    echo "  none"
else
    printf '%s\n' "${gates[@]}" | sort -u | sed 's/^/  - /'
fi

echo
echo "Couplings to check by hand:"
if [[ "${#hand[@]}" -eq 0 ]]; then
    echo "  none"
else
    printf '%s\n' "${hand[@]}" | sort -u | sed 's/^/  - /'
fi
