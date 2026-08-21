#!/usr/bin/env bash
# Dump Python thread stacks from a container that drops CAP_SYS_PTRACE, by attaching a
# sidecar that shares its pod and PID namespace.
set -euo pipefail
target="$1"
pid="${2:-1}"
docker run --rm --pod pod_hoover4 --pid="container:${target}" --cap-add=SYS_PTRACE \
  ghcr.io/benfred/py-spy:latest dump --pid "$pid"
