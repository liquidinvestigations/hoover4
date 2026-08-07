# Browser MCP router

Drives a real browser for the full research agent. Port `21932`, container
`hoover4-mcp-browser`.

Until plan 2 phase 3 this server exposed one `browse_page` tool over a shared Chromium. It
now exposes **Playwright's whole browser surface** — 30 tools: navigate, click, type, fill
forms, read the accessibility snapshot, list network requests and console messages, take
screenshots, manage tabs — routed to a browser that belongs to the calling conversation and
nobody else, with every page automatically captured.

`browse_page` does **not** survive. Reading a page is `browser_navigate` followed by
`browser_snapshot`, and keeping a fifth way to do it would only give a small model another
thing to pick wrongly.

## Shape

```
research agent ──MCP/streamable-http──▶ hoover4-mcp-browser (router)
   header: x-hoover4-chat-session: <id>        │
                                               │ per chat, on first tool call
                                               ▼
                        ┌────────────────────────────────────┐
                        │ Chromium (nodriver-configured)     │
                        │   own --user-data-dir              │
                        │   uBOL + ISDCAC loaded             │
                        │   ephemeral CDP port               │
                        └────────────────────────────────────┘
                              ▲                   ▲
                --cdp-endpoint│                   │ CDP (capture)
                        ┌─────┴──────────────┐    │
                        │ playwright-mcp     │    └── the router's own connection
                        │ (node, per chat)   │
                        └────────────────────┘
```

A call flows: **urlcheck → route to this chat's browser → forward to its sidecar →
capture**.

## Why a whole browser per chat, not a browser context

Phase 1 gave each conversation a Chromium *browser context*, which is the right isolation
boundary for cookies and costs almost nothing. Phase 3 needed more.

**playwright-mcp attached with `--cdp-endpoint` shares one browser context across every
client on that endpoint.** Measured, not assumed (plan §3.2): two clients, one cookie jar.
`--isolated` restores isolation but makes Playwright launch its *own* browser, which loses
the extensions and the CDP handle capture needs.

So the boundary moved down a level: one Chromium **process** per chat, each with its own
profile directory and its own sidecar bound to it. That costs a few hundred MB per live
chat, which is why the cap is 8 and the reaper is aggressive.

Verified live: chat A sets `document.cookie` on `example.com`, chat B on the same origin
reads nothing.

## Chromium is launched by this server, not by nodriver

`chat_browser.start()` spawns the browser process itself and only then hands nodriver a
`host`+`port` to attach to. Two reasons, both paid for:

* nodriver treats a configured `host`+`port` as *"attach to a browser that is already
  running"* and **skips the launch entirely** — and the port has to be configured, because
  the sidecar must be told it. The symptom is a confident `Failed to connect to browser /
  you may be running as root` against a Chromium that was never started.
* nodriver's own launch gives the browser ~2.7 s to answer `/json/version`. Chromium with
  two MV3 extensions takes 5–6 s in this image, so even without the first problem it would
  have raced.

`Config` still builds the argument list — it owns the extension flags — but the process and
its pipes are ours. Chromium's stderr goes to `DEVNULL`: in a container it writes a
continuous stream of D-Bus and GCM errors, and on a pipe nobody reads, that pipe fills and
the browser blocks on write — a wedge that looks exactly like a hung page.

## The sidecar answers to `localhost`, not `127.0.0.1`

playwright-mcp defaults `--allowed-hosts` to "the host the server is bound to", spelled
**`localhost`, with the port**, and compares it against the request's `Host` header. The
same address by IP comes back:

```
HTTP/1.1 403 Forbidden
Access is only allowed at localhost:41999
```

So the router's client URL is `http://localhost:<port>/mcp`. Do not "fix" it to
`127.0.0.1`, and do not pass `--allowed-hosts 127.0.0.1` — that makes it worse, because the
comparison then includes the port and never matches.

The binary is `playwright-mcp` (not `mcp-server-playwright`), pinned in the Dockerfile.
**Never `@latest` at runtime**: a silently updated sidecar changes the entire tool surface
the agent sees, mid-conversation, with nothing in the transcript saying so.

