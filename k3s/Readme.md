# Cluster deployment

This folder holds the code that runs Hoover and openDesk on k3s.
The Compose deployment of [`./deploy`](../docs/operations/Deploying.md) stays available beside it.
The images of the cluster come from commits of this repository.

## Find the parts.

| Folder or file | Purpose |
|---|---|
| [deploy-k3s](deploy-k3s) | Installs, updates, stops, starts and checks a site. [driver/](driver) holds its modules. |
| [config.py](config.py) | Reads and checks the site file `hoover4-site.ini`, writes the part of the site that each node receives, and reads the `hoover4.ini` of an earlier Compose install. |
| [hoover/](hoover) | Renders the Kubernetes objects of a Hoover installation from the Compose files ([manifests.py](hoover/manifests.py)), writes its `hoover4.ini` ([zone_ini.py](hoover/zone_ini.py)), prepares its stores and Secrets ([setup.py](hoover/setup.py)), and holds the GPU proxy ([gpu.py](hoover/gpu.py)). |
| [Compose_Parity.md](Compose_Parity.md) | Names the cluster form of every Compose service and volume folder. |
| [platform/operator/settings.py](platform/operator/settings.py) | Holds the operator settings registry, the saved and applied revisions, and the apply operations. |
| [platform/](platform) | Installs the registry, the ingress, the HTTPS frontend, the calls services, monitoring, the operator portal and runner, and the Hoover data servers. |
| [zones/](zones) | Installs and changes the openDesk zones. |
| [hosts/](hosts) | Prepares the hosts and installs k3s on them, as root. |
| [cluster/](cluster) | Installs the cluster services that every zone uses: RuntimeClasses, cert-manager and TopoLVM. |
| [images/](images) | Builds the images and pushes them to the cluster registry. |
| [tools/](tools) | Holds checks and operator tools. |
| [tests/](tests) | Holds the test suites and their fixtures. |

The folder `private/` holds the site file, the secrets, the kubeconfigs, the operator state and the generated files.
Git ignores it. The scripts of `platform/`, `zones/`, `hosts/` and `cluster/` read the site file through [settings.py](settings.py).
`config.legacy_settings()` gives the values of the earlier `private/settings.json`, and `config.legacy_hosts()` gives the `hosts.json` form.
An installation without a site file still reads `private/settings.json`.

## Write the site file.

The site file names the resources of the installation and the roles of its nodes.
It holds no port, tuning, feature switch, backup schedule or secret value.
The default path is `k3s/private/hoover4-site.ini`. [tests/fixtures/](tests/fixtures) has a single-node and a remote example.

| Section | Keys |
|---|---|
| `[site]` | `name`, `suffix`, `control_plane`, and optional `operator_user`, `vpn_cidr`, `state_path` |
| `[node.<name>]` | `roles`, and optional `local`, `ssh_address`, `architecture`, `vpn_address`, `wireguard_public_key`, `wireguard_port`, `lan_address`, `onprem`, `public_address`, `storage_tiers`, `lvm_volume_group`, `lvm_physical_volumes`, `reserved`, `avx2`, `data_root`, `tls_dns_credentials_file`, `gpu_api_key_file` |
| `[gpu_pool]` | `nodes` or `address`, and `api_key_file` |
| `[backup]` | `node` and `path` of the backup destination |
| `[hoover.<name>]` | `zone`, `home_node`, `stores`, `temporal_backend`, `clickhouse_database_prefix`, `manticore_table_prefix`, `system_bucket`, `collection_bucket_prefix`, and optional `history_source`, `source_ini`, `chat_control_dir` |

The roles are `control-plane`, `worker`, `public`, `registry`, `data`, `calls` and `gpu`.
The value `single` gives one host every role except `calls` and `gpu`.
A site with one node needs no VPN address and no public address.
A GPU node has no other role. A key that ends with `_file` names a private file on the node that has the matching role.

Check a site file, or print the part that one node receives:

```sh
python3 k3s/config.py check k3s/private/hoover4-site.ini
python3 k3s/config.py project k3s/private/hoover4-site.ini <node>
python3 k3s/config.py source /path/to/hoover4.ini
```

The storage identity of a Hoover installation is independent of its zone name.
A migrated Compose install keeps `Hoover4`, an empty table prefix, `hoover4-system` and `hoover4-c-`.
Set `history_source = k3s-branch` only for an installation that ran the earlier `k3s` branch of Hoover.

## Deploy a site.

`deploy-k3s` is the one command of a site. It needs Python 3 and SSH only.

```sh
k3s/deploy-k3s render --target all          # prints the configuration and the steps. Changes nothing.
k3s/deploy-k3s check --target all           # checks the hosts, the files and the tools. Changes nothing.
k3s/deploy-k3s bootstrap --target <node>    # writes the reviewed bootstrap script of a node
k3s/deploy-k3s up --target all [--revision <commit>]
k3s/deploy-k3s down --target all
k3s/deploy-k3s up --target all --start
k3s/deploy-k3s status
```

- `up` installs the hosts, k3s, the pinned operator tools, the cluster services, the registry, the images, the ingress, the HTTPS frontend, monitoring, the operator portal and runner, the calls services, the GPU proxy and each zone, in this order.
  The registry step runs before the image step, so each push has a target.
- The driver resolves `--revision` once. The record of the run keeps the commit, and every step and node gets it.
  The images carry this commit. Local changes of the checkout stay unchanged, and the record lists them.
