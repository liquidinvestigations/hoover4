#!/usr/bin/env bash
# Install the image registry of the cluster and point every node at it.
# settings.json names the node in registry_node and the address and port in registry_endpoint, for example
# <VPN address of that node>:5000. The registry runs with runc, because it is a platform service and holds no zone data.
# The push password is k3s/private/registry-push-password. The script creates it once. It writes the podman
# credentials for build-image.sh to k3s/private/registry-auth.json.
# KUBECONFIG names the admin kubeconfig. The default is k3s/private/kubeconfig.
set -euo pipefail
# A relative KUBECONFIG path starts at the current folder, so it becomes absolute before the cd.
if [ -n "${KUBECONFIG:-}" ]; then KUBECONFIG=$(realpath "$KUBECONFIG"); fi
cd "$(dirname "$0")"
private=$(realpath ../../private)
export KUBECONFIG=${KUBECONFIG:-$private/kubeconfig}
endpoint=$(python3 ../../settings.py get registry_endpoint '')
node=$(python3 ../../settings.py get registry_node '')
[ -n "$endpoint" ] && [ -n "$node" ] || { echo "settings.json needs registry_endpoint and registry_node" >&2; exit 1; }
password_file=$private/registry-push-password
[ -s "$password_file" ] || (umask 077; openssl rand -hex 24 > "$password_file")
password=$(cat "$password_file")
# A salt from the password keeps the htpasswd line the same at each run, so a second run changes nothing.
salt=$(printf '%s' "$password" | sha256sum | cut -c1-8)
kubectl create namespace registry --dry-run=client -o yaml | kubectl apply -f -
printf 'push:%s\n' "$(printf '%s' "$password" | openssl passwd -apr1 -salt "$salt" -stdin)" |
  kubectl -n registry create secret generic registry-push --from-file=htpasswd=/dev/stdin --dry-run=client -o yaml | kubectl apply -f -
(umask 077; printf '{"auths": {"%s": {"auth": "%s"}}}\n' "$endpoint" "$(printf 'push:%s' "$password" | base64 -w0)" > "$private/registry-auth.json")
# The hash of this file restarts the pod when the nginx configuration changes.
hash=$(sha256sum registry.yaml | cut -c1-16)
# A claim spec does not change after its creation. A new claim gets the default storage class of the site. After that,
# the field manager owns the class that the API set, so a later apply without the class would clear it, and the API
# refuses that. The manifest therefore names the class of an existing claim, including an adopted one.
class=$(kubectl -n registry get pvc registry-data -o jsonpath='{.spec.storageClassName}' 2>/dev/null || true)
class_rule=''
[ -z "$class" ] || class_rule="s|^  # The default storage class of the site.*|  storageClassName: $class|"
sed -e "s/NODE/$node/; s/HOST_IP/${endpoint%:*}/; s/CONFIG_HASH/$hash/" -e "$class_rule" registry.yaml |
  kubectl apply --server-side --force-conflicts --field-manager=hoover4-registry -f -
kubectl -n registry rollout status deployment/registry --timeout=300s
python3 node-registries.py
