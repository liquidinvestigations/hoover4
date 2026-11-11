#!/bin/bash
# Drop the k3s node ports on the public interface of the public host. Run it as root on that host.
# The provider firewall in front of the host passes these ports. The cluster uses them over wg0 only.
# Flannel VXLAN (UDP 8472) takes packets from any address, so a public packet could enter the pod network.
# The table loads at boot before k3s-agent. A second run writes nothing and restarts nothing.
# Usage: root-install-public-guard.sh [--dry-run]. --dry-run shows the changes and changes nothing.
set -euo pipefail
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
PUBLIC_IF=$(ip route show default | awk '{print $5; exit}')
[ -n "$PUBLIC_IF" ] && [ "$PUBLIC_IF" != wg0 ] || { echo "ERROR: no public interface found" >&2; exit 1; }
NFT_FILE=/etc/k3s-public-guard.nft
UNIT_FILE=/etc/systemd/system/k3s-public-guard.service
NFT_TEXT=$(cat <<EOF
# Written by root-install-public-guard.sh. The k3s node ports are for wg0 and the pod network only.
table inet k3s_public_guard
delete table inet k3s_public_guard
table inet k3s_public_guard {
  chain input {
    type filter hook input priority -10; policy accept;
    iifname "$PUBLIC_IF" udp dport 8472 counter drop comment "flannel VXLAN"
    iifname "$PUBLIC_IF" tcp dport { 10250, 10256 } counter drop comment "kubelet and kube-proxy"
    iifname "$PUBLIC_IF" meta l4proto { tcp, udp } th dport 30000-32767 counter drop comment "NodePorts"
  }
}
EOF
)
UNIT_TEXT=$(cat <<'EOF'
[Unit]
Description=Drop the k3s node ports on the public interface
Before=k3s-agent.service network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f /etc/k3s-public-guard.nft

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
ENABLED=$(systemctl is-enabled k3s-public-guard.service 2>/dev/null || true)
ACTIVE=$(systemctl is-active k3s-public-guard.service 2>/dev/null || true)
LOADED=$(nft list table inet k3s_public_guard >/dev/null 2>&1 && echo yes || echo no)
if [ "$CHANGED" = 0 ] && [ "$ENABLED" = enabled ] && [ "$ACTIVE" = active ] && [ "$LOADED" = yes ]; then
  echo "  k3s-public-guard.service is enabled and active, and the table is loaded"
elif [ "$DRY" = 1 ]; then
  echo "  $ systemctl daemon-reload; systemctl enable k3s-public-guard.service; systemctl restart k3s-public-guard.service"
else
  systemctl daemon-reload
  systemctl enable k3s-public-guard.service
  systemctl restart k3s-public-guard.service
fi
[ "$DRY" = 1 ] && echo "== dry run, no change made" || nft list table inet k3s_public_guard
