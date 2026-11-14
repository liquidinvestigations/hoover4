#!/usr/bin/env bash
# Install or update the HTTPS frontend on the public host. Run it on the workstation.
# The frontend is Caddy as the systemd unit hoover-frontend. It ends TLS and sends plain HTTP to the fixed Service
# address of the cluster ingress. Each zone has a gate (frontend-sync.sh). The frontend names no zone, so a zone add or
# delete needs no run of this script.
# The script installs Caddy, its unit, frontend-sync.sh as /opt/hoover-frontend/sync and the site settings
# /opt/hoover-frontend/site.env. It then runs sync.
# The TLS mode is tls_mode of the public node in the site file (../../config.py TLS_MODES):
#   cloudflare  the certbot live folder /etc/letsencrypt/live/<suffix> with the public certificate of *.<suffix>, and
#               the certbot Cloudflare credentials file tls_dns_credentials_file. The script also installs the certbot hook.
#   files       the certificate and key files tls_certificate_file and tls_key_file on the public host.
#   internal    Caddy issues the certificates from its local CA. The script copies the root certificate of that CA into
#               frontend/local-ca.crt of the state folder. The pods trust it (config.local_ca()), and the person installs
#               it in each browser that opens the site.
# With cloudflare and files, systemd gives the certificate files to the unit as credentials, so Caddy runs with no root.
# Other values: the SSH destination of the public node, the admin ranges (the cidr of each network and LAN of the site
# file, config.admin_ranges(), which reach the admin routes), the bind addresses (the node address and the public
# address of the public node) and the Service address of the ingress (../ingress/install-ingress.sh). The SSH user on
# the public host needs sudo -n.
# The cluster sources that pass without the gate are the pod range of each node and the node address of each node of
# hosts.json, because a pod request to another node leaves with the address of its node.
# Pods reach the frontend at the first bind address: a CoreDNS block answers every name below the suffix with it.
# ./build-caddy.sh builds the Caddy binary with the WAF module. A second run changes no file and restarts nothing.
# Usage: install-frontend.sh
set -euo pipefail
cd "$(dirname "$0")"
source_dir=$(realpath ../..)
private=$(python3 "$source_dir/settings.py" private)
export KUBECONFIG=${KUBECONFIG:-$private/kubeconfig}
get() { python3 "$source_dir/settings.py" get "$1" ''; }
ssh_host=$(get frontend_ssh)
tls_mode=$(get frontend_tls_mode)
tls_dir=$(get frontend_tls)
tls_certificate=$(get frontend_tls_certificate)
tls_key=$(get frontend_tls_key)
dns_credentials=$(get frontend_dns_credentials)
vpn=$(python3 "$source_dir/settings.py" get admin_ranges '[]' | python3 -c 'import json,sys;print(" ".join(json.load(sys.stdin)))')
ingress=$(get ingress_address)
binds=$(python3 -c 'import sys,json;sys.path.insert(0,sys.argv[1]);import settings;print(" ".join(settings.FRONTEND_BIND))' "$source_dir")
# config.py check refuses a site file without these values, so a missing one means a site file that the check did not
# read. Each message names the site file key.
problems=()
[ -n "$ssh_host" ] || problems+=("settings.py gives no frontend_ssh")
[ -n "$vpn" ] || problems+=("vars has no networks and no lans with a cidr, so no range reaches the admin routes")
[ -n "$binds" ] || problems+=("the public node has no node address and no public_address")
[ -n "$ingress" ] || problems+=("settings.py gives no ingress_address")
case "$tls_mode" in
  cloudflare) [ -n "$dns_credentials" ] || problems+=("the public node has tls_mode = cloudflare and no tls_dns_credentials_file") ;;
  files) [ -n "$tls_certificate" ] && [ -n "$tls_key" ] || problems+=("the public node has tls_mode = files and no tls_certificate_file or tls_key_file") ;;
  internal) ;;
  *) problems+=("the public node has no tls_mode of cloudflare, internal or files") ;;
