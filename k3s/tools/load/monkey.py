#!/usr/bin/env python3
"""Exercise the zone apps with many signed-in browser tabs at once, one app after the other.

Each user (see below) gets --tabs browser contexts (1 by default) with one tab each. For each app the script waits
until the app answers, signs every tab in through the zone Keycloak, and then clicks, types, uploads, downloads, goes
back and reloads at random for --seconds in every tab at the same time. It records the start and end time of each app
phase, so that the samples of sampler.py on the home node of the zone can be cut by phase.

Destructive controls are refused. A click target whose text, label or address names logout, delete, admin and similar
words is skipped. A page navigation to another host, to a logout address, or to an admin area is aborted. Every
browser dialog is dismissed, which cancels a confirmation.

Run it with the Python environment k3s/private/load-venv, which has Playwright and uses /usr/bin/chromium.
Usage: load-venv/bin/python monkey.py run [app ...] [--seconds 60] [--users N] [--tabs N]
       load-venv/bin/python monkey.py explore <app> [user]   (one tab, a screenshot every 5 s, then 20 s of exercise)
Apps: portal files office notes projects chat pad wiki meet hoover. The output goes to k3s/private/load/load-<time>/.
The users are Administrator, test.user and the zone users of ../../zones/zone-users.json, with the passwords of
k3s/private and the zone.
LOAD_ZONE names the zone, zone-a by default. LOAD_HOST names the SSH alias of the node that runs sampler.py. The script
reads the clock of that node to align the samples. Without it the clock offset is 0.
"""
import asyncio
import base64
import io
import json
import os
import random
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import settings  # noqa: E402
ZONE, SUFFIX = os.environ.get('LOAD_ZONE', 'zone-a'), settings.SUFFIX
DOMAIN = f'{ZONE}.{SUFFIX}'
APPS = {
    'portal': f'https://portal.{DOMAIN}/',
    'files': f'https://files.{DOMAIN}/',
    'office': f'https://files.{DOMAIN}/',
    'notes': f'https://notes.{DOMAIN}/',
    'projects': f'https://projects.{DOMAIN}/',
    'chat': f'https://chat.{DOMAIN}/',
    'pad': f'https://pad.{DOMAIN}/',
    'wiki': f'https://wiki.{DOMAIN}/',
    'meet': f'https://meet.{DOMAIN}/loadtest-room',
    'hoover': f'https://hoover.{DOMAIN}/',
}
DENY = re.compile(r'log ?out|sign ?out|abmeld|delete|lösch|remove|entfern|disable|deaktiv|reset|zurücksetz|revoke|leave|verlass|'
                  r'archiv|uninstall|destroy|purge|empty|leeren|\bban\b|kick|block|passw|recovery|wiederherstell|\block\b|sperr|'
                  r'encrypt|verschlüssel|admin|verwaltung|transfer|übertrag|end meeting|end call|beenden|hang ?up|auflegen|'
                  r'șterg|sterg|deconect|elimin|dezactiv|ieșire|iesire|resetare|parol|golește|goleste|'
                  r'mailto:|tel:|javascript:void\(0\);?\s*logout', re.I)
BLOCKED_PATH = re.compile(r'logout|sign_?out|/admin|/settings/admin|/settings/user/security|/univention/management|/realms/master|'
                          r'/_synapse/admin|/bin/admin|/xwiki/bin/admin|/apps/settings|/settings/apps', re.I)
LOGIN_TEXT = re.compile(r'^\s*(log ?in|sign ?in|anmelden|einloggen|login with.*|sign in with.*|continue|weiter|fortfahren|'
                        r'.*opendesk.*|sso|accept|allow|zulassen|akzeptieren|grant|i am the host|ich bin der gastgeber|'
                        r'join meeting|meeting beitreten|beitreten|join)\s*$', re.I)
