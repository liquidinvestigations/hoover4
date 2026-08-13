"""Report which state the session gate settles in for a real visitor.

The gate is the highest-risk component in the site: if the mint route stops working every
visitor sees "Sign-in required" instead of the app, and no page test catches it because
every page renders the same refusal. This loads one page in a real browser and reports
which of the three states the gate settled in.

Copied into `hoover4-mcp-browser` and run there, like the capture script:

    docker cp website/tools/check_session_gate.py hoover4-mcp-browser:/tmp/check.py
    docker exec hoover4-mcp-browser python /tmp/check.py
"""

import asyncio
import os
import sys

BASE = os.environ.get("HOOVER4_SITE_URL", "http://hoover4-website:8080")


async def main() -> int:
    import nodriver

    browser = await nodriver.start(
        headless=True,
        sandbox=False,
        browser_args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    )
    tab = await browser.get(BASE + "/")
    await asyncio.sleep(8)
    html = await tab.get_content()
    state = (
        "REFUSED" if "x-session-refused" in html
        else "LOADING" if "x-session-gate-loading" in html
        else "ADMITTED"
    )
    print(f"session gate: {state}")
    browser.stop()
    return 0 if state in ("ADMITTED", "REFUSED") else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
