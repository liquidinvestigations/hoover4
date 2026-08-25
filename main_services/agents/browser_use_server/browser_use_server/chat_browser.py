"""One chat's browser: a Chromium of its own, plus a playwright-mcp sidecar driving it.

## Why a whole browser per chat and not a context

A Chromium *browser context* per conversation is cheap and is the right isolation
boundary for cookies. It is not enough here: the agent drives the page through
**playwright-mcp**, and playwright-mcp connected with `--cdp-endpoint` shares
one browser context across every client attached to that endpoint. Measured, not assumed:
two clients, one cookie jar. `--isolated` restores isolation but makes
playwright launch its *own* browser, which loses the extensions and the CDP handle this
module needs for capture.

So the isolation boundary sits one level lower: **one Chromium process per chat**, each
with its own `--user-data-dir` and its own sidecar bound to it. That costs a few hundred
MB per live chat, which is why `BROWSER_MAX_CONTEXTS` is 8 and the reaper closes idle
contexts quickly.

## The three handles

Each :class:`ChatBrowser` holds:

1. the nodriver Chromium (extensions loaded, ephemeral CDP port),
2. the `@playwright/mcp` node process bound to that CDP port,
3. an MCP :class:`fastmcp.Client` speaking to the sidecar.

The router keeps its **own** CDP connection through (1). That is what makes capture
possible without asking the model to request it: the sidecar owns the Playwright session,
but CDP allows a second client, and `Page.captureScreenshot` / `Page.captureSnapshot` need
nothing Playwright is holding exclusively.

## What the browser may reach

Chromium is launched with a PAC script (:mod:`.netfilter`) that routes every internal
host and private address to a proxy that does not exist. That is the only layer that sees
a redirect: :mod:`.urlcheck` inspects tool arguments, and the sidecar's
`--blocked-origins` is documented as affecting neither redirects nor security.

## Extensions

Loaded through nodriver's `Config.add_extension()`, which supplies
`--disable-features=…DisableLoadExtensionCommandLineSwitch` and
`--enable-unsafe-extension-debugging`. Hand-rolling `--load-extension` appears to work and
loads nothing. Chromium has disabled that switch for MV3 by default.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import socket
import tempfile
import time
from dataclasses import dataclass, field

from browser_use_server import netfilter

log = logging.getLogger(__name__)

#: Pinned in the image. Never `@latest` at runtime: a silently updated sidecar changes
#: the whole tool surface the agent sees, mid-conversation.
PLAYWRIGHT_MCP_BIN = os.getenv("PLAYWRIGHT_MCP_BIN", "/opt/playwright-mcp/node_modules/.bin/playwright-mcp")

#: Directory holding the unpacked extensions, one subdirectory each. Empty or missing
#: means the browser runs without them. Degraded (ads and consent walls come back), never
#: fatal.
EXTENSIONS_DIR = os.getenv("BROWSER_EXTENSIONS_DIR", "/opt/browser-extensions")

VIEWPORT_WIDTH = int(os.getenv("BROWSER_WINDOW_WIDTH", "1280"))
VIEWPORT_HEIGHT = int(os.getenv("BROWSER_WINDOW_HEIGHT", "720"))

#: Navigation and action deadlines handed to the sidecar, in milliseconds.
NAV_TIMEOUT_MS = int(float(os.getenv("BROWSER_NAV_TIMEOUT", "30")) * 1000)
ACTION_TIMEOUT_MS = int(float(os.getenv("BROWSER_ACTION_TIMEOUT", "15")) * 1000)

#: How long to wait for the sidecar's HTTP port to answer before calling the spawn failed.
SIDECAR_START_TIMEOUT = float(os.getenv("BROWSER_SIDECAR_START_TIMEOUT", "45"))

#: How long Chromium gets to answer /json/version. Generous: two MV3 extensions add
#: several seconds to a cold start, and nodriver's own ~2.7 s budget is what made this
#: module launch the browser itself.
CHROMIUM_START_TIMEOUT = float(os.getenv("BROWSER_CHROMIUM_START_TIMEOUT", "45"))

#: Internal hosts the sidecar refuses as a *second* line of defence. The router's urlcheck
#: is the first line for tool arguments and :mod:`.netfilter`'s PAC script is the one that
#: survives a redirect; Playwright documents `--blocked-origins` as neither a security
#: boundary nor redirect-aware, so it is exactly a third opinion. Default comes from
#: urlcheck's own deny-list. A second literal list here is what let the two drift.
BLOCKED_ORIGIN_HOSTS = os.getenv("BROWSER_BLOCKED_ORIGINS", netfilter.DEFAULT_BLOCKED_HOSTS)


class BrowserSpawnFailed(RuntimeError):
    """A chat's browser or its sidecar could not be started."""


