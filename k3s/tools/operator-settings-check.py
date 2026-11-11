#!/usr/bin/env python3
"""Exercise the settings page of the operator portal in a browser. Usage: operator-settings-check.py <phase> [args]

The browser signs in to the operator portal as admin and opens settings.html. The password comes from
k3s/private/operator-login/admin-password, else it is the development password. Each phase uses the page as an operator does.
  invalid <scope> <key> <value>     enter a value, Save, and expect a marked refusal and no new revision
  save <scope> <key> <value>        enter a value and Save. Expect a new revision in the pending table.
  apply [timeout]                   press Apply and wait until the operation succeeds or fails
  retry [timeout]                   press Retry on the failed operation and wait for its end
  abandon                           press Abandon on the failed operation
  default <scope> <key>             press Use default and Save
  show                              take a screenshot only
The check appends one result per run to k3s/private/checks/operator-settings-check.jsonl and writes a screenshot to
k3s/private/checks/operator-settings/<n>-<phase>.png. It prints no password.
Run it with the browser Python environment in k3s/private/browser-venv, which has nodriver.
"""
import asyncio
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import settings  # noqa: E402

sys.path.insert(0, str(settings.HOOVER4 / 'website/tools'))
from browser_lifecycle import start_browser, stop_browser  # noqa: E402

OUT = settings.PRIVATE / 'checks'
SHOTS = OUT / 'operator-settings'
SHOTS.mkdir(parents=True, exist_ok=True)
BASE = f'https://operator.{settings.SUFFIX}'


def password():
    path = settings.PRIVATE / 'operator-login/admin-password'
    return path.read_text().splitlines()[0] if path.exists() else 'admin'


async def js(tab, code):
    """Return the value of a page expression. nodriver returns some values, such as an empty string or an array, as a
    RemoteObject, so the page sends every value as JSON text."""
    text = await tab.evaluate(f'Promise.resolve({code}).then(v => JSON.stringify(v === undefined ? null : v))',
                              await_promise=True, return_by_value=True)
    if not isinstance(text, str):
        raise RuntimeError(f'the page script failed: {text}'[:300])
    return json.loads(text)


async def login(tab):
    for _ in range(60):
        await asyncio.sleep(1)
        url = await js(tab, 'location.href')
        if url.startswith(f'{BASE}/settings.html'):
            return
        if await js(tab, "!!document.querySelector('input[name=password]')"):
            await js(tab, f"""(() => {{
              const set = (el, v) => {{ Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v);
                el.dispatchEvent(new Event('input', {{bubbles: true}})); }};
              set(document.querySelector('input[name=login]'), 'admin');
              set(document.querySelector('input[name=password]'), {json.dumps(password())});
              document.querySelector('form').submit(); }})()""")
            await asyncio.sleep(3)
    raise SystemExit(f'the login did not reach {BASE}/settings.html')


async def state(tab):
    return json.loads(await js(tab, "fetch('/settings.json',{cache:'no-store'}).then(r => r.text())"))


async def show(tab, scope, key):
    await js(tab, f"""(() => {{ const s = document.getElementById('scope'); s.value = {json.dumps(scope)};
      s.dispatchEvent(new Event('input')); const f = document.getElementById('filter');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(f, {json.dumps(key)});
      f.dispatchEvent(new Event('input')); }})()""")
    await asyncio.sleep(1)


async def set_value(tab, key, value):
    ok = await js(tab, f"""(() => {{
      const row = [...document.querySelectorAll('#tables tr')].find(r => r.querySelector('td.key')?.firstChild?.textContent === {json.dumps(key)});
      if (!row) return false; const input = row.querySelector('input,select'); input.value = {json.dumps(value)};
      input.onchange(); return true; }})()""")
    if not ok:
        raise SystemExit(f'the page shows no row for {key}')


async def click(tab, selector_text):
    ok = await js(tab, f"""(() => {{ const b = [...document.querySelectorAll('button')].find(b => b.textContent === {json.dumps(selector_text)} && !b.disabled);
      if (b) b.click(); return !!b; }})()""")
    if not ok:
        raise SystemExit(f'the page has no enabled button {selector_text!r}')


async def wait_operation(tab, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = await state(tab)
        op = data['active'] or (data['operations'] or [None])[0]
        if op and op['status'] in ('succeeded', 'failed', 'abandoned') and not (data['active'] and op['status'] != 'failed'):
            return op
        await asyncio.sleep(5)
    raise SystemExit(f'the operation did not end in {timeout} s')


async def main(argv):
    phase, args = argv[0], argv[1:]
    browser = await start_browser(OUT / 'operator-settings-browser.log', ['--window-size=1400,1000'], timeout=45)
    result = {'phase': phase, 'args': args if phase not in ('invalid', 'save') else args, 'time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    try:
        tab = await browser.get(f'{BASE}/settings.html')
        await login(tab)
        await asyncio.sleep(2)
        before = await state(tab)
        result['revision_before'] = before['revision']
        result['applied_before'] = before['applied']['revision']
        if phase in ('invalid', 'save'):
            scope, key, value = args
            await show(tab, scope, key)
            await set_value(tab, key, value)
            await click(tab, 'Save')
            await asyncio.sleep(2)
            result['message'] = await js(tab, "document.getElementById('save-result').textContent")
            result['marked'] = await js(tab, "[...document.querySelectorAll('.problem')].map(p => p.textContent)")
        elif phase == 'default':
            scope, key = args
            await show(tab, scope, key)
            await click(tab, 'Use default')
            await click(tab, 'Save')
            await asyncio.sleep(2)
            result['message'] = await js(tab, "document.getElementById('save-result').textContent")
        elif phase in ('apply', 'retry'):
            await click(tab, 'Apply' if phase == 'apply' else 'Retry')
            await asyncio.sleep(3)
            op = await wait_operation(tab, int(args[0]) if args else 1200)
            await asyncio.sleep(6)
            result['operation'] = {k: op[k] for k in ('id', 'status', 'error', 'revision', 'attempts', 'changed')}
            result['steps'] = [(s['name'], s['status']) for s in op['steps']]
            result['alert'] = await js(tab, "document.querySelector('[role=alert]')?.textContent || ''")
        elif phase == 'abandon':
            await click(tab, 'Abandon')
            await asyncio.sleep(3)
        after = await state(tab)
        result['revision_after'] = after['revision']
        result['applied_after'] = after['applied']['revision']
        result['pending'] = after['pending']
        result['services'] = after['services']
        result['summary'] = await js(tab, "document.getElementById('summary').textContent")
        count = len(list(SHOTS.glob('*.png'))) + 1
        shot = SHOTS / f'{count:02d}-{phase}.png'
        await tab.save_screenshot(str(shot), full_page=True)
        result['screenshot'] = str(shot)
    finally:
        await stop_browser(browser)
    with open(OUT / 'operator-settings-check.jsonl', 'a') as f:
        f.write(json.dumps(result) + '\n')
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    if not sys.argv[1:]:
        raise SystemExit(__doc__)
    asyncio.run(main(sys.argv[1:]))
