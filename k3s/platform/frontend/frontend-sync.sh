#!/bin/bash
# Write the Caddyfile of the HTTPS frontend and restart Caddy when the file or the certificate changed. It runs as root
# on the public host as /opt/hoover-frontend/sync. install-frontend.sh installs it with the site settings
# /opt/hoover-frontend/site.env and runs it. The file names no zone, so a zone add or delete changes nothing here.
# Every zone host is <zone>-<app>.<suffix> (../../config.py zone_host()), and the zone domain <zone>.<suffix> has the same
# rules. The one site *.<suffix> serves them all. Its matcher takes the zone id from the host name,
# and the frontend asks the gate of that zone. Another name below the suffix gets 404, except the extra hosts of site.env.
# A request passes to the ingress only in one of these cases:
#   - it comes from a pod or a node of the cluster (cluster in site.env),
#   - it is on a route that passes without the gate (open below). The Coraza WAF with the OWASP Core Rule Set then
#     checks it and refuses an attack pattern with 403,
#   - the gate oauth2-proxy of the zone (../../zones/gate.py) accepts its cookie at <zone>-auth.<suffix>/oauth2/auth.
# A page load without a gate cookie goes to the Keycloak sign-in of the zone. Any other request gets 401.
# The gate cookies have the domain .<suffix>, so a browser sends the gate cookies of every zone to each host. The gate
# of a zone reads only its own cookie. The applications get their requests without the gate cookies.
# The Keycloak admin routes answer 403 outside the admin ranges of the site file (vpn in site.env).
# site.env names the TLS mode (tls_mode, ../../config.py TLS_MODES). The certificate holds *.<suffix>:
#   cloudflare  certbot holds a public certificate for *.<suffix> and <suffix> in tls_dir. When the certificate lacks
#               one of them, or holds a name *.<zone>.<suffix> of the earlier zone names, certbot issues it again with
#               the DNS challenge.
#   files       the person supplies tls_certificate and tls_key. A certificate without *.<suffix> stops the script. A
#               changed certificate file restarts Caddy.
#   internal    Caddy issues the certificates from its local CA. Its root certificate is pki/authorities/local/root.crt
#               of the Caddy storage, which install-frontend.sh copies into the state folder.
# An earlier site.env without tls_mode is cloudflare. systemd gives the certificate files of cloudflare and files to the
# unit as credentials, so Caddy runs with no root. A second run changes nothing.
# On the local node of a single-node site, install-local-frontend.sh runs this script as the operator user with
# HOOVER_FRONTEND_DIR=frontend of the state folder and tls_mode=internal in site.env. Caddy then keeps its storage in
# that folder and its admin API on 127.0.0.1:2029 for a reload.
set -euo pipefail
here=${HOOVER_FRONTEND_DIR:-/opt/hoover-frontend}
source "$here/site.env"
tls_mode=${tls_mode:-cloudflare}
case "$tls_mode" in
  internal) tls_line='tls internal' ;;
  cloudflare|files) tls_line="tls /run/credentials/hoover-frontend.service/fullchain.pem /run/credentials/hoover-frontend.service/privkey.pem" ;;
  *) echo "site.env has the unknown tls_mode $tls_mode" >&2; exit 1 ;;
