#!/usr/bin/env bash
# Run the browser container of the repository browser harness for a website of the local cluster site.
# The harness (website/take-screenshots.sh, website/observe-chat.sh, website/run-manual-qa.sh) runs Chromium inside a
# container with docker exec. Under Compose that container is hoover4-mcp-browser. In the cluster the browser server
# runs in gVisor, where the harness cannot copy its scripts, so this script starts the container
# hoover4-harness-browser from the same image:
# - in the host network, so Chromium resolves *.<suffix> with the local DNS of the site and reaches the frontend,
# - with the local CA of the frontend as the Chromium policy CACertificates, so the browser trusts the site,
# - with sleep as its process, so it serves no MCP port. The harness starts its own Chromium.
# The stopped Compose container hoover4-mcp-browser stays unchanged.
# Usage: harness-browser.sh start|stop|status
# Then: BROWSER_CONTAINER=hoover4-harness-browser website/take-screenshots.sh --target https://hoover.<zone>.<suffix> ...
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
private=$here/../private
name=hoover4-harness-browser
image=${HARNESS_BROWSER_IMAGE:-localhost/hoover4-mcp-browser:local}
ca=$private/frontend/local-ca.crt
case "${1:-}" in
  start)
    [ -s "$ca" ] || { echo "the local CA $ca is missing. Run the frontend step of deploy-k3s first." >&2; exit 1; }
    policy=$private/harness-browser-policy.json
    python3 - "$ca" "$policy" <<'PY'
import base64, json, ssl, sys
der = ssl.PEM_cert_to_DER_cert(open(sys.argv[1]).read())
json.dump({'CACertificates': [base64.b64encode(der).decode()]}, open(sys.argv[2], 'w'))
PY
    docker rm -f "$name" >/dev/null 2>&1 || true
    docker run -d --name "$name" --network host --entrypoint sleep \
      -v "$policy:/etc/chromium/policies/managed/hoover4-local-ca.json:ro" "$image" infinity >/dev/null
    echo "started $name from $image"
    ;;
  stop) docker rm -f "$name" >/dev/null && echo "removed $name" ;;
  status) docker inspect -f '{{.Name}} {{.State.Status}} {{.Config.Image}}' "$name" ;;
  *) echo "usage: $0 start|stop|status" >&2; exit 2 ;;
esac
