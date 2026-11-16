#!/usr/bin/env python3
"""Generate the openDesk values of each zone and the site list of the HTTPS frontend.

The zones come from the zone state (zonestate.py). The secrets file is created once and reused. The other outputs are
regenerated from it. Each zone has its own PostgreSQL, SeaweedFS, Redis, Memcached and NATS in its namespace: the
openDesk charts render them, and postrender.py moves them into Kata on TopoLVM block volumes.
openDesk derives the database and object store passwords from the master password of the zone.
"""
import base64,json,pathlib,re,secrets,string,sys,yaml
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
import zonestate
out=settings.PRIVATE/'zones'
# The openDesk release is not in Git. The operator unpacks it into the private folder.
OPENDESK=settings.PRIVATE/'downloads/opendesk-v1.19.1/src'
ZONE_NAME=re.compile(r'zone-[a-z0-9]{1,12}')

def put(path,text):
 """Write a private file only when its text changes, through a renamed temporary file, so a helmfile process of
 another zone that reads it at the same time reads the old or the new text."""
 import os
 path=pathlib.Path(path)
 if path.exists() and path.read_text()==text:return
 tmp=path.with_name(f'.{path.name}.{os.getpid()}.tmp')
 fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 with os.fdopen(fd,'w') as f:f.write(text)
 os.replace(tmp,path)

def local_ca():
 """The local CA of the frontend for the trust bundle of a zone, when the frontend uses the TLS mode internal."""
 import config
 ca=config.local_ca(settings.SITE) if settings.SITE else ''
 return {'certificateAuthorities':{'values':{'hoover4-local-ca.crt':ca}}} if ca else {}

def zone_names():
 try:return list(zonestate.load()['zones'])
 except zonestate.ZoneStateError:
  if zonestate.PATH.exists():raise
  return []
ZONES=zone_names()
NEXTCLOUD_IMAGE_TAG='33.0.9-2'
# The key name of the one LiveKit key of all zones (load_secrets()).
LIVEKIT_KEY='hoover-calls'
XWIKI_EXTENSIONS_TAG='llm-0.11'
SUFFIX=settings.SUFFIX
# Pods name the images of the cluster registry with this host name. Each node maps it to the registry endpoint.
REGISTRY='registry.hoover.internal'
# The openDesk global.hosts defaults. Each zone gets them with its zone id in front (zone_hosts()), so each host of a
# zone is <zone>-<app>.<suffix> (settings.zone_host()).
OPENDESK_HOSTS={'collabora':'office','cryptpad':'pad','elementAdmin':'element-admin','elementSupervision':'element-supervision',
 'elementWeb':'chat','intercomService':'ics','jitsi':'meet','keycloak':'id','matrixAuthenticationService':'mas',
 'matrixNeoBoardWidget':'matrix-neoboard-widget','matrixNeoChoiceWidget':'matrix-neochoice-widget',
 'matrixNeoDateFixBot':'matrix-neodatefix-bot','matrixNeoDateFixWidget':'matrix-neodatefix-widget','matrixRTC':'mrtc',
 'minioApi':'objectstore','minioConsole':'objectstore-ui','seaweedfs':'objectstorage','seaweedfsAdmin':'objectstorage-ui',
 'nextcloud':'files','notes':'notes','nubus':'portal','openproject':'projects','openxchange':'webmail','openxchangeDav':'dav',
 'static':'static','synapse':'matrix','whiteboard':'whiteboard','xwiki':'wiki'}
# The applications of a zone that a browser opens: the openDesk hosts of the applications that the zones keep, auth (the
# sign-in host of the zone gate, gate.py), sfu (LiveKit, ../platform/calls/install-calls.py) and hoover.
HOSTS=['auth','portal','id','ics','files','office','pad','chat','matrix','mas','element-admin','matrix-neoboard-widget','matrix-neochoice-widget',
 'matrix-neodatefix-bot','matrix-neodatefix-widget','projects','wiki','notes','static','meet','mrtc','objectstorage','sfu','hoover']
def zone_hosts(zone):
 """The openDesk global.hosts of a zone: each default host name with the zone id in front, for example zone-a-portal."""
 return {key:f'{zone}-{name}' for key,name in OPENDESK_HOSTS.items()}
