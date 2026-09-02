# Known defects and limitations

What the system does today that a person changing it should know about. Every entry states
behaviour confirmed against the running stack, either by a command whose output shows it or
by naming where the behaviour was decided on purpose.

## Pipeline and indexing

### No extraction code rejoins a PDF's single-character text runs

A PDF page whose text layer stores a heading as single-character runs keeps that shape
through extraction and storage, because nothing in the pipeline rejoins the runs into words.
The entity stop-list hides the garbage entity this produces, but the underlying text is
untouched.

```
grep -rn "rejoin\|single.character run" --include="*.py" main_services/processing/tasks/
```

The search returns nothing. No extraction code rejoins the letters.

## Search and interface

### The in-chat search tool has no offset, so only the nearest results are reachable

`search_collections` takes a `max_results` argument up to its ceiling, and no offset. A
caller cannot page past the first batch of hits, so a plan that reasons "more turns reach
further results" is wrong: the tool returns the same top results every time.

```
grep -n "^def search_collections" -A 6 main_services/agents/collection_search_server/collection_search_server/server.py
```

### An unparseable route renders the not-found page under an HTTP 200 status

A request for a route the frontend cannot match renders the "Page not found" page, and the
response still carries a 200 status. A tool reading the status code alone sees success for a
page that does not exist.

```
env_file="main_services/ops/docker/.env"
bind=$(grep -E '^WEBSITE_BIND_IP=' "$env_file" | cut -d= -f2-)
case "$bind" in
    ""|0.0.0.0) WEBSITE_URL="http://localhost:12345" ;;
    *)          WEBSITE_URL="http://$bind:12345" ;;
esac
curl -s -o /dev/null -w '%{http_code}\n' "$WEBSITE_URL/this-route-cannot-match"
```

`WEBSITE_URL` follows the same derivation `main_services/verify-stack.sh` uses from
`WEBSITE_BIND_IP` in the rendered `.env`. The request prints `200`.

### The collection detail page renders no document error count

The collection detail page shows no error count for a collection, even when a plan recorded
failures against its documents.

```
grep -n "error" website/frontend/src/pages/admin/collection_detail.rs
```

The matches are all interface-action errors. None of them is a document error count.

## Chat and agents

### A chat conversation has no cap on its total prompt size

Cost tracks the number of tool calls made in a turn, not the size of any one of them, and
nothing caps how long a conversation or its tool history can grow.

```
grep -rn "max.*token\|prompt.*budget" main_services/processing/tasks/P_agent/summarize.py
```

The only cap found bounds one title-and-summary completion, not the conversation.

## Configuration and deployment

### A plain container stop or restart can cut the worker's drain short

The container runtime applies the compose file's stop grace period only when it is itself
the process stopping the container, so a plain `docker stop` or `docker restart` still kills
the worker ten seconds in, whatever the configuration says. `main_services/restart-worker.sh`
reads the worker's own drain period and passes it explicitly, but anything else that stops
the worker cuts the drain short, silently.

```
docker inspect hoover4-worker --format '{{.Config.StopTimeout}}'
```

It prints `10`, the runtime's own default, whatever the compose file configures.

### No workflow versioning exists, by decision

No patch gates and no build ids protect a running Temporal workflow from a definition change
made while an execution is in flight. A script names whether a diff touches workflow code
rather than only activity code, so the realistic case is covered. Real versioning is
deferred until a workflow-code deploy is genuinely needed under a live long-running
execution.

```
ls .agents/check-workflow-diff.py
```

### An applied migration is frozen, and its wording cannot be corrected

The migration runner records an md5 of the whole migration file, comments included, so
editing one word in an already-applied migration makes every deployment that already ran it
refuse to start. Two migration files in the tree carry wording that is known to be wrong and
cannot be corrected without resetting every deployment that applied them.

```
grep -n "already-applied migration is the exception" AGENTS.md
```

### `PDF_TO_HTML_ENDPOINT` reaches the website and nothing reads it

The website container is given the `PDF_TO_HTML_ENDPOINT` environment variable, but no Rust
or Python file in the tree reads it under that name.

```
grep -rn 'env::var("PDF_TO_HTML_ENDPOINT")' --include='*.rs' --include='*.py' .
```

### The AI status page reports a configuration mismatch across hosts

The host running the GPU-side services carries a diverged copy of the deployment script, so
its configuration fingerprint disagrees with the one the website host renders. Every guarded
capability still probes as agreeing, so the page states a real divergence in a way that
reads as worse than it is.

```
main_services/verify-stack.sh
```

The run prints a `NOTE - hoover4.ini drift` line naming the two fingerprints.

### `supports_tools` is never populated, so a profile cannot filter for tool-capable models

`llm_models` declares `supports_tools` with a default of 0, and the writer that fills the
table never sets the column. A profile's model picker cannot check whether a model chosen for
it can call tools at all.

```
grep -n "supports_tools" main_services/processing/database/db_global_migrations/00019_llm_models.sql main_services/processing/tasks/llm_catalog.py
```

The migration line is the only match. `llm_catalog.py` is the only writer and does not
mention the column.

### The local testdata checkout is behind the pinned commit

The stack verification warns that the local fixture checkout is at a different commit from
the one pinned in the repository. Every pinned fixture path still resolves, but a fixture
added since the pin is missing until the checkout is pulled.

```
main_services/verify-stack.sh
```

The run prints a `WARN - hoover-testdata is at` line naming both commits.

### A credential-shaped default sits in the tracked compose file

The object store's access secret has a literal default value, repeated in four services in
the compose file, so a deployment that sets nothing runs on a known key. It is a
long-standing convention here, which is why it keeps being copied into the next service.

```
grep -n "S3_SECRET_KEY" main_services/ops/docker/docker-compose.yaml
```

## Stated limitations, not defects

These are decisions. They are here so nobody re-reports them as bugs.

### A plan reports success over per-document failures

A plan is marked finished when its stages ran, not when every document inside it succeeded.
Requiring per-document success would mean a messy corpus never finishes. The operations log
renders the failure counts on the finished row instead, so a reader still has to check them
beside the green status.

### A nag can produce bookkeeping instead of work

A nag against a capable model can mark items resolved and restate a previous answer instead
of doing new work or revising the plan, without breaking the loop's own rules. A five-nag cap
bounds how much bookkeeping one stall can produce.

```
grep -n "nag_number\|five nags" main_services/processing/tasks/P_agent/nagging.py main_services/processing/tasks/P_agent/workflows.py
```

### Two collections are restricted and must be flipped by hand

No code is involved. Recorded here so the fact is not rediscovered.

### The search result ceiling of 1,000 is intended

The ceiling itself is a decision. The missing offset under it, which stops a caller from
reaching results past the first batch, is tracked above under Search and interface.
