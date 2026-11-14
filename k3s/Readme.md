# Cluster deployment

This folder holds the code that runs Hoover and openDesk on k3s.
The Compose deployment of [`./deploy`](../docs/operations/Deploying.md) stays available beside it.
The images of the cluster come from commits of this repository.

## Find the parts.

| Folder or file | Purpose |
|---|---|
| [deploy-k3s](deploy-k3s) | Installs, updates, stops, starts and checks a site. [driver/](driver) holds its modules. |
| [config.py](config.py) | Reads and checks the site file, a YAML Ansible inventory, gives the variables of the host plays and the part of the site that each node receives, and reads the `hoover4.ini` of an earlier Compose install. |
| [hoover/](hoover) | Renders the Kubernetes objects of a Hoover installation from the Compose files ([manifests.py](hoover/manifests.py)), writes its `hoover4.ini` ([zone_ini.py](hoover/zone_ini.py)), prepares its stores and Secrets ([setup.py](hoover/setup.py)), and holds the GPU proxy ([gpu.py](hoover/gpu.py)). |
| [Compose_Parity.md](Compose_Parity.md) | Names the cluster form of every Compose service and volume folder. |
| [platform/operator/settings.py](platform/operator/settings.py) | Holds the operator settings registry, the saved and applied revisions, and the apply operations. |
| [platform/](platform) | Installs the registry, the ingress, the HTTPS frontend, the calls services, monitoring, the operator portal and runner, and the Hoover data servers. |
| [zones/](zones) | Installs and changes the openDesk zones. |
| [ansible/](ansible) | Prepares the hosts and installs k3s on them: a vendored fork of `k3s-ansible` with the hoover4 roles and playbooks ([UPSTREAM.md](ansible/UPSTREAM.md)). |
| [images/operator/](images/operator) | The operator image, in which `deploy-k3s` runs the driver, Ansible, `kubectl` and `helm`. |
| [hosts/](hosts) | Holds manual host tools: the SSH key login, the NVMe volume group and the runsc build with GPU support. |
| [cluster/](cluster) | Installs the cluster services that every zone uses: RuntimeClasses, cert-manager and TopoLVM. |
| [images/](images) | Builds the images and pushes them to the cluster registry. |
| [migration/](migration) | Moves a stopped Compose installation into a Hoover installation of the cluster ([migrate.py](migration/migrate.py)). |
| [platform/mcp-relay/](platform/mcp-relay) | Serves the MCP servers, the interfaces and the stores of one installation on the loopback ports of the home node. |
| [platform/gpu/](platform/gpu) | Runs the GPU services on the GPU nodes of a site, behind an authenticated gateway. |
| [platform/backups/](platform/backups) | Runs the optional backups and restores a copy into an isolated target. |
| [tools/](tools) | Holds checks and operator tools. |
| [tests/](tests) | Holds the test suites and their fixtures. |

The state folder of a site holds the secrets, the kubeconfigs, the zone state, the operator state and the generated files.
It is beside the site file and has the name of the file without its extension (`config.state_folder()`), for example `private/demo/` for `private/demo.yml`.
One checkout manages more than one site, each with its own site file and state folder. Git ignores `private/`.
Every command needs the site file: `--site FILE`, else `HOOVER4_SITE`. No command has a default site file.
The scripts of `platform/`, `zones/`, `hoover/`, `tools/` and `cluster/` read the site file and every private path through [settings.py](settings.py), whose `PRIVATE` is the state folder of `HOOVER4_SITE`.
`config.legacy_settings()` gives the values of the earlier `settings.json`, and `config.legacy_hosts()` gives the `hosts.json` form.
A site file that does not exist gives the values of `settings.json` of its state folder.

## Write the site file.

The site file is a YAML Ansible inventory with one group, `hoover4`. The group variables are the site values, and each host of the group is one node with its values as host variables.
It names the resources of the installation, the roles of its nodes and the host changes that the installer makes on each node.
It holds no SSH address, port or user, and no port of a service, tuning, application switch, backup schedule or secret value.
It does not state the facts of a host. The facts play reads them on each node (see "Read the host facts").
[tests/fixtures/](tests/fixtures) has a single-node and a remote example.

```yaml
hoover4:
  vars:
    domain: k8.example.org
    control_plane: server-a
    networks:
      site: {cidr: 10.0.0.0/24, hubs: [edge]}
    lans:
      office: {cidr: 192.0.2.0/24}
    backup: {node: server-a, path: /srv/hoover4-backups}
  hosts:
    server-a:
      node_roles: [control-plane, worker, registry, data]
      networks:
        site: {address: 10.0.0.2, public_key: '<WireGuard public key>'}
      lan: {office: 192.0.2.10}
      storage: {hdd: vg-hdd, nvme: vg-nvme}
      k3s_volume_group: vg-nvme
```

| Place | Keys |
|---|---|
| `hoover4.vars` | `domain`, `control_plane`, and optional `networks`, `lans`, `gpu_pool`, `backup` |
| `hoover4.vars.networks.<name>` | `cidr`, and optional `interface` (default `wg0`), `hubs`, `port` (default 51820), `managed` (default true) |
| `hoover4.vars.lans.<name>` | optional `cidr` |
| `hoover4.hosts.<name>` | `node_roles`, and optional `local`, `ssh_host`, `networks`, `lan`, `public_address`, `storage`, `k3s_volume_group`, `stop_docker`, `public_firewall`, `reserved`, `data_root`, `tls_mode`, `tls_dns_credentials_file`, `tls_certificate_file`, `tls_key_file` |
| `hoover4.hosts.<name>.networks.<network>` | an address, or `address` and optional `public_key`, `interface`, `port`, `managed`, which replace the values of the network for this node |
| `hoover4.vars.gpu_pool` | `nodes` or `address` |
| `hoover4.vars.backup` | `node` and `path` of the backup destination |