- Each run has a record in `<operator state>/deploy/records/`. A failed or stopped run keeps its finished steps.
  `deploy-k3s up --resume <record>` continues at the first unfinished step with the same revision.
- A finished `up` of every node, without `--steps`, becomes `deploy/applied.json`. Its image references are digests in the registry.
  The earlier applied record moves to `deploy/previous.json`, so a failed update can return to its revision with `up --revision`.
- `down` scales the ingress and the zone gates to zero, then the applications and workers, then Temporal, then the stores, and then stops k3s.
  `deploy/stopped.json` keeps the replica counts. `up --start` starts k3s and restores the stores, Temporal, the applications and the ingress in this order.
  The workers end through their grace period, and no workflow is cancelled.
- The local node of a single-node site uses the adapter `local-arch`. It runs the root scripts [hosts/root-install-local.py](hosts/root-install-local.py) and [hosts/root-install-k3s.py](hosts/root-install-k3s.py) with `sudo -n`.
  The bootstrap script of the local node installs copies of these scripts into `/usr/local/libexec/hoover4` and a sudo rule for them and the units of the site. The driver uses a copy when it equals the source.
- A remote node uses the adapter `remote`. The driver checks it over SSH with read-only commands.
  It writes `bootstrap.sh`, `install.sh`, `README.txt` and the node part of the site into `private/deploy/remote/<node>/`.
  The operator runs them on the node. The step waits until the node is Ready, so a run with a waiting node is not applied.
  A node that SSH cannot reach fails its step with the SSH error, and the record stays resumable.

The local node of a single-node site gets the dummy link `hoover4` with the address `10.254.54.1`, a dnsmasq for the names below the suffix, and the units `hoover4-address`, `hoover4-dns` and `hoover4-frontend`.
k3s and every pod run in `hoover4.slice`. The node value `reserved` sets the memory and CPU that stay with the rest of the host, for example a Compose stack.
The k3s data and the kubelet folder are volumes of the volume group of the node. TopoLVM uses the free space of the group.
The admin kubeconfig is `private/kubeconfig`. k3s writes it as `/etc/rancher/k3s/hoover4-admin.yaml`, because `/etc/rancher/k3s/k3s.yaml` can belong to another k3s user of the host.
A new Hoover installation of a single-node site keeps its dataset folders `testdata` and `uploads` on claims, so it needs no NFS server.

## Choose the stores and the Temporal backend.

| Key | Value | Result |
|---|---|---|
| `stores` | `local` | The Compose stores run in the Hoover namespace on claims of the home node. The operations worker mounts them, so store backup and restore work. |
| `stores` | `zone` | ClickHouse, Manticore and Garage run in Kata on block volumes in the zone namespace, with a user for each service. Existing remote zones use this layout. |
| `temporal_backend` | `cassandra` | Temporal, Cassandra and Elasticsearch run as in Compose, with the dynamic configuration of deploy.py. |
| `temporal_backend` | `postgresql` | Temporal uses the PostgreSQL of the zone. Existing remote zones use this backend. No conversion between the backends exists. |

## Render a Hoover installation.

```sh
python3 k3s/hoover/manifests.py <installation> show --revision <commit>
python3 k3s/images/build-hoover.py --revision <commit>
```

`show` prints the objects and changes nothing.
A migrated installation reads its dataset mounts from its `source_ini`, and its render runs no command when `--revision` is given.
Another installation reads the addresses of the NFS servers of `platform/hoover-data/` from the cluster.
The image tag is the first 12 characters of the commit. The build exports the commit, so local changes stay out of the images.

## Save and apply operator settings.

The operator settings hold every Hoover ini tuning and switch, and the cluster settings of each Hoover installation.
These are the budget, the worker sandbox, the slot tuner, the administrator groups and the volume sizes.
They also hold the openDesk applications and memory limits of each zone, and the CPU policy of the cluster.
`python3 k3s/platform/operator/settings.py list` prints each setting with its type, default, services and apply mode.

- A save names the revision that it changes. A save over a newer revision is refused.
- A save changes no service. Apply starts one operation for the newest revision.
- An operation records each step before and after it runs. A retry continues at its first unfinished step with the same revisions.
- A failed operation keeps the applied revision and records the services that already changed.
- The values of an earlier Compose ini become saved values once. A saved value stays.
- The settings page of the operator portal (`https://operator.<suffix>/settings.html`) edits the saved values, shows the hardware suggestions, the pending changes, the affected services and the Apply operation, and offers Retry and Abandon.
  [platform/operator/apply.py](platform/operator/apply.py) names the steps of an Apply. The operator runner (unit `hoover4-operator-runner` of the operator user) runs them.
  A failed operation waits for Retry or Abandon. A restarted runner continues a running operation.
- The zone settings `app.<name>` turn openDesk applications and Hoover off and on. An application that is off has zero replicas and keeps its claims.
  The zone memory limits and the cluster CPU policy reach the zone render through [zones/postrender.py](zones/postrender.py).
- The backup policies are settings: `backup.opendesk.*` and `backup.hoover.*` of each zone, and `backup.platform.*` of the cluster.
  The site file `[backup]` names the destination. Without it the portal keeps the backup controls off.

## Run the tests.

```sh
k3s/tests/run.sh             # render, state and driver
k3s/tests/run.sh replay      # the workflow replay suite in the hoover4-worker container
```

The render, state and driver suites run in a container with the repository mounted read-only.
The driver suite uses fake ssh, sudo, bash and kubectl commands and contacts no host.
They change nothing on the host or a cluster.
