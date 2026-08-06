# Browser MCP server

Reads web pages with a real headless Chromium, for the pages the HTML scrapers cannot.
Port `8087`, container `hoover4-mcp-browser`, wired into the **full research agent** only.

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

`shm_size: 1gb` is set in compose: Chromium fills the default 64 MB `/dev/shm` and crashes
on content-heavy pages.

## The image is ~1 GB and that is expected

It carries Chromium plus its shared libraries and fonts. Do not try to slim it by dropping
the font packages — without them, text-heavy pages render as boxes and `innerText` comes
back as garbage, which is a silent content failure rather than a visible one.

## Tests

```bash
docker exec hoover4-mcp-browser python -m pytest tests/ -q   # 40 tests
```

Almost all of them are the URL check, because that is the security boundary: schemes,
every non-public address range in v4 and v6, the named services on this network, and the
public-name-with-private-record bypass.
