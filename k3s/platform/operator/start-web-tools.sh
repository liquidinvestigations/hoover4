#!/usr/bin/env bash
# Start the operator portal and the zone runner behind one login. Run ../monitoring/install-dashboards.sh and
# install-runner.sh first.
# KUBECONFIG names the admin kubeconfig. The default is kubeconfig of the state folder of the site file.
# OPERATOR_IMAGE names the operator image of the registry, OPERATOR_IMAGE_TAGS the tags of the Hoover images (JSON), and
# OPERATOR_REVISION the commit of the deployment. deploy-k3s sets them (step operator).
# A second run with the same inputs changes no object and restarts no pod. A Deployment restarts only when the
# configuration that its pods read at start changed (the annotation hoover.dev/config, set at the end).
set -euo pipefail
cd "$(dirname "$0")"
source_dir=$(realpath ../..)
private=$(python3 "$source_dir/settings.py" private)
export KUBECONFIG=${KUBECONFIG:-$private/kubeconfig}
for service in monitor-grafana headlamp monitor-kube-prometheus-st-prometheus; do
  kubectl -n monitoring get service "$service" >/dev/null
done
umask 077
login=$private/operator-login
# The operator login is the path site/operator-login of the secret store (../../secretstore.py). The files of
# operator-login/ of the state folder are copies, which this script reads. A missing value is generated once: the
# client and proxy secrets, the cookie secret of 32 bytes, and a random admin password, so no installation keeps the
# development password admin. A file of an earlier version gives its value to the store. The existing values keep
# sessions valid across reinstalls. A new proxy secret restarts the gateway and the portal together, because the
# portal hop of the gateway sends it to the portal with each request.
python3 "$source_dir/secretstore.py" files site/operator-login "$login" client-secret:hex32 cookie-secret:hex16 \
  proxy-secret:hex32 admin-password:urlsafe18 admin-password.bcrypt >/dev/null
hash_rule=''
if [ -s "$login/admin-password" ]; then
  # Dex reads bcrypt hashes. caddy hash-password reads one line from stdin. Each hash has a new salt, so the file
  # admin-password.bcrypt keeps the hash with the SHA-256 of the password, and a run with the same password reuses it.
  # Without this the Dex configuration would change on each run.
  password_digest=$(head -n 1 "$login/admin-password" | sha256sum | cut -d' ' -f1)
  hash=$(sed -n "s/^$password_digest //p" "$login/admin-password.bcrypt" 2>/dev/null || true)
  if [ -z "$hash" ]; then
    hash=$(head -n 1 "$login/admin-password" | "$private/bin/caddy" hash-password --algorithm bcrypt)
    printf '%s %s\n' "$password_digest" "$hash" > "$login/admin-password.bcrypt"
    # The new hash replaces the stored one on purpose, because it belongs to the stored password.
    python3 -c 'import sys;sys.path.insert(0,sys.argv[1]);import secretstore
secretstore.replace("site/operator-login",{"admin-password.bcrypt":open(sys.argv[2]).read()})' "$source_dir" "$login/admin-password.bcrypt"
  fi
  # cpu_policy.py prints JSON on one line, so the rule replaces the bcrypt value inside the Dex config string.
  hash_rule="s|hash: \\\$2[aby]\\\$[0-9][0-9]\\\$[./A-Za-z0-9]\\{53\\}|hash: ${hash}|"
fi
: "${OPERATOR_IMAGE:?OPERATOR_IMAGE names no operator image. Run deploy-k3s up --steps operator.}"
: "${OPERATOR_IMAGE_TAGS:?OPERATOR_IMAGE_TAGS names no image tags. Run deploy-k3s up --steps operator.}"
: "${OPERATOR_REVISION:?OPERATOR_REVISION names no commit. Run deploy-k3s up --steps operator.}"
# The pods read the commit of the deployment from this ConfigMap at their start, so a new commit restarts no pod.
kubectl get namespace operator-portal >/dev/null 2>&1 || kubectl create namespace operator-portal
kubectl -n operator-portal create configmap operator-revision --from-literal=revision="$OPERATOR_REVISION" --dry-run=client -o yaml | kubectl apply -f -
# cpu_policy.py writes the CPU policy values into the manifest.
# The operator pod runs on the control-plane node. backup-mount.py moves it to the backup node of the site file and
# mounts the backup folder there.
read -r control_plane single < <(python3 -c 'import sys;sys.path.insert(0,sys.argv[1]);import settings as s
print(s.SITE.control_plane, str(s.SITE.single).lower()) if s.SITE else print("- -")' "$source_dir")
[ "$control_plane" != - ] || { echo "the operator portal needs a site file. Set HOOVER4_SITE." >&2; exit 1; }
# The pods of a single-node site run below hoover4.slice (../../ansible/roles/hoover4_host/tasks/local.yml).
pod_cgroup=/sys/fs/cgroup/kubepods.slice
[ "$single" = true ] && pod_cgroup=/sys/fs/cgroup/hoover4.slice
# The node and image values go into the YAML first, so the numbers stay numbers in the JSON of cpu_policy.py.
# The tags go in first, because the name OPERATOR_IMAGE_TAGS starts with OPERATOR_IMAGE.
sed -e "s|value: OPERATOR_IMAGE_TAGS|value: '$OPERATOR_IMAGE_TAGS'|" \
  -e "s|CONTROL_PLANE|$control_plane|; s|POD_CGROUP|$pod_cgroup|; s|OPERATOR_IMAGE|$OPERATOR_IMAGE|" operator-login.yaml |
  python3 "$source_dir/zones/cpu_policy.py" --render - | python3 backup-mount.py | sed -e "s/hoover\.test/$(python3 "$source_dir/settings.py" suffix)/g" -e "$hash_rule" | kubectl apply -f -
# The one GPU key of the installation, which the portal shows and from which the GPU proxy derives the zone tokens.
python3 "$source_dir/hoover/gpu.py" ensure-key
kubectl -n operator-portal create secret generic operator-login --from-file="$login/client-secret" --from-file="$login/cookie-secret" --from-file="$login/proxy-secret" --dry-run=client -o yaml | kubectl apply -f -
# The portal reads the site file in its JSON form, because its Python image has no PyYAML.
python3 -c 'import sys;sys.path.insert(0,sys.argv[1]);import settings as s,config;print(config.dump(s.SITE),end="")' "$source_dir" |
  kubectl -n operator-portal create configmap portal-site --from-file=site.json=/dev/stdin --dry-run=client -o yaml | kubectl apply -f -
kubectl -n operator-portal create configmap dex-templates --from-file=password.html=dex-password.html --dry-run=client -o yaml | kubectl apply -f -
# The portal code is in the operator image. An earlier version kept it in this ConfigMap.
kubectl -n operator-portal delete configmap portal --ignore-not-found
python3 "$source_dir/platform/operator/config-digest.py"
# The first start of the operator pod pulls the operator image from the registry.
kubectl -n operator-portal rollout status deployment/dex deployment/gateway deployment/portal --timeout=600s
