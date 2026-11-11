#!/bin/bash
# Allow only key logins on the SSH server of a host. Run it as root on each host.
# The settings turn off password logins, root logins and X11 forwarding. sshd uses the first value that it reads,
# so the file name sorts before the other files in sshd_config.d.
# A changed file starts a timer that removes the file again after 180 seconds. Test a key login from a new connection,
# then run the script with --confirm, which stops the timer. Without --confirm the host returns to the earlier state.
# A second run writes nothing and reloads nothing.
# Usage: root-install-sshd.sh [--dry-run | --confirm]
set -euo pipefail
MODE=${1:-}
CONF=/etc/ssh/sshd_config.d/00-hoover.conf
TIMER=hoover-sshd-rollback
UNIT=$(systemctl list-unit-files ssh.service >/dev/null 2>&1 && echo ssh || echo sshd)
if [ "$MODE" = --confirm ]; then
  systemctl stop "$TIMER.timer" 2>/dev/null || true
  echo "  the rollback timer is stopped"
  exit 0
fi
TEXT='# Written by root-install-sshd.sh. Only key logins are allowed.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
X11Forwarding no'
grep -qE '^\s*Include\s+/etc/ssh/sshd_config.d/' /etc/ssh/sshd_config \
  || { echo "ERROR: /etc/ssh/sshd_config does not include sshd_config.d" >&2; exit 1; }
if [ -f "$CONF" ] && [ "$(cat "$CONF")" = "$TEXT" ]; then
  echo "  $CONF is current"
elif [ "$MODE" = --dry-run ]; then
  echo "  write $CONF"
  diff <(cat "$CONF" 2>/dev/null) <(printf '%s\n' "$TEXT") | sed 's/^/    /' || true
  echo "  $ systemctl reload $UNIT, then a rollback timer of 180 seconds"
else
  printf '%s\n' "$TEXT" > "$CONF"
  sshd -t || { rm -f "$CONF"; echo "ERROR: sshd refused the settings, and the file is removed" >&2; exit 1; }
  systemctl stop "$TIMER.timer" 2>/dev/null || true
  systemctl reset-failed "$TIMER.service" 2>/dev/null || true
  systemd-run --quiet --unit "$TIMER" --on-active=180 /bin/sh -c "rm -f $CONF && systemctl reload $UNIT"
  systemctl reload "$UNIT"
  echo "  reloaded. Test a key login from a new connection, then run: $0 --confirm"
fi
[ "$MODE" = --dry-run ] && echo "== dry run, no change made"
sshd -T | grep -E '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin|x11forwarding) '
