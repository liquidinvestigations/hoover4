# Cluster deployment

This folder holds the code that runs Hoover and openDesk on k3s.
The Compose deployment of [`./deploy`](../docs/operations/Deploying.md) stays available beside it.
The images of the cluster come from commits of this repository.

## Find the parts.

| Folder or file | Purpose |
|---|---|
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
Git ignores it. The scripts of `platform/`, `zones/`, `hosts/` and `cluster/` still read `private/settings.json` and `private/hosts.json`.
`config.legacy_hosts()` writes the `hosts.json` form of a site file.

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

## Run the tests.

```sh
k3s/tests/run.sh             # render and state
k3s/tests/run.sh replay      # the workflow replay suite in the hoover4-worker container
```

The render and state suites run in a container with the repository mounted read-only.
They change nothing on the host or a cluster.
