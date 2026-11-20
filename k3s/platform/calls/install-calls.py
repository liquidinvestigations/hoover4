#!/usr/bin/env python3
"""Install the call media services that every zone shares. Usage: install-calls.py [--probe [--force]]

The namespace calls holds two services. They serve the Jitsi of every zone. The chat calls of LiveKit are retired with
Element (../../zones/applications.py), and the script removes the LiveKit objects of an earlier version.
- coturn gives TURN and STUN on 3478 in the host network. It listens on loopback and on the pod bridge address of its
  node. Each zone has its own TURN secret. coturn reads the secrets from its SQLite database at
  each request. The sidecar secrets copies them from the Secret coturn-secrets into the database while coturn runs, so
  a new or deleted zone changes no pod.
  turn_listen in the settings file (k3s/settings.py) adds addresses: the frontend address, which the pods reach as
  turn.<suffix>, and the public address of the host. A remote client sends its media to coturn on 3478, and coturn
  relays it to the pods from the bridge address. It also relays to the public address of the media node, but a host rule
  limits that address to the earlier LiveKit media ports, where no service listens (turn_peers.py, the role
  hoover4_public_firewall of ../../ansible/).
  coturn relays UDP only, to the pods of the media node and to that address.
  --probe checks that rule on the media node with a probe pod in its host network in kube-system, records the result in
  the ConfigMap coturn-peer-check of calls, and installs nothing. It needs the admin kubeconfig: the step operator and the step calls
  of ../../deploy-k3s up run it. The zone runner of the operator portal has no right on pods in calls. Without --probe the
  script adds the public address only when the record names the media node and its public address, and stops
  otherwise.
- JVB is the Jitsi video bridge. The script copies the JVB Deployment that the openDesk chart renders in the first
  zone with zero replicas, without its XMPP connections. The sidecar zones connects the bridge to the Prosody of each
  zone through the REST API of the bridge (/colibri/muc-client/add and remove), from the Secret jvb-zones, so a new
  or deleted zone changes no pod.
The two services run on the media node: the first node with the role calls, else the first public node (decision
D9, config.calls_node()). When the media node has a public address, the services advertise it, so a client sends its
media straight to the node: the JVB on UDP 10000 and coturn on 3478. The pods publish
these ports as host ports of the media node, and ../calls/public_endpoints.py prints the firewall rules and the DNS
records that the operator adds. A media node without a public address, such as the local node of a single-node site,
advertises the pod addresses, which the host reaches.
A Deployment restarts only when its own Secret or its template changes (checksum()). The zone lists are in the Secrets
coturn-secrets and jvb-zones, which the sidecars read while they run. The kubelet updates a mounted Secret within
about a minute.
Each zone must be installed first, because the script reads its JVB template. The secrets come from the secret store
(../../secretstore.py): site/calls and the TURN secret of each zone in zones/<zone>/secrets. The script prints no
secret.
"""
import base64,copy,hashlib,ipaddress,json,os,pathlib,subprocess,sys,time
source=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(source));import settings
settings.use_kubeconfig()
sys.path.insert(0,str(source/'zones'));from zones import ZONES,SUFFIX
import cpu_policy
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent));import turn_peers
NS='calls';NODE=settings.HOST.get('calls_node',settings.HOST['ingress_node']);PUBLIC=settings.HOST.get('calls_public_address','')
def kubectl(*args,data=None):return subprocess.run(['kubectl',*args],input=data,text=True,check=True,capture_output=True).stdout
# The bridge cni0 has the first address of the pod range of the node. The TURN peers are the pods of the media node.
nodes=json.loads(kubectl('get','nodes','-o','json'))['items']
PODS=next(n['spec']['podCIDR'] for n in nodes if n['metadata']['name']==NODE)
BRIDGE=str(ipaddress.ip_network(PODS)[1])
COTURN='docker.io/coturn/coturn:4.7.0-alpine@sha256:99fe8365aa12dcb4f90346c29f07a05d35b781f8c117f31165700064e70337d9'
PROBE_IMAGE='docker.io/library/python:3.14-alpine@sha256:7f2ec713f0436c59df2362d973b6a05af9e87ba78f0e94f5245c302984a7a1fd'
# The sidecar of coturn. It copies the secrets of /etc/coturn-secrets/secrets into the database of coturn when the
# file changes, and marks the first copy for the startupProbe. It prints no secret.
COTURN_SECRETS=r"""set -eu
trap 'exit 0' TERM
db=/var/lib/coturn/turndb file=/etc/coturn-secrets/secrets last=''
rm -f /var/lib/coturn/synced
while :; do
  now=$(md5sum "$file" | cut -d' ' -f1)
  if [ "$now" != "$last" ]; then
    turnadmin -S -r "$TURN_REALM" -b "$db" 2>/dev/null | sed -n "s/\[$TURN_REALM\]\$//p" > /var/tmp/current || true
    added=0 removed=0
    while read -r s; do
      [ -n "$s" ] && ! grep -qxF "$s" /var/tmp/current && turnadmin -s "$s" -r "$TURN_REALM" -b "$db" >/dev/null 2>&1 && added=$((added+1))
    done < "$file"
    while read -r s; do
      [ -n "$s" ] && ! grep -qxF "$s" "$file" && turnadmin -X "$s" -r "$TURN_REALM" -b "$db" >/dev/null 2>&1 && removed=$((removed+1))
    done < /var/tmp/current
    rm -f /var/tmp/current
    echo "secrets: $added added, $removed removed"
    last=$now
    touch /var/lib/coturn/synced
  fi
  sleep 5
done
"""
# The sidecar of the JVB. It connects the bridge to the Prosody of each zone of /etc/jvb-zones/servers and removes the
# connection of a deleted zone, through the REST API of the bridge. A bridge that does not answer has restarted and lost
# its connections, so the sidecar adds them again. Every 10 minutes it adds every zone again, which the bridge ignores
# for a connection that it has.
JVB_ZONES=r"""
import json, os, time, urllib.error, urllib.request
BASE = 'http://127.0.0.1:8080'
def call(path, body=None):
    request = urllib.request.Request(BASE + path, json.dumps(body).encode() if body is not None else None,
                                     {'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=10) as answer:
            return answer.status
    except urllib.error.HTTPError as error:
        return error.code
    except OSError:
        return 0
added, full = {}, 0.0
while True:
    time.sleep(5)
    try:
        servers = {s['id']: s for s in json.load(open('/etc/jvb-zones/servers'))}
        password = open('/etc/jvb-password/password').read().strip()
    except (OSError, ValueError):
        continue
    if call('/colibri/stats') != 200:
        added = {}
        continue
    if time.monotonic() - full > 600:
        added, full = {}, time.monotonic()
    for zone in sorted(set(added) - set(servers)):
        status = call('/colibri/muc-client/remove', {'id': zone})
        added.pop(zone)
        print(json.dumps({'zone': zone, 'removed': status}), flush=True)
    for zone, server in sorted(servers.items()):
        if added.get(zone) == server:
            continue
        status = call('/colibri/muc-client/add', {**server, 'password': password, 'muc_nickname': os.environ['HOSTNAME']})
        if status == 200:
            added[zone] = server
        print(json.dumps({'zone': zone, 'added': status}), flush=True)
"""
def apply(items):kubectl('apply','-f','-',data=json.dumps({'apiVersion':'v1','kind':'List','items':items}))
def secret(name,values):
 return {'apiVersion':'v1','kind':'Secret','metadata':{'name':name,'namespace':NS},'type':'Opaque',
  'data':{k:base64.b64encode(v.encode()).decode() for k,v in values.items()}}
