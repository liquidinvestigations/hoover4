#!/usr/bin/env bash
# Run the test suites of the cluster deployment code in containers. Usage: k3s/tests/run.sh [suite ...]
# Without a suite it runs render and state.
#   render   the site file, the source ini reader and the Hoover render (test_config.py, test_render.py)
#   state    the operator settings registry, revisions and apply operations (test_state.py)
#   replay   the workflow replay suite of the pipeline, in the running hoover4-worker container
# The suites driver, migration and backup belong to later packages and do not exist yet.
# The render and state suites mount the repository read-only and change nothing on the host or a cluster.
set -euo pipefail

tests_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$tests_dir/../.." && pwd)"
suites=("$@")
[ ${#suites[@]} -eq 0 ] && suites=(render state)

declare -A files=([render]="test_config.py test_render.py" [state]="test_state.py")
built=""
status=0
for suite in "${suites[@]}"; do
    case "$suite" in
        render|state)
            if [ -z "$built" ]; then
                docker build --quiet --tag hoover4-k3s-tests "$tests_dir" >/dev/null
                built=1
            fi
            # shellcheck disable=SC2086
            docker run --rm \
                --mount "type=bind,src=$repo_root,dst=/repo,readonly" \
                --workdir /repo/k3s/tests \
                --env PYTHONDONTWRITEBYTECODE=1 \
                hoover4-k3s-tests \
                python -m pytest -q -p no:cacheprovider ${files[$suite]} || status=1
            ;;
        replay)
            docker exec hoover4-worker sh -lc 'cd /app && uv run pytest tests/replay -q -p no:cacheprovider' || status=1
            ;;
        driver|migration|backup)
            echo "the $suite suite does not exist yet. Its package creates it." >&2
            status=1
            ;;
        *)
            echo "unknown suite $suite. The suites are render, state and replay." >&2
            status=1
            ;;
    esac
done
exit $status
