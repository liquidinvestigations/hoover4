#!/usr/bin/env python3
"""Serve dashboard links, cluster cgroup measurements, the recent cluster event feed, and the zone pages.

The zone pages list each zone with its resource use and operations. A create, upgrade or delete request becomes an
operation ConfigMap, which runner.py runs. A create names the home node of the zone.
The settings page (settings.html) reads and saves the operator settings and starts Apply operations through
portal_settings.py. runner.py runs the Apply operations on the control-plane host.
The gateway sets X-Forwarded-User after the operator login, and network policy lets only the gateway pods connect.
A process of the host can reach the pod address without the network policy, so the portal accepts X-Forwarded-User only
together with X-Operator-Proxy-Secret. The secret is the key proxy-secret of the Secret operator-login
(start-web-tools.sh). Only the portal hop of the gateway pod sets it (operator-login.yaml): it listens on the loopback
address of that pod, removes a copy that a client sent and adds the secret, so Grafana, Prometheus and Headlamp never
receive it.
Every dynamic route needs the operator: status.json, events.json, zones.json, settings.json and every POST. The route
is the path without its query. /healthz answers {"ok": true} without the operator and gives no other data. The static
pages hold no data.
A POST needs the operator origin, so another site cannot send one with the operator session cookie.
"""
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import base64,functools,hmac,json,os,re,ssl,time,urllib.error,urllib.parse,urllib.request
ROOT=Path(__file__).resolve().parent/'portal'
CGROUP=Path(os.environ.get('PORTAL_CGROUP','/sys/fs/cgroup/kubepods.slice'))
ADDRESS=(os.environ.get('PORTAL_ADDRESS','127.0.0.1'),int(os.environ.get('PORTAL_PORT','18080')))
SA=Path('/var/run/secrets/kubernetes.io/serviceaccount')
API='https://'+os.environ.get('KUBERNETES_SERVICE_HOST','kubernetes.default.svc')+':'+os.environ.get('KUBERNETES_SERVICE_PORT','443')
def status():
 cpu=dict(line.split() for line in (CGROUP/'cpu.stat').read_text().splitlines())
 memory=dict(line.split() for line in (CGROUP/'memory.stat').read_text().splitlines())
 return {'time':time.time(),'cpu_usage_usec':int(cpu['usage_usec']),'cpu_max':(CGROUP/'cpu.max').read_text().strip(),
  'memory_current':int((CGROUP/'memory.current').read_text()),'memory_max':int((CGROUP/'memory.max').read_text()),
  'memory_anonymous':int(memory['anon']),'memory_file_cache':int(memory['file'])}
def events():
 """Return the 50 latest warning events of the cluster."""
 context=ssl.create_default_context(cafile=str(SA/'ca.crt'))
 request=urllib.request.Request(API+'/api/v1/events?limit=2000',headers={'Authorization':'Bearer '+(SA/'token').read_text().strip()})
 with urllib.request.urlopen(request,context=context,timeout=10) as response:items=json.load(response)['items']
 selected=[e for e in items if e.get('type')=='Warning']
 def when(e):return e.get('lastTimestamp') or e.get('eventTime') or e['metadata']['creationTimestamp']
 selected.sort(key=when,reverse=True)
 return [{'time':when(e),'type':e.get('type'),'namespace':e['metadata']['namespace'],'object':e['involvedObject'].get('kind','')+'/'+e['involvedObject'].get('name',''),
  'reason':e.get('reason'),'message':e.get('message','')[:300],'count':e.get('count') or 1} for e in selected[:50]]
ORIGIN=os.environ.get('PORTAL_ORIGIN','https://operator.hoover.test')
PROMETHEUS=os.environ.get('PORTAL_PROMETHEUS','http://monitor-kube-prometheus-st-prometheus.monitoring.svc.cluster.local:9090')
SUFFIX=os.environ.get('PORTAL_SUFFIX','hoover.test')
NS='operator-portal';LABEL='hoover.dev/operation'
PROXY_SECRET=os.environ.get('PORTAL_PROXY_SECRET','')
def operator(headers):
 """Return the operator name that the gateway sends, or an empty text when the gateway secret is missing or wrong."""
 given=headers.get('X-Operator-Proxy-Secret','')
 if not PROXY_SECRET or not hmac.compare_digest(given.encode(),PROXY_SECRET.encode()):return ''
 return headers.get('X-Forwarded-User','')
