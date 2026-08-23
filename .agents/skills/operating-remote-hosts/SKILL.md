---
name: operating-remote-hosts
description: Works on the two machines outside the development workstation. The demo box that serves the public deployment, and the GPU box that runs the standalone accelerated tier. Use when asked to "check the demo", "look at the server", "ssh in", "deploy to the demo box", "what's happening on the GPU box", "read the logs on the remote host", or when a symptom is reported from a deployment that is not the local one. Covers what differs there and therefore what transfers from a local success and what does not, the standing rule that these hosts are read first and changed only on purpose, and where the access details live, which is never in this repository.
allowed-tools: Bash, Read, Grep, Glob
---

# Operating the remote hosts

Two machines outside the development workstation run this system: **the demo box**, which
serves the public deployment, and **the GPU box**, which runs the standalone accelerated
tier.

## Where the access details live

**Not here, and not in any tracked file.** Host names, addresses, users, ports, credentials
and the shape of the network in front of the demo box live in `INFRASTRUCTURE_INVENTORY.md`
at the repository root, which is gitignored and is filled in from an interview with the
operator. Read that file to find out how to reach a host.

Nothing you learn there is copied into this repository, into a script, into a commit message
or into a log line. This skill is published; that file is not.

## Before you touch either one

**Read first.** Logs, container state, database queries, rendered compose configuration.
Diagnosis is the normal reason to be on a remote host, and it needs nothing but reads.

Then, in order:

- **Do not redeploy** unless redeploying is the explicit task. A deploy restarts containers,
  and any verification in flight dies with them.
- **Do not edit code on the box.** Changes made in place are invisible to git and to every
  other host, and the next deploy loses them.
- **Never run an unscoped prune or reset** on a host whose container runtime is shared with
  something else. Scope every cleanup to this project.
- **Capture what no export reproduces before any reset.** Collection display names and
  visibility flags are held only in the database; a reset plus a re-ingest recreates
  collections with bare names.

## The demo box: what differs, and therefore what does not transfer

- **It runs a different container engine from the workstation**, and that difference is the
  source of most surprises. A compose file the local engine accepts can be rejected outright
  there (a duplicate mapping key is the recurring example), and some flags the local
  workflow relies on do not exist. Validate a compose change against a strict parser before
  assuming a local success transfers.
- **It shares its container runtime with an unrelated stack.** Every cleanup must be scoped
  to this project's containers and volumes; the project-scoped reset is safe for exactly that
  reason.
- **The website is not reachable on the host's own loopback.** Something in front of it
  terminates traffic, and the site binds accordingly, so a connection refused on the box
  itself is the expected reading rather than a fault. The details are in the inventory file.
- **The test corpus is a bind mount**, so no reset touches it, but its fixtures sit one
  level deeper than the end-to-end verification's defaults expect, which makes the
  ingest-root overrides mandatory there.
- **Release mode is on**, so a reset that drops the build-target volume costs a cold release
  build on the next deploy. Budget for that before resetting anything people are looking at.
- **The worker fleet is sized narrower than the defaults** because the cores are shared.
  Oversubscription is expensive here in a specific way: a heartbeat deadline is also a slot
  lease, so a machine pushed past its capacity holds slots for activities nobody is waiting
  on and multiplies its own timeouts: `tuning-the-pipeline`.

## The GPU box: a target for experiments, and its state is in flux

Treat its configuration as unsettled. It is where accelerated serving is tried, and what it
is running today is a measurement, not a documented invariant. Ask it what it is running
rather than assuming.

- **Its architecture and device generation differ from the workstation's.** Most base images
  have a matching manifest, so architecture is rarely the real blocker.
- **The one genuinely architecture-bound dependency is the tensor library.** The pinned older
  CUDA build has no wheel for that architecture and carries no kernels for that device
  generation in any case; the newer index does, and it is the vision companion package,
  not the tensor library itself, that selects the compatible version. Dropping the
  per-package pins around it is not an architecture concession: they conflict with the newer
  build on the workstation's architecture as well. **When porting such a bump back, test it
  first and alone**. It is the only change that can regress a working host.
- **Three failures there look architecture-specific and are not.** A network pre-created
  without the compose project's labels is adopted by one engine and refused by the other,
  failing the whole bring-up. A service directory that does not exist takes the *entire*
  deploy down, because everything is built before anything starts. And a cache volume
  mounted at another framework's cache path overlays one model tree on another.
- **Throughput is bandwidth-bound rather than compute-bound at small batch sizes**, so
  batching several concurrent streams is nearly free.

## What to check before believing a remote symptom

The same rule as anywhere: reproduce from **inside** the container that has the problem, not
from the host and not from your workstation. `debugging-the-stack` applies unchanged. The
mechanisms do not become different because the machine is remote.

## References

- `reference/remote-work.md`, the read-only diagnosis pass, and what to capture before a
  reset.