# The portal comes first, because its sign-in gives each browser the Keycloak session that the Jitsi adapter needs.
ORDER = ['portal', 'files', 'office', 'notes', 'projects', 'chat', 'pad', 'wiki', 'meet', 'hoover']
# CryptPad has its own accounts and no single sign-on in openDesk, so its tabs stay anonymous.
ANONYMOUS = {'pad'}
EXTRA_DENY = {'pad': re.compile(r'log ?in|register|sign ?up|inregistr', re.I)}
WORDS = 'load test alpha beta gamma delta report draft meeting notes budget plan review summary agenda'.split()

CANDIDATES_JS = r"""(deny) => {
  const re = new RegExp(deny, 'i');
  const sel = 'a[href], button, [role=button], [role=menuitem], [role=tab], [role=link], [role=option], [role=treeitem],' +
              ' input[type=checkbox], summary, [tabindex="0"], li[onclick], td a';
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4 || r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth) continue;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') continue;
    const desc = [el.innerText, el.getAttribute('aria-label'), el.getAttribute('title'), el.getAttribute('href'),
                  el.getAttribute('data-action'), el.id, el.className && el.className.baseVal === undefined ? el.className : '']
                 .filter(Boolean).join(' ').slice(0, 300);
    if (re.test(desc)) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || s.pointerEvents === 'none') continue;
    out.push({x: r.left + r.width / 2, y: r.top + r.height / 2, d: desc.replace(/\s+/g, ' ').slice(0, 80)});
  }
  return out;
}"""
INPUTS_JS = r"""() => {
  const out = [];
  for (const el of document.querySelectorAll('input[type=text], input[type=search], input:not([type]), textarea, [contenteditable=true], [role=textbox]')) {
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8 || r.top > innerHeight || r.bottom < 0) continue;
    if (el.disabled || el.readOnly) continue;
    const name = (el.name || '') + ' ' + (el.type || '') + ' ' + (el.getAttribute('aria-label') || '');
    if (/pass|user|mail|login/i.test(name)) continue;
    out.push({x: r.left + Math.min(r.width / 2, 40), y: r.top + r.height / 2});
  }
  return out;
}"""
LOGIN_JS = r"""(pattern) => {
  const re = new RegExp(pattern, 'i');
  for (const el of document.querySelectorAll('a, button, input[type=submit], [role=button]')) {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4 || r.top > innerHeight) continue;
    const t = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
    if (t && t.length < 60 && re.test(t)) return {x: r.left + r.width / 2, y: r.top + r.height / 2, t};
  }
  return null;
}"""


def logins():
    """Return Administrator, test.user and the zone users with their passwords from the private files and the zone."""
    import subprocess
    secret = json.loads(subprocess.check_output(['kubectl', '--kubeconfig', str(settings.KUBECONFIG), '-n', ZONE, 'get', 'secret',
                                                 'ums-nubus-credentials', '-o', 'json']))['data']
    users = [('Administrator', base64.b64decode(secret['administrator_password']).decode()),
             ('test.user', (settings.PRIVATE / 'zones' / ZONE / 'test-user-password').read_text().strip())]
    fixture = json.loads((settings.PRIVATE / 'fixture-user-passwords.json').read_text())
    names = [u['username'] for u in json.loads((settings.SOURCE / 'zones/zone-users.json').read_text())['users']]
    return users + [(name, fixture[name]) for name in names]


def png_bytes(size):
    width = max(8, int((size / 3) ** 0.5))
    raw = b''.join(b'\x00' + os.urandom(width * 3) for _ in range(width))
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, width, 8, 2, 0, 0, 0)) + \
        chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


