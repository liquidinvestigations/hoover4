#!/usr/bin/env bash
# Build runsc with gVisor PR 16643 (nvproxy support for the GB10 GPU of the DGX Spark) and stage it for a GPU node.
# Decision D3: use this build when the released runsc fails on the GPU node. Decision D20: if the build fails too after a
# bounded diagnosis, select gpu.runtime = runc in the operator portal and record the failure.
# Usage: stage-runsc-nvproxy.sh <amd64|arm64> <staging folder>
# The script needs git and Docker or Podman with the docker command. gVisor builds runsc with Bazel in a container
# (make runsc). The build runs on a host of the target architecture, for example the GPU node itself.
# It writes <staging folder>/runsc-nvproxy/runsc and runsc.sha256. root-install-k3s.py installs the binary into
# /opt/gvisor-nvproxy on the GPU node when the staging folder holds it, and the handler runsc-nvproxy uses it.
# GVISOR_BASE names the gVisor commit that the pull request applies to. GVISOR_PR names the pull request.
set -euo pipefail
arch=${1:?the architecture, amd64 or arm64}
staging=${2:?the staging folder}
GVISOR_BASE=${GVISOR_BASE:-release-20261026.0}
GVISOR_PR=${GVISOR_PR:-16643}
[ "$(uname -m | sed 's/x86_64/amd64/; s/aarch64/arm64/')" = "$arch" ] || {
  echo "build on a $arch host. This host is $(uname -m)." >&2; exit 1; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
git clone --quiet https://github.com/google/gvisor "$work/gvisor"
cd "$work/gvisor"
git -c advice.detachedHead=false checkout --quiet "$GVISOR_BASE"
git fetch --quiet origin "pull/$GVISOR_PR/head:pr-$GVISOR_PR"
# A conflict stops the script. Record the base and the pull request revision in the inventory before a retry.
git -c user.name=stage -c user.email=stage@localhost merge --no-edit --quiet "pr-$GVISOR_PR"
pr_revision=$(git rev-parse "pr-$GVISOR_PR")
make runsc
binary=$(find bazel-out -path '*/runsc/runsc_/runsc' -type f -o -path '*/runsc/runsc' -type f | head -n 1)
[ -n "$binary" ] || { echo "the build wrote no runsc binary" >&2; exit 1; }
install -d "$staging/runsc-nvproxy"
install -m 0755 "$binary" "$staging/runsc-nvproxy/runsc"
(cd "$staging/runsc-nvproxy" && sha256sum runsc > runsc.sha256)
printf 'base %s\npull request %s at %s\n' "$GVISOR_BASE" "$GVISOR_PR" "$pr_revision" > "$staging/runsc-nvproxy/SOURCE"
echo "staged $staging/runsc-nvproxy/runsc ($(cut -d' ' -f1 "$staging/runsc-nvproxy/runsc.sha256"))"
