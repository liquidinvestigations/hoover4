#!/usr/bin/env python3
"""Run the zone operations that the operator website records. Usage: runner.py [--once]
The runner also starts the next due backup job once a minute (../backups/backups.py). Backups stay off until the site file
names a destination and an operator turns a backup policy on.

The portal writes each operation as a ConfigMap with the label hoover.dev/operation in the namespace operator-portal.
The runner is the container runner of the operator pod (operator-login.yaml, pod.py). Its state folder is a folder of
the pod, and the cluster holds the authoritative copy of the zone state, the zone secrets and the operator state
(../../clusterstate.py). Before each operation it reads the cluster copy, and after each step it writes its changes
back. The openDesk release and the Helm tools are in the image.
The runner uses the token of the ServiceAccount zone-runner (runner-rights.yaml). It can change the zone namespaces,
the shared call services, the operation ConfigMaps and the cluster copy of the state only.
It also runs the settings Apply operations of the operator state (apply.py), one at a time.
The operations and their steps:
  create-zone   register (zone state), frontend, install (zone.py apply), calls
  upgrade-zone  frontend, install, calls
  delete-zone   delete (zone.py delete), calls
The HTTPS frontend runs outside the cluster and serves every zone host <zone>-<app>.<suffix> with the certificate of
*.<suffix>, so no zone operation changes it. The step frontend checks that the frontend answers for the portal host of
the zone with a valid certificate, because the install needs the zone hosts. When it does not, the operation fails at
this step, and the message names deploy-k3s up --steps frontend on the operator workstation. Run again then continues at
this step.
The runner runs one operation at a time, oldest first, while it holds the site operation lock (../../oplock.py). It
records each finished step in the ConfigMap, so after a restart or a retry it continues at the first unfinished step.
Each step can run again without a different result.
The command output of each operation goes to <state folder>/operations/<operation>.log, which the cluster copy keeps.
The ConfigMap keeps its last lines, which name no secret, because the install scripts print none.
--once runs the queued operations and exits.
"""
import json,subprocess,sys,time,traceback
from pathlib import Path
# The commands of the steps run in the source folder.
source=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(source));import settings
settings.use_kubeconfig()
sys.path.insert(0,str(source/'zones'));import zones,zonestate
import clusterstate
NS='operator-portal';LABEL='hoover.dev/operation'
LOGS=settings.PRIVATE/'operations'
STEPS={'create-zone':['register','frontend','install','calls'],
 'upgrade-zone':['frontend','install','calls'],
 'delete-zone':['delete','calls']}
def kubectl(*args,data=None,check=True):return subprocess.run(['kubectl',*args],input=data,text=True,capture_output=True,check=check).stdout
def operations():
 items=json.loads(kubectl('-n',NS,'get','configmap','-l',LABEL,'-o','json'))['items']
 return sorted(items,key=lambda i:i['metadata']['creationTimestamp'])
def save(op,**data):
 op['data'].update(data)
 kubectl('-n',NS,'patch','configmap',op['metadata']['name'],'--type','merge','-p',json.dumps({'data':data}))
def now():return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
class Operation:
 def __init__(self,op):
  self.op=op;self.name=op['metadata']['name'];d=op['data']
  # An operation of an earlier version can name a home node. It has no effect.
  self.kind=d.get('kind');self.zone=d.get('zone','')
  LOGS.mkdir(parents=True,exist_ok=True);self.log=LOGS/f'{self.name}.log'
 def run(self,*command,data=None):
  """Run a command, append its output to the operation log, and copy the last lines to the ConfigMap every 10 s."""
  with open(self.log,'a') as out:
   out.write(f'$ {" ".join(map(str,command))}\n');out.flush()
   process=subprocess.Popen(command,cwd=source,stdin=subprocess.PIPE if data else subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,text=True)
   if data:process.stdin.write(data);process.stdin.close()
   while process.poll() is None:
    time.sleep(10);self.tail()
  self.tail()
  if process.returncode:raise RuntimeError(f'{" ".join(map(str,command))} exited with {process.returncode}')
 def tail(self):
  lines=self.log.read_text(errors='replace').splitlines()[-40:] if self.log.exists() else []
  save(self.op,log='\n'.join(line[:300] for line in lines),updated=now())
 def check(self):
  """Refuse an operation that the website must not send. Only a new operation needs the zone state check."""
  if self.kind not in STEPS:raise ValueError(f'unknown operation kind {self.kind!r}')
  if not zones.ZONE_NAME.fullmatch(self.zone):raise ValueError('a zone name is zone- and 1 to 12 lower-case letters or digits')
  started=any(s['state']=='done' for s in json.loads(self.op['data'].get('steps','[]')))
  names=zones.zone_names()
  if not started and self.kind=='create-zone' and self.zone in names:raise ValueError(f'{self.zone} exists')
  if not started and self.kind!='create-zone' and self.zone not in names:raise ValueError(f'{self.zone} does not exist')
 def execute(self):
  steps=json.loads(self.op['data'].get('steps') or 'null') or [{'name':n,'state':'pending'} for n in STEPS.get(self.kind,[])]
  save(self.op,state='running',steps=json.dumps(steps),error='')
  try:
   self.check()
   for step in steps:
    if step['state'] in ('done','skipped'):continue
    step.update(state='running',started=now());save(self.op,steps=json.dumps(steps),step=step['name'])
    warning=getattr(self,'step_'+step['name'])()
    step.update(state='skipped' if warning else 'done',finished=now());save(self.op,steps=json.dumps(steps),**({'warning':warning} if warning else {}))
    sync('push')
   save(self.op,state='done',step='',finished=now())
  except Exception as error:
   for step in steps:
    if step['state']=='running':step.update(state='failed')
   with open(self.log,'a') as out:out.write(traceback.format_exc())
   save(self.op,state='failed',steps=json.dumps(steps),error=str(error)[:500]);self.tail()
   try:sync('push')
   except Exception as sync_error:print(json.dumps({'state_error':str(sync_error)[:300]}),flush=True)
 def step_register(self):
  # zone.py register adds the zone to the zone state, so the frontend can serve its names before the install. The
  # zones need their names during the install.
  self.run(sys.executable,'-c','import sys;sys.path.insert(0,"zones");import zone;zone.register(sys.argv[1])',self.zone)
 def step_frontend(self):
  # The frontend runs on the public node outside the cluster, and the runner has no access there. The install needs
  # the zone hosts, so a create or upgrade checks that the frontend serves them. A delete operation of an earlier
  # version can still list this step, and it has nothing to check.
  if self.kind=='delete-zone':return
  problem=frontend_problem(self.zone)
  if problem:raise RuntimeError(f'The HTTPS frontend does not serve the hosts of {self.zone}: {problem}. Run deploy-k3s up '
   '--target <public node> --steps frontend on the operator workstation, then select Run again.')
 def step_install(self):self.run(sys.executable,'zones/zone.py','apply',self.zone)
 def step_calls(self):self.run(sys.executable,'platform/calls/install-calls.py')
 def step_delete(self):
  if self.zone in zones.zone_names():self.run(sys.executable,'zones/zone.py','delete',self.zone)
