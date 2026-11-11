#!/usr/bin/env bash
# Build an image with podman on the workstation and push it to the cluster registry.
# Usage: build-image.sh <context directory> <name:tag> [Containerfile]
# <name> is the path in the registry, for example hoover/blockmount. Pods name the image
# registry.hoover.internal/<name:tag>. Each node maps that name to the registry endpoint in /etc/rancher/k3s/registries.yaml.
# The endpoint is registry_endpoint in k3s/private/settings.json, for example <VPN address of the registry node>:5000.
# A tag that the registry already has is left unchanged. A local image with the tag is pushed without a new build.
# REBUILD=1 builds and pushes again. The images run on every node, so the build targets the x86-64-v2 baseline:
# a Containerfile must not compile for the build host CPU.
set -euo pipefail
dir=$1 image=$2 file=${3:-}
here=$(cd "$(dirname "$0")" && pwd)
endpoint=$(python3 "$here/../settings.py" get registry_endpoint '')
[ -n "$endpoint" ] || { echo "settings.json has no registry_endpoint" >&2; exit 1; }
local_name=registry.hoover.internal/$image
name=${image%:*} tag=${image##*:}
accept='application/vnd.oci.image.index.v1+json,application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json'
if [ -z "${REBUILD:-}" ] && curl -fs -o /dev/null -I -H "Accept: $accept" "http://$endpoint/v2/$name/manifests/$tag"; then
  echo "present $local_name"
  exit 0
fi
if [ -n "${REBUILD:-}" ] || ! podman image exists "$local_name"; then
  podman build -q --platform linux/amd64 -t "$local_name" ${file:+-f "$file"} "$dir" >/dev/null
fi
# The registry listens on the VPN address without TLS. A push needs the credentials that install-registry.sh writes.
podman push -q --tls-verify=false --authfile "$here/../private/registry-auth.json" "$local_name" "docker://$endpoint/$image"
echo "pushed $local_name"
