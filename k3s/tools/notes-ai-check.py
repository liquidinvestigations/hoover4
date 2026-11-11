#!/usr/bin/env python3
"""Check the Notes AI features through HTTPS as test.user. Usage: notes-ai-check.py [zone]

The script signs in, creates a document, calls the legacy text action (ai-transform) and the BlockNote AI proxy,
and deletes the document again. The proxy request sends the BlockNote tool definition, so the model must return a
tool call. The script prints the times and the first part of each answer, and no password.
"""
import html,http.cookiejar,json,pathlib,re,sys,time,urllib.error,urllib.parse,urllib.request
lab=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
OUT=settings.PRIVATE/'checks';OUT.mkdir(parents=True,exist_ok=True)
zone=sys.argv[1] if len(sys.argv)>1 else 'zone-b';base=f'https://notes.{zone}.{settings.SUFFIX}'
jar=http.cookiejar.CookieJar();browser=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def call(method,path,body=None,raw=False):
 csrf=next((c.value for c in jar if c.name=='csrftoken'),'')
 request=urllib.request.Request(base+path,method=method,data=json.dumps(body).encode() if body is not None else None,
  headers={'Content-Type':'application/json','X-CSRFToken':csrf,'Referer':base+'/'})
 with browser.open(request,timeout=300) as r:return r.read() if raw else (json.loads(r.read() or b'null'))
with browser.open(base+'/api/v1.0/authenticate/',timeout=120) as r:page=r.read().decode()
form=re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"',page)
password=(settings.PRIVATE/f'zones/{zone}/test-user-password').read_text().strip()
browser.open(urllib.request.Request(html.unescape(form.group(1)),data=urllib.parse.urlencode({'username':'test.user','password':password,'credentialId':''}).encode()),timeout=120).read()
config=call('GET','/api/v1.0/config/')
result={'zone':zone,'config':{k:config.get(k) for k in ('AI_FEATURE_ENABLED','AI_FEATURE_BLOCKNOTE_ENABLED','AI_FEATURE_LEGACY_ENABLED','AI_BOT') if k in config}}
document=call('POST','/api/v1.0/documents/',{'title':'AI check'})
try:
 text='Notes is the collaborative editor of openDesk. It stores documents in PostgreSQL and S3, and it uses a WebSocket service for live editing.'
 start=time.monotonic();answer=call('POST',f"/api/v1.0/documents/{document['id']}/ai-transform/",{'action':'summarize','text':text})
 result['transform']={'seconds':round(time.monotonic()-start,2),'answer':str(answer.get('answer'))[:160]}
 tool={'applyDocumentOperations':{'name':'applyDocumentOperations','description':'Apply operations to the BlockNote document.',
  'inputSchema':{'type':'object','properties':{'operations':{'type':'array','items':{'type':'object'}}},'required':['operations']}}}
 message={'id':'m1','role':'user','parts':[{'type':'text','text':'Add a heading with the text Hello to the document.'}]}
 start=time.monotonic();stream=call('POST',f"/api/v1.0/documents/{document['id']}/ai-proxy/",{'trigger':'submit-message','id':'c1','messages':[message],'toolDefinitions':tool},raw=True).decode(errors='replace')
 events=[json.loads(l[6:]) for l in stream.splitlines() if l.startswith('data: {')]
 kinds=sorted({e.get('type') for e in events})
 tool_input=next((e.get('input') for e in events if e.get('type')=='tool-input-available'),None)
 result['proxy']={'seconds':round(time.monotonic()-start,2),'event_types':kinds,'tool_input':json.dumps(tool_input)[:200] if tool_input else None,
  'error':next((e.get('errorText') for e in events if e.get('type')=='error'),None)}
finally:call('DELETE',f"/api/v1.0/documents/{document['id']}/")
print(json.dumps(result,indent=1))
