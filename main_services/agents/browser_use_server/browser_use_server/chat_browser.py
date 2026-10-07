"""One chat's browser: a Chromium of its own, plus a playwright-mcp sidecar driving it.

## Why a whole browser per chat and not a context

A Chromium *browser context* per conversation is cheap and is the right isolation
boundary for cookies. It is not enough here: the agent drives the page through
**playwright-mcp**, and playwright-mcp connected with `--cdp-endpoint` shares
one browser context across every client attached to that endpoint. Measured, not assumed:
two clients, one cookie jar. `--isolated` restores isolation but makes
playwright launch its *own* browser, which loses the extensions.

So the isolation boundary sits one level lower: **one Chromium process per chat**, each
with its own `--user-data-dir` and its own sidecar bound to it. That costs about 500 MB
per live chat. `BROWSER_MAX_CONTEXTS` limits these processes, and the reaper closes idle browsers.

## The three handles

Each :class:`ChatBrowser` holds:

1. the nodriver Chromium (extensions loaded, ephemeral CDP port),
2. the `@playwright/mcp` node process bound to that CDP port,
3. an MCP :class:`fastmcp.Client` speaking to the sidecar.

The router keeps its **own** CDP connection through (1). The tab cap uses it, because CDP
allows a second client beside the sidecar's Playwright session.

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

## Site isolation

nodriver also disables `IsolateOrigins` and `site-per-process`, so each site would not get
a renderer process of its own. `launch_args` removes the two from the feature list. Chromium
reads only the last `--disable-features` switch, so `launch_args` writes one switch with
every other disabled feature of the list. A second switch would drop
`DisableLoadExtensionCommandLineSwitch`, and `--load-extension` would then load nothing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
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

#: The size of every browser window. The container entry script makes the Xvfb screen the
#: same size from the same variables, so a page reads one size for the screen and the window.
WINDOW_WIDTH = int(os.getenv("BROWSER_WINDOW_WIDTH", "1280"))
WINDOW_HEIGHT = int(os.getenv("BROWSER_WINDOW_HEIGHT", "720"))

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


#: A folder for the Chromium log of each browser, for diagnosis. Unset means no log. When
#: set, Chromium gets `--enable-logging=stderr` and `--v=<BROWSER_CHROMIUM_LOG_V>`, and its
#: stderr goes to one file per browser in this folder.
CHROMIUM_LOG_DIR = os.getenv("BROWSER_CHROMIUM_LOG_DIR", "")
CHROMIUM_LOG_VERBOSITY = int(os.getenv("BROWSER_CHROMIUM_LOG_V", "0"))

#: The WebRTC address policy of every browser. See `write_profile_prefs()`.
WEBRTC_POLICY = "disable_non_proxied_udp"


def write_profile_prefs(profile_dir: str) -> None:
    """Write the preferences of a new profile, before Chromium starts with it.

    WebRTC may then send UDP only through a proxy that carries UDP, and no proxy here does.
    Without it, a page in a Tor context of `read_page` sent STUN packets directly. It learned
    the public address of the host, and it sent datagrams to a loopback port. A CDP browser
    context reads this preference through the profile. The switch
    `--force-webrtc-ip-handling-policy` does not do this: Chromium 154 gave it to no
    renderer process, and a page still got the public address.
    """
    import json

    folder = os.path.join(profile_dir, "Default")
    os.makedirs(folder, exist_ok=True)
    prefs = {"webrtc": {"ip_handling_policy": WEBRTC_POLICY,
                        "multiple_routes_enabled": False,
                        "nonproxied_udp_enabled": False}}
    with open(os.path.join(folder, "Preferences"), "w", encoding="utf-8") as fh:
        json.dump(prefs, fh)

#: The largest disk cache of one browser. See `start()`.
DISK_CACHE_BYTES = 64 * 1024 * 1024

#: The prefix of every chat's profile folder under the temporary directory.
PROFILE_PREFIX = "h4browser-"


def sweep_leftover_profiles(root: str | None = None) -> int:
    """Remove every chat profile folder under `root`. Returns how many went.

    Called once at server start, before any browser exists, so no folder found here
    belongs to a live browser.
    """
    root = root or tempfile.gettempdir()
    removed = 0
    try:
        names = os.listdir(root)
    except OSError as exc:
        log.warning("could not list %s for leftover profiles: %s", root, exc)
        return 0
    for name in names:
        path = os.path.join(root, name)
        if not name.startswith(PROFILE_PREFIX) or not os.path.isdir(path):
            continue
        try:
            shutil.rmtree(path)
            removed += 1
        except OSError as exc:
            log.warning("leftover profile %s not removed: %s", path, exc)
    return removed


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
    #: Serialises the `browser_*` calls of one chat, because they act on the sidecar's
    #: current tab. A global lock would make the chats queue behind each other for no
    #: safety benefit.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def busy(self) -> bool:
        """True while a call of this chat is in flight."""
        return self.lock.locked()

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


#: The disabled features that `launch_args` removes, so site isolation stays on.
SITE_ISOLATION_FEATURES = frozenset({"IsolateOrigins", "site-per-process"})


def launch_args(args: list[str]) -> list[str]:
    """`args` with one `--disable-features` switch, at the place of the first one. It holds
    every feature of the switches of `args`, in order, without `SITE_ISOLATION_FEATURES`.
    See the module text."""
    prefix = "--disable-features="
    features: list[str] = []
    out: list[str] = []
    place = -1
    for arg in args:
        if not arg.startswith(prefix):
            out.append(arg)
            continue
        if place < 0:
            place = len(out)
        for name in arg[len(prefix):].split(","):
            name = name.strip()
            if name and name not in features and name not in SITE_ISOLATION_FEATURES:
                features.append(name)
    if place >= 0 and features:
        out.insert(place, prefix + ",".join(features))
    return out


def browser_config(profile_dir: str, cdp_port: int):
    """The nodriver `Config` of one browser, and the extension folders it loads.

    Chromium runs headed, on the X display that `DISPLAY` names. It sends its own user
    agent and client hints, so the two agree. The window fills the Xvfb screen, so the
    screen size and the window size that a page reads agree too.
    """
    import nodriver

    config = nodriver.Config(
        headless=False,
        user_data_dir=profile_dir,
        browser_executable_path=os.getenv("BROWSER_EXECUTABLE") or None,
        # `sandbox=False` is how nodriver spells `--no-sandbox`; passing the flag through
        # `add_argument` raises, because Config owns it. Required in a container:
        # Chromium's sandbox needs privileges the image does not have and it exits
        # immediately without this.
        sandbox=False,
        host="127.0.0.1",
        port=cdp_port,
    )
    # nodriver adds `--remote-allow-origins=*`. With it, a script in any page may open the
    # CDP WebSocket of its own browser, and then control every tab of it. Without the flag,
    # Chromium refuses a CDP WebSocket whose request has an `Origin` header. nodriver and
    # the sidecar send no `Origin` header, so they still connect.
    config._default_browser_args = [
        arg for arg in config._default_browser_args
        if not arg.startswith("--remote-allow-origins")
    ]
    # /dev/shm is 64 MB by default and Chromium fills it on content-heavy pages. compose
    # raises it, but a browser per chat multiplies the demand, so the flag stays as well.
    # With this flag Chromium puts its shared memory files in /tmp, so the launcher mounts
    # /tmp as a tmpfs. On a disk, those writes made parallel tabs wait for I/O.
    config.add_argument("--disable-dev-shm-usage")
    # The profile is in /tmp too. This limits the disk cache of each browser in that tmpfs.
    config.add_argument(f"--disk-cache-size={DISK_CACHE_BYTES}")
    # Xvfb has no GPU. Chromium draws in software, and a page gets no WebGL context.
    config.add_argument("--disable-gpu")
    config.add_argument("--window-position=0,0")
    config.add_argument(f"--window-size={WINDOW_WIDTH},{WINDOW_HEIGHT}")
    # Every window fills the screen, so each new window covers the older ones. On X11,
    # Chromium marks the page of a covered window `hidden` and slows its timers and its
    # rendering. Measured on Xvfb: without this flag, a covered window reports `hidden`.
    config.add_argument("--disable-backgrounding-occluded-windows")
    # The line that survives a redirect. Consulted by Chromium for every request in every
    # tab, before a connection is opened, which is the coverage a tool-argument check
    # cannot have. See :mod:`.netfilter`.
    config.add_argument(f"--proxy-pac-url={netfilter.pac_data_url()}")
    extensions = extension_paths()
    for path in extensions:
        # `add_extension` is what supplies the two feature flags MV3 extensions need. See
        # the module docstring. It does NOT add --load-extension; nodriver's own `start()`
        # does that, and we are not calling it.
        config.add_extension(path)
    if extensions:
        # nodriver's own `Browser.start()` would add this, but we are not calling it (see
        # `start()`). `start()` clears `_extensions` after the launch, which stops
        # `Browser.create` adding a duplicate to a config we have already rendered.
        config.add_argument("--load-extension=%s" % ",".join(str(p) for p in extensions))
    return config, extensions


async def start(session_id: str, sidecar: bool = True) -> ChatBrowser:
    """Launch Chromium and, with `sidecar`, its sidecar for one chat. Raises on failure.

    A special session (`special_browser`) passes `sidecar=False`. Its browser gets the
    same launch settings and extensions.

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

    if not os.environ.get("DISPLAY"):
        # Chromium runs headed on the Xvfb display of the container entry script. Without
        # a display it exits at once, and the CDP probe would only report a timeout.
        raise BrowserSpawnFailed(
            "DISPLAY is not set. Start the server with its container display script."
        )
    chat = ChatBrowser(session_id=session_id)
    chat.profile_dir = tempfile.mkdtemp(prefix=f"{PROFILE_PREFIX}{session_id[:24]}-")
    chat.cdp_port = _free_port()
    write_profile_prefs(chat.profile_dir)
    config, extensions = browser_config(chat.profile_dir, chat.cdp_port)

    try:
        await _launch_chromium(chat, config)
        config._extensions = []
        chat.browser = await nodriver.Browser.create(config)
    except BaseException as exc:
        await _stop_chromium(chat)
        await _cleanup_profile(chat)
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise BrowserSpawnFailed(f"chromium did not start: {exc}") from exc

    if sidecar:
        try:
            await _start_sidecar(chat)
        except BaseException:
            await stop(chat)
            raise

    log.info(
        "chat %s: chromium up (cdp %s), %s, %d extensions",
        session_id, _cdp_endpoint(chat),
        f"sidecar on 127.0.0.1:{chat.sidecar_port}" if sidecar else "no sidecar",
        len(extensions),
    )
    return chat


