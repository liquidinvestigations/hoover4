#!/usr/bin/env bash
# Start the operator portal behind one login. Run ../monitoring/install-dashboards.sh first.
# KUBECONFIG names the admin kubeconfig. The default is k3s/private/kubeconfig.
set -euo pipefail
cd "$(dirname "$0")"
source_dir=$(realpath ../..)
private=$source_dir/private
export KUBECONFIG=${KUBECONFIG:-$private/kubeconfig}
for service in monitor-grafana headlamp monitor-kube-prometheus-st-prometheus; do
  kubectl -n monitoring get service "$service" >/dev/null
done
umask 077
login=$private/operator-login
mkdir -p "$login"
# The cookie secret must be 32 bytes. The existing files keep sessions valid across reinstalls.
[ -s "$login/client-secret" ] || python3 -c 'import secrets; print(secrets.token_hex(32), end="")' > "$login/client-secret"
[ -s "$login/cookie-secret" ] || python3 -c 'import secrets; print(secrets.token_hex(16), end="")' > "$login/cookie-secret"
# A host with public addresses keeps its own admin password in k3s/private/operator-login/admin-password. The manifest
# then gets the bcrypt hash of that password instead of the hash of the development password admin.
hash_rule=''
if [ -s "$login/admin-password" ]; then
  # Dex reads bcrypt hashes. caddy hash-password reads one line from stdin.
  hash=$(head -n 1 "$login/admin-password" | "$private/bin/caddy" hash-password --algorithm bcrypt)
  # cpu_policy.py prints JSON on one line, so the rule replaces the bcrypt value inside the Dex config string.
  hash_rule="s|hash: \\\$2[aby]\\\$[0-9][0-9]\\\$[./A-Za-z0-9]\\{53\\}|hash: ${hash}|"
fi
# cpu_policy.py writes the CPU policy values into the manifest.
python3 "$source_dir/zones/cpu_policy.py" --render operator-login.yaml | sed -e "s/hoover\.test/$(python3 "$source_dir/settings.py" suffix)/g" -e "$hash_rule" | kubectl apply -f -
kubectl -n operator-portal create secret generic operator-login --from-file="$login/client-secret" --from-file="$login/cookie-secret" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n operator-portal create configmap dex-templates --from-file=password.html=dex-password.html --dry-run=client -o yaml | kubectl apply -f -
kubectl -n operator-portal create configmap portal --from-file=portal-server.py --from-file=portal/index.html --dry-run=client -o yaml | kubectl apply -f -
kubectl -n operator-portal rollout restart deployment/dex deployment/gateway deployment/portal
kubectl -n operator-portal rollout status deployment/dex deployment/gateway deployment/portal --timeout=180s
# The inventory table shows every login with its password in clear text.
python3 "$source_dir/tools/write-password-table.py"
