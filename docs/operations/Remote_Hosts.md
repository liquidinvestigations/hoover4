# Remote hosts

Two machines outside the development workstation run hoover4: **the demo box**, which serves
the public deployment, and **the GPU box**, which runs the standalone accelerated tier. This
page describes how working on them differs from working locally.

**It deliberately names neither.** Host names, addresses, users, ports, credentials, and the
shape of the network in front of the demo box live in `INFRASTRUCTURE_INVENTORY.md` at the
repository root — a local, gitignored file filled in from an interview with the operator.
This tree is public; nothing from that file is copied into it, into a script, into a commit
message, or into a log.

## Contents

- [What may be done on a remote host](#what-may-be-done-on-a-remote-host)
- [The demo box](#the-demo-box)
- [The GPU box](#the-gpu-box)
- [What transfers from a local success](#what-transfers-from-a-local-success)

## What may be done on a remote host

The standing rule, and the reason it exists: these hosts carry state that no export
reproduces.

- **Read.** Logs, container state, database queries, rendered compose configuration.
  Diagnosis is the normal reason to be there, and it needs nothing but reads.
- **Do not redeploy** unless that is the explicit task. A deploy restarts containers, and any
  verification in flight dies with them.
- **Do not edit code on the box.** Changes made in place are invisible to git and to every
  other host, and the next deploy loses them.
- **Never run an unscoped prune or reset** on a host that shares its container runtime with
  something else. Every cleanup is scoped to this compose project; the project-scoped reset
  is safe for exactly that reason.
- **Capture what no export reproduces, before any reset.** Collection display names and
  visibility flags live only in the database — a reset plus a re-ingest gives back the
  documents and not those.

## The demo box

The public deployment.

- **It runs a different container engine from the workstation**, and that difference is the
  source of most surprises. A compose file the local engine accepts can be rejected outright
  there — a duplicate mapping key is the recurring example — and some flags the local
  workflow relies on do not exist. Validate a compose change against a strict parser before
  assuming a local success transfers.
- **Another product's stack shares the container daemon.** An unscoped prune destroys it.
- **The website is not reachable on the host's own loopback.** Something in front of it
  terminates traffic and the site binds accordingly, so a connection refused on the box
  itself is the expected reading rather than a fault.
- **The test corpus is a bind mount**, so no reset touches it. Its fixtures sit one level
  deeper than `main_services/verify-stack.sh` expects by default, which makes the ingest-root
  environment overrides mandatory on this host.
- **Release mode is on.** A reset drops the website's build-target volume, so the next deploy
  pays a cold release build. Budget for it before resetting anything people are looking at.
- **The worker fleet is sized narrower than the defaults**, because the cores are shared.
  Oversubscription is expensive here in a specific way: a heartbeat deadline is also a slot
  lease, so a machine pushed past its capacity holds slots for activities nobody is waiting on
  and multiplies its own timeouts.

## The GPU box

A target for experiments, running the standalone accelerated tier. **Its configuration is in
flux**: what it serves today is a measurement rather than a documented invariant, so ask the
machine what it is running instead of assuming.

- **Its architecture and device generation differ from the workstation's.** Every base image
  the tier needs has a matching manifest, so architecture is rarely the real blocker.
- **The one genuinely architecture-bound dependency is the tensor library.** The older pinned
  CUDA build has no wheel for that architecture and carries no kernels for that device
  generation in any case; the newer index does, and it is the vision companion package — not
  the tensor library itself — that selects the compatible version. Dropping the per-package
  pins around it is not an architecture concession: they conflict with the newer build on the
  workstation's architecture as well. When porting such a bump back, **test it first and
  alone** — it is the only change that can regress a working host.
- **Three failures there look architecture-specific and are not.** A network pre-created
  without the compose project's labels is adopted by one engine and refused by the other,
  which fails the whole bring-up. A service directory that does not exist takes the *entire*
  deploy down, because everything is built before anything starts. And a cache volume mounted
  at another framework's cache path overlays one model tree on another.
- **Throughput is bandwidth-bound rather than compute-bound at small batch sizes**: per-stream
  decode is flat out to sixteen concurrent streams, so batching is nearly free.

## What transfers from a local success

| local result | transfers? |
|---|---|
| the code compiles and the tests pass | yes |
| a compose file parses and brings the stack up | **no** — a stricter engine rejects things the local one accepts |
| a cleanup command is safe | **no** — a shared runtime turns an unscoped command into someone else's outage |
| a path exists at the depth a script expects | **no** — corpus layout differs, which is what the ingest-root overrides are for |
| a build takes N minutes | **no** — release mode and shared cores change it by a lot |

Whether local changes made on the GPU box during bring-up have been carried back into this
repository is **not recorded anywhere**. Confirm against the tree before assuming the tier
deploys from a clean checkout there.
