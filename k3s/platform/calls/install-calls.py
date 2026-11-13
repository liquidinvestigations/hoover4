#!/usr/bin/env python3
"""Install the call media services that every zone shares. Usage: install-calls.py

The namespace calls holds three services:
- coturn gives TURN and STUN on 3478 in the host network. It listens on loopback and on the pod bridge address of its
  node. Each zone has its own TURN secret, and LiveKit has one.
  turn_listen in the settings file (k3s/settings.py) adds addresses: the frontend address, which the pods reach as
  turn.<suffix>, and the public address of the host. A remote client sends its media to coturn on 3478, and coturn
  relays it to the pods from the bridge address. It also relays to the public address of the media node, but a host rule
  limits that address to the LiveKit media ports (turn_peers.py).
- LiveKit is the MatrixRTC SFU. Each zone signs tokens with its own key.
  sfu.<zone>.<suffix> reaches its signalling port through the ingress. Media goes to the pod address.
- JVB is the Jitsi video bridge. The script copies the JVB Deployment that the openDesk chart renders in the first
  zone with zero replicas, and points it at the Prosody of every zone.
The three services run on the media node: the first node with the role calls, else the first public node (decision
D9, config.calls_node()). When the media node has a public address, the services advertise it, so a client sends its
media straight to the node: the JVB on UDP 10000, LiveKit on TCP 7881 and UDP 7882, coturn on 3478. The pods publish
these ports as host ports of the media node, and ../calls/public_endpoints.py prints the firewall rules and the DNS
records that the operator adds. A media node without a public address, such as the local node of a single-node site,
advertises the pod addresses, which the host reaches.
Each zone must be installed first, because the script reads its JVB template. The secrets come from
k3s/private/zones/secrets.json, which zones.py writes. The script prints no secret.
"""
import base64,copy,hashlib,ipaddress,json,os,pathlib,subprocess,sys
source=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(source));import settings
settings.use_kubeconfig()
sys.path.insert(0,str(source/'zones'));from zones import ZONES,SUFFIX
import cpu_policy
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent));import turn_peers
sys.path.insert(0,str(source/'driver'));from hostroute import POD_IMAGE
data=json.loads((settings.PRIVATE/'zones/secrets.json').read_text());calls=data['calls']
NS='calls';NODE=settings.HOST.get('calls_node',settings.HOST['ingress_node']);PUBLIC=settings.HOST.get('calls_public_address','')
def kubectl(*args,data=None):return subprocess.run(['kubectl',*args],input=data,text=True,check=True,capture_output=True).stdout
# The bridge cni0 has the first address of the pod range of the node. The TURN peers are the pods of every node.
nodes=json.loads(kubectl('get','nodes','-o','json'))['items']
BRIDGE=next(str(ipaddress.ip_network(n['spec']['podCIDR'])[1]) for n in nodes if n['metadata']['name']==NODE)
cidrs=[ipaddress.ip_network(n['spec']['podCIDR']) for n in nodes]
PODS=f'{min(c[0] for c in cidrs)}-{max(c[-1] for c in cidrs)}'
COTURN='docker.io/coturn/coturn:4.7.0-alpine@sha256:99fe8365aa12dcb4f90346c29f07a05d35b781f8c117f31165700064e70337d9'
LIVEKIT='docker.io/livekit/livekit-server:v1.13.7@sha256:6fd3b7088874c4d119160dd688798dfec852bc014786d392caad15f6f63912a3'
def apply(items):kubectl('apply','-f','-',data=json.dumps({'apiVersion':'v1','kind':'List','items':items}))
def secret(name,values):
 return {'apiVersion':'v1','kind':'Secret','metadata':{'name':name,'namespace':NS},'type':'Opaque',
  'data':{k:base64.b64encode(v.encode()).decode() for k,v in values.items()}}
SECURITY={'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']},'readOnlyRootFilesystem':True,'runAsNonRoot':True,
 'runAsUser':65534,'runAsGroup':65534,'seccompProfile':{'type':'RuntimeDefault'}}
