# What each deploy flag actually does

## The two sides

`./deploy` acts on the **main stack**: the pipeline, the datastores, the website, the MCP
servers and the CPU model twins. `./deploy --ai-services` acts on the **GPU tier**, which is
a separate compose project on its own private network with no dependency on the main stack.
They are never brought up by one command.

## Order of operations in a normal run

1. `[storage] volumes_path` and one folder in it for each volume of the side are created,
   then the preflight checks run against the configuration and the runtime.
2. The generated `.env` beside the compose files is rendered from `hoover4.ini`, and the run
   prints whether it changed.
3. The container network is created or repaired **before** compose runs, with its upstream
   resolvers pinned. Without that step the network's DNS forwards to the host's local
   resolver stub and every external lookup from inside a container wedges, while
   container-name resolution keeps working, so the stack looks healthy and only
   internet-facing work hangs.
4. Each volume folder gets the owner its service writes as, in a one-shot container of the
   service's image. Compose then brings the selected side up, with `--build --force-recreate` when `--build` is
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

Stops and removes the selected side's containers. The volume folders survive. It runs with
any value of `[storage] volumes_path` and of the CPU keys.

## `--reset`

`down`, then empties the side's volume folders under `[storage] volumes_path`, in a one-shot
container, because the files belong to the uids of the services. It never removes a folder,
and it touches no path outside `<volumes_path>/<volume name>`. The `VOLUMES` table in
`deploy.py` gives each folder its reset class.

Preserved across a reset:

- **the symbol-navigation server and its state folder**, which are a separate project;
- **the model-cache folders**, unless `--reset-caches` is also given.

Lost across a reset, and worth capturing first: anything held only in the datastores that no
export reproduces (collection display names and visibility flags among them). A reset plus a
re-ingest recreates collections with bare names.

A reset also empties the website's build-target folder, so the next deploy pays a cold release
build wherever release mode is on.

## `--reset-temporal`

Empties only the folders of the workflow history and visibility stores, keeping the corpus in ClickHouse,
Manticore, Garage and Redis. What is lost is workflow history, which retention already caps
at a day. Running ingests do not survive. Their workflows are gone, and the scan stage
re-reads the dataset from disk on the next run. This is the flag that has to be used to
change the history-shard count.

## `--print-env` and `--print-command`

Render and show, run nothing. `--print-env` prints each refusal of a start, such as an
empty `[storage] volumes_path`, as a `warning:` line and still prints the environment. These
report what the container will get for a value at
configuration time, and `docker exec <c> env` reports what it has at runtime. Trust neither the ini file nor the compose file on its own.
