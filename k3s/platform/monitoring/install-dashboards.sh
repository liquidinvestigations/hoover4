#!/usr/bin/env bash
# Install monitoring, logs and dashboards: kube-prometheus-stack, Loki, Alloy, Headlamp, the disk dashboard and the
# alarms of alarms.yaml. No service names a node. A service with data stays on the node of its volume.
# KUBECONFIG names the admin kubeconfig. The default is <state folder>/kubeconfig. HELM names the helm command.
set -euo pipefail
cd "$(dirname "$0")"
source_dir=$(realpath ../..)
private=$(python3 "$source_dir/settings.py" private)
export KUBECONFIG=${KUBECONFIG:-$private/kubeconfig}
helm=${HELM:-$private/bin/helm}
suffix=$(python3 "$source_dir/settings.py" suffix)
# values writes a values file with the suffix of the site into a temporary folder and prints its path.
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
values() { sed -e "s/hoover\.test/$suffix/g" "$1" > "$work/$1"; echo "$work/$1"; }
source ../helm-release.sh
for repo in prometheus-community=https://prometheus-community.github.io/helm-charts grafana=https://grafana.github.io/helm-charts \
  grafana-community=https://grafana-community.github.io/helm-charts headlamp=https://kubernetes-sigs.github.io/headlamp/; do
  "$helm" repo add --force-update "${repo%%=*}" "${repo#*=}" >/dev/null
done
"$helm" repo update >/dev/null
# Grafana uses the strategy Recreate (monitoring-values.yaml). A server-side apply cannot change an existing Deployment
# from RollingUpdate to Recreate, because the API server keeps the defaulted rollingUpdate field. This patch replaces it.
if [ "$(kubectl -n monitoring get deployment monitor-grafana -o jsonpath='{.spec.strategy.type}' --ignore-not-found)" = RollingUpdate ]; then
  kubectl -n monitoring patch deployment monitor-grafana --type json -p '[{"op":"replace","path":"/spec/strategy","value":{"type":"Recreate"}}]'
fi
# cpu_policy.py patches the CPU values, and Helm 4 applies on the server, so each upgrade takes those fields back.
# helm_release upgrades only a release whose chart version or values changed, so a second run restarts no pod.
helm_release "$helm" monitor monitoring prometheus-community/kube-prometheus-stack 92.10.1 "$(values monitoring-values.yaml)" --force-conflicts --timeout 8m
helm_release "$helm" loki monitoring grafana-community/loki 18.17.0 "$(values loki-values.yaml)" --force-conflicts --timeout 5m
helm_release "$helm" alloy monitoring grafana/alloy 1.13.1 alloy-values.yaml --force-conflicts --timeout 5m
# Headlamp uses this read-only account.
kubectl -n monitoring create serviceaccount cluster-viewer --dry-run=client -o yaml | kubectl apply -f -
kubectl create clusterrolebinding cluster-viewer --clusterrole=view --serviceaccount=monitoring:cluster-viewer --dry-run=client -o yaml | kubectl apply -f -
kubectl create clusterrole cluster-host-viewer --verb=get,list,watch --resource=nodes,namespaces,persistentvolumes,storageclasses,runtimeclasses --dry-run=client -o yaml | kubectl apply -f -
kubectl create clusterrolebinding cluster-host-viewer --clusterrole=cluster-host-viewer --serviceaccount=monitoring:cluster-viewer --dry-run=client -o yaml | kubectl apply -f -
helm_release "$helm" headlamp monitoring headlamp/headlamp 0.46.0 "$(values headlamp-values.yaml)" --force-conflicts --timeout 5m
# The Grafana sidecar loads each ConfigMap with the label grafana_dashboard=1.
kubectl -n monitoring create configmap dashboard-disk-io --from-file=disk-io.json=dashboard-disk-io.json --dry-run=client -o yaml | kubectl label --local -f - grafana_dashboard=1 -o yaml | kubectl apply -f -
kubectl apply -f alarms.yaml
# A Helm upgrade brings back the chart CPU values, so cpu_policy.py writes the policy values again.
python3 "$source_dir/zones/cpu_policy.py" monitoring
