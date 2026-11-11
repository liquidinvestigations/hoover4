#!/bin/bash
# Set up the cluster on the k3s nodes: node labels, RuntimeClasses, cert-manager and TopoLVM.
# Run it on a host with kubectl, helm, python3 and the admin kubeconfig. A second run changes nothing.
# KUBECONFIG names the admin kubeconfig. The default is k3s/private/kubeconfig.
# SITE names the site file with the storage tiers and the AVX2 flag of each node. The default is k3s/private/hosts.json.
# HELM names the helm command. The default is k3s/private/bin/helm, else helm.
set -euo pipefail
# A relative KUBECONFIG path starts at the current folder, so it becomes absolute before the cd.
if [ -n "${KUBECONFIG:-}" ]; then KUBECONFIG=$(realpath "$KUBECONFIG"); fi
cd "$(dirname "$0")"
PRIVATE=$(realpath ../private)
export KUBECONFIG=${KUBECONFIG:-$PRIVATE/kubeconfig}
SITE=${SITE:-$PRIVATE/hosts.json}
if [ -z "${HELM:-}" ]; then
  if [ -x "$PRIVATE/bin/helm" ]; then HELM=$PRIVATE/bin/helm; else HELM=helm; fi
fi
CERT_MANAGER_VERSION=v1.21.3
TOPOLVM_CHART_VERSION=17.3.0

# A node with a storage tier is enrolled for stateful pods. The tier labels select the lvmd configuration.
# A node without AVX2 has no cpu.hoover/avx2 label. Workloads that need AVX2 select this label.
python3 - "$SITE" <<'PY' | while read -r node labels; do kubectl label node "$node" $labels --overwrite; done
import json, sys
site = json.load(open(sys.argv[1]))
for name, host in site["hosts"].items():
    labels = [f"storage.tier/{tier}=true" for tier in host.get("tiers", [])]
    if labels:
        labels.append("storage.hoover/enrolled=true")
    if host.get("avx2"):
        labels.append("cpu.hoover/avx2=true")
    if labels:
        print(name, " ".join(labels))
PY

kubectl apply -f runtimeclasses.yaml

# helm_install <release> <namespace> <repo/chart> <version> <values file>
# Install or upgrade the release only when its chart version, its status or its values differ.
# A Helm upgrade with no change still writes a new release revision, so the script skips it.
helm_install() {
  local release=$1 namespace=$2 chart=$3 version=$4 values=$5
  if "$HELM" get values "$release" -n "$namespace" -o json 2>/dev/null | python3 -c '
import json, sys, yaml
current, wanted = json.load(sys.stdin), yaml.safe_load(open(sys.argv[1])) or {}
sys.exit(0 if current == wanted else 1)' "$values" &&
    [ "$("$HELM" list -n "$namespace" --filter "^$release\$" --deployed -o json | python3 -c '
import json, sys
rows = json.load(sys.stdin)
print(rows[0]["chart"] if rows else "")')" = "${chart#*/}-$version" ]; then
    echo "$release ${chart#*/}-$version is deployed with the values of $values"
    return
  fi
  "$HELM" repo add "${chart%%/*}" "$(repo_url "${chart%%/*}")" --force-update >/dev/null
  "$HELM" upgrade --install "$release" "$chart" --version "$version" --namespace "$namespace" --create-namespace \
    -f "$values" --wait
}
repo_url() {
  case $1 in
    jetstack) echo https://charts.jetstack.io ;;
    topolvm) echo https://topolvm.github.io/topolvm ;;
  esac
}

helm_install cert-manager cert-manager jetstack/cert-manager "$CERT_MANAGER_VERSION" cert-manager-values.yaml

# The TopoLVM webhook ignores these namespaces, as the TopoLVM install guide says.
kubectl create namespace topolvm-system --dry-run=client -o yaml | kubectl apply -f -
kubectl label namespace kube-system topolvm-system topolvm.io/webhook=ignore --overwrite
helm_install topolvm topolvm-system topolvm/topolvm "$TOPOLVM_CHART_VERSION" topolvm-values.yaml

kubectl get nodes -L storage.hoover/enrolled,storage.tier/hdd,storage.tier/nvme,cpu.hoover/avx2
kubectl get runtimeclass,storageclass
kubectl -n topolvm-system get pods -o wide
