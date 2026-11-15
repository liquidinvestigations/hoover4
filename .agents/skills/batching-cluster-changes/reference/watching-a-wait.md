# Watching a wait

Set up the watch before you start the wait. A watch exits or emits a line at the first result, failure or stall,
and the harness then wakes the agent. The agent does not poll by hand and does not wait idle for an exit that a
stalled job never sends. Take the limits from [expected durations](expected-durations.md).

## Where the information is

`<state>` is the state folder of the site: the path of the site file without its extension.

| Information | Source | Read it with |
|---|---|---|
| Progress of `deploy-k3s up` and `down` | `<state>/operator/deploy/records/<id>.json`: steps with `state`, `started`, `finished`, `error` | [k3s/tools/watch-record.py](../../../../k3s/tools/watch-record.py), `deploy-k3s status` |
| Output of each step | `<state>/operator/deploy/logs/<id>.log` | `rg` for `FAILED`, `fatal`, `Error`. The size grows while a step works. |
| Zone create and delete from the portal | `<state>/operations/op-<time>-<action>-zone-<zone>.log` | `tail`, size growth |
| Pods that are not ready, with reasons and Warning events | the cluster API | [k3s/tools/sweep.py](../../../../k3s/tools/sweep.py) `<namespace>... [--wait SECONDS]` in the operator image |
| Requested and allocatable CPU and memory per node | the cluster API | `kubectl describe node <node>`, section "Allocated resources" |
| Pod CPU over time | Prometheus in namespace `monitoring` (`container_cpu_usage_seconds_total`) | `kubectl get --raw` on the Prometheus service proxy, as [k3s/zones/cpu_requests.py](../../../../k3s/zones/cpu_requests.py) does |
| Pod logs of a node | Loki, fed by Alloy from `/var/log/pods` | Grafana, or `kubectl logs` for one pod |
| Node load and CPU pressure | `/proc/loadavg`, `/proc/pressure/cpu` and `/proc/pressure/io` on the node | `ssh <node>` with the access in `INFRASTRUCTURE_INVENTORY.md` |
| CPU of the pods against the runtime | `cpu.stat` of `/sys/fs/cgroup/kubepods.slice` and of `system.slice/k3s.service` or `k3s-agent.service` | two reads 30 s apart. The difference of `usage_usec` divided by the interval gives the cores. |
| k3s and containerd on a node | `journalctl -u k3s` or `-u k3s-agent`, and `/var/lib/rancher/k3s/agent/containerd/containerd.log` | `sudo -n` on the node. The containerd log is in the time zone of the node. |
| Compose deploy | the log path that `deploy-logged.sh` prints | `rg` in the file |
| Compose services | the containers of the local runtime | `podman ps`, `podman logs --since 10m <name>` |
| A process that waits | the process list of the machine that runs it | `ps -eo pid,etimes,args`. `etimes` is the age in seconds. |

The k3s tools need `kubectl` and the site settings. Run them in the operator image with the checkout mounted read-only
and the state folder mounted read-write, with `HOOVER4_SITE` set to the site file and `KUBECONFIG` to
`<state>/kubeconfig`. `podman images localhost/hoover4-operator` names the current tag.

## How to get woken up

The Claude Code harness wakes the agent in two ways.

1. **One result.** Run a command with `run_in_background: true` that exits at the first result, failure or stall.
   The harness sends one notification when it exits. Use this for one deploy record or one rollout.

   ```
   python3 k3s/tools/watch-record.py <state> --stall 300 --deadline 3600
   ```

   It prints each step change and exits with 0 (complete), 1 (error), 2 (stall), 3 (a step over its limit) or 4
   (deadline). For pods, `sweep.py <namespace>... --wait 600` exits at all ready, at a state that waiting does not
   repair (including a pod that the scheduler cannot place for 2 minutes), or at the deadline.

2. **One event for each line.** Run the same command with the `Monitor` tool. Each output line is one notification,
   so each step change wakes the agent. Set `timeout_ms` to the deadline, at most 30 minutes, and start the monitor
   again after it expires. The command must also print on a stall, else silence looks like progress.

Start the watch in the same turn as the job. Then do independent work, or end the turn. When the notification
arrives, read the line, then the source of the table above for the detail.

A delegating agent watches the work of its subagent the same way. The record and log files are in the shared state
folder, so the organizer starts `watch-record.py` on the newest record with `Monitor` while the subagent works. A
notification that a subagent waits on its own background work tells nothing about progress.

Do not:

- block a turn with `sleep` or a loop that polls in the foreground.
- read a subagent transcript to follow its progress.
- start a watch that emits only on success.
