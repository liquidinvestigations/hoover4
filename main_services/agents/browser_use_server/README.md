# Browser MCP server

Reads web pages with a real headless Chromium, for the pages the HTML scrapers cannot.
Port `21932`, container `hoover4-mcp-browser`, wired into the **full research agent** only.

The metasearch server finds pages; this one reads them. It exists because a growing share
of the web renders its body with JavaScript, where `httpx` plus a CSS selector gets an
empty shell.

## Tools

| Tool | Returns |
|---|---|
| `browse_page(url, timeout_seconds=30)` | `{title, text, links, truncated}` — readable text, capped at `MAX_DOCUMENT_CHARS` |

## Security: the URL check is the point

**Read [`browser_use_server/urlcheck.py`](browser_use_server/urlcheck.py) before changing
anything here.** This server is driven by an LLM and sits *inside* the `hoover4` network,
where `clickhouse:8123`, `temporal:7233` and `manticore:9308` answer unauthenticated HTTP.
An unrestricted fetcher in that position is an arbitrary read of the whole stack — and the
URL can arrive from a web page the model was asked to summarise, so "the user would not
ask for that" is not a defence.

Every URL must pass, in order:

1. scheme is `http` or `https` — no `file://`, `chrome://`, `data:`, `ftp://`
2. the host is not a known service on this network, and does not end in `.internal`
3. the host resolves, and **every** address it resolves to is public — this is what
   catches a public name with a private `A` record (`localtest.me`, `*.nip.io`), the usual
   SSRF bypass

Verified live:

```
http://clickhouse:8123/   -> refused: 'clickhouse' is an internal service and must not be fetched
file:///etc/passwd        -> refused: scheme 'file' is not allowed; only http and https are fetchable
```

What it does **not** close is a DNS-rebinding race between the check and Chromium's own
resolution. The deny-list and the network's lack of anything routable behind it are what
stand there. If this server ever becomes reachable from off-box, that gap needs closing.

Refusals are *returned* as `success: false` with a reason rather than raised, so the model
learns it cannot reach internal hosts and moves on.

## One browser, one call at a time

A single Chromium instance, serialised behind an `asyncio.Lock`. Concurrent CDP sessions
in one container is how this server falls over — tabs leak and the websocket interleaves.
It is deliberately a throughput bottleneck: a research tool called a handful of times per
question, not a crawler.

Every call gets **two attempts**. Chromium's websocket can be dead while the cached handle
still looks live, so `cdp.page.navigate` raises and only the *next* call succeeds — in a
real agent run that meant a perfectly good URL failed and the agent apologised and went
somewhere else. The retry runs against a guaranteed-fresh instance, which also separates
"stale browser" from "this page genuinely will not load".

On timeout the browser is **destroyed**, not reused, and the call is *not* retried — a
timeout is about the page, not the instance. A hung navigation otherwise leaves
Chromium in a state the next call inherits, and the failure then looks intermittent and
unrelated.

## Per-chat browser sessions

Each conversation browses in its own **Chromium browser context** — separate cookies,
storage and cache, shared process. The session id arrives as `X-Hoover4-Chat-Session`,
set by the research agent from the id the website gave it. It carries no authority; it is
an isolation key.

Before this, every chat shared one cookie jar. A consent cookie or a login from one
conversation followed the next user into theirs, which is a cross-tenant leak through the
one component whose job is fetching untrusted pages. A separate *browser* per chat would
cost a few hundred MB each; a context is Chromium's own isolation boundary and costs
almost nothing.

A session is disposed on whichever comes first:

* the chat ends and the website calls `POST /sessions/{id}/close` (idempotent — closing
  an unknown session is a 200 with `closed: false`);
* `BROWSER_SESSION_IDLE_SECONDS` (default 1 h) pass with no call and the reaper takes it;
* `BROWSER_MAX_SESSIONS` is exceeded, and the least recently used is evicted;
* the server restarts.

Callers with no session header share one anonymous session — the pre-existing behaviour,
kept so `curl` and any agent not yet passing the header still work, at the cost of no
isolation between them.

`GET /sessions` and `GET /health` both list what is live, which is the quickest way to
confirm isolation is actually happening: if every chat shows `has_context: false`,
`create_context` is failing and the server has silently fallen back to the shared context
(it logs a warning when it does).

Isolation partitions *state*, not throughput — the single lock below still serialises
every call across all sessions.

## The nodriver return-value trap

`tab.evaluate(..., return_by_value=True)` returns a plain Python value **only for
scalars**. For an object it returns a raw `cdp.runtime.RemoteObject` with the payload
buried in `deep_serialized_value`. The first version of this server checked
`isinstance(payload, dict)`, always missed, and returned `success=True` with empty text —
a silently blank page, the worst outcome for a tool an agent relies on.

The extraction script therefore returns `JSON.stringify(...)`, which crosses the boundary
as a scalar, and anything that is not a string is reported as an error. There is also an
explicit "loaded but no readable text" failure, so a JS-gated or blocked page is never
reported as a successful empty read.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `BROWSER_NAV_TIMEOUT` | `30` | seconds per navigation; exceeding it restarts Chromium |
| `BROWSER_SETTLE_SECONDS` | `1.5` | pause after load, for JS-rendered bodies |
| `BROWSER_MAX_LINKS` | `50` | a nav-heavy page has hundreds and they are mostly chrome |
| `MAX_DOCUMENT_CHARS` | `20000` | one long article must not eat the agent's context |
| `BROWSER_SESSION_IDLE_SECONDS` | `3600` | drop a chat's context after this long unused |
| `BROWSER_SESSION_REAP_INTERVAL` | `360` | how often the reaper sweeps |
| `BROWSER_MAX_SESSIONS` | `32` | live contexts before the LRU one is evicted |

`shm_size: 1gb` is set in compose: Chromium fills the default 64 MB `/dev/shm` and crashes
on content-heavy pages.

## The image is ~1 GB and that is expected

It carries Chromium plus its shared libraries and fonts. Do not try to slim it by dropping
the font packages — without them, text-heavy pages render as boxes and `innerText` comes
back as garbage, which is a silent content failure rather than a visible one.

## Tests

```bash
docker exec hoover4-mcp-browser python -m pytest tests/ -q   # 51 tests
```

Most of them are the URL check, because that is the security boundary: schemes, every
non-public address range in v4 and v6, the named services on this network, and the
public-name-with-private-record bypass. The rest cover session lifetime — expiry, the LRU
cap, and idempotent close — against the registry directly, with the disposer injected, so
they need no Chromium.