SECURITY={'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']},'readOnlyRootFilesystem':True,'runAsNonRoot':True,
 'runAsUser':65534,'runAsGroup':65534,'seccompProfile':{'type':'RuntimeDefault'}}
RECORD='coturn-peer-check'
def probe_inputs():
 """A digest of the files that make the host rule coturn_peers and of the media node and its address."""
 roles=source/'ansible/roles/hoover4_public_firewall'
 files=[pathlib.Path(__file__).resolve().parent/'turn_peers.py',roles/'files/coturn-peers.sh',roles/'tasks/main.yml',roles/'defaults/main.yml']
 h=hashlib.sha256(f'{NODE}\0{PUBLIC}\0'.encode())
 for f in files:h.update(f.read_bytes()+b'\0')
 return h.hexdigest()[:16]
def probe(force=False):
 """Run the probe of the host rule coturn_peers on the media node, and record its result in the ConfigMap RECORD.

 A record of the same inputs (probe_inputs()) stays, and no probe pod runs, so a second deployment changes nothing.
 --force runs the probe again, for example after a manual change of the host rule.
 """
 if not PUBLIC:
  kubectl('delete','configmap','-n',NS,RECORD,'--ignore-not-found')
  print(json.dumps({'coturn_peer_check':'the media node has no public address'}));return
 inputs=probe_inputs()
 found=subprocess.run(['kubectl','-n',NS,'get','configmap',RECORD,'-o','json'],text=True,capture_output=True)
 record=json.loads(found.stdout).get('data',{}) if found.returncode==0 else {}
 if not force and record.get('node')==NODE and record.get('address')==PUBLIC and record.get('inputs')==inputs:
  print(json.dumps({'coturn_peer_check':'verified before','node':NODE,'address':PUBLIC,'verified':record.get('verified')}));return
 kubectl('delete','configmap','-n',NS,RECORD,'--ignore-not-found')
 # The pod admission policy hoover-pod-limits (../../zones/manifests/zone-pods.yaml) gives the host network in calls only
 # to coturn, so the probe pod runs in kube-system, which only the admin kubeconfig reaches.
 name,ns='coturn-peer-check','kube-system'
 kubectl('-n',ns,'delete','pod',name,'--ignore-not-found','--wait=true')
 kubectl('apply','-f','-',data=json.dumps(turn_peers.probe_pod(ns,NODE,PUBLIC,PROBE_IMAGE,SECURITY)))
 phase=''
 for _ in range(100):
  phase=kubectl('-n',ns,'get','pod',name,'-o','jsonpath={.status.phase}').strip()
  if phase in ('Succeeded','Failed'):break
  time.sleep(3)
 logs={c:subprocess.run(['kubectl','-n',ns,'logs',name,'-c',c],text=True,capture_output=True).stdout for c in ('coturn','control')}
 kubectl('-n',ns,'delete','pod',name,'--wait=false')
 if phase!='Succeeded':sys.exit(f'the probe of the host rule coturn_peers on {NODE} ended in phase {phase or "unknown"}: {logs}')
 problem=turn_peers.chain_problem(NODE,PUBLIC,logs['coturn'],logs['control'])
 if problem:sys.exit(problem)
 apply([{'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':RECORD,'namespace':NS},
  'data':{'node':NODE,'address':PUBLIC,'inputs':inputs,'verified':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}}])
 print(json.dumps({'coturn_peer_check':'verified','node':NODE,'address':PUBLIC}))
