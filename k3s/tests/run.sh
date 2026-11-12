#!/usr/bin/env bash
# Run the test suites of the cluster deployment code in containers. Usage: k3s/tests/run.sh [suite ...]
# Without a suite it runs render, state and driver.
#   render   the site file, the source ini reader and the Hoover render (test_config.py, test_render.py)
#   state    the operator settings registry, revisions, apply operations and portal routes (test_state.py, test_portal.py)
#   driver   the deployment driver with fake ssh, sudo and kubectl, and the host scripts (test_driver.py, test_hosts.py)
#   migration the offline copy, its hashes and owner mapping, interruption and the plan rules (test_migration.py)
#   backup   the backup schedule, eligibility, retention and restore manifests with controlled time (test_backup.py)
#   replay   the workflow replay suite of the pipeline, in the worker image with the processing folder mounted read-only.
#            REPLAY_IMAGE names the image. The default is the image of the Compose worker of this workstation.
# The render, state and driver suites mount the repository read-only and change nothing on the host or a cluster.
set -euo pipefail

tests_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$tests_dir/../.." && pwd)"
suites=("$@")
[ ${#suites[@]} -eq 0 ] && suites=(render state driver)

declare -A files=([render]="test_config.py test_render.py" [state]="test_state.py test_portal.py" [driver]="test_driver.py test_hosts.py"
                 [migration]="test_migration.py" [backup]="test_backup.py")
built=""
status=0
for suite in "${suites[@]}"; do
    case "$suite" in
        render|state|driver|migration|backup)
            if [ -z "$built" ]; then
                docker build --quiet --tag hoover4-k3s-tests "$tests_dir" >/dev/null
                built=1
            fi
            # shellcheck disable=SC2086
            docker run --rm \
                --mount "type=bind,src=$repo_root,dst=/repo,readonly" \
                --workdir /repo/k3s/tests \
                --env PYTHONDONTWRITEBYTECODE=1 \
                --env HOOVER4_SITE=/nonexistent/hoover4-site.ini \
                hoover4-k3s-tests \
                python -m pytest -q -p no:cacheprovider ${files[$suite]} || status=1
            ;;
        replay)
            docker run --rm --network none \
                --mount "type=bind,src=$repo_root/main_services/processing,dst=/app,readonly" \
                --workdir /app --env PYTHONDONTWRITEBYTECODE=1 --entrypoint sh \
                "${REPLAY_IMAGE:-localhost/hoover4_hoover4-worker:latest}" \
                -c '/opt/pysetup/.venv/bin/python -m pytest tests/replay -q -p no:cacheprovider' || status=1
            ;;
        *)
            echo "unknown suite $suite. The suites are render, state, driver, migration, backup and replay." >&2
            status=1
            ;;
    esac
done
exit $status
