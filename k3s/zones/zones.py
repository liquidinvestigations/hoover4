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

def local_ca():
 """The local CA of the frontend for the trust bundle of a zone, when the frontend runs on the local node."""
 path=settings.PRIVATE/'frontend/local-ca.crt'
 if not settings.HOST.get('frontend_local') or not path.exists():return {}
 return {'certificateAuthorities':{'values':{'hoover4-local-ca.crt':path.read_text()}}}

def zone_names():
 try:return list(zonestate.load()['zones'])
 except zonestate.ZoneStateError:
  if zonestate.PATH.exists():raise
  return []
ZONES=zone_names()
NEXTCLOUD_IMAGE_TAG='33.0.9-2'
XWIKI_EXTENSIONS_TAG='llm-0.11'
SUFFIX=settings.SUFFIX
# Pods name the images of the cluster registry with this host name. Each node maps it to the registry endpoint.
REGISTRY='registry.hoover.internal'
# These host names follow the openDesk global.hosts defaults for the applications that the zones keep.
# auth is the sign-in host of the zone gate (gate.py).
HOSTS=['auth','portal','id','ics','files','office','pad','chat','matrix','mas','element-admin','matrix-neoboard-widget','matrix-neochoice-widget',
 'matrix-neodatefix-bot','matrix-neodatefix-widget','projects','wiki','notes','static','meet','mrtc','sfu']
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
 for key in ('jvb_password','livekit_turn_secret'):calls.setdefault(key,secrets.token_hex(24))
 for zone in ZONES:
  z=data.setdefault(zone,{})
  # An installed zone keeps the Administrator password that openDesk derived from its master password.
  if 'master_password' not in z:z['administrator_password']=udm_password()
  z.setdefault('master_password',secrets.token_hex(24))
  # Each zone has its own TURN secret and LiveKit key, because coturn and LiveKit serve every zone.
  z.setdefault('turn_secret',secrets.token_hex(24));z.setdefault('livekit_secret',secrets.token_hex(24))
  # The Keycloak client of Hoover and its oauth2-proxy share this secret (hoover_oidc).
  z.setdefault('hoover_oidc_secret',secrets.token_hex(24))
  # The Keycloak client of the zone gate and its oauth2-proxy share this secret (gate_oidc). The cookie secret has 32 bytes.
  z.setdefault('gate_oidc_secret',secrets.token_hex(24));z.setdefault('gate_cookie_secret',secrets.token_hex(16))
 out.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,indent=1));path.chmod(0o600)
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
 apps={name:{'enabled':False} for name in ['oxAppSuite','dovecot','postfix','clamavSimple','mariadb','neoboard','elementAdmin']}
 apps['notes']={'enabled':True}
 return {
  'global':{'domain':f'{zone}.{SUFFIX}'},
  'apps':apps,
  'antivirus':{'icap':{'host':None},'milter':{'host':None}},
  'certificate':{'create':False},
  # The bundle of the zone is the Mozilla bundle that openDesk composes. A local frontend adds its local CA
  # (../platform/frontend/install-local-frontend.sh), because the pods reach the zone names through that frontend.
  'trust':{'create':True,'secret':{'mount':True,'name':'hoover-ca-bundle'},**local_ca()},
  'cluster':{'networking':{'ipFamilies':'IPv4'},'service':{'type':'ClusterIP'}},
  # The file system volumes of the apps use the default tier of the zone on its home node.
  'persistence':{'storageClassNames':{'RWO':storage_class}},
  'resources':reduced_resources(),
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
    'openproject':[str(out/'openproject-title.yaml')]}},
  # The Nextcloud image adds the Assistant and integration_openai apps. zone.py builds and pushes it.
  'images':{'nextcloud':{'registry':REGISTRY,'repository':'hoover/nextcloud-ai','tag':NEXTCLOUD_IMAGE_TAG}},
  # Calls use the shared coturn, LiveKit and JVB in the namespace calls (../platform/calls/install-calls.py).
  'turn':{'transport':'udp','server':{'host':f'turn.{SUFFIX}','port':'3478'},'tls':{'host':'','port':'5349'}},
  'secrets':{'turn':{'sharedSecret':{'value':z['turn_secret']}},'matrixRTC':{'livekitAuthSecret':{'value':z['livekit_secret']}},
   'jitsi':{'jvbAuthPassword':{'value':data['calls']['jvb_password']}},
   **({'nubus':{'systemAccounts':{'administratorPassword':{'value':z['administrator_password']}}}} if 'administrator_password' in z else {})},
  # Notes and Collabora use the private LLM in private/ai.json. zone-ai.py applies the same values to running zones.
  'ai':ai_values(),
 }