def coturn():
 lines=['listening-port=3478','listening-ip=127.0.0.1','listening-ip=::1',f'listening-ip={BRIDGE}',f'relay-ip={BRIDGE}',
  'min-port=49160','max-port=49199',f'realm=turn.{SUFFIX}','use-auth-secret','fingerprint','no-cli','no-tls','no-dtls',
  'no-multicast-peers','no-software-attribute',
  # Peers are the pods and the public media address. The host rule of turn_peers.py limits that address to the
  # LiveKit media ports, so a TURN user cannot reach the host or another network.
  *turn_peers.peer_lines(PODS,PUBLIC),
  # Logs go to stdout only. Without a user database, coturn keeps no state on disk.
  'log-file=stdout','simple-log','pidfile=/var/lib/coturn/turnserver.pid']
 lines+=[f'listening-ip={address}' for address in settings.HOST.get('calls_turn_listen',settings.HOST.get('turn_listen',[]))]
 lines+=[f"static-auth-secret={data[zone]['turn_secret']}" for zone in ZONES]+[f"static-auth-secret={calls['livekit_turn_secret']}"]
 pod={'hostNetwork':True,'dnsPolicy':'ClusterFirstWithHostNet','automountServiceAccountToken':False,'enableServiceLinks':False,
  'containers':[{'name':'coturn','image':COTURN,'args':['-c','/etc/coturn/turnserver.conf'],
   # The turnserver binary carries the file capability NET_BIND_SERVICE. Without it in the bounding set, exec fails.
   'resources':{'requests':{'cpu':'10m','memory':'16Mi'},'limits':{'cpu':'1','memory':'128Mi'}},
   'securityContext':{**SECURITY,'runAsUser':turn_peers.COTURN_UID,'runAsGroup':turn_peers.COTURN_UID,
    'capabilities':{'drop':['ALL'],'add':['NET_BIND_SERVICE']}},
   'volumeMounts':[{'name':'config','mountPath':'/etc/coturn','readOnly':True},{'name':'state','mountPath':'/var/lib/coturn'}]}],
  'volumes':[{'name':'config','secret':{'secretName':'coturn'}},{'name':'state','emptyDir':{'medium':'Memory','sizeLimit':'8Mi'}}]}
 if PUBLIC:
  # The init container writes the host rule for the public address (turn_peers.py). nsenter needs the host process ids.
  pod.update(hostPID=True,initContainers=[turn_peers.guard_container(POD_IMAGE,PUBLIC)])
 return [secret('coturn',{'turnserver.conf':'\n'.join(lines)+'\n'}),
  {'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'coturn','namespace':NS},
   'spec':{'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':{'app.kubernetes.io/name':'coturn'}},
    'template':{'metadata':{'labels':{'app.kubernetes.io/name':'coturn'}},'spec':pod}}}]
def livekit():
 keys={zone:data[zone]['livekit_secret'] for zone in ZONES}
 config={'port':7880,'rtc':{'tcp_port':turn_peers.LIVEKIT_TCP,'udp_port':turn_peers.LIVEKIT_UDP,'use_external_ip':False,
   'turn_servers':[{'host':f'turn.{SUFFIX}','port':3478,'protocol':'udp','secret':calls['livekit_turn_secret']}]},
  # lk-jwt creates each room after it checks the Matrix membership, so LiveKit must not create rooms for any token.
  'room':{'auto_create':False},'turn':{'enabled':False},'keys':keys,'logging':{'level':'warn','pion_level':'error'}}
 pod={'automountServiceAccountToken':False,'enableServiceLinks':False,
  'containers':[{'name':'livekit','image':LIVEKIT,'args':['--config','/etc/livekit/config.yaml','--node-ip',PUBLIC or '$(POD_IP)'],
   'env':[{'name':'POD_IP','valueFrom':{'fieldRef':{'fieldPath':'status.podIP'}}}],
   # With a public address the media ports are host ports of the media node, so a client reaches them directly.
   'ports':[{'name':'http','containerPort':7880},
    {'name':'rtc-tcp','containerPort':turn_peers.LIVEKIT_TCP,**({'hostPort':turn_peers.LIVEKIT_TCP} if PUBLIC else {})},
    {'name':'rtc-udp','containerPort':turn_peers.LIVEKIT_UDP,'protocol':'UDP',**({'hostPort':turn_peers.LIVEKIT_UDP} if PUBLIC else {})}],
   'readinessProbe':{'httpGet':{'path':'/','port':7880},'periodSeconds':10},
   'resources':{'requests':{'cpu':'50m','memory':'64Mi'},'limits':{'cpu':'2','memory':'1Gi'}},'securityContext':SECURITY,
   'volumeMounts':[{'name':'config','mountPath':'/etc/livekit','readOnly':True}]}],
  'volumes':[{'name':'config','secret':{'secretName':'livekit'}}]}
 items=[secret('livekit',{'config.yaml':json.dumps(config)}),
  {'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'livekit','namespace':NS},
   'spec':{'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':{'app.kubernetes.io/name':'livekit'}},
    'template':{'metadata':{'labels':{'app.kubernetes.io/name':'livekit'}},'spec':pod}}},
  {'apiVersion':'v1','kind':'Service','metadata':{'name':'livekit','namespace':NS},
   'spec':{'selector':{'app.kubernetes.io/name':'livekit'},'ports':[{'name':'http','port':7880,'targetPort':'http'}]}}]
 for zone in ZONES:
  host=f'sfu.{zone}.{SUFFIX}'
  items.append({'apiVersion':'networking.k8s.io/v1','kind':'Ingress','metadata':{'name':f'livekit-{zone}','namespace':NS},
   'spec':{'ingressClassName':'haproxy','rules':[{'host':host,'http':{'paths':[{'path':'/','pathType':'Prefix',
    'backend':{'service':{'name':'livekit','port':{'number':7880}}}}]}}]}})
 return items