esac
if [ ${#problems[@]} -gt 0 ]; then
  printf 'install-frontend.sh: %s.\n' "${problems[@]}" >&2
  echo "Correct the site file, and check it with: python3 k3s/config.py check <site file>" >&2
  exit 1
fi
first_bind=${binds%% *}
suffix=$(get suffix)
# The operator portal has its own login (../operator/).
extra_hosts=("operator.${suffix}")
cluster=$(kubectl get nodes -o jsonpath='{range .items[*]}{.spec.podCIDR}{" "}{end}')
cluster+=$(python3 -c 'import json,sys;print(" ".join(h["node_ip"] for h in json.load(open(sys.argv[1]))["hosts"].values()))' <(python3 "$source_dir/settings.py" hosts))
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
for name in binds ingress cluster vpn tls_mode tls_dir tls_certificate tls_key dns_credentials suffix; do printf '%s=%q\n' "$name" "${!name}"; done > "$work/site.env"
printf 'extra_hosts=(%s)\n' "${extra_hosts[*]}" >> "$work/site.env"
# The certificate files of cloudflare and files reach the unit as credentials. internal keeps its CA in the state folder
# of the unit.
credentials=''
if [ "$tls_mode" != internal ]; then
  credentials="LoadCredential=fullchain.pem:${tls_certificate}
LoadCredential=privkey.pem:${tls_key}"
fi
cat > "$work/hoover-frontend.service" <<UNIT
[Unit]
Description=HTTPS frontend of the hoover zones
Wants=network-online.target
After=network-online.target wg-quick@wg0.service
[Service]
DynamicUser=yes
StateDirectory=hoover-frontend
Environment=HOME=/var/lib/hoover-frontend XDG_DATA_HOME=/var/lib/hoover-frontend XDG_CONFIG_HOME=/var/lib/hoover-frontend
${credentials}
ExecStart=/opt/hoover-frontend/caddy run --config /opt/hoover-frontend/Caddyfile --adapter caddyfile
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
UNIT
cp "$private/bin/caddy" "$work/caddy"
cp frontend-sync.sh "$work/sync"
files=(site.env hoover-frontend.service caddy sync)
if [ "$tls_mode" = cloudflare ]; then
  # certbot runs this deploy hook after each renewal. A restart loads the new credential files.
  cat > "$work/hook" <<'HOOK'
#!/bin/sh
systemctl try-restart hoover-frontend.service
HOOK
  files+=(hook)
fi
# The files go to a temporary folder of the operator user. The root step installs only a changed file. It restarts
# Caddy when its binary or its unit changed, and sync restarts it when the Caddyfile or the certificate changed.
# retry <input file> <command...>: sshd drops new connections before authentication when it holds MaxStartups unauthenticated ones,
# for example while the public host gets login attempts from the internet. ssh and scp then exit with 255 before the
# remote command starts, so the call starts again after a pause.
# Each attempt opens the input file again, so a second attempt reads it from the start.
retry() {
  local input=$1 attempt rc err
  shift
  err=$(mktemp)
  for attempt in 1 2 3 4 5; do
    rc=0
    "$@" <"$input" 2>"$err" || rc=$?
    if [ "$rc" -ne 255 ] || ! grep -qE 'kex_exchange_identification|Connection closed by|Connection reset by' "$err" || [ "$attempt" -eq 5 ]; then
      cat "$err" >&2; rm -f "$err"; return "$rc"
    fi
    sleep 6
  done
}
remote=$(retry /dev/null ssh "$ssh_host" mktemp -d)
retry /dev/null scp -q "${files[@]/#/$work/}" "$ssh_host:$remote/"
cat > "$work/root.sh" <<'ROOT'
set -euo pipefail
src=$1 changed=''
put() { # put <file> <target> <mode>
  if ! cmp -s "$src/$1" "$2"; then install -D -m "$3" "$src/$1" "$2"; changed="$changed $1"; fi
}
put caddy /opt/hoover-frontend/caddy 0755
put sync /opt/hoover-frontend/sync 0755
put site.env /opt/hoover-frontend/site.env 0644
put hoover-frontend.service /etc/systemd/system/hoover-frontend.service 0644
[ ! -f "$src/hook" ] || put hook /etc/letsencrypt/renewal-hooks/deploy/hoover-frontend 0755
# The files of tls_mode files must exist before the unit starts, because systemd refuses a missing credential file.
. "$src/site.env"
if [ "$tls_mode" = files ]; then
  for file in "$tls_certificate" "$tls_key"; do
    [ -s "$file" ] || { echo "the certificate file $file of tls_mode = files is missing on $(hostname)" >&2; exit 1; }
  done
fi
if [ -n "$changed" ]; then
  systemctl daemon-reload
  systemctl enable -q hoover-frontend.service
fi
/opt/hoover-frontend/sync
rm -rf "$src"
case "$changed" in *caddy*|*hoover-frontend.service*) systemctl restart hoover-frontend.service ;; esac
systemctl is-active -q hoover-frontend.service
echo "frontend files: changed:${changed:- nothing}"
ROOT
retry "$work/root.sh" ssh "$ssh_host" "sudo -n bash -s '$remote'"
if [ "$tls_mode" = internal ]; then
  # Caddy writes the root certificate of its local CA at its first start, in the state folder of the unit.
  root=/var/lib/hoover-frontend/pki/authorities/local/root.crt
  retry /dev/null ssh "$ssh_host" "sudo -n sh -c 'for i in \$(seq 60); do [ -s $root ] && break; sleep 1; done; cat $root'" > "$work/local-ca.crt" ||
    { echo "$root is missing on the public host. Check: journalctl -u hoover-frontend" >&2; exit 1; }
  python3 -c 'import ssl,sys;ssl.PEM_cert_to_DER_cert(open(sys.argv[1]).read())' "$work/local-ca.crt" ||
    { echo "$root on the public host is no PEM certificate" >&2; exit 1; }
  mkdir -p "$private/frontend"
  cmp -s "$work/local-ca.crt" "$private/frontend/local-ca.crt" || install -m 0644 "$work/local-ca.crt" "$private/frontend/local-ca.crt"
  echo "local CA: $private/frontend/local-ca.crt. Install this file as a trusted certificate authority in each browser that opens the site."
fi
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