The site id is the domain with each `.` replaced by `-`, for example `k8-example-org`. Each command prints it with the site file and the state folder.
A list value is a YAML list or a text with commas. Ansible reserves the variable name `roles`, so the node roles have the key `node_roles`.
The roles are `control-plane`, `worker`, `public`, `registry`, `data`, `calls` and `gpu`.
The value `single` gives one host every role except `calls` and `gpu`.
A site with one node needs no network, no LAN address and no public address.
A GPU node has no other role. A key that ends with `_file` names a private file on the node that has the matching role.
`tls_mode` of the first public node selects the certificates of the HTTPS frontend. `config.py check` refuses a missing key of the selected mode.

| `tls_mode` | Keys | Certificates |
|---|---|---|
| `cloudflare` | `tls_dns_credentials_file` | certbot gets a public certificate for `*.<domain>` and `<domain>` with the Cloudflare DNS challenge. |
| `internal` | No key. | Caddy issues the certificates from its local CA. The frontend step copies the root certificate into `frontend/local-ca.crt` of the state folder. The pods trust it. Install that file in each browser that opens the site. |
| `files` | `tls_certificate_file`, `tls_key_file` | Put a certificate and its key on the node. The certificate must have the name `*.<domain>`. |

The default is `internal` on the local node, which has no other mode, and `cloudflare` on another node.
`extra_datasets` names read-only dataset folders of data nodes as `name:node:/path`, separated by commas. The NFS server of the node exports each one, and the installation mounts it at `/data/<name>`.
### Give each tier its own volume group.

`storage` maps each storage tier (`hdd`, `ssd`, `nvme`) of a node to a volume group. The person creates each volume group before the deployment.
The installer changes no disk, no partition and no existing file system. Two tiers of one node need two volume groups.
TopoLVM gives each node its own lvmd configuration, with one device class per tier on its volume group.
The facts play refuses a volume group that the node does not have.
The device class of each tier keeps 5 % of its volume group free (`spare-gb`), so the cluster schedules at most 95 % of each tier on each node.
The facts give the size of each group. The k3s data volumes of `k3s_volume_group` do not count.

### Turn the host changes on or off.

| Key | Default | Change on the node |
|---|---|---|
| `networks.<name>.managed` | true | Write and start a missing WireGuard interface, and add the peers of the network to it. With false, the installer changes nothing on the interface. |
| `stop_docker` | false | Stop and disable Docker. With false, the host play reports enabled Docker units and keeps them. |
| `k3s_volume_group` | empty | Create the logical volumes `rancher` and `kubelet` in this volume group and mount them at `/var/lib/rancher` and `/var/lib/kubelet`. Existing volumes of these names stay. |
| `public_firewall` | true on a `public` or `calls` node with a `public_address` | Install the host firewall of the role `hoover4_public_firewall`. |

`public_firewall` installs two parts. The media node of the call services gets the chain `coturn_peers` in its own table `inet hoover_coturn_peers`.
A node whose public address is on another interface than its node address also gets the drop rules of the k3s ports and the input filter of the public interface.
A node that uses one interface for both, for example a LAN node, does not get them, because they would drop the cluster traffic of the other nodes.
`config.py check` and `deploy-k3s check` print the switches of each node.

### Connect the nodes.

The first network of `vars.networks` is the cluster network: each node uses its address there as its node address and the interface of the network for flannel.
A site without networks connects its nodes at their LAN addresses (`lan`), and flannel uses the interface that holds the address on the node.
A network without `hubs` gives every node a direct peer for every other node.
With `hubs`, a hub peers with every node of the network. Another node peers with each hub and with each node on one of its LANs.
A LAN peer uses the LAN address as its endpoint, else a peer with a `public_address` uses that address. A peer without either has no endpoint and waits for the handshake of the other node.
A managed node that is no hub reaches each other managed node without a direct peer through the first hub. Both add the address of the other node to the AllowedIPs of the hub peer.
A node with `managed: false` keeps the routes of its own VPN, and its `public_key` must be in the site file.
The person adds its peers by hand. The peer table of `config.py check` and `deploy-k3s check` lists them with `by: hand`.
A managed node without `public_key` gets a new interface with a new key. The play then stops and names the key for the site file. The other nodes add their peer after the next run.
The play adds addresses and peers and removes none, so an existing route, for example to a VPN hub outside the site, stays.
The cidr of each network, and of each LAN that states one, reaches the admin routes of the HTTPS frontend.

### Read the host facts.

The facts play (role `hoover4_facts`) reads each node and writes `facts/<node>.json` of the state folder: the architecture (`uname -m`), AVX2 (`/proc/cpuinfo`), the name and memory of each GPU (`nvidia-smi`), the size of each volume group and of its k3s data volumes, and the interface of each address.
`deploy-k3s check` and the step `hosts:prepare` run it. The site file has no `architecture` and no `avx2`.
The cluster step labels the nodes from the facts: `cpu.hoover/avx2=true`, `gpu.hoover/count` and `gpu.hoover/memory-mib` (the memory of the smallest GPU of the node). A node without the fact loses the label.
The cluster step and the image steps stop with the name of a node that has no facts.

Check a site file, or print the part that one node receives:

