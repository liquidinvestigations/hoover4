#!/usr/bin/env bash
#
# Runs the server detached on ${HOST_BIND}:${HOST_PORT}, replacing any container already holding
# that name. Uses the release image by default; --dev runs from the dev image against the working
# tree instead, rebuilding the binary on start.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

mode="release"
case "${1:-}" in
    --dev) mode="dev" ;;
    "") ;;
    *) echo "usage: $0 [--dev]" >&2; exit 2 ;;
esac

docker rm --force "$SERVER_CONTAINER" >/dev/null 2>&1 || true

publish=(--publish "${HOST_BIND}:${HOST_PORT}:${CONTAINER_PORT}")

if [[ "$mode" == "dev" ]]; then
    ensure_dev_image
    docker run --detach --name "$SERVER_CONTAINER" \
        "${DEV_RUN_ARGS[@]}" "${publish[@]}" \
        --env "RES_VENDORED_DIR=/work/vendored" \
        "$DEV_IMAGE" \
        cargo run --release --bin regex-entity-scanner
else
    if ! image_exists "$REL_IMAGE"; then
        "${REPO_ROOT}/build-rel.sh"
    fi
    docker run --detach --name "$SERVER_CONTAINER" \
        --restart unless-stopped \
        "${publish[@]}" \
        "$REL_IMAGE"
fi

echo "${SERVER_CONTAINER} listening on http://${HOST_BIND}:${HOST_PORT} (${mode})"
echo "logs:  docker logs -f ${SERVER_CONTAINER}"
echo "stop:  docker rm -f ${SERVER_CONTAINER}"
