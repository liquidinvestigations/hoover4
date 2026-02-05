#!/bin/bash
set -ex

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}"; )" &> /dev/null && pwd 2> /dev/null; )";
cd "$SCRIPT_DIR"


cd ops/docker
echo "Stopping and removing volumes and containers"
docker rm -f  $(docker ps -qa) || true
docker volume rm -f $(docker volume ls -q) || true

echo "Starting containers"
docker compose build
time docker compose up -d

echo "Done"