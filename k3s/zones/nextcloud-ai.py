#!/usr/bin/env python3
"""Turn on the Nextcloud Assistant with the private LLM in k3s/private/ai.json. Usage: nextcloud-ai.py [zone ...]

The image from ../images/nextcloud-ai adds the Assistant and integration_openai apps. zones.py sets that image in
the zone values, and this script sets it on a running zone too.
The Assistant runs each chat message as a task. Nextcloud cron runs tasks only every 5 minutes, so a sidecar runs
occ taskprocessing:worker in the Nextcloud pod.
The script waits for Nextcloud, enables both apps and stores the provider settings in the zone database.
It turns off the image, speech and text-to-speech providers, because the model serves only text.
The script prints no key.
"""
import json,os,pathlib,subprocess,sys
lab=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
settings.use_kubeconfig()
sys.path.insert(0,str(lab));from zones import NEXTCLOUD_IMAGE_TAG,REGISTRY
IMAGE=f'{REGISTRY}/hoover/nextcloud-ai:{NEXTCLOUD_IMAGE_TAG}'
ai=json.loads((settings.PRIVATE/'ai.json').read_text());key=pathlib.Path(ai['api_key_file']).read_text().strip()
WORKER='worker'
def kubectl(zone,*args,data=None):return subprocess.run(['kubectl','-n',zone,*args],input=data,text=True,check=True,capture_output=True).stdout
def set_image_and_worker(zone):
 ref='deployment/opendesk-nextcloud-aio';spec=json.loads(kubectl(zone,'get',ref,'-o','json'))['spec']['template']['spec']
 aio=next(c for c in spec['containers'] if c['name']=='aio');ops=[]
 for i,c in enumerate(spec['containers']):
  if c['image']!=IMAGE:ops.append({'op':'replace','path':f'/spec/template/spec/containers/{i}/image','value':IMAGE})
 if not any(c['name']==WORKER for c in spec['containers']):
  mounts=[m for m in aio['volumeMounts'] if m['mountPath'] in ('/var/www/html/config','/var/nextcloud/data','/tmp','/etc/ssl/certs/ca-certificates.crt')]
  # The aio container writes config.php at start. The worker waits for it and restarts every 5 minutes, as the occ help advises.
  script='while [ ! -s /var/www/html/config/config.php ]; do sleep 2; done; while true; do php /var/www/html/occ taskprocessing:worker -t 300 -q; sleep 2; done'
  ops.append({'op':'add','path':'/spec/template/spec/containers/-','value':{'name':WORKER,'image':IMAGE,'imagePullPolicy':'IfNotPresent',
   'command':['sh','-c',script],'env':aio.get('env',[]),'securityContext':aio.get('securityContext',{}),'volumeMounts':mounts,
   'resources':{'requests':{'cpu':'10m','memory':'64Mi'},'limits':{'cpu':'1','memory':'512Mi'}}}})
 notify=json.loads(kubectl(zone,'get','deployment/opendesk-nextcloud-notifypush','-o','json'))['spec']['template']['spec']['containers']
 if ops:kubectl(zone,'patch',ref,'--type=json','-p',json.dumps(ops))
 if notify[0]['image']!=IMAGE:kubectl(zone,'set','image','deployment/opendesk-nextcloud-notifypush',f"{notify[0]['name']}={IMAGE}")
 return bool(ops)
def wait(zone):
 kubectl(zone,'rollout','status','deployment/opendesk-nextcloud-aio','--timeout=600s')
def aio_pod(zone):
 # The cron Job pods carry the same labels, so kubectl exec on the Deployment can reach a finished cron pod.
 pods=json.loads(kubectl(zone,'get','pods','-o','json'))['items']
 return next(p['metadata']['name'] for p in pods if p['status'].get('phase')=='Running' and not p['metadata'].get('deletionTimestamp')
  and any(o['kind']=='ReplicaSet' and o['name'].startswith('opendesk-nextcloud-aio-') for o in p['metadata'].get('ownerReferences',[])))
def occ(zone,*args,data=None):
 return kubectl(zone,'exec','-i',aio_pod(zone),'-c','aio','--','php','/var/www/html/occ',*args,data=data)
for zone in sys.argv[1:] or ['zone-a','zone-b']:
 changed=set_image_and_worker(zone);wait(zone)
 occ(zone,'app:enable','assistant','integration_openai')
 for name,value,lazy in [('url',ai['endpoint'],False),('service_name','Hoover',True),('default_completion_model_id',ai['model'],True),
   ('request_timeout','300',True),('max_tokens','4000',True),
   ('t2i_provider_enabled','0',False),('stt_provider_enabled','0',False),('tts_provider_enabled','0',False)]:
  occ(zone,'config:app:set','integration_openai',name,'--value',value,*(['--lazy'] if lazy else []))
 # The key goes through standard input, so it is not in a command line on the host.
 kubectl(zone,'exec','-i',aio_pod(zone),'-c','aio','--','sh','-c',
  'php /var/www/html/occ config:app:set integration_openai api_key --lazy --sensitive --value="$(cat)" >/dev/null',data=key)
 print(json.dumps({'zone':zone,'image':IMAGE,'deployment_changed':changed,'apps':'assistant integration_openai','model':ai['model']}),flush=True)