def ident(zone):return zone.replace('-','_')
def udm_password(length=40):
 """Return a password that the Nubus password check (cracklib) accepts.

 cracklib refuses a password with more than four neighbour pairs that step by one character code, such as ab or 32,
 as too simplistic/systematic. A SHA-1 hex value of openDesk often has more, so a new zone gets this value instead.
 """
 alphabet=string.ascii_letters+string.digits
 while True:
  value=''.join(secrets.choice(alphabet) for _ in range(length))
  steps=sum(1 for a,b in zip(value,value[1:]) if abs(ord(a)-ord(b))==1)
  if steps<=2 and any(c.isdigit() for c in value) and any(c.isupper() for c in value) and any(c.islower() for c in value):return value
def load_secrets():
 path=out/'secrets.json'
 data=json.loads(path.read_text()) if path.exists() else {}
 # The shared JVB uses one XMPP password in every zone Prosody.
 calls=data.setdefault('calls',{})
 # LiveKit reads its keys only at start, so every zone signs its tokens with the one key LIVEKIT_KEY, and a new zone
 # does not restart LiveKit (../platform/calls/install-calls.py).
 for key in ('jvb_password','livekit_turn_secret','livekit_secret'):calls.setdefault(key,secrets.token_hex(24))
 for zone in ZONES:
  z=data.setdefault(zone,{})
  # An installed zone keeps the Administrator password that openDesk derived from its master password.
  if 'master_password' not in z:z['administrator_password']=udm_password()
  z.setdefault('master_password',secrets.token_hex(24))
  # Each zone has its own TURN secret, because coturn serves every zone. livekit_secret of an earlier version stays unused.
  z.setdefault('turn_secret',secrets.token_hex(24))
  # The Keycloak client of Hoover and its oauth2-proxy share this secret (hoover_oidc).
  z.setdefault('hoover_oidc_secret',secrets.token_hex(24))
  # The Keycloak client of the zone gate and its oauth2-proxy share this secret (gate_oidc). The cookie secret has 32 bytes.
  z.setdefault('gate_oidc_secret',secrets.token_hex(24));z.setdefault('gate_cookie_secret',secrets.token_hex(16))
 out.mkdir(parents=True,exist_ok=True);put(path,json.dumps(data,indent=1));path.chmod(0o600)
 return data
def reduced_resources():
 """Lower the requests to 40 % of the openDesk defaults. Limits stay at the openDesk defaults."""
 source=yaml.safe_load((OPENDESK/'helmfile/environments/default/resources.yaml.gotmpl').read_text())['resources']
 def mebibytes(value):
  number,unit=re.fullmatch(r'([\d.]+)([KMG]i?|)',str(value)).groups()
  return float(number)*{'Ki':1/1024,'Mi':1,'Gi':1024,'K':1/1048.576,'M':1/1.048576,'G':953.674,'':1/1048576}[unit]
 def cores(value):
  text=str(value);return float(text[:-1])/1000 if text.endswith('m') else float(text)
 result={}
 for name,spec in source.items():
  requests=spec.get('requests') or {}
  if not requests:continue
  memory=max(32,int(mebibytes(requests['memory'])*0.4)) if 'memory' in requests else None
  result[name]={'requests':{'cpu':f"{int(min(cores(requests.get('cpu',0.05)),0.05)*1000)}m",**({'memory':f'{memory}Mi'} if memory else {})}}
 return result
