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
| [migration/](migration) | Moves a stopped Compose installation into a Hoover installation of the cluster ([migrate.py](migration/migrate.py)). |
| [platform/mcp-relay/](platform/mcp-relay) | Serves the MCP servers, the interfaces and the stores of one installation on the loopback ports of the home node. |
| [platform/gpu/](platform/gpu) | Runs the GPU services on the GPU nodes of a site, behind an authenticated gateway. |
| [platform/backups/](platform/backups) | Runs the optional backups and restores a copy into an isolated target. |
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

- `up` installs the hosts, k3s, the pinned operator tools, the cluster services, the registry, the images, the ingress, the HTTPS frontend, monitoring, the operator portal and runner, the GPU proxy, each zone and the calls services, in this order.
  The registry step runs before the image step, so each push has a target.
- The driver resolves `--revision` once. The record of the run keeps the commit, and every step and node gets it.
  The images carry this commit. Local changes of the checkout stay unchanged, and the record lists them.
- Each run has a record in `<operator state>/deploy/records/`. A failed or stopped run keeps its finished steps.
  `deploy-k3s up --resume <record>` continues at the first unfinished step with the same revision.
- A finished `up` of every node, without `--steps`, becomes `deploy/applied.json`. Its image references are digests in the registry.
  The earlier applied record moves to `deploy/previous.json`, so a failed update can return to its revision with `up --revision`.
- `down` scales the zone gates and the login proxy of each Hoover installation to zero, then the applications and workers, then Temporal, then the stores, and then stops the HTTPS frontend and k3s.
  The stores tier holds the databases, Keycloak, the LDAP server and the ingress controller, because the applications and the gates need them at start.
  `deploy/stopped.json` keeps the replica counts. `up --start` starts k3s and the HTTPS frontend, then restores the stores, Temporal, the applications and the gates in this order.
  The workers end through their grace period, and no workflow is cancelled.
- The tools step installs pinned downloads from [driver/artifacts.json](driver/artifacts.json) into `private/bin/`.
  The platform scripts use Helm 4. The openDesk helmfile uses Helm 3 from `private/bin/opendesk/`.
- The calls step runs after the zones, because the calls services read Secrets of the zones.
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
The frontend step adds the local CA to the trust store of the host and to the NSS stores of the operator user, so a browser of the host trusts the site.
`tools/write-password-table.py` writes the logins of the site into `private/passwords.md`.
`tools/local-site-check.py [--restart]` checks the storage, a registry pull and a restart of the host services of a single-node site.
`tools/zone-data-check.py <zone> write|read` writes one item into each openDesk application of a zone and reads it back.

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
  `tools/operator-settings-check.py` drives the page in a browser: an invalid value, a save, Apply, Retry, Abandon and Use default.
- The zone settings `app.<name>` turn openDesk applications and Hoover off and on. An application that is off has zero replicas and keeps its claims.
  The zone memory limits and the cluster CPU policy reach the zone render through [zones/postrender.py](zones/postrender.py).
- The backup policies are settings: `backup.opendesk.*` and `backup.hoover.*` of each zone, and `backup.platform.*` of the cluster.
  The site file `[backup]` names the destination. Without it the portal keeps the backup controls off.

## Reach an installation from the workstation.

`platform/mcp-relay/install-relay.py <installation> apply` runs the Deployment `mcp-relay` with runc in the host network of the home node.
It listens on 127.0.0.1 only and forwards each port to a Service of the installation: the five MCP servers, the Temporal, ClickHouse and Manticore interfaces, the stores and the research agents.
`kubectl port-forward` does not reach a pod in gVisor, so the relay replaces it.

- `--ports compose` uses the ports of the Compose install of the installation, so `.mcp.json` and the harness files stay unchanged.
- `--ports temporary` adds 1000 to each port, so a check can run while Compose still holds its ports.
- The relay keeps the chosen mode in `<operator state>/mcp-relay.json`. The driver step `mcp-relay` applies it again.
- `tools/mcp-relay-check.py <name>=<port> ...` sends the MCP requests of a development client to each port.

The website of an installation is `https://hoover.<zone>.<suffix>/`. A user signs in through the Keycloak of the zone.
The browser harness (`website/take-screenshots.sh`) runs Chromium in a container that must reach that name and trust the local CA.
`tools/harness-browser.sh start` runs the container `hoover4-harness-browser` from the Compose image of the browser server, in the host network, with the local CA as a Chromium policy.
Set `BROWSER_CONTAINER=hoover4-harness-browser`, pass `--target https://hoover.<zone>.<suffix>`, and give a zone login in `HOOVER4_TEST_USERNAME` and `HOOVER4_TEST_PASSWORD`.

## Move a Compose installation into the cluster.

Add a `[hoover.<name>]` section with `source_ini`, the `hoover4.ini` of the Compose install, and run the steps of [migration/migrate.py](migration/migrate.py) in order.
Each step records its result in `<operator state>/migration/<name>-<run>/`, and a finished step does not run again.

```sh
python3 k3s/migration/migrate.py plan <name> --dry-run   # the folders, the claims, the owners, the images and the space
for step in plan freeze record stop images copy secrets stores temporal workers resume; do
  python3 k3s/migration/migrate.py "$step" <name> || break
done
python3 k3s/migration/migrate.py users <name>             # a zone user for each owner of chats and boards
python3 k3s/platform/mcp-relay/install-relay.py <name> apply --ports compose
```

