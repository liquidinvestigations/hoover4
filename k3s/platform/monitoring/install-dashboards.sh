#!/usr/bin/env bash
# Install monitoring, logs and dashboards: kube-prometheus-stack, Loki, Alloy, Headlamp, the disk dashboard and the
# alarms of alarms.yaml. The services with data run on the server node of k3s/private/hosts.json.
# KUBECONFIG names the admin kubeconfig. The default is k3s/private/kubeconfig. HELM names the helm command.
set -euo pipefail
cd "$(dirname "$0")"
source_dir=$(realpath ../..)
private=$source_dir/private
export KUBECONFIG=${KUBECONFIG:-$private/kubeconfig}
helm=${HELM:-$private/bin/helm}
suffix=$(python3 "$source_dir/settings.py" suffix)
node=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["server"])' "$private/hosts.json")
values() { sed -e "s/hoover\.test/$suffix/g" -e "s/MONITOR_NODE/$node/g" "$1"; }
for repo in prometheus-community=https://prometheus-community.github.io/helm-charts grafana=https://grafana.github.io/helm-charts \
  grafana-community=https://grafana-community.github.io/helm-charts headlamp=https://kubernetes-sigs.github.io/headlamp/; do
  "$helm" repo add --force-update "${repo%%=*}" "${repo#*=}" >/dev/null
done
"$helm" repo update >/dev/null
# cpu_policy.py patches the CPU values, and Helm 4 applies on the server, so each upgrade takes those fields back.
"$helm" upgrade --install --force-conflicts monitor prometheus-community/kube-prometheus-stack --version 92.10.1 --namespace monitoring --create-namespace -f <(values monitoring-values.yaml) --timeout 8m
"$helm" upgrade --install --force-conflicts loki grafana-community/loki --version 18.17.0 --namespace monitoring -f <(values loki-values.yaml) --timeout 5m
"$helm" upgrade --install --force-conflicts alloy grafana/alloy --version 1.13.1 --namespace monitoring -f alloy-values.yaml --timeout 5m
# Headlamp uses this read-only account.
kubectl -n monitoring create serviceaccount cluster-viewer --dry-run=client -o yaml | kubectl apply -f -
kubectl create clusterrolebinding cluster-viewer --clusterrole=view --serviceaccount=monitoring:cluster-viewer --dry-run=client -o yaml | kubectl apply -f -
kubectl create clusterrole cluster-host-viewer --verb=get,list,watch --resource=nodes,namespaces,persistentvolumes,storageclasses,runtimeclasses --dry-run=client -o yaml | kubectl apply -f -
kubectl create clusterrolebinding cluster-host-viewer --clusterrole=cluster-host-viewer --serviceaccount=monitoring:cluster-viewer --dry-run=client -o yaml | kubectl apply -f -
"$helm" upgrade --install --force-conflicts headlamp headlamp/headlamp --version 0.46.0 --namespace monitoring -f <(values headlamp-values.yaml) --timeout 5m
# The Grafana sidecar loads each ConfigMap with the label grafana_dashboard=1.
kubectl -n monitoring create configmap dashboard-disk-io --from-file=disk-io.json=dashboard-disk-io.json --dry-run=client -o yaml | kubectl label --local -f - grafana_dashboard=1 -o yaml | kubectl apply -f -
kubectl apply -f alarms.yaml
# A Helm upgrade brings back the chart CPU values, so cpu_policy.py writes the policy values again.
python3 "$source_dir/zones/cpu_policy.py" monitoring