esac
[[ $suffix =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || { echo "site.env has the invalid suffix $suffix" >&2; exit 1; }
if [ -n "${HOOVER_FRONTEND_DIR:-}" ]; then
  globals="admin 127.0.0.1:2029
	local_certs
	storage file_system ${here}/data"
else
  globals="admin off
	storage file_system /var/lib/hoover-frontend"
  [ "$tls_mode" = internal ] && globals="$globals
	local_certs"
fi
# The host patterns of the zones. Each dot of the suffix is [.] in the regular expressions.
dots=${suffix//./[.]}
zone="zone-[a-z0-9]{1,12}"
# app <labels>: a CEL condition that is true on the hosts of these applications of any zone, for example app 'id'.
app() { printf "{http.request.host}.matches('^%s-(%s)[.]%s\$')" "$zone" "$1" "$dots"; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
{
cat <<CADDY
{
	${globals}
	# Without a limit Caddy waits for every open websocket before it stops, so a restart could take minutes.
	grace_period 5s
	skip_install_trust
	default_bind ${binds}
}
(upstream) {
	reverse_proxy ${ingress}:80 {
		flush_interval -1
	}
}
# The requests to the applications of a zone carry no gate cookie of any zone.
(app) {
	reverse_proxy ${ingress}:80 {
		flush_interval -1
		header_up Cookie "_hoover_gate_[^=;]*=[^;]*(; *)?" ""
	}
}
# The WAF checks the routes that pass without the gate. The rule set refuses a request with an attack pattern (403).
# A large request body is checked only in its first part. The sign-in arguments state, rd and redirect_uri hold
# a return address, for example a wiki path with /bin/, so the command injection and file access rules do not read
# them. On a domain that ends with .local, the file access rules match .local/bin/ of a wiki address.
(waf) {
	coraza_waf {
		load_owasp_crs
		directives \`
			Include @coraza.conf-recommended
			Include @crs-setup.conf.example
			Include @owasp_crs/*.conf
			SecRuleUpdateTargetByTag attack-rce "!ARGS:state|!ARGS:rd|!ARGS:redirect_uri"
			SecRuleUpdateTargetByTag attack-lfi "!ARGS:state|!ARGS:rd|!ARGS:redirect_uri"
			SecRuleEngine On
			SecRequestBodyLimitAction ProcessPartial
			SecResponseBodyAccess Off
			SecAuditEngine Off
		\`
	}
}
# Every zone host and zone domain. The matcher zone gives the zone id of the host as {re.zone.1}.
*.${suffix} {
	${tls_line}
	@zone vars_regexp zone {http.request.host} ^(${zone})(-[a-z0-9-]+)?[.]${dots}\$
	@cluster remote_ip ${cluster}
	@admin {
		not remote_ip ${vpn}
		expression \`$(app id) && path('/admin', '/admin/*', '/realms/master', '/realms/master/*')\`
	}
	# The gate answers its own sign-in routes with the cookies of the browser.
	@gate expression \`$(app auth)\`
	# The well-known routes and the preflights pass without the gate.
	# The Keycloak sign-in page of a zone loads its style sheets and images from the portal host before any gate cookie exists.
	@open expression \`method('OPTIONS') || path('/.well-known/*', '/robots.txt') || ($(app id) && path('/realms/opendesk/*', '/resources/*', '/fingerprintjs*', '/opendesk-static-files/*')) || ($(app portal) && path('/univention/theme.css', '/univention/portal/css/*', '/opendesk-static-files/*', '/favicon.ico'))\`
	@page header Accept *text/html*
	@other not header Accept *text/html*
	# Caddy runs the handlers of one route in the written order. The first handler that answers ends the request.
	handle @zone {
		route {
			route @cluster {
				import upstream
			}
			respond @admin 403
			route @gate {
				import waf
				import upstream
			}
			route @open {
				import waf
				import app
			}
			forward_auth @page ${ingress}:80 {
				uri /oauth2/auth
				header_up Host {re.zone.1}-auth.${suffix}
				# The sign-in starts at the gate. The gate sends the browser back to this address afterwards.
				@signin status 401
				handle_response @signin {
					reverse_proxy ${ingress}:80 {
						rewrite /oauth2/start
						header_up Host {re.zone.1}-auth.${suffix}
						header_up X-Auth-Request-Redirect {scheme}://{host}{uri}
					}
				}
			}
			forward_auth @other ${ingress}:80 {
				uri /oauth2/auth
				header_up Host {re.zone.1}-auth.${suffix}
			}
			import app
		}
	}
	handle {
		respond 404
	}
}
CADDY
# The operator portal has its own login (../operator/).
for host in "${extra_hosts[@]}"; do
  printf '%s {\n\t%s\n\timport upstream\n}\n' "$host" "$tls_line"
done
} > "$work/Caddyfile"
"$here/caddy" adapt --config "$work/Caddyfile" --adapter caddyfile >/dev/null
if [ -n "${HOOVER_FRONTEND_DIR:-}" ]; then
  if ! cmp -s "$work/Caddyfile" "$here/Caddyfile"; then
    install -m 0644 "$work/Caddyfile" "$here/Caddyfile"
    # A running frontend loads the file through its admin API. A stopped frontend reads it at its start.
    "$here/caddy" reload --config "$here/Caddyfile" --adapter caddyfile --address 127.0.0.1:2029 2>/dev/null || true
    echo "frontend: changed: Caddyfile"
  else
    echo "frontend: changed: nothing"
  fi
  exit 0
fi
changed=''
# certificate_names <file>: the DNS names of the certificate, one in each line.
certificate_names() { openssl x509 -in "$1" -noout -ext subjectAltName | tr -d ' ' | tr ',' '\n' | sed -n 's/^DNS://p'; }
if [ "$tls_mode" = cloudflare ]; then
  names=("*.${suffix}" "${suffix}")
  have=$(certificate_names "$tls_dir/fullchain.pem")
  missing=$(printf '%s\n' "${names[@]}" | grep -vxF -f <(printf '%s\n' "$have") || true)
  # The zone names of the earlier form *.<zone>.<suffix> leave the certificate.
  earlier=$(printf '%s\n' "$have" | grep -xE "\*\.zone-[a-z0-9]{1,12}\.${suffix//./\\.}" || true)
  if [ -n "$missing$earlier" ]; then
    domains=()
    for name in "${names[@]}"; do domains+=(-d "$name"); done
    certbot certonly --non-interactive --quiet --cert-name "$(basename "$tls_dir")" --expand --key-type ecdsa --dns-cloudflare \
      --dns-cloudflare-credentials "$dns_credentials" --dns-cloudflare-propagation-seconds 30 "${domains[@]}"
    changed="$changed certificate"
  fi
elif [ "$tls_mode" = files ]; then
  if ! certificate_names "$tls_certificate" | grep -qxF "*.${suffix}"; then
    echo "the certificate $tls_certificate lacks the name *.${suffix}. Replace it with a certificate that has it." >&2
    exit 1
  fi
  digest=$(cat "$tls_certificate" "$tls_key" | sha256sum | cut -d' ' -f1)
  if [ "$digest" != "$(cat "$here/certificate.sha256" 2>/dev/null || true)" ]; then
    echo "$digest" > "$here/certificate.sha256"
    changed="$changed certificate"
  fi
fi
if ! cmp -s "$work/Caddyfile" "$here/Caddyfile"; then
  install -m 0644 "$work/Caddyfile" "$here/Caddyfile"
  changed="$changed Caddyfile"
fi
# The admin API is off, so a restart loads the new file. systemd reads the certificate files at the start.
if [ -n "$changed" ] && systemctl is-enabled -q hoover-frontend.service; then systemctl restart hoover-frontend.service; fi
echo "frontend: changed:${changed:- nothing}"
