#!/usr/bin/env python3
"""Sign in to each zone portal through Keycloak as Administrator and report which password source works.

Usage: verify-zone-admin.py [zone]...  The script prints no password.
"""
import base64,html,http.cookiejar,json,os,pathlib,re,ssl,subprocess,sys,urllib.error,urllib.parse,urllib.request
root=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(root.parent));import settings
settings.use_kubeconfig()
CA=ssl.create_default_context(cafile=str(settings.PRIVATE/'frontend/local-ca.crt'))
def secret(zone,name,key):
 data=json.loads(subprocess.check_output(['kubectl','-n',zone,'get','secret',name,'-o','json'],text=True))['data']
 return base64.b64decode(data[key]).decode()
def sign_in(zone,user,password):
 """Return the landing address after the portal OIDC login, or the Keycloak error text."""
 browser=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),urllib.request.HTTPSHandler(context=CA))
 with browser.open(f'https://portal.{zone}.{settings.SUFFIX}/univention/oidc/?location=/univention/portal/',timeout=60) as r:page=r.read().decode()
 action=html.unescape(re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"',page,re.S).group(1))
 data=urllib.parse.urlencode({'username':user,'password':password,'credentialId':''}).encode()
 try:
  with browser.open(urllib.request.Request(action,data=data),timeout=60) as r:landing=r.geturl();page=r.read().decode(errors='replace')
 except urllib.error.HTTPError as e:return False,f'HTTP {e.code} {e.geturl()}'
 error=re.search(r'id="input-error"[^>]*>\s*([^<]+)',page)
 if error:return False,error.group(1).strip()
 return landing.startswith(f'https://portal.{zone}.{settings.SUFFIX}/univention/'),landing.split('?')[0]
results={}
for zone in sys.argv[1:] or ['zone-a','zone-b']:
 candidates={'master-password file':(settings.PRIVATE/f'zones/{zone}/master-password').read_text().strip(),
  'ums-nubus-credentials administrator_password':secret(zone,'ums-nubus-credentials','administrator_password')}
 for source,password in candidates.items():
  results[f'{zone} {source}']=sign_in(zone,'Administrator',password)
  print(zone,source,*results[f'{zone} {source}'],flush=True)
(root/'evidence/zone-admin-login.json').write_text(json.dumps(results,indent=1))
