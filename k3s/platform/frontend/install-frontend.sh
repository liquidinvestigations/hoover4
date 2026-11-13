#!/usr/bin/env bash
# Install or update the HTTPS frontend on the public host. Run it on the workstation.
# The frontend is Caddy as the systemd unit hoover-frontend. It ends TLS with the public wildcard certificate and sends
# plain HTTP to the fixed Service address of the cluster ingress. Each zone has a gate (frontend-sync.sh).
# The script installs Caddy, its unit, the certbot hook, frontend-sync.sh as /opt/hoover-frontend/sync and the site
# settings /opt/hoover-frontend/site.env. It then runs sync with the zones of zone-state.json.
# settings.json gives these values:
#   frontend_ssh       the SSH alias of the public host. The operator user there has sudo -n.
#   frontend_bind      the addresses where Caddy listens, for example the VPN address and the public address.
#   frontend_tls       the certificate folder on the public host with fullchain.pem and privkey.pem, a certbot live
#                      folder. systemd gives the files to the unit as credentials, so Caddy runs with no root.
#   frontend_dns_credentials  the certbot Cloudflare credentials file on the public host
#   vpn_cidr           the VPN network of the operators, for example 10.0.0.0/24
#   ingress_address    the Service address of the ingress (../ingress/install-ingress.sh).
# The cluster sources that pass without the gate are the pod range of each node and the VPN address of each node of
# hosts.json, because a pod request to another node leaves through wg0 with the address of its node.
# Pods reach the frontend at the first frontend_bind address: a CoreDNS block answers every name below the suffix with it.
# ./build-caddy.sh builds the Caddy binary with the WAF module. A second run with the same zones changes no file and
# restarts nothing.
# Usage: install-frontend.sh
set -euo pipefail
cd "$(dirname "$0")"
source_dir=$(realpath ../..)
private=$source_dir/private
export KUBECONFIG=${KUBECONFIG:-$private/kubeconfig}
get() { python3 "$source_dir/settings.py" get "$1" ''; }
ssh_host=$(get frontend_ssh)
tls_dir=$(get frontend_tls)
dns_credentials=$(get frontend_dns_credentials)
vpn=$(get vpn_cidr)
ingress=$(get ingress_address)
binds=$(python3 -c 'import sys,json;sys.path.insert(0,sys.argv[1]);import settings;print(" ".join(settings.FRONTEND_BIND))' "$source_dir")
[ -n "$ssh_host" ] && [ -n "$tls_dir" ] && [ -n "$dns_credentials" ] && [ -n "$vpn" ] && [ -n "$ingress" ] && [ -n "$binds" ] || {
  echo "settings.json needs frontend_ssh, frontend_tls, frontend_dns_credentials, vpn_cidr, frontend_bind and ingress_address" >&2; exit 1; }
first_bind=${binds%% *}
# zones.py writes the zone names and the domain suffix.
python3 "$source_dir/zones/zones.py" >/dev/null
source "$private/zones/frontend.env"
cluster=$(kubectl get nodes -o jsonpath='{range .items[*]}{.spec.podCIDR}{" "}{end}')
cluster+=$(python3 -c 'import json,sys;print(" ".join(h["wg_ip"] for h in json.load(open(sys.argv[1]))["hosts"].values()))' <(python3 "$source_dir/settings.py" hosts))
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
for name in binds ingress cluster vpn tls_dir dns_credentials suffix; do printf '%s=%q\n' "$name" "${!name}"; done > "$work/site.env"
printf 'extra_hosts=(%s)\n' "${extra_hosts[*]}" >> "$work/site.env"
printf '%s\n' "${zones[@]}" > "$work/zones"
cat > "$work/hoover-frontend.service" <<UNIT
[Unit]
Description=HTTPS frontend of the hoover zones
Wants=network-online.target
After=network-online.target wg-quick@wg0.service
[Service]
DynamicUser=yes
StateDirectory=hoover-frontend
Environment=HOME=/var/lib/hoover-frontend XDG_DATA_HOME=/var/lib/hoover-frontend XDG_CONFIG_HOME=/var/lib/hoover-frontend
LoadCredential=fullchain.pem:${tls_dir}/fullchain.pem
LoadCredential=privkey.pem:${tls_dir}/privkey.pem
ExecStart=/opt/hoover-frontend/caddy run --config /opt/hoover-frontend/Caddyfile --adapter caddyfile
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
UNIT
# certbot runs this deploy hook after each renewal. A restart loads the new credential files.
cat > "$work/hook" <<'HOOK'
#!/bin/sh
systemctl try-restart hoover-frontend.service
HOOK
cp "$private/bin/caddy" "$work/caddy"
cp frontend-sync.sh "$work/sync"
# The files go to a temporary folder of the operator user. The root step installs only a changed file. It restarts
# Caddy when its binary or its unit changed, and sync restarts it when the Caddyfile or the certificate changed.
# retry <input file> <command...>: sshd drops new connections before authentication when it holds MaxStartups unauthenticated ones,
# for example while the public host gets login attempts from the internet. ssh and scp then exit with 255 before the
# remote command starts, so the call starts again after a pause (../../driver/hostroute.py SSH_REFUSED).
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
retry /dev/null scp -q "$work/site.env" "$work/zones" "$work/hoover-frontend.service" "$work/hook" "$work/caddy" "$work/sync" "$ssh_host:$remote/"
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
put hook /etc/letsencrypt/renewal-hooks/deploy/hoover-frontend 0755
if [ -n "$changed" ]; then
  systemctl daemon-reload
  systemctl enable -q hoover-frontend.service
fi
/opt/hoover-frontend/sync < "$src/zones"
rm -rf "$src"
case "$changed" in *caddy*|*hoover-frontend.service*) systemctl restart hoover-frontend.service ;; esac
systemctl is-active -q hoover-frontend.service
echo "frontend files: changed:${changed:- nothing}"
ROOT
retry "$work/root.sh" ssh "$ssh_host" "sudo -n bash -s '$remote'"
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