def zone_values(zone,data,storage_class):
 z=data[zone]
 # The home chart serves global.domain, which is the domain of the site and of every zone, so no zone installs it.
 apps={name:{'enabled':False} for name in ['oxAppSuite','dovecot','postfix','clamavSimple','mariadb','neoboard','elementAdmin','home']}
 apps['notes']={'enabled':True}
 return {
  # openDesk names each host <global.hosts.x>.<global.domain>. The mail domain and the Matrix server name stay
  # <zone>.<suffix>, so the Matrix IDs and the mail addresses of each zone differ.
  'global':{'domain':SUFFIX,'hosts':zone_hosts(zone),'mailDomain':settings.zone_domain(zone),'matrixDomain':settings.zone_domain(zone)},
  'apps':apps,
  'antivirus':{'icap':{'host':None},'milter':{'host':None}},
  'certificate':{'create':False},
  # The bundle of the zone is the Mozilla bundle that openDesk composes. A local frontend adds its local CA
  # (../platform/frontend/install-local-frontend.sh), because the pods reach the zone names through that frontend.
  'trust':{'create':True,'secret':{'mount':True,'name':'hoover-ca-bundle'},**local_ca()},
  'cluster':{'networking':{'ipFamilies':'IPv4'},'service':{'type':'ClusterIP'}},
  # The file system volumes of the apps use the default tier of the zone, on the node where the scheduler binds them.
  'persistence':{'storageClassNames':{'RWO':storage_class}},
  'resources':reduced_resources(),
  # Helm waits this many seconds for each of these releases. The openDesk values of 300 s and 600 s ran out during a
  # zone create while other zones started on the same nodes: the Synapse account bootstrap of the meetings bot, the
  # Nextcloud management Job, the OpenProject bootstrap and XWiki. A timeout made the whole install run again.
  'deployment':{'timeouts':{'releases':{'matrixNeodatefixBotBootstrap':900,'opendeskMatrixUserVerificationServiceBootstrap':900,
    'opendeskNextcloudManagement':1200,'opendeskOpenprojectBootstrap':900,'openproject':1200,'xwiki':1200}}},
  # The MVP has no MFA and no email, so the zone login asks only for the user name and password.
  'functional':{'authentication':{'twoFactor':{'groups':[]},'newDeviceLoginNotification':{'enabled':False},
    'oidc':oidc_clients(zone)},
    'portal':{'custom':{'extraDataFiles':{'90-hoover-portal.yaml':hoover_portal(zone)}}},
    # The deploy timestamp changes at each render, so every installer run would upgrade the Nubus release.
    'admin':{'portal':{'deploymentTimestamp':{'enabled':False}}},
    # XWiki, OpenProject, Nextcloud and OX take this language as the default. The openDesk default is de_DE.
    # OpenProject and XWiki write their seed content in it when a zone is created.
    'internationalization':{'defaultLanguage':'en_GB'}},
  'customization':{'release':{'opendeskElement':[str(out/'synapse-url-preview.yaml'),str(out/zone/'calls-matrix.yaml')],'jitsi':[str(out/'calls-jitsi.yaml')],
    'ums':[str(out/'two-factor-off.yaml'),str(out/'nats-sync.yaml'),str(out/'nats-probes.yaml')],
    'redis':[str(out/'redis-probes.yaml')],'xwiki':[str(out/'xwiki-group-sync.yaml'),str(out/'xwiki-title.yaml')],
    'openproject':[str(out/'openproject-title.yaml')],'intercomService':[str(out/zone/'intercom.yaml')]}},
  # The Nextcloud image adds the Assistant and integration_openai apps. zone.py builds and pushes it.
  'images':{'nextcloud':{'registry':REGISTRY,'repository':'hoover/nextcloud-ai','tag':NEXTCLOUD_IMAGE_TAG}},
  # Calls use the shared coturn, LiveKit and JVB in the namespace calls (../platform/calls/install-calls.py).
  'turn':{'transport':'udp','server':{'host':f'turn.{SUFFIX}','port':'3478'},'tls':{'host':'','port':'5349'}},
  'secrets':{'turn':{'sharedSecret':{'value':z['turn_secret']}},'matrixRTC':{'livekitAuthSecret':{'value':data['calls']['livekit_secret']}},
   'jitsi':{'jvbAuthPassword':{'value':data['calls']['jvb_password']}},
   **({'nubus':{'systemAccounts':{'administratorPassword':{'value':z['administrator_password']}}}} if 'administrator_password' in z else {})},
  # Notes and Collabora use the private LLM in private/ai.json. zone-ai.py applies the same values to running zones.
  'ai':ai_values(),
 }
