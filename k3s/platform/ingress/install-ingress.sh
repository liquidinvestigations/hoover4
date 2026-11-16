#!/usr/bin/env bash
# Install the cluster ingress. Only the HTTPS frontend on the public host connects to it from outside the cluster.
# settings.json gives the fixed Service address (ingress_address, in the k3s Service range) and the node of the
# controller (ingress_node, the node of the frontend).
# KUBECONFIG names the admin kubeconfig. The default is <state folder>/kubeconfig. HELM names the helm command.
set -euo pipefail
# A relative KUBECONFIG path starts at the current folder, so it becomes absolute before the cd.
if [ -n "${KUBECONFIG:-}" ]; then KUBECONFIG=$(realpath "$KUBECONFIG"); fi
cd "$(dirname "$0")"
private=$(python3 ../../settings.py private)
export KUBECONFIG=${KUBECONFIG:-$private/kubeconfig}
helm=${HELM:-$private/bin/helm}
address=$(python3 ../../settings.py get ingress_address '')
node=$(python3 ../../settings.py get ingress_node '')
[ -n "$address" ] && [ -n "$node" ] || { echo "settings.json needs ingress_address and ingress_node" >&2; exit 1; }
"$helm" repo add haproxy-ingress https://haproxy-ingress.github.io/charts >/dev/null
"$helm" repo update haproxy-ingress >/dev/null
# The values of the site go into one values file, so helm_release compares every value of the release and upgrades it
# only on a change.
values=$(mktemp --suffix=.yaml)
trap 'rm -f "$values"' EXIT
python3 - "$address" "$node" > "$values" <<'PY'
import json, sys, yaml
data = yaml.safe_load(open('haproxy-ingress-values.yaml')) or {}
controller = data.setdefault('controller', {})
controller.setdefault('service', {})['clusterIP'] = sys.argv[1]
controller.setdefault('nodeSelector', {})['kubernetes.io/hostname'] = sys.argv[2]
print(json.dumps(data))
PY
source ../helm-release.sh
helm_release "$helm" haproxy-ingress ingress haproxy-ingress/haproxy-ingress 0.16.2 "$values" --wait --timeout 5m
