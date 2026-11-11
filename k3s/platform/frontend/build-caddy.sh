#!/usr/bin/env bash
# Build the Caddy binary of the HTTPS frontend with the Coraza WAF module into k3s/private/bin/caddy.
# The build runs in the Caddy builder image with podman, so the workstation needs no Go toolchain.
# The module embeds the OWASP Core Rule Set, so the frontend host needs no rule files.
# A binary that already has the module and the Caddy version stays. REBUILD=1 builds again.
# Usage: build-caddy.sh
set -euo pipefail
cd "$(dirname "$0")"
private=$(realpath ../../private)
caddy_version=v2.11.7
coraza_version=v2.6.2
target=$private/bin/caddy
if [ -z "${REBUILD:-}" ] && [ -x "$target" ] && "$target" version | grep -q "^$caddy_version " &&
   "$target" list-modules --versions 2>/dev/null | grep -q "^http.handlers.waf $coraza_version"; then
  echo "present $target"
  exit 0
fi
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
podman run --rm -q -e CGO_ENABLED=0 -v "$work:/out" "docker.io/library/caddy:${caddy_version#v}-builder" \
  xcaddy build "$caddy_version" --with "github.com/corazawaf/coraza-caddy/v2@$coraza_version" --output /out/caddy
install -D -m 0755 "$work/caddy" "$target"
"$target" list-modules --versions | grep "^http.handlers.waf"