def public_peer():
 """The public address of the media node, when the record of probe() shows the host rule coturn_peers for it."""
 if not PUBLIC:return ''
 found=subprocess.run(['kubectl','-n',NS,'get','configmap',RECORD,'-o','json'],text=True,capture_output=True)
 record=json.loads(found.stdout)['data'] if found.returncode==0 else {}
 if record.get('node')!=NODE or record.get('address')!=PUBLIC:
  sys.exit(f'calls has no verified record of the host rule coturn_peers for {PUBLIC} on {NODE}. Run deploy-k3s up '
   '--target <control plane> --steps operator on the operator workstation, then run this step again.')
 return PUBLIC
def coturn(public):
 lines=['listening-port=3478','listening-ip=127.0.0.1','listening-ip=::1',f'listening-ip={BRIDGE}',f'relay-ip={BRIDGE}',
  'min-port=49160','max-port=49199',f'realm=turn.{SUFFIX}','use-auth-secret','fingerprint','no-cli','no-tls','no-dtls',
  'no-multicast-peers','no-software-attribute',
  # The shared secrets of the TURN REST API are in this database (COTURN_SECRETS), not in this file.
  'userdb=/var/lib/coturn/turndb',
  # UDP relay only, to the pods of the media node and the public media address. The host rule coturn_peers limits
  # that address to the earlier LiveKit media ports for the coturn user, so a TURN user cannot reach the host or another
  # network.
  *turn_peers.peer_lines(PODS,public),
  # Logs go to stdout only. Without a user database, coturn keeps no state on disk.
  'log-file=stdout','simple-log','pidfile=/var/lib/coturn/turnserver.pid']
 lines+=[f'listening-ip={address}' for address in settings.HOST.get('calls_turn_listen',settings.HOST.get('turn_listen',[]))]
 pod={'hostNetwork':True,'dnsPolicy':'ClusterFirstWithHostNet','automountServiceAccountToken':False,'enableServiceLinks':False,
  'containers':[{'name':'coturn','image':COTURN,'args':['-c','/etc/coturn/turnserver.conf'],
   # The turnserver binary carries the file capability NET_BIND_SERVICE. Without it in the bounding set, exec fails.
   'resources':{'requests':{'cpu':'10m','memory':'16Mi'},'limits':{'cpu':'1','memory':'128Mi'}},
   'securityContext':{**SECURITY,'runAsUser':turn_peers.COTURN_UID,'runAsGroup':turn_peers.COTURN_UID,
    'capabilities':{'drop':['ALL'],'add':['NET_BIND_SERVICE']}},
   'volumeMounts':[{'name':'config','mountPath':'/etc/coturn','readOnly':True},{'name':'state','mountPath':'/var/lib/coturn'}]}],
  # A sidecar: it starts before coturn, and coturn starts after its first copy of the secrets (startupProbe).
  'initContainers':[{'name':'secrets','image':COTURN,'restartPolicy':'Always','command':['sh','-c',COTURN_SECRETS],
   'env':[{'name':'TURN_REALM','value':f'turn.{SUFFIX}'}],
   'startupProbe':{'exec':{'command':['test','-f','/var/lib/coturn/synced']},'periodSeconds':2,'failureThreshold':60},
   'resources':{'requests':{'cpu':'5m','memory':'8Mi'},'limits':{'cpu':'200m','memory':'32Mi'}},
   'securityContext':{**SECURITY,'runAsUser':turn_peers.COTURN_UID,'runAsGroup':turn_peers.COTURN_UID,
    'capabilities':{'drop':['ALL'],'add':['NET_BIND_SERVICE']}},
   'volumeMounts':[{'name':'secrets','mountPath':'/etc/coturn-secrets','readOnly':True},{'name':'state','mountPath':'/var/lib/coturn'},
    {'name':'admin-tmp','mountPath':'/var/tmp'}]}],
  'volumes':[{'name':'config','secret':{'secretName':'coturn'}},{'name':'state','emptyDir':{'medium':'Memory','sizeLimit':'8Mi'}},
   {'name':'secrets','secret':{'secretName':'coturn-secrets'}},{'name':'admin-tmp','emptyDir':{'medium':'Memory','sizeLimit':'4Mi'}}]}
 shared=[secret('coturn-secrets',{'secrets':''.join(f'{v}\n' for v in [data[zone]['turn_secret'] for zone in ZONES])})]
 return shared+[secret('coturn',{'turnserver.conf':'\n'.join(lines)+'\n'}),
  {'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'coturn','namespace':NS},
   'spec':{'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':{'app.kubernetes.io/name':'coturn'}},
    'template':{'metadata':{'labels':{'app.kubernetes.io/name':'coturn'}},'spec':pod}}}]
