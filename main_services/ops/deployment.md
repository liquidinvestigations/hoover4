# Deploying on a host reachable from the internet

`./deploy` is the same command everywhere. What changes on a server is `hoover4.ini`:
which interfaces the ports answer on, whether the accelerated tier exists at all, and where
the corpus lives. This is the runbook for that configuration, for the reset that precedes it,
and for the staged ingest that follows.

**Every address below is a placeholder.** This page describes the mechanism, which key
publishes what, and what each one is protecting against. What a particular deployment
actually uses is in `INFRASTRUCTURE_INVENTORY.md` at the repository root, which is local and
gitignored: this file is public, and no hostname, address or credential belongs in it.

The shape assumed throughout is a host with one interface reachable from the internet and one
private one, no accelerator, and a hosted model endpoint.

## The two bind keys

`website_bind_ip` and `infra_bind_ip` in `[main_services]` are the address half of every
published port mapping. Both default to `0.0.0.0`, which is what a dev box wants and what
a host reachable from the internet must not have.

| | publishes | default | on a public host |
|---|---|---|---|
| `website_bind_ip` | the website's `12345` | `0.0.0.0` | the private address a reverse proxy reaches it on |
| `infra_bind_ip` | ClickHouse HTTP + native, Manticore SQL + HTTP, Garage S3 API, CH-UI, ClickHouse monitoring, pdf-to-html | `0.0.0.0` | `127.0.0.1` |

**Neither of these is hardening in the abstract.** The website authenticates by trusting an
identity header set in front of it, so it has to be unreachable except through whatever sets
that header. In demo mode it additionally provisions every anonymous visitor a guest session
and treats it as an administrator; with demo mode off nothing anonymous is provisioned at
all, the identity route refuses, the site renders *Sign-in required*, and every endpoint
answers 401, so a deployment fronted by something that sets no identity header serves
nobody, which is the intended failure rather than a fault.

The infrastructure ports are worse and simpler: the search engine has no authentication at
all, and the column store, the object store and the two admin consoles ship with the compose
file's default credentials. Published on a reachable interface, **each one is a full read of
the corpus**.

The port half stays where it is: every service port is an ini key, and the website's
`12345` is deliberately hardcoded in the compose file as the one URL humans type.
Services already bound to loopback in the compose file. Temporal, Cassandra,
Elasticsearch, Redis, the CPU twins, every MCP server and both research agents. Ignore
`infra_bind_ip` and stay on loopback regardless.

Reaching a loopback-bound admin console from elsewhere is a port forward over ssh, not a
change to the bind key. Under a forward, the `http://localhost:<port>` links the admin pages
render are correct as written, which is why they are not configurable.

## A `hoover4.ini` for a host with no accelerator

Everything not listed stays at `hoover4.ini.example`'s value. Angle-bracketed values are
placeholders; the real ones are in `INFRASTRUCTURE_INVENTORY.md`.

```ini
[ai_services]
enabled            = false      ; the GPU tier does not exist on this host
ai_server_enabled  = false
ner_enabled        = false
embeddings_enabled = false
reranker_enabled   = false
easyocr_enabled    = false      ; not implied by the others, see below
llm_selfhosted     = false

[main_services]
ner_provider          = spacy       ; the CPU twin, in-network
embeddings_provider   = none        ; no vectors, no semantic search
pdf_ocr_provider      = tesseract   ; CPU
tesseract_cpu_enabled = true
ocr_pdf_enabled       = true
gpu_fallback          = false       ; nothing to fall back from

website_release_mode  = true        ; a visitor must not get `dx serve`
serena_enabled        = false       ; dev tooling, not a deployed service

demo_mode             = true
testdata_dir          = /opt/hoover4-testdata
datasets_mount_path   = /testdata

website_bind_ip       = <private-ip>    ; the private address the proxy reaches
infra_bind_ip         = 127.0.0.1

mcp_shared_secret_file = <secrets-dir>/mcp-shared-secret.txt

[llm_provider.nvidia]
enabled      = true
base_url     = https://integrate.api.nvidia.com/v1
model        = nvidia/nemotron-3-super-120b-a12b
api_key_file = <secrets-dir>/nvidia-api-key.txt

[llm_provider.selfhosted]
enabled = false
[llm_provider.moonshot]
enabled = false
```

**`easyocr_enabled` behaves differently from the others.** `OCR_EASYOCR_URL` is rendered from that flag alone,
*regardless* of `[ai_services] enabled`, and it ships `true`. Left alone it renders a
`host.containers.internal:21962` endpoint into the worker and the website, a name Docker
Engine on Linux does not inject at all (only podman and Docker Desktop do), so the OCR
calls hang rather than fail. `[ai_services] enabled = false` stops
`./deploy --ai-services` from running; it does not blank the derived URLs.

Which gives the one-line test for "no GPU endpoints anywhere":

```bash
./deploy --print-env | grep host.containers.internal    # must print nothing
```

`--print-env` renders and starts nothing, so run it before anything else and read it.
For the configuration above it must show `NER_URL=http://hoover4-ner-spacy:8000/v1`, and
`EMBEDDINGS_URL`, `RERANK_URL`, `OCR_EASYOCR_URL` and `NER_URL_FALLBACK` all **empty**.

