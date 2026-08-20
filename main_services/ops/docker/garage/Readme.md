# Garage — the S3 blob store

Single-node [Garage](https://garagehq.deuxfleurs.fr/) serving the `hoover4-blobs` bucket
on `garage:3900`. Blob keys are `<collection_dataset>/<blob_hash>` for ingested content
and `derived/...` for everything the pipeline and the agents synthesise;
`blobs.s3_path` stores them as `s3://<bucket>/<key>`.

Files here:

- `garage.toml` — the daemon's config, bind-mounted read-only.
- `Dockerfile` + `init.sh` — the `garage-init` one-shot that turns a blank node into a
  usable cluster.

## The region is not cosmetic

`s3_region = "us-east-1"` in `garage.toml` is a deliberate deviation from Garage's own
default of `"garage"`, and it is the single setting that decides whether an S3 client
needs to know anything about this deployment.

SigV4 signs the region into the credential scope, so a client using the universal default
against a server declaring `garage` fails with
`AuthorizationHeaderMalformed … unexpected scope: '…/us-east-1/s3/aws4_request'`. That
error names authorization, not the region, so it reads as a credential problem and sends
you to the wrong file. Declaring the region every client already assumes keeps "point it
at a different endpoint" a one-line change.

Changing this value means passing an explicit region at every S3 construction site in
the tree, in three languages.

## Credentials have minimum lengths

Garage rejects an access key id shorter than 8 characters and a secret shorter than 16:
`garage key import` answers *"Key identifiers should be at least 8 characters long"*.
Short credentials that work against other S3 implementations are refused here, and the
refusal happens at bootstrap rather than at first use.

## The bootstrap runs on every deploy

`init.sh` is not a first-run script. It waits for `/health`, reads the node id from the
admin API, and then checks each piece of state before changing it: the layout is assigned
only when `.nodes[0].role` is still `null`, the key is imported only when
`garage key info` does not already find it, the bucket is created only when
`garage bucket info` does not. The permission grants are unconditional because granting
an existing permission is a no-op.

It reads the node id over HTTP rather than sharing the metadata volume: LMDB is
single-writer, and a second process opening that directory is not something to find out
about later.

## `docker stats` reads high here, and that is normal

LMDB is mmap-backed, so most of what the container appears to be using is reclaimable
page cache rather than the daemon's own memory. Under a memory limit the total sits near
that limit whether the store is busy or idle. This is the same reading mistake the JVM
services invite (see the ops `Readme.md`): judge by `anon` in
`/sys/fs/cgroup/memory.stat`, never by the `docker stats` total, and ask Garage itself
with `garage stats` when the question is whether the store is healthy.

## Operating it

There is no web console. `khairul169/garage-webui` speaks the v1 admin API and Garage 2.x
answers `Unknown API endpoint` to it, so the admin API port is published on loopback for
`curl` and the CLI instead:

```
docker exec garage /garage status                 # one node, with a role assigned
docker exec garage /garage bucket info hoover4-blobs
docker exec garage /garage key info <access key>
docker exec garage /garage layout show            # no staged changes on a settled node
```

`NO ROLE ASSIGNED` in `status` means the bootstrap did not run or did not finish — read
`docker logs garage-init`.

## Navigation

- [Go Back](../Readme.md)
