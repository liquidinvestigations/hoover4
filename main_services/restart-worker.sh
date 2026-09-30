#!/bin/bash
# Restart the worker without killing through its drain.
#
# `docker restart hoover4-worker` is wrong here twice over, and both failures are quiet:
#
#   1. Under Podman `restart` refuses outright, because an initialisation container is a
#      dependency and is `Exited (0)`, which is its correct final state. The error names that
#      container and reads as a broken stack. Stop and then start works.
#   2. The container is created with a ten-second stop timeout whatever the compose file
#      says: podman applies `stop_grace_period` only when it is the one stopping the
#      container, and the value cannot be written afterwards. So a direct stop SIGKILLs
#      the worker part-way through draining, which is the exact failure the graceful
#      period exists to prevent, and it is invisible unless someone counts documents.
#
# The drain period is read from the worker's own environment, so it cannot drift from the
# configuration key that set it.
#
# hoover4-ops mounts the same worker source and imports the same modules. A worker restart
# that leaves it running keeps the old modules loaded there, and a changed module then
# fails in the operations worker only, for example with an ImportError in the chat artifact
# sweep. So the script restarts both containers by default. They drain at the same time.
# WORKER names one container to restart only that one.
set -e

WORKERS="${WORKER:-hoover4-worker hoover4-ops}"
MARGIN=30

stop_one() {
    local name="$1" grace timeout
    grace=$(docker exec "$name" sh -lc 'echo ${HOOVER4_WORKER_GRACEFUL_SHUTDOWN_SECONDS:-60}' 2>/dev/null | tr -d '\r')
    case "$grace" in
        ''|*[!0-9]*) grace=60 ;;
    esac
    timeout=$(( grace + MARGIN ))
    echo "stopping $name with a ${grace}s drain (${timeout}s before SIGKILL)"
    docker stop -t "$timeout" "$name" >/dev/null
}

names=()
pids=()
for name in $WORKERS; do
    if ! docker inspect "$name" >/dev/null 2>&1; then
        if [ -n "${WORKER:-}" ]; then
            echo "error: no container named $name" >&2
            exit 1
        fi
        echo "$name does not exist, so it is not restarted"
        continue
    fi
    stop_one "$name" &
    names+=("$name")
    pids+=("$!")
done

failed=0
for i in "${!pids[@]}"; do
    if ! wait "${pids[$i]}"; then
        echo "error: the stop of ${names[$i]} failed" >&2
        failed=1
    fi
done
for name in "${names[@]}"; do
    docker start "$name" >/dev/null
    echo "$name restarted"
done
exit "$failed"
