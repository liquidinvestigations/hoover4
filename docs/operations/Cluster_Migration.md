# Move an earlier installation into a cluster site

This manual moves three kinds of earlier installation into a site of `k3s/deploy-k3s`.
Each kind has its own procedure. Do not use the procedure of one kind for another kind.

| Earlier installation | Procedure |
|---|---|
| A k3s cluster of the earlier deployment tool, with its zones | [Adopt an earlier cluster](#adopt-an-earlier-cluster) |
| A Compose installation of `./deploy` | [Move a Compose installation](#move-a-compose-installation) |
| The local single-node site of a workstation | [Retire a local single-node site](#retire-a-local-single-node-site) |

[The cluster deployment reference](../../k3s/Readme.md) describes each command in detail.

## Adopt an earlier cluster

The site keeps the zone names, the home nodes, the claims, the database prefixes, the buckets and the service users of the earlier cluster.
The existing zones keep the zone store layout (`stores = zone`), the PostgreSQL Temporal backend and `history_source = k3s-branch`.
No step converts the Temporal backend.

1. Write the site file with the nodes and one `[hoover.<name>]` section for each zone.
2. Compare the cluster with the site file. The command changes nothing.

   ```sh
   python3 k3s/tools/adopt-cluster.py inventory
   ```

   Correct each difference that it lists before the next step.
3. Find the runner of the earlier tool, and stop and disable it. One runner owns the operator state of a site.

   ```sh
   python3 k3s/tools/adopt-cluster.py runners
   ```

4. Copy the k3s tokens of the server into the private staging folder:

   ```sh
   python3 k3s/tools/adopt-cluster.py tokens
   ```

5. Save the values of the `hoover4.ini` of each earlier zone once as operator settings. The command lists the keys that the current revision does not read.

   ```sh
   python3 k3s/tools/adopt-cluster.py settings
   ```

6. Run `k3s/deploy-k3s up --target all --revision <commit>`.

### Convert the server datastore to etcd

A server of the earlier tool can use SQLite. The `root` step of the server converts it to etcd without a reinstall.

1. The root script stops k3s and copies the SQLite datastore, the token and the configuration into `/var/lib/hoover4-recovery/` with `SHA256SUMS`.
2. It reads the copy again. A copy that does not verify stops the script, and k3s stays stopped.
3. It starts k3s with `cluster-init`. The `verify` step saves an etcd snapshot and checks the `etcd` role of the node.
4. After the conversion, `verify` restarts the controllers of `kube-system`, `ingress`, `cert-manager`, `topolvm-system`, `monitoring` and `operator-portal`.
   Without this restart, CoreDNS, the ingress controller, cert-manager and TopoLVM did not see objects that were created after the conversion.

The SQLite copy is the only rollback before new writes. After new writes, the copy does not hold them.
To return to it, stop k3s, restore the copy while the server is stopped, and start k3s.

### Check the workflow histories

Replay the open and recent closed workflows of each zone with the new worker before new work starts.
A history that does not replay shows a change of a workflow that needs a Temporal patch marker.

## Move a Compose installation

The migration copies the stopped Compose stores into the claims of a Hoover installation of the site.
The source keeps its data folders, and nothing deletes them.

1. Add a `[hoover.<name>]` section with `source_ini`, the `hoover4.ini` of the Compose installation.
   A migrated installation keeps the storage identity `Hoover4`, an empty table prefix, `hoover4-system` and `hoover4-c-`, and `history_source = compose`.
2. Show the plan. The command changes nothing.

   ```sh
   python3 k3s/migration/migrate.py plan <name> --dry-run
   ```

3. Run the steps in order. A finished step does not run again, and a later step with changed inputs stops.

   ```sh
   for step in plan freeze record stop images copy secrets stores temporal workers resume; do
     python3 k3s/migration/migrate.py "$step" <name> || break
   done
   ```

4. Give each owner of chats and boards a zone user:

   ```sh
   python3 k3s/migration/migrate.py users <name>
   ```

| Step | Result |
|---|---|
| `freeze` | Stops the website, the sign-in proxy, the MCP and agent servers, then the workers with their grace period. |
| `record` | Records the Temporal namespaces, the open workflows with their histories, and the store contents. |
| `stop` | Stops Temporal and the stores of the source. |
| `copy` | Copies each folder into its claim with the mapped owners, and checks the SHA-256 of every file. |
| `stores`, `temporal` | Start only the stores and Temporal, and compare them with the record. |
| `workers`, `resume` | Start the workers, and wait until each open workflow of the record continues or closes. |

`--engine docker|podman` names the container runtime of the source, and `--source-host` the SSH host of the source.
The migration runs its root commands with `sudo -n` on the source host and on the operator host, so the operator user needs unrestricted `sudo -n` on both.

### Retry and return

An interrupted `copy` empties the claim and copies it again. A claim with another volume identity than the record stops the step.
Before the target takes new work, delete the claims of the target installation and start Compose again with `./deploy`.
After the target takes new work, a return to Compose loses that work.

## Retire a local single-node site

`k3s/tools/local-retirement.py` preserves the local site and writes a removal script. It removes nothing itself.

1. Record the units, mounts, volumes, network setup, claims and protected resources:

   ```sh
   python3 k3s/tools/local-retirement.py inventory <archive folder>
   ```

2. Stop the site and copy each claim, the objects and the private folder. The command prints the root step for the k3s datastore.

   ```sh
   python3 k3s/tools/local-retirement.py archive <archive folder>
   ```

3. Run the printed root step `root-install-k3s.py --preserve <name>`, move the copy into the archive folder, then write and read the manifest again:

   ```sh
   python3 k3s/tools/local-retirement.py manifest <archive folder>
   python3 k3s/tools/local-retirement.py verify <archive folder>
   ```

4. Restore the archive into a temporary zone of another site and verify the sign-in and the data before the removal.
   [The operations manual](Cluster_Operations.md#restore-a-zone) describes the restore.
5. Write the removal script, read every line, and run it as root:

   ```sh
   python3 k3s/tools/local-retirement.py removal <archive folder>
   ```

   The script keeps the k3s binary, `kubectl`, `crictl`, `ctr`, the k3s scripts and the kubeconfig link of another project.
6. Verify that `k3s` is inactive, that `/var/lib/rancher` is not mounted, and that the link `hoover4` is absent.
