#!/usr/bin/env python3
"""Write one item into each openDesk application of a zone, or read the items back. Usage: zone-data-check.py <zone> write|read

The browser signs in as Administrator through the zone Keycloak (zone-browser-check.py) and uses the web API of each
application from its own page, with the session of the browser:
  files     a text file p88-persist.txt in the Files of the user (WebDAV)
  wiki      the page Main.P88Persist (XWiki REST API)
read looks for each item and prints whether it exists. Jitsi keeps no data, so the check has no item for it. The script prints one JSON line for each application and no password.
Run it with the browser Python environment in <state folder>/browser-venv, which has nodriver.
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
    'files': (f'https://{z.host("files")}/apps/files/', {
        'write': f"""(async () => {{ const p = '/remote.php/dav/files/' + encodeURIComponent(OC.getCurrentUser().uid) + '/{MARK}.txt';
          return String((await fetch(p, {{method: 'PUT', headers: {{requesttoken: OC.requestToken}}, body: 'persisted by plan 88'}})).status); }})()""",
        'read': f"""(async () => {{ const p = '/remote.php/dav/files/' + encodeURIComponent(OC.getCurrentUser().uid) + '/{MARK}.txt';
          const r = await fetch(p, {{headers: {{requesttoken: OC.requestToken}}}}); return r.status + ' ' + (await r.text()); }})()"""}),
    'wiki': (f'https://{z.host("wiki")}/bin/view/Main/', {
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
        tab = await browser.get(f'https://{z.host("portal")}/univention/oidc/?location=/univention/portal/')
        await z.sign_in(tab, 'Administrator', password)
        await asyncio.sleep(5)
        for app, (url, scripts) in SCRIPTS.items():
            try:
                tab = await browser.get(url)
                await asyncio.sleep(6)
                result = await z.evaluate(tab, scripts[mode])
            except Exception as error:  # noqa: BLE001 - the row names the failure of this application
                result = f'error {type(error).__name__}: {error}'[:200]
            passed = str(result).startswith(('200', '201', '204')) and (mode == 'write' or MARK.replace('-', '') in str(result).replace('-', '').lower()
                                                                         or 'persisted' in str(result) or str(result).split()[-1] not in ('0', ''))
            ok &= passed
            print(json.dumps({'zone': z.ZONE, 'app': app, 'mode': mode, 'ok': passed, 'result': str(result)[:160]}), flush=True)
    finally:
        await z.stop_browser(browser)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[2] not in ('write', 'read'):
        raise SystemExit(__doc__)
    asyncio.run(main(sys.argv[2]))
