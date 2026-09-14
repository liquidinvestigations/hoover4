#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"

docker build --tag hoover4-deploy-tests "$script_dir"
exec docker run --rm \
    --mount "type=bind,src=$repo_root,dst=/repo,readonly" \
    --mount "type=bind,src=$script_dir,dst=/tests,readonly" \
    --workdir /tests \
    hoover4-deploy-tests \
    python -m pytest -v -p no:cacheprovider test_render.py