## Lifecycle

| Variable | Default | Meaning |
|---|---|---|
| `BROWSER_MAX_CONTEXTS` | `8` | live chats before the least recently used is evicted |
| `BROWSER_IDLE_SECONDS` | `900` | a chat idle this long has its browser reaped |
| `BROWSER_REAP_INTERVAL` | `60` | how often the reaper sweeps |
| `BROWSER_MAX_TABS_PER_CHAT` | `6` | a model opening a tab per result must not exhaust the container |

Eviction tears down both processes and deletes the profile directory. The evicted chat's
next call transparently starts a fresh browser — its cookies and tabs are gone, which the
design accepts. Coming back always costs somebody else their browser: the cap is a memory
ceiling.

`POST /sessions/{id}/close` drops one chat immediately (called when a conversation ends).
Idempotent: closing an unknown session is a 200 with `closed: false`.

**There is no global lock any more.** It existed because one Chromium cannot serve
concurrent CDP sessions safely; with one browser per chat, serialisation belongs per chat,
and a global lock would make eight conversations queue behind each other.

`GET /health` and `GET /sessions` report live sessions with both ports, spawn failures,
sidecar restarts and whether the template is ready.

A dead sidecar is **restarted on the next call** rather than surfaced as a failure: the
tool call the user is waiting on succeeds, instead of failing once to teach us the process
was gone. A second failure in the same call is real and is returned as a retryable error.

## The warm template session

`list_tools` runs during graph construction, for every chat, including the ones that will
never browse. It is answered from a **template browser started at boot** — otherwise tool
discovery would start a Chromium per conversation on the site.

The template also makes a broken image fail at boot with a log line instead of on the first
user's first tool call. `/health` reports `template_ready` and the tool count; `tools: 0` is
the signature.

## Security: the URL check is the boundary

**Read [`browser_use_server/urlcheck.py`](browser_use_server/urlcheck.py) before changing
anything here.** This server is driven by an LLM and sits *inside* the `hoover4` network,
where `clickhouse:8123`, `temporal:7233` and `manticore:9308` answer unauthenticated HTTP.
An unrestricted fetcher in that position is an arbitrary read of the whole stack — and the
URL can arrive from a web page the model was asked to summarise, so "the user would not ask
for that" is not a defence.

`check_tool_arguments` runs in the **router**, before the call reaches the sidecar, on every
URL-shaped argument of every forwarded tool. `browse_page` was the only navigating tool when
this module was written; there are now two dozen, so the guard moved up to the dispatch
point. Each candidate must pass, in order:

1. scheme is `http` or `https` — no `file://`, `chrome://`, `data:`, `ftp://`
2. the host is not a known service on this network, and does not end in `.internal`
3. the host resolves, and **every** address it resolves to is public — this is what catches
   a public name with a private `A` record (`localtest.me`, `*.nip.io`), the usual SSRF
   bypass

Verified live through the router:

```
http://clickhouse:8123/  -> refused: 'clickhouse' is an internal service and must not be fetched
file:///etc/passwd       -> refused: 'file:///etc/passwd' is not an http or https URL
http://127.0.0.1:8087/   -> refused: '127.0.0.1' resolves to the non-public address 127.0.0.1
```

Refusals are **returned** as a tool result, not raised, so the model learns it cannot reach
internal hosts and moves on. No browser is spawned for a refused call.

### The line that survives a redirect

`check_tool_arguments` only ever sees **tool arguments**. Everything Chromium does after a
navigation starts — an HTTP 302, a `<meta refresh>`, `location =`, an `<img src>` — passes
through no tool call and so through no check. Measured: a public page redirecting to
`http://manticore:9308/sql?query=…` was fetched and its data returned to the model.

So Chromium is launched with a **PAC script** ([`netfilter.py`](browser_use_server/netfilter.py))
handed to `--proxy-pac-url` as a `data:` URL. PAC is consulted for every request the network
stack makes, each hop of a redirect chain included, before a connection is opened, in every
tab. Anything internal is routed to a proxy that does not exist and fails at once with
`ERR_PROXY_CONNECTION_FAILED`:

