#!/usr/bin/env python3
"""Create a zone and delete it again through the operator website in a browser. Usage: operator-zone-check.py [zone] [--delete-only]

The browser signs in to the operator website as admin and sends the create form for the zone.
It waits until the operation is done, opens the onboarding login and signs in to the zone portal with it.
Then it deletes the zone through the delete button and waits until that operation is done.
--delete-only signs in and deletes the zone, for example after a create that failed.
After the delete the check reads the cluster and the host files for any part of the zone that is left.
The check writes k3s/private/checks/operator-zone-check.json and screenshots. It prints no password.
Run it with the browser Python environment in k3s/private/browser-venv, which has nodriver.
"""
import asyncio,base64,json,os,pathlib,re,subprocess,sys,time
root=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
OUT=settings.PRIVATE/'checks';OUT.mkdir(parents=True,exist_ok=True)
settings.use_kubeconfig()
sys.path.insert(0,str(settings.HOOVER4/'website/tools'))
from browser_lifecycle import start_browser,stop_browser
args=[a for a in sys.argv[1:] if not a.startswith('--')];zone=args[0] if args else 'zone-c';DELETE_ONLY='--delete-only' in sys.argv
BASE=f'https://operator.{settings.SUFFIX}'
result={'zone':zone}
def kubectl(*args):return subprocess.run(['kubectl',*args],capture_output=True,text=True)
async def operation(tab,kind,timeout):
 """Wait until the newest operation of this kind for the zone is done or failed, and return it."""
 deadline=time.time()+timeout
 while time.time()<deadline:
  data=json.loads(await tab.evaluate("fetch('/zones.json').then(r=>r.text())",await_promise=True))
  ops=[o for o in data['operations'] if o['kind']==kind and o['zone']==zone]
  if ops and ops[0]['state'] in ('done','failed'):return ops[0]
  await asyncio.sleep(30)
 raise SystemExit(f'{kind} {zone} did not finish in {timeout} s')
async def click(tab,label):
 found=await tab.evaluate(f"""(() => {{
  const row = [...document.querySelectorAll('#zones tr')].find(r => r.querySelector('a')?.textContent === {json.dumps(zone)});
  const b = row && [...row.querySelectorAll('button')].find(b => b.textContent === {json.dumps(label)});
  if (b) b.click(); return !!b; }})()""")
 if not found:raise SystemExit(f'no button {label!r} for {zone}')
def leftovers():
 """Return each part of the zone that is still present after the delete."""
 left={}
 if kubectl('get','namespace',zone).returncode==0:left['namespace']=True
 # The zone stores and their volumes go with the zone namespace. A TopoLVM volume of the zone must be gone too.
 volumes=kubectl('get','logicalvolumes.topolvm.io','-o','json').stdout
 if volumes and zone in volumes:left['volumes']=True
 if (settings.PRIVATE/'zones'/zone).exists():left['files']=True
 if zone in json.loads((settings.PRIVATE/'zones/secrets.json').read_text()):left['secrets']=True
 if zone in (settings.PRIVATE/'frontend/Caddyfile').read_text():left['frontend_sites']=True
 livekit=subprocess.run(['kubectl','-n','calls','get','secret','livekit','-o','jsonpath={.data.config\\.yaml}'],capture_output=True,text=True).stdout
 if zone in base64.b64decode(livekit).decode():left['livekit_key']=True
 return left
def finish():
 result['left_after_delete']=leftovers()
 deleted=result.get('delete',{}).get('state')=='done' and not result['left_after_delete']
 result['passed']=deleted if DELETE_ONLY else deleted and result.get('create',{}).get('state')=='done' and result['zone_portal']['signed_in']
 (OUT/f"operator-zone-check{'-delete' if DELETE_ONLY else ''}.json").write_text(json.dumps(result,indent=1)+'\n');print(json.dumps(result))
async def delete(tab):
 # The delete button asks for the zone name in a prompt, so the page gets the answer first.
 await tab.evaluate(f"window.prompt = () => {json.dumps(zone)}")
 started=time.time();await click(tab,'Delete the zone');await asyncio.sleep(3)
 delete=await operation(tab,'delete-zone',3600)
 result['delete']={'state':delete['state'],'error':delete['error'],'minutes':round((time.time()-started)/60,1),'steps':json.loads(delete['steps'])}
 await tab.reload();await asyncio.sleep(5);await tab.save_screenshot(str(OUT/'operator-zone-deleted.png'))
async def main():
 browser=await start_browser(OUT/'browser.log',['--window-size=1400,1000'],timeout=45)
 try:
  tab=await browser.get(BASE+'/');await asyncio.sleep(3)
  await (await tab.select('input[name="login"]',timeout=20)).send_keys('admin')
  await (await tab.select('input[name="password"]',timeout=10)).send_keys('admin')
  await (await tab.select('button[type="submit"]',timeout=10)).click();await asyncio.sleep(5)
  if DELETE_ONLY:
   await delete(tab);return finish()
  started=time.time()
  data=json.loads(await tab.evaluate("fetch('/zones.json').then(r=>r.text())",await_promise=True))
  failed=[o for o in data['operations'] if o['kind']=='create-zone' and o['zone']==zone][:1]
  if failed and failed[0]['state']=='failed':
   # A failed create runs again from its first unfinished step through its Run again button.
   result['resumed']=failed[0]['name']
   await tab.evaluate(f"""[...document.querySelectorAll('#operations tr')].find(r => r.textContent.includes({json.dumps('create-zone '+zone)}))
    .querySelector('button').click()""")
  else:
   await (await tab.select('#create input[name="zone"]',timeout=20)).send_keys(zone)
   await (await tab.select('#create button',timeout=10)).click()
  await asyncio.sleep(3)
  result['create_message']=await tab.evaluate("document.getElementById('zones-status').textContent")
  create=await operation(tab,'create-zone',5400)
  result['create']={'state':create['state'],'error':create['error'],'minutes':round((time.time()-started)/60,1),'steps':json.loads(create['steps'])}
  await tab.save_screenshot(str(OUT/'operator-zone-created.png'))
  if create['state']!='done':raise SystemExit('the create failed: '+create['error'])
  await tab.reload();await asyncio.sleep(5)
  await click(tab,'Show the onboarding login');await asyncio.sleep(3)
  text=await tab.evaluate("document.getElementById('onboarding').textContent")
  password=re.search(r'password (\S+)\.$',text).group(1)
  result['onboarding']=text.replace(password,'<password>')
  portal=await browser.get(f'https://portal.{zone}.{settings.SUFFIX}/univention/oidc/?location=/univention/portal/',new_tab=True);await asyncio.sleep(5)
  await (await portal.select('input[name="username"]',timeout=60)).send_keys('Administrator')
  await (await portal.select('input[name="password"]',timeout=10)).send_keys(password)
  await (await portal.select('#kc-login',timeout=10)).click();await asyncio.sleep(10)
  result['zone_portal']={'url':await portal.evaluate('location.href'),'title':await portal.evaluate('document.title'),
   'signed_in':await portal.evaluate("document.body.innerText.includes('Administrator')")}
  await portal.save_screenshot(str(OUT/'operator-zone-portal.png'));await portal.close()
  await delete(tab)
 finally:await stop_browser(browser)
 finish()
asyncio.run(main())
