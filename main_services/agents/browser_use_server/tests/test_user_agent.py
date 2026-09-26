"""The chat browser's user agent, and the removal of its profile folders."""

from __future__ import annotations

import asyncio
import os
import stat
import sys
import time

from browser_use_server import chat_browser


def _fake_executable(tmp_path, output: str) -> str:
    path = tmp_path / "chromium"
    path.write_text(f"#!/bin/sh\nprintf '%s' '{output}'\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_the_user_agent_takes_the_major_version_and_drops_headless(tmp_path):
    chat_browser.user_agent_for.cache_clear()
    exe = _fake_executable(tmp_path, "Chromium 153.0.8010.52 built on Debian")
    agent = chat_browser.user_agent_for(exe)
    assert agent == (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    )
    assert "Headless" not in agent


def test_no_version_gives_no_user_agent(tmp_path):
    chat_browser.user_agent_for.cache_clear()
    assert chat_browser.user_agent_for(_fake_executable(tmp_path, "")) is None
    assert chat_browser.user_agent_for(str(tmp_path / "missing")) is None


def test_the_sweep_removes_only_profile_folders(tmp_path):
    (tmp_path / "h4browser-a-1").mkdir()
    (tmp_path / "h4browser-b-2" / "Default").mkdir(parents=True)
    (tmp_path / "other").mkdir()
    (tmp_path / "h4browser-file").write_text("x")
    assert chat_browser.sweep_leftover_profiles(str(tmp_path)) == 2
    assert sorted(os.listdir(tmp_path)) == ["h4browser-file", "other"]


def test_cleanup_removes_the_folder_and_clears_the_path(tmp_path):
    folder = tmp_path / "h4browser-x"
    (folder / "Default").mkdir(parents=True)
    chat = chat_browser.ChatBrowser(session_id="x", profile_dir=str(folder))
    asyncio.run(chat_browser._cleanup_profile(chat))
    assert not folder.exists()
    assert chat.profile_dir == ""


def test_stop_ends_the_whole_process_group():
    async def run() -> int:
        # A parent that starts a child in its own group, then waits.
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c",
            "import subprocess, sys, time; "
            "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            "print(c.pid, flush=True); time.sleep(60)",
            stdout=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        child = int((await proc.stdout.readline()).decode().strip())
        chat = chat_browser.ChatBrowser(session_id="g", chromium=proc)
        await chat_browser._stop_chromium(chat)
        return child

    child = asyncio.run(run())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        # A zombie still answers signal 0 until its parent reaps it; the parent is gone,
        # so check the process state as well.
        try:
            with open(f"/proc/{child}/stat") as handle:
                state = handle.read().rsplit(")", 1)[1].split()[0]
        except OSError:
            break
        if state == "Z":
            break
        time.sleep(0.05)
    else:
        raise AssertionError(f"child {child} of the stopped group is still alive")
