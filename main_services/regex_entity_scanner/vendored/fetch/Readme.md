# Fetch scripts

One script per upstream, plus `common.sh` with the shared helpers. They run inside the dev
container, are idempotent, and can be run individually or through `../fetch-all.sh`.

The shape every script follows:

1. Stage the download or shallow clone under `tmp/stage/`.
2. Copy **only the subset we use** into `../data/` (loaded at run time) or `../reference/`
   (ported and generated from at development time).
3. Copy the upstream licence into `../licenses/`.
4. `stamp` the target with its upstream and the commit or version it came from.

Two details in `common.sh` are worth knowing before writing a new one. `clone` and `npm_tarball`
echo a path on stdout for the caller to capture, so progress output goes to stderr — a progress line
landing in that capture turns into a path that does not exist. And `replace_dir` deletes the target
before copying, so that a file removed upstream disappears here too instead of lingering as a
vendored ghost.

`gleif.sh` is excluded from `fetch-all.sh` by name: the download is measured in gigabytes and
nothing needs it until LEI resolution does.
