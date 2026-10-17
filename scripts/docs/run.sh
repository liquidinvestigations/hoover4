#!/usr/bin/env bash
# Run documentation checks against the current checkout in an isolated container.
set -euo pipefail
root=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
image=localhost/hoover4-docs-check:1
docker build -q -t "$image" "$root/scripts/docs" >/dev/null
if [[ ${1:-} == test ]]; then
    shift
    exec docker run --rm --network none -v "$root:/repo:ro" --entrypoint python3 "$image" \
        -B -m unittest discover -s scripts/docs/tests "$@"
fi
if [[ ${1:-} == publish ]]; then
    shift
    exec docker run --rm --network none -v "$root:/repo:rw" --entrypoint python3 "$image" \
        -B scripts/docs/publish_screenshots.py "$@"
fi
if [[ ${1:-} == external ]]; then
    shift
    mkdir -p "$root/plans"
    exec docker run --rm -v "$root:/repo:ro" -v "$root/plans:/repo/plans:rw" --entrypoint python3 "$image" \
        -B scripts/docs/external_links.py "$@"
fi
# The index list selects tracked paths without Git inside the container.
index=$(mktemp)
trap 'rm -f "$index"' EXIT
git -C "$root" ls-files -z > "$index"
if [[ ${1:-} == mermaid ]]; then
    output=${2:?Use an output directory for rendered diagrams.}
    mkdir -p "$output"
    output=$(cd "$output" && pwd)
    docker run --rm --network none -v "$root:/repo:ro" -v "$index:/tmp/docs-index:ro" \
        -v "$output:/output:rw" --entrypoint python3 "$image" \
        -B scripts/docs/mermaid.py extract /output
    python3 "$root/scripts/docs/mermaid.py" render "$output"
else
    docker run --rm --network none -v "$root:/repo:ro" -v "$index:/tmp/docs-index:ro" \
        "$image" --index /tmp/docs-index "$@"
fi
