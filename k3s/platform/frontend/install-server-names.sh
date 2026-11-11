#!/usr/bin/env bash
# Let the workstation reach the zone names through the HTTPS frontend over the VPN, before public DNS points there.
# It writes the names of each zone into the marked block hoover-zones of /etc/hosts, with the first frontend_bind
# address of settings.json. --remove deletes the block. Local sudo -n writes the file. A second run changes nothing.
# Usage: install-server-names.sh [--remove]
set -euo pipefail
cd "$(dirname "$0")"
source_dir=$(realpath ../..)
private=$source_dir/private
current=$(sed '/^# BEGIN hoover-zones$/,/^# END hoover-zones$/d' /etc/hosts)
if [ "${1:-}" = --remove ]; then
  wanted=$current
else
  python3 "$source_dir/zones/zones.py" >/dev/null
  source "$private/zones/frontend.env"
  address=$(python3 -c 'import sys;sys.path.insert(0,sys.argv[1]);import settings;print(settings.FRONTEND_BIND[0])' "$source_dir")
  names=("${extra_hosts[@]}")
  for zone in "${zones[@]}"; do
    names+=("${zone}.${suffix}" "hoover.${zone}.${suffix}")
    for host in "${hosts[@]}"; do names+=("${host}.${zone}.${suffix}"); done
  done
  wanted=$(printf '%s\n# BEGIN hoover-zones\n' "$current"; for name in "${names[@]}"; do printf '%s %s\n' "$address" "$name"; done; echo '# END hoover-zones')
fi
if [ "$wanted" = "$(cat /etc/hosts)" ]; then echo "/etc/hosts is current"; exit 0; fi
printf '%s\n' "$wanted" | sudo -n tee /etc/hosts.hoover-zones >/dev/null
sudo -n install -m 644 /etc/hosts.hoover-zones /etc/hosts
sudo -n rm -f /etc/hosts.hoover-zones
echo "wrote /etc/hosts"
