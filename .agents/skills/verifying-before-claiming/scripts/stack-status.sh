#!/usr/bin/env bash
# One-line health view of every container, unhealthy ones first.
set -uo pipefail
docker ps -a --format '{{.Names}}\t{{.Status}}' | sort -t$'\t' -k2 | column -t -s$'\t'
