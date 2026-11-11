#!/usr/bin/env python3
"""Run an XWiki script as the zone Administrator. Usage: xwiki-admin-script.py <zone> <script file> [name=value ...]

XWiki accepts the openDesk users only through OIDC, and openDesk turns the superadmin off.
So a browser signs in through the portal as Administrator and opens the wiki.
The script saves the file content as the hidden page Hoover.AdminScript, renders it, prints the result and deletes
the page. A page that Administrator saves runs with the programming right of Administrator.
Each name=value argument replaces the text @name@ in the file before the save. A value file:<path> reads the file.
A file that ends with .js runs as an async function body in the signed-in page instead, for REST reads.
Run it with the browser Python environment in k3s/private/browser-venv, which has nodriver.
"""
import asyncio,base64,json,os,pathlib,subprocess,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
settings.use_kubeconfig()
sys.path.insert(0,str(settings.HOOVER4/'website/tools'))
from browser_lifecycle import start_browser,stop_browser
zone,source=sys.argv[1:3];d=f'{zone}.{settings.SUFFIX}'
script=pathlib.Path(source).read_text()
for pair in sys.argv[3:]:
 name,value=pair.split('=',1)
 # A value that starts with file: comes from that file, so a key stays out of the command line.
 if value.startswith('file:'):value=pathlib.Path(value[5:]).read_text().strip()
 script=script.replace(f'@{name}@',value)
def secret(name,key):
 data=json.loads(subprocess.check_output(['kubectl','-n',zone,'get','secret',name,'-o','json'],text=True))['data'][key]
 return base64.b64decode(data).decode()
def wait():
 subprocess.run(['kubectl','-n',zone,'rollout','status','statefulset/xwiki','--timeout=600s'],check=True,stdout=subprocess.DEVNULL)
# The fetch calls run inside the signed-in page, so they carry the session cookie and the CSRF form token.
RUN='''(async () => {
 const token = document.documentElement.getAttribute('data-xwiki-form-token');
 const page = '/rest/wikis/xwiki/spaces/Hoover/pages/AdminScript';
 const body = new URLSearchParams({title: 'Admin script', content: %s, hidden: 'true'});
 const put = await fetch(page, {method: 'PUT', body, headers: {'XWiki-Form-Token': token, 'Accept': 'application/json'}});
 if (put.status >= 300) return JSON.stringify({error: 'save', status: put.status, text: (await put.text()).slice(0, 500)});
 const saved = await put.json();
 const run = await fetch('/bin/get/Hoover/AdminScript?outputSyntax=plain');
 const text = await run.text();
 await fetch(page, {method: 'DELETE', headers: {'XWiki-Form-Token': token}});
 return JSON.stringify({status: run.status, text, author: saved.author, user: document.documentElement.getAttribute('data-xwiki-user-reference')});
})()'''
async def main():
 wait()
 password=secret('ums-nubus-credentials','administrator_password')
 browser=await start_browser(settings.PRIVATE/'browser.log',['--window-size=1400,900'],timeout=45)
 try:
  tab=await browser.get(f'https://portal.{d}/univention/oidc/?location=/univention/portal/');await asyncio.sleep(4)
  await (await tab.select('input[name="username"]',timeout=20)).send_keys('Administrator')
  await (await tab.select('input[name="password"]',timeout=10)).send_keys(password)
  await (await tab.select('#kc-login',timeout=10)).click();await asyncio.sleep(6)
  # Parallel OIDC callbacks can lose the session and leave the page without a user.
  # The script opens the wiki again until the page shows the signed-in user.
  user=''
  for _ in range(6):
   await tab.get(f'https://wiki.{d}/bin/view/Main/')
   for _ in range(15):
    await asyncio.sleep(2)
    user=await tab.evaluate("document.documentElement.getAttribute('data-xwiki-user-reference')||''")
    if user:break
   if user:break
  if not user:sys.exit('the browser is not signed in to the wiki')
  if source.endswith('.js'):
   # A .js file runs as an async function body in the signed-in page. It returns the text to print.
   print(await tab.evaluate('(async () => {'+script+'})()',await_promise=True));return
  result=json.loads(await tab.evaluate(RUN%json.dumps(script),await_promise=True))
  if os.environ.get('XWIKI_SCRIPT_DEBUG'):print(json.dumps({k:result.get(k) for k in ('author','user','status')}))
  print(result.get('text') if 'text' in result else json.dumps(result))
  if result.get('status',0)>=300 or 'error' in result:sys.exit(1)
 finally:await stop_browser(browser)
asyncio.run(main())