ZONE_NAME=re.compile(r'zone-[a-z0-9]{1,12}')
class Refused(Exception):
 """A request that the portal refuses. The message goes back to the operator."""
def api(method,path,body=None,content='application/json'):
 context=ssl.create_default_context(cafile=str(SA/'ca.crt'))
 request=urllib.request.Request(API+path,method=method,data=None if body is None else json.dumps(body).encode(),
  headers={'Authorization':'Bearer '+(SA/'token').read_text().strip(),'Content-Type':content,'Accept':'application/json'})
 with urllib.request.urlopen(request,context=context,timeout=20) as response:return json.load(response)
def prometheus(query):
 url=PROMETHEUS+'/api/v1/query?'+urllib.parse.urlencode({'query':query})
 with urllib.request.urlopen(url,timeout=10) as response:
  return {r['metric'].get('namespace'):float(r['value'][1]) for r in json.load(response)['data']['result']}
def operations():
 items=api('GET',f'/api/v1/namespaces/{NS}/configmaps?labelSelector={LABEL}')['items']
 items.sort(key=lambda i:i['metadata']['creationTimestamp'],reverse=True)
 keys=('kind','zone','actor','state','step','steps','error','log','created','updated','finished')
 return [{'name':i['metadata']['name'],**{k:(i.get('data') or {}).get(k,'') for k in keys}} for i in items[:20]]
def zones():
 spaces=api('GET','/api/v1/namespaces?labelSelector=hoover.dev%2Fzone%3Dtrue')['items']
 try:
  usage={'cpu':prometheus('sum by (namespace) (rate(container_cpu_usage_seconds_total{namespace=~"zone-.*",container!=""}[5m]))'),
   'memory':prometheus('sum by (namespace) (container_memory_working_set_bytes{namespace=~"zone-.*",container!=""})'),
   # The page shows the requested volume sizes.
   'storage':prometheus('sum by (namespace) (kube_persistentvolumeclaim_resource_requests_storage_bytes{namespace=~"zone-.*"})')}
 except (OSError,ValueError,KeyError):usage={}
 result=[]
 for space in spaces:
  name=space['metadata']['name']
  # The Hoover namespace hoover-<zone> belongs to its zone.
  if not ZONE_NAME.fullmatch(name):continue
  result.append({'name':name,'phase':space['status'].get('phase'),'portal':f'https://portal.{name}.{SUFFIX}/',
   **{k:v.get(name) for k,v in usage.items()}})
 nodes=[n['metadata']['name'] for n in api('GET','/api/v1/nodes?labelSelector=storage.hoover%2Fenrolled%3Dtrue')['items']]
 return {'zones':result,'nodes':nodes,'operations':operations(),'usage_available':bool(usage)}
def create_operation(actor,body):
 kind=body.get('kind');zone=str(body.get('zone',''));home=str(body.get('home',''))
 if kind not in ('create-zone','upgrade-zone','delete-zone'):raise Refused('The operation kind is create-zone, upgrade-zone or delete-zone.')
 if not ZONE_NAME.fullmatch(zone):raise Refused('A zone name is zone- followed by 1 to 12 lower-case letters or digits.')
 if kind=='create-zone' and home not in zones()['nodes']:raise Refused('Select the home node of the zone.')
 if kind=='delete-zone' and body.get('confirm')!=zone:raise Refused('Type the zone name to confirm the delete.')
 if any(o['zone']==zone and o['state'] in ('queued','running') for o in operations()):raise Refused(f'An operation for {zone} is not finished.')
 name=f'op-{int(time.time())}-{kind}-{zone}'
 api('POST',f'/api/v1/namespaces/{NS}/configmaps',{'apiVersion':'v1','kind':'ConfigMap',
  'metadata':{'name':name,'namespace':NS,'labels':{LABEL:'true'}},
  'data':{'kind':kind,'zone':zone,'home':home if kind=='create-zone' else '','actor':actor,'state':'queued','created':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}})
 return {'operation':name}
def retry(name):
 item=api('GET',f'/api/v1/namespaces/{NS}/configmaps/{urllib.parse.quote(name)}')
 if (item.get('metadata',{}).get('labels') or {}).get(LABEL)!='true':raise Refused('This is not an operation.')
 if (item.get('data') or {}).get('state')!='failed':raise Refused('Only a failed operation can run again.')
 api('PATCH',f'/api/v1/namespaces/{NS}/configmaps/{urllib.parse.quote(name)}',{'data':{'state':'queued','error':''}},'application/merge-patch+json')
 return {'operation':name}
