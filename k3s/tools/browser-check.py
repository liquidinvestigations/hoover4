#!/usr/bin/env python3
"""Sign in once through the operator portal and open each tool from its link."""
import asyncio,json,pathlib,sys
root=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
OUT=settings.PRIVATE/'checks';OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(settings.HOOVER4/'website/tools'))
from browser_lifecycle import start_browser,stop_browser
PAGE='JSON.stringify({url:location.href,title:document.title,text:document.body.innerText.slice(0,10000),passwords:document.querySelectorAll("input[type=password]").length})'
TOOLS=[('headlamp','Open Headlamp.','/headlamp/c/main/deployments?namespace=kube-system','coredns'),('grafana','Open Grafana.','/grafana/explore','Explore'),('prometheus','Open Prometheus targets.','/prometheus/targets','kubelet')]
async def page(tab):return json.loads(await tab.evaluate(PAGE))
async def main():
 browser=await start_browser(OUT/'browser.log',['--window-size=1400,900','--ignore-certificate-errors'],timeout=45)
 results={}
 try:
  tab=await browser.get(f'https://operator.{settings.SUFFIX}/');await asyncio.sleep(2)
  results['login']=await page(tab);assert 'Username' in results['login']['text'],results['login']
  await tab.save_screenshot(str(OUT/'operator-login.png'))
  await (await tab.select('input[name="login"]',timeout=10)).send_keys('admin')
  await (await tab.select('input[name="password"]',timeout=10)).send_keys('admin')
  await (await tab.select('button[type="submit"]',timeout=10)).click();await asyncio.sleep(7)
  results['portal']=await page(tab);assert 'GiB' in results['portal']['text'],results['portal']
  await tab.save_screenshot(str(OUT/'portal.png'))
  for name,link,path,marker in TOOLS:
   tab=await browser.get(f'https://operator.{settings.SUFFIX}/');await asyncio.sleep(2)
   await (await tab.find(link,best_match=True)).click();await asyncio.sleep(6)
   results[name]=await page(tab)
   await tab.save_screenshot(str(OUT/f'{name}.png'))
   tab=await browser.get(f'https://operator.{settings.SUFFIX}'+path);await asyncio.sleep(6)
   results[name+' detail']=await page(tab)
   await tab.save_screenshot(str(OUT/f'{name}-detail.png'))
   for key in (name,name+' detail'):
    assert results[key]['passwords']==0 and '/dex/' not in results[key]['url'],(key,results[key]['url'])
   assert marker in results[name+' detail']['text'],(name,results[name+' detail']['text'][:500])
 finally:
  (OUT/'browser-pages.json').write_text(json.dumps(results,indent=2))
  await stop_browser(browser)
 print(json.dumps({k:{'url':v['url'],'title':v['title'],'passwords':v['passwords']} for k,v in results.items()},indent=1))
asyncio.run(main())
