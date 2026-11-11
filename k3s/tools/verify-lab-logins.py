#!/usr/bin/env python3
"""Check every login of the inventory password table. Usage: verify-lab-logins.py [--no-platform] [zone ...]

Each check signs in the way a person does, or checks the password where the login is in the cluster only.
Each request asks for a page, so the zone gate sends it to the Keycloak sign-in. The checks of the internal admin logins
sign in at the gate as Administrator first. The Keycloak admin check connects to the VPN address of the frontend,
because the frontend refuses the admin routes outside vpn_cidr.
An application answers 502 or 503 while it starts. A check repeats such a request for up to 600 seconds.
Without zones the script checks every zone of the zone state. --no-platform leaves out the operator portal and Grafana,
for a cluster that does not run them yet. Each zone check covers Administrator, test.user and the users of zone-users.json.
The script prints one line for each login and no password. It exits with 1 when a check fails.
"""
import base64,html,ipaddress,shlex,socket,http.cookiejar,json,pathlib,re,subprocess,sys,time,urllib.error,urllib.parse,urllib.request
root=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(root.parent));import settings
settings.use_kubeconfig()
sys.path.insert(0,str(root));sys.path.insert(0,str(root.parent/'zones'));import zonestate
import importlib;operator_login=importlib.import_module('verify-operator-login')
def secret(zone,name,key):
 return base64.b64decode(json.loads(subprocess.check_output(['kubectl','-n',zone,'get','secret',name,'-o','json']))['data'][key]).decode()
def browser():
 jar=http.cookiejar.CookieJar();o=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
 o.addheaders=[('Accept','text/html,*/*')];o.jar=jar;return o
# A host name in VPN_HOSTS connects to the VPN address of the frontend. TLS and the Host header keep the name.
VPN=ipaddress.ip_network(settings.HOST.get('vpn_cidr','0.0.0.0/32'))
FRONTEND_VPN=next((a for a in settings.FRONTEND_BIND if ipaddress.ip_address(a) in VPN),None)
VPN_HOSTS=set();system_getaddrinfo=socket.getaddrinfo
def getaddrinfo(host,*args,**kwargs):return system_getaddrinfo(FRONTEND_VPN if host in VPN_HOSTS else host,*args,**kwargs)
socket.getaddrinfo=getaddrinfo
def request(o,url,data=None,headers={}):
 start=time.monotonic()
 while True:
  try:
   with o.open(urllib.request.Request(url,data=data,headers=headers),timeout=600) as r:status,landing,page=r.status,r.geturl(),r.read().decode(errors='replace')
  except urllib.error.HTTPError as e:status,landing,page=e.code,url,e.read().decode(errors='replace')
  if status not in (502,503) or time.monotonic()-start>600:return status,landing,page
  time.sleep(2)
def keycloak_login(o,url,user,password):
 """Open the URL, fill the Keycloak form, and return the final status, address and page."""
 status,landing,page=request(o,url)
 form=re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"',page)
 if not form:return status,landing,page
 return request(o,html.unescape(form.group(1)),urllib.parse.urlencode({'username':user,'password':password,'credentialId':''}).encode())
def gated(zone):
 """Return a browser that has the gate cookie of the zone for Administrator."""
 o=browser();status,landing,page=keycloak_login(o,f'https://auth.{zone}.{settings.SUFFIX}/oauth2/start?rd=/',
  'Administrator',secret(zone,'ums-nubus-credentials','administrator_password'))
 if not any(c.name=='_hoover_gate' for c in o.jar):
  raise RuntimeError(f'no gate cookie after the sign-in: {status} {landing.split("?")[0]}')
 return o
def basic(user,password):return {'Authorization':'Basic '+base64.b64encode(f'{user}:{password}'.encode()).decode()}
def in_pod(namespace,target,container,command,env={}):
 # Some images have no env program, so the shell sets the variables.
 exports=''.join(f'export {k}={shlex.quote(v)}; ' for k,v in env.items())
 args=['kubectl','-n',namespace,'exec',target]+(['-c',container] if container else [])+['--','sh','-c',exports+command]
 return subprocess.run(args,capture_output=True,text=True,timeout=120)
results=[]
def check(name,function):
 try:ok,detail=function()
 except Exception as e:ok,detail=False,f'{type(e).__name__}: {e}'[:160]
 results.append(ok);print(f"{'pass' if ok else 'FAIL'}  {name}  {detail}",flush=True)
def operator():
 operator_login.sign_in();return True,'Dex login opened the portal'
