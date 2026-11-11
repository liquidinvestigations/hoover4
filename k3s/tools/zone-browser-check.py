#!/usr/bin/env python3
"""Sign in to every application of a zone in a real browser, as each zone user and as Administrator.

For each user the script starts a fresh Chromium, signs in once through the zone Keycloak at the portal, and then
opens each application. An application passes when the browser stays on the host of the application, the page shows
no password field, and the page text holds a marker that only a signed-in page shows. The page title does not count,
because a page without a session can have the same title. Element and Jitsi get one click on their single sign-on
button when they show one.
- Office is Collabora, which opens documents from Files. The check writes an empty hoover-office-check.odt to the
  Files of the user, opens it, and waits for the Document_Loaded message of Collabora. Then it deletes the file.
- Pad is CryptPad. It has its own accounts and no single sign-on, so its row shows that the start page answers.
  The row has "contract": "availability" and does not show a sign-in.
- Meet checks the join page of a room only.
The passwords come from k3s/private/fixture-user-passwords.json and from the Secret ums-nubus-credentials.
The script prints one JSON line for each check and no password. It exits with 1 when a check fails.
The screenshots and the page texts go to k3s/private/checks/zone-browser/, which Git ignores.
Usage: k3s/private/browser-venv/bin/python zone-browser-check.py <zone> [user ...]
"""
import asyncio
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings  # noqa: E402
sys.path.insert(0, str(settings.HOOVER4 / 'website/tools'))
from browser_lifecycle import start_browser, stop_browser  # noqa: E402

ZONE = sys.argv[1]
D = f'{ZONE}.{settings.SUFFIX}'
OUT = settings.PRIVATE / 'checks' / 'zone-browser'
PAGE = ('JSON.stringify({url: location.href, title: document.title, text: document.body ? document.body.innerText.slice(0, 3000) : "",'
        ' passwords: document.querySelectorAll("input[type=password]").length})')
# name, address, expected host, text markers of a signed-in page (one of them must show), single sign-on buttons to click
APPS = [
    ('portal', f'https://portal.{D}/univention/portal/', f'portal.{D}', ['Logged in as', 'Angemeldet als'], []),
    ('files', f'https://files.{D}/apps/files/', f'files.{D}', ['All files', 'Alle Dateien'], []),
    ('notes', f'https://notes.{D}/', f'notes.{D}', ['My notes', 'Meine Notizen'], []),
    ('projects', f'https://projects.{D}/', f'projects.{D}', ['Sie sind nun angemeldet', 'You are now logged in', 'My page', 'Meine Seite',
                                                           'My projects', 'Meine Projekte'], []),
    # After the first sign-in of a user, Element asks a new browser to verify the device. It shows that page only to a
    # signed-in user.
    ('chat', f'https://chat.{D}/', f'chat.{D}', ['Unreads', 'Ungelesen', 'Start chat', 'Unterhaltung beginnen', 'Verify this device'],
     ['Continue', 'Sign in', 'Anmelden', 'Weiter']),
    ('pad', f'https://pad.{D}/', f'pad.{D}', ['CryptPad'], []),
    ('wiki', f'https://wiki.{D}/bin/view/Main/', f'wiki.{D}', ['Benutzerprofil', 'User profile', 'User Profile'], []),
    ('meet', f'https://meet.{D}/hoover-check-room', f'meet.{D}', ['Join meeting', 'Konferenz beitreten', 'Beitreten'], ['Login', 'Anmelden', 'Sign in']),
    ('hoover', f'https://hoover.{D}/', f'hoover.{D}', ['Text Search'], []),
]
AVAILABILITY = {'pad'}
# Runs in the Files page: write an empty document and return its file id.
CREATE_DOCUMENT = """(async () => {
 const path = '/remote.php/dav/files/' + encodeURIComponent(OC.getCurrentUser().uid) + '/hoover-office-check.odt';
 const headers = {requesttoken: OC.requestToken};
 const put = await fetch(path, {method: 'PUT', headers, body: ''});
 const find = await fetch(path, {method: 'PROPFIND', headers: {...headers, Depth: '0', 'Content-Type': 'application/xml'},
   body: '<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns"><d:prop><oc:fileid/></d:prop></d:propfind>'});
 return JSON.stringify({put: put.status, find: find.status, fileid: ((await find.text()).match(/<oc:fileid>(\\d+)</) || [])[1] || null});
})()"""
DELETE_DOCUMENT = """fetch('/remote.php/dav/files/' + encodeURIComponent(OC.getCurrentUser().uid) + '/hoover-office-check.odt',
 {method: 'DELETE', headers: {requesttoken: OC.requestToken}}).then(r => String(r.status))"""
# Collabora posts its loading state to the Files page.
LISTEN = """window.hooverOffice = []; window.addEventListener('message', e => { try {
 const m = typeof e.data === 'string' ? JSON.parse(e.data) : e.data; if (m && m.MessageId) window.hooverOffice.push(m.MessageId + ':' + ((m.Values || {}).Status || ''));
 } catch (error) {} }); 'ok'"""


def passwords():
    out = json.loads((settings.PRIVATE / 'fixture-user-passwords.json').read_text())
    data = json.loads(subprocess.check_output(['kubectl', '--kubeconfig', str(settings.KUBECONFIG), '-n', ZONE, 'get', 'secret',
                                               'ums-nubus-credentials', '-o', 'json']))['data']
    out['Administrator'] = base64.b64decode(data['administrator_password']).decode()
    return out


async def page(tab):
    return json.loads(await tab.evaluate(PAGE))


