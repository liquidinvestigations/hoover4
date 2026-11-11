#!/usr/bin/env python3
"""Apply the CPU policy to the cluster workloads. Usage: cpu_policy.py [--check] [namespace ...] | cpu_policy.py --render <manifest>

cpu-policy.json holds the values. Each container and init container gets a small CPU request and a burstable CPU limit,
so the scheduler books about one sixth of the CPU allocation of each container. Memory stays as it is, because
the Kata VMs reserve their memory.
- The request is the allocation divided by the oversubscription factor. A workload with a continuous load gets
  the request from the continuous table, near its measured use.
- The limit is the default limit. A slow-starting workload gets the slow-start limit for all its containers.
  Kata sizes each VM from the CPU limits of its containers.
- Prometheus gets its values through its Prometheus resource, because the operator writes its StatefulSet.
Without namespaces the script covers every namespace except the skipped ones. It patches only a workload whose
values differ, so a second run restarts nothing. --check prints the differences and changes nothing.
Other scripts import apply() to write the policy into the objects that they create.
--render prints a YAML manifest file, or standard input for -, with the policy as a JSON list for kubectl apply, so an installer keeps the policy.
"""
import fnmatch,json,os,pathlib,subprocess,sys
lab=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(lab.parent));import settings
POLICY=json.loads((lab/'cpu-policy.json').read_text())
def _operator_values():
 """The cluster settings cpu.* of the operator state (../platform/operator/settings.py), which replace the file values."""
 import importlib.util
 if not settings.SITE or not (settings.SITE.operator_state()/'desired.json').exists():return {}
 spec=importlib.util.spec_from_file_location('operator_settings',lab.parent/'platform/operator/settings.py')
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 revision=os.environ.get('HOOVER4_SETTINGS_REVISION')
 overrides=module.State(settings.SITE.operator_state()).overrides(int(revision) if revision else None)
 return module.effective('cluster',overrides.get('cluster',{}))
_values=_operator_values()
if _values:
 POLICY['oversubscription']=int(_values['cpu.oversubscription']);POLICY['allocation']=_values['cpu.allocation']
 POLICY['limit']=_values['cpu.limit'];POLICY['slowStart']['limit']=_values['cpu.slow_start_limit']
KINDS={'Deployment':'deployment','StatefulSet':'statefulset','DaemonSet':'daemonset','CronJob':'cronjob'}
def millicores(value):
 text=str(value);return float(text[:-1]) if text.endswith('m') else float(text)*1000
def values(namespace,kind,name):
 """Return the CPU request and limit for each container of a workload."""
 ref=f'{namespace}/{KINDS.get(kind,kind.lower())}/{name}'
 request=POLICY['continuous'].get(ref) or f"{int(millicores(POLICY['allocation'])/POLICY['oversubscription'])}m"
 slow=any(fnmatch.fnmatchcase(ref,p) for p in POLICY['slowStart']['workloads'])
 return request,POLICY['slowStart']['limit'] if slow else POLICY['limit']
def pod_spec(item):
 spec=item['spec']
 if item['kind']=='CronJob':return spec['jobTemplate']['spec']['template']['spec']
 return spec['template']['spec']
def apply(item):
 """Write the policy into a workload object. Return True when a value changed."""
 request,limit=values(item['metadata'].get('namespace',''),item['kind'],item['metadata']['name'])
 changed=False
 spec=pod_spec(item)
 for container in spec.get('containers',[])+spec.get('initContainers',[]):
  resources=container.setdefault('resources',{})
  for key,value in (('requests',request),('limits',limit)):
   current=(resources.get(key) or {}).get('cpu')
   if current is None or millicores(current)!=millicores(value):resources.setdefault(key,{})['cpu']=value;changed=True
 return changed
def kubectl(*args,data=None):return subprocess.run(['kubectl',*args],input=data,text=True,check=True,capture_output=True).stdout
def namespaces(selected):
 if selected:return selected
 names=[i['metadata']['name'] for i in json.loads(kubectl('get','namespaces','-o','json'))['items']]
 return [n for n in names if n not in POLICY['skipNamespaces']]
def render(path):
 import yaml
 items=[d for d in yaml.safe_load_all(sys.stdin.read() if path=='-' else pathlib.Path(path).read_text()) if d]
 for item in items:
  if item.get('kind') in KINDS:apply(item)
 print(json.dumps({'apiVersion':'v1','kind':'List','items':items}))
def main():
 if sys.argv[1:2]==['--render']:return render(sys.argv[2])
 settings.use_kubeconfig()
 check='--check' in sys.argv
 for namespace in namespaces([a for a in sys.argv[1:] if not a.startswith('--')]):
  for kind,resource in KINDS.items():
   for item in json.loads(kubectl('-n',namespace,'get',resource+'s','-o','json'))['items']:
    item['kind']=kind
    if item['metadata'].get('ownerReferences'):continue
    before=json.dumps(pod_spec(item),sort_keys=True)
    if not apply(item):continue
    ref=f"{resource}/{item['metadata']['name']}"
    if check:print(json.dumps({'namespace':namespace,'workload':ref,'change':'cpu policy differs'}));continue
    spec=pod_spec(item)
    patch={'containers':[{'name':c['name'],'resources':c['resources']} for c in spec['containers']]}
    if spec.get('initContainers'):patch['initContainers']=[{'name':c['name'],'resources':c['resources']} for c in spec['initContainers']]
    body={'spec':{'jobTemplate':{'spec':{'template':{'spec':patch}}}}} if kind=='CronJob' else {'spec':{'template':{'spec':patch}}}
    kubectl('-n',namespace,'patch',ref,'--type','strategic','-p',json.dumps(body))
    print(json.dumps({'namespace':namespace,'workload':ref,'change':'cpu policy'}),flush=True)
  for item in json.loads(kubectl('-n',namespace,'get','prometheuses.monitoring.coreos.com','-o','json') if namespace=='monitoring' else '{"items":[]}')['items']:
   request,limit=values(namespace,'StatefulSet','prometheus-'+item['metadata']['name'])
   resources=item['spec'].get('resources') or {}
   if (resources.get('requests') or {}).get('cpu')==request and (resources.get('limits') or {}).get('cpu')==limit:continue
   if check:print(json.dumps({'namespace':namespace,'workload':'prometheus/'+item['metadata']['name'],'change':'cpu policy differs'}));continue
   kubectl('-n',namespace,'patch','prometheus',item['metadata']['name'],'--type','merge','-p',json.dumps({'spec':{'resources':{'requests':{'cpu':request},'limits':{'cpu':limit}}}}))
   print(json.dumps({'namespace':namespace,'workload':'prometheus/'+item['metadata']['name'],'change':'cpu policy'}),flush=True)
if __name__=='__main__':main()