async def _launch_chromium(chat: ChatBrowser, config) -> None:
    """Start the browser process and wait for its CDP endpoint to answer."""
    args = launch_args(list(config()))
    # Chromium in a container writes a continuous stream of D-Bus and GCM errors to
    # stderr. Left on a pipe with nobody reading, that pipe fills and the browser blocks on
    # write, a wedge that looks exactly like a hung page. So stderr goes to DEVNULL, or to
    # a file when `BROWSER_CHROMIUM_LOG_DIR` asks for the log. A browser that will not
    # start is caught by the port probe below.
    log_file = None
    if CHROMIUM_LOG_DIR:
        os.makedirs(CHROMIUM_LOG_DIR, exist_ok=True)
        path = os.path.join(CHROMIUM_LOG_DIR,
                            f"{chat.session_id[:24]}-{chat.cdp_port}-{int(time.time())}.log")
        log_file = open(path, "ab")  # noqa: SIM115 - the child process holds it open
        args += ["--enable-logging=stderr", f"--v={CHROMIUM_LOG_VERBOSITY}"]
        log.info("chat %s: chromium log in %s", chat.session_id, path)
    try:
        chat.chromium = await asyncio.create_subprocess_exec(
            str(config.browser_executable_path),
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=log_file if log_file is not None else asyncio.subprocess.DEVNULL,
            # Its own process group, so `_stop_chromium` ends the renderers and helpers
            # too. Ending only the parent leaves children that write into the profile.
            start_new_session=True,
        )
    finally:
        if log_file is not None:
            log_file.close()
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


