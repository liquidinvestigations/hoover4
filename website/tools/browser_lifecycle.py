"""Start an owned browser with bounded readiness and awaited cleanup."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO


@dataclass
class BrowserOwner:
    process: Any
    profile: Any
    log: BinaryIO
    browser: Any = None
    closed: bool = False
    process_group: int | None = None


async def stop_process(process: Any, timeout: float = 10.0, process_group: int | None = None) -> None:
    """Await process exit, using kill only after termination times out."""
    if process_group is not None:
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if process.returncode is not None:
        await process.wait()
    else:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await asyncio.wait_for(process.wait(), timeout)
    if process_group is not None:
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass


async def close_owner(owner: BrowserOwner) -> None:
    """Close connections and reap the process before removing its profile."""
    if owner.closed:
        return
    errors = []
    if owner.browser is not None:
        connections = [*owner.browser.tabs, owner.browser]
        results = await asyncio.gather(*[
            asyncio.wait_for(connection.aclose(), 5.0) for connection in connections
        ], return_exceptions=True)
        errors.extend(result for result in results if isinstance(result, Exception))
    try:
        await stop_process(owner.process, process_group=owner.process_group)
    except Exception as error:
        errors.append(error)
    finally:
        owner.log.close()
    if owner.process.returncode is not None:
        for attempt in range(4):
            try:
                owner.profile.cleanup()
                break
            except OSError:
                if attempt == 3:
                    raise
                await asyncio.sleep(0.1 * (attempt + 1))
        owner.closed = True
    if errors:
        raise ExceptionGroup("Browser cleanup failed", errors)


def read_version(url: str) -> bool:
    with urllib.request.urlopen(url, timeout=1.0) as response:
        return bool(json.load(response).get("webSocketDebuggerUrl"))


async def start_browser(log_path: Path, browser_args: list[str], timeout: float = 45.0):
    """Wait for Chromium readiness before attaching the automation connection."""
    import nodriver

    task = asyncio.current_task()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
    profile = tempfile.TemporaryDirectory(prefix="hoover4-browser-")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("wb")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    config = nodriver.Config(
        headless=True, sandbox=False, user_data_dir=profile.name,
        host="127.0.0.1", port=port, browser_args=browser_args,
    )
    try:
        process = await asyncio.create_subprocess_exec(
            config.browser_executable_path, *config(),
            stdin=asyncio.subprocess.DEVNULL, stdout=log, stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
    except BaseException:
        log.close()
        profile.cleanup()
        raise
    owner = BrowserOwner(process=process, profile=profile, log=log, process_group=process.pid)
    try:
        deadline = time.monotonic() + timeout
        last_error = None
        while time.monotonic() < deadline:
            if process.returncode is not None:
                raise RuntimeError(f"Chromium exited with {process.returncode}; see {log_path.name}")
            try:
                if await asyncio.to_thread(read_version, f"http://127.0.0.1:{port}/json/version"):
                    break
            except Exception as error:
                last_error = error
            await asyncio.sleep(0.1)
        else:
            raise TimeoutError(f"Chromium did not become ready within {timeout:g}s; see {log_path.name}") from last_error
        browser = nodriver.Browser(config)
        owner.browser = browser
        await asyncio.wait_for(browser.start(), timeout)
        browser._qa_owner = owner
        return browser
    except BaseException:
        await close_owner(owner)
        raise


async def stop_browser(browser) -> None:
    """Close only the browser process owned by this capture run."""
    await close_owner(browser._qa_owner)


def stop_run(directory: Path, timeout: float = 25.0) -> None:
    """Stop runner processes whose script belongs to this exact run directory."""
    scripts = {str(directory / name).encode() for name in ("capture_screenshots.py", "chat_observer.py")}
    owned = []
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            arguments = (process / "cmdline").read_bytes().split(b"\0")
            if scripts.intersection(arguments):
                owned.append((process, (process / "stat").read_text().split(") ", 1)[1].split()[19]))
                os.kill(int(process.name), signal.SIGTERM)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    deadline = time.monotonic() + timeout
    for process, started in owned:
        while time.monotonic() < deadline:
            try:
                fields = (process / "stat").read_text().split(") ", 1)[1].split()
                if fields[19] != started or fields[0] == "Z":
                    break
            except FileNotFoundError:
                break
            time.sleep(0.1)
        else:
            fields = (process / "stat").read_text().split(") ", 1)[1].split()
            if fields[19] == started:
                os.kill(int(process.name), signal.SIGKILL)


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--stop-run":
        stop_run(Path(sys.argv[2]).resolve())
    else:
        raise SystemExit("Use --stop-run with the run directory.")