def grafana():
 data=json.loads(subprocess.check_output(['kubectl','-n','monitoring','get','secret','monitor-grafana','-o','json']))['data']
 user,password=(base64.b64decode(data[k]).decode() for k in ('admin-user','admin-password'))
 # The Grafana image has no shell, so the check uses a port forward to the runc pod.
 with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
 forward=subprocess.Popen(['kubectl','-n','monitoring','port-forward','deploy/monitor-grafana',f'{port}:3000'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:
  for _ in range(20):
   try:
    with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}/api/user',headers=basic(user,password)),timeout=10) as r:body=r.read().decode()
    return json.loads(body).get('login')==user,'local admin password accepted by the Grafana API'
   except urllib.error.HTTPError as e:return False,f'{e.code} from the Grafana API'
   except (urllib.error.URLError,ConnectionError):time.sleep(0.5)
  return False,'the port forward did not open'
 finally:forward.terminate()
def application(zone,user,password,url,host):
 def run():
  status,landing,page=keycloak_login(browser(),url,user,password)
  error=re.search(r'id="input-error"[^>]*>\s*([^<]+)',page)
  ok=status==200 and urllib.parse.urlparse(landing).hostname==host and not error
  return ok,f'{status} {landing.split("?")[0]}'+(f' Keycloak: {html.unescape(error.group(1).strip())}' if error else '')
 return run
def keycloak_admin(zone):
 d=f'{zone}.{settings.SUFFIX}';console=f'https://id.{d}/admin/master/console/'
 url=f'https://id.{d}/realms/master/protocol/openid-connect/auth?'+urllib.parse.urlencode({'client_id':'security-admin-console','redirect_uri':console,
  'response_type':'code','scope':'openid','state':'check','nonce':'check','code_challenge':'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM','code_challenge_method':'S256'})
 if not FRONTEND_VPN:return False,'frontend_bind has no address in vpn_cidr'
 VPN_HOSTS.add(f'id.{d}')
 status,landing,_=keycloak_login(gated(zone),url,'kcadmin',secret(zone,'keycloak-admin-password','adminPassword'))
 return status==200 and landing.startswith(console) and 'code=' in landing,f'{status} {landing.split("?")[0]}'
def nextcloud_admin(zone):
 status,_,page=request(gated(zone),f'https://files.{zone}.{settings.SUFFIX}/ocs/v2.php/cloud/user?format=json',headers={**basic('nextcloud',secret(zone,'nextcloud-admin-password','password')),'OCS-APIRequest':'true'})
 return status==200 and '"id":"nextcloud"' in page.replace(' ',''),f'{status} password accepted by the Nextcloud API'
def openproject_admin(zone):
 o=gated(zone);d=f'https://projects.{zone}.{settings.SUFFIX}'
 status,landing,page=request(o,d+'/login/internal')
 token=re.search(r'name="authenticity_token" value="([^"]+)"',page)
 if not token:return False,f'{status} no internal login form'
 status,landing,page=request(o,d+'/login',urllib.parse.urlencode({'authenticity_token':html.unescape(token.group(1)),'username':'admin','password':secret(zone,'openproject-admin-password','password')}).encode())
 return status==200 and '/login' not in landing,f'{status} {landing.split("?")[0]}'
def collabora_admin(zone):
 user,password=secret(zone,'collabora-admin-password','username'),secret(zone,'collabora-admin-password','password')
 # The Nextcloud container has curl, and it reaches the Collabora Service from inside the zone.
 command='for i in $(seq 300); do c=$(curl -s -o /dev/null -w "%{http_code}" -u "$U:$P" http://collabora:9980/browser/dist/admin/admin.html); case $c in 502|503|000) sleep 2;; *) echo $c; exit;; esac; done; echo $c'
 out=in_pod(zone,'deploy/opendesk-nextcloud-aio','aio',command,{'U':user,'P':password})
 return out.stdout.strip()=='200',f'{out.stdout.strip() or out.stderr[-120:]} from inside the zone'
def ldap_admin(zone):
 out=in_pod(zone,'ums-ldap-server-primary-0','main','ldapwhoami -x -H ldap://localhost:389 -D cn=admin,dc=swp-ldap,dc=internal -w "$P"',{'P':secret(zone,'ums-ldap-server-admin','password')})
 return out.returncode==0,(out.stdout or out.stderr).strip()[:120]
args=sys.argv[1:];platform='--no-platform' not in args;args=[a for a in args if a!='--no-platform']
if platform:
 check('operator portal',operator)
 check('Grafana local admin',grafana)
FIXTURE=json.loads((root.parent/'zones/zone-users.json').read_text())['users']
PASSWORDS=json.loads((settings.PRIVATE/'fixture-user-passwords.json').read_text())
for zone in args or list(zonestate.load()['zones']):
 d=f'{zone}.{settings.SUFFIX}'
 users=[('Administrator',secret(zone,'ums-nubus-credentials','administrator_password'))]
 test_user=settings.PRIVATE/f'zones/{zone}/test-user-password'
 if test_user.exists():users.append(('test.user',test_user.read_text().strip()))
 users+=[(e['username'],PASSWORDS[e['username']]) for e in FIXTURE]
 for user,password in users:
  for app,url,host in [('portal',f'https://portal.{d}/univention/oidc/?location=/univention/portal/',f'portal.{d}'),
   ('files',f'https://files.{d}/login',f'files.{d}'),('projects',f'https://projects.{d}/login',f'projects.{d}'),
   ('wiki',f'https://wiki.{d}/bin/view/Main/',f'wiki.{d}'),('notes',f'https://notes.{d}/api/v1.0/authenticate/',f'notes.{d}'),
   ('chat',f'https://mas.{d}/login',f'mas.{d}')]:
   check(f'{zone} {user} {app}',application(zone,user,password,url,host))
 check(f'{zone} Keycloak admin console',lambda:keycloak_admin(zone))
 check(f'{zone} Nextcloud internal admin',lambda:nextcloud_admin(zone))
 check(f'{zone} OpenProject internal admin',lambda:openproject_admin(zone))
 check(f'{zone} Collabora admin console',lambda:collabora_admin(zone))
 check(f'{zone} LDAP admin',lambda:ldap_admin(zone))
print(f'{sum(results)} of {len(results)} logins passed')
sys.exit(0 if all(results) else 1)