def hoover_oidc(zone):
 """Return the Hoover Keycloak client and the scope that carries the proxy claims."""
 host=f"https://{settings.zone_host(zone,'hoover')}"
 scope={'name':'opendesk-hoover-scope','description':'Claims for the Hoover proxy.','protocol':'openid-connect','protocolMappers':[
  {'name':'opendesk_username','protocol':'openid-connect','protocolMapper':'oidc-usermodel-attribute-mapper','consentRequired':False,
   'config':{'userinfo.token.claim':'true','user.attribute':'uid','id.token.claim':'true','access.token.claim':'true','claim.name':'opendesk_username','jsonType.label':'String'}},
  {'name':'email','protocol':'openid-connect','protocolMapper':'oidc-usermodel-attribute-mapper','consentRequired':False,
   'config':{'userinfo.token.claim':'true','user.attribute':'mailPrimaryAddress','id.token.claim':'true','access.token.claim':'true','claim.name':'email','jsonType.label':'String'}},
  {'name':'given_name','protocol':'openid-connect','protocolMapper':'oidc-usermodel-attribute-mapper','consentRequired':False,
   'config':{'userinfo.token.claim':'true','user.attribute':'firstname','id.token.claim':'true','access.token.claim':'true','claim.name':'given_name','jsonType.label':'String'}},
  {'name':'family_name','protocol':'openid-connect','protocolMapper':'oidc-usermodel-attribute-mapper','consentRequired':False,
   'config':{'userinfo.token.claim':'true','user.attribute':'lastname','id.token.claim':'true','access.token.claim':'true','claim.name':'family_name','jsonType.label':'String'}},
  {'name':'groups','protocol':'openid-connect','protocolMapper':'oidc-group-membership-mapper','consentRequired':False,
   'config':{'full.path':'false','id.token.claim':'true','access.token.claim':'true','userinfo.token.claim':'true','claim.name':'groups'}},
  # Keycloak 25 and later put the sign-in nonce only in the first ID token. The Hoover proxy compares the nonce after
  # each refresh, and without this mapper it drops the session at the first refresh, one minute after sign-in.
  {'name':'nonce','protocol':'openid-connect','protocolMapper':'oidc-nonce-backwards-compatible-mapper','consentRequired':False,'config':{}}]}
 client={'name':'opendesk-hoover','clientId':'opendesk-hoover','protocol':'openid-connect','clientAuthenticatorType':'client-secret',
  'secret':{'existingSecret':{'name':'hoover-oidc','key':'client-secret'}},
  'redirectUris':[f'{host}/oauth2/callback'],'standardFlowEnabled':True,'implicitFlowEnabled':False,'directAccessGrantsEnabled':False,
  'publicClient':False,'consentRequired':False,
  # oauth2-proxy has no back-channel logout. A logout through Keycloak loads the proxy sign-out in the browser, which
  # removes the proxy cookie at once. The short access token ends a session that a logout in another browser ended.
  'frontchannelLogout':True,
  'attributes':{'post.logout.redirect.uris':f"{host}/*##https://{settings.zone_host(zone,'portal')}/*",
   'frontchannel.logout.url':f'{host}/oauth2/sign_out','frontchannel.logout.session.required':'false','access.token.lifespan':'60'},
  'defaultClientScopes':['opendesk-hoover-scope']}
 return {'clientScopes':{'opendesk-hoover-scope':scope},'clients':{'opendesk-hoover':client}}
def gate_oidc(zone):
 """Return the Keycloak client of the zone gate. Its oauth2-proxy answers at <zone>-auth.<suffix> (gate.py)."""
 host=f"https://{settings.zone_host(zone,'auth')}"
 client={'name':'opendesk-gate','clientId':'opendesk-gate','protocol':'openid-connect','clientAuthenticatorType':'client-secret',
  'secret':{'existingSecret':{'name':'gate-oidc','key':'client-secret'}},
  'redirectUris':[f'{host}/oauth2/callback'],'standardFlowEnabled':True,'implicitFlowEnabled':False,'directAccessGrantsEnabled':False,
  'publicClient':False,'consentRequired':False,'frontchannelLogout':True,
  'attributes':{'post.logout.redirect.uris':f"https://{settings.zone_host(zone,'portal')}/*",'frontchannel.logout.url':f'{host}/oauth2/sign_out',
   'frontchannel.logout.session.required':'false','access.token.lifespan':'60'},
  # Without the email scope the tokens carry no unverified mail address, which oauth2-proxy refuses.
  'defaultClientScopes':['profile'],'optionalClientScopes':[]}
 return {'clients':{'opendesk-gate':client}}
