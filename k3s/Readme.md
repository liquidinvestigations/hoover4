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
| [import_compose/](import_compose) | Imports a stopped Compose installation into a new zone, once per zone ([import_compose.py](import_compose/import_compose.py)). |
| [platform/mcp-relay/](platform/mcp-relay) | Serves the MCP servers, the interfaces and the stores of one installation on the loopback ports of the control-plane node. |
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
| `hoover4.vars` | `domain`, `control_plane`, and optional `networks`, `lans`, `gpu_pool`, `backup`, `stores`, `deploy` |
| `hoover4.vars.networks.<name>` | `cidr`, and optional `interface` (default `wg0`), `hubs`, `port` (default 51820), `managed` (default true) |
| `hoover4.vars.lans.<name>` | optional `cidr` |
| `hoover4.hosts.<name>` | `node_roles`, and optional `local`, `ssh_host`, `networks`, `lan`, `public_address`, `storage`, `k3s_volume_group`, `stop_docker`, `public_firewall`, `reserved`, `data_root`, `tls_mode`, `tls_dns_credentials_file`, `tls_certificate_file`, `tls_key_file` |
| `hoover4.hosts.<name>.networks.<network>` | an address, or `address` and optional `public_key`, `interface`, `port`, `managed`, which replace the values of the network for this node |
| `hoover4.vars.gpu_pool` | `nodes` or `address` |
| `hoover4.vars.backup` | `node` and `path` of the backup destination |
| `hoover4.vars.deploy` | optional `parallel_zones`: the zone steps that `deploy-k3s up` runs at the same time (default 2) |
| `hoover4.vars.replicas` | optional pod count of each processing pool of the site: `tika`, `tesseract-cpu`, `ocr-pdf`, `pdf-search`, `regex-entity-scanner`, `clamav` (default 1 each, see [Scale the stateless services](#scale-the-stateless-services)) |

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

### Measure the node speed.

The role `hoover4_speed` measures each node once, while k3s does not run on it, and writes `speed/<node>.json` of the state folder:

- `threads`: the threads of the node.
- `cpu_speed`: the work of one thread in one CPU second while all threads run a zlib and a Python probe for 0.5 s each.
- `disks`: the write speed of each storage tier of the node in MiB/s. The role writes 1 GiB with direct I/O into a new logical volume of the volume group of the tier, and then deletes the volume.

The step `hosts:prepare` measures a node without a stored value, before the step `hosts:k3s` starts k3s on it.
Then `up` uses the stored values and does not measure again. The cluster copy of the state keeps `speed/`.
`deploy-k3s check` prints the values of each node. The disk speeds do not change the placement.

Measure a node again, for example after a change of its CPU or of a frequency setting:

```sh
ssh <node> sudo systemctl stop k3s-agent        # the unit k3s on the control plane
ssh <node> 'echo 1 | sudo tee /sys/fs/cgroup/kubepods.slice/cgroup.kill'
ssh <node> 'echo 1 | sudo tee /sys/fs/cgroup/system.slice/k3s-agent.service/cgroup.kill'
ssh <node> sudo /usr/local/bin/k3s-killall.sh
k3s/deploy-k3s measure-speed --site k3s/private/<site>.yml --target <node>
ssh <node> sudo systemctl start k3s-agent
k3s/deploy-k3s up --site k3s/private/<site>.yml --target all
```

`measure-speed` refuses a node where k3s or a container runs, or whose 1-minute load is above 5, and names the reason.
The node keeps its earlier value. `k3s-killall.sh` stops only the runc containers of k3s. The gVisor and Kata sandboxes
run in `kubepods.slice`, and their shims stay in the cgroup of the k3s unit after the stop, so the two `cgroup.kill`
writes stop them. The pods of the node start again with k3s. Their data stays on their volumes.
The next `up` gives the new factor to k3s, which restarts k3s on each node whose reserve changes.
A site of an earlier version measured `cpu_speed` in the facts play at every run, also under load. Its nodes keep the last facts value as their stored value. `deploy-k3s check` names each such node and the commands above.
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
python3 k3s/zones/zone.py apply zone-x [--stores site|local] [--dataset name:node:/path]
python3 k3s/zones/zone.py delete zone-x
```

- A zone has no home node. The k3s scheduler configuration of the server
  ([ansible/roles/hoover4_k3s/templates/scheduler-config.yaml.j2](ansible/roles/hoover4_k3s/templates/scheduler-config.yaml.j2))
  scores the nodes with three plugins. `NodeAffinity` (weight 50) prefers the planned node of the pod, which the
  [site placement](#place-the-pods-of-the-site) gives each new pod of the stores and the zones. 50 x 100 is above the
  sum of the two resource plugins, so a pod starts on its planned node when that node has room.
  `NodeResourcesFit` `LeastAllocated` (weight 10) prefers the node with the lowest requested share of its allocatable
  CPU and memory (weight 1 each). `NodeResourcesBalancedAllocation` (weight 10) prefers the node whose requested CPU
  share and memory share are nearest after the pod (weight 1 each). These two decide the node of a pod without a
  planned node, or of a pod whose planned node is full. A node that joins has no requests, so it takes such pods
  first.
- The allocatable CPU of a node counts threads of the fastest node of the site. The speed factor of a node is its
  stored `cpu_speed` divided by the highest one, in steps of 0.05 (`config.py` `speed_factors()`). A node without a
  stored value has the factor 1. The k3s role gives the kubelet the `system-reserved` CPU
  `threads x (1 - factor) + base` (`config.py` `kubelet_reserved()`), so the allocatable CPU is
  `factor x threads - base`. `base` is the measured CPU of k3s on a node without pods, in threads of the fastest node:
  130m for an agent (the kubelet) and 270m for the server (the kubelet and the control plane), `runtimeOverhead.node` of
  [zones/cpu-requests.json](zones/cpu-requests.json). k3s needs `base / factor` threads of a slower node. The node value
  `reserved` with `cpu=` replaces `base`, in threads of the node. A site needs it only when another service of the host
  uses CPU. The memory of `reserved` stays the memory reserve.
- Each pod also requests the steady CPU that it causes outside its pod cgroup (`runtimeOverhead` of
  [zones/cpu-requests.json](zones/cpu-requests.json), [zones/cpu_requests.py](zones/cpu_requests.py)):
  - The RuntimeClasses ([cluster/runtimeclasses.yaml](cluster/runtimeclasses.yaml)) add the part that is the same for
    each pod as `overhead.podFixed` (`pod_fixed()`): 3.3m of the kubelet, 1.7m of containerd and the shim, and for
    gVisor 0.7m of the statistics call of the sandbox. That gives 6m for gVisor and 5m for Kata.
  - The render adds the part of the containers and the exec probes of the pod to the request of its main container
    (`runtime_cost()`), and names it in the annotation `hoover.dev/cpu-runtime`. containerd collects the statistics of
    each gVisor container every 10 s with one runsc command of about 7 ms (0.7m). Each liveness and readiness exec
    probe starts one command of about 45 ms at each period (4.5m at 10 s).
  - The memory overhead is 32 MiB for gVisor (the shim and its runsc process use about 14 MiB) and 640 MiB for Kata.
    A Kata pod cgroup holds the VM, the shim and virtiofsd. The host keeps each guest page that the guest used once,
    so the cgroup grows to the guest size: 512 MiB of `default_memory` plus the container limits. The pod cgroup limit
    is the container limits plus the overhead, so the overhead holds the 512 MiB and the memory outside the guest
    (at most 60 MiB per pod under load). See [Size the memory](#size-the-memory).
  - The values are steady costs, so the start-peak factor of the requests does not apply to them. A runc pod outside
    the renders, for example a platform DaemonSet, has no RuntimeClass, and its cost stays in the free CPU of the node.
- The renders keep the runtime cost low. containerd collects the CPU statistics every 10 s
  (`stats_collect_period` of [ansible/roles/hoover4_k3s/templates/runtimes.toml.j2](ansible/roles/hoover4_k3s/templates/runtimes.toml.j2)).
  The default of 1 s started one runsc command per gVisor container every second. A Compose check that only fetches
  one local URL becomes an HTTP probe, which the kubelet makes itself ([hoover/manifests.py](hoover/manifests.py)
  `http_probe()`). The post-renderer removes the openDesk exec probes that always pass (`exit 0`), uses a TCP probe
  for memcached, and lengthens the Nextcloud and Redis probe periods to 10 s (`probes()` of
  [zones/postrender.py](zones/postrender.py)). The Temporal readiness probe of the site runs every 15 s.
- The memory request of a pod is its measured peak under load ([Size the memory](#size-the-memory)). The CPU request
  of a measured workload is
  `baseline + 0.2 x (start peak - baseline)`, rounded up to 10m, from [zones/cpu-requests.json](zones/cpu-requests.json).
  The start peak is the highest CPU rate (1 min) from the pod start until Ready plus 120 s, and the baseline is the
  median CPU rate in an idle period. Each pod names them in the annotations `hoover.dev/cpu-start-peak`,
  `hoover.dev/cpu-baseline` and `hoover.dev/cpu-request-basis`. A workload without a measurement keeps the request of
  [zones/cpu-policy.json](zones/cpu-policy.json) or of its installer. The shared stores of `hoover-stores` (ClickHouse,
  Garage, Temporal, Cassandra, OpenSearch) have the part `site` of the table, measured from a start of the stores.
  Measure a zone create again and write the table with
  `python3 k3s/zones/cpu_requests.py measure --zone zone-x --start T --end T --idle-start T --idle-end T --write`, and
  the stores with `measure --site` and the times of their start.
- A pod that can run on one node only has the PriorityClass `hoover-node-bound`
  ([cluster/priorityclasses.yaml](cluster/priorityclasses.yaml)): the store pods of `hoover-stores`, a zone pod with a
  claim, a zone pod that names a node, for example ClamAV and the other services that reach the internet from the
  public node, and the operator portal on the control plane. When its node is full, the scheduler preempts pods of the default priority on that node, and their
  Deployments start them again on another node. A pod of the default priority preempts no pod, and two pods of the class
  do not preempt each other, so preemption does not repeat. The Hoover render, the post-renderer of openDesk
  ([zones/postrender.py](zones/postrender.py)) and the store installers set the class. A chart value stays.
- A normal `deploy-k3s up` moves no running pod. `deploy-k3s up --rebalance` adds the last step `rebalance`
  ([placement.py](placement.py) `rebalance()`), see [Move the pods to their planned nodes](#move-the-pods-to-their-planned-nodes).
  `cluster/setup.sh` deletes the descheduler of an earlier version.
- The zone pod policy ([zones/manifests/zone-pods.yaml](zones/manifests/zone-pods.yaml)) keeps the runtime rule. It adds
  no topology spread.
- A claim takes the first tier of its tier list that a node of the site has ([zones/zonestate.py](zones/zonestate.py)). The
  scheduler binds it on a node with that tier and free capacity, and its pod then stays on that node (TopoLVM).
- `--home` of an earlier version is accepted and has no effect. A zone entry with a `home` value keeps that node only as
  the NFS data node of the zone, when the node has the role `data`.
- A new zone gets `stores = site` and `temporal = site` unless `--stores local` is given. `--dataset` adds a read-only dataset folder of a data node. These values apply to a new zone, and a change of an existing zone is refused.
- A zone with `stores = site` adds its tenant to the [shared stores](#share-the-hoover-stores-of-a-site) and its namespace to the [Temporal of the site](#share-temporal-in-a-site) at create, and `zone.py delete` removes both before it deletes the namespaces.
- The Hoover installation of a zone has the name of the zone. Its storage names come from the zone id: for `zone-x` the ClickHouse database prefix `zone_x`, the Manticore table prefix `zone_x_`, the system bucket `zone-x-system` and the collection bucket prefix `zone-x-c-`. No file stores them.
- `zone.py apply` installs openDesk in waves of its sub-helmfiles (`OPENDESK_WAVES`): the migrations, then the services,
  then Nubus, then the ten applications at the same time, then the OpenProject bootstrap and the last migrations.
  An entry without an installed release uses `helmfile sync`, so a new zone has no diff pass. A failed entry runs once
  more on its own, and the log names the cause (`helmfile-retry`). An openDesk release with another entry list stops
  the install until `OPENDESK_WAVES` names its entries.
- The waves and the steps that set the login flow, the users and the application state run only after a change.
  `zone.py` compares a digest of their inputs with the record `zones/<zone>/opendesk-applied.json` of the state
  folder, which the last complete run of the zone wrote. It also compares the Helm releases of the zone namespace.
  The inputs are these:
  - the openDesk release, the post-renderer with its modules and tables, the pinned tool versions and the scripts of
    the application state
  - the openDesk values and the other files of the zone folder, the shared value files, the zone user passwords and
    `ai.json`
  - the zone state entry, the effective operator settings without the backup policies, and the site settings
  - the environment of helmfile, the Kubernetes version and the storage tiers

  The Helm releases must have the recorded names, revisions and charts, and the status `deployed`. The log line
  `opendesk-check` names each changed input. Without a change, only the Collabora discovery check of
  `zone-patches.py` runs. The record is the path `zones/<zone>/records/opendesk-applied.json` of the secret store. The
  runner of the operator pod and every workstation therefore read the same record.
- A change by hand of an object or of the application state is not an input. `zone.py apply <zone> --full` and
  `deploy-k3s up --full` run the waves and the application state steps without the check.
- helmfile keeps each pulled chart version in `opendesk-charts/` of the state folder, with a lock file for each
  version. It pulls and verifies only a version that is missing. The cache is not part of the cluster copy. On the test
  site it holds 33 chart versions in 24 MiB. Remove the folder to pull every chart again, for example after an
  interrupted pull.
- `deploy-k3s up` applies each zone of the zone state again, after the platform steps. It runs at most
  `vars.deploy.parallel_zones` zone steps at the same time (default 2).

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

### Keep the pods in place.

A pod stops or moves on a running site only in a deployment: `deploy-k3s up`, a zone operation of the portal or of
`zones/zone.py`, and a settings Apply. The other sources have these limits:

| Source | Between deployments |
|---|---|
| Rebalance | No. Only `up --rebalance` moves running pods, one at a time ([Move the pods to their planned nodes](#move-the-pods-to-their-planned-nodes)). |
| Site placement | No. The step `placement` runs only in `up`. A new CPU scale factor resizes the CPU requests of the running pods in place and restarts no container. A new plan changes no pod template ([Place the pods of the site](#place-the-pods-of-the-site)). |
| Preemption | No. Only a new pod of the class `hoover-node-bound` preempts. The renders give the class only to Deployments, StatefulSets, the operator portal and the coturn probe pod of the calls step, so no Job or CronJob creates such a pod. |
| Node-pressure eviction | No, while each pod stays at its measured peak: the requests hold the peaks and the kubelet reserves the memory of k3s and the system ([Size the memory](#size-the-memory)). |
| OOM kill | A container above its limit restarts in its pod, on its node. The limits stay above the measured peaks. |
| Periodic tasks and Jobs | A zone has no CronJob. Each periodic openDesk task runs in a container that stays running ([Run the periodic tasks](#run-the-periodic-tasks)). The install and migration Jobs start their own pods, only in a deployment. These pods have the default priority, so they preempt no pod. |
| Rollout | A large single-replica Deployment stops its old pod before the new pod starts (`rollout()` of [zones/postrender.py](zones/postrender.py), `Recreate` in the Hoover render), so an update needs no free memory for a second pod. |
| Node restart | A node that returns within 300 s restarts its pods in place. After 300 s the taint `node.kubernetes.io/unreachable` evicts its pods, and their controllers start them on other nodes. The pods of the class `hoover-node-bound` wait for their node. |
| Zone backup | No. The scheduled zone copy reads the running zone and stops no workload ([Back up and restore](#back-up-and-restore)). |
| Kubelet reserve change | No running pod is refused. When a new `system-reserved` value would make the restarted kubelet of a node refuse its running pods, `up` keeps the current value in `hosts:k3s` and applies the new value in the step `hosts:kubelet` after the zone steps ([Change the kubelet reserve](#change-the-kubelet-reserve)). |

### Change one zone without the others.

A zone create, apply, upgrade or delete changes the namespaces `<zone>` and `hoover-<zone>`. These actions also change
objects outside them:

| Action | Object outside the zone | Effect on the pods of another zone |
|---|---|---|
| `zone.py` cluster step | the zone pod policy `hoover-zone-pods` and the XWiki extension repository in `extensions` | None. They change only with the source, and the policy acts on new pods only. |
| `shared.py grow` | the claims of the shared stores in `hoover-stores` grow with the zone count | None. The claim template and the pods stay. |
| `creds.py`, `setup.py`, `shared.py remove` | the tenant of the zone in the shared stores: ClickHouse and Manticore users and databases, Garage keys and buckets, the Temporal namespace, the Secrets `hoover-stores` and `garage-tenants` | None. The stores apply these changes while they run. |
| Ingress objects of the zone | the routes of the ingress controller | None. The controller reloads its configuration and keeps its pod. |
| Step `calls` of the zone runner ([platform/calls/install-calls.py](platform/calls/install-calls.py)) | the configuration of coturn, LiveKit and the JVB, which holds each zone | The three call services restart, and the calls of every zone end. |
| Step `placement` of `up` | the ConfigMap `kube-system/hoover-placement` and the CPU requests of the running pods | A new CPU scale factor resizes the pods of every zone in place, without a restart. A zone operation of the portal does not run this step. |

A zone backup reads the zone and stops no pod of any zone.

### Run the periodic tasks.

The openDesk charts start a new pod for each run of a CronJob. The post-renderer replaces each CronJob with a container
that stays running (`PERIODIC` and `periodic()` of [zones/postrender.py](zones/postrender.py)). The container runs the
command of the CronJob with its image, environment, volumes and service account. It runs the command once at its start
and then at each time of the CronJob schedule, in UTC.

| Task | Container | Interval |
|---|---|---|
| Nextcloud background jobs (`cron.php`) | sidecar `cron` in the pod of `opendesk-nextcloud-aio` | 5 minutes |
| UDM license cache | container `license-cache` of the Deployment `ums-udm-rest-api-periodic` | 1 hour |
| UDM blocklist cleanup | container `blocklist-cleanup` of the Deployment `ums-udm-rest-api-periodic` | 1 day, at 08:00 |
| Matrix media cleanup | Deployment `opendesk-element-customization-media-cleanup` | 1 hour |

- Each run writes the line `periodic task <name>: exit <code> after <seconds> s` into the log of its container.
  A failed run does not stop the loop. It repeats after 60 s, at most 5 times, unless the next time of the schedule
  comes first. Read the runs with `kubectl -n <zone> logs deployment/opendesk-nextcloud-aio -c cron`.
- A sidecar has its own copy of each volume of the CronJob, so it shares no empty folder with the other containers.
- The memory request of the container is the peak of one run. The pod requests its measured peak plus its sidecars.
- The media cleanup runs `kubectl exec` in the Synapse media pod with its own service account, so it has its own
  Deployment.
- The two UDM tasks share the Deployment `ums-udm-rest-api-periodic`. As sidecars, each change of a task restarted the
  UDM REST API, and the provisioning transformer then restarted too. The UDM REST API keeps `maxSurge: 0`
  (`NO_SURGE`), because its second pod found no node on the full test site.
- The pod of a task Deployment keeps the labels of its CronJob, except the labels with which a Service or workload
  selector of the render would also select it (`own_labels()`).
- A chart that renders a CronJob without a rule in `PERIODIC` stops the zone install. A new rule names the pod or
  `None` with an optional Deployment name, the container name and the memory of one run. It also names the command when the CronJob uses the entrypoint
  of its image.

### Change the kubelet reserve.

The step `hosts:k3s` writes the `system-reserved` value of each node ([config.py](config.py) `kubelet_reserved()`) and
restarts k3s when it changes. The restarted kubelet admits its running pods again against the new allocatable memory
and CPU, and it refuses a pod that does not fit (`OutOfmemory`, `OutOfcpu`). [kubelet.py](kubelet.py) prevents this:

- `deploy-k3s check` and `up` read the reserve of each running kubelet (its `configz`) and compute the new allocatable
  of each node: the current allocatable plus the current reserve minus the new reserve.
- A node is held when its new allocatable memory or CPU is lower and the requests of its pods, with the RuntimeClass
  overhead, are above it. `check` prints the nodes in `state.kubelet` with the order `kubelet-first` or
  `requests-first`.
- With held nodes, `up` gives the k3s play the current value of each held node in `hosts:k3s`, so k3s does not restart
  there. The record keeps the held values in `kubelet_hold`. The step `hosts:kubelet` follows the zone steps and the
  calls step, and comes before the step `rebalance` of `up --rebalance`. It checks the requests again and then runs the k3s play with the new
  values. When the requests still do not fit, it fails and changes nothing. `--steps hosts:k3s` also selects
  `hosts:kubelet`.
- The placement plan uses the allocatable after the change, so the plan fits the nodes after `hosts:kubelet`.

### Size the memory.

The memory request of each workload is its peak under load ([zones/memory-requests.json](zones/memory-requests.json),
[zones/memory_requests.py](zones/memory_requests.py)). `peak` is the highest working set of the pod cgroup on the host
in a load and the 30 minutes after it. `request` is `margin` x `peak`, rounded up to 32 MiB. A workload without an
entry keeps the request of its installer ([hoover/manifests.py](hoover/manifests.py) `REQUESTS`).

- The pod cgroup holds every container of the pod and the gVisor sentry. For a Kata pod it holds the VM, the shim and
  virtiofsd. The render gives the main container the table value minus the requests of the other containers, and for
  a Kata pod also minus the RuntimeClass overhead, which the scheduler adds to the pod. So a Kata pod requests its
  peak with the margin, and at least the overhead of 640 MiB and 16 MiB.
- `outsidePeak` of a Kata workload is the highest difference between its pod cgroup and the working set of its
  containers in the guest. It holds the guest kernel, the agent, the guest pages that the host keeps after the guest
  freed them, and the memory outside the guest. The host part outside the guest (the heaps of the shim, Cloud
  Hypervisor and virtiofsd, and the kernel memory of the cgroup) was at most 60 MiB per pod.
- The kubelet reserves the memory of k3s, the system and the kernel beside the pods (`system-reserved`,
  [config.py](config.py) `kubelet_reserved()`): `node` of the table, from the highest difference between the node working
  set and the pods in the load, with the margin. `server` holds the control plane. A site value `reserved` with
  `memory=` replaces it. The hard eviction threshold stays `memory.available<500Mi`, and no soft threshold is set. So
  a node reaches memory pressure only when its pods use more than their requests.
- The limits stay in [zones/memory-limits.json](zones/memory-limits.json). The tool names each workload whose limit is
  below its peak.

The load of a measurement: an ingest of the fixture corpus in each zone (`hoover/seed.py <zone>` and
`hoover/seed.py <zone> --browser`), the browser load of [tools/load/monkey.py](tools/load/monkey.py) with two tabs for
each user in every application, and a ClamAV signature reload (`RELOAD` on the clamd socket) at the start and in the
middle. Sample the Kata guests in the same time with [tools/load/guest_sampler.py](tools/load/guest_sampler.py). Then
write the table:

```sh
python3 k3s/tools/load/guest_sampler.py guest.jsonl --seconds 7200
python3 k3s/zones/memory_requests.py measure --zone zone-a --zone zone-b --start T --end T --guest guest.jsonl --write
python3 k3s/zones/memory_requests.py measure --site --start T --end T --guest guest.jsonl --write
```

`--write` keeps the margin, and with `--guest` it also writes `node`. The next `up` applies the requests and the reserve.
The pods whose request changes start again.

## Deploy a site.

`deploy-k3s` is the one command of a site. The workstation needs Python 3 and `podman` or `docker`.

```sh
k3s/deploy-k3s render --site <file> --target all   # prints the configuration, the inventory and the steps. Changes no host.
k3s/deploy-k3s check --site <file> --target all    # reads the facts of the nodes and checks the files and the tools
k3s/deploy-k3s up --site <file> --target all [--ask-become-pass]
k3s/deploy-k3s down --site <file> --target all
k3s/deploy-k3s up --site <file> --target all --start
k3s/deploy-k3s status --site <file>
k3s/deploy-k3s measure-speed --site <file> --target <node>   # see "Measure the node speed"
```

- `deploy-k3s` computes a digest of the inputs of [images/operator/](images/operator) and of [ansible/requirements.yml](ansible/requirements.yml), and builds the image `localhost/hoover4-operator:<digest>` when it is missing.
  It then runs one container with `--rm` for the command. The container mounts the checkout read-only at its own path, the folder of the site file read-write, `~/.ssh` read-only, the SSH agent socket and the runtime folder of the user for the podman service.
  It runs with the UID of the user and the network of the host. `HOME` is `/tmp/home` of the container, so no tool writes into the checkout. Inside it, `HOOVER4_OPERATOR_IMAGE=1` makes `deploy-k3s` run the driver ([driver/deploy.py](driver/deploy.py)).
- `up` runs the host steps, then the pinned operator tools, the cluster services, the secret store, the registry, the images, the ingress, the HTTPS frontend, monitoring, the operator pod (the portal and the zone runner), the GPU proxy, each zone and the calls services, in this order.
  The registry step runs before the image step, so each push has a target.
- Monitoring ([platform/monitoring/](platform/monitoring)) names no node. Prometheus, Grafana and Loki stay on the nodes of their claims.
  Alloy runs on each node and reads the log files of the pods of its node from `/var/log/pods` with the labels `namespace`, `pod` and `container`. No log stream passes through the API server.
- The host steps are one Ansible run each on all target nodes. The site file is the inventory.
  The driver gives the values that it derives from the site file as the extra variable `hoover4_nodes`.
  [ansible/playbooks/group_vars/hoover4.yml](ansible/playbooks/group_vars/hoover4.yml) gives each value to its node as a `hoover4_*` variable.
  `hosts:prepare` runs [ansible/playbooks/hoover4-hosts.yml](ansible/playbooks/hoover4-hosts.yml): the facts of each node into `facts/<node>.json` of the state folder, the speed of a node without a stored value into `speed/<node>.json` (see [Measure the node speed](#measure-the-node-speed)), the packages of the node in one task, Docker (`stop_docker`), the kernel modules, sysctl, NetworkManager, SELinux, the k3s data volumes (`k3s_volume_group`), the local node of a single-node site, the backup folder, the public firewall (`public_firewall`), and the WireGuard interfaces of the managed networks.
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
- The driver holds the site operation lock ([oplock.py](oplock.py)) while it runs. The settings Apply, the zone operations, the Compose import and the openDesk and platform backups take the same lock.
  When the cluster answers, the lock is the Lease `site-operation` of the namespace `operator-portal`, so the workstation and the runner in the cluster exclude each other. A holder renews it every 20 seconds, and a Lease without a renewal for 90 seconds is free. Before the cluster exists, the lock is a file lock of the operator state folder.
  A settings save takes no lock, so a save during a run waits as a later revision.
- A failed step ends the run. A failed play names the nodes of its failed tasks, and the log of the record holds the output of each task.
- A zone step waits until the zone and its Hoover installation have ready workloads, and then records their settings scopes as applied with the pinned revision.
  A workload whose status shows a complete rollout needs no `kubectl rollout status` call.
- A zone step then starts a check pod with the OIDC egress label of oauth2-proxy. The pod sends an invalid sign-in code with the client secret of the proxy to Keycloak. The step fails when Keycloak does not answer `invalid_grant`, for example when a NetworkPolicy or a DNS answer blocks the token exchange.
  The step records a digest of the objects that the sign-in depends on: the workloads, NetworkPolicies, Services, Secrets, ConfigMaps and Ingresses of the zone and its Hoover namespace, and the CoreDNS configuration. When the digest equals the one of the last complete `up`, the check pod does not run.
- A second `up` without a change of its inputs changes no object, starts, deletes or restarts no pod, builds no image and restarts no service:
  the image tags are digests of the image inputs (see [Render a Hoover installation](#render-a-hoover-installation)), the operator step restarts a pod of `operator-portal` only when the configuration that it reads at start changed,
  a zone apply restarts the portal server only at the first install of the zone and runs the openDesk waves only on a changed input, the prepull step starts no pull pod when the Hoover images, the openDesk release and the nodes are those of the last complete `up`,
  the probe of the calls step runs again only when its inputs changed, the ingress and monitoring steps upgrade a Helm release only when its chart version or values changed ([platform/helm-release.sh](platform/helm-release.sh)), and the registry step starts no pod on the nodes, because the host play writes the registry mirror file.
  The record of the deployment changes. The cluster copy of the state changes only when a file of the state changed, for example the placement plan after pods moved.
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
- The stores step creates and updates the shared stores of the site ([hoover/stores/shared.py](hoover/stores/shared.py)) before the zone steps. `down` and `up --start` stop and start them with the stores tier.
- After the conversion of the server from SQLite to etcd, `hosts:verify` restarts the Deployments and DaemonSets of `kube-system`, `ingress`, `cert-manager`, `topolvm-system`, `monitoring` and `operator-portal`.
  Without the restart, CoreDNS, the ingress controller, cert-manager, TopoLVM and the monitoring operators did not see objects that were created after the conversion.
- The restore of a platform copy and the copy of a retired server run [ansible/roles/hoover4_k3s/files/k3s-datastore.py](ansible/roles/hoover4_k3s/files/k3s-datastore.py) with sudo on the server.
  The script reads and writes `~/hoover4-snapshots/<name>/` of the user that runs sudo, and takes names only.

The local node of a single-node site gets the dummy link `hoover4` with the address `10.254.54.1`, a dnsmasq for the names below the domain, and the units `hoover4-address`, `hoover4-dns` and `hoover4-frontend`.
k3s and every pod run in `hoover4.slice`. The node value `reserved` sets the memory and CPU that stay with the rest of the host, for example a Compose stack.
The k3s data and the kubelet folder are volumes of the volume group of the node, which the person creates. TopoLVM uses the free space of the group.
The local node connects to `localhost` over SSH unless it has `ssh_host`, so the workstation needs an SSH server for its own user.
The admin kubeconfig is `kubeconfig` of the state folder. k3s writes it as `/etc/rancher/k3s/hoover4-admin.yaml`, because `/etc/rancher/k3s/k3s.yaml` can belong to another k3s user of the host.
A new Hoover installation of a single-node site keeps its dataset folders `testdata` and `uploads` on claims, so it needs no NFS server.
The frontend step adds the local CA to the trust store of the host and to the NSS stores of the operator user, so a browser of the host trusts the site.
`tools/write-password-table.py` prints the logins of the site from the secret store and the live Secrets. Nothing stores the table.
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

## Choose the store layout.

| Zone state value | Value | Result |
|---|---|---|
| `stores` | `local` | The Compose stores run in the Hoover namespace on claims of one node. The operations worker mounts them, so store backup and restore work. The pods with a claim share the node of the first bound claim through a required pod affinity. |
| `stores` | `site` | ClickHouse, Garage, the two Manticore daemons and Temporal are shared by the site. Every new zone uses this layout. |
| `stores` | `zone` | ClickHouse, Manticore and Garage run in the zone namespace. A zone entry without `stores` is a zone of this earlier layout. The installer and `deploy-k3s check` refuse it. Delete the zone and create it again: its data does not move. |
| `temporal` | `site` | The zone uses its namespace in the Temporal of the site. Every new zone with `stores = site` gets this value. |
| `temporal` | `zone` | With `stores = local`, Temporal, Cassandra and Elasticsearch run in the Hoover namespace as in Compose. With `stores = site`, the zone is from an earlier version whose Temporal ran on the PostgreSQL of the zone. The installer and `deploy-k3s check` refuse it. Delete the zone and create it again: its workflow history does not move. |
| `manticore` | `site` | The zone uses three users of the Manticore daemons of the site and its own schema proxy. Every new zone with `stores = site` gets this value. |
| `manticore` | `zone` | With `stores = site`, the zone is from an earlier version whose Manticore daemons ran in the zone namespace. The installer and `deploy-k3s check` refuse it. Delete the zone and create it again: its search tables do not move. |

## Share the Hoover stores of a site.

One ClickHouse, one Garage, two Manticore daemons (text and vectors) and one PostgreSQL serve every zone of a site, in the namespace `hoover-stores` ([hoover/stores/shared.py](hoover/stores/shared.py)). The step `stores` of `deploy-k3s up` creates them, and each zone with `stores = site` is a tenant. PostgreSQL holds the [openDesk databases](#keep-the-opendesk-databases-on-the-shared-postgresql) of the zones.
The site file sets their nodes and node counts in `vars.stores`, with the history shard count and the sizes of the [Temporal of the site](#share-temporal-in-a-site):

```yaml
hoover4:
  vars:
    stores:
      nodes: [node-a, node-b, node-c]   # default: every node with the role worker and a storage tier
      history_shards: 128               # default: 128. Temporal keeps the count of its creation.
      garage: {nodes: 3}                # default: the node count of nodes, at most 3
      cassandra: {nodes: 1, data_gib: 2}  # default: 1 node and 2 GiB of live data
      opensearch: {nodes: 1}            # default: 1
      temporal: {pods: 1}               # default: 1
      zones: 2                          # default: the zones of the zone state, at least 1
```

Each store keeps one copy of each part of its data. No store has replication or failover.

- ClickHouse runs one pod.
- PostgreSQL runs one pod.
- Manticore runs one pod for text and one pod for vectors. Each pod runs on one node, without replication or failover.
- Garage runs one pod on each of its `garage.nodes` nodes, with the replication factor 1. The layout gives each node a part of the objects. The client Service selects every ready Garage pod, and each pod forwards a request to the node that holds the object.
- A store node count cannot become smaller than at the last apply, because each node holds a part of the data. `deploy-k3s check` and the stores step refuse it. A larger count adds nodes, and the store moves a part of the data to them.
- Each pod of a store needs a storage tier on its own node. The step takes the first preferred tier that enough nodes have.
- The stores step takes the node of each store pod from the site placement before its volume exists. See [Place the pods of the site](#place-the-pods-of-the-site).
- A claim holds the size of one zone store for each zone with `stores = site`, at least one zone: 20 GiB for ClickHouse and for each Garage pod, 16 GiB for Manticore text and 10 GiB for Manticore vectors. A Garage pod also holds its share of the [openDesk objects](#keep-the-opendesk-objects-in-garage) of each zone. Its claim is (20 GiB + 30 GiB x replication factor / Garage pod count) x zone count, rounded up. 30 GiB is the SeaweedFS volume of a zone before the move to Garage ([zones/postrender.py](zones/postrender.py) `STORES`). Three Garage pods and two zones give 60 GiB for each claim. The PostgreSQL claim holds 20 GiB for each zone, the volume of a zone PostgreSQL before the move. A zone create grows the claims. The file system in the Kata guest of a store grows at the next start of its pod. The memory limits and requests are those of one zone store ([zones/memory-limits.json](zones/memory-limits.json) `hoover`).
- Isolation of a zone: in ClickHouse the zone user and one user for each service, with grants on the databases `<prefix>` and `<prefix>_*` only, and the settings profile `<prefix>`, which limits the memory of one user to half of the ClickHouse limit. In Garage the zone key, a key for each service, and the buckets `<zone>-*`. A key reaches only the buckets that it created or that the setup allowed. A bucket that Hoover creates for a collection has a local alias of the zone key, so another zone cannot take its name. The zone credentials are in the Secrets `hoover-stores` and `garage-tenants` of the zone namespace. The password of the Manticore schema user is only in the Secret `manticore-schema` of the Hoover namespace, because openDesk service accounts can list the Secrets of the zone namespace.
- Network: only namespaces with the label `hoover.dev/hoover` reach ClickHouse on 8123 and 9000, Manticore on 9306 to 9309 and Garage on 3900. Only namespaces with the label `hoover.dev/opendesk-postgresql` reach PostgreSQL on 5432. `zone.py apply` gives the label to the openDesk namespace of each zone with `stores = site`. The ingress controller also reaches Garage on 3900 for the object storage host of each zone. See [Keep the openDesk objects in Garage](#keep-the-opendesk-objects-in-garage). The Garage RPC port takes only the Garage pods, and the admin port takes no connection. ClickHouse reaches only DNS and Garage on 3900.
- The zone copy of the backups holds the ClickHouse databases `<prefix>` and `<prefix>_Processing` and the objects of the bucket `<zone>-system` of a zone with `stores = site`, in `hoover/<zone>/shared/`. ClickHouse writes the archive of the databases into `<zone>-exports` with the zone key. The S3 client copies it and the bucket out. The collection exports hold the collection databases, Manticore tables and buckets. `main.py reindex-collection` also builds the Manticore tables of a collection again from ClickHouse.
- A zone delete removes the tenant (`shared.py remove`). It then checks that no bucket, key, database, user, table, Temporal namespace, object storage Ingress or PostgreSQL database or user of the zone stays. Each Garage pod has the container `s3`, the S3 client of the operator tools ([hoover/stores/garage_client.py](hoover/stores/garage_client.py)). It empties the buckets, so the delete needs no pod of the zone. A failed part or a remaining object stops the delete before it removes the namespaces and the zone state entry. Repair the store and delete the zone again. `shared.py remove` and `temporal.py remove` take only a full zone id.
- A new zone is refused while the stores hold an object of an earlier zone with the same id. The message names the objects. Remove them with `shared.py remove <zone>` in the operator image, then apply the zone again.

### Keep the openDesk objects in Garage.

A zone with `stores = site` keeps the objects of its openDesk applications in the shared Garage, and runs no SeaweedFS ([zones/objectstore.py](zones/objectstore.py)). A zone of the layout `local` keeps SeaweedFS in its namespace.

- Each openDesk object store of the zone has the bucket `<zone>-opendesk-<bucket>`: `migrations`, `nextcloud`, `notes`, `ums` (Nubus), `openproject`, `openxchange` and `synapse`.
- The key `<zone>-opendesk` reads and writes these buckets only. It has a local alias with the openDesk name of each bucket, for example `nextcloud`, so the applications keep their bucket names. Nextcloud names its root storage by the bucket name. The key cannot create a bucket, change a bucket setting, or reach a Hoover bucket or a bucket of another zone. Its id and secret are `objectstore_key` of the zone secrets in the secret store, and `zone.py apply` imports it into Garage.
- The values of the zone name the object storage host `<zone>-objectstorage.<domain>`, the key and the Garage region `us-east-1`. Garage refuses a request that is signed for another region. The openDesk Notes template passes no region to its chart, so the zone gives Notes the region in the customization file `zones/notes-s3-region.yaml` of the state folder. Without it Notes signs with an empty region, and Garage refuses each read of a Notes attachment.
- The applications and the browsers of the users reach Garage at the object storage host, through the HTTPS frontend and the Ingress `opendesk-<zone>` in `hoover-stores`. The Ingress sends only the paths of the zone buckets and the bucket list (`/`) to Garage. Garage answers the bucket list with the buckets of the key. It answers the CORS requests of the OpenProject pages of the zone, because a Garage bucket without a CORS setting refuses them.
- The S3 features that each application uses, checked against Garage 2.3.0:

  | Application | Bucket | Features | Garage |
  |---|---|---|---|
  | Nextcloud (primary storage) | `nextcloud` | GET, PUT, DELETE, multipart upload, copy, head, list | supported |
  | OpenProject (attachments, fog) | `openproject` | PUT with the streaming signature, presigned GET from the browser | supported. The direct upload from the browser (presigned POST) is off in this OpenProject configuration. |
  | Synapse (media store) | `synapse` | GET, PUT, DELETE, head. A customer key (SSE-C) when the zone sets one. | supported, SSE-C included |
  | Notes | `notes` | GET, PUT, DELETE, signed GET through the Notes frontend | supported |
  | Nubus portal | `ums` | GET, PUT, list | supported |
  | openDesk migrations | `migrations` | GET, PUT, list | supported |
  | Open-Xchange | `openxchange` | GET, PUT, DELETE, multipart upload | supported. The zones do not install Open-Xchange. |

  No application uses versioning, object lock, bucket policies, ACLs or a conditional write, which Garage does not support.
- A zone of an earlier version runs SeaweedFS and has no value `objectstore` in the zone state. `zone.py apply` with the admin kubeconfig moves it, and `deploy-k3s up` runs that apply for each zone:
  1. The Ingress takes the paths of the zone buckets. The applications then reach Garage with their SeaweedFS key, which Garage refuses, so no application changes an object. The switch starts here.
  2. Every bucket of SeaweedFS is copied into Garage, and the object count and the byte count of each bucket must be equal in both stores. Else the Ingress goes away, the applications use SeaweedFS again, and the apply stops with the counts.
  3. The volume of SeaweedFS gets the reclaim policy `Retain` and the label `hoover.dev/seaweedfs-of=<zone>`. The zone state gets `objectstore = garage`, and the openDesk waves switch the applications. Helm removes SeaweedFS, and its volume stays.
  4. Each workload whose configuration holds the key, and Nextcloud, restart once. The switch ends when they are ready. `zones/<zone>/objectstore-move.json` of the state folder records the counts and the times.

  The zone runner of the portal cannot keep a volume, so a portal Apply leaves such a zone on SeaweedFS until the next `deploy-k3s up`. A move changes no pod of another zone.
- Check the applications of the zone after a move. Then delete the kept SeaweedFS volume with `zones/objectstore.py drop-seaweedfs <zone>` in the operator image. A zone delete deletes it too.
- `zones/objectstore.py show <zone>` prints the object and byte count of each bucket. `zones/objectstore.py check <zone>` compares the counts of SeaweedFS and Garage while both run.
- The Garage claims include 30 GiB of openDesk objects for each zone, divided over the Garage pods. See [Share the Hoover stores of a site](#share-the-hoover-stores-of-a-site) for the formula. `zones/objectstore.py show <zone>` prints the bytes that a zone uses.
- The zone copy of the backups reads the openDesk buckets from Garage with the zone key. The copy has the form of a SeaweedFS copy. `restore-zone` writes the objects back into the Garage buckets of the zone. A zone delete removes the buckets, the key and the Ingress.

### Keep the openDesk databases on the shared PostgreSQL.

A zone with `stores = site` keeps the databases of its openDesk applications on the shared PostgreSQL, and runs no PostgreSQL ([zones/postgresql.py](zones/postgresql.py)). A zone of the layout `local` keeps PostgreSQL in its namespace.

- The server runs the PostgreSQL major version of the openDesk release (15) in Kata on a block volume of a fast tier. Its admin password is `postgresql-admin` of the Secret `hoover-stores`. The operator tools connect as the admin through the local socket of the pod and need no password.
- Each PostgreSQL database of the openDesk release has the database `<prefix>_<name>` and the user `<prefix>_<user>` of the zone, for example `zone_a_nextcloud` and `zone_a_nextcloud_user`. The user owns its database and has the connection limit of the release. It cannot create a database or a role. The passwords are `postgresql` of the zone secrets in the secret store, and `zone.py apply` creates the users and the databases. The values of the zone name the server `postgresql.hoover-stores.svc.cluster.local`, the names and the passwords, and turn the openDesk PostgreSQL off.
- No database of a zone, and neither `postgres` nor `template1`, admits a connection of `PUBLIC`. A user connects only to its own database. In each zone database no user reads `pg_database`, `pg_stat_database`, `pg_stat_database_conflicts`, `pg_roles`, `pg_user`, `pg_group`, `pg_auth_members`, `pg_stat_activity` or `pg_shdescription`. Synapse reads the collation of its database from `pg_database` at its start, so the Synapse user reads that catalog in its own database and can see the database names.
- The extensions of the openDesk databases are `pg_trgm`, `unaccent`, `fuzzystrmatch` and `btree_gist` (Notes, OpenProject and the Matrix authentication service). PostgreSQL 15 lets the owner of a database create them. Synapse needs the collation `C`, and XWiki the encoding `UNICODE`, as in the release. No application needs another server setting. The server allows 1000 connections, and a zone opens about 40.
- A zone of an earlier version runs PostgreSQL and has no value `postgresql` in the zone state. `zone.py apply` with the admin kubeconfig moves it, and `deploy-k3s up` runs that apply for each zone:
  1. The users of the zone PostgreSQL lose their login, and their sessions end. No application changes a row from here. The switch starts here.
  2. Each database is copied with `pg_dump` and `pg_restore` as its new user, and the row count of each table must be equal on both servers. Else the users get their login again, the applications use the zone PostgreSQL again, and the apply stops with the counts.
  3. The Nextcloud configuration in the copied database gets the shared server, because Nextcloud reads it from its database at its start.
  4. The volume of the zone PostgreSQL gets the reclaim policy `Retain` and the label `hoover.dev/postgresql-of=<zone>`. The zone state gets `postgresql = site`, and the openDesk waves switch the applications. Helm removes the zone PostgreSQL.
  5. Each workload whose configuration names the shared server, and Nextcloud, restart once. The switch ends when they are ready. The claim of the zone PostgreSQL goes, and its volume stays. `zones/<zone>/postgresql-move.json` of the state folder records the counts and the times.

  The zone runner of the portal cannot keep a volume, so a portal Apply leaves such a zone on its own PostgreSQL until the next `deploy-k3s up`. A move changes no pod of another zone.
- Check the applications of the zone after a move. Then delete the kept volume with `zones/postgresql.py drop-volume <zone>` in the operator image. A zone delete deletes it too.
- `zones/postgresql.py show <zone>` prints the databases of a zone with their sizes. `zones/postgresql.py check <zone>` compares the row counts of both servers while both run.
- The server removes its lock file at its start, so it starts again after a power loss and replays its write-ahead log.
- The zone copy of the backups holds a `pg_dump` of each database of the zone in `postgresql/<name>.sql`, without owner and rights. `restore-zone` drops each database, creates it again empty with its user and rights, and imports the dump as that user. A copy from before the move holds `postgresql.sql`, which `restore-zone` refuses for a zone on the shared server. A zone delete removes the databases and the users.

### Export the ClickHouse part of a collection.

The shared ClickHouse mounts no folder of a zone. A collection export of a zone with `stores = site` therefore writes the ClickHouse archive into the Garage bucket `<zone>-exports` of the zone:

| Part | Rule |
|---|---|
| Writer | The operations user `<prefix>_ops` runs `BACKUP DATABASE ... TO S3(...)` with the zone key. It has the grant `BACKUP` on `<prefix>_*` only. `RESTORE` uses the grants of the zone databases. |
| Bucket | Only the zone key reaches `<zone>-exports`. Garage refuses the bucket of another zone to that key. The operations pod gets the bucket address in `CLICKHOUSE_BACKUP_S3_URL`. |
| Progress | The operations user reads `system.backups`. The row policy `<prefix>_backups` shows only the rows whose id starts with `<prefix>-`. |
| Server | ClickHouse allows no backup to a file of its own volume (`backups.allowed_path` is removed). ClickHouse 25.8 has no setting that limits the S3 address of a backup. The network policy `clickhouse-closed` therefore lets ClickHouse reach only DNS and Garage on 3900. |
| Export folder | The folder in the claim `ops-backups` keeps the manifest and the other parts. The ClickHouse part of the manifest names the object (`object`: bucket and key). |
| Collection copy | The backup job `hoover:<zone>:<collection>` copies the object into the export folder, copies the folder, and then removes the folder and the object. A collection copy therefore holds the ClickHouse archive. |
| Import | An import reads the object of its own bucket. A folder can hold the archive, for example a collection copy or a Compose export. The import then uploads it to `imports/<operation>/` of the bucket and removes it after the restore. |

A zone delete removes the bucket with its objects. An export that fails after the ClickHouse part leaves its object in the bucket until the zone delete.

### Place the pods of the site.

The step `placement` of `deploy-k3s up` computes the node of every pod of the site and one CPU scale factor
([placement.py](placement.py)). It runs before the stores and the zones. `deploy-k3s check` computes the same plan and
prints it in `placement` of its state. It changes nothing on the cluster.

| Input | Source |
|---|---|
| Node capacity | The allocatable memory and CPU of each schedulable node without the role `gpu`. The kubelet reserve is already subtracted, and the CPU counts threads of the fastest node ([Measure the node speed](#measure-the-node-speed)). |
| Pods of other installers | The platform pods, the DaemonSet pods and the Job pods, at their requests on their nodes. |
| Site pods | A new render at the factor 1: the shared stores, and for each enabled zone the Hoover installation, the zone gate and openDesk (`helmfile template` with the post-renderer, all openDesk entries at the same time). The openDesk render of a zone is kept in `placement/render-<zone>.json` of the state folder with a digest of its inputs, and a plan with the same inputs uses it. The inputs are the zone values, the zone state entry, the effective operator settings that the post-renderer reads (`operator_effective()` of [zones/zone.py](zones/zone.py)), the openDesk release and the files of `zones/`. A saved backup policy changes no input. |
| Planned zones | `vars.stores zones` beyond the zone state count as copies of the first zone. They are only counted. |

Rules:

- Memory is a hard limit. The memory requests on a node stay at most its allocatable memory, and they never scale.
- CPU is a soft limit. When no plan fits with the full CPU requests, the plan lowers every CPU request of the site
  pods by one factor: the largest of 1, 0.95, 0.90 and so on at which a plan fits. This replaces a CPU scale that an
  operator sets by hand. The factor moves in steps of 0.05, because each change resizes every running pod.
- A pod with a bound local claim, or with a node selector of one host, stays on that node. A required node affinity,
  a required pod anti-affinity against its own pods and a required pod affinity to another workload are kept.
- A running pod keeps its node when its new requests fit there. A plan never moves a running pod, so a zone create, a
  zone delete or a new factor restarts and moves no pod of another zone.
- The other pods take the node with the lowest share of requested CPU per allocatable CPU, and the plan then moves and
  swaps them while the CPU shares become more even. ClickHouse and each Manticore daemon on different nodes is the
  lowest goal.
- The same inputs give the same plan.

When memory does not fit at any factor, the step and the check fail. The message names the free memory of each node
and the pods without room. When a plan fits only with a move of running pods, the message says so.

The pod templates of the renders keep the CPU requests at the factor 1 and name no planned node. So a new plan or a
new factor changes no template and restarts no pod. The plan reaches the pods in these ways:

| Part | Mechanism |
|---|---|
| New pods | The ConfigMap `hoover-placement` of `kube-system` holds the factor and the planned nodes of each workload. The MutatingAdmissionPolicy `hoover-site-placement` ([cluster/placement-policy.yaml](cluster/placement-policy.yaml)) reads it when a pod of `hoover-stores` or of a zone is created. It multiplies each CPU request by the factor, rounded up to 1m, and adds a preferred node affinity of weight 100 for the planned nodes. The annotations `hoover.dev/cpu-scale` and `hoover.dev/planned-nodes` record both. |
| Running pods | The step resizes the CPU requests of each running pod of a Deployment or StatefulSet of the site in place (the `resize` subresource) to the request of its template times the factor. A CPU resize restarts no container in gVisor and in Kata. The annotation `hoover.dev/cpu-scale` gets the factor. |
| Store volumes | The stores step writes the planned nodes of each store pod with a local volume into the required node affinity of its StatefulSet. The ConfigMap `shared-stores` records them under `placement`. |
| Pods away from their planned node | They stay. `up --rebalance` moves them ([Move the pods to their planned nodes](#move-the-pods-to-their-planned-nodes)). |

The step writes the ConfigMap and resizes a pod only when a value differs, so a second `up` changes nothing. The plan
is kept in `placement/plan.json` of the state folder, and the cluster copy of the state holds it.

### Move the pods to their planned nodes.

```sh
k3s/deploy-k3s up --target all --rebalance
k3s/deploy-k3s up --target all --rebalance --steps rebalance
```

A normal `up` keeps each running pod on its node. The CPU shares of the nodes can therefore stay uneven, for example
after a zone create. Run `--rebalance` in a maintenance window, because each moved pod restarts.

- The plan of the step `rebalance` starts from the current places. It moves a running pod only when the move makes
  the CPU shares of the nodes more even, and it keeps memory as the hard limit. It plans single moves, each of which
  fits the nodes after the moves before it. It plans no swap, because a swap needs room for both pods at once. A pod with a claim or a node
  selector, and a pod that is placed together with another workload, do not move. `plan.json` gets the list `moves`.
- The step writes the planned nodes into the ConfigMap of the admission policy, then moves one pod at a time: the
  next pod whose planned node has room now. It evicts the pod through the eviction API, so a PodDisruptionBudget
  applies, and waits up to 600 s until the new pod of its workload is ready.
- The step stops at the first failure: no planned node has room for the next move, the API refuses the eviction, the
  new pod starts on another node, or it is not ready in time. The pods that moved stay on their new nodes, and every
  other pod stays where it is. The record names the moved pods.

The stores step runs before the zones. When the new store pods fit only after the zones have their new requests, the
plan says `zones-first`, and `up` runs the stores step after the zone steps.

A zone operation of the portal uses the factor and the plan of the last `up`. Its new pods get the factor and no
planned node. Run `deploy-k3s up` after a zone create on a full site to compute a new factor.

### Isolate the zones in Manticore.

Each zone has three Manticore users in both daemons, with rights on the tables `<prefix>_*` only ([hoover/stores/service_users.py](hoover/stores/service_users.py) `MANTICORE_GRANTS`):

| User | Rights | Holder |
|---|---|---|
| `<prefix>_read` | `read` | The website and the collections server. They connect to the read-only HTTP listener 9309, which refuses every change and `SET ro=0`. |
| `<prefix>_write` | `read`, `write` | The workers, the singletons and the operations worker. The user inserts, replaces, updates and deletes rows, and optimizes and flushes tables. It cannot create, alter or drop a table. |
| `<prefix>_schema` | `read`, `write`, `schema` | Only the schema proxy of the zone, from the Secret `manticore-schema` of the Hoover namespace. |

A Manticore 29.9 user with the right `schema` can create a distributed table that names a table of another user, and then read that table. No zone service holds that user.
The schema proxy `manticore-schema` runs in the Hoover namespace of each zone with the processing image of the zone ([main_services/processing/database/manticore_schema.py](../main_services/processing/database/manticore_schema.py)).
The services with the write user send each table change to it with an operation name, its arguments and the proxy credential `manticore-proxy-token`. No SQL passes the proxy.
The proxy builds every table name from the table prefix of the zone, refuses a table of another zone, and has no operation that creates a distributed table.
The migrations of Hoover run at the proxy (operation `migrate`). Only the workers, the singletons, the operations worker and the website reach the proxy port.
The website holds `manticore-status-token`, a second proxy credential that allows only the operation `status`. The admin panel "Manticore load" reads the load counters of both daemons through it, because `SHOW STATUS` needs the right `schema`. The counters cover every zone of the site, and the panel says so. The table values of the panel come from the read user and cover the tables of the zone.

The collection export and restore run at the proxy too (operations `export_tables` and `import_tables`).
The data folder of the text daemon is a block volume in the Kata guest of its pod, so no other pod can mount it.
The container `files` of the daemon pod ([hoover/stores/manticore_file_service.py](hoover/stores/manticore_file_service.py)) mounts the same file system and serves the table files on port 9318:

| Access | Rule |
|---|---|
| Caller | A Manticore user whose name ends with `_schema`. The service checks the credentials with `SHOW TABLES` on the daemon. Only the schema proxies of the zones reach the port (policies `manticore-files-clients` and `egress-manticore-files`). |
| Read | A file of the folder of a table that `SHOW TABLES` of the caller lists. The export reads the files that `FREEZE` names. |
| Write | Files below `import/<caller>/<stage>/` of the data folder. The import stages the files there, `IMPORT TABLE` copies them into the data folder, and the import removes the stage. |
| Names | Lowercase letters, digits and underscores. A file name starts with the table name and a dot. The service follows no symbolic link. |

A zone proxy therefore reads the files of its own tables only, and writes only below its own stage folder. `IMPORT TABLE` of Manticore 29.9 takes any path that the daemon can read, also with the schema user of another zone, so the proxy builds the stage path from its own user and takes no path argument.
The proxy mounts the claim `ops-backups` of the zone at `/backups` and runs on the node of the operations worker. It reads and writes only the export folders of its zone. An export or import argument names one folder of `/backups`, and the proxy refuses another path.
The proxy keeps its running exports and imports in memory by an operation id of the caller. When Temporal cancels the export or import activity, the activity sends `POST /cancel` with the id. The proxy stops the operation before its next table or file, removes the artifacts or the stage and the partial tables of the operation, and then answers. A started `IMPORT TABLE` cannot be stopped, so the cancel waits for it. The cancel of an unknown or ended id succeeds.
An import fills each table under the name `<table>_partial<16 hex digits>` and renames it onto its target after the last table. No complete Hoover table has that end. At its start the proxy removes `import/<schema user>/` through the file service and drops the partial tables of its prefix, because a restart loses its table of operations. The Deployment has one replica with the strategy `Recreate`, so no other operation of the zone runs at that time.
Dropped Manticore tables leave an empty folder with a `.lock` file in the data folder. Neither the proxy nor the zone delete removes it.
The zone delete and the zone create read `SHOW TABLES`, `SHOW USERS` and `SHOW PERMISSIONS` as one XML answer of the mysql client (`shared.py manticore_list()`). An answer that `kubectl exec` cut, or an empty answer, stops the step, so a cut answer never reads as an empty tenant.

`kubectl exec -i` into a Kata pod stops the output after 16 to 32 KiB when the client closes the standard input, and the command then waits. `kubectl exec` without `-i`, and every gVisor pod, give the complete output. Each tool that sends input to a command in a Kata pod and reads its output keeps the standard input open until the command ends ([podexec.py](podexec.py) `run()` and `call()`): the SQL of the shared ClickHouse and Manticore (`shared.py`, `ch.py`), the ClickHouse reads of the backups, the ClickHouse of a Compose import, and the probes of `tools/storage-checks.py` and `tools/hoover-store-access-check.py`.
The import gives each table the prefix of the zone and the name after the prefix in the export, so a copy of another zone imports into the tables of this zone.

Manticore 29.9 stops `searchd` on a `GRANT` to an unknown user and on a `DROP USER` of an unknown user. The setup and the zone delete therefore read the users first.
A zone create adds the users, and a zone delete drops the tables `<prefix>_*` and the three users. Before it drops them, the zone delete removes `import/<prefix>_schema/` from the data folder through the container `files` of the text daemon pod. A delete without a ready daemon stops, and the users and tables stay until the next delete.
[tools/tenant-isolation-check.py](tools/tenant-isolation-check.py) `<zone> <other zone>` checks the isolation of ClickHouse, Garage, Manticore and Temporal from the pods of the zone, also the ClickHouse backup grant and the export bucket. Both zones need the collection `demo` with its Manticore tables.

### Lost store nodes

A store pod keeps its data on the volume of its node. When a node stops, the parts of the data on that node are out of reach until the node returns:

- ClickHouse: every zone loses access to its ClickHouse data.
- Manticore: every zone loses its search (text daemon) or its vector search (vectors daemon). When the volume is lost, `main.py reindex-collection` builds the tables of each collection again from ClickHouse.
- Garage: a read or write of an object in the part of that node fails.
- Cassandra: Temporal fails for the workflows whose rows are in the token ranges of that node.
- OpenSearch: the visibility queries fail when the node holds a primary shard of the visibility index. OpenSearch on several nodes stops when less than a majority of its nodes runs.

1. Find the store pod that does not run: `kubectl -n hoover-stores get pods -o wide`.
2. When its node returns, the pod starts again with its volume, and the clients reach it.
3. When the volume of a store is lost, its part of the data is lost. Restore the collections of each zone from their collection exports. The backups hold no copy of the Temporal history.

The stores of an earlier version kept several copies (`vars.stores replicas` and `failover`). The stores step and `deploy-k3s check` refuse them. Delete every zone, delete the namespace `hoover-stores` (`kubectl delete namespace hoover-stores`, which deletes its claims), run `deploy-k3s up --steps stores`, and create the zones again. The data of the zones does not move.

## Run the processing pools of the site.

ClamAV and the stateless file processors (Tika, Tesseract, the searchable-PDF builder, the PDF search and the regex
scanner) run once for every zone of a site, in the namespace `hoover-pools` ([hoover/pools.py](hoover/pools.py)). The
step `stores` of `deploy-k3s up` applies them after the shared stores. A site without a zone of the store layout `site`
runs no pool. A zone of the local store layout keeps its own copies.

- The Hoover installation of a zone renders no copy of these services. Each Compose name, for example `hoover4-tika`,
  is an ExternalName Service of the pool, so the Hoover services keep their addresses.
- A pool holds no zone identity and no store credential, and reaches no store.
- The operator settings have one scope `pools` for the pools of the site (`POOLED` in
  [platform/operator/settings.py](platform/operator/settings.py)). Examples are `budget.clamav_memory_mib`,
  `budget.tika_cpus` and the concurrency of each service.
- The Hoover installations of the store layout `site` read the same values, so their worker slots match the pools.
  Their own scope does not list these settings.
- A pool setting that an earlier revision saved in such an installation has no effect. The first step of an Apply
  names it once in the operation log. The step `stores` of `up` names it in its result. The settings page can remove it.
- A zone of the local store layout keeps these settings in its own scope.
- An Apply of a pool setting runs `pools.py apply` in the step `pools`. It restarts only the pods of the changed pools.
- The workers also read some pool settings (`POOL_CLIENT_KEYS`), for example `main_services.clamav_concurrency`. A
  change of one of them also renders each installation of the store layout `site` again.
- A changed Tika configuration changes the annotation `hoover.dev/config` of the Tika pods, so they restart.
- The searchable-PDF builder holds no object store key. The workers send the source in the request and write the PDF of
  the answer into the collection bucket with their own key (`OCR_PDF_TRANSFER=inline`). Compose keeps the object form.
- A zone create makes the pools when the site has none, and the delete of the last zone removes them (`pools.py
  ensure`). A running pool stays as it is, so a zone create, apply or delete changes no pool pod. `up` applies the saved
  pool settings in the step `stores`.
- Network: each pool takes connections on its own ports from the workers, the singletons and the website of the Hoover
  namespaces. The searchable-PDF builder reaches Tesseract. ClamAV reaches the internet for its signature updates. A
  pool reaches no store, no zone namespace and no other pool. With a GPU pool, the searchable-PDF builder reaches
  EasyOCR through the forwarder `gpu` of `hoover-pools`, whose token has the name `hoover-pools`.
- No pool keeps a file of a request. Tika, Tesseract, the searchable-PDF builder and the PDF search write each request
  into a temporary file or folder that they remove before the answer. clamd scans the stream in a temporary file and
  removes it. [tools/tenant-isolation-check.py](tools/tenant-isolation-check.py) lists the temporary folders of every
  pool pod, and [tools/hoover-network-check.py](tools/hoover-network-check.py) checks the connections.
- The memory request of each pool is the measured peak of its workload in the part `hoover` of
  [zones/memory-requests.json](zones/memory-requests.json). The concurrency settings of a service limit the requests that
  one pod works on, so more zones give a pool more waiting requests and no more working memory. A zone load measurement
  (`memory_requests.py measure --zone`) also measures `hoover-pools`.
- A site of an earlier version moves to the pools in one `up`. The placement plan runs the stores step after the zone
  steps when the pools fit only after the zone copies leave. The ingest of a zone then waits for the pools: the
  activities that call a pool fail and Temporal runs them again.

## Scale the stateless services.

`vars.replicas` of the site file sets the pod count of each processing pool. The Service of the service spreads the
connections over its ready pods. The [site placement](#place-the-pods-of-the-site) counts every pod of the count.
`deploy-k3s check` and `up` fail when the memory requests then do not fit the nodes. A CPU shortage lowers the CPU
scale factor.

```yaml
hoover4:
  vars:
    replicas: {tika: 2, tesseract-cpu: 2}
```

| Service | Key | Scales |
|---|---|---|
| Tika, Tesseract, the searchable-PDF builder, the PDF search, the regex scanner | `tika`, `tesseract-cpu`, `ocr-pdf`, `pdf-search`, `regex-entity-scanner` | Yes. Each request is complete in one pod. |
| ClamAV | `clamav` | Yes, on the public node, because it loads its signatures from the internet. Each pod loads its own signatures. With signature updates on, two pods can report other database versions for a short time. |
| Workers | `budget.worker_pods` (operator setting) | Yes, by their own setting. |
| Singletons, operations worker | none | No. They are single writers. |
| Website | none | No. It keeps the open chat streams and polls of its users in its memory. |

On a site with a zone of the store layout `site`, the concurrency settings (for example `tika_concurrency`) belong to
the scope `pools`. In the local store layout they belong to the installation. They set the slots of each pod of a
service and the slots of the workers of each zone that call it. A larger `vars.replicas` count gives the service more
capacity. A pool answers 503 when its queue is full, and the worker runs the activity again later.

## Share Temporal in a site.

One Temporal serves every zone of a site, in the namespace `hoover-stores` ([hoover/stores/temporal.py](hoover/stores/temporal.py)). The step `stores` of `deploy-k3s up` creates it with one Cassandra cluster for its history and one OpenSearch cluster for its visibility index. Temporal uses no PostgreSQL.

- Each zone with `stores = site` has its own Temporal namespace, with the name of the zone. A zone create registers it with the retention of the setting `main_services.temporal_retention` of the zone and adds the search attribute `CollectionDataset`. A zone delete removes it.
- The Hoover services of the zone that call Temporal (website, workers, operations, the to-do server) get `TEMPORAL_NAMESPACE` and the key of the zone in `TEMPORAL_API_KEY` from the Secret `hoover-runtime`. The key is a JWT with the permission `<zone>:write`. Temporal checks it on each request (the default authorizer and claim mapper). It permits the workflows, task queues and visibility of the zone namespace only, and no change of a namespace or of a search attribute. A request without a key or for another namespace gets `PERMISSION_DENIED`.
- The signing key is in the Secret `temporal-auth` of `hoover-stores`. A sidecar of each Temporal pod publishes its public key on 127.0.0.1. A key has no expiry. To replace every key, delete the Secret `temporal-auth`, run `deploy-k3s up --steps stores`, then apply each zone again.
- Cassandra runs one pod on each of its `cassandra.nodes` nodes, and OpenSearch one pod on each of its `opensearch.nodes` nodes, in gVisor on file system volumes. The keyspace `temporal` has the replication factor 1, so the Cassandra nodes share the token ranges, and Temporal reads and writes with the consistency `LOCAL_ONE`. The visibility index has one primary shard for each OpenSearch node of its creation and no replica shard. Temporal runs `temporal.pods` pods with every Temporal service, preferably on different nodes. Temporal holds no data.
- `history_shards` sets the history shard count of a new Temporal. Temporal keeps it from its creation, so `deploy-k3s check` and the stores step refuse a change.
- Sizes: the Cassandra heap is 1.5 GiB plus 0.4 GiB for each GiB of live data (`cassandra.data_gib`), at least 1.5 GiB and at most 8 GiB. The default of 2 GiB of data gives a 2368 MiB heap. The Cassandra memory request is the heap plus 1 GiB, which covers the measured use outside the heap. The limit adds 1 GiB and the live data for the page cache. OpenSearch has a 1280 MiB heap, a request of 1920 MiB and a limit of 3584 MiB. Each Temporal pod requests 448 MiB. The claims hold 20 GiB (Cassandra) and 10 GiB (OpenSearch) for each zone with `stores = site`, at least one zone.
- Network: only namespaces with the label `hoover.dev/hoover` reach the frontend on 7233 (gRPC) and 7243 (HTTP). The internal frontend on 7236, which checks no key, and the other Temporal ports take only the Temporal pods. Cassandra and OpenSearch take only the Temporal pods and the schema Job.
- [tools/tenant-isolation-check.py](tools/tenant-isolation-check.py) also checks that a zone cannot describe, list, start, signal, cancel or terminate a workflow in the namespace of another zone.
- A zone created before the Temporal of the site has `temporal = zone` and ran its Temporal on the PostgreSQL of the zone. Delete it and create it again. Its workflow history does not move.
- The zone copy of the backups does not hold the workflow history of a zone with `stores = site`.

## Render a Hoover installation.

```sh
python3 k3s/hoover/manifests.py <zone> show --revision <commit>
python3 k3s/images/build-hoover.py --revision <commit>
```

`show` prints the objects and changes nothing.
The argument is the zone. The render reads the addresses of the NFS servers of `platform/hoover-data/` from the cluster.
The tag of each image is a digest of its inputs at the commit: its Containerfile and its context, and for the
website image also `docs/user-manual/` ([hoover/compose.py](hoover/compose.py) `image_tags()`). A commit that
changes no input of an image keeps its tag, so `up` builds no image and restarts no pod for it. `deploy-k3s` computes
the tags once for each deployment, keeps them in the record and gives them to every step in `HOOVER4_IMAGE_TAGS`.
The build skips an image whose tag the registry has. It exports the commit for the other images, so local changes stay
out of the images.
The website image holds the manuals of `docs/user-manual/` for the `/docs` page. The build copies them into the `website/` context of the exported tree.

## Keep the state in the cluster.

The cluster holds the authoritative zone state and operator state. [clusterstate.py](clusterstate.py) keeps one object for each file in the namespace `operator-portal`.

| Files of the state folder | Objects |
|---|---|
| `zone-state.json`, `operator/` (settings, revisions, Apply operations and their logs, backup and relay state), `operations/` (the logs of the zone operations), `facts/`, `frontend/local-ca.crt` | ConfigMaps with the label `hoover.dev/state=file` |

- The annotation `hoover.dev/state-path` of each object names its file. A log keeps its last 256 KiB in the cluster.
- The secrets are in the secret store ([Keep the secrets in OpenBao.](#keep-the-secrets-in-openbao)). `zones/` of the
  state folder holds copies that the zone tools write from the store, and the cluster copy does not keep it. Only the
  runner container of the operator pod mounts `zones/`, so the portal container reads no copy of a zone secret.
- `operator/deploy/` (the records of `deploy-k3s`), the tokens, the kubeconfig and the downloaded tools stay only in the state folder, because the workstation needs them before a cluster exists.
- `deploy-k3s` reads the cluster copy into the state folder after it takes the site lock, and before `render` and `check`. After each step it writes the changed files back. The state folder keeps an export copy for inspection.
- A folder keeps the digest of each file and the `resourceVersion` of its object from the last synchronization. A write of a file that another writer changed fails with a conflict, and the next run reads the newer copy first.
- `python3 k3s/clusterstate.py pull|push <state folder>` reads or writes the copy by hand. `KUBECONFIG` names the kubeconfig.

The operator pod (Deployment `portal` of `operator-portal`) runs the portal and the zone runner from the operator image of the registry ([platform/operator/pod.py](platform/operator/pod.py)).
It mounts no checkout and no host state folder. Each container reads the cluster copy into a folder of the pod at its start. The runner reads the secrets from the secret store and keeps their copies in its own memory folder, so the portal container cannot read them.
The pod runs on the control-plane node. When the site file has `backup`, it runs on the backup node, and the runner container mounts the backup folder of that node at the same path ([platform/operator/backup-mount.py](platform/operator/backup-mount.py)).
The portal page then shows the cluster slice of the backup node.
The runner uses the token of the ServiceAccount `zone-runner` and needs no SSH access. The HTTPS frontend serves every zone host, so a zone operation does not change it.
A create or upgrade checks that the frontend answers for `<zone>-portal.<domain>` with a valid certificate, and stops at the step `frontend` until it does. `deploy-k3s up --target <public node> --steps frontend` on the workstation installs the frontend.
The runner checks that the registry has the images of the revision. `deploy-k3s up --steps images` builds them.

## Keep the secrets in OpenBao.

[platform/secrets/openbao.py](platform/secrets/openbao.py) runs OpenBao, the secret store of the site, and [secretstore.py](secretstore.py) is its client.
The step `secret-store` of `deploy-k3s up` installs it after the step `cluster`, and every later step waits for it.

- OpenBao runs as the StatefulSet `openbao` of the namespace `openbao`, with one pod in gVisor on the control-plane node.
  The pod has the PriorityClass `hoover-node-bound`, a 128 MiB memory request and Raft storage on a 2 GiB claim.
  One pod is enough, because the site has one k3s server, and the pods read Kubernetes Secret copies, so a stopped store stops no service.
- OpenBao unseals itself at each start, also after a power loss, with the static seal key `secret-store/seal.key` of the state folder of the deploying host.
  The Secret `openbao-seal` holds the same key, and only the OpenBao pod mounts it. A key of the state folder that differs from the Secret stops the step.
  The first start writes the recovery key into `secret-store/recovery-key`. The root token configures the store once and is then revoked.
- The k3s server keeps the Secrets encrypted at rest (`secrets-encryption`). A server without it gets it at its next `hosts:k3s` step: `k3s secrets-encrypt enable`, a restart with the flag, `rotate-keys`, which encrypts every Secret again, and a second restart.
- The listener uses TLS with a certificate of a CA that the step makes once. The ConfigMap `openbao-ca` of `operator-portal` holds the CA certificate.
  The runner calls the Service `openbao.openbao.svc`. The workstation reaches the pod through `kubectl proxy` and the API server, because a port-forward does not reach a listener in gVisor. The network policy admits only the operator pod and the node of the pod.
- Each secret is a path of the KV version 2 mount `hoover`, which requires check-and-set on each write. A write names the version that it read, so a write after another writer reads and changes again, and both changes stay.

  | Path | Secrets |
  |---|---|
  | `site/calls` | the JVB password and the LiveKit secrets |
  | `site/zone-users` | the password of each user of [zones/zone-users.json](zones/zone-users.json) |
  | `site/stores`, `site/temporal`, `site/gpu` | the Secret `hoover-stores` of the shared stores, the Temporal signing key, the GPU key |
  | `site/operator-login`, `site/registry` | the operator login and the registry push password |
  | `zones/<zone>/secrets` | the secrets of the zone: master password, client secrets, TURN secret, Garage key, PostgreSQL passwords |
  | `zones/<zone>/test-user`, `zones/<zone>/imported-users` | the test.user password and the users of a Compose import |
  | `zones/<zone>/stores`, `zones/<zone>/garage-tenants`, `zones/<zone>/hoover/<Secret>` | the store credentials of the zone and the Secrets of its Hoover namespace |
  | `zones/<zone>/records/<file>` | the records `opendesk-applied.json`, `objectstore-move.json` and `postgresql-move.json` |

- A step that owns a secret keeps it in the store and writes its Kubernetes Secret from the store. A missing value is generated once, and a stored value never changes.
  A Secret or a file of an earlier version gives the values that the store lacks. A value that differs from the store stops the step with the path and the key, and the services keep the value of the Secret.
- A process logs in with the Kubernetes auth method. The role `deployer` uses a short token of the ServiceAccount `openbao-deployer` and administers the store. The roles `runner` and `backup` use the token of the ServiceAccount `zone-runner`.
  The runner reads and writes the paths of `hoover` and creates zone step tokens. The backups read every path and take and restore the snapshot of the store.
- `zone.py` uses a token of the token role `zone-step` for its zone. Its policy reaches `zones/<zone>/` of that zone only, and reads `site/calls` and `site/zone-users`, which the step `secret-store` writes. `tools/runner-scope-check.py <zone> <other zone>` checks these policies.
- `zones/` of the state folder holds copies: the values, the master password, the client Secrets, `fixture-user-passwords.json` and `test-user-password`. `zones.py` writes them from the store at each zone apply.
- `tools/write-password-table.py` prints the login table from the store and the live Secrets. Redirect it to a private file when a person needs a copy.
- An earlier version kept `zones/` as Secrets of `operator-portal` with the label `hoover.dev/state=secret`.
  The step `secret-store` loads their secret values into the store and reads each value back. A value that the store holds with another value stops the step before any write.
  The step `operator` checks each value again after the operator pod of the new version runs.
  It then deletes the earlier Secrets and the files `zones/secrets.json` and `zones/passwords.md` of the state folder.
- `python3 k3s/platform/secrets/openbao.py status` prints the seal state, the version and the paths of the store.

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
- The scope `pools` holds the settings of the processing pools of the site
  ([Run the processing pools of the site.](#run-the-processing-pools-of-the-site)). It exists when the site has a zone of
  the store layout `site`.
- The zone settings `app.<name>` turn openDesk applications and Hoover off and on. An application that is off has zero replicas and keeps its claims.
  The zone memory limits and the cluster CPU policy reach the zone render through [zones/postrender.py](zones/postrender.py).
- The backup policies are settings: `backup.opendesk.*` and `backup.hoover.*` of each zone, and `backup.platform.*` of the cluster.
  `backup` of the site file names the destination. Without it the portal keeps the backup controls off.

## Reach an installation from the workstation.

`platform/mcp-relay/install-relay.py <installation> apply` runs the Deployment `mcp-relay` with runc in the host network of the control-plane node.
It listens on 127.0.0.1 only and forwards each port to a Service of the installation: the five MCP servers, the Temporal, ClickHouse and Manticore interfaces, the stores and the research agents.
`kubectl port-forward` does not reach a pod in gVisor, so the relay replaces it.

- `--ports compose` uses the ports of the Compose install of the installation, so `.mcp.json` and the harness files stay unchanged.
- `--ports temporary` adds 1000 to each port, so a check can run while Compose still holds its ports.
- The relay keeps the chosen mode in `<operator state>/mcp-relay.json`. The driver step `mcp-relay` applies it again.
- `tools/mcp-relay-check.py <name>=<port> ...` sends the MCP requests of a development client to each port.

The website of an installation is `https://<zone>-hoover.<domain>/`. A user signs in through the Keycloak of the zone.
The browser harness (`website/take-screenshots.sh`) runs Chromium in a container that must reach that name and trust the local CA.
`tools/harness-browser.sh start` runs the container `hoover4-harness-browser` from the Compose image of the browser server, in the host network, with the local CA as a Chromium policy.
It reads the local CA from the state folder of the site that `HOOVER4_SITE` names.
Set `BROWSER_CONTAINER=hoover4-harness-browser`, pass `--target https://<zone>-hoover.<domain>`, and give a zone login in `HOOVER4_TEST_USERNAME` and `HOOVER4_TEST_PASSWORD`.

## Move a Compose installation into the cluster.

`deploy-k3s import-compose` imports a stopped Compose installation into a new zone ([import_compose/import_compose.py](import_compose/import_compose.py)).
The site file, the zone state, the operator portal and the host roles have no Compose key. Every Compose input is an argument of this command.
The command runs once per zone. A zone that exists stops it, and so does a finished import of the same zone.

```sh
k3s/deploy-k3s import-compose <zone> <folder> --home <node> --ini <file> --dataset uploads=<folder> --dry-run
k3s/deploy-k3s import-compose <zone> <folder> --home <node> --ini <file> --dataset uploads=<folder>
k3s/deploy-k3s import-compose <zone> --users       # a zone user for each owner of chats and boards
k3s/deploy-k3s import-compose <zone> --status
python3 k3s/platform/mcp-relay/install-relay.py <zone> apply --ports compose
```

- `<folder>` is the Compose volume folder, relative to the `data_root` of the source node. A bind mount can put the folder there. An absolute path, `..` and a symbolic link out of the data root are refused.
- `--ini` names the `hoover4.ini` of the Compose installation, relative to the folder of the site file. Its explicit values become operator settings of `hoover:<zone>`, with the Temporal history shard count of the source.
- `--dataset <name>=<folder>` copies the folder of a dataset mount of the ini into the claim `dataset-<name>`. Each writable mount needs it or `--without-dataset <name>`. A site with data nodes keeps its dataset folders on NFS, so the plan refuses a dataset there.
- `--home` names the node with the role `worker` that receives the store volumes and the store images. The copy pod binds the claims there, and the pods of the local layout that share the claims follow them. The zone state does not keep this value.
- `--source-node` names the node that runs Compose. The default is the `--home` node. The command connects with `ssh` and runs its root commands with `sudo -n` on that node and on the `--home` node.
- `--engine docker|podman` names the runtime of the source. A rootful Docker keeps the host owners, and rootless Podman maps them through its user namespace.
- The command runs every unfinished step in order. `--until <step>` stops after a step. The records are in `<state folder>/operator/import/<zone>/`, which stays on the workstation.

| Step | Result |
|---|---|
| `plan` | Checks the folders on the source node, the images, the claims and the free capacity, and pins the inputs. It saves `app.hoover = false` for the zone. |
| `freeze`, `record`, `stop` | Stop the intake and the workers, record Temporal and the store contents, then stop Temporal and the stores. |
| `zone` | Runs `zone.py apply` with `stores = local`, which runs the Compose Temporal in the Hoover namespace. The Hoover objects have zero replicas. |
| `images`, `copy`, `secrets` | Import the source store images. Copy each folder into its claim with the mapped owners and a SHA-256 of every file. Write the Compose store credentials. |
| `stores` | Starts the stores and Temporal, and compares them with the record. |
| `renames` | Gives the databases, the Manticore tables and the Garage bucket aliases the names of the zone. Changes the bucket names of the `*s3_path` columns and the container paths of the dataset rows. |
| `temporal`, `workers`, `resume` | Compare Temporal with the record, start every service, and wait until each open workflow continues or closes. |

The source folders stay unchanged. To return to Compose before the zone takes new work, delete the zone and run `./deploy`.
After the zone takes new work, a return to Compose loses that work.

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
A site without a zone runs only coturn, because only a zone uses LiveKit, and the JVB copies its template from a zone.
A media node with a public address advertises it, and the clients send their media straight to it: UDP 10000 (JVB), TCP 7881 and UDP 7882 (LiveKit), UDP and TCP 3478 (TURN).
coturn relays UDP only, so a TURN user reaches no store of a zone, which all serve TCP.
It relays to the pods of the media node and, on a media node with a public address, to that address for a client that can only use TURN.
The pods of the other nodes and the bridge address of the media node are no peers ([platform/calls/turn_peers.py](platform/calls/turn_peers.py)).
The chain `coturn_peers` of [coturn-peers.sh](ansible/roles/hoover4_public_firewall/files/coturn-peers.sh), in its own table, limits the public address to the LiveKit media ports for the coturn user, so a TURN user reaches no other port of the node.
The steps `operator` and `calls` of `deploy-k3s up` check that chain with a probe pod in the host network of the media node (`install-calls.py --probe`).
They record the result in the ConfigMap `coturn-peer-check` of `calls`.
The pod admission policy of `calls` refuses a host network pod other than coturn, so the probe pod runs in `kube-system` with the admin kubeconfig.
The probe pod and the call services must run on the media node, so they have the PriorityClass `hoover-node-bound`. On a full media node they preempt a pod of the default priority. The probe requests 16 MiB for each of its two containers.
The record names a digest of the inputs of the chain (the media node, its public address, `turn_peers.py` and the files of the role). The probe runs again only when that digest changed. `install-calls.py --probe --force` runs it at once.

A zone create or delete restarts no call service, so the calls of the other zones continue
([platform/calls/install-calls.py](platform/calls/install-calls.py)):

| Service | Zone keys | Change of a zone |
|---|---|---|
| coturn | one TURN secret for each zone, and one for LiveKit, in the SQLite database of coturn | The Secret `coturn-secrets` lists the secrets. The sidecar `secrets` copies them into the database when the mounted file changes. coturn reads the secrets from the database at each request. |
| LiveKit | one key `hoover-calls` for all zones | Nothing changes in LiveKit. LiveKit reads its keys only at start, so a key for each zone would restart it. |
| JVB | one XMPP password for all zones | The Secret `jvb-zones` lists the Prosody of each zone. The sidecar `zones` adds and removes the XMPP connection of each zone through the REST API of the bridge (`/colibri/muc-client/add` and `remove`). It adds all connections again when the bridge restarts. |

The kubelet updates a mounted Secret within about one minute, so a new zone reaches coturn and the JVB in that time.
The shared LiveKit key is an access boundary change: the token service (`lk-jwt`) of each zone holds the key, so the
service of one zone can sign a token for a room of another zone. The Matrix room of a call names the LiveKit room.
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
The `backup` node holds the backup folder (`path`). The operator pod runs on that node, and its runner container mounts the folder at the same path.
The runner writes, checks, lists and removes the copies as files of that folder, so no copy needs SSH, a user entry or a key.
The host step `hosts:prepare` creates the folders `zones/`, `platform/` and `staging/` and the marker `.hoover4-backup-destination`, owned by the user of the operator pod (uid 1000).
When the fstab of the node names a mount at the path and the file system is not mounted, the step writes nothing there.
The commands take names: a zone, a collection, a job and a generation (the name of a copy). No command takes a host path.
Run them in the runner container, because only that container has the folder:

| Copy | Folder below the backup folder |
|---|---|
| A complete zone: openDesk and its Hoover installation | `zones/<zone>/<generation>/` |
| A Hoover collection of a zone | `zones/<zone>/collections/<collection>/<generation>/` |
| The platform recovery set | `platform/<generation>/` |

```sh
run="kubectl -n operator-portal exec deploy/portal -c runner -- python3 /opt/hoover4/k3s/platform/backups/backups.py"
$run enable    # writes the folders and the marker, as the host step does
$run status
$run copies
$run verify zone:<zone> <generation>
$run restore-zone <zone> <generation> [--from <zone of the copy>]
$run restore-hoover <zone> <collection> <generation> [--from <zone of the copy>]
$run recovery <generation>
$run restore-platform <generation>
$run restore-secret-store <generation>
```

- The operator runner starts at most one due job each minute. [schedule.py](platform/backups/schedule.py) holds the rules: eligibility, the weekly limit, the slots and the retention.
- A Hoover collection gets a copy after its first completed ingestion and after each complete reprocessing, at most once in 7 days, and keeps one or two copies.
- Each zone and the platform recovery set get one copy each week, and keep two or three copies. The portal setting `backup.opendesk.*` controls the zone copy.
- A missing marker pauses every job, so a missing remote mount does not fill the local disk.
- A copy is made in `staging/<job>/<generation>.partial` of the backup folder, checked against its manifest and renamed into its folder. The rename moves no data. A failed job or check keeps the older copies.
- A restore reads a copy in place, after a check of every file against its manifest.
- Each tar stream from a pod must reach its end-of-archive marker, and each database dump must end with the end line of its dump tool. Otherwise the copy reads that part again, up to three times.
- The platform copy holds the newest scheduled etcd snapshot of the server with its token and k3s configuration, `private.tar`, `openbao.snap`, and `recovery.json` (format version 3).
  `openbao.snap` is the Raft snapshot of the secret store. The etcd snapshot holds the seal key in the Secret `openbao-seal`. `restore-secret-store` replaces the data of a running store with the snapshot of a copy. `recovery.json` names the snapshot time and the application copies that a complete recovery needs, because a snapshot holds no claim data. `recovery` also reads format version 2 and a copy of the earlier SQLite format.
  k3s saves an etcd snapshot every 12 hours and keeps 5 in `/var/lib/rancher/k3s/server/db/snapshots` (the k3s defaults). When the newest snapshot is older than 24 hours, the job fails with a message that names its age.
  The job starts the pod `k3s-snapshot-read` in the namespace `platform-backup` on the control plane. The pod mounts the snapshot folder, the token and the k3s configuration read-only, and the runner reads the files with tar through `kubectl exec` and checks their SHA-256. The job then deletes the pod. The runner needs no SSH and no access to a host.
  The pod runs as root without a capability and without an API token. The policy `k3s-snapshot-reader` ([platform/operator/runner-rights.yaml](platform/operator/runner-rights.yaml)) admits only this pod form in `platform-backup`, and the runner can only create, read and delete pods there.
  A pod that stays running is not necessary for a weekly job of under a minute. It would keep the token mounted and hold memory on the control plane all the time.
- The zone copy reads the running zone. No workload stops or scales. `workloads.json` of the copy records the replicas
  of the applications, gates and workers, which `restore-zone` applies. The next runner tick restores a closure that a
  job of an earlier version left. The earlier job key `opendesk:<zone>` reads as `zone:<zone>`.
- The parts of a zone copy hold different moments. `moments.json` names the start and the end of each part. The copy
  reads them in this order (`online_parts()` of [backups.py](platform/backups/backups.py)):

  | Part | Moment |
  |---|---|
  | `postgresql.sql`, `mariadb.sql` | `pg_dumpall` and `mariadb-dump --single-transaction`. Each database is at one moment. |
  | `postgresql/` | A `pg_dump` of each openDesk database of a zone on the shared PostgreSQL. Each database is at one moment. |
  | `claims/` | A tar file of each claim. A file can change while tar reads it. The LMDB files of OpenLDAP are read again until no write committed during the read. Redis and NATS read a file with a cut last record at their start. |
  | `objects/` | The objects of each openDesk bucket of the zone in Garage, with the key `<zone>-opendesk`, or of a SeaweedFS that has not moved, with its `admin` identity. Both have the same form. A bucket with a customer key (SSE-C) is read and written with that key. |
  | `hoover/<installation>/shared/` | ClickHouse `BACKUP` of the zone databases (each table at one moment), then the objects of the system bucket. |

  A database comes before the files and objects that its rows name. An object that a row names was written before the
  row, so the later copy holds it, unless the application deleted it in between. Objects without a row stay unused.
- The claim of a SeaweedFS that has not moved is not copied as a file, because its files change while it runs.
- The receipt queries use the ClickHouse of the store layout. The site layout uses the admin of the shared ClickHouse. The local layout uses the Compose credentials.
- The collection export reads each small frozen Manticore file whole, and a `.meta` file must be JSON. The archive entry gets the size of the bytes that the export read.
- Make sure that the backup folder is on another host. The system cannot check this.
- Each copy has `copy-manifest.json` with the SHA-256 of every file. A collection copy also holds the `manifest.json` of the export, which the import reads.
- A collection copy fails when the JSON metadata of a Manticore table in the export does not parse, because the import refuses it.
- A zone copy keeps the dumps of the zone databases, the objects of the object store, and one tar file for each other claim of the zone namespace, with the owners and modes, and the same parts of the Hoover namespace in `hoover/<installation>/`.
  A Block claim of a Kata store is read through its store container, so the store must run. A file system claim is read with `tar` in a running container that mounts it, else through a short reader pod on the node of the claim. A claim that a pod owns holds temporary files and is not copied.
- `restore-hoover` imports into an installation without that collection, or into a collection whose stores `drop_collection_database` removed.
- `restore-zone` restores a complete zone copy into an installed zone. It closes the zone and its Hoover installation and stops their stores, except the zone databases and the object store. A zone on Garage gets the objects of the copy in its openDesk buckets.
  It then replaces the objects of each bucket of the copy, applies the Secrets of each part, replaces the content of each claim, imports the dumps, restarts the databases and the object store, and opens the zone with the replicas of `workloads.json` (`closure.json` in a copy of an earlier version).
  All parts are in place before an application starts.
  A dump without its end line stops the restore before any change. `psql` and the MariaDB client stop at the first error, and the restore fails with that error.
  A copy part `hoover/<installation>/` restores into the installation of that name, or into the one installation of the zone.
  A failure leaves the zone closed. `<operator state>/backups/restore-<zone>.json` names the finished steps.

## Run the tests.

```sh
k3s/tests/run.sh             # render, state (with the portal routes) and driver (with the host scripts)
k3s/tests/run.sh import backup
k3s/tests/run.sh replay      # the workflow replay suite in the worker image
```

The render, state and driver suites run in a container with the repository mounted read-only.
The driver suite uses fake ssh, sudo, bash and kubectl commands and contacts no host.
They change nothing on the host or a cluster.