def hoover_oidc(zone):
 """Return the Hoover Keycloak client and the scope that carries the proxy claims."""
 host=f'https://hoover.{zone}.{SUFFIX}'
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
  'attributes':{'post.logout.redirect.uris':f'{host}/*##https://portal.{zone}.{SUFFIX}/*',
   'frontchannel.logout.url':f'{host}/oauth2/sign_out','frontchannel.logout.session.required':'false','access.token.lifespan':'60'},
  'defaultClientScopes':['opendesk-hoover-scope']}
 return {'clientScopes':{'opendesk-hoover-scope':scope},'clients':{'opendesk-hoover':client}}
def gate_oidc(zone):
 """Return the Keycloak client of the zone gate. Its oauth2-proxy answers at auth.<zone>.<suffix> (gate.py)."""
 host=f'https://auth.{zone}.{SUFFIX}'
 client={'name':'opendesk-gate','clientId':'opendesk-gate','protocol':'openid-connect','clientAuthenticatorType':'client-secret',
  'secret':{'existingSecret':{'name':'gate-oidc','key':'client-secret'}},
  'redirectUris':[f'{host}/oauth2/callback'],'standardFlowEnabled':True,'implicitFlowEnabled':False,'directAccessGrantsEnabled':False,
  'publicClient':False,'consentRequired':False,'frontchannelLogout':True,
  'attributes':{'post.logout.redirect.uris':f'https://portal.{zone}.{SUFFIX}/*','frontchannel.logout.url':f'{host}/oauth2/sign_out',
   'frontchannel.logout.session.required':'false','access.token.lifespan':'60'},
  # Without the email scope the tokens carry no unverified mail address, which oauth2-proxy refuses.
  'defaultClientScopes':['profile'],'optionalClientScopes':[]}
 return {'clients':{'opendesk-gate':client}}
def oidc_clients(zone):
 hoover,gate=hoover_oidc(zone),gate_oidc(zone)
 return {'clientScopes':hoover['clientScopes'],'clients':{**hoover['clients'],**gate['clients']}}
def hoover_portal(zone):
 host=f'https://hoover.{zone}.{SUFFIX}'
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
def ai_values():
 path=settings.PRIVATE/'ai.json'
 if not path.exists():return {'endpoint':'','apiKey':{'value':''},'model':''}
 ai=json.loads(path.read_text())
 return {'endpoint':ai['endpoint'],'apiKey':{'value':pathlib.Path(ai['api_key_file']).read_text().strip()},'model':ai['model'],'allowUserSettings':False}
def default_class(zone):
 """Return the StorageClass of the file system volumes of a zone."""
 home=zonestate.home(zone)
 return zonestate.tier(zone,'default',zonestate.node_tiers(home,settings.KUBECONFIG))+'-ext4'
