# Containers and scripts

Nothing is built or run on the host. There is no host Rust toolchain and no host Python; every
build, test, script and server process runs in a container built from this repository.

## The six scripts

| Script | What it does |
|---|---|
| `build-dev.sh [--force]` | Builds the development image from `Dockerfile.devel`. `--force` rebuilds from scratch, ignoring the layer cache and re-pulling the base image. |
| `build-rel.sh [--force]` | Builds the release image from `Dockerfile.release`. |
| `shell.sh [command…]` | Interactive shell in a throwaway dev container. With arguments, runs them instead: `./shell.sh cargo test`. A terminal is allocated only when there is one on both ends, so redirected output keeps stdout and stderr apart, `./shell.sh python3 tests/conformance/extract_presidio.py > presidio.jsonl` writes the cases and leaves the progress line on the terminal. |
| `run-server.sh [--dev]` | Runs the server detached on `127.0.0.1:19705`, replacing any container already holding the name. `--dev` runs from the dev image against the working tree. |

`run-server.sh` resolves the image tag at `docker run` time, so starting the server while a build is
still exporting silently runs the *previous* image. `/health` is what tells them apart (`rules` and
`rule_set_version` are both in it), and comparing the container's image id against `docker images`
is what proves which one is serving. A stale image reporting two compiled rules out of forty-one
looks exactly like a working service until something asks it for an entity type it no longer has.

| `test.sh [filter…]` | The full battery in the dev container, building the image first if it is missing. Arguments pass through to `cargo test`. |
| `test-long.sh [origin]` | The upstream conformance run in the dev container: the checked-in cases taken from the reference projects our rules were ported from, scored as recall, precision and coverage. An argument restricts the run to one origin, named by its case file's stem, `./test-long.sh stdnum`. |

`test.sh` and `test-long.sh` are separate entry points and neither runs the other. The battery is
held to two or three minutes because it runs on every rule change; the conformance run has a budget
of fifteen to twenty minutes and samples each scheme deterministically rather than exceeding it.

`common.sh` holds the image names, the published address and the shared helpers. It is sourced, not
executed.

If something is needed that these do not cover, extend them or the Dockerfiles. A host-side install
is not a shortcut. It is a machine that works and a repository that does not.

## The development image

`Dockerfile.devel` is the toolchain, bind-mounted on the working tree at `/work`. It holds no state
of its own: the cargo registry cache, the build directory and the shell history all live under the
mount, in `.container/` and `target/`, so deleting the container costs nothing and the tree stays
the single source of truth.

Under rootless podman, container root maps to the invoking user, so files the container creates in
the mount are owned by that user on the host, no ownership repair, no `--user` juggling.

The directories that hold cargo's state live inside the mount, which does not exist until the
container starts, so the entrypoint creates them before handing over.

## The release image

`Dockerfile.release` builds in one stage and ships in another. What lands in the final image is the
optimised binary, `vendored/data` (the reference data the scanner loads at startup), and the
upstream licence notices, which the licences require to travel with the data. No toolchain, no
sources, no bind mount, and no `vendored/reference`, which is development material.

It runs as an unprivileged user, listens on `0.0.0.0:19705` inside the container, and is configured
by two environment variables: `RES_BIND` for the listen address and `RES_VENDORED_DIR` for the data
directory. `RES_LOG` takes a tracing filter.

`.dockerignore` keeps the build directory, the scratch tree and `vendored/reference` out of the
build context. The context is sent in full, and without it that is hundreds of megabytes per
build.

## Ports

The server listens on all interfaces inside its container; only the loopback publish on the host
makes it reachable, at `127.0.0.1:19705`. Nothing here is authenticated, so that publish is the
entire access control story. Do not widen it without adding one.