async def wait_page(tab, host, markers, seconds=90):
    deadline = time.monotonic() + seconds
    seen = {}
    while time.monotonic() < deadline:
        await asyncio.sleep(2)
        try:
            seen = await page(tab)
        except Exception:
            continue
        if seen['url'].split('/')[2] == host and not seen['passwords'] and any(m in seen['text'] for m in markers):
            return True, seen
    return False, seen


async def sign_in(tab, user, password):
    """Fill the Keycloak form. The page redirects several times before the form settles, so each try starts again."""
    deadline = time.monotonic() + 120
    while True:
        await asyncio.sleep(3)
        try:
            await (await tab.select('input[name="username"]', timeout=20)).send_keys(user)
            await (await tab.select('input[name="password"]', timeout=5)).send_keys(password)
            await (await tab.select('#kc-login', timeout=5)).click()
            return
        except Exception:
            if time.monotonic() > deadline:
                raise


async def click_any(tab, labels):
    for label in labels:
        try:
            element = await tab.find(label, best_match=True, timeout=2)
        except Exception:
            continue
        if element:
            await element.click()
            return label
    return None


async def evaluate(tab, script):
    """Run a script that returns a string. nodriver returns the exception details instead of a string when it throws."""
    value = await tab.evaluate(script, await_promise=True)
    if not isinstance(value, str):
        raise RuntimeError(f'the page script failed: {value}'[:200])
    return value


async def check_office(browser, user):
    """Open an empty document of the user in Collabora through Files, and wait until Collabora loads it."""
    began = time.monotonic()
    try:
        tab = await browser.get(f'https://files.{D}/apps/files/')
        ok, _ = await wait_page(tab, f'files.{D}', ['All files', 'Alle Dateien'])
        if not ok:
            raise RuntimeError('the Files page did not open')
        document = json.loads(await evaluate(tab, CREATE_DOCUMENT))
        if document['put'] not in (201, 204) or not document['fileid']:
            raise RuntimeError(f'the document was not written: {document}')
        tab = await browser.get(f'https://files.{D}/apps/files/files/{document["fileid"]}?dir=/&openfile=true')
        await evaluate(tab, LISTEN)
        deadline, messages = time.monotonic() + 120, []
        while time.monotonic() < deadline:
            await asyncio.sleep(2)
            messages = json.loads(await evaluate(tab, 'JSON.stringify(window.hooverOffice || [])'))
            if 'App_LoadingStatus:Document_Loaded' in messages:
                break
        await tab.save_screenshot(str(OUT / f'{user}-office.png'))
        deleted = await evaluate(tab, DELETE_DOCUMENT)
        return {'user': user, 'app': 'office', 'ok': 'App_LoadingStatus:Document_Loaded' in messages,
                'seconds': round(time.monotonic() - began, 1), 'messages': sorted(set(messages))[:8], 'deleted': deleted}
    except Exception as error:
        return {'user': user, 'app': 'office', 'ok': False, 'error': f'{type(error).__name__}: {error}'[:200]}


async def check_user(user, password):
    results = []
    browser = await start_browser(OUT / f'browser-{user}.log', ['--window-size=1400,900', '--use-fake-ui-for-media-stream',
                                                               '--use-fake-device-for-media-stream'], timeout=120)
    try:
        start = time.monotonic()
        tab = await browser.get(f'https://portal.{D}/univention/oidc/?location=/univention/portal/')
        await sign_in(tab, user, password)
        for name, url, host, markers, buttons in APPS:
            began = time.monotonic()
            seen = {}
            try:
                if name != 'portal':
                    tab = await browser.get(url)
                ok, seen = await wait_page(tab, host, markers, 40 if buttons else 120)
                clicked = None
                if not ok and buttons:
                    clicked = await click_any(tab, buttons)
                    ok, seen = await wait_page(tab, host, markers, 120)
                await tab.save_screenshot(str(OUT / f'{user}-{name}.png'))
                row = {'user': user, 'app': name, 'ok': ok, 'seconds': round(time.monotonic() - began, 1), 'url': seen.get('url', '').split('?')[0],
                       'title': seen.get('title', '')[:80], 'clicked': clicked}
                if name in AVAILABILITY:
                    row['contract'] = 'availability'
            except Exception as error:
                row = {'user': user, 'app': name, 'ok': False, 'error': f'{type(error).__name__}: {error}'[:200]}
            (OUT / f'{user}-{name}.json').write_text(json.dumps({'row': row, 'text': (seen or {}).get('text', '')}, indent=1))
            results.append(row)
            print(json.dumps(row), flush=True)
            if name == 'portal' and not row['ok']:
                break
        row = await check_office(browser, user)
        results.append(row)
        print(json.dumps(row), flush=True)
        results.append({'user': user, 'app': 'all', 'seconds': round(time.monotonic() - start, 1)})
    except Exception as error:
        row = {'user': user, 'app': 'sign-in', 'ok': False, 'error': f'{type(error).__name__}: {error}'[:200]}
        results.append(row)
        print(json.dumps(row), flush=True)
    finally:
        await stop_browser(browser)
    return results


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    known = passwords()
    users = sys.argv[2:] or ['Administrator'] + [u['username'] for u in json.loads((settings.SOURCE / 'zones/zone-users.json').read_text())['users']]
    rows = []
    for user in users:
        rows += await check_user(user, known[user])
    checks = [r for r in rows if 'ok' in r]
    print(json.dumps({'zone': ZONE, 'checks': len(checks), 'passed': sum(r['ok'] for r in checks)}))
    sys.exit(0 if all(r['ok'] for r in checks) else 1)


if __name__ == '__main__':
    asyncio.run(main())
