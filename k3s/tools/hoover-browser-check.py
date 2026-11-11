#!/usr/bin/env python3
"""Sign in to the Hoover of one zone in a fresh browser, and record what the page shows.

HOOVER_USER names the account, test.user by default. The password of test.user comes from
k3s/private/zones/<zone>/test-user-password, and the password of a zone user from k3s/private/fixture-user-passwords.json.
With LAB_INVENTORY it comes from the zone row of that login table instead. The script never prints it.
It opens the Hoover address, which redirects to the zone Keycloak, signs in, and waits for the Hoover page.
With a search word it also types the word into the search box and records the result text.
The JSON result goes to stdout. The screenshot goes to k3s/private/checks/hoover, which Git ignores.
Usage: <browser-venv python> hoover-browser-check.py <zone> [search word | logout | viewer | stay]
page <path> opens one site path. viewer checks that the PDF viewer bundle loads as JavaScript. A third argument names a document path to download.
logout ends the Keycloak session in a second tab, then reloads Hoover 5 s and 130 s later.
stay sends a POST to the site every 20 s for 200 s. The proxy refreshes the session one minute after sign-in, so
the check fails when a refresh ends the session and the proxy answers with a redirect to Keycloak.
LAB_SUFFIX, LAB_RESOLVE, and LAB_INVENTORY check another host: its domain suffix, the address that serves its names, and its
login table. LAB_RESOLVE maps every name of the suffix to the address and accepts the frontend certificate of that host.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings  # noqa: E402
sys.path.insert(0, str(settings.HOOVER4 / 'website/tools'))
from browser_lifecycle import start_browser, stop_browser  # noqa: E402

ZONE = sys.argv[1]
MODE = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] in ('logout', 'viewer', 'page', 'stay') else 'search'
WORD = sys.argv[2] if len(sys.argv) > 2 and MODE == 'search' else ''
SUFFIX = __import__('os').environ.get('LAB_SUFFIX', settings.SUFFIX)
RESOLVE = __import__('os').environ.get('LAB_RESOLVE')
HOST = f'hoover.{ZONE}.{SUFFIX}'
PRIVATE = settings.PRIVATE / 'checks/hoover'
USER = __import__('os').environ.get('HOOVER_USER', 'test.user')


def password():
    if not __import__('os').environ.get('LAB_INVENTORY'):
        if USER == 'test.user':
            return (settings.PRIVATE / 'zones' / ZONE / 'test-user-password').read_text().strip()
        return json.loads((settings.PRIVATE / 'fixture-user-passwords.json').read_text())[USER]
    for line in Path(__import__('os').environ['LAB_INVENTORY']).read_text().splitlines():
        cells = [c.strip().strip('`') for c in line.split('|')]
        # The inventory holds the tables of several hosts, so the address must name the zone of this suffix.
        if len(cells) > 4 and cells[1] == f'{ZONE} portal and applications' and f'.{ZONE}.{SUFFIX}/' in cells[2] and cells[3] == USER:
            return cells[4]
    raise SystemExit(f'the inventory has no {USER} row for {ZONE}')


async def page(tab):
    return await tab.evaluate('JSON.stringify({url: location.href, title: document.title, text: document.body ? document.body.innerText.slice(0, 600) : ""})')


async def main():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    extra = [f'--host-resolver-rules=MAP *.{SUFFIX} {RESOLVE}', '--ignore-certificate-errors'] if RESOLVE else []
    browser = await start_browser(PRIVATE / 'browser.log', ['--window-size=1400,900', *extra], timeout=45)
    result = {'zone': ZONE, 'user': USER, 'started': time.time(), 'steps': []}
    try:
        start = time.monotonic()
        tab = await browser.get(f'https://{HOST}/')
        # The proxy redirects to Keycloak. Typing before that page settles hits a replaced element.
        await asyncio.sleep(4)
        await (await tab.select('input[name="username"]', timeout=30)).send_keys(USER)
        await (await tab.select('input[name="password"]', timeout=10)).send_keys(password())
        await (await tab.select('#kc-login', timeout=10)).click()
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            await asyncio.sleep(1)
            seen = json.loads(await page(tab))
            if HOST in seen['url'] and 'oauth2' not in seen['url'] and seen['text'].strip():
                break
        seen['seconds'] = round(time.monotonic() - start, 1)
        result['steps'].append({'step': 'sign-in', **seen})
        if MODE == 'page':
            # Open one site path, for example /red_flag_terms, and record what it shows.
            await tab.get(f'https://{HOST}{sys.argv[3]}')
            await asyncio.sleep(8)
            result['steps'].append({'step': 'page', **json.loads(await page(tab))})
        if MODE == 'viewer':
            # The document view imports the PDF viewer bundle as a module. A missing file comes back as the HTML page.
            await asyncio.sleep(5)
            probe = await tab.evaluate(
                "fetch('/assets/_viewer/dist/embedpdf.js').then(r => JSON.stringify({status: r.status, type: r.headers.get('content-type'),"
                " opener: typeof window.x_open_pdf_viewer}))", await_promise=True)
            result['steps'].append({'step': 'viewer', **json.loads(probe), 'url': '', 'text': ''})
            if len(sys.argv) > 3:
                # The document path, for example /_download_document/demo_emails/<file hash>.
                probe = await tab.evaluate(
                    f"fetch({json.dumps(sys.argv[3])}).then(async r => JSON.stringify({{status: r.status, type: r.headers.get('content-type'),"
                    " bytes: (await r.arrayBuffer()).byteLength}))", await_promise=True)
                result['steps'].append({'step': 'document', 'path': sys.argv[3], **json.loads(probe), 'url': '', 'text': ''})
        if MODE == 'logout':
            # The portal logout ends the Keycloak session. The Keycloak end-session page does the same.
            logout = await browser.get(f'https://id.{ZONE}.{SUFFIX}/realms/opendesk/protocol/openid-connect/logout', new_tab=True)
            await asyncio.sleep(3)
            await (await logout.select('#kc-logout', timeout=20)).click()
            await asyncio.sleep(3)
            ended = time.monotonic()
            result['steps'].append({'step': 'keycloak-logout', **json.loads(await page(logout))})
            for wait in (5, 130):
                await asyncio.sleep(max(0, ended + wait - time.monotonic()))
                await tab.reload()
                await asyncio.sleep(4)
                after = json.loads(await page(tab))
                after['host'] = after['url'].split('/')[2]
                result['steps'].append({'step': f'reload {wait} s after logout', **after})
        if MODE == 'stay':
            # The chat sends POST requests. With redirect manual a redirect to Keycloak shows as the type opaqueredirect.
            for _ in range(10):
                await asyncio.sleep(20)
                probe = await tab.evaluate("fetch('/', {method: 'POST', redirect: 'manual'}).then(r => JSON.stringify({status: r.status, type: r.type}))",
                                           await_promise=True)
                result['steps'].append({'step': 'post', 'seconds': round(time.monotonic() - start), **json.loads(probe)})
            if any(s.get('type') == 'opaqueredirect' for s in result['steps']):
                result['error'] = 'the proxy redirected a request to Keycloak'
        if WORD:
            result['inputs'] = json.loads(await tab.evaluate(
                "JSON.stringify([...document.querySelectorAll('input,textarea')].map(e => [e.tagName, e.type, e.placeholder, e.id, e.className.slice(0,40)]))"))
            # The home box submits on a key press. A JavaScript event does not cause it, so the check sends Enter through CDP.
            # The page can attach its key handler after the box shows, so the check repeats Enter until the address changes.
            import nodriver.cdp.input_ as input_cdp
            home = json.loads(await page(tab))['url']
            for attempt in range(3):
                # The page can render the box again and clear it, so each attempt types the word again.
                box = await tab.select('input[type="search"], input[type="text"]', timeout=20)
                await box.clear_input()
                await box.send_keys(WORD)
                for kind in ('keyDown', 'char', 'keyUp'):
                    await tab.send(input_cdp.dispatch_key_event(type_=kind, key='Enter', code='Enter', windows_virtual_key_code=13,
                                                                native_virtual_key_code=13, text='\r' if kind == 'char' else None))
                await asyncio.sleep(4)
                if json.loads(await page(tab))['url'] != home:
                    break
            await asyncio.sleep(4)
            result['steps'].append({'step': 'search', 'word': WORD, **json.loads(await page(tab))})
        await tab.save_screenshot(str(PRIVATE / f'hoover-{ZONE}.png'))
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'[:400]
    finally:
        result['finished'] = time.time()
        await stop_browser(browser)
    print(json.dumps(result, indent=1))
    sys.exit(1 if 'error' in result else 0)


if __name__ == '__main__':
    asyncio.run(main())
