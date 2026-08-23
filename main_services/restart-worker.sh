#!/bin/bash
# Restart the worker without killing through its drain.
#
# `docker restart hoover4-worker` is wrong here twice over, and both failures are quiet:
#
#   1. Under a rootless runtime `restart` refuses outright, because an initialisation
#      container is `Exited (0)`, which is its correct final state. The error names that container
#      and reads as a broken stack. Stop and then start works.
#   2. The container is created with a ten-second stop timeout whatever the compose file
#      says: podman applies `stop_grace_period` only when it is the one stopping the
#      container, and the value cannot be written afterwards. So a direct stop SIGKILLs
#      the worker part-way through draining, which is the exact failure the graceful
#      period exists to prevent, and it is invisible unless someone counts documents.
#
# The drain period is read from the worker's own environment, so it cannot drift from the
# configuration key that set it.
set -e

WORKER="${WORKER:-hoover4-worker}"
MARGIN=30

grace=$(docker exec "$WORKER" sh -lc 'echo ${HOOVER4_WORKER_GRACEFUL_SHUTDOWN_SECONDS:-60}' 2>/dev/null | tr -d '\r')
case "$grace" in
    ''|*[!0-9]*) grace=60 ;;
esac
timeout=$(( grace + MARGIN ))

echo "stopping $WORKER with a ${grace}s drain (${timeout}s before SIGKILL)"
docker stop -t "$timeout" "$WORKER"
docker start "$WORKER"
echo "$WORKER restarted"