def oidc_clients(zone):
 hoover,gate=hoover_oidc(zone),gate_oidc(zone)
 return {'clientScopes':hoover['clientScopes'],'clients':{**hoover['clients'],**gate['clients']}}
def hoover_portal(zone):
 host=f"https://{settings.zone_host(zone,'hoover')}"
 icon='PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMTEiIGhlaWdodD0iMTExIiB2aWV3Qm94PSIwIDAgMTExIDExMSI+PHJlY3Qgd2lkdGg9IjExMSIgaGVpZ2h0PSIxMTEiIHJ4PSIyMCIgZmlsbD0iI0ZGRiIvPjxjaXJjbGUgY3g9IjQ4IiBjeT0iNDgiIHI9IjIyIiBmaWxsPSJub25lIiBzdHJva2U9IiMzNDEyOTEiIHN0cm9rZS13aWR0aD0iOCIvPjxwYXRoIGQ9Ik02NCA2NEw4NCA4NCIgc3Ryb2tlPSIjNTcxRUZBIiBzdHJva2Utd2lkdGg9IjEwIiBzdHJva2UtbGluZWNhcD0icm91bmQiLz48L3N2Zz4='
 return ('---\naction: "create_or_modify"\nmodule: "portals/entry"\n'
  'position: "cn=entry,cn=portals,cn=univention,dc=swp-ldap,dc=internal"\nproperties:\n  name: "hoover"\n'
  '  displayName:\n    en_US: "Hoover"\n    de_DE: "Hoover"\n  description:\n'
  '    en_US: "Search documents in this zone."\n    de_DE: "Dokumente in dieser Zone suchen."\n'
  # UDM takes each link as a [locale, URL] pair, as in the openDesk portal entries.
  f'  link:\n    - - "en_US"\n      - "{host}"\n  linkTarget: "newwindow"\n  activated: true\n'
  '  anonymous: false\n  allowedGroups:\n    - "cn=Domain Users,cn=groups,dc=swp-ldap,dc=internal"\n'
  f'  icon: "{icon}"\n...\n---\naction: "ensure_list_contains"\nmodule: "portals/category"\n'
  'position: "cn=od.applications,cn=category,cn=portals,cn=univention,dc=swp-ldap,dc=internal"\nproperties:\n'
  '  entries:\n    - "cn=hoover,cn=entry,cn=portals,cn=univention,dc=swp-ldap,dc=internal"\n...\n')
def origin_regex(zone):
 """The origins of the pages of a zone: https://<zone>-<app>.<suffix>, also as a bare host name."""
 # Only the dots need an escape: a zone id and a domain hold letters, digits, - and dots.
 return '(^|//)'+zone+'-[a-z0-9-]+'+('.'+SUFFIX).replace('.','\\.')+'$'
def ai_values():
 path=settings.PRIVATE/'ai.json'
 if not path.exists():return {'endpoint':'','apiKey':{'value':''},'model':''}
 ai=json.loads(path.read_text())
 return {'endpoint':ai['endpoint'],'apiKey':{'value':pathlib.Path(ai['api_key_file']).read_text().strip()},'model':ai['model'],'allowUserSettings':False}
def default_class(zone):
 """Return the StorageClass of the file system volumes of a zone."""
 return zonestate.tier(zone,'default',zonestate.site_tiers(settings.KUBECONFIG))+'-ext4'