def _signal_group(pgid: int, sig: int) -> bool:
    """Send `sig` to a process group. False when the group no longer exists."""
    try:
        os.killpg(pgid, sig)
        return True
    except ProcessLookupError:
        return False


def _group_alive(pgid: int) -> bool:
    return _signal_group(pgid, 0)


async def _stop_chromium(chat: ChatBrowser) -> None:
    """End the Chromium process group: the browser and every child it started."""
    proc, chat.chromium = chat.chromium, None
    if proc is None:
        return
    pgid = proc.pid
    _signal_group(pgid, signal.SIGTERM)
    try:
        await asyncio.wait_for(proc.wait(), timeout=8)
    except asyncio.TimeoutError:
        pass
    deadline = time.monotonic() + 2
    while _group_alive(pgid) and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    if _group_alive(pgid):
        _signal_group(pgid, signal.SIGKILL)
    if proc.returncode is None:
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
    own, losing the extensions. `--cdp-endpoint` is what
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
        # No `--headless` and no `--viewport-size`: the sidecar launches no browser, and
        # without a viewport override the page size follows the window, as in a person's
        # browser.
        "--no-sandbox",
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
    await _cleanup_profile(chat)
    log.info("chat %s: browser torn down", chat.session_id)


async def _cleanup_profile(chat: ChatBrowser) -> None:
    """Remove the profile folder. Retries, because a child can still write into it."""
    last: OSError | None = None
    if chat.profile_dir:
        for _attempt in range(3):
            try:
                shutil.rmtree(chat.profile_dir)
                last = None
                break
            except FileNotFoundError:
                last = None
                break
            except OSError as exc:
                last = exc
                await asyncio.sleep(0.5)
        if last is not None:
            log.warning(
                "chat %s: profile %s not removed: %s", chat.session_id, chat.profile_dir, last
            )
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
