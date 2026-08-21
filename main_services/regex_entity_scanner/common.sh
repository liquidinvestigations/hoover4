# Shared settings for the container scripts. Sourced, never executed.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

DEV_IMAGE="regex-entity-scanner-dev:local"
REL_IMAGE="regex-entity-scanner:local"
SERVER_CONTAINER="regex-entity-scanner"

# The published address. The server listens on 0.0.0.0 inside the container; only the loopback
# mapping on the host makes it reachable.
HOST_BIND="127.0.0.1"
HOST_PORT="19705"
CONTAINER_PORT="19705"

# A bind mount of the working tree is the whole development story: sources, `target/`, the cargo
# registry under `.container/` and the vendored data are all read and written in place, so the
# container holds no state of its own and can be thrown away at any moment.
DEV_RUN_ARGS=(
    --volume "${REPO_ROOT}:/work"
    --workdir /work
)

image_exists() {
    docker image inspect "$1" >/dev/null 2>&1
}

# Builds the dev image unless it is already present. `--force`/`-f` rebuilds from scratch.
ensure_dev_image() {
    if [[ "${1:-}" == "--force" || "${1:-}" == "-f" ]] || ! image_exists "$DEV_IMAGE"; then
        "${REPO_ROOT}/build-dev.sh" "${1:-}"
    fi
}
