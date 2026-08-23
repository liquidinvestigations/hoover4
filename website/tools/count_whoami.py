"""Count `/api/whoami…` requests per page load, in a real browser.

Diagnostic for "the session gate fires more than once": `whoami` is the only endpoint
that mints a session, so every extra call is an extra session write. Run it the way
`take-screenshots.sh` runs the capture script, copied into `hoover4-mcp-browser` and
executed there, because that is the only container with a browser and the website is
only reachable from inside the podman network.

    docker cp website/tools/count_whoami.py hoover4-mcp-browser:/tmp/count_whoami.py
    docker exec hoover4-mcp-browser python /tmp/count_whoami.py
"""

import asyncio
import os
import sys

BASE = os.environ.get("HOOVER4_SITE_URL", "http://hoover4-website:8080")
ROUTES = ["/", "/file_browser", "/ai_chat", "/admin", "/admin/users", "/admin/metrics"]


async def main() -> int:
    import nodriver
    import nodriver.cdp.network as network_cdp

    browser = await nodriver.start(
        headless=True,
        sandbox=False,
        browser_args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    )
    tab = await browser.get(BASE + "/")
    seen: list[str] = []

    def on_request(event, _connection=None):
        seen.append(event.request.url)

    tab.add_handler(network_cdp.RequestWillBeSent, on_request)
    await tab.send(network_cdp.enable())
    await asyncio.sleep(3)

    total = 0
    for route in ROUTES:
        seen.clear()
        await tab.get(BASE + route)
        await asyncio.sleep(6)
        hits = [u for u in seen if "/api/whoami" in u]
        total += len(hits)
        print(f"{route:20s} whoami={len(hits)}")
    print(f"TOTAL {total} over {len(ROUTES)} navigations")
    browser.stop()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
