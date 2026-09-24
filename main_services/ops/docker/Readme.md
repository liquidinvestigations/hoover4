# Docker build contexts and compose files

Everything `deploy.py` feeds to compose.

| path | holds |
|---|---|
| `docker-compose.yaml` | the always-on core of the main stack |
| `compose/` | optional overlays, selected by a configuration flag or a condition in `deploy.py` |
| `cassandra-entrypoint.sh` | `temporal-cassandra`'s entrypoint, which writes `file_cache_size_in_mb` and then starts the image's own entrypoint |
| `garage/` | the object store's configuration and its layout bootstrap |
| `pdf-to-html/` | the conversion service image |
| `serena/` | the symbol-server image and its entrypoint |
| `temporal-dynamicconfig/` | workflow-server tuning, bind-mounted as a **directory**. `deploy.py` renders `generated.yaml` there, and the server reads that file |
| `clickhouse-server-config-override.xml` | the column store's settings overlay |
| `extra/` | the vendor's original config, kept for diffing against the override |
| `vllm_command.sh` | the local model server's argument assembly |

`temporal-dynamicconfig/` is mounted as a directory rather than as a single file on purpose:
a single-file bind mount follows the inode it was created with, so an editor that writes and
renames leaves the container silently reading the old contents.

`temporal-dynamicconfig/generated.yaml` holds every key of the tracked `docker.yaml` and the
persistence rate limits of `hoover4.ini`, because the server reads one dynamic config file.
Add a tuning key to `docker.yaml`, never to `generated.yaml`.

`compose/research-agents.yaml` holds the two research agents, and `deploy.py` selects it only
when an LLM provider is enabled. `compose/research-agents-internet.yaml` adds the internet
MCP servers to the full research agent's dependencies. It is selected when the agents and
`internet_tools_enabled` are both on.

Each compose file defines an `x-logging` field and gives it to every service it defines,
because a YAML anchor does not cross files. A new service needs `logging: *logging`.
`scripts/deploy.py_tests/` fails when a service has no such line.

`hoover4-worker` mounts `website/backend/src` and `hoover4-website` mounts
`main_services/processing/tasks`, both read-only under `/mirror/`. The unit tests of the
Temporal readiness gate read the other runtime's copy of its constants there.

`deploy.py` renders the generated `.env` files these read; **never hand-edit a generated
file**. The next deploy overwrites it, and until then the change looks like it worked.

Relative paths resolve against the **project directory** (the first compose file's
directory) not against the file that declares them, so an overlay in `compose/` points
somewhere else from where it reads as pointing. `./deploy --print-command` and
`docker compose … config` render the absolutes.

A duplicate mapping key is accepted by one compose implementation and rejected outright by
the other, so `deploy.py` preflights every file it is about to use with a loader that
rejects duplicates. The usual way to create one is an edit that removes a name line and
leaves the indented line under it attached to whatever came before.
