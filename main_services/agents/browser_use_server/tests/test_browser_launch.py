"""The launch settings of a browser, the removal of its profile folders, and its stop."""

from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest

from browser_use_server import chat_browser


def test_the_browser_runs_headed_with_its_own_user_agent(tmp_path):
    config, _extensions = chat_browser.browser_config(str(tmp_path), 9222)
    args = list(config())
    assert not [a for a in args if a.startswith("--headless")]
    assert not [a for a in args if a.startswith("--user-agent")]
    assert not [a for a in args if a.startswith("--ozone-platform")]
    assert f"--window-size={chat_browser.WINDOW_WIDTH},{chat_browser.WINDOW_HEIGHT}" in args
    assert "--window-position=0,0" in args
    assert "--disable-backgrounding-occluded-windows" in args
    assert "--remote-debugging-port=9222" in args


def test_a_new_profile_sends_webrtc_udp_only_through_a_proxy(tmp_path):
    import json

    chat_browser.write_profile_prefs(str(tmp_path))
    prefs = json.loads((tmp_path / "Default" / "Preferences").read_text())
    assert prefs["webrtc"]["ip_handling_policy"] == "disable_non_proxied_udp"


def test_no_page_origin_may_open_the_cdp_websocket(tmp_path):
    # nodriver adds `--remote-allow-origins=*`. Without it, Chromium refuses a CDP
    # WebSocket request that has an `Origin` header, which every page script sends.
    config, _extensions = chat_browser.browser_config(str(tmp_path), 9222)
    assert not [a for a in config() if a.startswith("--remote-allow-origins")]


def test_the_chromium_log_goes_to_a_file_when_asked(monkeypatch, tmp_path):
    seen = {}

    async def fake_exec(*args, stdout=None, stderr=None, start_new_session=False):
        seen["args"] = args
        seen["stderr"] = stderr
        return object()

    async def answers(port, timeout):
        return True

    monkeypatch.setattr(chat_browser, "CHROMIUM_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(chat_browser, "CHROMIUM_LOG_VERBOSITY", 1)
    monkeypatch.setattr(chat_browser.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(chat_browser, "_wait_for_cdp", answers)
    chat = chat_browser.ChatBrowser(session_id="_reader", cdp_port=9222)
    config, _extensions = chat_browser.browser_config(str(tmp_path / "p"), 9222)
    asyncio.run(chat_browser._launch_chromium(chat, config))
    assert "--enable-logging=stderr" in seen["args"] and "--v=1" in seen["args"]
    assert [name for name in os.listdir(tmp_path / "logs") if name.startswith("_reader-9222-")]
    assert seen["stderr"].closed


def test_no_display_fails_before_a_launch(monkeypatch, tmp_path):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(chat_browser.tempfile, "tempdir", str(tmp_path))
    with pytest.raises(chat_browser.BrowserSpawnFailed, match="DISPLAY"):
        asyncio.run(chat_browser.start("x"))
    assert os.listdir(tmp_path) == []


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


def test_launch_args_keep_site_isolation_and_the_extension_switch():
    args = ["--a", "--disable-features=IsolateOrigins,site-per-process,"
            "DisableLoadExtensionCommandLineSwitch", "--b", "--disable-features=Foo,IsolateOrigins"]
    assert chat_browser.launch_args(args) == [
        "--a", "--disable-features=DisableLoadExtensionCommandLineSwitch,Foo", "--b"]
    assert chat_browser.launch_args(["--disable-features=site-per-process"]) == []
    assert chat_browser.launch_args(["--a"]) == ["--a"]


def test_the_launch_of_a_browser_with_extensions_has_one_feature_switch(tmp_path, monkeypatch):
    ext = tmp_path / "ubol"
    ext.mkdir()
    (ext / "manifest.json").write_text("{}")
    monkeypatch.setattr(chat_browser, "EXTENSIONS_DIR", str(tmp_path))
    config, _ = chat_browser.browser_config(str(tmp_path / "profile"), 9999)
    args = chat_browser.launch_args(list(config()))
    features = [a for a in args if a.startswith("--disable-features=")]
    assert features == ["--disable-features=DisableLoadExtensionCommandLineSwitch"]
    assert any(a.startswith("--load-extension=") for a in args)
