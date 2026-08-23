# Working on a remote host

## The read-only pass

Most remote sessions should end here. Nothing below changes anything.

1. **What is running, and how long has it been running.** A container that restarted recently
   is the first thing to explain.
2. **The container's own logs**, from before the symptom, not from the tail.
3. **What the container actually received for the value in question**, read from its
   environment rather than from the file that was supposed to produce it.
4. **The rendered compose configuration**, which resolves relative paths and variable
   substitution to absolutes. A path that reads correctly in a file can resolve somewhere
   else entirely.
5. **A request made from inside the container that has the problem**, to the service it
   cannot reach. Host-side success proves nothing.
6. **Counts from the datastores**, for anything about data.

Report what you found and stop, unless changing something was the task.

## Before any reset

Capture, off the box, everything that lives only in the datastores and that no export
reproduces:

- the collection registry rows, including display names and visibility flags;
- user, group and permission rows;
- any settings changed through the site rather than through the configuration file.

A reset plus a re-ingest gives you back the documents and not these. This has been discovered
after the fact more than once.

## What transfers from a local success and what does not

| local result | transfers? |
|---|---|
| the code compiles and the tests pass | yes |
| a compose file parses and brings the stack up | **no**, a different engine is stricter, and rejects things the local one accepts |
| a cleanup command is safe | **no**, a shared runtime turns an unscoped command into someone else's outage |
| a path exists at the depth the script expects | **no**, corpus layout differs, and the ingest-root overrides exist for that |
| a build takes N minutes | **no**, release mode and shared cores change it by a lot |

## Deploying, when deploying is the task

Same entry point as locally, and the same rules: read what is in flight first, run the build
with its whole output captured, and never combine the reset flag with the build flag.
The reset path returns before the build runs. `deploying-the-stack` has the detail.

Afterwards, verify from inside the network and from a browser, in that order. A container
that is up is not a site that renders.

## Access

`INFRASTRUCTURE_INVENTORY.md` at the repository root, gitignored, local, filled in from an
interview with the operator. Never copy anything out of it into this repository, a script, a
commit message, or a log.