def jvb():
 # The openDesk chart renders the JVB with zero replicas. Its pod template keeps the chart security context.
 source=json.loads(kubectl('-n',ZONES[0],'get','deployment','jitsi-jvb-0','-o','json'))
 spec=copy.deepcopy(source['spec']['template']['spec']);container=spec['containers'][0]
 # The template reads its settings from zone ConfigMaps. The copy takes them as plain values, without the zone parts.
 values={}
 for name in ('jitsi-common','jitsi-jvb'):values.update(json.loads(kubectl('-n',ZONES[0],'get','configmap',name,'-o','json'))['data'])
 for key in ('PUBLIC_URL','ADAPTER_INTERNAL_URL','TOOLBAR_BUTTONS','ENABLE_OCTO','JVB_OCTO_REGION','DEPLOYMENTINFO_REGION'):values.pop(key,None)
 # The bridge gets no XMPP connection at start. The sidecar zones adds one for each zone (JVB_ZONES).
 for key in ('XMPP_SERVER','XMPP_PORT'):values.pop(key,None)
 values.update({'JVB_DISABLE_XMPP':'1','JVB_AUTH_USER':'jvb','COLIBRI_REST_ENABLED':'true',
  'JVB_STUN_SERVERS':'','JVB_DISABLE_STUN':'true','VIDEOBRIDGE_MAX_MEMORY':'768m'})
 servers=[{'id':zone,'hostname':f'jitsi-prosody.{zone}.svc.cluster.local','port':'5222','domain':values['XMPP_AUTH_DOMAIN'],
  'username':'jvb','muc_jids':f"{values.get('JVB_BREWERY_MUC','jvbbrewery')}@{values['XMPP_INTERNAL_MUC_DOMAIN']}",
  'disable_certificate_verification':'true'} for zone in ZONES]
 env=[{'name':k,'value':v} for k,v in sorted(values.items())]
 env+=[{'name':'JVB_AUTH_PASSWORD','valueFrom':{'secretKeyRef':{'name':'jvb','key':'password'}}},
  {'name':'POD_IP','valueFrom':{'fieldRef':{'fieldPath':'status.podIP'}}},
  # A public media node advertises its public address first, so a remote client sends its media there. The pod
  # address stays for the clients that reach the pods.
  {'name':'JVB_ADVERTISE_IPS','value':f'{PUBLIC},$(POD_IP)' if PUBLIC else '$(POD_IP)'},
  {'name':'JVB_PORT','value':'10000'}]
 container['env']=env;container.pop('envFrom',None)
 container['ports']=[{'name':'media','containerPort':10000,'protocol':'UDP',**({'hostPort':10000} if PUBLIC else {})}]+\
  [p for p in container.get('ports',[]) if p.get('containerPort')!=10000]
 # The custom volumes are not mounted in the template.
 spec['volumes']=[v for v in spec.get('volumes',[]) if 'configMap' not in v and 'secret' not in v]
 spec.pop('serviceAccountName',None);spec.pop('serviceAccount',None);spec['automountServiceAccountToken']=False
 spec['volumes'].append({'name':'jvb-zones','secret':{'secretName':'jvb-zones'}})
 spec['volumes'].append({'name':'jvb-password','secret':{'secretName':'jvb'}})
 spec['containers'].append({'name':'zones','image':PROBE_IMAGE,'command':['python3','-c',JVB_ZONES],
  'resources':{'requests':{'cpu':'5m','memory':'24Mi'},'limits':{'cpu':'200m','memory':'64Mi'}},'securityContext':SECURITY,
  'volumeMounts':[{'name':'jvb-zones','mountPath':'/etc/jvb-zones','readOnly':True},
   {'name':'jvb-password','mountPath':'/etc/jvb-password','readOnly':True}]})
 labels={'app.kubernetes.io/name':'jvb'}
 return [secret('jvb-zones',{'servers':json.dumps(servers,sort_keys=True)}),secret('jvb',{'password':calls['jvb_password']}),
  # The bridge publishes host port 10000 on the media node, so a second bridge pod cannot start on that node while the
  # old one runs. The Deployment therefore replaces the bridge with Recreate: the old bridge stops first. Its
  # shutdown waits for its calls for up to the chart grace period of 7200 s, so an update during a call waits for that
  # call, and the rollout check below fails after 300 s. A forced delete leaves the old container running.
  {'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'jvb','namespace':NS},
   'spec':{'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':labels},
    'template':{'metadata':{'labels':labels},'spec':spec}}}]
