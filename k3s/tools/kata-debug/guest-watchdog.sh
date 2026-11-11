#!/bin/sh
# Runs in a Kata guest, started through the agent debug console. It moves itself to its own cgroup, so a freeze of
# the agent or container cgroups does not stop it. Every 2 s it writes the agent thread states, the frozen cgroups,
# and the stack of each task in uninterruptible sleep to the guest kernel log with the prefix hooverwd. The host reads
# those lines from the guest memory after the agent stops answering, so the guest needs no working agent for them.
# The guest needs debug_console_enabled in the runtime configuration. Start it with guest-console.py and a script that
# sets /proc/sys/kernel/printk_devkmsg to on, writes this file to /run/hooverwd.sh, and runs it with setsid in the
# background. Read the lines with guest-memory-lines.py watchdog <sandbox id>.
mkdir -p /sys/fs/cgroup/hooverwd
echo $$ > /sys/fs/cgroup/hooverwd/cgroup.procs
n=0
while sleep 2; do
  n=$((n + 1))
  agent=$(pidof kata-agent)
  states=$(for task in /proc/$agent/task/*; do sed -n 's/^State:\t\(.\).*/\1/p' $task/status; done | sort | uniq -c | tr -s ' \n' ' ')
  frozen=$(for f in $(find /sys/fs/cgroup -name cgroup.freeze); do [ "$(cat $f)" = 1 ] && echo -n "${f%/cgroup.freeze} "; done)
  echo "hooverwd $n agent=$agent states=[$states] frozen=[$frozen]" > /dev/kmsg
  for stat in /proc/[0-9]*/task/[0-9]*/stat; do
    state=$(cut -d')' -f2 "$stat" 2>/dev/null | cut -d' ' -f2)
    [ "$state" = D ] || continue
    task=${stat%/stat}
    echo "hooverwd $n D $task $(cat $task/comm) $(cat $task/stack 2>/dev/null | sed 's/^\[<0>\] //' | cut -d+ -f1 | tr '\n' ' ')" > /dev/kmsg
  done
  # A frozen agent thread waits in the freezer, so its stack shows where the freeze caught it.
  for task in /proc/$agent/task/*; do
    wchan=$(cat $task/wchan)
    case $wchan in *futex_wait*|*ep_poll*|*epoll_wait*|0) continue ;; esac
    echo "hooverwd $n A ${task##*/} $(cat $task/comm) $wchan $(cat $task/stack 2>/dev/null | sed 's/^\[<0>\] //' | cut -d+ -f1 | tr '\n' ' ')" > /dev/kmsg
  done
done
