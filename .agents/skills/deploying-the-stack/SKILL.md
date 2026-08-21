---
name: deploying-the-stack
description: Brings the stack up, rebuilds it, resets it, and waits on the long jobs that result. Use when asked to "deploy", "redeploy", "rebuild", "bring it up", "restart the stack", "reset", "wipe the data", "apply the config change", or when a change to a Dockerfile, a compose file or the configuration has to take effect. Covers `./deploy` and every flag, the configuration flow from the one ini file into the generated environment files, why bringing containers up is not a deployment, the flag combination that silently does not rebuild, restarting a single container under a rootless runtime, and how to run a long build without losing its output or killing something already in flight.
allowed-tools: Bash, Read, Grep, Glob
---

# Deploying the stack

`./deploy` at the repository root is the only entry point. It renders configuration, then
drives the container runtime.

```
./deploy                    # main stack up
./deploy --build            # build images first, then up
./deploy --ai-services      # the standalone GPU tier instead
./deploy --down             # stop the selected side
./deploy --reset            # down, then remove the project's data volumes
./deploy --reset-caches     # with --reset: also wipe the model caches
./deploy --reset-temporal   # drop Temporal's history and visibility stores only
./deploy --print-env        # render the environment files and show them, start nothing
./deploy --print-command    # show the compose invocation, run nothing
```

## Before you deploy anything

**Check what is in flight.** A deploy restarts containers, and the end-to-end verification
runs for tens of minutes inside the worker — restarting it kills the run outright. Batch
your fixes so one restart serves several.

```
docker ps --format '{{.Names}}\t{{.Status}}'
uptime                      # someone else's build may already own the machine
```

## Configuration flows one way

`hoover4.ini` (gitignored; the template beside it is `hoover4.ini.example`) is the single
source. `deploy.py` renders it into the generated `.env` files next to the compose files.
**Never hand-edit a generated `.env`** — the next deploy overwrites it, and the change looks
like it worked until then.

- **Ports are configuration keys, not literals.** Read the key; never hard-code the number.
- **Secrets are files outside the repository**, bind-mounted read-only. No key value ever
  goes into a tracked file, a script, or a log line.
- **A key that is rendered and read by nothing is a lie.** When you add one, grep for its
  consumer in the same change, or write it down as not-yet-implemented.

## Four things that behave differently from how they read

**`up -d` is not a deployment; it is a no-op with opinions.** It reuses existing images and
containers, so a broken build context, a changed ignore file and new environment all stay
invisible until something forces a rebuild or a recreate. After changing anything that feeds
a build, run `--build` and *read the output*.

**`--reset --build` does not rebuild.** The reset path returns before the build path is
reached. It is two commands: `./deploy --reset`, then `./deploy --build`.

**Restarting one container fails under a rootless runtime when a sibling has legitimately
exited.** `docker restart <name>` refuses because an init container is `Exited (0)`, which is
its correct final state. `docker stop <name>` followed by `docker start <name>` works.

**Relative paths in a compose file resolve against the project directory** — the first `-f`
file's directory — not against the file that declares them. An overlay in a subdirectory
therefore points somewhere else entirely from where it reads as pointing.
`docker compose … config` renders absolute paths; use it whenever an overlay is added or
moved.

## Reading a build

Never judge a build from the last fifty lines. Redirect the full output to a file and grep
it:

```
.agents/skills/deploying-the-stack/scripts/deploy-logged.sh --build
```

It writes the whole run to a file, prints the exit status on its own line, and shows the
error context if there is any. A truncated log has cost a full rebuild cycle here more than
once.

**Build parallelism is bounded by one build argument**, which feeds every backend's own
spelling of it — the make, cmake, cargo and thread-cap variables are set as a group.
Missing one of them loses the bound and takes the machine down with it.

## Waiting on it

Background the run and keep working. A monitor that emits only on failure signatures beats
polling — but make sure its filter would fire on a crash, because silence must not be
indistinguishable from success. See `reference/long-jobs.md`.

## After a deploy

Confirm from **inside** the network, not from the host: a service being up on the host proves
nothing about whether the container that needs it can reach it.

```
docker exec hoover4-worker curl -sS --max-time 5 http://<service>:<port>/health
.agents/skills/verifying-before-claiming/scripts/stack-status.sh
```

If something is wrong, `debugging-the-stack` routes by symptom.

## References

- `reference/deploy-flags.md` — what each flag actually does, what a reset preserves, and
  the order the pieces come up in.
- `reference/long-jobs.md` — backgrounding, monitoring on failure signatures, and not
  disturbing a verification.
