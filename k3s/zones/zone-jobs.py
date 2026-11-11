#!/usr/bin/env python3
"""Shorten the Nextcloud LDAP sync times of a zone, and run its first sync. Usage: zone-jobs.py <zone>

zone-patches.py runs this script after each zone install.
- Nextcloud keeps LDAP group members in its cache for 60 s instead of 600 s.
  Its group update job runs every 5 minutes instead of each hour.
  After a change the script runs cron.php once, so the first LDAP sync and group update run at install.
- postrender.py holds the schedule changes of the Element media cleanup and the OpenProject worker.
- XWiki needs no change here. zones.py runs its LDAP group jobs each minute.
  Its other jobs only send email, and the zones do not deliver email.
The script prints one JSON line for each change it makes. A second run changes nothing.
"""
import json,pathlib,subprocess,sys,time
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
lab=pathlib.Path(__file__).resolve().parent;settings.use_kubeconfig()
zone=sys.argv[1]
def kubectl(*args,data=None):return subprocess.run(['kubectl','-n',zone,*args],input=data,text=True,check=True,capture_output=True).stdout
def get(ref):return json.loads(kubectl('get',ref,'-o','json'))
def report(change,**fields):print(json.dumps({'zone':zone,**fields,'change':change}),flush=True)
def aio_pod():
 # The cron Job pods carry the same labels, so kubectl exec on the Deployment can reach a finished cron pod.
 pods=json.loads(kubectl('get','pods','-o','json'))['items']
 return next(p['metadata']['name'] for p in pods if p['status'].get('phase')=='Running' and not p['metadata'].get('deletionTimestamp')
  and any(o['kind']=='ReplicaSet' and o['name'].startswith('opendesk-nextcloud-aio-') for o in p['metadata'].get('ownerReferences',[])))
def occ(*args):return kubectl('exec',aio_pod(),'-c','aio','--','php','/var/www/html/occ',*args)
def nextcloud():
 kubectl('rollout','status','deployment/opendesk-nextcloud-aio','--timeout=900s')
 configs=json.loads(occ('ldap:show-config','--output=json'))
 changed=False
 for config,values in configs.items():
  if str(values.get('ldapCacheTTL'))!='60':occ('ldap:set-config',config,'ldapCacheTTL','60');report('LDAP cache 60 s',config=config);changed=True
 # config:app:get exits with 1 when the key is unset.
 current=subprocess.run(['kubectl','-n',zone,'exec',aio_pod(),'-c','aio','--','php','/var/www/html/occ','config:app:get','user_ldap','bgjRefreshInterval'],
  capture_output=True,text=True).stdout.strip()
 if current!='300':
  occ('config:app:set','user_ldap','bgjRefreshInterval','--value','300');report('LDAP group update every 300 s');changed=True
 if not changed:return
 # One cron.php run does the first LDAP user sync and group update, which otherwise wait for the next 5-minute run.
 name=f'hoover-setup-{int(time.time())}'
 kubectl('create','job',name,'--from=cronjob/opendesk-nextcloud-aio-cron')
 kubectl('wait',f'job/{name}','--for=condition=complete','--timeout=900s')
 kubectl('delete','job',name,'--wait=false');report('cron.php run',job=name)
nextcloud()
