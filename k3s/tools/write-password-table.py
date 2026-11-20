#!/usr/bin/env python3
"""Print every deployment login and password of the site in clear text, as a Markdown table. Usage:
  write-password-table.py                 print the table of this site
  write-password-table.py --print <label> print the logins as one marked block with the heading <label>

The table is a view: nothing stores it. The values come from the secret store (../secretstore.py) and from the live
cluster Secrets, so the table shows the values that the services use. Redirect the output to a private file when a
person needs a copy, and keep that file out of Git.
The zone users of ../zones/zone-users.json have their passwords in the path site/zone-users of the store.
"""
import base64,json,pathlib,subprocess,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import secretstore,settings
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'zones'));import zonestate
root=pathlib.Path(__file__).resolve().parent;settings.use_kubeconfig()
# A site without zones yet has no zone state file.
ZONES=list(zonestate.load()['zones']) if zonestate.PATH.exists() else []
def secret(namespace,name):
 try:item=json.loads(subprocess.check_output(['kubectl','-n',namespace,'get','secret',name,'-o','json'],text=True,stderr=subprocess.DEVNULL))
 except subprocess.CalledProcessError:return None
 return {k:base64.b64decode(v).decode() for k,v in item.get('data',{}).items()}
def value(namespace,name,key):
 data=secret(namespace,name);return data.get(key,'(missing key)') if data else '(missing Secret)'
operator_password=secretstore.read('site/operator-login').get('admin-password','(missing)').strip()
rows=[('Operator portal','https://operator.'+settings.SUFFIX+'/','admin',operator_password,'One login opens every operator tool.')]
grafana=secret('monitoring','monitor-grafana') or {}
rows.append(('Grafana local admin','https://operator.'+settings.SUFFIX+'/grafana/',grafana.get('admin-user','(missing)'),grafana.get('admin-password','(missing)'),'The operator portal login is enough.'))
for zone in ZONES:
 if secret(zone,'ums-nubus-credentials') is None:continue
 rows+=[(f'{zone} portal and applications',f'https://{zone}-portal.{settings.SUFFIX}/','Administrator',value(zone,'ums-nubus-credentials','administrator_password'),'Domain admin, and admin in Files and Wiki. zone-users.py sets the application flags.')]
 test_user=secretstore.read(secretstore.zone_path(zone,'test-user')).get('password')
 if test_user:rows.append((f'{zone} portal and applications',f'https://{zone}-portal.{settings.SUFFIX}/','test.user',test_user,'Normal user in every in-scope application.'))
 rows+=[(f'{zone} Keycloak admin console',f'https://{zone}-id.{settings.SUFFIX}/admin/master/console/','kcadmin',value(zone,'keycloak-admin-password','adminPassword'),'The console signs in to `master`. The zone users are in `opendesk`.'),
  (f'{zone} Nextcloud internal admin',f'https://{zone}-files.{settings.SUFFIX}/login?direct=1','nextcloud',value(zone,'nextcloud-admin-password','password'),'The direct login skips Keycloak.'),
  (f'{zone} Collabora admin console',f'http://collabora.{zone}.svc:9980/browser/dist/admin/admin.html',value(zone,'collabora-admin-password','username'),value(zone,'collabora-admin-password','password'),'In the cluster only. openDesk blocks this page at the ingress.'),
  (f'{zone} LDAP admin',f'ldap://ums-ldap-server-primary.{zone}.svc:389','cn=admin,dc=swp-ldap,dc=internal',value(zone,'ums-ldap-server-admin','password'),'In the cluster only.'),
  (f'{zone} openDesk master password','-','-',secretstore.read(secretstore.zone_path(zone)).get('master_password','(missing)'),'It generates the zone secrets. It is not a login.')]
 # A zone of an earlier version runs PostgreSQL in its namespace. The openDesk chart gives the superuser password to
 # the container environment. A zone on the shared PostgreSQL has no such server (../zones/postgresql.py).
 try:
  env=json.loads(subprocess.check_output(['kubectl','-n',zone,'get','statefulset','postgresql','-o','json'],text=True,stderr=subprocess.DEVNULL))['spec']['template']['spec']['containers'][0]['env']
  pg=next((e.get('value','(from a Secret)') for e in env if e['name']=='POSTGRES_PASSWORD'),'(missing)')
  rows.append((f'{zone} PostgreSQL superuser',f'postgresql.{zone}.svc:5432','postgres',pg,'In the cluster only.'))
 except subprocess.CalledProcessError:pass
 stores=secret(zone,'hoover-stores')
 if stores:
  rows+=[(f'{zone} Hoover ClickHouse zone user','clickhouse.hoover-stores.svc:8123',zone.replace('-','_'),stores.get('clickhouse-zone','(missing)'),'In the cluster only. It reaches only the databases of the zone.'),
   (f'{zone} Hoover Manticore read user','manticore.hoover-stores.svc:9309 and manticore-vectors',zone.replace('-','_')+'_read',stores.get('manticore-read','(missing)'),'In the cluster only. It reads only the tables of the zone.')]