def frontend_problem(zone):
 """An empty text when the HTTPS frontend answers a TLS connection for <zone>-portal.<suffix> with a valid certificate."""
 import socket,ssl
 host=settings.zone_host(zone,'portal')
 context=ssl.create_default_context()
 ca=settings.PRIVATE/'frontend/local-ca.crt'
 if ca.exists():context.load_verify_locations(str(ca))
 try:
  with socket.create_connection((host,443),timeout=15) as raw,context.wrap_socket(raw,server_hostname=host):return ''
 except (OSError,ssl.SSLError) as error:return f'{host}: {error}'
WAITING={}
def site_lock(kind,operation_id):
 """Hold the site operation lock (../../oplock.py) for one operation, or return None while another operation holds it."""
 import oplock
 lock=oplock.site_lock(settings.SITE.operator_state())
 try:lock.acquire(kind,operation_id)
 except oplock.Busy as error:
  # The runner prints a wait once for each holder, not every 3 s.
  if WAITING.get(operation_id)!=str(error):print(json.dumps({'waiting':operation_id,'reason':str(error)[:300]}),flush=True)
  WAITING[operation_id]=str(error)
  return None
 try:sync('pull')
 except Exception:
  lock.release();raise
 return lock
def sync(direction):
 """Read or write the cluster copy of the state (../../clusterstate.py), when the runner runs in the operator pod."""
 if __import__('os').environ.get(clusterstate.ENV)!='1':return {}
 return getattr(clusterstate,direction)(settings.PRIVATE)
def settings_apply():
 """Run the active settings Apply of the operator state (apply.py). A failed Apply waits for a retry in the portal.
 The Apply waits while another site operation, for example deploy-k3s, holds the site lock."""
 sys.path.insert(0,str(source/'platform/operator'));import apply
 site=apply.site();state=apply.operator_settings.State(site.operator_state())
 op=state.active()
 if op is None or op.status not in ('running','queued'):return False
 lock=site_lock('apply',op.id)
 if lock is None:return False
 try:
  log=site.operator_state()/'logs'/f'{op.id}.log';log.parent.mkdir(parents=True,exist_ok=True)
  done=state.run(apply.executors(site,log))
  sync('push')
 finally:lock.release()
 print(json.dumps({'apply':done.id,'status':done.status,'error':done.error[:300]}),flush=True)
 return True
def backup_tick():
 """Start the next due backup job (../backups/backups.py). Backups stay off without vars.backup and the backup settings."""
 sys.path.insert(0,str(source/'platform/backups'));import backups
 result=backups.tick()
 if result.get('state') not in ('off','idle','paused'):print(json.dumps({'backups':result}),flush=True)
def main():
 once='--once' in sys.argv
 last_backup=0
 while True:
  try:
   if settings.SITE is not None and settings_apply():continue
  except Exception as error:print(json.dumps({'apply_error':str(error)[:300]}),flush=True)
  if settings.SITE is not None and time.time()-last_backup>=60:
   last_backup=time.time()
   try:backup_tick()
   except Exception as error:print(json.dumps({'backup_error':str(error)[:300]}),flush=True)
  try:
   items=operations()
   # A running operation is one that the runner was doing when it stopped, so it continues first.
   pending=[i for i in items if i['data'].get('state')=='running']+[i for i in items if i['data'].get('state')=='queued']
   if pending:
    lock=site_lock('zone-operation',pending[0]['metadata']['name']) if settings.SITE is not None else None
    if settings.SITE is None or lock is not None:
     try:Operation(pending[0]).execute()
     finally:
      if lock is not None:lock.release()
     continue
  except subprocess.CalledProcessError as error:print(json.dumps({'error':str(error)[:300]}),flush=True)
  if once:return
  time.sleep(3)
if __name__=='__main__':main()
