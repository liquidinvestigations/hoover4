#!/usr/bin/env python3
"""Run the zone operations that the operator website records. Usage: runner.py [--once]

The portal writes each operation as a ConfigMap with the label hoover.dev/operation in the namespace operator-portal.
The runner runs on the operator host, which holds k3s/private: the zone state, the zone secrets, the openDesk
release and the Helm tools. install-runner.sh starts it as a systemd user service.
The runner uses the kubeconfig of the ServiceAccount zone-runner (runner-rights.yaml). It can change the zone
namespaces, the shared call services and the operation ConfigMaps only. It updates the HTTPS frontend through an SSH
key that can run only /opt/hoover-frontend/sync on the public host, and it sends that script only the zone names.
The operations and their steps:
  create-zone   register (zone state with the home node), frontend, install (zone.py apply), calls
  upgrade-zone  frontend, install, calls
  delete-zone   delete (zone.py delete), frontend, calls
The runner runs one operation at a time, oldest first. It records each finished step in the ConfigMap, so after a
restart or a retry it continues at the first unfinished step. Each step can run again without a different result.
The command output of each operation goes to k3s/private/operations/<operation>.log. The ConfigMap keeps its last
lines, which name no secret, because the install scripts print none.
--once runs the queued operations and exits.
"""
import json,subprocess,sys,time,traceback
from pathlib import Path
# The commands of the steps run in the source folder.
source=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(source));import settings
settings.use_kubeconfig()
sys.path.insert(0,str(source/'zones'));import zones,zonestate
NS='operator-portal';LABEL='hoover.dev/operation'
LOGS=settings.PRIVATE/'operations'
KEY=settings.PRIVATE/'operator-runner/ssh-key'
STEPS={'create-zone':['register','frontend','install','calls'],
 'upgrade-zone':['frontend','install','calls'],
 'delete-zone':['delete','frontend','calls']}
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
  self.kind=d.get('kind');self.zone=d.get('zone','');self.home=d.get('home','')
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
    if step['state']=='done':continue
    step.update(state='running',started=now());save(self.op,steps=json.dumps(steps),step=step['name'])
    getattr(self,'step_'+step['name'])()
    step.update(state='done',finished=now());save(self.op,steps=json.dumps(steps))
   save(self.op,state='done',step='',finished=now())
  except Exception as error:
   for step in steps:
    if step['state']=='running':step.update(state='failed')
   with open(self.log,'a') as out:out.write(traceback.format_exc())
   save(self.op,state='failed',steps=json.dumps(steps),error=str(error)[:500]);self.tail()
 def step_register(self):
  # zone.py register checks the home node and adds the zone to the zone state, so the frontend can serve its names
  # before the install. The zones need their names during the install.
  self.run(sys.executable,'-c','import sys;sys.path.insert(0,"zones");import zone;zone.register(sys.argv[1],sys.argv[2])',self.zone,self.home)
 def step_frontend(self):
  # The key runs only the sync script, which reads the zone names from standard input. The connection uses no SSH
  # configuration file, so no other key of the operator user can open a shell instead.
  config=dict(line.split(' ',1) for line in subprocess.check_output(['ssh','-G',settings.HOST['frontend_ssh']],text=True).splitlines() if ' ' in line)
  self.run('ssh','-F','none','-i',KEY,'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o',f"UserKnownHostsFile={config['userknownhostsfile'].split()[0]}",
           '-p',config['port'],f"{config['user']}@{config['hostname']}",data=''.join(f'{z}\n' for z in zones.zone_names()))
 def step_install(self):self.run(sys.executable,'zones/zone.py','apply',self.zone)
 def step_calls(self):self.run(sys.executable,'platform/calls/install-calls.py')
 def step_delete(self):
  if self.zone in zones.zone_names():self.run(sys.executable,'zones/zone.py','delete',self.zone)
def main():
 once='--once' in sys.argv
 while True:
  try:
   items=operations()
   # A running operation is one that the runner was doing when it stopped, so it continues first.
   pending=[i for i in items if i['data'].get('state')=='running']+[i for i in items if i['data'].get('state')=='queued']
   if pending:Operation(pending[0]).execute();continue
  except subprocess.CalledProcessError as error:print(json.dumps({'error':str(error)[:300]}),flush=True)
  if once:return
  time.sleep(3)
if __name__=='__main__':main()
