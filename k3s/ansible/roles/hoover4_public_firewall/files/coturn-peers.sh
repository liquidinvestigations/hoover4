#!/bin/bash
# Limit the public media address of the media node for the coturn user. The role hoover4_public_firewall runs it as
# root on the media node of the call services when that node has a public address.
# coturn may relay to that address (../../../../platform/calls/turn_peers.py). No call service of the address needs a
# relay since the retirement of LiveKit, so the chain coturn_peers drops every packet of the coturn user to that
# address. Its hook runs before the DNAT of the host ports. The chain is in its own table, so it does not depend on the public interface or on
# public-firewall.sh, and it changes no traffic of another user. The calls step of the driver adds the public peer only
# after a probe shows this rule.
# Environment: HOOVER4_PUBLIC_IP, the public address of the node.
# The table loads at boot before the network. A second run writes nothing and restarts nothing.
# Usage: coturn-peers.sh [--dry-run]
set -euo pipefail
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
PUBLIC_IP=${HOOVER4_PUBLIC_IP:-}
[[ "$PUBLIC_IP" =~ ^[0-9A-Fa-f.:]+$ ]] || { echo "ERROR: HOOVER4_PUBLIC_IP names no address" >&2; exit 1; }
FAMILY=ip
[[ "$PUBLIC_IP" == *:* ]] && FAMILY=ip6
# The user id of coturn, COTURN_UID of ../../../../platform/calls/turn_peers.py.
COTURN_UID=64981
NFT_FILE=/etc/hoover-coturn-peers.nft
UNIT_FILE=/etc/systemd/system/hoover-coturn-peers.service
NFT_TEXT=$(cat <<EOF
# Written by coturn-peers.sh. The coturn user reaches no port of the public media address.
table inet hoover_coturn_peers
delete table inet hoover_coturn_peers
table inet hoover_coturn_peers {
  chain coturn_peers {
    type filter hook output priority raw; policy accept;
    meta skuid != $COTURN_UID accept
    $FAMILY daddr != $PUBLIC_IP accept
    counter drop comment "coturn relays to no port of the public address"
  }
}
EOF
)
UNIT_TEXT=$(cat <<'EOF'
[Unit]
Description=Limit the public media address for the coturn user
Before=network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f /etc/hoover-coturn-peers.nft

[Install]
WantedBy=multi-user.target
EOF
)
CHANGED=0
# write_file <path> <text>: write the text when the file differs. A dry run shows the difference.
write_file() {
  if [ -f "$1" ] && [ "$(cat "$1")" = "$2" ]; then
    echo "  $1 is current"
    return
  fi
  CHANGED=1
  echo "  write $1"
  diff <(cat "$1" 2>/dev/null) <(printf '%s\n' "$2") | sed 's/^/    /' || true
  [ "$DRY" = 1 ] || printf '%s\n' "$2" > "$1"
}
write_file "$NFT_FILE" "$NFT_TEXT"
write_file "$UNIT_FILE" "$UNIT_TEXT"
ENABLED=$(systemctl is-enabled hoover-coturn-peers.service 2>/dev/null || true)
LOADED=$(nft list table inet hoover_coturn_peers >/dev/null 2>&1 && echo yes || echo no)
if [ "$CHANGED" = 0 ] && [ "$ENABLED" = enabled ] && [ "$LOADED" = yes ]; then
  echo "  hoover-coturn-peers.service is enabled, and the table is loaded"
elif [ "$DRY" = 1 ]; then
  echo "  $ nft -c -f $NFT_FILE; systemctl daemon-reload; systemctl enable hoover-coturn-peers.service; nft -f $NFT_FILE"
else
  nft -c -f "$NFT_FILE"
  systemctl daemon-reload
  systemctl enable -q hoover-coturn-peers.service
  nft -f "$NFT_FILE"
fi
[ "$DRY" = 1 ] && echo "== dry run, no change made" || nft list table inet hoover_coturn_peers