def onboarding(zone):
 if not ZONE_NAME.fullmatch(zone):raise Refused('Unknown zone.')
 secret=api('GET',f'/api/v1/namespaces/{zone}/secrets/ums-nubus-credentials')
 return {'zone':zone,'portal':f'https://portal.{zone}.{SUFFIX}/','username':'Administrator',
  'password':base64.b64decode(secret['data']['administrator_password']).decode()}
def nodes():
 """The allocatable CPUs and memory of each node, for the hardware suggestions."""
 out={}
 for n in api('GET','/api/v1/nodes')['items']:
  a=n['status']['allocatable'];m=a['memory']
  mib=int(m[:-2])//1024 if m.endswith('Ki') else int(m[:-2]) if m.endswith('Mi') else int(m)//2**20
  out[n['metadata']['name']]={'cpus':int(a['cpu']) if a['cpu'].isdigit() else int(a['cpu'][:-1])//1000,'memory_mib':mib}
 return out
def portal_settings():
 import portal_settings as module
 return module
def route(path):
    """The path of a request without its query and fragment."""
    return urllib.parse.urlsplit(path).path
class Handler(SimpleHTTPRequestHandler):
 def reply(self,code,data):
  raw=json.dumps(data).encode();self.send_response(code)
  self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_POST(self):
  actor=operator(self.headers)
  if self.headers.get('Origin')!=ORIGIN or not actor:return self.reply(403,{'error':'The request must come from the operator website.'})
  try:body=json.loads(self.rfile.read(min(int(self.headers.get('Content-Length') or 0),262144)) or b'{}')
  except ValueError:return self.reply(400,{'error':'The request body is not JSON.'})
  parts=route(self.path).strip('/').split('/')
  if len(parts)==2 and parts[0]=='settings':
   module=portal_settings()
   if parts[1] not in module.ACTIONS:return self.reply(404,{'error':'Unknown request.'})
   try:result=module.ACTIONS[parts[1]](actor,body)
   except module.Refused as error:return self.reply(error.status,{'error':str(error),'problems':error.problems})
   except (OSError,ValueError,KeyError) as error:return self.reply(503,{'error':f'The operator state is unavailable: {error}'})
   print(json.dumps({'time':time.time(),'actor':actor,'request':self.path,'result':'accepted'}),flush=True)
   return self.reply(200,result)
  try:
   if parts==['operations']:result=create_operation(actor,body)
   elif len(parts)==3 and parts[0]=='operations' and parts[2]=='retry':result=retry(parts[1])
   elif len(parts)==3 and parts[0]=='zones' and parts[2]=='onboarding':result=onboarding(parts[1])
   else:return self.reply(404,{'error':'Unknown request.'})
  except Refused as error:return self.reply(400,{'error':str(error)})
  except (OSError,ValueError,KeyError):return self.reply(503,{'error':'The cluster API did not answer.'})
  # The log records the operator, the request and the result, and no password.
  print(json.dumps({'time':time.time(),'actor':actor,'request':self.path,'result':'accepted'}),flush=True)
  self.reply(200,result)
 def do_GET(self):
  path=route(self.path)
  if path=='/healthz':return self.reply(200,{'ok':True})
  routes=ROUTES
  if path not in routes:
   if path.endswith('.json'):return self.reply(404,{'error':'Unknown request.'})
   return super().do_GET()
  if not operator(self.headers):return self.reply(403,{'error':'The request must come through the operator login.'})
  produce,failure=routes[path]
  produce=globals()[produce] if isinstance(produce,str) else produce
  try:raw=json.dumps(produce()).encode();self.send_response(200)
  except Exception:raw=json.dumps({'error':failure}).encode();self.send_response(503)
  self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
def settings_overview():return portal_settings().overview(nodes())
# The dynamic routes. The handler looks each function up at request time, so a test can replace it.
ROUTES={'/status.json':('status','Cluster resource measurements are unavailable.'),'/events.json':('events','The cluster event feed is unavailable.'),
 '/zones.json':('zones','The zone list is unavailable.'),'/settings.json':('settings_overview','The operator settings are unavailable.')}
if __name__=='__main__':ThreadingHTTPServer(ADDRESS,functools.partial(Handler,directory=str(ROOT))).serve_forever()