if subprocess.run(['kubectl','get','namespace',NS],capture_output=True).returncode:
 apply([{'apiVersion':'v1','kind':'Namespace','metadata':{'name':NS}}])
if '--probe' in sys.argv[1:]:
 probe(force='--force' in sys.argv[1:]);sys.exit(0)
import secretstore
calls=secretstore.read('site/calls')
data={'calls':calls,**{zone:secretstore.zone_secrets(zone) for zone in ZONES}}
def checksum(items):
 # Each Deployment carries a hash of its Secret, so a changed config restarts it and an unchanged one does not.
 # A restart of coturn or the JVB ends the calls that run on it.
 data={i['metadata']['name']:i['data'] for i in items if i['kind']=='Secret'}
 for item in items:
  # The CPU policy values go in before the hash, so a later cpu_policy.py run changes nothing.
  if item['kind']=='Deployment':
   item['spec']['template']['spec']['nodeSelector']={'kubernetes.io/hostname':NODE}
   # The services run on the media node only, so on a full node they preempt a pod of the default priority.
   item['spec']['template']['spec']['priorityClassName']=turn_peers.NODE_BOUND
   cpu_policy.apply(item)
  if item['kind']=='Deployment':
   digest=hashlib.sha256(json.dumps(data.get(item['metadata']['name'],{}),sort_keys=True).encode()).hexdigest()[:16]
   item['spec']['template']['metadata'].setdefault('annotations',{})['hoover.dev/config']=digest
 return items
