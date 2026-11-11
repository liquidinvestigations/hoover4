#!/usr/bin/env python3
"""Apply the zone changes that the Helm render cannot hold. Usage: zone-patches.py <zone>

zone.py runs this script after each Helm pass. postrender.py holds every change of a rendered object. This script holds
the changes of application state. Each change checks the current state first, so a second run changes nothing.

- zone-ai.py sets the Collabora AI URL without the trailing slash that the openDesk template adds.
- nextcloud-ai.py adds the task worker sidecar of the Nextcloud Assistant and stores the provider settings.
- XWiki stores the new LDAP group job schedule at its first start, but its scheduler has already read the old one.
  The script restarts XWiki once in that case, waits until Administrator is in XWikiAdminGroup, and runs xwiki-ai.sh.
- zone-jobs.py shortens the Nextcloud LDAP sync times and runs its first sync.
- Nextcloud keeps the first Collabora discovery answer in its app data, with no expiry. An answer from before Collabora
  was ready is empty, and each document open then fails with HTTP 500. The script fetches it again after Collabora is
  Ready and keeps the callback address.
The three AI steps run only when k3s/private/ai.json exists.
The script prints one JSON line for each change it makes.
"""
import json,os,pathlib,subprocess,sys,time
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
lab=pathlib.Path(__file__).resolve().parent;settings.use_kubeconfig()
zone=sys.argv[1]
def kubectl(*args,data=None):return subprocess.run(['kubectl','-n',zone,*args],input=data,text=True,check=True,capture_output=True).stdout
def get(ref):return json.loads(kubectl('get',ref,'-o','json'))
def psql(database,query):
 # The zone PostgreSQL runs in the zone namespace. The superuser connects through the local socket.
 return subprocess.run(['kubectl','-n',zone,'exec','statefulset/postgresql','-c','postgresql','--','psql','-U','postgres','-d',database,'-Atc',query],
  check=True,capture_output=True,text=True).stdout
def xwiki_admin():
 database='xwiki'
 cron=psql(database,"select s.xws_value from xwikiobjects o join xwikistrings s on s.xws_id=o.xwo_id where o.xwo_name='LDAPUserImport.LDAPGroupImportJob' and o.xwo_classname='XWiki.SchedulerJobClass' and s.xws_name='cron'").strip()
 log=subprocess.run(['kubectl','-n',zone,'logs','xwiki-0','-c','xwiki'],capture_output=True,text=True).stdout
 # The scheduler reads each job at start, so the stored schedule takes effect only at the next start.
 if 'SchedulerJobClass.cron] to value' in log:
  kubectl('rollout','restart','statefulset/xwiki');kubectl('rollout','status','statefulset/xwiki','--timeout=900s')
  print(json.dumps({'zone':zone,'workload':'statefulset/xwiki','change':f'restart for the group job schedule {cron}'}),flush=True)
 member="select 1 from xwikiobjects o join xwikistrings s on s.xws_id=o.xwo_id where o.xwo_name='XWiki.XWikiAdminGroup' and s.xws_name='member' and s.xws_value='XWiki.Administrator'"
 for _ in range(60):
  if psql(database,member).strip():return
  time.sleep(5)
 sys.exit('Administrator did not join XWikiAdminGroup in 5 minutes')
DISCOVERY=('require "/var/www/html/lib/base.php"; $d=\\OCP\\Server::get(\\OCA\\Richdocuments\\Service\\DiscoveryService::class)->get();'
 ' echo ($d && @simplexml_load_string($d)!==false) ? "valid" : "invalid";')
def nextcloud(*args):return kubectl('exec','deploy/opendesk-nextcloud-aio','-c','aio','--',*args).strip()
def discovery_valid():return nextcloud('php','-r',DISCOVERY).splitlines()[-1:]==['valid']
def office_discovery():
 kubectl('rollout','status','deployment/collabora','--timeout=900s')
 if discovery_valid():return
 callback=nextcloud('php','/var/www/html/occ','config:app:get','richdocuments','wopi_callback_url')
 nextcloud('php','/var/www/html/occ','richdocuments:activate-config',f'--callback-url={callback}')
 if not discovery_valid():sys.exit('Nextcloud did not get a valid Collabora discovery')
 print(json.dumps({'zone':zone,'change':'Collabora discovery fetched again'}),flush=True)
# A host without private/ai.json keeps the empty AI values that zones.py renders.
if (settings.PRIVATE/'ai.json').exists():
 subprocess.run([sys.executable,str(lab/'zone-ai.py'),zone],check=True,stdout=subprocess.DEVNULL)
 print(json.dumps({'zone':zone,'change':'AI settings from private/ai.json'}),flush=True)
if (settings.PRIVATE/'ai.json').exists():subprocess.run([sys.executable,str(lab/'nextcloud-ai.py'),zone],check=True)
xwiki_admin()
if (settings.PRIVATE/'ai.json').exists():subprocess.run(['bash',str(lab/'xwiki-ai.sh'),zone],check=True)
office_discovery()
subprocess.run([sys.executable,str(lab/'zone-jobs.py'),zone],check=True)