def main():
 data=load_secrets()
 # The zone Jitsi keeps web, Prosody and Jicofo. The shared JVB in the namespace calls joins each zone Prosody.
 put(out/'calls-jitsi.yaml',yaml.safe_dump({'jitsi':{'jvb':{'replicaCount':0,'service':{'enabled':False}},
  'jicofo':{'extraEnvs':{'JICOFO_MAX_MEMORY':'512m'}},'prosody':{'extraEnvs':{'LOG_LEVEL':'warn'}}}},sort_keys=False))
 # The Nubus chart syncs JetStream every 10 ms. Idle, that gave about 960 writes per second on each zone volume.
 # The chart blocks URL previews only for some private ranges. Pod, Service and loopback addresses stay reachable,
 # so a chat user could make Synapse fetch internal URLs. This list is the Synapse sample list for private ranges.
 ranges=['127.0.0.0/8','10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','100.64.0.0/10','192.0.0.0/24','169.254.0.0/16','192.88.99.0/24',
  '198.18.0.0/15','192.0.2.0/24','198.51.100.0/24','203.0.113.0/24','224.0.0.0/4','::1/128','fe80::/10','fc00::/7','2001:db8::/32','ff00::/8','fec0::/10']
 put(out/'synapse-url-preview.yaml','synapse:\n  additional:\n    9-hooverUrlPreview:\n      config: |\n        url_preview_ip_range_blacklist:\n'+''.join(f"          - '{r}'\n" for r in ranges))
 # XWiki imports LDAP groups, and with them the admin group, only in two scheduler jobs at night.
 # Each job runs every minute instead, so a group change reaches XWiki within a minute.
 # The jobs run as XWiki.superadmin, which needs no login.
 # openDesk passes each properties entry to XWiki as a -D option, and XWiki stores the value at start.
 # The jobs read group members through the LDAP group cache, which openDesk keeps for 300 s. The zones keep it for 60 s.
 job='property:xwiki:LDAPUserImport.{}^XWiki.SchedulerJobClass.cron'
 # XWiki installs extensions only from the repository in manifests/xwiki-extensions.yaml.
 # The openDesk templates set German window titles for XWiki and OpenProject, independent of the default language.
 put(out/'xwiki-title.yaml','properties:\n  "property:xwiki:XWiki.XWikiPreferences^XWiki.XWikiPreferences.title": "Knowledge - $!tdoc.displayTitle - openDesk"\n')
 put(out/'openproject-title.yaml','environment:\n  OPENPROJECT_APP__TITLE: "Projects - openDesk"\n')
 put(out/'xwiki-group-sync.yaml','properties:\n'+f'  "{job.format("LDAPGroupImportJob")}": "0 * * * * ?"\n'+f'  "{job.format("MappedGroupsDailyUpdater")}": "30 * * * * ?"\n'
  +'customConfigs:\n  xwiki.cfg:\n    xwiki.authentication.ldap.groupcache_expiration: 60\n  xwiki.properties:\n    extension.repositories: "hoover:maven:http://xwiki-extensions.extensions.svc.cluster.local/repo/"\n')
 put(out/'nats-sync.yaml','# A sync each second limits a host crash to one second of provisioning events.\nnubusProvisioning:\n  nats:\n    config:\n      jetstream:\n        fileStore:\n          sync_interval: 1s\n')
 put(out/'nats-probes.yaml','nubusProvisioning:\n  nats:\n    startupProbe:\n      httpGet: {path: "/healthz?js-enabled-only=true", port: monitor}\n      initialDelaySeconds: 0\n      periodSeconds: 1\n      failureThreshold: 120\n      timeoutSeconds: 5\n    readinessProbe:\n      httpGet: {path: "/healthz?js-enabled-only=true", port: monitor}\n      initialDelaySeconds: 0\n      periodSeconds: 2\n      failureThreshold: 3\n      timeoutSeconds: 5\n    livenessProbe:\n      httpGet: {path: "/healthz?js-enabled-only=true", port: monitor}\n      initialDelaySeconds: 0\n      periodSeconds: 10\n      failureThreshold: 3\n      timeoutSeconds: 5\n')
 put(out/'redis-probes.yaml','master:\n  readinessProbe:\n    exec: {command: ["/bin/bash", "-ec", "/health/ping_readiness_local.sh 1"]}\n    initialDelaySeconds: 0\n    periodSeconds: 1\n    failureThreshold: 5\n    timeoutSeconds: 2\n  livenessProbe:\n    exec: {command: ["/bin/bash", "-ec", "/health/ping_liveness_local.sh 5"]}\n    initialDelaySeconds: 5\n    periodSeconds: 5\n    failureThreshold: 5\n    timeoutSeconds: 6\n')
 put(out/'two-factor-off.yaml','# The MVP has no MFA.\nnubusKeycloakBootstrap:\n  bootstrap:\n    twoFactorAuthentication:\n      enabled: false\n')
 for zone in ZONES:
  folder=out/zone;folder.mkdir(exist_ok=True)
  put(folder/'values.yaml',yaml.safe_dump(zone_values(zone,data,default_class(zone)),sort_keys=False));(folder/'values.yaml').chmod(0o600)
  put(folder/'master-password',data[zone]['master_password']);(folder/'master-password').chmod(0o600)
  # The Keycloak bootstrap reads the Hoover and gate client secrets from these Secrets. zone.py applies them before Helm.
  # data, not stringData: kubectl apply reports a stringData Secret as changed on each run.
  def b64(value):return base64.b64encode(value.encode()).decode()
  oidc={'apiVersion':'v1','kind':'List','items':[
   {'apiVersion':'v1','kind':'Secret','metadata':{'name':'hoover-oidc','namespace':zone},'type':'Opaque',
    'data':{'client-secret':b64(data[zone]['hoover_oidc_secret'])}},
   # The gate client of Keycloak and the gate oauth2-proxy read this Secret.
   {'apiVersion':'v1','kind':'Secret','metadata':{'name':'gate-oidc','namespace':zone},'type':'Opaque',
    'data':{'client-secret':b64(data[zone]['gate_oidc_secret']),'cookie-secret':b64(data[zone]['gate_cookie_secret'])}}]}
  put(folder/'hoover-oidc-secret.json',json.dumps(oidc));(folder/'hoover-oidc-secret.json').chmod(0o600)
  # The intercom service answers the cross-origin requests of the pages of its own zone only. The openDesk value is
  # global.domain, which matches the pages of every zone of the site. Its chart builds the Keycloak and portal URLs
  # from the fixed host names id and portal, so the zone gives them in full.
  put(folder/'intercom.yaml',yaml.safe_dump({'ics':{'originRegex':origin_regex(zone),
   'keycloak':{'url':f"https://{settings.zone_host(zone,'id')}"},'portal':{'url':f"https://{settings.zone_host(zone,'portal')}"}}}))
  # lk-jwt of each zone signs tokens with the shared key LIVEKIT_KEY for the shared LiveKit. Without its own SFU, the chart does not
  # set LIVEKIT_URL. lk-jwt polls the SFU for gone participants, because the shared SFU sends no webhooks.
  put(folder/'calls-matrix.yaml',yaml.safe_dump({'matrixRTC':{'sfu':{'enabled':False},'livekitAuth':{'key':LIVEKIT_KEY},
   'extraEnv':[{'name':'LIVEKIT_URL','value':f"wss://{settings.zone_host(zone,'sfu')}"},{'name':'LIVEKIT_SANITY_CHECK_INTERVAL_SECONDS','value':'10'},
    # lk-jwt logs each health probe at info, so the level is warn to keep the log writes low.
    {'name':'LIVEKIT_LOG_LEVEL','value':'warn'}],
   # lk-jwt finds the homeserver through the server well-known over HTTPS, so it needs the frontend CA like the other parts.
   'extraVolumes':[{'name':'trusted-cert-secret-volume','secret':{'secretName':'hoover-ca-bundle','items':[{'key':'ca.crt','path':'ca-certificates.crt'}]}}],
   'extraVolumeMounts':[{'name':'trusted-cert-secret-volume','mountPath':'/etc/ssl/certs/ca-certificates.crt','subPath':'ca-certificates.crt'}]}},sort_keys=False))
 # install-server-names.sh writes these names into /etc/hosts of the workstation.
 put(out/'frontend.env',f"zones=({' '.join(ZONES)})\nsuffix={SUFFIX}\nhosts=({' '.join(HOSTS)})\nextra_hosts=(operator.{SUFFIX})\nbind_extra=({' '.join(settings.FRONTEND_BIND)})\n")
 print(json.dumps({'zones':ZONES,'output':str(out)}))
if __name__=='__main__':
 # The zone steps of deploy-k3s up can run at the same time, and each one runs this file. One run at a time writes the
 # secrets and the values.
 import fcntl
 out.mkdir(parents=True,exist_ok=True)
 with open(out/'.zones.lock','w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  main()
