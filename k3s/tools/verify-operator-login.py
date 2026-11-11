#!/usr/bin/env python3
"""Sign in once through the operator gateway and verify access to every portal tool."""
import http.cookiejar,json,pathlib,re,ssl,sys,urllib.error,urllib.parse,urllib.request
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
BASE='https://operator.'+settings.SUFFIX
# A host with its own operator password keeps it in this file. Without it the check uses the development password admin.
PASSWORD_FILE=settings.PRIVATE/'operator-login/admin-password'
PASSWORD=PASSWORD_FILE.read_text().strip() if PASSWORD_FILE.exists() else 'admin'
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args):return None
# The local CA file signs the local frontend. A public certificate needs the system store, which the default context reads.
CA=ssl.create_default_context()
if (settings.PRIVATE/'frontend/local-ca.crt').exists():CA.load_verify_locations(cafile=str(settings.PRIVATE/'frontend/local-ca.crt'))
def opener(jar,follow=True):
 handlers=[urllib.request.HTTPCookieProcessor(jar),urllib.request.HTTPSHandler(context=CA)]+([] if follow else [NoRedirect])
 return urllib.request.build_opener(*handlers)
def get(o,path,headers={}):
 try:
  with o.open(urllib.request.Request(BASE+path,headers=headers),timeout=20) as r:return r.status,r.geturl(),r.read().decode(errors='replace')
 except urllib.error.HTTPError as e:return e.code,e.headers.get('Location',''),e.read().decode(errors='replace')
def get_json(o,path,headers={}):
 status,_,body=get(o,path,headers);assert status==200,(path,status);return json.loads(body)
def sign_in():
 """Return a cookie opener after the login admin with PASSWORD."""
 browser=opener(http.cookiejar.CookieJar())
 status,url,page=get(browser,'/')
 assert '/dex/auth/local' in url,url
 action=urllib.parse.urljoin(url,re.search(r'<form[^>]*action="([^"]+)"',page).group(1).replace('&amp;','&'))
 data=urllib.parse.urlencode({'login':'admin','password':PASSWORD}).encode()
 with browser.open(urllib.request.Request(action,data=data),timeout=20) as r:landing=r.geturl();page=r.read().decode()
 assert landing==BASE+'/' and 'Hoover cluster operations' in page,landing
 return browser
def main():
 results={}
 anonymous=opener(http.cookiejar.CookieJar(),follow=False)
 for path in ['/','/grafana/api/user','/prometheus/api/v1/targets','/headlamp/','/status.json']:
  status,_,_=get(anonymous,path)
  results['anonymous '+path]=status
  assert status in (302,401,403),(path,status)
 browser=sign_in()
 results['status.json']=get_json(browser,'/status.json')
 # The gateway replaces a client user header with the signed-in user.
 user=get_json(browser,'/grafana/api/user',{'X-Forwarded-User':'forged'})
 results['grafana user']={k:user.get(k) for k in ('login','isGrafanaAdmin')};assert user['login']=='admin',user
 targets=get_json(browser,'/prometheus/api/v1/targets')['data']['activeTargets']
 results['prometheus targets up']=[sum(t['health']=='up' for t in targets),len(targets)]
 deployments=get_json(browser,'/headlamp/clusters/main/apis/apps/v1/namespaces/kube-system/deployments')
 results['headlamp deployments']=sorted(d['metadata']['name'] for d in deployments['items'])
 status,_,_=get(browser,'/headlamp/clusters/main/api/v1/namespaces/monitoring/secrets')
 results['headlamp secret list status']=status;assert status==403
 print(json.dumps(results,indent=1))
if __name__=='__main__':main()
