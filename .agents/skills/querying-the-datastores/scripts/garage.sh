#!/usr/bin/env bash
# Run a Garage admin command. The image carries no shell, so the binary is invoked
# directly rather than through `sh -lc`.
#
#   garage.sh bucket list
#   garage.sh bucket info hoover4-c-<collectionname>
#   garage.sh status
set -euo pipefail
docker exec -i "${GARAGE_CONTAINER:-garage}" /garage "$@"
