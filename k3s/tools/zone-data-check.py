#!/usr/bin/env python3
"""Write one item into each openDesk application of a zone, or read the items back. Usage: zone-data-check.py <zone> write|read

The browser signs in as Administrator through the zone Keycloak (zone-browser-check.py) and uses the web API of each
application from its own page, with the session of the browser:
  files     a text file p88-persist.txt in the Files of the user (WebDAV)
  notes     a document with the title p88-persist (Notes API)
  projects  a project with the identifier p88-persist (OpenProject API v3)
  wiki      the page Main.P88Persist (XWiki REST API)
  chat      a room with the name p88-persist (Matrix client API, with a compatibility token of the Matrix
            authentication service for the user, because Element keeps its token encrypted in the browser)
read looks for each item and prints whether it exists. CryptPad keeps its data encrypted in the browser and Jitsi
keeps none, so the check has no item for them. The script prints one JSON line for each application and no password.
Run it with the browser Python environment in k3s/private/browser-venv, which has nodriver.
"""
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('zone_browser_check', HERE / 'zone-browser-check.py')
z = importlib.util.module_from_spec(spec)
spec.loader.exec_module(z)

MARK = 'p88-persist'
SCRIPTS = {
    'files': (f'https://files.{z.D}/apps/files/', {
        'write': f"""(async () => {{ const p = '/remote.php/dav/files/' + encodeURIComponent(OC.getCurrentUser().uid) + '/{MARK}.txt';
          return String((await fetch(p, {{method: 'PUT', headers: {{requesttoken: OC.requestToken}}, body: 'persisted by plan 88'}})).status); }})()""",
        'read': f"""(async () => {{ const p = '/remote.php/dav/files/' + encodeURIComponent(OC.getCurrentUser().uid) + '/{MARK}.txt';
          const r = await fetch(p, {{headers: {{requesttoken: OC.requestToken}}}}); return r.status + ' ' + (await r.text()); }})()"""}),
    'notes': (f'https://notes.{z.D}/', {
        'write': f"""(async () => {{ const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
          const r = await fetch('/api/v1.0/documents/', {{method: 'POST', credentials: 'include', headers: {{'Content-Type': 'application/json', 'X-CSRFToken': csrf}},
          body: JSON.stringify({{title: '{MARK}'}})}}); return String(r.status); }})()""",
        'read': f"""(async () => {{ const r = await fetch('/api/v1.0/documents/?title={MARK}', {{credentials: 'include'}});
          const d = await r.json(); return r.status + ' ' + (d.results || []).filter(x => x.title === '{MARK}').length; }})()"""}),
    'projects': (f'https://projects.{z.D}/', {
        'write': f"""(async () => {{ const t = document.querySelector('meta[name=csrf-token]').content;
          const r = await fetch('/api/v3/projects', {{method: 'POST', headers: {{'Content-Type': 'application/json', 'X-CSRF-Token': t}},
          body: JSON.stringify({{name: '{MARK}', identifier: '{MARK}'}})}}); return String(r.status); }})()""",
        'read': f"""(async () => {{ const r = await fetch('/api/v3/projects/{MARK}'); return r.status + ' ' + ((await r.json()).identifier || ''); }})()"""}),
    'wiki': (f'https://wiki.{z.D}/bin/view/Main/', {
        'write': """(async () => { const t = document.documentElement.dataset.xwikiFormToken || '';
          const body = '<page xmlns="http://www.xwiki.org"><title>P88 persist</title><content>persisted by plan 88</content></page>';
          const r = await fetch('/rest/wikis/xwiki/spaces/Main/pages/P88Persist', {method: 'PUT', headers: {'Content-Type': 'application/xml', 'XWiki-Form-Token': t}, body});
          return String(r.status); })()""",
        'read': """(async () => { const r = await fetch('/rest/wikis/xwiki/spaces/Main/pages/P88Persist', {headers: {Accept: 'application/json'}});
          return r.status + ' ' + ((r.ok && (await r.json()).content) || ''); })()"""}),
}


async def main(mode):
    password = z.passwords()['Administrator']
    browser = await z.start_browser(z.OUT / 'browser-data.log', ['--window-size=1400,900'], timeout=120)
    ok = True
    try:
        tab = await browser.get(f'https://portal.{z.D}/univention/oidc/?location=/univention/portal/')
        await z.sign_in(tab, 'Administrator', password)
        await asyncio.sleep(5)
        for app, (url, scripts) in SCRIPTS.items():
            try:
                tab = await browser.get(url)
                await asyncio.sleep(12 if app == 'chat' else 6)
                if app == 'chat':
                    await z.click_any(tab, ['Continue', 'Sign in', 'Anmelden', 'Weiter'])
                    await asyncio.sleep(12)
                result = await z.evaluate(tab, scripts[mode])
            except Exception as error:  # noqa: BLE001 - the row names the failure of this application
                result = f'error {type(error).__name__}: {error}'[:200]
            passed = str(result).startswith(('200', '201', '204')) and (mode == 'write' or MARK.replace('-', '') in str(result).replace('-', '').lower()
                                                                         or 'persisted' in str(result) or str(result).split()[-1] not in ('0', ''))
            ok &= passed
            print(json.dumps({'zone': z.ZONE, 'app': app, 'mode': mode, 'ok': passed, 'result': str(result)[:160]}), flush=True)
    finally:
        await z.stop_browser(browser)
    result = chat(mode)
    passed = result.startswith('200')
    ok &= passed
    print(json.dumps({'zone': z.ZONE, 'app': 'chat', 'mode': mode, 'ok': passed, 'result': result[:160]}), flush=True)
    sys.exit(0 if ok else 1)


def chat(mode):
    import re
    import subprocess
    import urllib.parse
    import urllib.request
    out = subprocess.run(['kubectl', '--kubeconfig', str(z.settings.KUBECONFIG), '-n', z.ZONE, 'exec',
                          'deploy/element-matrix-authentication-service', '--', 'mas-cli', 'manage',
                          'issue-compatibility-token', 'administrator'], capture_output=True, text=True)
    out = out.stdout + out.stderr
    token = (re.findall(r'mct_[A-Za-z0-9_]+', out) or [''])[0]
    base = f'https://matrix.{z.D}/_matrix/client/v3'

    def call(path, body=None):
        request = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    try:
        if mode == 'write':
            return '200 ' + call('/createRoom', {'name': MARK, 'preset': 'private_chat'})['room_id']
        for room in call('/joined_rooms')['joined_rooms']:
            try:
                if call(f'/rooms/{urllib.parse.quote(room)}/state/m.room.name')['name'] == MARK:
                    return '200 ' + room
            except OSError:
                continue
        return '404 no room named ' + MARK
    except OSError as error:
        return f'error {error}'


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[2] not in ('write', 'read'):
        raise SystemExit(__doc__)
    asyncio.run(main(sys.argv[2]))