def main():
 data=load_secrets()
 # The zone Jitsi keeps web, Prosody and Jicofo. The shared JVB in the namespace calls joins each zone Prosody.
 (out/'calls-jitsi.yaml').write_text(yaml.safe_dump({'jitsi':{'jvb':{'replicaCount':0,'service':{'enabled':False}},
  'jicofo':{'extraEnvs':{'JICOFO_MAX_MEMORY':'512m'}},'prosody':{'extraEnvs':{'LOG_LEVEL':'warn'}}}},sort_keys=False))
 # The Nubus chart syncs JetStream every 10 ms. Idle, that gave about 960 writes per second on each zone volume.
 # The chart blocks URL previews only for some private ranges. Pod, Service and loopback addresses stay reachable,
 # so a chat user could make Synapse fetch internal URLs. This list is the Synapse sample list for private ranges.
 ranges=['127.0.0.0/8','10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','100.64.0.0/10','192.0.0.0/24','169.254.0.0/16','192.88.99.0/24',
  '198.18.0.0/15','192.0.2.0/24','198.51.100.0/24','203.0.113.0/24','224.0.0.0/4','::1/128','fe80::/10','fc00::/7','2001:db8::/32','ff00::/8','fec0::/10']
 (out/'synapse-url-preview.yaml').write_text('synapse:\n  additional:\n    9-hooverUrlPreview:\n      config: |\n        url_preview_ip_range_blacklist:\n'+''.join(f"          - '{r}'\n" for r in ranges))
 # XWiki imports LDAP groups, and with them the admin group, only in two scheduler jobs at night.
 # Each job runs every minute instead, so a group change reaches XWiki within a minute.
 # The jobs run as XWiki.superadmin, which needs no login.
 # openDesk passes each properties entry to XWiki as a -D option, and XWiki stores the value at start.
 # The jobs read group members through the LDAP group cache, which openDesk keeps for 300 s. The zones keep it for 60 s.
 job='property:xwiki:LDAPUserImport.{}^XWiki.SchedulerJobClass.cron'
 # XWiki installs extensions only from the repository in manifests/xwiki-extensions.yaml.
 # The openDesk templates set German window titles for XWiki and OpenProject, independent of the default language.
 (out/'xwiki-title.yaml').write_text('properties:\n  "property:xwiki:XWiki.XWikiPreferences^XWiki.XWikiPreferences.title": "Knowledge - $!tdoc.displayTitle - openDesk"\n')
 (out/'openproject-title.yaml').write_text('environment:\n  OPENPROJECT_APP__TITLE: "Projects - openDesk"\n')
 (out/'xwiki-group-sync.yaml').write_text('properties:\n'+f'  "{job.format("LDAPGroupImportJob")}": "0 * * * * ?"\n'+f'  "{job.format("MappedGroupsDailyUpdater")}": "30 * * * * ?"\n'
  +'customConfigs:\n  xwiki.cfg:\n    xwiki.authentication.ldap.groupcache_expiration: 60\n  xwiki.properties:\n    extension.repositories: "hoover:maven:http://xwiki-extensions.extensions.svc.cluster.local/repo/"\n')
 (out/'nats-sync.yaml').write_text('# A sync each second limits a host crash to one second of provisioning events.\nnubusProvisioning:\n  nats:\n    config:\n      jetstream:\n        fileStore:\n          sync_interval: 1s\n')
 (out/'nats-probes.yaml').write_text('nubusProvisioning:\n  nats:\n    startupProbe:\n      httpGet: {path: "/healthz?js-enabled-only=true", port: monitor}\n      initialDelaySeconds: 0\n      periodSeconds: 1\n      failureThreshold: 120\n      timeoutSeconds: 5\n    readinessProbe:\n      httpGet: {path: "/healthz?js-enabled-only=true", port: monitor}\n      initialDelaySeconds: 0\n      periodSeconds: 2\n      failureThreshold: 3\n      timeoutSeconds: 5\n    livenessProbe:\n      httpGet: {path: "/healthz?js-enabled-only=true", port: monitor}\n      initialDelaySeconds: 0\n      periodSeconds: 10\n      failureThreshold: 3\n      timeoutSeconds: 5\n')
 (out/'redis-probes.yaml').write_text('master:\n  readinessProbe:\n    exec: {command: ["/bin/bash", "-ec", "/health/ping_readiness_local.sh 1"]}\n    initialDelaySeconds: 0\n    periodSeconds: 1\n    failureThreshold: 5\n    timeoutSeconds: 2\n  livenessProbe:\n    exec: {command: ["/bin/bash", "-ec", "/health/ping_liveness_local.sh 5"]}\n    initialDelaySeconds: 5\n    periodSeconds: 5\n    failureThreshold: 5\n    timeoutSeconds: 6\n')
 (out/'two-factor-off.yaml').write_text('# The MVP has no MFA.\nnubusKeycloakBootstrap:\n  bootstrap:\n    twoFactorAuthentication:\n      enabled: false\n')
 for zone in ZONES:
  folder=out/zone;folder.mkdir(exist_ok=True)
  (folder/'values.yaml').write_text(yaml.safe_dump(zone_values(zone,data,default_class(zone)),sort_keys=False));(folder/'values.yaml').chmod(0o600)
  (folder/'master-password').write_text(data[zone]['master_password']);(folder/'master-password').chmod(0o600)
  # The Keycloak bootstrap reads the Hoover and gate client secrets from these Secrets. zone.py applies them before Helm.
  # data, not stringData: kubectl apply reports a stringData Secret as changed on each run.
  def b64(value):return base64.b64encode(value.encode()).decode()
  oidc={'apiVersion':'v1','kind':'List','items':[
   {'apiVersion':'v1','kind':'Secret','metadata':{'name':'hoover-oidc','namespace':zone},'type':'Opaque',
    'data':{'client-secret':b64(data[zone]['hoover_oidc_secret'])}},
   # The gate client of Keycloak and the gate oauth2-proxy read this Secret.
   {'apiVersion':'v1','kind':'Secret','metadata':{'name':'gate-oidc','namespace':zone},'type':'Opaque',
    'data':{'client-secret':b64(data[zone]['gate_oidc_secret']),'cookie-secret':b64(data[zone]['gate_cookie_secret'])}}]}
  (folder/'hoover-oidc-secret.json').write_text(json.dumps(oidc));(folder/'hoover-oidc-secret.json').chmod(0o600)
  # lk-jwt of each zone signs tokens with the zone key for the shared LiveKit. Without its own SFU, the chart does not
  # set LIVEKIT_URL. lk-jwt polls the SFU for gone participants, because the shared SFU sends no webhooks.
  (folder/'calls-matrix.yaml').write_text(yaml.safe_dump({'matrixRTC':{'sfu':{'enabled':False},'livekitAuth':{'key':zone},
   'extraEnv':[{'name':'LIVEKIT_URL','value':f'wss://sfu.{zone}.{SUFFIX}'},{'name':'LIVEKIT_SANITY_CHECK_INTERVAL_SECONDS','value':'10'},
    # lk-jwt logs each health probe at info, so the level is warn to keep the log writes low.
    {'name':'LIVEKIT_LOG_LEVEL','value':'warn'}],
   # lk-jwt finds the homeserver through the server well-known over HTTPS, so it needs the frontend CA like the other parts.
   'extraVolumes':[{'name':'trusted-cert-secret-volume','secret':{'secretName':'hoover-ca-bundle','items':[{'key':'ca.crt','path':'ca-certificates.crt'}]}}],
   'extraVolumeMounts':[{'name':'trusted-cert-secret-volume','mountPath':'/etc/ssl/certs/ca-certificates.crt','subPath':'ca-certificates.crt'}]}},sort_keys=False))
 (out/'frontend.env').write_text(f"zones=({' '.join(ZONES)})\nsuffix={SUFFIX}\nhosts=({' '.join(HOSTS)})\nextra_hosts=(operator.{SUFFIX})\nbind_extra=({' '.join(settings.FRONTEND_BIND)})\n")
 print(json.dumps({'zones':ZONES,'output':str(out)}))
if __name__=='__main__':main()
