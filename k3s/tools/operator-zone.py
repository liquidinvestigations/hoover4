#!/usr/bin/env python3
"""Send a zone operation through the operator portal and wait until the zone runner ends it.

Usage: operator-zone.py create <zone> <home node> | upgrade <zone> | delete <zone>
The browser signs in to https://operator.<suffix>/ as admin with k3s/private/operator-login/admin-password. It
sends the operation from the portal page, as the page form does, and reads the operation list of /zones.json every
30 s. It prints the state, the step and the error of the operation, and exits with 1 when the operation fails or does
not end within 90 minutes. Run it with k3s/private/browser-venv, which has nodriver.
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

ORIGIN = f'https://operator.{settings.SUFFIX}'
OUT = settings.PRIVATE / 'checks' / 'operator-zone'


async def evaluate(tab, script):
    value = await tab.evaluate(script, await_promise=True)
    if not isinstance(value, str):
        raise RuntimeError(f'the page script failed: {value}'[:300])
    return json.loads(value)


async def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ('create', 'upgrade', 'delete') or (sys.argv[1] == 'create') != (len(sys.argv) == 4):
        sys.exit(__doc__)
    action, zone = sys.argv[1:3]
    body = {'kind': f'{action}-zone', 'zone': zone}
    if action == 'create':
        body['home'] = sys.argv[3]
    if action == 'delete':
        body['confirm'] = zone
    OUT.mkdir(parents=True, exist_ok=True)
    browser = await start_browser(OUT / 'browser.log', ['--window-size=1400,900'], timeout=120)
    try:
        tab = await browser.get(ORIGIN + '/')
        await (await tab.select('input[name="login"]', timeout=60)).send_keys('admin')
        await (await tab.select('input[name="password"]', timeout=10)).send_keys(
            (settings.PRIVATE / 'operator-login/admin-password').read_text().strip())
        await (await tab.select('button[type="submit"]', timeout=10)).click()
        for _ in range(30):
            await asyncio.sleep(2)
            if (await tab.evaluate('location.href')).startswith(ORIGIN + '/') and await tab.evaluate("!!document.getElementById('create')"):
                break
        else:
            raise SystemExit('the operator portal did not open after the sign-in')
        sent = await evaluate(tab, f"""fetch('/operations', {{method: 'POST', headers: {{'Content-Type': 'application/json'}},
            body: {json.dumps(json.dumps(body))}}}).then(async r => JSON.stringify({{status: r.status, body: await r.json()}}))""")
        print(json.dumps({'at': time.strftime('%H:%M:%S'), 'sent': body, 'answer': sent}), flush=True)
        if sent['status'] != 200:
            sys.exit(1)
        name = sent['body']['operation']
        deadline = time.time() + 90 * 60
        state = ''
        while time.time() < deadline:
            await asyncio.sleep(30)
            data = await evaluate(tab, "fetch('/zones.json').then(r => r.text())")
            operation = next((o for o in data['operations'] if o['name'] == name), {})
            if (operation.get('state'), operation.get('step')) != state:
                state = (operation.get('state'), operation.get('step'))
                print(json.dumps({'at': time.strftime('%H:%M:%S'), 'operation': name, 'state': state[0], 'step': state[1],
                                  'error': operation.get('error', '')}), flush=True)
            if state[0] in ('done', 'failed'):
                print(json.dumps({'zones': [z['name'] for z in data['zones']]}), flush=True)
                sys.exit(0 if state[0] == 'done' else 1)
        sys.exit(1)
    finally:
        await stop_browser(browser)


if __name__ == '__main__':
    asyncio.run(main())
