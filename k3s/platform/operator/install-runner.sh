#!/usr/bin/env bash
# Prepare the rights of the zone runner. Usage: install-runner.sh
# The runner (runner.py) is a container of the operator pod, which start-web-tools.sh starts. It uses the token of the
# ServiceAccount zone-runner, the Secret zone-runner-token, which the pod mounts.
# The script applies the runner rights (runner-rights.yaml) and the zone pod policy (../../zones/manifests/zone-pods.yaml)
# with the admin kubeconfig, because the runner cannot change the policy. It writes the runner kubeconfig
# operator-runner/kubeconfig of the state folder for ../../tools/runner-scope-check.py.
# The runner needs no SSH key and no access to a host. Run ../calls/install-calls.py first, because the rights name
# the namespace calls. A second run changes nothing.
set -euo pipefail
source_dir=$(cd "$(dirname "$0")/../.." && pwd)
private=$(python3 "$source_dir/settings.py" private)
export KUBECONFIG=${KUBECONFIG:-$private/kubeconfig}
folder=$private/operator-runner
mkdir -p "$folder"
chmod 700 "$folder"
# The rights name these namespaces. The calls, the zones and the stores step of deploy-k3s up fill them later, and a
# single-node site keeps hoover-data empty.
# The script creates only a missing namespace. An apply over an existing one would replace the last applied
# configuration of its own manifest, and the next kubectl diff of the runner would then send an update of the
# namespace, which the policy zone-runner-scope refuses.
for namespace in operator-portal calls hoover-data extensions hoover-stores; do
  kubectl get namespace "$namespace" >/dev/null 2>&1 || kubectl create namespace "$namespace"
done
kubectl apply -f "$source_dir/platform/operator/runner-rights.yaml"
(cd "$source_dir/zones" && python3 -c 'import zone; zone.cluster()')
token=''
for _ in $(seq 30); do
  token=$(kubectl -n operator-portal get secret zone-runner-token -o jsonpath='{.data.token}' | base64 -d)
  [ -n "$token" ] && break
  sleep 1
done
[ -n "$token" ] || { echo "the token of zone-runner is missing" >&2; exit 1; }
server=$(kubectl config view --minify --raw -o jsonpath='{.clusters[0].cluster.server}')
ca=$(kubectl config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')
(umask 077; cat > "$folder/kubeconfig.new" <<KUBECONFIG
apiVersion: v1
kind: Config
clusters: [{name: cluster, cluster: {server: "$server", certificate-authority-data: "$ca"}}]
users: [{name: zone-runner, user: {token: "$token"}}]
contexts: [{name: zone-runner, context: {cluster: cluster, user: zone-runner}}]
current-context: zone-runner
KUBECONFIG
)
mv "$folder/kubeconfig.new" "$folder/kubeconfig"
