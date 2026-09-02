# Nomad, Consul and Vault, outside the compose stack

hoover4 also has a Nomad, Consul and Vault cluster, separate from the podman compose stack
that `./deploy` manages. This page describes what that cluster is for, where it lives, and
what is known about GPU support on each architecture that runs hoover4 today.

## Contents

- [What the local cluster is for](#what-the-local-cluster-is-for)
- [How it differs from the compose stack](#how-it-differs-from-the-compose-stack)
- [GPU support by architecture](#gpu-support-by-architecture)
- [What blocks a container job today](#what-blocks-a-container-job-today)
- [The image registry](#the-image-registry)

## What the local cluster is for

hoover4 has no Nomad job today. The compose stack, started by `./deploy`, is the only way
this system runs in development and on the demo box. The local cluster exists to test Nomad
itself, and to test GPU device support under Nomad, before hoover4 gains its own jobs.

The checkout, the cluster's data directories and its configuration live under
`external/liquid/`, alongside the three cloned repositories that a Nomad deployment of
hoover4 would use: `liquidinvestigations/node`, which renders and deploys Nomad job files,
`liquidinvestigations/core`, the identity provider, and `liquidinvestigations/cluster`, which
this page describes. `external/` is outside the tracked tree. `INFRASTRUCTURE_INVENTORY.md`
at the repository root, also outside the tracked tree, carries the addresses and the commands
that bring the local cluster up and down.

## How it differs from the compose stack

The compose stack runs as one user's own rootless podman containers. The cluster container
runs as a separate, privileged instance of the same container engine, reached through
`sudo docker`, so its containers and networks are not the ones `docker ps` shows by default.
It shares the host's network stack, rather than the compose stack's own private networks.

Nomad, inside that cluster container, does not talk to the rootless podman instance the
compose stack uses. It talks to a second, privileged instance of the engine over its own
API, mounted into the cluster container as `/var/run/docker.sock`. A container that Nomad
starts is invisible to `docker ps` run as the ordinary user, and visible to `sudo docker ps`.

## GPU support by architecture

The workstation and the GPU box differ in more than instruction set.

- **The workstation** carries an NVIDIA GeForce RTX 3090 and the NVIDIA Container Toolkit.
  Nomad's own device plugin for NVIDIA GPUs detects the card, reports its memory, clocks and
  driver version, and lets a job request it through a `device` stanza. A process inside a
  Nomad allocation on this workstation has not been shown to see the card, for the reason
  below.
- **The GPU box** is aarch64. It has no Nomad installed. Its container engine is real Docker,
  not podman, and the NVIDIA Container Toolkit works there: a container started with
  `docker run --gpus all` sees the card. The base images hoover4's own services build from,
  such as ClickHouse, Manticore, PostgreSQL and Python, already publish an aarch64 build, so
  those layers need no separate work for that architecture. hoover4's own seventeen built
  images, which today exist only as an x86 local build cache, are the part that would still
  need a multi-architecture build before they could run there.

## What blocks a container job today

Two separate faults, found on the workstation, keep a Nomad job from proving it holds the
GPU there.

**The docker driver cannot start any container.** Nomad's docker driver asks the container
engine to set a per-container memory-swappiness value. On a host whose container engine is
podman running under a `cgroup v2`-only kernel, that request fails before the container
starts, because `cgroup v2` carries no per-container swappiness setting at all, of any value
other than "leave it alone". This is a property of `cgroup v2` and podman's runtime, not of
this one workstation, so it is expected to affect any modern host running the same
combination.

**A process inside a Nomad allocation cannot open the GPU, under the `exec` or `raw_exec`
drivers.** The device nodes and the driver version file are present and readable inside the
allocation, so the fault is not a missing mount. The most likely cause is that Nomad puts
each allocation in its own process-id namespace, and NVIDIA's driver library needs a
process-id namespace it shares with the host to open the card. This is a plausible
explanation from the symptom, not a confirmed one, because the one Nomad driver that lets a
job ask for the host's process-id namespace is the docker driver, and that driver is blocked
by the fault above on this host.

**A per-job override does not exist on this Nomad release.** Nomad's docker task
configuration has no `memory_swappiness` argument in version 1.5.6. A job that sets one,
whether to `-1` or to a value in the documented range, fails validation before the task
starts. The error is `Invalid label: No argument or block type is named "memory_swappiness"`.
A job that omits the setting entirely reaches the same `crun: cannot set memory swappiness
with cgroupv2` fault as before. Nomad's docker driver sets an implicit swappiness value on
every container it starts, and this release gives no job-level way to turn that off. Fixing
this needs a Nomad release whose docker driver accepts the setting, or one that does not send
it under `cgroup v2` at all. No such release has been confirmed yet.

## The image registry

A plain `registry:2` container, `liquid-registry`, stands beside the cluster container. A
build on this workstation pushes an image there. A Nomad docker job later pulls it back.
The registry is not part of `cluster.py`. That script's `runserver` command and
its matching `[program:...]` blocks in `templates/supervisord.conf` cover Consul, Vault and
Nomad, each installed by downloading one HashiCorp release binary. A registry has no matching single-binary release to install the same way. It runs instead as
a second container under the same privileged engine as the cluster, and shares its network.

Both container engines on this workstation need to trust the registry before a push or a
pull succeeds, because it answers over plain HTTP. That is the rootless one the compose
stack uses, and the privileged one the cluster uses. Neither carried a per-user
`registries.conf` override before this was added, so both fell back to one shared system
file. A per-user override in each engine's own home directory is what took effect. The
address itself is not repeated here, because it identifies a real host. It lives in the
gitignored `INFRASTRUCTURE_INVENTORY.md`, and in `hoover4.ini`'s `[cluster]` section.
