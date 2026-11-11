#!/usr/bin/env python3
"""Check the Nextcloud Assistant through HTTPS as test.user. Usage: nextcloud-ai-check.py [zone]

The script signs in through the Keycloak form and lists the task types that the Assistant can use.
It schedules one chat task (core:text2text:chat) and one text task (core:text2text) and polls each until it ends.
The taskprocessing worker sidecar runs the tasks. The script prints the times and the first part of each answer,
and no password.
"""
import html,http.cookiejar,json,pathlib,re,sys,time,urllib.error,urllib.parse,urllib.request
lab=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
OUT=settings.PRIVATE/'checks';OUT.mkdir(parents=True,exist_ok=True)
zone=sys.argv[1] if len(sys.argv)>1 else 'zone-a';base=f'https://files.{zone}.{settings.SUFFIX}'
jar=http.cookiejar.CookieJar();browser=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def ocs(method,path,body=None):
 request=urllib.request.Request(base+'/ocs/v2.php'+path,method=method,data=json.dumps(body).encode() if body is not None else None,
  headers={'OCS-APIRequest':'true','Accept':'application/json','Content-Type':'application/json'})
 with browser.open(request,timeout=120) as r:return json.loads(r.read())['ocs']['data']
# Nextcloud answers with an error page while it starts, so the sign-in waits until the login page comes.
for _ in range(60):
 try:
  with browser.open(base+'/apps/user_oidc/login/1',timeout=120) as r:page=r.read().decode()
  form=re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"',page)
  if form:break
 except urllib.error.HTTPError:pass
 time.sleep(5)
password=(settings.PRIVATE/f'zones/{zone}/test-user-password').read_text().strip()
browser.open(urllib.request.Request(html.unescape(form.group(1)),data=urllib.parse.urlencode({'username':'test.user','password':password,'credentialId':''}).encode()),timeout=120).read()
types=ocs('GET','/taskprocessing/tasktypes')['types']
result={'zone':zone,'task_types':sorted(t for t in types if t.startswith('core:text2text'))}
history=[{'role':'human','content':'Hello.'},{'role':'assistant','content':'Hello. How can I help?'}]
cases={'chat':('core:text2text:chat',{'system_prompt':'Answer in one sentence.','input':'What is openDesk?','history':[json.dumps(m) for m in history]}),
 'text':('core:text2text',{'input':'Write one sentence about a wiki.'})}
for name,(kind,task_input) in cases.items():
 if kind not in types:result[name]={'error':f'{kind} is not available'};continue
 start=time.monotonic();task=ocs('POST','/taskprocessing/schedule',{'type':kind,'appId':'assistant','customId':'hoover-check','input':task_input})['task']
 while task['status'] in ('STATUS_SCHEDULED','STATUS_RUNNING') and time.monotonic()-start<300:
  time.sleep(2);task=ocs('GET',f"/taskprocessing/task/{task['id']}")['task']
 result[name]={'status':task['status'],'seconds':round(time.monotonic()-start,1),'answer':str((task.get('output') or {}).get('output'))[:200],
  'error':task.get('errorMessage')}
 ocs('DELETE',f"/taskprocessing/task/{task['id']}")
print(json.dumps(result,indent=1))
(OUT/f'nextcloud-ai-check-{zone}.json').write_text(json.dumps(result,indent=1)+'\n')
