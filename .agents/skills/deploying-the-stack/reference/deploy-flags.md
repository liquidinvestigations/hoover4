# What each deploy flag actually does

## The two sides

`./deploy` acts on the **main stack**: the pipeline, the datastores, the website, the MCP
servers and the CPU model twins. `./deploy --ai-services` acts on the **GPU tier**, which is
a separate compose project on its own private network with no dependency on the main stack.
They are never brought up by one command.

## Order of operations in a normal run

1. Preflight checks against the configuration and the runtime.
2. The generated `.env` beside the compose files is rendered from `hoover4.ini`, and the run
   prints whether it changed.
3. The container network is created or repaired **before** compose runs, with its upstream
   resolvers pinned. Without that step the network's DNS forwards to the host's local
   resolver stub and every external lookup from inside a container wedges, while
   container-name resolution keeps working — so the stack looks healthy and only
   internet-facing work hangs.
4. Compose brings the selected side up, with `--build --force-recreate` when `--build` is
   given.
5. On the main side, the symbol-navigation server comes up last, **as its own compose
   project**, so that nothing a `down` or a `--reset` selects can take out the connection
   the agent is working through.

## `--build`

Builds images first, then recreates. Needed after any change to a `Dockerfile`, a build
context, an ignore file, or a file the image copies in rather than mounts.

**It does not combine with `--reset`.** The reset path returns before the build path is
reached, so `--reset --build` resets and stops. Run them as two commands.

## `--down`

Stops and removes the selected side's containers. Volumes survive.

## `--reset`

`down`, then removes this compose project's data volumes. It is scoped by project name on
purpose: an unscoped prune on a host that shares its container runtime with something else
destroys the other stack.

Preserved across a reset:

- **the symbol-navigation server and its state volume**, which are a separate project;
- **the model-cache volumes**, unless `--reset-caches` is also given.

Lost across a reset, and worth capturing first: anything held only in the datastores that no
export reproduces — collection display names and visibility flags among them. A reset plus a
re-ingest recreates collections with bare names.

A reset also drops the website's build-target volume, so the next deploy pays a cold release
build wherever release mode is on.

## `--reset-temporal`

Drops only the workflow history and visibility stores, keeping the corpus in ClickHouse,
Manticore, Garage and Redis. What is lost is workflow history, which retention already caps
at a day. Running ingests do not survive — their workflows are gone, and the scan stage
re-reads the dataset from disk on the next run. This is the flag that has to be used to
change the history-shard count.

## `--print-env` and `--print-command`

Render and show, run nothing. These are the honest answer to "is the container getting the
value I think it is" at configuration time — and `docker exec <c> env` is the honest answer
at runtime. Trust neither the ini file nor the compose file on its own.
