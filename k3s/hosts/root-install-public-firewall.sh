#!/bin/bash
# Admit only the allowed ports on the public interface of the public host. Run it as root on that host.
# Allowed: SSH, HTTP and HTTPS (TCP and UDP 443) of the frontend, TURN (UDP and TCP 3478) and the direct media ports of
# the call services (UDP 10000 of the JVB, TCP 7881 and UDP 7882 of LiveKit), and WireGuard (UDP 42069). A separate
# calls node runs the same script. ../platform/calls/public_endpoints.py firewall prints the ports of each node. Answers to connections of the host and ICMP also pass. The table drops every other packet that
# enters on the public interface. The drop rules of root-install-public-guard.sh stay, and its table runs first.
# On a node with the public address of the call services, the chain coturn_peers lets the coturn user reach that address
# only on the LiveKit media ports, because coturn may relay to it (../platform/calls/turn_peers.py). Its hook runs
# before the DNAT of the host ports. Run this script before the calls step of the driver.
# The table loads at boot before the network. A second run writes nothing and restarts nothing.
# A changed table starts a timer that removes the table again after 180 seconds. Test SSH from a new connection, then
# run the script with --confirm, which stops the timer. Without --confirm the host returns to the earlier state.
# Usage: root-install-public-firewall.sh [--dry-run | --confirm]
set -euo pipefail
MODE=${1:-}
PUBLIC_IF=$(ip route show default | awk '{print $5; exit}')
[ -n "$PUBLIC_IF" ] && [ "$PUBLIC_IF" != wg0 ] || { echo "ERROR: no public interface found" >&2; exit 1; }
PUBLIC_IP=$(ip -4 -o addr show dev "$PUBLIC_IF" scope global | awk '{split($4, a, "/"); print a[1]; exit}')
[ -n "$PUBLIC_IP" ] || { echo "ERROR: $PUBLIC_IF has no global IPv4 address" >&2; exit 1; }
# The user id of coturn, COTURN_UID of ../platform/calls/turn_peers.py.
COTURN_UID=64981
NFT_FILE=/etc/hoover-public-firewall.nft
UNIT_FILE=/etc/systemd/system/hoover-public-firewall.service
TIMER=hoover-public-firewall-rollback
if [ "$MODE" = --confirm ]; then
  systemctl stop "$TIMER.timer" 2>/dev/null || true
  systemctl enable -q hoover-public-firewall.service
  echo "  the rollback timer is stopped, and the table loads at boot"
  exit 0
fi
NFT_TEXT=$(cat <<EOF
# Written by root-install-public-firewall.sh. Only the allowed ports pass on the public interface.
table inet hoover_public_firewall
delete table inet hoover_public_firewall
table inet hoover_public_firewall {
  chain input {
    type filter hook input priority -5; policy accept;
    iifname != "$PUBLIC_IF" accept
    ct state established,related accept
    meta l4proto { icmp, ipv6-icmp } accept
    tcp dport { 22, 80, 443 } accept comment "SSH and the HTTPS frontend"
    udp dport 443 accept comment "HTTP/3 of the frontend"
    meta l4proto { tcp, udp } th dport 3478 accept comment "TURN of the call services"
    udp dport { 7882, 10000 } accept comment "direct media of LiveKit and the JVB"
    tcp dport 7881 accept comment "LiveKit media over TCP"
    udp dport 42069 accept comment "WireGuard"
    counter drop
  }
  chain coturn_peers {
    type filter hook output priority raw; policy accept;
    meta skuid != $COTURN_UID accept
    ip daddr != $PUBLIC_IP accept
    udp dport 7882 accept comment "LiveKit media"
    tcp dport 7881 accept comment "LiveKit media over TCP"
    counter drop comment "coturn relays to no other port of the public address"
  }
}
EOF
)
UNIT_TEXT=$(cat <<'EOF'
[Unit]
Description=Admit only the allowed ports on the public interface
Before=network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f /etc/hoover-public-firewall.nft

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
  [ "$MODE" = --dry-run ] || printf '%s\n' "$2" > "$1"
}
write_file "$NFT_FILE" "$NFT_TEXT"
write_file "$UNIT_FILE" "$UNIT_TEXT"
LOADED=$(nft list table inet hoover_public_firewall >/dev/null 2>&1 && echo yes || echo no)
if [ "$CHANGED" = 0 ] && [ "$LOADED" = yes ]; then
  echo "  the table is loaded"
elif [ "$MODE" = --dry-run ]; then
  echo "  $ nft -f $NFT_FILE, then a rollback timer of 180 seconds"
else
  nft -c -f "$NFT_FILE"
  systemctl daemon-reload
  # The unit stays disabled until --confirm, so a reboot also returns to the earlier state.
  systemctl disable -q hoover-public-firewall.service 2>/dev/null || true
  systemctl stop "$TIMER.timer" 2>/dev/null || true
  systemctl reset-failed "$TIMER.service" 2>/dev/null || true
  systemd-run --quiet --unit "$TIMER" --on-active=180 /usr/sbin/nft delete table inet hoover_public_firewall
  nft -f "$NFT_FILE"
  echo "  loaded. Test SSH from a new connection, then run: $0 --confirm"
fi
[ "$MODE" = --dry-run ] && echo "== dry run, no change made" || nft list table inet hoover_public_firewall
