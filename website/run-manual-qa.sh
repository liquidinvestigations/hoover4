#!/usr/bin/env bash
# Run the fixture-validated manual QA browser matrix.
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
script_dir="$repo_root/website"
out="$repo_root/website/test_reports/manual_qa"
select=""
resolutions="720p,1080p"
skip_chat=false
TARGET_ARG=""
LOGIN_ENV_ARG=""

while [ $# -gt 0 ]; do
    case "$1" in
        --out) out="${2:?--out needs a value}"; shift 2 ;;
        --select) select="${2:?--select needs a value}"; shift 2 ;;
        --resolutions) resolutions="${2:?--resolutions needs a value}"; shift 2 ;;
        --skip-chat) skip_chat=true; shift ;;
        --target) TARGET_ARG="${2:?--target needs a value}"; shift 2 ;;
        --login-env) LOGIN_ENV_ARG="${2:?--login-env needs a value}"; shift 2 ;;
        *) echo "error: unknown argument '$1'" >&2; exit 2 ;;
    esac
done

LOGIN_ENV_FILE="${LOGIN_ENV_ARG:-$script_dir/TEST_LOGIN.env}"
if [ -z "$LOGIN_ENV_ARG" ] && [ ! -f "$LOGIN_ENV_FILE" ]; then
    LOGIN_ENV_FILE=""
fi
# shellcheck source=tools/capture_credentials.sh
source "$script_dir/tools/capture_credentials.sh"
require_capture_target
export HOOVER4_SITE_URL="$SITE_URL"
echo "== target: $SITE_URL (source: $TARGET_SOURCE) =="

mkdir -p "$out"
plan="$out/manual-qa-plan.json"
browser_container="${BROWSER_CONTAINER:-hoover4-mcp-browser}"
remote_dir="/tmp/manual-qa-$$"
cleanup() {
    docker exec "$browser_container" rm -rf "$remote_dir" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker exec "$browser_container" mkdir -p "$remote_dir"
docker cp "$repo_root/website/tools/manual_qa.py" "$browser_container:$remote_dir/manual_qa.py"
docker cp "$repo_root/website/test_reports/manual_qa_fixtures.json" "$browser_container:$remote_dir/profile.json"
docker cp "$repo_root/website/browser-tests" "$browser_container:$remote_dir/browser-tests"
set +e
scenarios="$(docker exec -w "$remote_dir" "$browser_container" python3 manual_qa.py --profile profile.json --ini browser-tests --select "$select" --out manual-qa-plan.json --print-scenarios)"
preflight_status=$?
set -e
docker cp "$browser_container:$remote_dir/manual-qa-plan.json" "$plan"
browser_status=2
if [ -n "$scenarios" ]; then
    set +e
    "$repo_root/website/take-screenshots.sh" --target "$SITE_URL" --names "$scenarios" --resolutions "$resolutions" --out "$out/browser"
    browser_status=$?
    set -e
fi
chat_status=2
if ! $skip_chat && docker exec -w "$remote_dir" "$browser_container" python3 -c 'import json; raise SystemExit(0 if json.load(open("manual-qa-plan.json", encoding="utf-8"))["chat_required"] else 1)'; then
    set +e
    "$repo_root/website/observe-chat.sh" --target "$SITE_URL" --prompts collection-exploration --conversations 1 --resolutions "$resolutions" --out "$out/chat"
    chat_status=$?
    set -e
fi
docker cp "$out/." "$browser_container:$remote_dir/evidence"
set +e
docker exec -w "$remote_dir" "$browser_container" python3 manual_qa.py --summarize evidence --resolutions "$resolutions" --browser-exit "$browser_status" --chat-exit "$chat_status" --preflight-exit "$preflight_status"
result_status=$?
set -e
docker cp "$browser_container:$remote_dir/evidence/manual-qa-results.json" "$out/manual-qa-results.json"
exit "$result_status"
