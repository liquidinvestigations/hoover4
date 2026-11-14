# Move an earlier installation into a cluster site

The k3s installation is experimental.

This manual moves three kinds of earlier installation into a site of `k3s/deploy-k3s`.
Each kind has its own procedure. Do not use the procedure of one kind for another kind.

| Earlier installation | Procedure |
|---|---|
| A k3s cluster of the earlier deployment tool, with its zones | [Adopt an earlier cluster](#adopt-an-earlier-cluster) |
| A Compose installation of `./deploy` | [Move a Compose installation](#move-a-compose-installation) |
| The local single-node site of a workstation | [Retire a local single-node site](#retire-a-local-single-node-site) |

[The cluster deployment reference](../../../k3s/Readme.md) describes each command in detail.

## Adopt an earlier cluster

The site keeps the zone names, the claims, the database prefixes, the buckets and the service users of the earlier cluster.
The existing zones keep the zone store layout (`stores = zone`) and the PostgreSQL Temporal backend.
The storage names of a zone come from its zone name, so an existing zone keeps them only when the earlier cluster used the same names.
No step converts the Temporal backend.

1. Write the site file with the nodes, and write the zone state `zone-state.json` of the state folder with one entry for each zone.
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

6. Check out the commit, then run `k3s/deploy-k3s up --target all`.

### Convert the server datastore to etcd

A server of the earlier tool can use SQLite. The k3s play of the server (step `hosts:k3s`) converts it to etcd without a reinstall.

1. The play stops k3s and copies the SQLite datastore, the token and the configuration into `/var/lib/hoover4-recovery/` with `SHA256SUMS`.
2. It reads the copy again. A copy that does not verify stops the play, and k3s stays stopped.
3. It starts k3s with `cluster-init` and saves an etcd snapshot. The step `hosts:verify` checks the `etcd` role of the node.
4. After the conversion, `hosts:verify` restarts the controllers of `kube-system`, `ingress`, `cert-manager`, `topolvm-system`, `monitoring` and `operator-portal`.
   Without this restart, CoreDNS, the ingress controller, cert-manager and TopoLVM did not see objects that were created after the conversion.

The SQLite copy is the only rollback before new writes. After new writes, the copy does not hold them.
To return to it, stop k3s, restore the copy while the server is stopped, and start k3s.

### Check the workflow histories

Replay the open and recent closed workflows of each zone with the new worker before new work starts.
A history that does not replay shows a change of a workflow that needs a Temporal patch marker.

## Move a Compose installation

`k3s/deploy-k3s import-compose` imports the stopped Compose stores into a new zone of the site.
The zone gets the storage names of its zone id, and the import renames the databases, tables and buckets.
The source keeps its data folders, and nothing deletes them. The import runs once per zone.

The import needs `sudo -n` on the source node and on the node that `--home` names.
It sends `probe.py` and `root_copy.py` to Python as root on the source node, and imports the store images with `k3s ctr` on the `--home` node.
The copy binds the store volumes on that node, and the pods that share the volumes follow them. The zone has no home node after the import.

1. Put the Compose volume folder below the `data_root` of the source node, for example with a bind mount.
   Do the same for each dataset folder that the import copies.
2. Put the `hoover4.ini` of the Compose installation into the folder of the site file.
3. Show the plan. The command changes nothing.

   ```sh
   k3s/deploy-k3s import-compose <zone> <folder> --home <node> --ini <file> --dataset uploads=<folder> --dry-run
   ```

4. Run the import. A finished step does not run again, so the same command continues an interrupted import.
   A later step with changed inputs stops.

   ```sh
   k3s/deploy-k3s import-compose <zone> <folder> --home <node> --ini <file> --dataset uploads=<folder>
   ```

5. Give each owner of chats and boards a zone user:

   ```sh
   k3s/deploy-k3s import-compose <zone> --users
   ```

| Step | Result |
|---|---|
| `plan` | Checks the folders, the images, the claims and the free capacity, and saves the ini values as settings of the zone. |
| `freeze` | Stops the website, the sign-in proxy, the MCP and agent servers, then the workers with their grace period. |
| `record` | Records the Temporal namespaces, the open workflows with their histories, and the store contents. |
| `stop` | Stops Temporal and the stores of the source. |
| `zone` | Creates the zone with the Compose store layout. No Hoover service starts. |
| `copy` | Copies each folder into its claim with the mapped owners, and checks the SHA-256 of every file. |
| `stores` | Starts only the stores and Temporal, and compares them with the record. |
| `renames` | Renames the databases, tables and bucket aliases, the bucket names in the stored object paths and the dataset paths. |
| `temporal` | Compares Temporal with the record. |
| `workers`, `resume` | Start the workers, and wait until each open workflow of the record continues or closes. |

`--engine docker|podman` names the container runtime of the source, and `--source-node` the node of the source.
[The cluster deployment reference](../../../k3s/Readme.md#move-a-compose-installation-into-the-cluster) lists every option.

### Retry and return

An interrupted `copy` empties the claim and copies it again. A claim with another volume identity than the record stops the step.
Before the zone takes new work, delete the zone in the operator portal and start Compose again with `./deploy`.
After the zone takes new work, a return to Compose loses that work.
A second import of the same zone id needs the removal of `operator/import/<zone>/` of the state folder after the zone delete.

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

3. Run the printed root step `sudo python3 - preserve <name> < k3s/ansible/roles/hoover4_k3s/files/k3s-datastore.py`, move the copy into the archive folder, then write and read the manifest again:

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
