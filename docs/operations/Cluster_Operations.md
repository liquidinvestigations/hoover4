# Operate a cluster site

This manual describes the daily tasks of a platform operator on a site of `k3s/deploy-k3s`.
[The installation manual](Cluster_Installation.md) installs a site, and [the zone manual](Zone_Operator_Manual.md) describes the tasks of each zone.
[The cluster deployment reference](../../k3s/Readme.md) describes each command in detail.

## Contents

- [Upgrade the site](#upgrade-the-site)
- [Return to an earlier release](#return-to-an-earlier-release)
- [Save and apply settings](#save-and-apply-settings)
- [Stop and start the site](#stop-and-start-the-site)
- [Monitor the site](#monitor-the-site)
- [Back up the site](#back-up-the-site)
- [Restore a zone](#restore-a-zone)
- [Restore the platform](#restore-the-platform)
- [Reach an installation from a workstation](#reach-an-installation-from-a-workstation)

## Upgrade the site

An upgrade installs the source and the images of one commit.

1. Show the steps of the commit. The command changes nothing.

   ```sh
   k3s/deploy-k3s render --target all --revision <commit>
   ```

2. Run the upgrade:

   ```sh
   k3s/deploy-k3s up --target all --revision <commit>
   ```

3. When a step fails, read its error and correct the cause. Continue the same record:

   ```sh
   k3s/deploy-k3s up --resume <record>
   ```

4. Check the result with `k3s/deploy-k3s status`. The applied revision is the commit of the last complete run.

The record of a run pins the commit, the fingerprint of its exported tree, the site file, the saved settings revision and the cluster.
A resume refuses a change of these inputs. A second `up` of the same commit changes no object.
A waiting or failed step stops every step that depends on it.

One site operation runs at a time. The driver, the settings Apply, the zone operations, the migration and the zone and platform backups share one lock.

## Return to an earlier release

`deploy/previous.json` in the operator state names the release before the applied one.
Run `k3s/deploy-k3s up --target all --revision <earlier commit>` to return to it.
An earlier image does not reverse stored data. A database migration of the later release stays applied, so check that the earlier release reads it.

## Save and apply settings

The operator settings hold the tunings, switches, applications, memory limits and backup policies of the site and its zones.
The settings page is `https://operator.<suffix>/settings.html`.

1. Edit a value and select **Save**. A save changes no service.
2. Read the pending changes and the services that each change restarts.
3. Select **Apply**. The runner applies the newest saved revision, one scope at a time.
4. When the operation fails, read its error, correct the cause, and select **Retry**. A retry continues at the first unfinished step.
5. Select **Abandon** to stop a failed operation. The scopes that it did not finish keep their earlier applied revision.

A value that you save during a running operation stays pending for the next Apply.
The setting `gpu.runtime` applies the GPU pool and checks each GPU service with and without the pool key.

## Stop and start the site

```sh
k3s/deploy-k3s down --target all
k3s/deploy-k3s up --target all --start
```

`down` stops the zone gates, then the applications and workers, then Temporal, then the stores, then the HTTPS frontend and k3s.
It also suspends the CronJobs of the zones. The workers end through their grace period, and no workflow is cancelled.
`up --start` starts the parts in the reverse order and resumes only the CronJobs that `down` suspended.

## Monitor the site

The operator portal at `https://operator.<suffix>/` links the monitoring tools.

| Tool | Use |
|---|---|
| Headlamp | Inspect the deployments, pods, events, volumes and logs. |
| Grafana | Read the resource dashboards. Use Explore to search the logs in Loki. |
| Prometheus | Read the alarms at `/alerts` and the scrape targets. |

The portal also shows the recent warning events of the cluster and the operations of the zones.

## Back up the site

The site file `[backup]` names the backup node and its backup folder.
The settings `backup.opendesk.*` and `backup.hoover.*` of each zone and `backup.platform.*` of the cluster turn each job on and set its retained copies.

1. Create the backup folder. The `up` run creates it on the backup node with the folders `zones` and `platform`.
2. Write the marker of the folder. A folder without the marker pauses every job, so a missing mount does not fill the disk.

   ```sh
   python3 k3s/platform/backups/backups.py enable
   ```

3. Turn on the backup policies on the settings page, and Apply.
4. Read the state of the jobs and the list of copies:

   ```sh
   python3 k3s/platform/backups/backups.py status
   python3 k3s/platform/backups/backups.py copies
   ```

| Copy | Folder below the backup folder |
|---|---|
| A complete zone: openDesk and its Hoover installation | `zones/<zone>/<generation>/` |
| A Hoover collection of a zone | `zones/<zone>/collections/<collection>/<generation>/` |
| The platform recovery set | `platform/<generation>/` |

The commands take names only. A zone copy closes the zone during the copy and reopens it with the recorded replicas.
A copy replaces an older copy only after its check on the backup node. A failed transfer keeps the older copies.
Keep the backup folder on another site. The system cannot check this.

## Restore a zone

A restore replaces the data of an installed zone with a zone copy.

1. Install the target zone. It can be the zone of the copy or another zone.
2. Check the copy on the backup node:

   ```sh
   python3 k3s/platform/backups/backups.py verify zone:<zone of the copy> <generation>
   ```

3. Restore it. `--from` names the zone of the copy when it differs from the target zone.

   ```sh
   python3 k3s/platform/backups/backups.py restore-zone <zone> <generation> --from <zone of the copy>
   ```

4. Sign in to the zone, and check the files, the chats and boards, and the collections.

The restore closes the zone and its Hoover installation and stops their stores, except the zone databases.
It applies the Secrets of the copy, replaces each claim, imports the database dumps, and opens the zone.
A failure leaves the zone closed. `<operator state>/backups/restore-<zone>.json` names the finished steps, and a second run continues after them.
Restore a single collection with `backups.py restore-hoover <zone> <collection> <generation>`.

## Restore the platform

The platform copy holds an etcd snapshot of the server, its token and k3s configuration, the private files of the site and `recovery.json`.
An etcd snapshot holds no volume data, so a complete recovery also restores the zone copies that `recovery.json` names.

1. Print the recovery set and the root steps of a copy:

   ```sh
   python3 k3s/platform/backups/backups.py recovery <generation>
   python3 k3s/platform/backups/backups.py restore-platform <generation>
   ```

2. Do the printed steps on the stopped server of an isolated cluster. The root step is `root-install-k3s.py --bundle backup --node <server> --restore-snapshot <name>`.
3. Restore each zone copy with `restore-zone`, then sign in to each zone.

## Reach an installation from a workstation

The relay of an installation serves its MCP servers, interfaces and stores on the loopback address of its home node.
Development tools reach them through an SSH tunnel. No port opens to the network.

1. Start the relay with the ports of the Compose installation:

   ```sh
   python3 k3s/platform/mcp-relay/install-relay.py <installation> apply --ports compose
   ```

2. Start an SSH tunnel from the workstation to the home node, with one `-L 127.0.0.1:<port>:127.0.0.1:<port>` for each port that the client uses.
3. Check the MCP servers through the tunnel. The check fails on a tool error, a wrong server name, or a call without the token that is not refused.

   ```sh
   python3 k3s/tools/mcp-relay-check.py --secret-from k3s:<Hoover namespace> mcp-collections=<port> mcp-todo=<port>
   ```
