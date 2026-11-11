#!/usr/bin/env bash
# Create or upgrade a zone through zone.py. A new zone needs --home <node>.
set -euo pipefail
exec python3 "$(dirname "$0")/zone.py" apply "$@"
