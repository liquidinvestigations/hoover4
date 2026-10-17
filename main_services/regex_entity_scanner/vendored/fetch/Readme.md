# Fetch scripts

One script per upstream, plus [common.sh](common.sh) with the shared helpers. They run inside the dev
container, are idempotent, and can be run individually or through [../fetch-all.sh](../fetch-all.sh).

The shape every script follows:

1. Stage the download or shallow clone under `tmp/stage/`.
2. Copy **only the subset we use** into [../data/](../data) (loaded at run time) or `../reference/`
   (ported and generated from at development time).
3. Copy the upstream licence into [../licenses/](../licenses).
4. `stamp` the target with its upstream and the commit or version it came from.

`clone` and `npm_tarball` in [common.sh](common.sh) write the selected path to stdout.
They write progress to stderr so the caller can capture the path separately.
`replace_dir` deletes the target before copying its replacement.
Files removed upstream therefore disappear from the local copy.

[gleif.sh](gleif.sh) is excluded from [fetch-all.sh](../fetch-all.sh) by name: the download is measured in gigabytes and
nothing needs it until LEI resolution does.
