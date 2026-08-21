# Deploying

`./deploy` at the repository root is the only entry point. It renders configuration, repairs
the container network, and then drives the container runtime.

## Contents

- [The flags](#the-flags)
- [Configuration flows one way](#configuration-flows-one-way)
- [Secrets](#secrets)
- [Before you deploy anything](#before-you-deploy-anything)
- [What a deploy does not do](#what-a-deploy-does-not-do)
- [Reading a build](#reading-a-build)
- [Resetting](#resetting)
- [After a deploy](#after-a-deploy)

## The flags

```
./deploy                    # main stack up
./deploy --build            # build images first, then up
./deploy --ai-services      # the standalone accelerated tier instead
./deploy --down             # stop the selected side
./deploy --reset            # down, then remove this project's data volumes
./deploy --reset-caches     # with --reset: also wipe the model caches
./deploy --reset-temporal   # drop the workflow history and visibility stores only
./deploy --print-env        # render the environment files and show them, start nothing
./deploy --print-command    # show the compose invocation, run nothing
```

The two sides are never brought up by one command. The main stack is the pipeline, the
datastores, the website, the MCP servers and the CPU model twins; the accelerated tier is a
separate compose project on its own private network.

The order inside a normal run is worth knowing, because two of the steps only exist because
of a failure they prevent:

1. Preflight the configuration and the runtime.
2. Render the generated `.env` beside the compose files, and print whether it changed.
3. **Create or repair the container network, with its upstream resolvers pinned**, before
   compose runs. Without that the network's DNS forwards to the host's local resolver stub
   and every external lookup from inside a container wedges — while container-name
   resolution keeps working, so the stack looks healthy and only internet-facing work hangs.
4. Bring the selected side up.
5. On the main side, bring the symbol-navigation server up last, **as its own compose
   project**, so nothing a `down` or a `--reset` selects can take out the connection an agent
   is working through.

## Configuration flows one way

`hoover4.ini` at the repository root is the single source. It is gitignored; the template
beside it is `hoover4.ini.example`. `deploy.py` renders it into the generated `.env` files
next to the compose files.

**Never hand-edit a generated `.env`.** The next deploy overwrites it, and until then the
change looks like it worked.

- **Ports are configuration keys, not literals.** Read the key; never hard-code the number.
  The website's port is the one exception, because a person types it.
- **A key that is rendered and read by nothing is a lie.** When adding one, grep for its
  consumer in the same change, or record it as not-yet-implemented.
  [Configuration reference](Configuration_Reference.md) is the list, with the consumer of
  each.

## Secrets

Secrets are **files outside the repository**, bind-mounted read-only. No key value goes into
a tracked file, a script, or a log line — the configuration names the path, and the container
reads it.

Host addresses, users and credentials for a particular deployment live in
`INFRASTRUCTURE_INVENTORY.md` at the repository root, which is local and gitignored.

## Before you deploy anything

**Check what is in flight.** A deploy restarts containers, and the end-to-end verification
runs for tens of minutes inside the worker — restarting it kills the run outright.

```
docker ps --format '{{.Names}}\t{{.Status}}'
uptime
```

Batch your fixes so one restart serves several. On a shared machine, check the owner column
of the process list before concluding that the load is yours.

## What a deploy does not do

**Bringing containers up is not a deployment; it is a no-op with opinions.** It reuses
existing images and containers, so a broken build context, a changed ignore file and new
environment all stay invisible until something forces a rebuild or a recreate. After changing
anything that feeds a build, run `--build`.

**`--reset --build` does not rebuild.** The reset path returns before the build path is
reached. It is two commands: `./deploy --reset`, then `./deploy --build`.

**Restarting one container fails under a rootless runtime when a sibling has legitimately
exited.** A `restart` refuses because an initialisation container is `Exited (0)`, which is
its correct final state. Stop and then start works.

**Relative paths in a compose file resolve against the project directory** — the first
compose file's directory — not against the file that declares them. An overlay in a
subdirectory therefore points somewhere else entirely from where it reads as pointing.
`./deploy --print-command`, and `docker compose … config`, render the absolutes.

## Reading a build

Never judge a build from its last fifty lines: the interesting failure is usually thousands
of lines above the end, and reading only the tail has cost a full rebuild cycle to recover.
Redirect the whole run to a file and grep it —
`.agents/skills/deploying-the-stack/scripts/deploy-logged.sh` does exactly that and prints
the exit status on its own line.

**Build parallelism is bounded by one build argument**, which feeds every backend's own
spelling of it: the make, cmake, cargo and thread-cap variables are set as a group. Missing
one of them loses the bound and takes the machine down with it.

## Resetting

A reset is **scoped to this compose project** by name. That is not politeness: on a host whose
container runtime is shared with something else, an unscoped prune destroys the other stack.

Preserved across a reset: the symbol-navigation server and its state volume, because they are
a separate project; and the model-cache volumes, unless the cache flag is also given.

Lost across a reset, and worth capturing first: anything held only in the datastores that no
export reproduces. Collection display names and visibility flags are the recurring example —
a reset plus a re-ingest recreates collections with bare names.

A reset also drops the website's build-target volume, so the next deploy pays a cold release
build wherever release mode is on.

## After a deploy

Confirm from **inside** the network. A service being up on the host proves nothing about
whether the container that needs it can reach it: containers on separate networks cannot use
each other's names, and a rootless container cannot reach its host's LAN address at all — it
hangs rather than refuses.

```
docker exec hoover4-worker curl -sS --max-time 5 http://<service>:<port>/health
```

Then a page load. If something is wrong, [Troubleshooting](Troubleshooting.md) routes by
symptom.