def _free_port() -> int:
    """An ephemeral port, chosen by the kernel and released immediately.

    There is a race between releasing it and the child binding it. It is tolerable here:
    the alternative is a fixed port range that collides between chats, which fails the
    same way but reproducibly and at a worse moment.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def extension_paths() -> list[str]:
    """Unpacked extension directories, in load order."""
    if not os.path.isdir(EXTENSIONS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(EXTENSIONS_DIR)):
        path = os.path.join(EXTENSIONS_DIR, name)
        if os.path.isfile(os.path.join(path, "manifest.json")):
            out.append(path)
        else:
            log.warning("%s has no manifest.json; not loading it as an extension", path)
    return out


@dataclass
class ChatBrowser:
    """Everything one conversation browses with."""

    session_id: str
    profile_dir: str = ""
    browser: object | None = None
    #: The browser process. Ours, not nodriver's. See `start()`.
    chromium: asyncio.subprocess.Process | None = None
    sidecar: asyncio.subprocess.Process | None = None
    sidecar_port: int = 0
    cdp_port: int = 0
    client: object | None = None
    last_used: float = field(default_factory=time.monotonic)
    calls: int = 0
    sidecar_restarts: int = 0
    #: One chat's calls are serialised. The old global lock is gone, with one browser per
    #: chat, a global lock would make eight conversations queue behind each other for no
    #: safety benefit.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def touch(self) -> None:
        self.last_used = time.monotonic()
        self.calls += 1

    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_used

    def describe(self) -> dict:
        return {
            "session_id": self.session_id,
            "calls": self.calls,
            "idle_seconds": round(self.idle_seconds(), 1),
            "sidecar_port": self.sidecar_port,
            "cdp_port": self.cdp_port,
            "sidecar_alive": self.sidecar is not None and self.sidecar.returncode is None,
            "chromium_alive": self.chromium is not None and self.chromium.returncode is None,
            "sidecar_restarts": self.sidecar_restarts,
            "has_browser": self.browser is not None,
        }


async def start(session_id: str) -> ChatBrowser:
    """Launch Chromium and its sidecar for one chat. Raises on failure.

    **Chromium is launched here, not by nodriver.** Two reasons, both learned the hard
    way:

    * nodriver treats an explicitly configured `host`+`port` as *"attach to a browser that
      is already running"* and skips the launch entirely, and the port has to be
      configured, because the sidecar must be told it. The symptom is a confident
      "Failed to connect to browser / you may be running as root" against a Chromium that
      was never started.
    * nodriver's own launch gives the browser only ~2.7 s to answer `/json/version`.
      Chromium with two MV3 extensions takes 5-6 s in this image, so even without the
      first problem it would have raced.

    `Config` is still what builds the argument list (it owns the extension flags), but
    the process and its pipes are ours.
    """
    import nodriver

    chat = ChatBrowser(session_id=session_id)
    chat.profile_dir = tempfile.mkdtemp(prefix=f"h4browser-{session_id[:24]}-")
    chat.cdp_port = _free_port()

    config = nodriver.Config(
        headless=True,
        user_data_dir=chat.profile_dir,
        browser_executable_path=os.getenv("BROWSER_EXECUTABLE") or None,
        # `sandbox=False` is how nodriver spells `--no-sandbox`; passing the flag through
        # `add_argument` raises, because Config owns it. Required in a container:
        # Chromium's sandbox needs privileges the image does not have and it exits
        # immediately without this.
        sandbox=False,
        host="127.0.0.1",
        port=chat.cdp_port,
    )
    # /dev/shm is 64 MB by default and Chromium fills it on content-heavy pages. compose
    # raises it, but a browser per chat multiplies the demand, so the flag stays as well.
    config.add_argument("--disable-dev-shm-usage")
    config.add_argument("--disable-gpu")
    config.add_argument(f"--window-size={VIEWPORT_WIDTH},{VIEWPORT_HEIGHT}")
    # The line that survives a redirect. Consulted by Chromium for every request in every
    # tab, before a connection is opened, which is the coverage a tool-argument check
    # cannot have. See :mod:`.netfilter`.
    config.add_argument(f"--proxy-pac-url={netfilter.pac_data_url()}")
    extensions = extension_paths()
    for path in extensions:
        # `add_extension` is what supplies the two feature flags MV3 extensions need in
        # headless Chromium. See the module docstring. It does NOT add --load-extension;
        # nodriver's own `start()` does that, and we are not calling it.
        config.add_extension(path)
    if extensions:
        # nodriver's own `Browser.start()` would add this, but we are not calling it (see
        # the docstring). Clearing `_extensions` afterwards stops `Browser.create` adding
        # a duplicate to a config we have already rendered.
        config.add_argument("--load-extension=%s" % ",".join(str(p) for p in extensions))

    try:
        await _launch_chromium(chat, config)
        config._extensions = []
        chat.browser = await nodriver.Browser.create(config)
    except Exception as exc:
        await _stop_chromium(chat)
        _cleanup_profile(chat)
        raise BrowserSpawnFailed(f"chromium did not start: {exc}") from exc

    try:
        await _start_sidecar(chat)
    except Exception:
        await stop(chat)
        raise

    log.info(
        "chat %s: chromium up (cdp %s), sidecar on 127.0.0.1:%d, %d extensions",
        session_id, _cdp_endpoint(chat), chat.sidecar_port, len(extensions),
    )
    return chat


async def _launch_chromium(chat: ChatBrowser, config) -> None:
    """Start the browser process and wait for its CDP endpoint to answer."""
    args = list(config())
    chat.chromium = await asyncio.create_subprocess_exec(
        str(config.browser_executable_path),
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        # Chromium in a container writes a continuous stream of D-Bus and GCM errors to
        # stderr. Left on a pipe with nobody reading, that pipe fills and the browser
        # blocks on write, a wedge that looks exactly like a hung page. DEVNULL is the
        # cheap correct answer; the messages are noise, and a browser that will not start
        # is caught by the port probe below rather than by reading its log.
        stderr=asyncio.subprocess.DEVNULL,
    )
    if not await _wait_for_cdp(chat.cdp_port, CHROMIUM_START_TIMEOUT):
        raise BrowserSpawnFailed(
            f"chromium did not answer on 127.0.0.1:{chat.cdp_port} within "
            f"{CHROMIUM_START_TIMEOUT:g}s"
        )


async def _wait_for_cdp(port: int, timeout: float) -> bool:
    """Poll `/json/version` until the browser is really ready.

    An open TCP port is not enough here: Chromium accepts the connection slightly before
    the DevTools endpoint answers, and attaching in that window fails.
    """
    import json
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout

    def probe() -> bool:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=2
            ) as response:
                return bool(json.loads(response.read()).get("webSocketDebuggerUrl"))
        except (urllib.error.URLError, OSError, ValueError):
            return False

    while time.monotonic() < deadline:
        if await asyncio.to_thread(probe):
            return True
        await asyncio.sleep(0.4)
    return False


async def _stop_chromium(chat: ChatBrowser) -> None:
    proc, chat.chromium = chat.chromium, None
    if proc is None or proc.returncode is not None:
        return
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=8)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()


def _cdp_endpoint(chat: ChatBrowser) -> str:
    """The `http://127.0.0.1:<port>` this chat's Chromium is listening on."""
    port = chat.cdp_port or getattr(getattr(chat.browser, "config", None), "port", 0)
    if not port:
        raise BrowserSpawnFailed("could not determine chromium's CDP port")
    return f"http://127.0.0.1:{port}"


