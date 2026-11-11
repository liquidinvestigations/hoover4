#!/usr/bin/env python3
"""Give the users of each zone access to every in-scope application. Usage: zone-users.py [--refresh] [zone ...]

The openDesk bootstrap creates Administrator with every application flag off, so the applications reject its login.
The script turns on each application flag and each application admin flag of Administrator.
It creates test.user with the application flags and without admin flags when the user is missing.
It creates each user of zone-users.json in the same way. A user has the same password in every zone and on
every host, from k3s/private/fixture-user-passwords.json. The script makes a password for a user that has none in the file.
For an existing test.user it turns on the application flags that are off. --refresh turns the test.user flags off
and on again, so Nubus computes the group membership again.
The test.user password is in k3s/private/zones/<zone>/test-user-password. The script prints no password.
A user whose stored password the Nubus password check refuses stops the script, because that password is the login.
Each UDM request runs in the UDM REST API container through kubectl exec (udm.py). Without zones it covers every zone of the zone state.
"""
import json,pathlib,secrets,string,sys,urllib.parse
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
lab=pathlib.Path(__file__).resolve().parent;settings.use_kubeconfig()
sys.path.insert(0,str(lab));import udm
BASE='dc=swp-ldap,dc=internal'
# Jitsi admits members of managed-by-attribute-Videoconference, which opendeskVideoconferenceEnabled sets.
APPS=['Fileshare','Projectmanagement','Knowledgemanagement','Livecollaboration','Notes','Videoconference']
ENABLED={f'opendesk{a}Enabled':True for a in APPS}
ADMIN={f'opendesk{a}Admin':True for a in ['Fileshare','Projectmanagement','Knowledgemanagement','Livecollaboration']}
def password():
 # The Nubus password policy needs letters, digits and a minimum length.
 alphabet=string.ascii_letters+string.digits
 while True:
  value=''.join(secrets.choice(alphabet) for _ in range(20))
  if any(c.isdigit() for c in value) and any(c.isupper() for c in value) and any(c.islower() for c in value):return value
def run(zone):
 call=udm.client(zone)
 try:
  def user(uid):return udm.user(call,uid)
  result={'zone':zone}
  item=user('Administrator')
  dn=urllib.parse.quote(item['dn'],safe='')
  if any(item['properties'].get(k)!=v for k,v in {**ENABLED,**ADMIN}.items()):
   _,headers,_=call('GET',f'users/user/{dn}')
   call('PATCH',f'users/user/{dn}',{'properties':{**ENABLED,**ADMIN}},{'If-Match':headers.get('Etag','*')})
   result['administrator']='application and admin flags set'
  else:result['administrator']='application and admin flags on'
  path=settings.PRIVATE/f'zones/{zone}/test-user-password'
  if user('test.user') is None:
   value=password()
   call('POST','users/user/',{'position':f'cn=users,{BASE}','properties':{'username':'test.user','firstname':'Test','lastname':'User',
    'password':value,'mailPrimaryAddress':f'test.user@{zone}.{settings.SUFFIX}',**ENABLED}})
   path.write_text(value+'\n');path.chmod(0o600);result['test.user']='created'
  else:
   # A user from an earlier run gets the application flags that were added since then.
   existing=user('test.user');dn=urllib.parse.quote(existing['dn'],safe='')
   if REFRESH:
    # Nubus adds a user to managed-by-attribute-<app> when the flag changes. A group that was created after the
    # flag was set therefore misses the user until the flag changes again.
    _,headers,_=call('GET',f'users/user/{dn}')
    call('PATCH',f'users/user/{dn}',{'properties':{k:False for k in ENABLED}},{'If-Match':headers.get('Etag','*')})
    existing=user('test.user')
   if any(existing['properties'].get(k)!=v for k,v in ENABLED.items()):
    _,headers,_=call('GET',f'users/user/{dn}')
    call('PATCH',f'users/user/{dn}',{'properties':ENABLED},{'If-Match':headers.get('Etag','*')})
   result['test.user']=('exists' if path.exists() else 'exists without a stored password')+', application flags on'
  for entry in FIXTURE:
   uid=entry['username'];found=user(uid)
   if found is None:
    # The stored password is the login of the user in every zone, so a refused password stops the script.
    call('POST','users/user/',{'position':f'cn=users,{BASE}','properties':{'username':uid,'firstname':entry['firstname'],
     'lastname':entry['lastname'],'password':PASSWORDS[uid],'mailPrimaryAddress':f'{uid}@{zone}.{settings.SUFFIX}',**ENABLED}})
    result[uid]='created'
   else:
    if any(found['properties'].get(k)!=v for k,v in ENABLED.items()):
     dn=urllib.parse.quote(found['dn'],safe='');_,headers,_=call('GET',f'users/user/{dn}')
     call('PATCH',f'users/user/{dn}',{'properties':ENABLED},{'If-Match':headers.get('Etag','*')})
    result[uid]='exists, application flags on'
  print(json.dumps(result))
 finally:pass
REFRESH='--refresh' in sys.argv
FIXTURE=json.loads((lab/'zone-users.json').read_text())['users']
PASSWORD_FILE=settings.PRIVATE/'fixture-user-passwords.json'
PASSWORDS=json.loads(PASSWORD_FILE.read_text()) if PASSWORD_FILE.exists() else {}
def save_passwords():PASSWORD_FILE.write_text(json.dumps(PASSWORDS,indent=1)+'\n');PASSWORD_FILE.chmod(0o600)
if any(e['username'] not in PASSWORDS for e in FIXTURE):
 PASSWORDS.update({e['username']:password() for e in FIXTURE if e['username'] not in PASSWORDS});save_passwords()
import zonestate
for zone in [a for a in sys.argv[1:] if not a.startswith('--')] or list(zonestate.load()['zones']):run(zone)
