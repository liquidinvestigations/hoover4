# Install a cluster site

This manual installs Hoover and openDesk on a k3s cluster with `k3s/deploy-k3s`.
[The cluster deployment reference](../../k3s/Readme.md) describes each command and file in detail.
Keep host names, addresses and credentials in the private site folder and in the private infrastructure inventory.

## Contents

- [Prepare the operator host](#prepare-the-operator-host)
- [Write the site file](#write-the-site-file)
- [Choose the node roles](#choose-the-node-roles)
- [Give the driver root access on each node](#give-the-driver-root-access-on-each-node)
- [Install the site](#install-the-site)
- [Add a GPU node](#add-a-gpu-node)
- [Sign in for the first time](#sign-in-for-the-first-time)
- [Verify the installation](#verify-the-installation)

## Prepare the operator host

The operator host runs the driver and the operator runner. It is usually the control-plane node.

1. Install Python 3, `git`, `ssh` and `kubectl`.
2. Install `podman` or `docker`. The tools step builds the Caddy binary of the HTTPS frontend in a container.
   A host without a container engine needs a Caddy binary of another host in `k3s/private/bin/caddy`.
3. Clone the repository. The folder `k3s/private/` holds the site file, the secrets and the operator state. Git ignores it.
4. Give the operator user SSH access with a key to every node.

## Write the site file

The site file is `k3s/private/hoover4-site.ini`. It is the only file that holds host paths.
[The single-node and remote examples](../../k3s/tests/fixtures) show the format.

| Section | Content |
|---|---|
| `[site]` | The site name, the domain suffix of the zones, the control-plane node and the operator user. |
| `[node.<name>]` | The roles of the node, its SSH address, its VPN address and interface, its storage tiers and its volume group. |
| `[gpu_pool]` | The GPU nodes or the address of an external GPU pool, and the key file of the pool. |
| `[backup]` | The backup node and the backup folder on that node. |
| `[hoover.<name>]` | One Hoover installation: its zone, its home node, its store layout and its storage identity. |

Check the file before each change:

```sh
python3 k3s/config.py check k3s/private/hoover4-site.ini
```

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

## Give the driver root access on each node

The driver runs two root scripts on each node: `root-install.py` prepares the host, and `root-install-k3s.py` installs k3s.
The scripts accept names only: the bundle name, the node name, the operator user and a step.
They read the host paths from `hosts.json` of the bundle `~/k3s-install/<bundle>/`, which the driver writes from the site file.
A script refuses an absolute path, `..`, and a symbolic link below the home folder of the operator user.

The driver selects the first root route that works on a node.

| Route | Condition |
|---|---|
| `sudo` | The operator user runs `sudo -n` for every command. |
| `scoped` | The bootstrap rule of the node lets the operator user run the installed root scripts with `sudo -n`. |
| `cluster` | The node is Ready in the cluster. A privileged pod starts the root command as a unit of the host. |

A new node without `sudo -n` has no route. The driver writes the bundle to the node and waits. Do these steps on that node:

1. Read `~/k3s-install/<bundle>/bootstrap.sh`. It installs the root scripts into `/usr/local/libexec/hoover4` and writes a sudo rule for these scripts only.
2. Compare the SHA-256 values in the script with the files of the bundle.
3. Run it once as root: `sudo sh ~/k3s-install/<bundle>/bootstrap.sh`.
4. On the operator host, run the command that the driver printed: `k3s/deploy-k3s up --resume <record>`.

## Install the site

1. Show the configuration and the steps. The command changes nothing.

   ```sh
   k3s/deploy-k3s render --target all
   k3s/deploy-k3s check --target all
   ```

2. Install the site from a commit:

   ```sh
   k3s/deploy-k3s up --target all --revision <commit>
   ```

   The driver exports the tree of the commit into `k3s/private/build/<commit>/` and runs every step from that tree.
   It prepares the hosts, installs k3s, the cluster services, the registry, the images, the ingress, the HTTPS frontend, monitoring, the operator portal and runner, the GPU services, each zone and the call services.
3. When a step fails, read its error, correct the cause, and continue with the same inputs:

   ```sh
   k3s/deploy-k3s up --resume <record>
   ```

   A resume refuses a changed site file, a changed tree and another cluster. Start a new run after such a change.
4. A complete run writes `deploy/applied.json` in the operator state. `k3s/deploy-k3s status` shows the applied revision.

## Add a GPU node

A GPU node keeps its existing VPN interface. Name that interface in the site file.

1. Add `[node.<name>]` with the role `gpu`, the architecture `arm64` or `amd64`, the VPN address and `vpn_interface`.
2. Install the NVIDIA driver and the NVIDIA container toolkit on the node. The root script refuses a GPU node without them.
3. Run `k3s/deploy-k3s up --target <name>`. The driver writes the bundle and waits when the node has no root route.
4. Do the bootstrap steps of [the root access section](#give-the-driver-root-access-on-each-node) on the node, then resume the record.
5. Stop the Compose GPU services of the node only after the GPU pool of the cluster answers authenticated requests.

## Sign in for the first time

1. Open the operator portal at `https://operator.<suffix>/`.
2. Sign in with the operator account. Its password is in `k3s/private/operator-login/`.
3. Create the first zone. [The zone manual](Zone_Operator_Manual.md) describes the zone tasks.

## Verify the installation

| Check | Command |
|---|---|
| The server uses etcd | `kubectl get node <server>` shows the role `etcd`. The verify step of the driver also saves a snapshot. |
| The nodes are Ready | `kubectl get nodes` |
| The run is complete | `k3s/deploy-k3s status` names the applied record and revision. |
| The logins of a zone work | `python3 k3s/tools/verify-lab-logins.py <zone>` |

[The operations manual](Cluster_Operations.md) describes upgrades, settings, backups and restore.
[The migration manual](Cluster_Migration.md) describes the move of an earlier installation into a site.