- `freeze` stops the website, its sign-in proxy and the MCP and agent servers, and then the workers with their grace period.
- `record` keeps the Temporal namespaces, search attributes, counts and open workflows, the histories of the open workflows and the store contents.
- `stop` stops Temporal and then the stores. The source data folders stay unchanged, and nothing deletes them.
- `images` imports the store and Temporal images of the source into k3s, and checks their content ids.
- `copy` copies each folder into its claim, maps the owners of the rootless Podman runtime, and verifies a SHA-256 of every file before any target service starts.
- `stores` starts only the stores and Temporal, and compares the store contents with the record. A table with a TTL clause can hold fewer rows, because ClickHouse removes expired rows at start.
- `temporal` compares the Temporal namespaces, search attributes, counts and open workflows with the record. The workers start only after it passes.
- `resume` waits until every open workflow of the record has new events or has closed.

To return to Compose before the target takes new work, delete the claims of the target installation and run `./deploy`.
After the target takes new work, a return to Compose loses that work.

## Run the GPU services on GPU nodes.

A site with `[gpu_pool] nodes = <GPU nodes>` runs the GPU services on those nodes ([platform/gpu/gpu_pool.py](platform/gpu/gpu_pool.py), driver step `gpu-pool`).
A site with `[gpu_pool] address` uses a GPU host outside the site, for example the Compose GPU host of this workstation.

1. The node needs the NVIDIA driver and the NVIDIA container toolkit. `hosts/root-install-k3s.py` refuses a GPU node without them.
2. `root-install-k3s.py` registers the runtime `runsc-nvproxy` (gVisor with GPU support), and labels and taints the node `hoover.dev/gpu=true`.
3. `images/build-hoover.py --gpu` builds the images of the GPU services for the architecture of the GPU nodes.
4. The operator setting `gpu.runtime` selects `runsc` (RuntimeClass `gvisor-gpu`) or `runc` (RuntimeClass `nvidia`).

When the GPU services fail in gVisor, build runsc with gVisor PR 16643 with `hosts/stage-runsc-nvproxy.sh <arch> <staging folder>` on a host of the node architecture.
Run `root-install-k3s.py` on the node again, which installs the build. When the services still fail, save `gpu.runtime = runc` and Apply, and record the failure.
The gateway of each GPU node accepts a request only with the pool key of `[gpu_pool] api_key_file`, on every port, and listens on the VPN address of the node for the other installations of the shared pool.

## Place the call services.

The JVB, LiveKit and coturn run on the first node with the role `calls`, else on the first public node.
A media node with a public address advertises it, and the clients send their media straight to it: UDP 10000 (JVB), TCP 7881 and UDP 7882 (LiveKit), UDP and TCP 3478 (TURN).
`python3 k3s/platform/calls/public_endpoints.py show` prints the DNS records and the firewall ports of each node, and `deploy-k3s render` includes them.
Run `hosts/root-install-public-firewall.sh` on the public node and on the calls node.

Check a call from outside the site after a remote installation:

1. Join a meeting at `https://meet.<zone>.<suffix>/` from a computer outside the VPN, and a second participant from another network.
2. Run `tools/call-check.py <zone>` with `LAB_SUFFIX`, `LAB_KUBECONFIG`, `LAB_USER` and `LAB_PASSWORD_FILE` of the remote site.
3. The check passes when the JVB counts the conference and the ICE candidate of the browser is the public address of the media node.

## Back up and restore.

Backups are off until the site file has `[backup]`, the destination folder has its marker, and an operator turns a policy on in the portal.

```sh
python3 k3s/platform/backups/backups.py enable    # writes the marker .hoover4-backup-destination into the destination
python3 k3s/platform/backups/backups.py status
python3 k3s/platform/backups/backups.py verify <copy folder>
python3 k3s/platform/backups/backups.py restore-hoover <copy folder> <installation>
python3 k3s/platform/backups/backups.py restore-volumes <copy folder> <namespace>
```

- The operator runner starts at most one due job each minute. [schedule.py](platform/backups/schedule.py) holds the rules: eligibility, the weekly limit, the slots and the retention.
- A Hoover collection gets a copy after its first completed ingestion and after each complete reprocessing, at most once in 7 days, and keeps one or two copies.
- openDesk and the platform recovery set get one copy each week, and keep two or three copies.
- A missing marker pauses every job, so a missing remote mount does not fill the local disk.
- Make sure that the destination is on another site. The system cannot check this.
- Each copy has `copy-manifest.json` with the SHA-256 of every file. A collection copy also holds the `manifest.json` of the export, which the import reads.
- A collection copy fails when the JSON metadata of a Manticore table in the export does not parse, because the import refuses it.
- An openDesk copy keeps one tar file for each claim, with the owners and modes. A Block claim of a Kata store is read through its store container, so the store must run. A claim that a pod owns holds temporary files and is not copied.
- `restore-hoover` imports into an installation without that collection, or into a collection whose stores `drop_collection_database` removed.
- A restore of an openDesk copy writes its claims into a new namespace with the same volume modes. A Block claim is written through a Kata pod, which makes its file system. The database dumps restore with `psql` and `mariadb` in that namespace.

## Run the tests.

```sh
k3s/tests/run.sh             # render, state and driver
k3s/tests/run.sh migration backup
k3s/tests/run.sh replay      # the workflow replay suite in the worker image
```

The render, state and driver suites run in a container with the repository mounted read-only.
The driver suite uses fake ssh, sudo, bash and kubectl commands and contacts no host.
They change nothing on the host or a cluster.
