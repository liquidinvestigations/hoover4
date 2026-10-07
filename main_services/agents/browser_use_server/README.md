# Browser tools

The browser server provides interactive tools and `read_page` through MCP.
Each agent run owns its interactive browser, cookies, tabs, and captures.
The router refuses a new interactive browser when every permitted browser has an active call.
Release and idle expiry close the browser and remove its temporary profile.

## Independent queues

Page reads use a separate reader browser and bounded tab queue.
Metasearch source fetches use another browser and bounded tab queue.
Interactive browser calls retain their own run locks and browser limit.
A stalled page read does not occupy an interactive browser.

| Setting | Default | Behavior |
|---|---|---|
| `BROWSER_MAX_CONTEXTS` | `16` | This setting limits interactive browsers. |
| `READER_TAB_SLOTS` | `4` | This setting limits concurrent page reads. |
| `METASEARCH_TAB_SLOTS` | `2` | This setting limits concurrent metasearch source fetches. |
| `SPECIAL_BROWSER_MAX_WAITING` | `32` | This setting limits waiting requests in each shared browser queue. |
| `READ_PAGE_CALL_TIMEOUT_S` | `180` | This setting limits the complete page-read call. |
| `BROWSER_IDLE_SECONDS` | `900` | This setting controls interactive browser idle expiry. |
| `BROWSER_MAX_TABS_PER_CHAT` | `6` | This setting limits tabs in each interactive browser. |

Set deployment values in `hoover4.ini`.
The deployment generates the corresponding environment variables.

## Browser lifecycle

Chromium runs with a private Xvfb display and its native user agent and client hints.
The image pins Playwright MCP and verifies downloaded extension checksums.
The reader loads uBlock Origin Lite into its isolated contexts when Chromium supports this operation.
Interactive browsers also load the cookie consent extension.
Chromium output uses a file or the null device, so an unread output pipe cannot block Chromium.
Shutdown closes subprocess groups and removes temporary profiles.
Shared browser watchdogs replace failed browsers and release affected calls.

## Page reads

`read_page` reads independent URLs concurrently and preserves their input order.
Each route attempt uses a fresh browser context.
A public-destination SOCKS relay validates direct DNS results and connects to the validated address.
Private destinations remain refused after redirects and during subresource requests.

The Markdown extractor removes navigation, forms, scripts, media, and unrelated controls.
It preserves source lists, package metadata, tables, captions, code, and headings.
Links remain enabled unless the caller passes `links: false`.
HTTP error pages and unresolved bot checks provide no source text.
Each URL reports its own failure without discarding completed reads.

The reader retains text for versioned offset and literal-find continuations.
Cache entries belong to one caller and agent run.
A global character limit bounds the retained text across callers.
The cache also preserves the selected route and link mode.
PDF reads retain the page and byte limits defined in `read_page.py`.
Captures use the attempt's explicit tab and retain caller and run ownership.
The shared artifact writer applies screenshot and snapshot size limits.

## Source fetches and Tor

The internal source-fetch route serves metasearch through its separate browser queue.
It requires the token from `BROWSER_FETCH_TOKEN_FILE`.
An empty token file disables this route.
The route accepts bounded GET requests and returns raw or rendered source content.
It does not appear in the model's tool catalogue.

Tor fallback remains disabled until the deployment enables it.
Configured routes retry blocked or failed public reads within the complete call deadline.
Each attempt uses a separate context and SOCKS authentication identity.
The result records the selected route and earlier failed attempts.
The deployment's Tor clients have no published ports or control interface.
See the configuration reference for the deployment switches and token file setting.

## Verification

The image includes unit tests for queues, ownership, cancellation, extraction contracts, and source fetches.
Unit tests use fake browser connections and local SOCKS servers.
Actual Chromium and live source verification provide separate runtime evidence.

## Capture contracts

Interactive `browser_snapshot` and `browser_take_screenshot` calls produce captures, including failed calls.
Other interactive actions do not produce captures.
A fresh page read captures its selected attempt.
A cached continuation produces no new capture.
Each explicit capture writes a separate artifact identity and object.

The screenshot runs before the MHTML snapshot and has its own deadline.
A failed snapshot preserves an available thumbnail and records its failure.
An oversized snapshot records `too_large` and preserves the thumbnail.
The MHTML converter resolves resources against each part's source location.
It removes executable content before the website displays the HTML in its restricted iframe.

Tool results include owned artifact identifiers in `_hoover4_artifacts` and the `[hoover4:artifacts]` marker.
The marker records a failed tool result because transcript text alone cannot establish success.
Unreadable sidecar snapshot file links become instructions to request readable page content.

## Image dependencies

The image pins Playwright MCP and these extensions.
Change each extension version and its checksum together.

| Extension | Version | Source |
|---|---|---|
| uBlock Origin Lite | `2026.804.1652` | The image downloads the `uBlockOrigin/uBOL-home` release. |
| I still don't care about cookies | `1.1.9` | The image downloads the `OhMyGuus/I-Still-Dont-Care-About-Cookies` release. |

Missing extensions report degraded browser operation without preventing startup.
The interactive sidecar connects through its required loopback hostname spelling.
Its allowed-host validation also compares the ephemeral listener port.