### Secrets

Every `*_file` key holds a host path, never a value. `deploy.py` refuses a file that does
not exist, that is group- or world-readable, or whose real path is inside the checkout.
A key in the checkout leaks into build contexts and commits. The file is bind-mounted
read-only into the containers that need it; no key value ever reaches a `.env` or a log.

```bash
mkdir -p <secrets-dir> && chmod 700 <secrets-dir>
head -c 32 /dev/urandom | base64 > <secrets-dir>/mcp-shared-secret.txt
chmod 600 <secrets-dir>/mcp-shared-secret.txt
chmod 600 <secrets-dir>/nvidia-api-key.txt
```

`<secrets-dir>` is a directory **outside the checkout**, which `deploy.py` enforces: it
refuses a file that does not exist, that is group- or world-readable, or whose real path is
inside the repository. Where a given deployment keeps it is recorded in
`INFRASTRUCTURE_INVENTORY.md`, by location, never by value.

An empty `mcp_shared_secret_file` leaves the MCP servers unauthenticated, which is
tolerable only because they publish on `127.0.0.1`.

## Resetting a host that has run an older stack

`./deploy --reset` takes the compose project down and removes its `hoover4_*` data
volumes. Two things it does not do, both of which matter on a host that has been running
a while:

**It does not remove orphans, and one orphan aborts the reset.** `compose down` without
`--remove-orphans` leaves behind any container the current compose file no longer
declares. If such a container holds a `hoover4_*` volume, the volume removal fails, and
`--reset` turns that into a hard failure *after* the rest of the stack is already down.
Remove them by hand first:

```bash
docker ps -a --filter label=com.docker.compose.project=hoover4 --format '{{.Names}}'
```

Review that list against the current compose file and `docker rm -f` anything no longer
in it, before the reset rather than after.

**It does not touch images or build cache.** Reclaiming those needs an explicit and
**scoped** prune. On a shared daemon this is not optional scoping:

```bash
docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | grep -i hoover4   # review
docker rmi $(docker images -q 'hoover4-*')
docker builder prune -af
```

**Never `docker system prune -a --volumes` on a shared daemon.** It takes every other
project's images and unnamed volumes with it.

What a reset destroys is exactly the derived data: ClickHouse, Manticore, Garage blobs,
Temporal's Cassandra and Elasticsearch, the monitoring volume and the website's build
target. The corpus itself is a **bind mount** (`testdata_dir`), not a volume, and no step
here touches it. That is the whole recovery story: everything except the bind mount is
re-creatable from it.

## Build and first boot

```bash
git submodule update --init --recursive     # the PDF viewer is a submodule
./deploy --build 2>&1 | tee ~/deploy-build.log
```

Read the log rather than its last fifty lines. `up -d` reuses existing images and
containers, so a broken build context stays invisible until something forces a rebuild.

`./deploy` on the main side never calls `nvidia-smi` (the GPU preflight returns
immediately for the main side), so nothing here needs a GPU to exist.

With `website_release_mode = true` the website container then runs `dx build --release`
**on first boot**, into a build-target volume the reset just emptied. That is a cold Rust
+ WASM release build and the site is down for its duration:

```bash
docker logs -f hoover4-website     # wait for `[website] serving …`
```

Do not conclude anything is wrong before that line appears.

### Assertions before ingesting anything

```bash
docker ps --format '{{.Names}}\t{{.Status}}'   # all healthy, nothing restarting
ss -tlnp | grep 12345                          # the website bind address only
ss -tlnp | grep 219                            # 127.0.0.1 on every infrastructure port
curl -sI http://<website_bind_ip>:12345/           # 200
curl -sS --max-time 5 http://<reachable-ip>:12345/ # must FAIL
curl -sS --max-time 5 http://<reachable-ip>:21900/ # must FAIL
docker exec hoover4-worker uv run python main.py list-collections
```

Run the last two probes **from a machine outside the private network** as well. That they
stop answering is the entire point of the bind settings, and a probe from the host itself
does not test it.

## Creating collections and ingesting

```bash
cd main_services
./run.sh create-collection <name> --fullname "<Display Name>" --public
./run.sh add-disk-dataset  <name> <dataset> <in-container path>
```

`create-collection` registers the collection and provisions its ClickHouse database in
one idempotent command, which is the scripted equivalent of the admin UI's create action.
`--public` is worth stating: a collection is restricted by default and is then visible
only through a group grant. A demo that displays its collections anyway is relying on
`demo_mode` and the `guest_permissions_mode` server setting both being open, which is two
independent defaults holding rather than one intent recorded.

Paths are **in-container** paths under `datasets_mount_path`, so a corpus at
`/opt/hoover4-testdata/consulate` on the host is `/testdata/consulate` here.

### Ingest in stages, smallest first

`add-disk-dataset` blocks through scan → compute-plans → execute-plans, which is correct:
the stages must run in order and only the CLI sequences them. Two consequences:

