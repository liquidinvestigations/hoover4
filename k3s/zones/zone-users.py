#!/usr/bin/env python3
"""Give the users of each zone access to every in-scope application. Usage: zone-users.py [--refresh] [zone ...]

The openDesk bootstrap creates Administrator with every application flag off, so the applications reject its login.
The script turns on each application flag and each application admin flag of Administrator.
It creates test.user with the application flags and without admin flags when the user is missing.
It creates each user of zone-users.json in the same way. A user has the same password in every zone and on
every host, from the path site/zone-users of the secret store (../secretstore.py). The step secret-store of
deploy-k3s up makes a password for a user that has none, because a zone step only reads the path. The script writes a
copy into <state folder>/zones/fixture-user-passwords.json.
For an existing test.user it turns on the application flags that are off. --refresh turns the test.user flags off
and on again, so Nubus computes the group membership again.
The test.user password is the path zones/<zone>/test-user of the store, with a copy in
<state folder>/zones/<zone>/test-user-password. A new test.user gets the stored password, else a new one. The script
prints no password.
A user whose stored password the Nubus password check refuses stops the script, because that password is the login.
Each UDM request runs in the UDM REST API container through kubectl exec (udm.py). Without zones it covers every zone of the zone state.
"""
import json,os,pathlib,secrets,string,sys,urllib.parse
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import secretstore,settings
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
   value=secretstore.keep(secretstore.zone_path(zone,'test-user'),{'password':password})['password']
   call('POST','users/user/',{'position':f'cn=users,{BASE}','properties':{'username':'test.user','firstname':'Test','lastname':'User',
    'password':value,'mailPrimaryAddress':f'test.user@{settings.zone_domain(zone)}',**ENABLED}})
   write_copy(path,value+'\n');result['test.user']='created'
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
   stored=secretstore.read(secretstore.zone_path(zone,'test-user')).get('password')
   if stored:write_copy(path,stored+'\n')
   result['test.user']=('exists' if stored else 'exists without a stored password')+', application flags on'
  for entry in FIXTURE:
   uid=entry['username'];found=user(uid)
   if found is None:
    # The stored password is the login of the user in every zone, so a refused password stops the script.
    call('POST','users/user/',{'position':f'cn=users,{BASE}','properties':{'username':uid,'firstname':entry['firstname'],
     'lastname':entry['lastname'],'password':PASSWORDS[uid],'mailPrimaryAddress':f'{uid}@{settings.zone_domain(zone)}',**ENABLED}})
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
def write_copy(path,text):
 """Write a copy of a stored password into the state folder, through a renamed temporary file."""
 path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 if path.exists() and path.read_text()==text:return
 tmp=path.with_name(f'.{path.name}.{os.getpid()}.tmp')
 with open(os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),'w') as f:f.write(text)
 os.replace(tmp,path)
STORED=secretstore.read('site/zone-users')
missing=[e['username'] for e in FIXTURE if e['username'] not in STORED]
if missing:raise SystemExit(f'the secret store has no password of {", ".join(missing)}. Run deploy-k3s up --steps secret-store.')
# The order of zone-users.json, as in the copies of earlier versions.
PASSWORDS={e['username']:STORED[e['username']] for e in FIXTURE}
write_copy(settings.ZONE_USER_PASSWORDS,json.dumps({**PASSWORDS,**{k:v for k,v in STORED.items() if k not in PASSWORDS}},indent=1)+'\n')
import zonestate
for zone in [a for a in sys.argv[1:] if not a.startswith('--')] or list(zonestate.load()['zones']):run(zone)
