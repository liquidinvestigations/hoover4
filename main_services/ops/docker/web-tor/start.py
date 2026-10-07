"""Run two isolated Tor clients without host listeners or control interfaces."""

import os
from pathlib import Path
import signal
import subprocess
import time

clients = []


def stop(*_):
    for client in clients:
        if client.poll() is None:
            client.terminate()


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    for index, port in enumerate((9050, 9051), 1):
        folder = Path(f"/tmp/tor-{index}")
        folder.mkdir(mode=0o700, exist_ok=True)
        config = folder / "torrc"
        config.write_text(
            f"DataDirectory {folder}\n"
            f"SocksPort 0.0.0.0:{port} IsolateSOCKSAuth\n"
            "ClientOnly 1\n"
            "ClientRejectInternalAddresses 1\n"
            "SafeSocks 1\n"
            "AvoidDiskWrites 1\n"
            "Log notice stdout\n"
        )
        clients.append(subprocess.Popen(["tor", "-f", str(config)]))
    while all(client.poll() is None for client in clients):
        time.sleep(1)
finally:
    stop()
    for client in clients:
        try:
            client.wait(timeout=15)
        except subprocess.TimeoutExpired:
            client.kill()
            client.wait()