# The shared stores of the site (../hoover/stores/shared.py).
shared=secret('hoover-stores','hoover-stores')
if shared:
 rows+=[('Shared ClickHouse admin','clickhouse.hoover-stores.svc:8123','hoover_admin',shared.get('clickhouse-admin','(missing)'),'In the cluster only. It reaches every zone.'),
  ('Shared Manticore admin','manticore.hoover-stores.svc:9306 and manticore-vectors','hoover_admin',shared.get('manticore-admin','(missing)'),'In the cluster only. It reaches every zone.'),
  ('Shared Garage admin API','garage-0.garage-peers.hoover-stores.svc:3903','-',shared.get('garage-admin-token','(missing)'),'A bearer token. Only the store pods reach the port.'),
  ('Shared PostgreSQL admin','postgresql.hoover-stores.svc:5432','postgres',shared.get('postgresql-admin','(missing)'),'In the cluster only. Only the openDesk namespaces of the site zones reach the port.')]
fixture=json.loads((root.parent/'zones/zone-users.json').read_text())['users']
passwords=secretstore.read('site/zone-users')
if '--print' in sys.argv:
 # Print the logins of this host as one marked block, for the private notes of the person.
 label=sys.argv[sys.argv.index('--print')+1]
 rows+=[(f'{zone} portal and applications',f'https://{zone}-portal.{settings.SUFFIX}/',e['username'],passwords.get(e['username'],'(not created yet)'),'Zone user from zone-users.json.')
  for zone in ZONES if secret(zone,'ums-nubus-credentials') is not None for e in fixture]
 # The person-facing logins come first: the zone portal Administrator, the operator portal, then the zone users.
 def priority(row):
  if row[2]=='Administrator':return 0
  if row[0]=='Operator portal':return 1
  if row[0].endswith('portal and applications'):return 2
  return 3
 rows.sort(key=priority)
 block=[f'<!-- {label} passwords begin: write-password-table.py --print writes this block -->','',f'## {label} logins and passwords','',
  f'These values are in clear text. They come from the secret store and the live Secrets of {label}. Run `write-password-table.py --print {label}` on {label} to print them again.','',
  '| Login | Address | User | Password | Note |','|---|---|---|---|---|',*[f'| {a} | {b} | `{c}` | `{d}` | {e} |' for a,b,c,d,e in rows],'',f'<!-- {label} passwords end -->']
 print('\n'.join(block));sys.exit()
table=['# Logins and passwords','','These values are in clear text. Run `k3s/tools/write-password-table.py` to print them again.',
 'Run `k3s/tools/verify-lab-logins.py` to check every login.',
 'The XWiki superadmin is off, because openDesk turns it on only in debug mode. Administrator is an XWiki admin.','',
 '## Zone users','',
 'Each user is a normal user with every application, Hoover included, in every zone that `zone-users.py` prepares.',
 'A user has the same password in every zone and on every host.','',
 '| User | Password |','|---|---|',*[f"| `{e['username']}` | `{passwords.get(e['username'],'(not created yet)')}` |" for e in fixture],'',
 '## Deployment logins and passwords','',
 '| Login | Address | User | Password | Note |','|---|---|---|---|---|',*[f'| {a} | {b} | `{c}` | `{d}` | {e} |' for a,b,c,d,e in rows]]
print('\n'.join(table))
