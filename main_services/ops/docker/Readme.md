# Docker build contexts and compose files

Everything `deploy.py` feeds to compose.

| path | holds |
|---|---|
| `docker-compose.yaml` | the always-on core of the main stack |
| `compose/` | one optional overlay per service, selected by a configuration flag |
| `garage/` | the object store's configuration and its layout bootstrap |
| `pdf-to-html/` | the conversion service image |
| `serena/` | the symbol-server image and its entrypoint |
| `temporal-dynamicconfig/` | workflow-server tuning, bind-mounted as a **directory** |
| `clickhouse-server-config-override.xml` | the column store's settings overlay |
| `extra/` | the vendor's original config, kept for diffing against the override |
| `vllm_command.sh` | the local model server's argument assembly |

`temporal-dynamicconfig/` is mounted as a directory rather than as a single file on purpose:
a single-file bind mount follows the inode it was created with, so an editor that writes and
renames leaves the container silently reading the old contents.

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