* **Killing the CLI does not stop the work.** The workflows keep running server-side
  while the caller sees a dead command. Run each ingest under `tmux` or `nohup`.
* **Never redeploy while one is running.** `./deploy` recreates `hoover4-worker` and
  SIGKILLs whatever is attached to it.

Ingest a small slice of every collection first, as its own dataset, and verify the whole
pipeline on that before releasing the rest. A dataset is the unit of retry and the unit
of the progress bar, so a corpus split into several datasets fails and resumes in pieces
rather than all at once. Content-addressed ingest means overlapping datasets dedup rather
than duplicate, so a slice that is later covered by a fuller dataset costs nothing.

Watch progress at `/admin/collections/<name>/processing`, and in the Temporal UI over the
ssh tunnel above. `./task-time-report.sh --since '<start>'` turns a finished small ingest
into an estimate for a large one.

### Verify after each stage

```bash
cd main_services
HOOVER4_TESTDATA_DIR=<host corpus dir> ./fetch-testdata.sh --check
T=<in-container path to hoover-testdata/data>
INGEST_ROOT_TESTDATA=$T/disk-files/pdf-doc-txt \
INGEST_ROOT_EMAILS=$T/eml-2-attachment \
INGEST_ROOT_ZIPS=$T/zip-in-multiple-locations \
INGEST_ROOT_SHAPES=$T/many-children \
  ./verify-stack.sh
```

The `INGEST_ROOT_*` overrides are not optional when `testdata_dir` points outside the
repo: the defaults assume the in-repo `testdata/`, and the fixtures then sit at a
different depth. `fetch-testdata.sh --check` needs `HOOVER4_TESTDATA_DIR` for the same
reason.

`ingest_dataset` skips a dataset that is already registered and the invariants iterate
over every collection in the ledger rather than a hardcoded list, so re-running after each
stage is cheap. Two of its checks find real problems on a fresh host in particular: the
**Manticore-vs-ledger equality** check, because the whole index is new, and the assertion
that **no `blobs` row references `derived/`**, because the searchable-PDF writer writes
back into the blob store under that prefix and the ingest walker must never re-scan its own output.

## Memory

Cassandra sits near its `mem_limit` from the moment it starts: the JVM reserves its heap
at boot. A high number there is not pressure and is not the signal to act on. An actual
kill is:

```bash
dmesg -T | grep -i -E 'oom|killed process'
docker ps -a --filter status=exited --format '{{.Names}}\t{{.Status}}'   # look for 137
```

The largest ingest is the window in which this happens. If something is killed, raise
that container's `mem_limit`, or, for `hoover4-mcp-browser`, which has no `mem_limit`
and runs up to eight Chromium instances, lower `BROWSER_MAX_CONTEXTS`.

**A killed server process does not look like a memory problem to its callers.** When a
cgroup kills the process inside a container that restarts, `docker ps` shows the service
healthy moments later and `OOMKilled` on the container is **false**, so what the pipeline
reports is `ConnectionError: Connection refused` against something that is plainly up.
The two things that identify it are `RestartCount` climbing and
`Memory cgroup out of memory` in `dmesg`. Check both before believing a network fault
between two containers on the same network.

`hoover4-ner-spacy` is the one to watch during a large ingest, and its growth is not a
leak in the ordinary sense: a spaCy pipeline interns every distinct string it has ever
seen and never evicts, so memory tracks the corpus's vocabulary rather than the current
request. `NER_RECYCLE_CHARS` bounds it by rebuilding the pipeline on a character budget;
`/health` reports `pipeline_reloads`, and that number staying at 0 through a long ingest
means the bound is not being applied.

## What a configuration with no accelerator does not do

Stated up front, because none of it is a fault to be diagnosed later:

| | |
|---|---|
| **No vector search** | `embeddings_provider = none` leaves `EMBEDDINGS_URL` empty, P5 logs *"skipping chunk+embed"* and writes nothing. No `text_chunk_vectors`, no `_vectors` shards, keyword search everywhere. |
| **…which removes a memory risk** | `_vectors` HNSW tables are RAM-resident at roughly 2 KB per chunk. Not building them is one large thing the host does not have to hold. |
| **No reranking** | Collection RAG and web search return RRF order with `rerank_applied: false`. |
| **Chat still works** | It is a network call to the LLM provider, not a GPU. It answers from keyword retrieval only. |
| **Entity counts differ** | CPU spaCy is a different model from the GPU NER. A different number is not a regression. |
| **OCR is on the CPU** | Tesseract processes image-bearing PDFs and `ocr_pdf` writes searchable PDFs back to the blob store under `derived/`. Slower ingest, new output, one invariant guarding against re-ingesting it. |
| **Demo mode means anonymous administrators** | Every guest session is an administrator, and demo mode is what provisions guests at all. Acceptable only behind an authenticating front end, which is what `website_bind_ip` is enforcing. |
| **A browser ships with the stack** | `compose/agents.yaml` is always on, so `hoover4-mcp-browser` is part of any deployment. Its URL checks are strict (public http/https only, deny-list, PAC), but it is there. |

## Navigation

- [Go Back](Readme.md)
