# Install a cluster site

The k3s installation is experimental.

This manual installs Hoover and openDesk on a k3s cluster with `k3s/deploy-k3s`.
[The cluster deployment reference](../../../k3s/Readme.md) describes each command and file in detail.
Keep host names, addresses and credentials in the private site folder and in the private infrastructure inventory.

## Contents

- [Prepare the operator host](#prepare-the-operator-host)
- [Write the site file](#write-the-site-file)
- [Choose the node roles](#choose-the-node-roles)
- [Choose the certificates of the HTTPS frontend](#choose-the-certificates-of-the-https-frontend)
- [Give the operator SSH and sudo access to each node](#give-the-operator-ssh-and-sudo-access-to-each-node)
- [Install the site](#install-the-site)
- [Add a GPU node](#add-a-gpu-node)
- [Sign in for the first time](#sign-in-for-the-first-time)
- [Verify the installation](#verify-the-installation)

## Prepare the operator host

The operator host is a workstation that reaches every node with SSH. It runs the driver. The operator portal and the zone runner run as a pod in the cluster.

1. Install Python 3 and `podman` or `docker`. `k3s/deploy-k3s` builds the operator image ([k3s/images/operator](../../../k3s/images/operator)) when its inputs change.
   The image holds Ansible, `kubectl`, `helm`, `ssh` and `git`. The host needs no other tool.
2. Clone the repository. Every step runs the scripts of this checkout. The record of a run keeps the commit and the uncommitted changes.
3. Put the site file in a folder of your choice, for example `k3s/private/<site>.yml`. Git ignores `k3s/private/`.
   Its state folder is beside it, with the name of the file without its extension, for example `k3s/private/<site>/`.
   One checkout manages more than one site. Each site has its own site file and state folder.

## Write the site file

Give the site file to every command with `--site FILE`, or set `HOOVER4_SITE`. No command has a default site file.
Each command first prints the site id, the site file and the state folder. The site id is the domain with each `.` replaced by `-`.
The site file is the only file that holds host paths.

The site file is a YAML Ansible inventory with one group, `hoover4`.
[The single-node and remote examples](../../../k3s/tests/fixtures) show the format.

| Place | Content |
|---|---|
| `hoover4.vars` | The domain of the zones (`domain`) and the control-plane node. |
| `hoover4.vars.networks.<name>` | One WireGuard network: its range (`cidr`), interface, hub nodes, port and the switch `managed`. |
| `hoover4.vars.lans.<name>` | One LAN, with an optional range (`cidr`). |
| `hoover4.hosts.<name>` | One node: its roles (`node_roles`), its address in each network and LAN, its public address, the volume group of each storage tier (`storage`), the switches of its host changes, and the TLS mode of a public node. |
| `hoover4.vars.gpu_pool` | The GPU nodes or the address of an external GPU pool. |
| `hoover4.vars.backup` | The backup node and the backup folder on that node. |
| `hoover4.vars.deploy` | The count of zone steps that `deploy-k3s up` runs at the same time (`parallel_zones`, default 2). |
| `hoover4.vars.stores` | The nodes and node counts of the shared stores, and the zone count (`zones`) that the store placement reserves memory and CPU for. |
| `hoover4.vars.replicas` | The pod count of each stateless processing service of every zone, for example `tika: 2` (default 1). |

Check the file before each change:

```sh
python3 k3s/config.py check <site file>
```

The check prints the switches of each node and the WireGuard peer table. Prepare these items on the nodes before the first run.

1. Create a volume group for each storage tier of each node, for example with `vgcreate`. The installer changes no disk.
   The facts play of `k3s/deploy-k3s check` refuses a volume group that the node does not have.
2. Choose the switches of each node: `stop_docker`, `k3s_volume_group` and `public_firewall`.
   [The reference](../../../k3s/Readme.md) lists what each switch changes.
3. A site without a WireGuard network connects its nodes at their LAN addresses. Give each node `lan` and declare the LAN in `vars.lans`.
4. The cidr of each network, and of each LAN that states one, reaches the admin routes of the HTTPS frontend.

The facts play reads the architecture, AVX2, the GPUs and the volume group sizes of each node. Do not write them in the site file.
The first `up` measures the CPU speed and the write speed of each storage tier of each node before k3s starts, and keeps them.
To measure a node again, follow [Measure the node speed](../../../k3s/Readme.md#measure-the-node-speed).

## Choose the node roles

| Role | Work of the node |
|---|---|
| `control-plane` | Runs the k3s server with the embedded etcd datastore. A site has one control-plane node. |
| `worker` | Runs the pods of the zones. |
| `public` | Receives the public HTTPS traffic and runs the HTTPS frontend. |
| `registry` | Holds the image registry. |
| `data` | Exports the dataset folders of the Hoover installations over NFS. |
| `calls` | Runs the TURN and media servers of the video calls. |
| `gpu` | Runs the GPU services. A GPU node has no other role. |

Every k3s server uses embedded etcd, also on a site with one node. One server does not make the datastore highly available.

## Choose the certificates of the HTTPS frontend

The HTTPS frontend runs on the first public node. Set `tls_mode` in its entry of `hoover4.hosts`.
`config.py check` refuses a missing key of the selected mode, so `up` stops before the first step.

| `tls_mode` | Use it when | Keys |
|---|---|---|
| `cloudflare` | The domain is at Cloudflare. certbot gets a public certificate for `*.<domain>` and `<domain>` with the DNS challenge. This is the default of a node that is not local. | `tls_dns_credentials_file`: the certbot Cloudflare credentials file on the public node. |
| `internal` | The site is on a LAN or has no public domain. Caddy issues the certificates from its own CA. This is the only mode of the local node of a single-node site. | No key. |
| `files` | You have a certificate from another authority. | `tls_certificate_file` and `tls_key_file`: the full certificate chain and the key, as files on the public node. |

With `internal`, the frontend step copies the root certificate of the CA into `frontend/local-ca.crt` of the state folder, and prints that path.
Import that file as a trusted certificate authority in each browser that opens the site. The pods of the zones trust it without a change.

With `files`, the certificate must have the name `*.<domain>`. A certificate without it stops the frontend step with a message.
Replace the files on the public node, then run the frontend step again.

Each zone host is `<zone>-<app>.<domain>`, for example `zone-a-portal.<domain>`. The name `*.<domain>` covers every zone, so a new zone needs no new certificate.
Point the DNS records `*.<domain>` and `<domain>` to the public node, and `turn.<domain>` to the media node. `deploy-k3s render` prints them. A new zone needs no new DNS record.

## Give the operator SSH and sudo access to each node

The host steps are Ansible plays ([k3s/ansible](../../../k3s/ansible)) that the driver runs in the operator image.
The image mounts `~/.ssh` read-only and the SSH agent socket, so `ssh` uses the configuration and the keys of the current user.
Ansible writes new host keys into `known_hosts` of the state folder.

1. Give the user of the workstation SSH access with a key to every node. The driver runs `ssh <node name>`.
   Add a `Host` entry with the node name, the address and the user to `~/.ssh/config`.
   A node whose `Host` alias has another name names that alias in `ssh_host`. The site file holds no address, port or user for SSH.
2. Give that user `sudo` on every node.
   Without a password, the plays run unattended. With a password, add `--ask-become-pass` to the command. The driver asks once for each command.

The installer adds no SSH key, no sudo rule and no root script to a node.
The host play removes `/usr/local/libexec/hoover4`, the sudo rule `/etc/sudoers.d/90-hoover4` and the revision folders of `~/k3s-install` of an earlier installer.

## Install the site

1. Name the site file for the commands of this shell:

   ```sh
   export HOOVER4_SITE=k3s/private/<site>.yml
   ```

2. Show the configuration and the steps. The command changes nothing.

   ```sh
   k3s/deploy-k3s render --target all
   k3s/deploy-k3s check --target all
   ```

3. Install the site from the commit of the checkout:

   ```sh
   k3s/deploy-k3s up --target all
   ```

   The steps `hosts:prepare` and `hosts:k3s` run one Ansible play each on all target nodes in parallel.
   The k3s play writes the admin kubeconfig into the state folder, with the node address of the server. `hosts:verify` reads every node through it.
   The driver then installs the cluster services, the registry, the images, the ingress, the HTTPS frontend, monitoring, the operator portal and runner, the GPU services, each zone and the call services.
   Before the step `stores` creates a store pod with a volume, it chooses the node of that pod. `k3s/deploy-k3s check` prints the plan in `store_placement` and refuses `vars.replicas` counts that the nodes cannot hold. See [the store placement](../../../k3s/Readme.md#place-the-store-pods).
   A step starts when the steps that it needs are done, so independent steps run at the same time. For example, the ingress, the frontend, monitoring and the images run together after the registry. The step `prepull` pulls the zone images on every eligible node while the zones apply. `vars.deploy.parallel_zones` of the site file limits the zone steps that run at the same time (default 2). The output lines of a step start with the step name in brackets.
4. When a step fails, read its error, correct the cause, and continue with the same inputs:

   ```sh
   k3s/deploy-k3s up --resume <record>
   ```

   A resume refuses a changed site file, another commit of the checkout and another cluster. Start a new run after such a change.
5. A complete run writes `deploy/applied.json` in the operator state. `k3s/deploy-k3s status` shows the applied revision.

## Add a GPU node

A GPU node can keep its existing VPN interface. Then name that interface in the site file and turn off `managed` for the node.

1. Add a node to `hoover4.hosts` with the role `gpu` and its entry in the cluster network, for example
   `networks: {site: {address: <address>, public_key: '<key>', interface: <interface>, managed: false}}`.
   The public key is the key of the existing VPN interface of the node.
   The installer configures nothing on that interface. The nodes that peer with it, for example a hub, add a direct peer for it.
   Add the reverse peers on the GPU node by hand. The peer table of `k3s/deploy-k3s check` lists them with `by: hand`.
2. Install the NVIDIA driver on the node. The k3s play refuses a GPU node where `nvidia-smi -L` fails.
   The host play adds the NVIDIA repository and installs the NVIDIA container toolkit when the node does not have it.
3. Run `k3s/deploy-k3s up --target <name> --steps hosts`.
4. Stop the Compose GPU services of the node only after the GPU pool of the cluster answers authenticated requests.

The GPU services of the site share one GPU key, which `k3s/deploy-k3s up` generates. Open **GPU key** on the operator portal to copy it.
A Compose GPU host at `gpu_pool` `address` needs the same key in the file of its `[ai_services] vllm_api_key_file`.
To keep the key of an existing Compose GPU host instead, give that key to `python3 k3s/hoover/gpu.py set-key` on standard input before the first `up`.

The direct peer takes the VPN address of the GPU node away from the earlier route of the peer node.
Until the reverse peer exists on the GPU node, the peer node cannot reach that address. A GPU pool at that address then does not answer it.
Add the reverse peer first. Then run the host steps of the peer node, and check the address from it and from the other nodes.

## Sign in for the first time

1. Open the operator portal at `https://operator.<domain>/`.
2. Sign in with the operator account. Its password is in `operator-login/` of the state folder.
3. Create the first zone. [The zone manual](Zone_Operator_Manual.md) describes the zone tasks.

<a href="img/operator-home.png"><img src="img/operator-home.png" alt="The start page of the operator portal with the cluster use and the links to the tools" width="100%"></a>

## Verify the installation

| Check | Command |
|---|---|
| The server uses etcd | `kubectl get node <server>` shows the role `etcd`. The verify step of the driver also saves a snapshot. |
| The nodes are Ready | `kubectl get nodes` |
| The run is complete | `k3s/deploy-k3s status` names the applied record and revision. |
| The logins of a zone work | `python3 k3s/tools/verify-lab-logins.py <zone>` |

[The operations manual](Cluster_Operations.md) describes upgrades, settings, backups and restore.
[The migration manual](Cluster_Migration.md) describes the move of an earlier installation into a site.
