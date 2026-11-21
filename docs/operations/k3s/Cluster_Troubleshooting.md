# Find the cause of a site failure

The k3s installation is experimental.

This manual names the known failures of a site of `k3s/deploy-k3s`, the command that shows each one, and the action.
[The operations manual](Cluster_Operations.md) describes the daily tasks, and [the recovery manual](Cluster_Recovery.md) describes the restore of lost data.
[The cluster deployment reference](../../../k3s/Readme.md) describes each command in detail.

## Contents

- [A step of deploy-k3s failed](#a-step-of-deploy-k3s-failed)
- [Another operation holds the site lock](#another-operation-holds-the-site-lock)
- [An incomplete reset blocks every command](#an-incomplete-reset-blocks-every-command)
- [Pods do not start](#pods-do-not-start)
- [A pod waits for memory or for a node](#a-pod-waits-for-memory-or-for-a-node)
- [A volume group is full](#a-volume-group-is-full)
- [An alarm is active](#an-alarm-is-active)
- [A Kata guest does not answer](#a-kata-guest-does-not-answer)

## A step of deploy-k3s failed

A failed step ends the run. The record keeps the finished steps.

1. Print the records and read the step that failed:

   ```sh
   k3s/deploy-k3s status --site <site file>
   k3s/deploy-k3s status <record> --site <site file>
   ```

2. Read the log of the step. A failed Ansible play names the nodes of its failed tasks, and the log holds the output of each task.
3. Correct the cause, then continue the run at the first unfinished step:

   ```sh
   k3s/deploy-k3s up --resume <record> --site <site file>
   ```

`--resume` refuses a changed site file, another commit and another cluster. Start a new run after such a change.

## Another operation holds the site lock

`deploy-k3s`, the settings Apply, the zone operations, the Compose import, the backups and the restores take one site lock.
A second operation waits or stops with the name of the holder.
When the cluster answers, the lock is the Lease `site-operation` in the namespace `operator-portal`.

```sh
kubectl -n operator-portal get lease site-operation -o yaml
```

The holder renews the Lease every 20 seconds. A Lease without a renewal for 90 seconds is free, so the lock of a stopped process frees itself.
Wait for the operation that the Lease names. Do not delete the Lease while its holder runs.

## An incomplete reset blocks every command

While a reset is incomplete, the site lock keeps a reset marker. `up`, `down`, the settings Apply, the zone operations, the backups, the restores and the Compose import stop with the record id of the reset.

1. Correct the cause that the record of the reset names.
2. Continue the reset:

   ```sh
   k3s/deploy-k3s reset --site <site file> --resume <record>
   ```

A complete reset removes the marker.

## Pods do not start

Print every pod that is not ready, with its reason and the recent warning events:

```sh
python3 k3s/tools/sweep.py <namespace>... [--wait SECONDS]
```

With `--wait` the command stops at the first state that waiting does not repair. Examples are `CrashLoopBackOff`, an image error, `OOMKilled`, and a pod without a node for 2 minutes.

1. Read the conditions and the warning events of the pod.
2. Read `kubectl -n <namespace> logs <pod> --previous`, then the log of the application.
3. Correct every cause of the sweep, then delete each failed pod. A back-off timer grows to 300 seconds, and a new pod starts at once.

## A pod waits for memory or for a node

The placement step plans every pod of the site before a change. When the memory does not fit at any CPU factor, the step and `deploy-k3s check` fail. The message names the free memory of each node and the pods without room.

```sh
k3s/deploy-k3s check --site <site file> --target all
```

1. Read the plan and the factor in the output of `check`.
2. Free memory: delete or stop a zone, lower a memory limit in the site file, or add a node.
3. Run `deploy-k3s up` again.

A pod that the plan does not move keeps its node. A zone create or delete moves no pod of another zone.

## A volume group is full

Each storage tier of a node keeps 5 % of its volume group free. A claim that does not fit stays `Pending`, and the alarm `VolumeGroupAlmostFull` fires below 10 % free space.

1. Find the volume group and the node in the alarm, or with `vgs` on the node.
2. Remove the data that is not needed, for example a deleted zone or an old collection.
3. Or add a disk to the volume group on the node. The installer changes no disk, partition or volume group.

## An alarm is active

The operator portal shows the active alarms. No alarm leaves the cluster.

| Alarm | Meaning | Action |
|---|---|---|
| `VolumeGroupAlmostFull` | A volume group has less than 10 % free space. | See [A volume group is full](#a-volume-group-is-full). |
| `VolumeAlmostFull` | A claim has less than 10 % free space. | Remove data in the application that uses the claim. |
| `ContainerVolumeAlmostFull` | `/`, `/var/lib/rancher` or `/var/lib/kubelet` of a node has less than 20 % free space. | Remove old images and logs on the node. |
| `NodeMemoryLow` | A node has less than 10 % of its memory available. | Read the placement plan. Move or stop a zone, or add memory. |
| `ContainerOutOfMemory` | A container stopped at its memory limit. | Read its peak in Grafana. Raise its limit in the site file when the peak is normal use. |
| `PodRestarts` | A container restarted three times in 15 minutes. | Read its previous log, as [Pods do not start](#pods-do-not-start) describes. |
| `NodeSwapAlmostFull` | A node has less than 25 % of its swap free. | Find the pods with swap in Grafana. Lower the load or the quotas of `vars.pod_swap`. |
| `NodeMemoryPressure` | The processes of a node waited for memory in more than 5 % of the time for 10 minutes. | Lower the load of the node or move a zone. |
| `NodeOutOfMemoryKill` | The kernel of a node stopped a process. | Read `journalctl -k` on the node for the process. |
| `PodSwapNearQuota` | A pod has more than 30 % of its memory limit in swap. | Raise the memory limit of the pod, or lower its load. |
| `BackupFailed` | The last copy of a backup job failed. | Read `last_error` of the job with `backups.py status` and run the job again. |
| `BackupBlocked` | A backup job has no space. | Remove old copies or make the backup volume larger. |
| `BackupPaused` | The backup folder has no marker. | Mount the backup volume, or run `backups.py enable`. |
| `BackupOff` | The site has a backup folder and no backup policy. | Turn on a policy in the settings. |

## A Kata guest does not answer

The tools of `k3s/tools/kata-debug/` read a Kata guest from its node. Run them as root on the node of the pod.

- `guest-memory-lines.py watchdog|agent <sandbox id> [count]` prints the last kernel log lines of the guest watchdog, or the last log lines of the Kata agent, from the memory of the guest. The read changes nothing.
- `guest-console.py <sandbox id> <script file>` runs a script in the guest. The guest must run with the debug console on. The sites have the debug console off.

The sandbox id is the pod sandbox id of `crictl pods --name <pod>`.