```sh
python3 k3s/config.py check k3s/private/<site>.yml
python3 k3s/config.py project k3s/private/<site>.yml <node>
python3 k3s/config.py source /path/to/hoover4.ini
python3 k3s/config.py ansible k3s/private/<site>.yml
```

`ansible` prints the variables that the driver gives to the host plays. A YAML site file needs PyYAML. The operator image has it.

### Create and delete zones.

The site file names no zone. The zone state `zone-state.json` holds the zones, and [zones/zone.py](zones/zone.py) and the operator portal change it.
The cluster holds the authoritative zone state (see [the cluster copy of the state](#keep-the-state-in-the-cluster)). `zone.py` takes the site operation lock, reads the cluster copy into the state folder and writes its changes back.

```sh
python3 k3s/zones/zone.py apply zone-x --home <node> [--stores zone|local] [--temporal-backend postgresql|cassandra] [--dataset name:node:/path]
python3 k3s/zones/zone.py delete zone-x
```

- The home node needs the role `worker`. Every pod and volume of the zone stays on it.
- `stores` and `temporal_backend` have the defaults `zone` and `postgresql`. `--dataset` adds a read-only dataset folder of a data node. These values apply to a new zone, and a change of an existing zone is refused.
- The Hoover installation of a zone has the name of the zone. Its storage names come from the zone id: for `zone-x` the ClickHouse database prefix `zone_x`, the Manticore table prefix `zone_x_`, the system bucket `zone-x-system` and the collection bucket prefix `zone-x-c-`. No file stores them.
- `deploy-k3s up` applies each zone of the zone state again, after the platform steps.

### Name the zone hosts.

Each zone host has one label below the domain, `<zone>-<app>.<domain>` ([config.py](config.py) `zone_host()`). An example is `zone-x-portal.example.org`.
The certificate of `*.<domain>` and the DNS record of `*.<domain>` cover every zone, so a zone create or delete changes no certificate, no DNS record and no frontend file.

- The openDesk values of a zone set `global.domain` to the domain and each `global.hosts` entry to `<zone>-<default host>` ([zones/zones.py](zones/zones.py)). The home chart of openDesk serves `global.domain` itself, so no zone installs it.
- The mail domain and the Matrix server name of a zone stay `<zone>.<domain>`. The zone domain serves the Matrix well-known files.
- The intercom service of a zone answers the cross-origin requests of the hosts of its own zone only.
- The gate of a zone signs in at `<zone>-auth.<domain>` ([zones/gate.py](zones/gate.py)). Its cookie has the domain `.<domain>` and the name `_hoover_gate_<zone>`.
  One sign-in opens every host of the zone. The gate of another zone does not accept the cookie.
- The HTTPS frontend serves the one site `*.<domain>` ([platform/frontend/frontend-sync.sh](platform/frontend/frontend-sync.sh)). It takes the zone id from the host name and asks the gate of that zone. It removes the gate cookies from the requests to the applications. Another name below the domain gets 404.
- `python3 k3s/platform/calls/public_endpoints.py dns` prints the records `*.<domain>`, `<domain>` and `turn.<domain>`.

## Deploy a site.

`deploy-k3s` is the one command of a site. The workstation needs Python 3 and `podman` or `docker`.

```sh
k3s/deploy-k3s render --site <file> --target all   # prints the configuration, the inventory and the steps. Changes no host.
k3s/deploy-k3s check --site <file> --target all    # reads the facts of the nodes and checks the files and the tools
k3s/deploy-k3s up --site <file> --target all [--ask-become-pass]
k3s/deploy-k3s down --site <file> --target all
k3s/deploy-k3s up --site <file> --target all --start
k3s/deploy-k3s status --site <file>
```

- `deploy-k3s` computes a digest of the inputs of [images/operator/](images/operator) and of [ansible/requirements.yml](ansible/requirements.yml), and builds the image `localhost/hoover4-operator:<digest>` when it is missing.
  It then runs one container with `--rm` for the command. The container mounts the checkout read-only at its own path, the folder of the site file read-write, `~/.ssh` read-only, the SSH agent socket and the runtime folder of the user for the podman service.
  It runs with the UID of the user and the network of the host. `HOME` is `/tmp/home` of the container, so no tool writes into the checkout. Inside it, `HOOVER4_OPERATOR_IMAGE=1` makes `deploy-k3s` run the driver ([driver/deploy.py](driver/deploy.py)).
- `up` runs the host steps, then the pinned operator tools, the cluster services, the registry, the images, the ingress, the HTTPS frontend, monitoring, the operator pod (the portal and the zone runner), the GPU proxy, each zone and the calls services, in this order.
  The registry step runs before the image step, so each push has a target.
- The host steps are one Ansible run each on all target nodes. The site file is the inventory.
  The driver gives the values that it derives from the site file as the extra variable `hoover4_nodes`.
  [ansible/playbooks/group_vars/hoover4.yml](ansible/playbooks/group_vars/hoover4.yml) gives each value to its node as a `hoover4_*` variable.
  `hosts:prepare` runs [ansible/playbooks/hoover4-hosts.yml](ansible/playbooks/hoover4-hosts.yml): the facts of each node into `facts/<node>.json` of the state folder, the packages of the node in one task, Docker (`stop_docker`), the kernel modules, sysctl, NetworkManager, SELinux, the k3s data volumes (`k3s_volume_group`), the local node of a single-node site, the backup folder, the public firewall (`public_firewall`), and the WireGuard interfaces of the managed networks.
  `hosts:k3s` runs [ansible/playbooks/hoover4-k3s.yml](ansible/playbooks/hoover4-k3s.yml): gVisor, Kata Containers and the GPU runtime, the tokens, the k3s configuration and the registry mirror, then k3s on the server and on the agents.
  Each node downloads k3s, its install script, gVisor and Kata Containers itself and verifies the pinned digests of [ansible/roles/hoover4_k3s/defaults/main.yml](ansible/roles/hoover4_k3s/defaults/main.yml).
  A node restarts k3s only when an input file, the binary or a token file changed, or when the unit is not active.
  The server play writes the admin kubeconfig into `kubeconfig` of the state folder, with the node address of the server.
  `hosts:verify` reads every target through that kubeconfig: Ready, the k3s version, the flannel interface, and `cluster-init` and the `etcd` role of the server. A missing kubeconfig fails the step with its path.
- The driver connects to a node with `ssh <node name>` and the SSH configuration of the user of the workstation. `~/.ssh/config` gives the address, the port, the user and the key of that name.
  A node whose `Host` alias differs from its name names the alias in `ssh_host`. New host keys go to `known_hosts` of the state folder.
  `become` uses `sudo` without a password. `--ask-become-pass` asks once for the password of each command.
  The installer adds no SSH key, no sudo rule and no root script to a node. The host play removes `/usr/local/libexec/hoover4`, `/etc/sudoers.d/90-hoover4` and the revision folders of `~/k3s-install` of an earlier installer.
- The tokens of the site are in `staging/tokens/` of the state folder. The server play copies the tokens of a running server into an empty folder, and writes random tokens for a new site.
  A token that differs from the token of a host stops the play before any change, so a host keeps its token.
- Every step runs the scripts of the checkout. The record keeps the commit of HEAD, the path of the checkout and its `git status --porcelain` lines.
  The image step builds the images of that commit from a temporary `git archive` tree, so uncommitted changes stay out of the images.
  The image step also builds the image `hoover/operator:<digest>` of the operator pod ([images/operator-pod/](images/operator-pod)) on the operator image. It holds the files of the checkout that the pod runs, with their uncommitted changes, and the operator tools of `bin/` and `downloads/` of the state folder. The tag is a digest of these files, the tool versions and the base image.
  The control plane needs the architecture of the workstation, because the pod runs the operator image of the workstation.
- Each run has a record in `<operator state>/deploy/records/`. A failed or stopped run keeps its finished steps.
  The record pins the commit, the SHA-256 of the site file, the saved settings revision and the UID of `kube-system`.
  `deploy-k3s up --resume <record>` continues at the first unfinished step with these inputs, and refuses a changed site file, another commit or another cluster.
- The driver holds the site operation lock ([oplock.py](oplock.py)) while it runs. The settings Apply, the zone operations, the migration steps and the openDesk and platform backups take the same lock.
  When the cluster answers, the lock is the Lease `site-operation` of the namespace `operator-portal`, so the workstation and the runner in the cluster exclude each other. A holder renews it every 20 seconds, and a Lease without a renewal for 90 seconds is free. Before the cluster exists, the lock is a file lock of the operator state folder.
  A settings save takes no lock, so a save during a run waits as a later revision.
- A failed step ends the run. A failed play names the nodes of its failed tasks, and the log of the record holds the output of each task.
- A zone step waits until the zone and its Hoover installation have ready workloads, and then records their settings scopes as applied with the pinned revision.
- A zone step then starts a check pod with the OIDC egress label of oauth2-proxy. The pod sends an invalid sign-in code with the client secret of the proxy to Keycloak. The step fails when Keycloak does not answer `invalid_grant`, for example when a NetworkPolicy or a DNS answer blocks the token exchange.
- A finished `up` of every node, without `--steps`, becomes `deploy/applied.json`. Its image references are digests in the registry.
  The earlier applied record moves to `deploy/previous.json`. Check out its commit and run `up` to return to it.
- `down` scales the zone gates and the login proxy of each Hoover installation to zero, then the applications and workers, then Temporal, then the stores, and then stops the HTTPS frontend and k3s.
  The stores tier holds the databases, Keycloak, the LDAP server and the ingress controller, because the applications and the gates need them at start.
  `deploy/stopped.json` keeps the replica counts. `up --start` starts k3s and the HTTPS frontend, then restores the stores, Temporal, the applications and the gates in this order.
  The workers end through their grace period, and no workflow is cancelled.
  The k3s stop and start of each node run [ansible/playbooks/hoover4-service.yml](ansible/playbooks/hoover4-service.yml). The stop also ends the containers of the pods.
  `down` also suspends the CronJobs of the zone namespaces, and the start resumes the CronJobs that it suspended.
- The tools step installs pinned downloads from [driver/artifacts.json](driver/artifacts.json) into `bin/` of the state folder.
  The platform scripts use Helm 4. The openDesk helmfile uses Helm 3 from `bin/opendesk/`.
- The calls step runs after the zones, because the calls services read Secrets of the zones.
- After the conversion of the server from SQLite to etcd, `hosts:verify` restarts the Deployments and DaemonSets of `kube-system`, `ingress`, `cert-manager`, `topolvm-system`, `monitoring` and `operator-portal`.
  Without the restart, CoreDNS, the ingress controller, cert-manager, TopoLVM and the monitoring operators did not see objects that were created after the conversion.
- The etcd snapshot of the platform backup, the restore of a snapshot and the copy of a retired server run [ansible/roles/hoover4_k3s/files/k3s-datastore.py](ansible/roles/hoover4_k3s/files/k3s-datastore.py) with `sudo -n` over SSH ([driver/nodeshell.py](driver/nodeshell.py)).
  The script writes `~/hoover4-snapshots/<name>/` of the user that runs sudo, and takes names only.

The local node of a single-node site gets the dummy link `hoover4` with the address `10.254.54.1`, a dnsmasq for the names below the domain, and the units `hoover4-address`, `hoover4-dns` and `hoover4-frontend`.
k3s and every pod run in `hoover4.slice`. The node value `reserved` sets the memory and CPU that stay with the rest of the host, for example a Compose stack.
The k3s data and the kubelet folder are volumes of the volume group of the node, which the person creates. TopoLVM uses the free space of the group.
The local node connects to `localhost` over SSH unless it has `ssh_host`, so the workstation needs an SSH server for its own user.
The admin kubeconfig is `kubeconfig` of the state folder. k3s writes it as `/etc/rancher/k3s/hoover4-admin.yaml`, because `/etc/rancher/k3s/k3s.yaml` can belong to another k3s user of the host.
A new Hoover installation of a single-node site keeps its dataset folders `testdata` and `uploads` on claims, so it needs no NFS server.
The frontend step adds the local CA to the trust store of the host and to the NSS stores of the operator user, so a browser of the host trusts the site.
`tools/write-password-table.py` writes the logins of the site into `passwords.md` of the state folder.
`tools/local-site-check.py [--restart]` checks the storage, a registry pull and a restart of the host services of a single-node site.
`tools/zone-data-check.py <zone> write|read` writes one item into each openDesk application of a zone and reads it back.

Every k3s server runs embedded etcd (`cluster-init`), also on a site with one node. One server is not highly available.
A server that still runs SQLite converts to etcd at its next `root` step. The installer first stops k3s, copies the datastore, the token and the configuration into `/var/lib/hoover4-recovery/` with `SHA256SUMS`, and reads the copy again.
After each start of the server, the installer verifies etcd with a snapshot. A host that already belongs to a cluster keeps its token: a staged token with another secret stops the installer before any change.

## Adopt a running cluster.

1. `tools/adopt-cluster.py inventory` writes the nodes, namespaces, claims, Secret names, images and storage identities of the cluster into `<operator state>/adoption/` and lists each difference from the site file.
2. `tools/adopt-cluster.py runners` lists the runner units of the earlier tool. Stop them before the first run of this driver.
3. `tools/adopt-cluster.py tokens` copies the tokens of the server into `staging/tokens/` of the state folder.
4. `tools/adopt-cluster.py settings` saves the explicit values of the `hoover4.ini` of each zone of the earlier tool once as operator settings. It lists the keys that this revision does not read.

## Retire the local single-node site.

`tools/local-retirement.py` preserves the local site and writes the removal script. It removes nothing.

1. `inventory <folder>` records the units, mounts, volumes, link, DNS routing, claims and the protected resources.
2. `archive <folder>` stops the site with `deploy-k3s down` without the k3s step, copies each claim, the objects and the state folder, and writes `archive-manifest.json`. It prints the root step that copies the k3s datastore and token (`k3s-datastore.py preserve <name>`). `manifest <folder>` writes the manifest again after that step.
3. `verify <folder>` reads the archive again against its manifest.
4. `removal <folder>` writes `remove-local-k3s.sh`. A person reviews it and runs it as root.
   The script removes the services, units, data, volumes, link and DNS setup of the site. The k3s binary, `kubectl`, `crictl`, `ctr`, the k3s scripts and `/etc/rancher/k3s/k3s.yaml` stay, because another project uses them.

## Choose the stores and the Temporal backend.

| Zone state value | Value | Result |
|---|---|---|
| `stores` | `local` | The Compose stores run in the Hoover namespace on claims of the home node. The operations worker mounts them, so store backup and restore work. |
| `stores` | `zone` | ClickHouse, Manticore and Garage run in Kata on block volumes in the zone namespace, with a user for each service. Existing remote zones use this layout. |
| `temporal_backend` | `cassandra` | Temporal, Cassandra and Elasticsearch run as in Compose, with the dynamic configuration of deploy.py. |
| `temporal_backend` | `postgresql` | Temporal uses the PostgreSQL of the zone. Existing remote zones use this backend. No conversion between the backends exists. |

## Render a Hoover installation.

```sh
python3 k3s/hoover/manifests.py <zone> show --revision <commit>
python3 k3s/images/build-hoover.py --revision <commit>
```

`show` prints the objects and changes nothing.
The argument is the zone. The render reads the addresses of the NFS servers of `platform/hoover-data/` from the cluster.
The image tag is the first 12 characters of the commit. The build exports the commit, so local changes stay out of the images.

## Keep the state in the cluster.

The cluster holds the authoritative zone state, zone secrets and operator state. [clusterstate.py](clusterstate.py) keeps one object for each file in the namespace `operator-portal`.

| Files of the state folder | Objects |
|---|---|
| `zone-state.json`, `operator/` (settings, revisions, Apply operations and their logs, backup and relay state), `operations/` (the logs of the zone operations), `facts/`, `frontend/local-ca.crt` | ConfigMaps with the label `hoover.dev/state=file` |
| `zones/` (the zone secrets, the openDesk values and the master passwords) | Secrets with the label `hoover.dev/state=secret` |

- The annotation `hoover.dev/state-path` of each object names its file. A log keeps its last 256 KiB in the cluster.
- `operator/deploy/` (the records of `deploy-k3s`), the tokens, the kubeconfig and the downloaded tools stay only in the state folder, because the workstation needs them before a cluster exists.
- `deploy-k3s` reads the cluster copy into the state folder after it takes the site lock, and before `render` and `check`. After each step it writes the changed files back. The state folder keeps an export copy for inspection.
- A folder keeps the digest of each file and the `resourceVersion` of its object from the last synchronization. A write of a file that another writer changed fails with a conflict, and the next run reads the newer copy first.
- `python3 k3s/clusterstate.py pull|push <state folder>` reads or writes the copy by hand. `KUBECONFIG` names the kubeconfig.

The operator pod (Deployment `portal` of `operator-portal`) runs the portal and the zone runner from the operator image of the registry ([platform/operator/pod.py](platform/operator/pod.py)).
It mounts no checkout and no host state folder. Each container reads the cluster copy into a folder of the pod at its start. The runner keeps the zone secrets in its own memory folder, so the portal container cannot read them.
The runner uses the token of the ServiceAccount `zone-runner` and needs no SSH access. The HTTPS frontend serves every zone host, so a zone operation does not change it.
A create or upgrade checks that the frontend answers for `<zone>-portal.<domain>` with a valid certificate, and stops at the step `frontend` until it does. `deploy-k3s up --target <public node> --steps frontend` on the workstation installs the frontend.
The runner checks that the registry has the images of the revision. `deploy-k3s up --steps images` builds them.

## Save and apply operator settings.

The operator settings hold every Hoover ini tuning and switch, and the cluster settings of each Hoover installation.
These are the budget, the worker sandbox, the slot tuner, the administrator groups and the volume sizes.
They also hold the openDesk applications and memory limits of each zone, and the CPU policy of the cluster.
`python3 k3s/platform/operator/settings.py list` prints each setting with its type, default, services and apply mode.

- A save names the revision that it changes. A save over a newer revision is refused.
- A save changes no service. Apply starts one operation for the newest revision.
- An operation records each step before and after it runs. A retry continues at its first unfinished step with the same revisions.
- A failed operation keeps the applied revision of each unfinished scope and records the services that already changed. A scope whose steps all finished gets its applied revision at once.
- `gpu.runtime` applies the GPU pool (`gpu_pool.py apply`) and calls each GPU service with and without the pool key (`gpu_pool.py verify`). It changes no zone.
- The values of an earlier Compose ini become saved values once. A saved value stays.
- The settings page of the operator portal (`https://operator.<domain>/settings.html`) edits the saved values, shows the hardware suggestions, the pending changes, the affected services and the Apply operation, and offers Retry and Abandon.
  [platform/operator/apply.py](platform/operator/apply.py) names the steps of an Apply. The runner container of the operator pod runs them.
  A failed operation waits for Retry or Abandon. A restarted runner continues a running operation.
  `tools/operator-settings-check.py` drives the page in a browser: an invalid value, a save, Apply, Retry, Abandon and Use default.
  `tools/operator-portal-shots.py` captures a portal page for the manuals at 1400 by 900 pixels, with the host names and addresses replaced.
- The zone settings `app.<name>` turn openDesk applications and Hoover off and on. An application that is off has zero replicas and keeps its claims.
  The zone memory limits and the cluster CPU policy reach the zone render through [zones/postrender.py](zones/postrender.py).
- The backup policies are settings: `backup.opendesk.*` and `backup.hoover.*` of each zone, and `backup.platform.*` of the cluster.
  `backup` of the site file names the destination. Without it the portal keeps the backup controls off.

## Reach an installation from the workstation.

`platform/mcp-relay/install-relay.py <installation> apply` runs the Deployment `mcp-relay` with runc in the host network of the home node.
It listens on 127.0.0.1 only and forwards each port to a Service of the installation: the five MCP servers, the Temporal, ClickHouse and Manticore interfaces, the stores and the research agents.
`kubectl port-forward` does not reach a pod in gVisor, so the relay replaces it.

- `--ports compose` uses the ports of the Compose install of the installation, so `.mcp.json` and the harness files stay unchanged.
- `--ports temporary` adds 1000 to each port, so a check can run while Compose still holds its ports.
- The relay keeps the chosen mode in `<operator state>/mcp-relay.json`. The driver step `mcp-relay` applies it again.
- `tools/mcp-relay-check.py <name>=<port> ...` sends the MCP requests of a development client to each port.

The website of an installation is `https://<zone>-hoover.<domain>/`. A user signs in through the Keycloak of the zone.
The browser harness (`website/take-screenshots.sh`) runs Chromium in a container that must reach that name and trust the local CA.
`tools/harness-browser.sh start` runs the container `hoover4-harness-browser` from the Compose image of the browser server, in the host network, with the local CA as a Chromium policy.
Set `BROWSER_CONTAINER=hoover4-harness-browser`, pass `--target https://<zone>-hoover.<domain>`, and give a zone login in `HOOVER4_TEST_USERNAME` and `HOOVER4_TEST_PASSWORD`.

## Move a Compose installation into the cluster.

The migration steps of [migration/migrate.py](migration/migrate.py) need a rewrite: the site file names no zone and no Compose install, so the steps below have no target until the Compose import command replaces them.
The steps read the target and its `source_ini` from the earlier site file key `hoovers`.
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
- `--engine docker|podman` names the runtime of the source, and `--source-host` the SSH host of the source. A rootful Docker keeps the host owners, and rootless Podman maps them through its user namespace.
- `plan` writes `inputs.json`: the commit, the settings revision, the site file SHA-256, the engine, the source host, the images and the storage identity. A later step with another input stops.
- `copy` copies each folder into its claim with the mapped owners, and verifies a SHA-256 of every file before any target service starts.
  A home node on this host gets the copy through a mount of the volume. Another home node gets a tar stream into a pod that mounts the claim, and the check runs in that pod. The record keeps the UID and volume of each claim.
- `stores` starts only the stores and Temporal, and compares the store contents with the record. A table with a TTL clause can hold fewer rows, because ClickHouse removes expired rows at start.
- `temporal` compares the Temporal namespaces, search attributes, counts and open workflows with the record. The workers start only after it passes.
- `resume` waits until every open workflow of the record has new events or has closed.

To return to Compose before the target takes new work, delete the claims of the target installation and run `./deploy`.
After the target takes new work, a return to Compose loses that work.

## Run the GPU services on GPU nodes.

A site with `gpu_pool` `nodes: <GPU nodes>` runs the GPU services on those nodes ([platform/gpu/gpu_pool.py](platform/gpu/gpu_pool.py), driver step `gpu-pool`).
A site with `gpu_pool` `address` uses a GPU host outside the site, for example the Compose GPU host of this workstation.
A site without `gpu_pool` has no GPU services and no GPU proxy. Its Hoover installations get no forwarder `gpu`, and their GPU endpoints are empty.

1. The node needs the NVIDIA driver. The k3s play refuses a GPU node where `nvidia-smi -L` fails. The host play installs the NVIDIA container toolkit from the NVIDIA repository when the node does not have it.
2. The k3s play registers the runtime `runsc-nvproxy` (gVisor with GPU support), and labels and taints the node `hoover.dev/gpu=true`.
3. The driver step `gpu-images` builds the images of the GPU services for the architecture of the GPU nodes and checks that architecture in the registry. A GPU node of another architecture than this host builds them (`--builder`).
4. The operator setting `gpu.runtime` selects `runsc` (RuntimeClass `gvisor-gpu`) or `runc` (RuntimeClass `nvidia`).

When the GPU services fail in gVisor, build runsc with gVisor PR 16643 with `hosts/stage-runsc-nvproxy.sh <arch> <state folder>` on a host of the node architecture.
Copy `runsc-nvproxy/` into the state folder of the workstation, then run `deploy-k3s up --target <node> --steps hosts:k3s`, which installs the build. When the services still fail, save `gpu.runtime = runc` and Apply, and record the failure.
The step `gpu-pool` waits for the GPU workloads and calls each port with the key, which must answer, and without it, which must answer 403.

## Share one GPU key.

The installation has one GPU key. The operator step generates it once and keeps it in the Secret `gpu-api-key` of the namespace `operator-portal`. The site file names no key.

- The model server, the AI server and EasyOCR read the key from `HOOVER4_GPU_API_KEY` and refuse to start without it. Each checks `Authorization: Bearer <key>` on every route except `/health`. The model server checks it with `--api-key`.
- The gateway of each GPU node checks the key on every port too, and listens on the node address for the other installations of the shared pool.
- The GPU proxy (`hoover/gpu.py`) sends the key on every port. The token of each zone is the HMAC-SHA256 of the zone name with the GPU key.
- The operator portal shows the key with a copy control. A GPU host outside the cluster, for example a Compose GPU host at `gpu_pool` `address`, needs the same key in the file of its `[ai_services] vllm_api_key_file`.
- `hoover/gpu.py set-key` replaces the key with the key on standard input, for example the key of an existing Compose GPU host. A new key changes every zone token. Run `hoover/gpu.py install`, `platform/gpu/gpu_pool.py apply` and `zones/zone.py apply` of each zone after it.

## Place the call services.

The JVB, LiveKit and coturn run on the first node with the role `calls`, else on the first public node.
A site without a zone runs only coturn, because LiveKit needs the key of a zone, and the JVB copies its template from a zone.
A media node with a public address advertises it, and the clients send their media straight to it: UDP 10000 (JVB), TCP 7881 and UDP 7882 (LiveKit), UDP and TCP 3478 (TURN).
coturn relays UDP only, so a TURN user reaches no store of a zone, which all serve TCP.
It relays to the pods of the media node and, on a media node with a public address, to that address for a client that can only use TURN.
The pods of the other nodes and the bridge address of the media node are no peers ([platform/calls/turn_peers.py](platform/calls/turn_peers.py)).
The chain `coturn_peers` of [coturn-peers.sh](ansible/roles/hoover4_public_firewall/files/coturn-peers.sh), in its own table, limits the public address to the LiveKit media ports for the coturn user, so a TURN user reaches no other port of the node.
The steps `operator` and `calls` of `deploy-k3s up` check that chain with a probe pod in the host network of the media node (`install-calls.py --probe`).
They record the result in the ConfigMap `coturn-peer-check` of `calls`.
The pod admission policy of `calls` refuses a host network pod other than coturn, so the probe pod runs in `kube-system` with the admin kubeconfig.
The step `calls`, also in a portal zone operation, adds the public address only when that record names the media node and its address.
Without the record, the step stops and names `deploy-k3s up --steps operator`.
The JVB port is not in that rule, so a Jitsi client that can only use TURN reaches the JVB through its pod address only.
`python3 k3s/platform/calls/public_endpoints.py show` prints the DNS records and the firewall ports of each node, and `deploy-k3s render` includes them.
The switch `public_firewall` of the site file installs the role `hoover4_public_firewall` on the public node and on the calls node (see "Turn the host changes on or off").
The role installs the chain `coturn_peers` on the media node also when the public address is on the interface of the node address, for example on a LAN site.
`public-firewall.sh` starts a rollback timer of 180 seconds. The role confirms the table after a new SSH connection works.
On a site with `public_firewall: false` on the media node, the probe fails, and the `calls` step stops until the chain exists.

Check a call from outside the site after a remote installation:

1. Join a meeting at `https://<zone>-meet.<domain>/` from a computer outside the VPN, and a second participant from another network.
2. Run `tools/call-check.py <zone>` with `LAB_SUFFIX`, `LAB_KUBECONFIG`, `LAB_USER` and `LAB_PASSWORD_FILE` of the remote site.
3. The check passes when the JVB counts the conference and the ICE candidate of the browser is the public address of the media node.

## Back up and restore.

Backups are off until the site file has `backup`, the destination folder has its marker, and an operator turns a policy on in the portal.
The `backup` node holds the backup folder (`path`). The capacity check, the marker check, the check of each copy and retention run on that node over its user shell.
The commands take names: a zone, a collection, a job and a generation (the name of a copy). No command takes a host path.

| Copy | Folder below the backup folder |
|---|---|
| A complete zone: openDesk and its Hoover installation | `zones/<zone>/<generation>/` |
| A Hoover collection of a zone | `zones/<zone>/collections/<collection>/<generation>/` |
| The platform recovery set | `platform/<generation>/` |

```sh
python3 k3s/platform/backups/backups.py enable    # writes the marker .hoover4-backup-destination and the folders
python3 k3s/platform/backups/backups.py status
python3 k3s/platform/backups/backups.py copies
python3 k3s/platform/backups/backups.py verify zone:<zone> <generation>
python3 k3s/platform/backups/backups.py restore-zone <zone> <generation> [--from <zone of the copy>]
python3 k3s/platform/backups/backups.py restore-hoover <zone> <collection> <generation> [--from <zone of the copy>]
python3 k3s/platform/backups/backups.py recovery <generation>
python3 k3s/platform/backups/backups.py restore-platform <generation>
```

- The operator runner starts at most one due job each minute. [schedule.py](platform/backups/schedule.py) holds the rules: eligibility, the weekly limit, the slots and the retention.
- A Hoover collection gets a copy after its first completed ingestion and after each complete reprocessing, at most once in 7 days, and keeps one or two copies.
- Each zone and the platform recovery set get one copy each week, and keep two or three copies. The portal setting `backup.opendesk.*` controls the zone copy.
- A missing marker pauses every job, so a missing remote mount does not fill the local disk.
- A copy is made in `<operator state>/backups/staging/`, checked, sent to the node into `<generation>.partial`, checked there and renamed. A failed transfer or check keeps the older copies.
- A restore reads a copy on the operator host in place, or fetches it into `<operator state>/backups/restore/`.
  A fetched copy must have the manifest of the copy on the backup node, and every file must match that manifest.
- Each tar stream from a pod must reach its end-of-archive marker, and each database dump must end with the end line of its dump tool. Otherwise the copy reads that part again, up to three times.
- The platform copy holds an etcd snapshot of the server with its token and k3s configuration, `private.tar`, and `recovery.json` (format version 2). `recovery.json` names the application copies that a complete recovery needs, because a snapshot holds no claim data. `recovery` also reads a copy of the earlier SQLite format.
  The snapshot runs `k3s-datastore.py snapshot <name>` with `sudo -n` on the server, which writes `~/hoover4-snapshots/<name>/` of the operator user. The operator user needs sudo without a password on the control plane.
- The zone copy closes the zone first. The applications, gates and workers of the zone and its Hoover installation scale to zero.
  Their CronJobs are suspended, and the stores keep running. After the copy, the recorded replicas and suspensions return.
  The next runner tick restores a closure that a stopped job left. The earlier job key `opendesk:<zone>` reads as `zone:<zone>`.
- The receipt queries use the ClickHouse of the store layout. The zone layout uses the zone user in the zone namespace. The local layout uses the Compose credentials.
- The collection export reads each small frozen Manticore file whole, and a `.meta` file must be JSON. The archive entry gets the size of the bytes that the export read.
- Make sure that the destination is on another site. The system cannot check this.
- Each copy has `copy-manifest.json` with the SHA-256 of every file. A collection copy also holds the `manifest.json` of the export, which the import reads.
- A collection copy fails when the JSON metadata of a Manticore table in the export does not parse, because the import refuses it.
- A zone copy keeps the dumps of the zone databases and one tar file for each claim of the zone namespace, with the owners and modes, and the same parts of the Hoover namespace in `hoover/<installation>/`.
  A Block claim of a Kata store is read through its store container, so the store must run. A claim that a pod owns holds temporary files and is not copied.
- `restore-hoover` imports into an installation without that collection, or into a collection whose stores `drop_collection_database` removed.
- `restore-zone` restores a complete zone copy into an installed zone. It closes the zone and its Hoover installation and stops their stores, except the zone databases.
  It then applies the Secrets of each part, replaces the content of each claim, imports the dumps, restarts the databases and opens the zone.
  A dump without its end line stops the restore before any change. `psql` and the MariaDB client stop at the first error, and the restore fails with that error.
  A copy part `hoover/<installation>/` restores into the installation of that name, or into the one installation of the zone.
  A failure leaves the zone closed. `<operator state>/backups/restore-<zone>.json` names the finished steps.

## Run the tests.

```sh
k3s/tests/run.sh             # render, state (with the portal routes) and driver (with the host scripts)
k3s/tests/run.sh migration backup
k3s/tests/run.sh replay      # the workflow replay suite in the worker image
```

The render, state and driver suites run in a container with the repository mounted read-only.
The driver suite uses fake ssh, sudo, bash and kubectl commands and contacts no host.
They change nothing on the host or a cluster.