* a **single-label** host (`isPlainHostName`) — every container here answers to a bare name,
  so this covers services added after the file was written, with no list to maintain;
* `.internal` and `.localhost` suffixes (cloud metadata lives in the first);
* any address, **after resolution**, in a private, loopback, link-local, CGNAT or reserved
  range — the same rule urlcheck applies, applied to what the browser actually connects to;
* a name that does not resolve: fail closed.

`--blocked-origins` on the sidecar is a **third** opinion, nothing more. Playwright's own
documentation says it is not a security boundary *and does not affect redirects* — and until
this sweep it did nothing at all: a bare hostname compiles to the glob `*://host/**`, a
single `*` does not cross `/`, and every service here listens on a port, so it matched
nothing. It is now passed as `http://host:*` / `https://host:*`, the one form
`originOrHostGlob` turns into a port-tolerant glob.

What none of this closes is a DNS-rebinding race between urlcheck and Chromium's own
resolution — though the PAC script resolves independently at connect time, which narrows it
considerably. PAC's `dnsResolve` is IPv4-only (`dnsResolveEx` is a Microsoft extension
Chromium does not implement); this network is IPv4 and the name rules catch every internal
host regardless.

## Capture

After any tool that can change what is on screen — and **also when it failed** — the router
takes a capture through its own CDP connection:

1. `Page.captureScreenshot` → downscaled to 1280×720 → WebP q72;
2. `Page.captureSnapshot{format: "mhtml"}` → inlined to self-contained HTML by
   [`mhtml.py`](browser_use_server/mhtml.py);
3. one `chat_artifacts` row, and `{"artifact_id": …}` appended to the tool result under
   `_hoover4_artifacts`.

**Capture is never a tool argument.** The completeness of the transcript must not depend on
the model's judgement — a model that forgets to screenshot the CAPTCHA it hit produces a
transcript where the failure is invisible.

**Each step has its own deadline, and this is not a detail.** A navigation that timed out
leaves the page still loading, and `captureSnapshot` then blocks until the load settles — so
a single shared budget burned all of it on the snapshot and the *screenshot never happened*,
in exactly the case where the evidence is most valuable. Now the screenshot goes first under
`CAPTURE_SCREENSHOT_TIMEOUT_SECONDS` (8), the snapshot gets
`CAPTURE_SNAPSHOT_TIMEOUT_SECONDS` (12), and a snapshot that times out still writes the row
with `status = 'failed'` and a `detail` the card shows.

Over `CAPTURE_MAX_SNAPSHOT_BYTES` (8 MB) the snapshot is dropped, the row says
`status = 'too_large'`, and the thumbnail is kept regardless.

Cost control: a capture whose `(url, document.lastModified)` matches the previous one in the
same chat **reuses the previous `body_key`** and only takes a fresh screenshot. A
`browser_click` that opened a menu does not need a second 3 MB snapshot. (Verified: a
`browser_navigate` and the `browser_snapshot` after it share one `page.html`.)

## MHTML → self-contained HTML

MHTML is a faithful archive and an unusable one — no browser renders it from an
`<iframe src>`. [`mhtml.py`](browser_use_server/mhtml.py) inlines it into one HTML document
with `data:` URIs, using `email.parser` and no new dependency.

Every `<script>`, every `on*` attribute, `<base>`, and any `javascript:` / `data:text/html`
href is stripped. The website's CSP (`default-src 'none'`) and `<iframe sandbox="">` already
prevent execution; this is defence in depth against a viewer that gets the headers wrong.

**The trap:** subresource references resolve against **the part's own `Content-Location`**,
not the document's. A stylesheet at `https://cdn.example/css/app.css` containing
`url(../img/x.png)` means `https://cdn.example/img/x.png`, nowhere near the page URL.
Getting this wrong produces a capture that renders with missing images and no error
anywhere. Covered by fixtures in `tests/test_mhtml.py`.

## Extensions

Baked into the image at build time from **pinned GitHub release URLs with their sha256
verified**, unpacked into `/opt/browser-extensions/<name>/`:

| Extension | Chrome Web Store id | Version (image `ARG`) | Source |
|---|---|---|---|
| uBlock Origin Lite | `ddkjiahejlhfcafbddmgiahcphecmpfh` | `UBOL_VERSION=2026.804.1652` | `uBlockOrigin/uBOL-home` releases |
| I still don't care about cookies | `edibdbjcniadpccecjdfdjjppcpchdlm` | `ISDCAC_VERSION=1.1.9` | `OhMyGuus/I-Still-Dont-Care-About-Cookies` releases |

Both projects publish the unpacked Chromium extension as a release asset, which is versioned
and immutable. The Chrome Web Store's CRX endpoint is neither — and a blocker that updates
itself changes what the agent sees with nothing recording it. Bump the `ARG`s and the
checksums together, and update this table.

They are loaded through nodriver's `Config.add_extension()`, which is what supplies
`--disable-features=…,DisableLoadExtensionCommandLineSwitch` and
`--enable-unsafe-extension-debugging`. **Hand-rolling `--load-extension` will appear to work
and load nothing** — Chromium disables that switch for MV3 by default.

uBlock Origin Lite runs at its default *Basic* level, which is declarativeNetRequest-only
and needs no per-site permission. That blocks network requests but does not always remove
the empty ad frames from the DOM, so a snapshot may still show ad-shaped containers. That
is expected, not a bug.

A missing or empty extensions directory is **degraded, not fatal**: the browser starts
without them and `/health` lists what it loaded.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `BROWSER_NAV_TIMEOUT` | `30` | seconds, handed to the sidecar as `--timeout-navigation` |
| `BROWSER_ACTION_TIMEOUT` | `15` | seconds, `--timeout-action` |
| `BROWSER_WINDOW_WIDTH` / `_HEIGHT` | `1280` / `720` | viewport, and the thumbnail's ceiling |
| `BROWSER_CHROMIUM_START_TIMEOUT` | `45` | how long Chromium gets to answer `/json/version` |
| `BROWSER_SIDECAR_START_TIMEOUT` | `45` | same, for playwright-mcp |
| `CAPTURE_MAX_SNAPSHOT_BYTES` | `8388608` | over this, `status = 'too_large'` |
| `CAPTURE_TIMEOUT_SECONDS` | `20` | whole-capture backstop |
| `CHAT_ARTIFACTS_ENABLED` | `true` | off means the tools still work and produce no artifacts |

`shm_size: 2gb` is set in compose. Chromium fills the default 64 MB `/dev/shm` and crashes
on content-heavy pages, and up to eight browsers multiply the demand.

## The image is ~1.5 GB and that is expected

Chromium plus its shared libraries and fonts, Node for the sidecars, and the two extensions.
Do not try to slim it by dropping the font packages — without them, text-heavy pages render
as boxes and the accessibility snapshot comes back as garbage, which is a *silent* content
failure rather than a visible one.

## Tests

```bash
docker exec hoover4-mcp-browser python -m pytest tests/ -q   # 101 tests
```

Four groups, none of which need Chromium or Node:

* **`test_urlcheck.py`** — the security boundary, tested hardest: schemes, every non-public
  address range in v4 and v6, the named services on this network, the
  public-name-with-private-record bypass, and the per-tool-argument guard in front of the
  Playwright surface.
* **`test_mhtml.py`** — the converter against fixtures rather than the live web: a page with
  `quoted-printable` CSS, one with `srcset`, one with `url()` inside an inline style, one
  whose stylesheet references a resource relative to *its own* location, and one over the
  byte cap.
* **`test_router.py`** — lifetime: per-chat isolation, the LRU cap, the idle reaper,
  idempotent close, and sidecar restart, with `chat_browser.start`/`stop` stubbed.
* **`test_netfilter.py`** — the redirect boundary: that every blocked origin is emitted in
  the one form playwright-mcp compiles into a port-tolerant glob (with that compiler
  reimplemented in the test, so a sidecar upgrade that changes it fails here rather than
  silently), and that the PAC script refuses every shape of internal target and falls
  closed. The end-to-end proof needs a real Chromium and the network and is recorded in
  `netfilter.py`'s docstring.
