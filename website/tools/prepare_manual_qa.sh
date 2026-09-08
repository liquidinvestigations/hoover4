#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
worker_log="$repo_root/website/test_reports/manual_qa_fixtures.worker.log"
profile="$repo_root/website/test_reports/manual_qa_fixtures.json"
mkdir -p "$repo_root/website/test_reports"
if [ -f "$profile" ]; then
    mv "$profile" "$repo_root/website/test_reports/manual_qa_fixtures.previous.json"
fi
staging="$(docker exec hoover4-worker mktemp -d /tmp/manual-qa-preparation.XXXXXX)"

docker cp "$repo_root/website/tools/prepare_manual_qa.py" "hoover4-worker:$staging/prepare_manual_qa.py"
docker cp "$repo_root/website/tools/manual_qa_fixtures.json" "hoover4-worker:$staging/manual_qa_fixtures.json"
set +e
docker exec -w /app -e "MANUAL_QA_STAGING_ROOT=$staging" hoover4-worker uv run python "$staging/prepare_manual_qa.py" "$@" 2>&1 | tee "$worker_log"
status=$?
set -e

for argument in "$@"; do
    if [ "$argument" = "--prepare-only" ]; then
        exit "$status"
    fi
done

if docker exec hoover4-worker test -f "$staging/manual_qa_fixtures.resolved.json"; then
    docker cp "hoover4-worker:$staging/manual_qa_fixtures.resolved.json" "$profile.pending"
    mv "$profile.pending" "$profile"
fi
exit "$status"