def jvb():
 # The openDesk chart renders the JVB with zero replicas. Its pod template keeps the chart security context.
 source=json.loads(kubectl('-n',ZONES[0],'get','deployment','jitsi-jvb-0','-o','json'))
 spec=copy.deepcopy(source['spec']['template']['spec']);container=spec['containers'][0]
 # The template reads its settings from zone ConfigMaps. The copy takes them as plain values, without the zone parts.
 values={}
 for name in ('jitsi-common','jitsi-jvb'):values.update(json.loads(kubectl('-n',ZONES[0],'get','configmap',name,'-o','json'))['data'])
 for key in ('PUBLIC_URL','ADAPTER_INTERNAL_URL','TOOLBAR_BUTTONS','ENABLE_OCTO','JVB_OCTO_REGION','DEPLOYMENTINFO_REGION'):values.pop(key,None)
 values.update({'XMPP_SERVER':','.join(f'jitsi-prosody.{zone}.svc.cluster.local' for zone in ZONES),'JVB_AUTH_USER':'jvb',
  'JVB_STUN_SERVERS':'','JVB_DISABLE_STUN':'true','VIDEOBRIDGE_MAX_MEMORY':'768m'})
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
 labels={'app.kubernetes.io/name':'jvb'}
 return [secret('jvb',{'password':calls['jvb_password']}),
  # A new bridge starts before the old one stops. The old bridge keeps its calls for up to the chart grace period of
  # 7200 s, and Jicofo sends new conferences to the new bridge. A forced delete leaves the old container running.
  {'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'jvb','namespace':NS},
   'spec':{'replicas':1,'strategy':{'type':'RollingUpdate','rollingUpdate':{'maxSurge':1,'maxUnavailable':0}},'selector':{'matchLabels':labels},
    'template':{'metadata':{'labels':labels},'spec':spec}}}]
apply([{'apiVersion':'v1','kind':'Namespace','metadata':{'name':NS}}])
def checksum(items):
 # Each Deployment carries a hash of its Secret, so a changed config restarts it and an unchanged one does not.
 # A restart of coturn, LiveKit or the JVB ends the calls that run on it.
 data={i['metadata']['name']:i['data'] for i in items if i['kind']=='Secret'}
 for item in items:
  # The CPU policy values go in before the hash, so a later cpu_policy.py run changes nothing.
  if item['kind']=='Deployment':
   item['spec']['template']['spec']['nodeSelector']={'kubernetes.io/hostname':NODE}
   cpu_policy.apply(item)
  if item['kind']=='Deployment':
   digest=hashlib.sha256(json.dumps(data.get(item['metadata']['name'],{}),sort_keys=True).encode()).hexdigest()[:16]
   item['spec']['template']['metadata'].setdefault('annotations',{})['hoover.dev/config']=digest
 return items
# The bridge copies its template from the first zone and serves only zones. Without a zone, the script removes it.
apply(checksum(coturn()+livekit()+(jvb() if ZONES else [])))
if not ZONES:kubectl('-n',NS,'delete','deployment','jvb','--ignore-not-found')
deployments=['coturn','livekit']+(['jvb'] if ZONES else [])
for name in deployments:kubectl('-n',NS,'rollout','status',f'deployment/{name}','--timeout=300s')
print(json.dumps({'namespace':NS,'deployments':deployments,'zones':ZONES}))
