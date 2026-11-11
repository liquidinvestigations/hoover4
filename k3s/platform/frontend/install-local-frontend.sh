#!/usr/bin/env bash
# Write the HTTPS frontend of the local node of a single-node site. Run it as the operator user. ../../deploy-k3s runs it.
# Caddy runs as the unit hoover4-frontend (../../hosts/root-install-local.py, step frontend) with the files of
# k3s/private/frontend: site.env, the Caddyfile of frontend-sync.sh, and the data folder of the local CA.
# Caddy listens on the node address of the site file. It ends TLS with certificates of its local CA and sends plain HTTP
# to the Service address of the cluster ingress. The gates and the WAF are those of the remote frontend.
# The zones are the zones of the Hoover installations of the site file. The site file also gives the operator name.
# A CoreDNS block answers every name below the suffix with the node address, so pods reach the frontend too.
# Usage: install-local-frontend.sh          write site.env and the Caddyfile, and reload a running Caddy
#        install-local-frontend.sh --ca     copy the root certificate of the local CA to k3s/private/frontend/local-ca.crt
set -euo pipefail
cd "$(dirname "$0")"
source_dir=$(realpath ../..)
private=$source_dir/private
folder=$private/frontend
export KUBECONFIG=${KUBECONFIG:-$private/kubeconfig}
get() { python3 "$source_dir/settings.py" get "$1" ''; }
umask 077
mkdir -p "$folder/data"
if [ "${1:-}" = --ca ]; then
  root=$folder/data/pki/authorities/local/root.crt
  # Caddy writes the root certificate of its local CA at its first start.
  for _ in $(seq 60); do [ -s "$root" ] && break; sleep 1; done
  [ -s "$root" ] || { echo "$root is missing. Check: journalctl -u hoover4-frontend" >&2; exit 1; }
  install -m 0644 "$root" "$folder/local-ca.crt"
  echo "local CA: $folder/local-ca.crt"
  # Chromium and Firefox read their own NSS stores. The system store gets the CA from root-install-local.py (trust).
  name="Hoover4 local site CA"
  mkdir -p "$HOME/.pki/nssdb"
  [ -f "$HOME/.pki/nssdb/cert9.db" ] || certutil -d "sql:$HOME/.pki/nssdb" -N --empty-password
  { find "$HOME/.pki" "$HOME/.mozilla" "$HOME/.config/mozilla" -name cert9.db 2>/dev/null || true; } | while read -r db; do
    certutil -d "sql:$(dirname "$db")" -D -n "$name" 2>/dev/null || true
    certutil -d "sql:$(dirname "$db")" -A -t C,, -n "$name" -i "$folder/local-ca.crt"
    echo "trusted in $(dirname "$db")"
  done
  exit 0
fi
[ "$(get frontend_local)" = true ] || { echo "the HTTPS frontend of this site is not on the local node" >&2; exit 1; }
suffix=$(get suffix)
binds=$(python3 -c 'import sys;sys.path.insert(0,sys.argv[1]);import settings;print(" ".join(settings.FRONTEND_BIND))' "$source_dir")
first_bind=${binds%% *}
ingress=$(get ingress_address)
zones=$(python3 -c 'import sys;sys.path.insert(0,sys.argv[1]);import settings;print("\n".join(sorted({h.zone for h in settings.SITE.hoovers.values()})))' "$source_dir")
# The pods of the node and the node itself pass without the gate, as on a remote site.
cluster="$(kubectl get nodes -o jsonpath='{range .items[*]}{.spec.podCIDR}{" "}{end}' 2>/dev/null || true)${first_bind}/32"
vpn=${first_bind}/32
tls_dir='' dns_credentials='' tls_mode=internal
extra_hosts=("operator.${suffix}")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
for name in binds ingress cluster vpn tls_dir dns_credentials suffix tls_mode; do printf '%s=%q\n' "$name" "${!name}"; done > "$work/site.env"
printf 'extra_hosts=(%s)\n' "${extra_hosts[*]}" >> "$work/site.env"
cmp -s "$work/site.env" "$folder/site.env" || install -m 0644 "$work/site.env" "$folder/site.env"
ln -sfn "$private/bin/caddy" "$folder/caddy"
printf '%s\n' "$zones" | HOOVER_FRONTEND_DIR=$folder bash frontend-sync.sh
# Zone names resolve to the frontend inside the cluster. k3s CoreDNS imports the *.server keys of coredns-custom.
before=$(kubectl -n kube-system get configmap coredns-custom -o jsonpath='{.data.zones\.server}' 2>/dev/null || true)
dns="${suffix}:53 {
  errors
  template IN A ${suffix} {
    answer \"{{ .Name }} 60 IN A ${first_bind}\"
  }
  template IN AAAA ${suffix} {
    rcode NOERROR
  }
}"
if [ "$before" != "$dns" ]; then
  kubectl -n kube-system create configmap coredns-custom --from-literal="zones.server=$dns" --dry-run=client -o yaml | kubectl apply -f -
  # The CoreDNS reload plugin does not detect changes in imported files.
  kubectl -n kube-system rollout restart deployment/coredns
  kubectl -n kube-system rollout status deployment/coredns --timeout=120s
  echo "coredns: changed"
else
  echo "coredns: current"
fi
