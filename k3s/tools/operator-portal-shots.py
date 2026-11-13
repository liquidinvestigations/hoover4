#!/usr/bin/env python3
"""Capture pages of the operator portal for the manuals.

Usage: operator-portal-shots.py <name> <path> [<selector> [<script>]]

The browser signs in to the operator portal as admin and opens <path>, for example / or /settings.html.
It waits until the loading texts are gone. Then it runs the page <script> and scrolls <selector> into view, when given.
The page timers stop, so a refresh does not write the original text back.
The site suffix becomes example.org, and each node name becomes node-1, node-2 and so on.
Each IP address becomes a documentation address. So the image names no host.
The script saves a 1400 by 900 viewport image as <private>/checks/portal-shots/<name>.png.
It appends the name, the path, the image SHA-256, the size and the time to portal-shots/manifest.jsonl.
The admin password comes from <private>/operator-login/admin-password. The script prints no password.
<private> is the private folder beside the tree. Run the script from the tree of the site, for example an exported tree.
Run it with the browser Python environment in k3s/private/browser-venv, which has nodriver.
"""
import asyncio
import hashlib
import json
import pathlib
import struct
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import settings  # noqa: E402

sys.path.insert(0, str(settings.HOOVER4 / 'website/tools'))
from browser_lifecycle import start_browser, stop_browser  # noqa: E402

OUT = settings.PRIVATE / 'checks' / 'portal-shots'
BASE = f'https://operator.{settings.SUFFIX}'
LOADING = ('is loading', 'are loading')


def password():
    return (settings.PRIVATE / 'operator-login/admin-password').read_text().splitlines()[0]


async def js(tab, code):
    text = await tab.evaluate(f'Promise.resolve({code}).then(v => JSON.stringify(v === undefined ? null : v))',
                              await_promise=True, return_by_value=True)
    if not isinstance(text, str):
        raise RuntimeError(f'the page script failed: {text}'[:300])
    return json.loads(text)


async def login(tab, path):
    for _ in range(60):
        await asyncio.sleep(1)
        url = await js(tab, 'location.href')
        if url.startswith(BASE + path.split('?')[0]) and not await js(tab, "!!document.querySelector('input[name=password]')"):
            return
        if await js(tab, "!!document.querySelector('input[name=password]')"):
            await js(tab, f"""(() => {{
              const set = (el, v) => {{ Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v);
                el.dispatchEvent(new Event('input', {{bubbles: true}})); }};
              set(document.querySelector('input[name=login]'), 'admin');
              set(document.querySelector('input[name=password]'), {json.dumps(password())});
              document.querySelector('form').submit(); }})()""")
            await asyncio.sleep(3)
    raise SystemExit(f'the login did not reach {BASE}{path}')


def masks():
    site = config.read(settings.SITE_FILE)
    out = {settings.SUFFIX: 'example.org'}
    out.update({name: f'node-{i}' for i, name in enumerate(sorted(site.nodes, key=len, reverse=True), 1)})
    return out


def png_size(path):
    with open(path, 'rb') as f:
        head = f.read(24)
    return struct.unpack('>II', head[16:24])


async def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    name, path = argv[0], argv[1]
    selector = argv[2] if len(argv) > 2 else ''
    script = argv[3] if len(argv) > 3 else ''
    OUT.mkdir(parents=True, exist_ok=True)
    browser = await start_browser(OUT / 'browser.log', ['--window-size=1400,900'], timeout=45)
    try:
        tab = await browser.get(BASE + path)
        await login(tab, path)
        await tab.send(__import__('nodriver').cdp.emulation.set_device_metrics_override(
            width=1400, height=900, device_scale_factor=1, mobile=False))
        for _ in range(60):
            text = await js(tab, 'document.body.innerText')
            if not any(word in text for word in LOADING):
                break
            await asyncio.sleep(1)
        await asyncio.sleep(2)
        if script:
            await js(tab, f'(() => {{ {script}; return true; }})()')
            await asyncio.sleep(2)
        await js(tab, '(() => { for (let i = 1; i < 100000; i++) { clearInterval(i); clearTimeout(i); } return true; })()')
        await asyncio.sleep(2)
        await js(tab, f"""(() => {{
          const map = {json.dumps(masks())};
          const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          const fix = s => Object.entries(map).reduce((t, [a, b]) => t.split(a).join(b), s)
            .replace(/\\b(?:\\d{{1,3}}\\.){{3}}\\d{{1,3}}\\b/g, '192.0.2.1').replace(/\\b[0-9a-f]{{1,4}}(?::[0-9a-f]{{0,4}}){{3,7}}\\b/gi, '2001:db8::1');
          while (walk.nextNode()) walk.currentNode.nodeValue = fix(walk.currentNode.nodeValue);
          document.querySelectorAll('input,option').forEach(e => {{ if (e.value) e.value = fix(e.value); }});
          return true; }})()""")
        if selector:
            await js(tab, f"document.querySelector({json.dumps(selector)})?.scrollIntoView({{block: 'start'}}) || true")
            await asyncio.sleep(1)
        shot = OUT / f'{name}.png'
        await tab.save_screenshot(str(shot), format='png', full_page=False)
    finally:
        await stop_browser(browser)
    width, height = png_size(shot)
    row = {'name': name, 'path': path, 'selector': selector, 'script': script, 'sha256': hashlib.sha256(shot.read_bytes()).hexdigest(),
           'width': width, 'height': height, 'time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    with open(OUT / 'manifest.jsonl', 'a') as f:
        f.write(json.dumps(row) + '\n')
    print(json.dumps(row))


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1:]))