async def _start_sidecar(chat: ChatBrowser) -> None:
    """Spawn `@playwright/mcp` bound to this chat's Chromium and wait for its port.

    `--isolated` is deliberately absent: it would make playwright launch a browser of its
    own, losing the extensions and the CDP handle capture needs. `--cdp-endpoint` is what
    binds it to the Chromium above, and the per-chat *process* is what supplies the
    isolation `--cdp-endpoint` alone does not.
    """
    chat.sidecar_port = _free_port()
    args = [
        PLAYWRIGHT_MCP_BIN,
        "--cdp-endpoint", _cdp_endpoint(chat),
        "--port", str(chat.sidecar_port),
        "--host", "127.0.0.1",
        # NOTE: no `--allowed-hosts`. The sidecar's default is "the host the server is
        # bound to", spelled `localhost`, WITH the port, and compared against the request's
        # Host header. Which is why the client URL below says `localhost` and not
        # `127.0.0.1`: the same address by IP comes back `403 Access is only allowed at
        # localhost:<port>`.
        "--headless",
        "--no-sandbox",
        "--viewport-size", f"{VIEWPORT_WIDTH},{VIEWPORT_HEIGHT}",
        "--timeout-navigation", str(NAV_TIMEOUT_MS),
        "--timeout-action", str(ACTION_TIMEOUT_MS),
        # Coordinate-based clicking, for pages whose accessibility tree is useless.
        "--caps", "vision",
        # Expanded to `scheme://host:*` origins: the bare hostnames this used to pass
        # compiled to `*://host/**`, which matches no URL that carries a port, and every
        # service on this network has one. See `netfilter.blocked_origins`.
        "--blocked-origins", netfilter.blocked_origins(BLOCKED_ORIGIN_HOSTS),
    ]
    chat.sidecar = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    asyncio.create_task(_drain(chat))

    if not await _wait_for_port(chat.sidecar_port, SIDECAR_START_TIMEOUT):
        raise BrowserSpawnFailed(
            f"playwright-mcp did not answer on 127.0.0.1:{chat.sidecar_port} "
            f"within {SIDECAR_START_TIMEOUT:g}s"
        )

    from fastmcp import Client

    # `localhost`, not `127.0.0.1`, see the note on --allowed-hosts above.
    chat.client = Client(f"http://localhost:{chat.sidecar_port}/mcp")
    await chat.client.__aenter__()


