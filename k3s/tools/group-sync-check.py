#!/usr/bin/env python3
"""Measure how long an admin flag change in Nubus takes to reach each application. Usage: group-sync-check.py <zone>

The check turns on the four application admin flags of test.user, waits until each application shows the user as
admin, then turns them off and waits again. The check reads the admin state from the application databases, from MAS
for chat, and from occ in Nextcloud.
It writes k3s/private/checks/group-sync-check-<zone>.json and prints no credential. It exits with 1 when an
application does not follow the flag within the timeout.
"""
import json,pathlib,subprocess,sys,time,urllib.parse,urllib.request
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
sys.path.insert(0,str(settings.SOURCE/'zones'));import udm
OUT=settings.PRIVATE/'checks';OUT.mkdir(parents=True,exist_ok=True)
settings.use_kubeconfig()
zone=sys.argv[1]
FLAGS={'files':'opendeskFileshareAdmin','projects':'opendeskProjectmanagementAdmin','wiki':'opendeskKnowledgemanagementAdmin','chat':'opendeskLivecollaborationAdmin'}
URLS={'files':'files/status.php','projects':'projects/health_checks/default','wiki':'wiki/','chat':'chat/'}
TIMEOUT=600
def kubectl(*args,check=True):return subprocess.run(['kubectl',*args],check=check,capture_output=True,text=True).stdout
# Each zone has its own PostgreSQL from the openDesk chart, with one database for each application.
def psql(database,query):return kubectl('-n',zone,'exec','postgresql-0','-c','postgresql','--','psql','-U','postgres','-d',database,'-Atc',query).strip()
def aio_pod():
 pods=json.loads(kubectl('-n',zone,'get','pods','-o','json'))['items']
 return next((p['metadata']['name'] for p in pods if p['status'].get('phase')=='Running' and not p['metadata'].get('deletionTimestamp')
  and any(o['kind']=='ReplicaSet' and o['name'].startswith('opendesk-nextcloud-aio-') for o in p['metadata'].get('ownerReferences',[]))),None)
def nextcloud_uid():
 users=json.loads(kubectl('-n',zone,'exec',aio_pod(),'-c','aio','--','php','/var/www/html/occ','user:list','--output=json'))
 return next(uid for uid,name in users.items() if name.startswith('Test User'))
def admin(app,uid):
 """Return True or False for the admin state of test.user, or None when the application cannot answer now."""
 if app=='projects':value=psql('openproject',"select admin from users where login='test.user'");return {'t':True,'f':False}.get(value)
 if app=='wiki':
  return bool(psql('xwiki',"select 1 from xwikiobjects o join xwikistrings s on s.xws_id=o.xwo_id where o.xwo_name='XWiki.XWikiAdminGroup' and s.xws_name='member' and s.xws_value='XWiki.testuser'"))
 # MAS grants the Synapse admin right through can_request_admin. Synapse users.admin stays 0.
 if app=='chat':value=psql('matrix_authentication',"select can_request_admin from users where username='test.user'");return {'t':True,'f':False}.get(value)
 pod=aio_pod()
 if pod is None:return None
 out=subprocess.run(['kubectl','-n',zone,'exec',pod,'-c','aio','--','php','/var/www/html/occ','user:info',uid,'--output=json'],capture_output=True,text=True).stdout
 try:return 'managed-by-attribute-FileshareAdmin' in json.loads(out)['groups']
 except (ValueError,KeyError):return None
def request(app):
 # A browser request makes the application read the user again.
 try:urllib.request.urlopen(urllib.request.Request('https://'+URLS[app].replace('/',f'.{zone}.{settings.SUFFIX}/',1),headers={'User-Agent':'Mozilla/5.0 group-sync-check'}),timeout=60).read()
 except Exception:pass
def set_flags(value):
 call=udm.client(zone)
 dn=urllib.parse.quote(udm.user(call,'test.user')['dn'],safe='')
 _,headers,_=call('GET',f'users/user/{dn}')
 call('PATCH',f'users/user/{dn}',{'properties':{flag:value for flag in FLAGS.values()}},{'If-Match':headers.get('Etag','*')})
 return time.time()
def wait(value,uid,started):
 seconds={};pending=set(FLAGS)
 while pending and time.time()-started<TIMEOUT:
  for app in sorted(pending):
   if admin(app,uid)==value:seconds[app]=round(time.time()-started,1);pending.discard(app)
  time.sleep(2)
 return {**seconds,**{app:None for app in pending}}
for app in FLAGS:request(app)
for _ in range(120):
 if aio_pod():break
 time.sleep(5)
uid=nextcloud_uid();result={'zone':zone,'timeout_seconds':TIMEOUT}
for value,key in ((True,'on_seconds'),(False,'off_seconds')):
 started=set_flags(value);result[key]=wait(value,uid,started)
 for app in FLAGS:request(app)
path=OUT/f"group-sync-check-{zone}.json"
path.write_text(json.dumps(result,indent=1)+'\n');print(json.dumps(result))
# An application that did not follow the flag within the timeout fails the check.
sys.exit(1 if any(v is None for key in ('on_seconds','off_seconds') for v in result[key].values()) else 0)
