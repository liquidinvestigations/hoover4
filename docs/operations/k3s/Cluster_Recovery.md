# Recover a cluster site

The k3s installation is experimental. A zone keeps its data in one copy on the nodes of the site. Keep the backups and the files of [the custody list](Cluster_Installation.md#keep-the-files-of-the-site) outside the site.

This manual describes the restore of lost data of a site of `k3s/deploy-k3s`.
[The operations manual](Cluster_Operations.md) describes the backups, and [the troubleshooting manual](Cluster_Troubleshooting.md) describes failures without data loss.

## Contents

- [Choose the procedure](#choose-the-procedure)
- [Restore a zone](#restore-a-zone)
- [Restore the platform](#restore-the-platform)
- [Recover a lost node or volume](#recover-a-lost-node-or-volume)
- [Recover a lost control plane](#recover-a-lost-control-plane)
- [Recover a lost state folder](#recover-a-lost-state-folder)
- [Recover a lost site](#recover-a-lost-site)

## Choose the procedure

| Loss | Procedure | Needs |
|---|---|---|
| The data of one zone | [Restore a zone](#restore-a-zone) | The identity copy and the zone copy of the zone |
| A node or a volume | [Recover a lost node or volume](#recover-a-lost-node-or-volume) | The zone copies and the collection copies |
| The control-plane server | [Recover a lost control plane](#recover-a-lost-control-plane) | A platform copy, the site identity file and its passphrase |
| The state folder of the workstation | [Recover a lost state folder](#recover-a-lost-state-folder) | The site file and the site identity file |
| Every node of the site | [Recover a lost site](#recover-a-lost-site) | The site file, a platform copy, the zone copies and the collection copies |

## Restore a zone

A restore writes a copy into an installed zone. It can be the zone of the copy or another zone. The target keeps its own Secrets and service passwords.

1. Install the target zone.
2. Check both copies in the runner container (`$run` of [Back up the site](Cluster_Operations.md#back-up-the-site)):

   ```sh
   $run verify identity:<zone of the copy> <generation>
   $run verify zone:<zone of the copy> <generation>
   ```

3. Restore the identity copy first. It replaces the users, the groups and the sign-in data of the target. `--from` names the zone of the copy when it differs from the target zone.

   ```sh
   $run restore-identity <zone> <generation> --from <zone of the copy>
   ```

4. Restore the zone copy. It replaces the files, the wiki pages, the chats, the boards and the Hoover databases.

   ```sh
   $run restore-zone <zone> <generation> --from <zone of the copy>
   ```

5. Sign in to the zone as a user of the copy, with the password of the copy. Check the files, the wiki pages, the chats and boards, and the collections.
6. Restore the collections with `$run restore-hoover <zone> <collection> <generation>`.

`restore-zone` stops in its first step when a user who owns data in the copy is not in the directory of the target with the same name and id. The message names the users. A new zone has users with the same names and new ids, so restore the identity copy first. Restore the identity copy, or create the users and add `--without-owners`.
`Administrator` and the onboarding account `test.user` keep the passwords of the target zone.

A restore closes the zone and writes the parts of the copy. It then writes the passwords of the target into the restored data, starts the zone, and runs `zone.py apply <zone> --full`.
A failure leaves the zone in the state of its last finished step. `<operator state>/backups/restore-<zone>.json` names the finished steps. Run the same command again after the cause is corrected. It continues at the first step that is not done, also after a restart of the operator pod.
A copy of an earlier format stops the restore. Its message names the commit that restores such a copy into its own running zone.

## Restore the platform

The platform copy holds the newest scheduled etcd snapshot of the server with its k3s configuration, `site-config.tar`, the snapshot of the secret store and `recovery.json`. It holds no server token and no key. `recovery.json` names the time of the snapshot and the zone copies that a complete recovery needs.

Keep the site identity file outside the site. Write it once after the first `deploy-k3s up`, and check it:

```sh
k3s/deploy-k3s identity export <file> --site <site file>
k3s/deploy-k3s identity verify <file> --site <site file>
```

The command asks for a passphrase. Keep the passphrase apart from the file.

1. Print the recovery set and the procedures of a copy:

   ```sh
   $run recovery <generation>
   $run restore-platform <generation>
   ```

2. For a lost site, do procedure 1: unpack `site-config.tar` into the state folder, run `deploy-k3s up --target all`, then restore the identity copy and the zone copy of each zone.
3. For an etcd restore on the same hardware, do procedure 2. It needs the site identity file and its passphrase.

## Recover a lost node or volume

This procedure is not tested.

A store pod keeps its data on the volume of its node. While a node is stopped, its part of the store data is out of reach for every zone. [The lost store nodes](../../../k3s/Readme.md#lost-store-nodes) section of the reference names the effect for each store.

1. Find the pods that do not run:

   ```sh
   kubectl -n hoover-stores get pods -o wide
   python3 k3s/tools/sweep.py hoover-stores <zone>
   ```

2. When the node returns with its volumes, its pods start again. No restore is necessary.
3. When a volume is lost, restore its data:
   - A claim of a zone: [restore the zone](#restore-a-zone) from its copies.
   - A store of `hoover-stores`: restore the collections of each zone with `restore-hoover`. `main.py reindex-collection` builds the Manticore tables of a collection again from ClickHouse. No copy holds the Temporal history.

## Recover a lost control plane

This procedure is not tested. The first step was run on a test site.

The site has one control-plane server with embedded etcd. Without it, no cluster command runs.
The platform copy holds the newest scheduled etcd snapshot without the server token. The site identity file holds the token.

1. Install the operating system of the server again with the same host name and address, or repair its disk.
2. Print the procedures of the newest platform copy. Run the commands in the runner container while a node with the backup folder runs, or read `recovery.json` of the copy on the backup node:

   ```sh
   $run restore-platform <generation>
   ```

3. Do procedure 2. Its first step writes the server token of the identity file into the folder `etcd/` of the copy. openssl asks for the passphrase.
4. Copy the folder to the server and run the datastore script of the printed command with sudo.
5. Run `deploy-k3s up --target all`, then restore the secret store as the procedure prints.
6. Remove the file `token` from the folder of the copy.

## Recover a lost state folder

This procedure is not tested.

The state folder of the workstation (`k3s/private/<site>/`) holds the admin kubeconfig, the server token and the operator logins. It also holds the seal key and the recovery key of the secret store. The cluster keeps a copy of the zone and operator state.

1. Write the three values of the site identity file into a new state folder:

   ```sh
   openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -in <identity file> | tar -x -C <folder>
   ```

   The archive holds `server-token`, `seal.key` and `recovery-key`. Move them to `staging/tokens/server-token`, `secret-store/seal.key` and `secret-store/recovery-key` of the state folder, with the mode 0600.
2. Copy the admin kubeconfig of the server (`/etc/rancher/k3s/k3s.yaml`) to `kubeconfig` of the state folder, and replace the address `127.0.0.1` with the address of the server.
3. Read the cluster copy of the state:

   ```sh
   KUBECONFIG=<state folder>/kubeconfig python3 k3s/clusterstate.py pull <state folder>
   ```

4. Run `deploy-k3s check --target all`, then `deploy-k3s identity verify <identity file>`.

## Recover a lost site

This procedure is not tested.

1. Install the nodes with the site file. Unpack `site-config.tar` of the newest platform copy into the state folder first, so the site gets the same zones and settings.

   ```sh
   k3s/deploy-k3s up --target all --site <site file>
   ```

2. Mount the backup volume on the backup node, and run `backups.py enable` in the runner container.
3. [Restore each zone](#restore-a-zone): the identity copy first, then the zone copy.
4. Restore the collections with `restore-hoover`.
5. Write a new site identity file. A reinstall makes a new server token and new keys.