async def _drain(chat: ChatBrowser) -> None:
    """Forward the sidecar's output into our log.

    Without this the pipe fills, the node process blocks on write, and the whole chat
    wedges with no error anywhere, in a failure mode that looks exactly like a hung page.
    """
    proc = chat.sidecar
    if proc is None or proc.stdout is None:
        return
    try:
        async for line in proc.stdout:
            text = line.decode("utf-8", "replace").rstrip()
            if text:
                log.debug("sidecar[%s] %s", chat.session_id, text)
    except Exception:  # noqa: BLE001 - draining must never take the server down
        log.debug("sidecar log drain for %s ended", chat.session_id)


async def _wait_for_port(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return True
        except OSError:
            await asyncio.sleep(0.25)
    return False


async def restart_sidecar(chat: ChatBrowser) -> None:
    """Replace a dead sidecar, keeping the same Chromium (and therefore the cookies)."""
    log.warning("chat %s: restarting playwright-mcp sidecar", chat.session_id)
    chat.sidecar_restarts += 1
    await _stop_sidecar(chat)
    await _start_sidecar(chat)


def sidecar_alive(chat: ChatBrowser) -> bool:
    return chat.sidecar is not None and chat.sidecar.returncode is None


def chromium_alive(chat: ChatBrowser) -> bool:
    return chat.chromium is not None and chat.chromium.returncode is None


async def _stop_sidecar(chat: ChatBrowser) -> None:
    if chat.client is not None:
        try:
            await chat.client.__aexit__(None, None, None)
        except Exception as exc:  # noqa: BLE001 - already tearing down
            log.debug("sidecar client close failed: %s", exc)
        chat.client = None
    proc, chat.sidecar = chat.sidecar, None
    if proc is None or proc.returncode is not None:
        return
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()


async def stop(chat: ChatBrowser) -> None:
    """Tear the whole chat down: sidecar, Chromium, profile directory."""
    await _stop_sidecar(chat)
    browser, chat.browser = chat.browser, None
    if browser is not None:
        try:
            # Closes nodriver's websocket. It does not own the process (we launched it),
            # so `_stop_chromium` below is what actually ends it.
            browser.stop()
        except Exception as exc:  # noqa: BLE001 - we are already in the teardown path
            log.debug("nodriver stop for %s: %s", chat.session_id, exc)
    await _stop_chromium(chat)
    _cleanup_profile(chat)
    log.info("chat %s: browser torn down", chat.session_id)


def _cleanup_profile(chat: ChatBrowser) -> None:
    if chat.profile_dir and os.path.isdir(chat.profile_dir):
        shutil.rmtree(chat.profile_dir, ignore_errors=True)
    chat.profile_dir = ""


async def enforce_tab_cap(chat: ChatBrowser, max_tabs: int) -> int:
    """Close this chat's oldest page tabs past `max_tabs`. Returns how many went.

    A model that opens a tab per search result would otherwise exhaust the container
    through a single conversation, and unlike the browser cap, nothing else would notice:
    the tabs are inside one Chromium the router already counts as one session.

    The **oldest** go, not the newest: the tab the agent is looking at is the one it just
    opened. Never raises, a tab that will not close is not worth failing a tool call for.
    """
    browser = chat.browser
    if browser is None or max_tabs < 1:
        return 0
    try:
        await browser.update_targets()
        pages = [
            t for t in getattr(browser, "tabs", [])
            if getattr(getattr(t, "target", None), "type_", "") == "page"
        ]
    except Exception as exc:  # noqa: BLE001
        log.debug("could not enumerate tabs for %s: %s", chat.session_id, exc)
        return 0

    excess = len(pages) - max_tabs
    if excess <= 0:
        return 0

    closed = 0
    for tab in pages[:excess]:
        try:
            await tab.close()
            closed += 1
        except Exception as exc:  # noqa: BLE001
            log.debug("could not close a tab for %s: %s", chat.session_id, exc)
    if closed:
        log.info(
            "chat %s had %d tabs (cap %d); closed the %d oldest",
            chat.session_id, len(pages), max_tabs, closed,
        )
    return closed
