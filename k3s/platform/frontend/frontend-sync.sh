#!/bin/bash
# Write the Caddyfile of the HTTPS frontend for the zones on standard input, one zone name in each line, and restart
# Caddy when the file or the certificate changed. It runs as root on the public host as /opt/hoover-frontend/sync.
# install-frontend.sh installs it with the site settings /opt/hoover-frontend/site.env and runs it with the zones of
# zone-state.json. The zone runner of the operator portal runs it through an SSH key that can run only this script,
# so a zone name is the only input from the runner. The script refuses any other name.
# Each zone has a gate. A request passes to the ingress only in one of these cases:
#   - it comes from a pod or a node of the cluster (cluster in site.env),
#   - it is on a route that passes without the gate (open below). The Coraza WAF with the OWASP Core Rule Set then
#     checks it and refuses an attack pattern with 403,
#   - the gate oauth2-proxy of the zone (../../zones/gate.py) accepts its cookie at auth.<zone>.<suffix>/oauth2/auth.
# A page load without a gate cookie goes to the Keycloak sign-in of the zone. Any other request gets 401.
# The Keycloak admin routes and the admin routes of Synapse and lk-jwt answer 403 outside the VPN (vpn in site.env).
# When the certificate lacks the name *.<zone>.<suffix> of a zone, certbot adds it with the DNS challenge. The list
# replaces the names of a deleted zone at that time. A second run with the same zones changes nothing.
set -euo pipefail
here=/opt/hoover-frontend
source "$here/site.env"
zones=()
while read -r zone; do
  [ -n "$zone" ] || continue
  [[ $zone =~ ^zone-[a-z0-9]{1,12}$ ]] || { echo "refused zone name" >&2; exit 1; }
  zones+=("$zone")
done
credentials=/run/credentials/hoover-frontend.service
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
{
cat <<CADDY
{
	admin off
	# Without a limit Caddy waits for every open websocket before it stops, so a restart could take minutes.
	grace_period 5s
	storage file_system /var/lib/hoover-frontend
	skip_install_trust
	default_bind ${binds}
}
(upstream) {
	reverse_proxy ${ingress}:80 {
		flush_interval -1
	}
}
# The WAF checks the routes that pass without the gate. The rule set refuses a request with an attack pattern (403).
# Large chat media uploads are checked only in their first part. The sign-in arguments state, rd and redirect_uri hold
# a return address, for example a wiki path with /bin/, so the command injection rules do not read them.
(waf) {
	coraza_waf {
		load_owasp_crs
		directives \`
			Include @coraza.conf-recommended
			Include @crs-setup.conf.example
			Include @owasp_crs/*.conf
			SecRuleUpdateTargetByTag attack-rce "!ARGS:state|!ARGS:rd|!ARGS:redirect_uri"
			SecRuleEngine On
			SecRequestBodyLimitAction ProcessPartial
			SecResponseBodyAccess Off
			SecAuditEngine Off
		\`
	}
}
# The gate of one zone. The argument is the zone domain <zone>.<suffix>.
(gate) {
	tls ${credentials}/fullchain.pem ${credentials}/privkey.pem
	@cluster remote_ip ${cluster}
	@admin {
		not remote_ip ${vpn}
		expression \`(host('id.{args[0]}') && path('/admin', '/admin/*', '/realms/master', '/realms/master/*')) || (host('matrix.{args[0]}') && path('/_synapse/admin/*')) || (host('mrtc.{args[0]}') && path('/sfu_webhook*'))\`
	}
	# The routes of the sign-in, of the chat and call clients with their own tokens, and of preflights pass without the gate.
	@open expression \`method('OPTIONS') || path('/.well-known/*', '/robots.txt') || host('auth.{args[0]}', 'mas.{args[0]}', 'sfu.{args[0]}') || (host('id.{args[0]}') && path('/realms/opendesk/*', '/resources/*', '/fingerprintjs*', '/opendesk-static-files/*')) || (host('matrix.{args[0]}') && path('/_matrix/client/*', '/_matrix/media/*')) || (host('mrtc.{args[0]}') && path('/sfu/get*', '/get_token*', '/delegate_delayed_leave*'))\`
	@page header Accept *text/html*
	@other not header Accept *text/html*
	# Caddy runs the handlers of one route in the written order. The first handler that answers ends the request.
	route {
		route @cluster {
			import upstream
		}
		respond @admin 403
		route @open {
			import waf
			import upstream
		}
		forward_auth @page ${ingress}:80 {
			uri /oauth2/auth
			header_up Host auth.{args[0]}
			# The sign-in starts at the gate. The gate sends the browser back to this address afterwards.
			@signin status 401
			handle_response @signin {
				reverse_proxy ${ingress}:80 {
					rewrite /oauth2/start
					header_up Host auth.{args[0]}
					header_up X-Auth-Request-Redirect {scheme}://{host}{uri}
				}
			}
		}
		forward_auth @other ${ingress}:80 {
			uri /oauth2/auth
			header_up Host auth.{args[0]}
		}
		import upstream
	}
}
CADDY
for zone in "${zones[@]}"; do
  printf '%s, *.%s {\n\timport gate %s\n}\n' "${zone}.${suffix}" "${zone}.${suffix}" "${zone}.${suffix}"
done
# The operator portal has its own login (../operator/).
for host in "${extra_hosts[@]}"; do
  printf '%s {\n\ttls %s/fullchain.pem %s/privkey.pem\n\timport upstream\n}\n' "$host" "$credentials" "$credentials"
done
} > "$work/Caddyfile"
"$here/caddy" adapt --config "$work/Caddyfile" --adapter caddyfile >/dev/null
names=("*.${suffix}")
for zone in "${zones[@]}"; do names+=("*.${zone}.${suffix}"); done
changed=''
have=$(openssl x509 -in "$tls_dir/fullchain.pem" -noout -ext subjectAltName | tr -d ' ' | tr ',' '\n' | sed -n 's/^DNS://p')
# The certificate gets a new zone name, and it loses the name of a deleted zone.
missing=$(printf '%s\n' "${names[@]}" | grep -vxF -f <(printf '%s\n' "$have") || true)
deleted=$(printf '%s\n' "$have" | grep -xE "\*\.zone-[a-z0-9]{1,12}\.${suffix//./\\.}" | grep -vxF -f <(printf '%s\n' "${names[@]}") || true)
if [ -n "$missing$deleted" ]; then
  domains=()
  for name in "${names[@]}"; do domains+=(-d "$name"); done
  certbot certonly --non-interactive --quiet --cert-name "$(basename "$tls_dir")" --expand --key-type ecdsa --dns-cloudflare \
    --dns-cloudflare-credentials "$dns_credentials" --dns-cloudflare-propagation-seconds 30 "${domains[@]}"
  changed="$changed certificate"
fi
if ! cmp -s "$work/Caddyfile" "$here/Caddyfile"; then
  install -m 0644 "$work/Caddyfile" "$here/Caddyfile"
  changed="$changed Caddyfile"
fi
# The admin API is off, so a restart loads the new file. systemd reads the certificate files at the start.
if [ -n "$changed" ] && systemctl is-enabled -q hoover-frontend.service; then systemctl restart hoover-frontend.service; fi
echo "frontend: zones ${zones[*]:-none}, changed:${changed:- nothing}"