# The bridge copies its template from the first zone and serves only zones. Without a zone, the script removes it.
apply(checksum(coturn(public_peer())+(jvb() if ZONES else [])))
if not ZONES:kubectl('-n',NS,'delete','deployment','jvb','--ignore-not-found')
# The LiveKit objects of an earlier version: the SFU of the retired chat calls, its Secret and the Ingress of each
# zone. The script lists them first, so a run without them deletes nothing.
retired=[n for n in kubectl('-n',NS,'get','deployment,service,secret,ingress','-o','name').split()
 if n.split('/',1)[1]=='livekit' or n.split('/',1)[1].startswith('livekit-')]
if retired:kubectl('-n',NS,'delete',*retired,'--ignore-not-found')
# coturn stops the old pod before the new one starts, so a refused or failing pod leaves no call service.
# The JVB starts its new pod first and keeps the old one, so this script does not wait for it.
for name in ('coturn',):
 r=subprocess.run(['kubectl','-n',NS,'rollout','status',f'deployment/{name}','--timeout=300s'],text=True,capture_output=True)
 if r.returncode:
  events=subprocess.run(['kubectl','-n',NS,'get','events','--field-selector','reason=FailedCreate','-o','jsonpath={.items[-1:].message}'],text=True,capture_output=True).stdout
  sys.exit(f'the call service {name} did not start: {(r.stderr or r.stdout).strip()[-300:]} {events[-300:]}')
deployments=['coturn']+(['jvb'] if ZONES else [])
for name in deployments:kubectl('-n',NS,'rollout','status',f'deployment/{name}','--timeout=300s')
print(json.dumps({'namespace':NS,'deployments':deployments,'zones':ZONES}))
