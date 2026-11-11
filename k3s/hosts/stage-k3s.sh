#!/bin/bash
# Download and verify the k3s, Kata Containers and gVisor files of one architecture.
# Usage: stage-k3s.sh [amd64|arm64] [folder]. The defaults are amd64 and ~/k3s-install.
# Run it as a normal user before root-install-k3s-<host>.py. It needs no root access.
# Kata Containers runs on the amd64 nodes only, so an arm64 folder has no Kata file.
# A second run keeps the files that exist and verifies them again.
set -euo pipefail
ARCH=${1:-amd64}
case $ARCH in
  amd64) GVISOR_ARCH=x86_64 K3S_BINARY=k3s ;;
  arm64) GVISOR_ARCH=aarch64 K3S_BINARY=k3s-arm64 ;;
  *) echo "the architecture $ARCH is not amd64 or arm64" >&2; exit 1 ;;
esac
K3S_VERSION=v1.36.5+k3s1
KATA_VERSION=4.3.1
# The sha256 digest of the release asset on GitHub.
KATA_SHA256=66b35b06f6b41b56f8606ddf3ed3e5660b0971d1e309d903457c4056a0b9eff0
GVISOR_RELEASE=20261026.0
DIR=${2:-$HOME/k3s-install}
mkdir -p "$DIR"
cd "$DIR"

fetch() {
  if [ ! -s "$2" ]; then
    curl -fsSL --retry 3 -o "$2.part" "$1"
    mv "$2.part" "$2"
  fi
}

K3S_URL_VERSION=${K3S_VERSION//+/%2B}
fetch "https://github.com/k3s-io/k3s/releases/download/$K3S_URL_VERSION/$K3S_BINARY" k3s
fetch "https://github.com/k3s-io/k3s/releases/download/$K3S_URL_VERSION/sha256sum-$ARCH.txt" "k3s-sha256sum-$ARCH.txt"
echo "$(grep -E " $K3S_BINARY\$" "k3s-sha256sum-$ARCH.txt" | cut -d' ' -f1)  k3s" | sha256sum -c -
fetch "https://raw.githubusercontent.com/k3s-io/k3s/$K3S_URL_VERSION/install.sh" install-k3s.sh

if [ "$ARCH" = amd64 ]; then
  fetch "https://github.com/kata-containers/kata-containers/releases/download/$KATA_VERSION/kata-go-static-$KATA_VERSION-amd64.tar.zst" kata-go-static.tar.zst
  echo "$KATA_SHA256  kata-go-static.tar.zst" | sha256sum -c -
fi

# The archive holds runsc and containerd-shim-runsc-v1. The .sha512 file holds the digest first.
fetch "https://storage.googleapis.com/gvisor/releases/release/$GVISOR_RELEASE/$GVISOR_ARCH/gvisor.tar.zstd" gvisor.tar.zstd
fetch "https://storage.googleapis.com/gvisor/releases/release/$GVISOR_RELEASE/$GVISOR_ARCH/gvisor.tar.zstd.sha512" gvisor.tar.zstd.sha512
echo "$(cut -d' ' -f1 gvisor.tar.zstd.sha512)  gvisor.tar.zstd" | sha512sum -c -
sha256sum install-k3s.sh
ls -l "$DIR"
