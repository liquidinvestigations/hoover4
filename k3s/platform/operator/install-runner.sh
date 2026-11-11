#!/usr/bin/env bash
# Install the zone runner of the operator portal on the operator host. Usage: install-runner.sh
# The runner (runner.py) runs as a systemd user service of the operator user, because the private installation files
# and podman belong to that user. Lingering keeps it running without a login session.
# The script applies the runner rights (runner-rights.yaml) and the zone pod policy (../../zones/manifests/zone-pods.yaml)
# with the admin kubeconfig, because the runner cannot change the policy. It writes the runner kubeconfig
# k3s/private/operator-runner/kubeconfig with the token of the ServiceAccount zone-runner.
# It makes the SSH key k3s/private/operator-runner/ssh-key once. On the public host the key may run only
# /opt/hoover-frontend/sync as root (../frontend/frontend-sync.sh). Run ../frontend/install-frontend.sh and
# ../calls/install-calls.py first, because the rights name the namespace calls and the sync script.
# A second run changes nothing and restarts the runner.
set -euo pipefail
source_dir=$(cd "$(dirname "$0")/../.." && pwd)
private=$source_dir/private
export KUBECONFIG=${KUBECONFIG:-$private/kubeconfig}
folder=$private/operator-runner
mkdir -p "$folder"
chmod 700 "$folder"
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
[ -s "$folder/ssh-key" ] || ssh-keygen -q -t ed25519 -N '' -C hoover-zone-runner -f "$folder/ssh-key"
ssh_host=$(python3 "$source_dir/settings.py" get frontend_ssh '')
line="restrict,command=\"sudo -n /opt/hoover-frontend/sync\" $(cat "$folder/ssh-key.pub")"
ssh "$ssh_host" "grep -qxF '$line' ~/.ssh/authorized_keys || echo '$line' >> ~/.ssh/authorized_keys"
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/hoover-operator.service <<UNIT
[Unit]
Description=Hoover zone runner
[Service]
WorkingDirectory=${source_dir}
Environment=KUBECONFIG=${folder}/kubeconfig
ExecStart=/usr/bin/python3 ${source_dir}/platform/operator/runner.py
Restart=always
RestartSec=10
[Install]
WantedBy=default.target
UNIT
sudo -n loginctl enable-linger "$(id -un)"
systemctl --user daemon-reload
systemctl --user enable -q hoover-operator
systemctl --user restart hoover-operator
systemctl --user --no-pager status hoover-operator | head -3