def odt_bytes(text):
    content = ('<?xml version="1.0" encoding="UTF-8"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
               'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2"><office:body><office:text>'
               + ''.join(f'<text:p>{text} {i}</text:p>' for i in range(40)) + '</office:text></office:body></office:document-content>')
    manifest = ('<?xml version="1.0" encoding="UTF-8"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
                'manifest:version="1.2"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>'
                '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        z.writestr(zipfile.ZipInfo('mimetype'), 'application/vnd.oasis.opendocument.text')
        z.writestr('content.xml', content, zipfile.ZIP_DEFLATED)
        z.writestr('META-INF/manifest.xml', manifest, zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def upload_file(folder):
    kind = random.choice(['txt', 'png', 'txt', 'png', 'odt'])
    name = f'loadtest-{int(time.time() * 1000) % 10**9}-{random.randint(0, 999)}.{kind}'
    path = folder / name
    if kind == 'txt':
        path.write_text('\n'.join(' '.join(random.choices(WORDS, k=12)) for _ in range(random.randint(50, 20000))))
    elif kind == 'png':
        path.write_bytes(png_bytes(random.randint(20_000, 1_500_000)))
    else:
        path.write_bytes(odt_bytes('load test document'))
    return path


def ready(url, timeout=420):
    """Request the app until it answers with a status below 500. Return the seconds it took."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 loadtest'}), timeout=60) as r:
                r.read(4096)
                return round(time.monotonic() - start, 1)
        except urllib.error.HTTPError as error:
            if error.code < 500:
                return round(time.monotonic() - start, 1)
        except Exception:
            pass
        time.sleep(3)
    return None


class Tab:
    def __init__(self, browser, user, password, out, label=None):
        self.browser, self.user, self.password, self.out = browser, user, password, out
        # The label names the tab in the results, because one user can have several tabs.
        self.label = label or user
        self.stats = {}

    async def open(self):
        self.context = await self.browser.new_context(viewport={'width': 1366, 'height': 850}, accept_downloads=True,
                                                      ignore_https_errors=False, locale='en-US')
        await self.context.route('**/*', self.guard)
        self.context.on('page', self.on_popup)
        self.page = await self.context.new_page()
        self.page.on('dialog', lambda d: asyncio.ensure_future(d.dismiss()))
        self.page.on('download', lambda d: asyncio.ensure_future(self.on_download(d)))
        self.page.on('response', self.on_response)
        self.page.on('pageerror', lambda e: self.count('page_errors'))

    def count(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0) + n

    async def guard(self, route):
        request = route.request
        if request.resource_type == 'document' and request.is_navigation_request():
            url = request.url
            host = url.split('/')[2] if '://' in url else ''
            allowed = host == DOMAIN or host.endswith('.' + DOMAIN) or host == 's3.' + SUFFIX
            if not allowed or BLOCKED_PATH.search(url.split('?')[0]):
                self.count('blocked_navigations')
                return await route.abort()
        await route.continue_()

    def on_popup(self, page):
        if hasattr(self, 'page') and page is not self.page:
            self.count('popups')
            asyncio.ensure_future(self.close_later(page))

    async def close_later(self, page):
        await asyncio.sleep(3)
        try:
            await page.close()
        except Exception:
            pass

    async def on_download(self, download):
        try:
            path = await download.path()
            if path:
                self.count('download_bytes', os.path.getsize(path))
            self.count('downloads')
            await download.delete()
        except Exception:
            self.count('download_errors')

    def on_response(self, response):
        if response.status >= 500:
            self.count('http_5xx')
            self.stats.setdefault('5xx_urls', [])
            if len(self.stats['5xx_urls']) < 10:
                self.stats['5xx_urls'].append(f"{response.status} {response.url.split('?')[0][:120]}")
        elif response.status >= 400:
            self.count('http_4xx')

    async def sign_in(self, app, deadline_seconds=300, shots=None):
        """Open the app and pass every login step. Return the seconds it took, or None."""
        url = APPS[app]
        app_host = url.split('/')[2]
        start = time.monotonic()
        try:
            await self.page.goto(url, wait_until='domcontentloaded', timeout=90_000)
        except Exception as error:
            self.count('goto_errors')
        settled = 0
        last_click = ''
        while time.monotonic() - start < deadline_seconds:
            await asyncio.sleep(2)
            if shots is not None:
                await self.shot(shots, f'{app}-login-{int(time.monotonic() - start):03d}')
            try:
                page_url = self.page.url
                text = await self.page.evaluate('document.body ? document.body.innerText.slice(0, 2000) : ""')
                if app == 'meet':
                    name = self.page.locator('#premeeting-name-input')
                    if await name.count() and await name.is_visible() and not await name.input_value():
                        await name.fill(self.user)
                if await self.page.locator('input[name=username]').count() and 'id.' + DOMAIN in page_url:
                    await self.page.fill('input[name=username]', self.user)
                    await self.page.fill('input[name=password]', self.password)
                    await self.page.click('#kc-login')
                    settled = 0
                    continue
                target = None if app in ANONYMOUS else await self.page.evaluate(LOGIN_JS, LOGIN_TEXT.pattern)
                on_app = app_host in page_url
                if target and target['t'] != last_click or target and not on_app:
                    last_click = target['t']
                    await self.page.mouse.click(target['x'], target['y'])
                    self.count('login_clicks')
                    settled = 0
                    continue
                # A page that still loads shows a spinner with no text, so a ready page needs visible text
                # that stays without a login control for three checks.
                if app == 'meet' and await self.page.locator('.premeeting-screen').count():
                    join = self.page.locator('[data-testid="prejoin.joinMeeting"]')
                    if await join.count():
                        await join.first.click()
                        self.count('login_clicks')
                    settled = 0
                    continue
                if on_app and len(text.strip()) > 60 and not await self.page.locator('input[type=password]').count():
                    settled += 1
                    if settled >= 3:
                        if app == 'office':
                            await self.open_document()
                        return round(time.monotonic() - start, 1)
            except Exception:
                self.count('login_errors')
        return None

    async def open_document(self):
        """Store a new ODT in the user's Nextcloud through WebDAV and open it in Collabora."""
        data = base64.b64encode(odt_bytes(f'load test {self.label}')).decode()
        name = f'loadtest-office-{self.label}-{int(time.time())}.odt'
        fileid = await self.page.evaluate(r"""async ([data, name]) => {
          const uid = OC.getCurrentUser().uid, token = OC.requestToken;
          const body = Uint8Array.from(atob(data), c => c.charCodeAt(0));
          const path = '/remote.php/dav/files/' + encodeURIComponent(uid) + '/' + name;
          const signal = AbortSignal.timeout(60000);
          await fetch(path, {method: 'PUT', headers: {requesttoken: token}, body, signal});
          const r = await fetch(path, {method: 'PROPFIND', signal, headers: {requesttoken: token, Depth: '0', 'Content-Type': 'application/xml'},
            body: '<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns"><d:prop><oc:fileid/></d:prop></d:propfind>'});
          const m = (await r.text()).match(/<oc:fileid>(\d+)</);
          return m ? m[1] : null;
        }""", [data, name])
        if fileid is None:
            self.count('office_upload_failed')
        if fileid:
            await self.page.goto(f'https://files.{DOMAIN}/index.php/apps/files/files/{fileid}?dir=/&openfile=true',
                                 wait_until='domcontentloaded', timeout=90_000)
            await asyncio.sleep(12)
            self.start_url = self.page.url
        else:
            self.count('office_open_errors')

    async def finish(self, app):
        """End the Matrix session of a chat tab, so that the test leaves no extra device on the account."""
        if app != 'chat':
            return None
        try:
            await self.page.goto(APPS['chat'], wait_until='domcontentloaded', timeout=60_000)
            await asyncio.sleep(8)
            device = await self.page.evaluate("window.mxMatrixClientPeg && mxMatrixClientPeg.get() ? mxMatrixClientPeg.get().getDeviceId() : null")
            if not device:
                return 'no client'
            # Element's own logout action revokes the OAuth session at MAS, which also removes the Matrix device.
            await self.page.evaluate("window.mxDispatcher.dispatch({action: 'logout'})")
            await asyncio.sleep(10)
            still = await self.page.evaluate("window.mxMatrixClientPeg && mxMatrixClientPeg.get() ? mxMatrixClientPeg.get().getDeviceId() : null")
            return f'logged out {device}' if not still else f'still signed in {still}'
        except Exception as error:
            return 'error ' + str(error)[:120]

    async def shot(self, folder, name):
        try:
            await self.page.screenshot(path=str(folder / f'{name}-{self.label}.png'))
        except Exception:
            pass

    async def frames_offset(self, frame):
        x = y = 0.0
        while frame.parent_frame is not None:
            box = await (await frame.frame_element()).bounding_box()
            if not box:
                return None
            x, y = x + box['x'], y + box['y']
            frame = frame.parent_frame
        return x, y

    async def random_target(self, script, arg=None):
        frames = [f for f in self.page.frames if not f.is_detached()]
        random.shuffle(frames)
        frames.sort(key=lambda f: f.parent_frame is None)  # Child frames first, for Collabora and Jitsi.
        for frame in frames if random.random() < 0.6 else frames[::-1]:
            try:
                # A frame that still loads can hold an evaluate call for a long time, so each call has a limit.
                found = await asyncio.wait_for(frame.evaluate(script, arg) if arg is not None else frame.evaluate(script), 3)
                if not found:
                    continue
                offset = await asyncio.wait_for(self.frames_offset(frame), 3)
                if offset is None:
                    continue
                pick = random.choice(found)
                return pick['x'] + offset[0], pick['y'] + offset[1], pick.get('d', '')
            except Exception:
                continue
        return None

    async def action(self, folder):
        roll = random.random()
        page = self.page
        if roll < 0.55:
            extra = EXTRA_DENY.get(self.app)
            target = await self.random_target(CANDIDATES_JS, DENY.pattern + ('|' + extra.pattern if extra else ''))
            if target:
                await page.mouse.click(target[0], target[1])
                self.count('clicks')
        elif roll < 0.67:
            target = await self.random_target(INPUTS_JS)
            if target:
                await page.mouse.click(target[0], target[1])
                await page.keyboard.type(' '.join(random.choices(WORDS, k=random.randint(1, 6))), delay=15)
                if random.random() < 0.5:
                    await page.keyboard.press('Enter')
                self.count('typing')
        elif roll < 0.74:
            for frame in page.frames:
                try:
                    inputs = frame.locator('input[type=file]')
                    if await asyncio.wait_for(inputs.count(), 3):
                        path = upload_file(folder)
                        await inputs.first.set_input_files(str(path))
                        self.count('uploads')
                        self.count('upload_bytes', path.stat().st_size)
                        path.unlink()
                        break
                except Exception:
                    self.count('upload_errors')
        elif roll < 0.81:
            await page.go_back(wait_until='domcontentloaded', timeout=20_000)
            self.count('back')
        elif roll < 0.86:
            await page.reload(wait_until='domcontentloaded', timeout=30_000)
            self.count('reloads')
        elif roll < 0.93:
            await page.mouse.wheel(0, random.choice([-600, 400, 800]))
            self.count('scrolls')
        elif roll < 0.97:
            await page.keyboard.press(random.choice(['Escape', 'Escape', 'Enter', 'Tab']))
            self.count('keys')
        else:
            await page.goto(getattr(self, 'start_url', None) or APPS[self.app], wait_until='domcontentloaded', timeout=30_000)
            self.count('home')

    async def exercise(self, app, seconds, folder):
        self.app = app
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                await asyncio.wait_for(self.action(folder), timeout=max(1.0, min(25.0, end - time.monotonic())))
                self.count('actions')
            except Exception:
                self.count('action_errors')
            # A person pauses between actions. The pause also lets a page react to the last action.
            await asyncio.sleep(random.uniform(0.4, 2.0))
            host = self.page.url.split('/')[2] if '://' in self.page.url else ''
            if not host.endswith(DOMAIN):
                self.count('left_zone')
                try:
                    await self.page.goto(APPS[app], wait_until='domcontentloaded', timeout=30_000)
                except Exception:
                    pass


async def bounded(coroutine, seconds):
    """Run one tab step with a time limit, so that a hung request cannot stop the whole run."""
    try:
        return await asyncio.wait_for(coroutine, seconds)
    except Exception as error:
        return f'stopped: {type(error).__name__}'


def remote_time():
    import subprocess
    if not os.environ.get('LOAD_HOST'):
        return 0
    local = time.time()
    remote = float(subprocess.run(['ssh', '-o', 'BatchMode=yes', os.environ['LOAD_HOST'], 'date +%s.%N'], capture_output=True, text=True, timeout=30).stdout)
    return remote - (local + time.time()) / 2


async def main():
    mode = sys.argv[1]
    args = [a for a in sys.argv[2:] if not a.startswith('--')]
    seconds = int(sys.argv[sys.argv.index('--seconds') + 1]) if '--seconds' in sys.argv else 60
    users = logins()
    if '--users' in sys.argv:
        users = users[:int(sys.argv[sys.argv.index('--users') + 1])]
    if '--seconds' in sys.argv:
        args = [a for a in args if a != str(seconds)]
    per_user = int(sys.argv[sys.argv.index('--tabs') + 1]) if '--tabs' in sys.argv else 1
    for flag in ('--users', '--pre', '--tabs'):
        if flag in sys.argv:
            args = [a for a in args if a != sys.argv[sys.argv.index(flag) + 1]]
    stamp = time.strftime('%Y%m%dT%H%M%S')
    out = settings.PRIVATE / 'load' / f'load-{stamp}'
    out.mkdir(parents=True, exist_ok=True)
    uploads = out / 'uploads'
    uploads.mkdir(exist_ok=True)
    result = {'started': time.time(), 'clock_offset': remote_time(), 'users': [u for u, _ in users], 'phases': []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                           args=['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
                                                 '--autoplay-policy=no-user-gesture-required'])
        if mode == 'explore':
            app = args[0]
            user = [u for u in users if u[0] == (args[1] if len(args) > 1 else 'gabriel')][0]
            tab = Tab(browser, *user, out)
            await tab.open()
            print('ready', app, ready(APPS[app]), flush=True)
            if '--pre' in sys.argv:
                print('pre', await tab.sign_in(sys.argv[sys.argv.index('--pre') + 1]), flush=True)
            took = await tab.sign_in(app, shots=out)
            print('sign-in', took, tab.page.url.split('?')[0], flush=True)  # The query can hold a token.
            await tab.shot(out, f'{app}-signed-in')
            await tab.exercise(app, seconds if '--seconds' in sys.argv else 20, uploads)
            await tab.shot(out, f'{app}-after')
            print('finish', await tab.finish(app), flush=True)
            print(json.dumps(tab.stats), flush=True)
            print(out)
            return
        tabs = [Tab(browser, u, p, out, f'{u}-{i}' if per_user > 1 else u) for u, p in users for i in range(per_user)]
        for tab in tabs:
            await tab.open()
        for app in args or ORDER:
            phase = {'app': app, 'ready_start': time.time()}
            phase['ready_seconds'] = await asyncio.to_thread(ready, APPS[app])
            print(app, 'ready after', phase['ready_seconds'], flush=True)
            if app == 'office':
                # Collabora answers on its own address, and a document open is its first request.
                phase['office_ready_seconds'] = await asyncio.to_thread(ready, f'https://office.{DOMAIN}/hosting/discovery')
            signed = await asyncio.gather(*(bounded(t.sign_in(app), 420) for t in tabs))
            phase['sign_in_seconds'] = dict(zip([t.label for t in tabs], signed))
            print(app, 'signed in', phase['sign_in_seconds'], flush=True)
            for t in tabs:
                t.stats = {}
            phase['start'] = time.time()
            await asyncio.gather(*(bounded(t.exercise(app, seconds, uploads), seconds + 60) for t in tabs if t.page))
            phase['end'] = time.time()
            phase['tabs'] = {t.label: t.stats for t in tabs}
            for t in tabs:
                await t.shot(out, f'{app}-end')
            phase['finish'] = dict(zip([t.label for t in tabs], await asyncio.gather(*(bounded(t.finish(app), 90) for t in tabs))))
            result['phases'].append(phase)
            (out / 'driver.json').write_text(json.dumps(result, indent=1))
            print(app, 'done', {u: s.get('actions') for u, s in phase['tabs'].items()}, flush=True)
            await asyncio.sleep(20)
        await browser.close()
    result['ended'] = time.time()
    (out / 'driver.json').write_text(json.dumps(result, indent=1))
    print(out)


if __name__ == '__main__':
    asyncio.run(main())
