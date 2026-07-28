#!/bin/bash
# Bring up the AI tier (GPU services, MCP servers, agents).
#
# This is deliberately not a one-liner like main_services/start-docker.sh, because
# `docker compose up -d` in this directory fails in two ways that are easy to
# misread:
#
#   1. "network hoover4 not found" — the `hoover4` network is declared external and
#      is created by the main stack. That has to be up first.
#   2. "crun: cannot stat `/usr/lib/libnvidia-*.so.<driver>`: OCI runtime attempted
#      to invoke a command that was not found" — the CDI spec in /etc/cdi/nvidia.yaml
#      lists library mounts derived from the running driver version, and a partial
#      driver upgrade (e.g. nvidia-utils bumped, nvidia-settings left behind) leaves
#      entries pointing at files that were never installed. crun refuses to start the
#      container over a missing bind source, so only the two GPU services fail while
#      the rest of the stack comes up — which looks like a GPU problem and is not.
#
# Both are checked before anything is started.

set -e

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}"; )" &> /dev/null && pwd 2> /dev/null; )";
cd "$SCRIPT_DIR"

# Pinned so the model caches (ai_services_ai_models_cache ~6 GB,
# ai_services_vllm_huggingface_cache ~16 GB) stay attached even if this directory is
# renamed. Changing this orphans them and re-downloads every weight.
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ai_services}"

CDI_SPEC="${CDI_SPEC:-/etc/cdi/nvidia.yaml}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-900}"

log() { printf '\n=== %s\n' "$*"; }


# ---------------------------------------------------------------- preflight: config
if [ ! -f .env ]; then
    echo "ERROR: no .env here. Start from the template:" >&2
    echo "    cp env.example .env && \$EDITOR .env   # at minimum set MCP_SHARED_SECRET" >&2
    exit 1
fi


# --------------------------------------------------------------- preflight: network
log "checking the hoover4 network"
if ! docker network inspect hoover4 >/dev/null 2>&1; then
    echo "ERROR: the external 'hoover4' network does not exist." >&2
    echo "       Bring the main stack up first: ../main_services/start-docker.sh" >&2
    exit 1
fi
echo "ok"


# ------------------------------------------------------------------- preflight: CDI
# Drop mounts whose host path does not exist. A CDI mount is a bind, so a missing
# source is always fatal at container start; removing the entry can only help. The
# entries this hits in practice are libnvidia-gtk3 / libnvidia-wayland-client, which
# belong to nvidia-settings and are irrelevant to CUDA workloads.
prune_stale_cdi_mounts() {
    [ -r "$CDI_SPEC" ] || { echo "no CDI spec at $CDI_SPEC — skipping (GPU services will run on CPU or fail)"; return 0; }

    local pruned; pruned="$(mktemp)"
    awk '
        function flush() { if (in_block && keep) printf "%s", buf; buf = ""; in_block = 0 }
        /^[[:space:]]*- hostPath:[[:space:]]*/ {
            flush()
            path = $0; sub(/^[[:space:]]*- hostPath:[[:space:]]*/, "", path)
            keep = (system("test -e \"" path "\"") == 0)
            if (!keep) print "  dropping missing mount: " path > "/dev/stderr"
            in_block = 1; buf = $0 "\n"; next
        }
        {
            if (in_block && $0 ~ /^[[:space:]]*(containerPath:|options:|- )/) { buf = buf $0 "\n"; next }
            flush(); print
        }
        END { flush() }
    ' "$CDI_SPEC" > "$pruned"

    if cmp -s "$CDI_SPEC" "$pruned"; then
        echo "ok — every CDI mount resolves"
        rm -f "$pruned"
        return 0
    fi

    echo "CDI spec references files that do not exist on this host; patching it."
    if ! sudo -n true 2>/dev/null; then
        echo "WARNING: $CDI_SPEC needs root to fix and sudo is not available." >&2
        echo "         The GPU services will fail with an OCI runtime error." >&2
        echo "         Fix by hand, or re-run this script with sudo access." >&2
        rm -f "$pruned"
        return 0
    fi

    local backup="${CDI_SPEC}.bak-$(date +%Y%m%d%H%M%S)"
    sudo cp -a "$CDI_SPEC" "$backup"
    sudo cp "$pruned" "$CDI_SPEC"
    sudo chmod 644 "$CDI_SPEC"
    rm -f "$pruned"
    echo "patched. previous spec kept at $backup"
    echo "NOTE: 'nvidia-ctk cdi generate' will reintroduce these entries. The durable"
    echo "      fix is to bring every nvidia-* package to the same version."
}

log "checking the NVIDIA CDI spec"
prune_stale_cdi_mounts


# ------------------------------------------------------------------------- start up
log "starting containers"
time docker compose up -d --remove-orphans "$@"


# --------------------------------------------------------------------- wait & report
# vLLM and the embedding server download weights on a cold start, so "starting" is a
# normal state for several minutes. Only an exited container is treated as a failure.
log "waiting for health (up to ${WAIT_TIMEOUT}s; Ctrl-C is safe, containers keep going)"

services="$(docker compose ps --services 2>/dev/null)"
deadline=$(( $(date +%s) + WAIT_TIMEOUT ))
failed=""

while :; do
    pending=""
    failed=""
    for svc in $services; do
        state="$(docker inspect -f '{{.State.Status}}' "$svc" 2>/dev/null || echo missing)"
        health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$svc" 2>/dev/null || true)"
        case "$state" in
            running)  [ -n "$health" ] && [ "$health" != "healthy" ] && pending="$pending $svc" ;;
            missing)  ;;
            *)        failed="$failed $svc" ;;
        esac
    done
    [ -z "$pending" ] && break
    [ "$(date +%s)" -ge "$deadline" ] && break
    sleep 10
done

log "status"
docker compose ps

if [ -n "$failed" ]; then
    echo
    echo "ERROR: these containers are not running:$failed" >&2
    for svc in $failed; do
        echo "--- $svc ---" >&2
        docker logs --tail 20 "$svc" 2>&1 | sed 's/^/    /' >&2
    done
    exit 1
fi

if [ -n "$pending" ]; then
    echo
    echo "still starting (weights download on a cold start):$pending"
    echo "follow with: docker compose logs -f$pending"
fi

echo
echo "Done."
