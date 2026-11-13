#!/bin/bash
# Set up the cluster on the k3s nodes: node labels, RuntimeClasses, cert-manager and TopoLVM.
# Run it on a host with kubectl, helm, python3 and the admin kubeconfig. A second run changes nothing.
# KUBECONFIG names the admin kubeconfig. The default is k3s/private/kubeconfig.
# The site file (settings.py) gives the storage tiers and the AVX2 flag of each node.
# HELM names the helm command. The default is k3s/private/bin/helm, else helm.
set -euo pipefail
# A relative KUBECONFIG path starts at the current folder, so it becomes absolute before the cd.
if [ -n "${KUBECONFIG:-}" ]; then KUBECONFIG=$(realpath "$KUBECONFIG"); fi
cd "$(dirname "$0")"
PRIVATE=$(realpath ../private)
export KUBECONFIG=${KUBECONFIG:-$PRIVATE/kubeconfig}
# SITE names a hosts.json file. Without it, settings.py writes the hosts.json form of the site file.
if [ -z "${SITE:-}" ]; then SITE=$(mktemp); python3 ../settings.py hosts > "$SITE"; fi
if [ -z "${HELM:-}" ]; then
  if [ -x "$PRIVATE/bin/helm" ]; then HELM=$PRIVATE/bin/helm; else HELM=helm; fi
fi
CERT_MANAGER_VERSION=v1.21.3
TOPOLVM_CHART_VERSION=17.3.0

# A node of the site file joins the cluster in its own root step, for example a GPU node that waits for its bootstrap.
# A node that has not joined gets its labels at the first run after it joins.
joined=" $(kubectl get nodes -o jsonpath='{.items[*].metadata.name}') "
label_node() {
  local node=$1; shift
  if [[ "$joined" == *" $node "* ]]; then
    kubectl label node "$node" "$@" --overwrite
  else
    echo "node $node has not joined the cluster. It gets its labels at the first run after it joins."
  fi
}

# A node with a storage tier is enrolled for stateful pods. The tier labels select the lvmd configuration.
# A node without AVX2 has no cpu.hoover/avx2 label. Workloads that need AVX2 select this label.
python3 - "$SITE" <<'PY' | while read -r node labels; do label_node "$node" $labels; done
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
# The lvmd label selects the lvmd configuration of the volume group of each node (topolvm_values.py).
python3 topolvm_values.py "$SITE" labels | while read -r node label; do label_node "$node" "$label"; done
values=$(mktemp --suffix=.json)
python3 topolvm_values.py "$SITE" > "$values"

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
helm_install topolvm topolvm-system topolvm/topolvm "$TOPOLVM_CHART_VERSION" "$values"

kubectl get nodes -L storage.hoover/enrolled,storage.hoover/lvmd,cpu.hoover/avx2
kubectl get runtimeclass,storageclass
kubectl -n topolvm-system get pods -o wide
