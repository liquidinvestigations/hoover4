#!/usr/bin/env bash
# Install the cluster ingress. Only the HTTPS frontend on the public host connects to it from outside the cluster.
# settings.json gives the fixed Service address (ingress_address, in the k3s Service range) and the node of the
# controller (ingress_node, the node of the frontend).
# KUBECONFIG names the admin kubeconfig. The default is k3s/private/kubeconfig. HELM names the helm command.
set -euo pipefail
# A relative KUBECONFIG path starts at the current folder, so it becomes absolute before the cd.
if [ -n "${KUBECONFIG:-}" ]; then KUBECONFIG=$(realpath "$KUBECONFIG"); fi
cd "$(dirname "$0")"
private=$(realpath ../../private)
export KUBECONFIG=${KUBECONFIG:-$private/kubeconfig}
helm=${HELM:-$private/bin/helm}
address=$(python3 ../../settings.py get ingress_address '')
node=$(python3 ../../settings.py get ingress_node '')
[ -n "$address" ] && [ -n "$node" ] || { echo "settings.json needs ingress_address and ingress_node" >&2; exit 1; }
"$helm" repo add haproxy-ingress https://haproxy-ingress.github.io/charts >/dev/null
"$helm" repo update haproxy-ingress >/dev/null
"$helm" upgrade --install haproxy-ingress haproxy-ingress/haproxy-ingress --version 0.16.2 --namespace ingress --create-namespace \
  -f haproxy-ingress-values.yaml --set "controller.service.clusterIP=$address" --set "controller.nodeSelector.kubernetes\.io/hostname=$node" \
  --wait --timeout 5m
