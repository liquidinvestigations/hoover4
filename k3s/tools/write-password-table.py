#!/usr/bin/env python3
"""Write every deployment login and password in clear text into k3s/private/passwords.md, which Git ignores.

The hoover4 inventory keeps no credential values, so the table stays in the private folder of the site.

The script reads the live cluster Secrets, so the table shows the values that the services use.
It replaces the block between the two marker lines and prints only the row count.
Above that block it writes the users of ../zones/zone-users.json with their passwords from
k3s/private/fixture-user-passwords.json, which zone-users.py makes.
"""
import base64,json,os,pathlib,subprocess,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'zones'));import zonestate
root=pathlib.Path(__file__).resolve().parent;settings.use_kubeconfig()
INVENTORY=settings.PRIVATE/'passwords.md'
BEGIN='<!-- lab passwords begin: write-password-table.py writes this block -->';END='<!-- lab passwords end -->'
# A site without zones yet has no zone state file.
ZONES=list(zonestate.load()['zones']) if zonestate.PATH.exists() else []
def secret(namespace,name):
 try:item=json.loads(subprocess.check_output(['kubectl','-n',namespace,'get','secret',name,'-o','json'],text=True,stderr=subprocess.DEVNULL))
 except subprocess.CalledProcessError:return None
 return {k:base64.b64decode(v).decode() for k,v in item.get('data',{}).items()}
def value(namespace,name,key):
 data=secret(namespace,name);return data.get(key,'(missing key)') if data else '(missing Secret)'
operator_password=settings.PRIVATE/'operator-login/admin-password'
rows=[('Operator portal','https://operator.'+settings.SUFFIX+'/','admin',operator_password.read_text().strip() if operator_password.exists() else 'admin','One login opens every operator tool.')]
grafana=secret('monitoring','monitor-grafana') or {}
rows.append(('Grafana local admin','https://operator.'+settings.SUFFIX+'/grafana/',grafana.get('admin-user','(missing)'),grafana.get('admin-password','(missing)'),'The operator portal login is enough.'))
for zone in ZONES:
 if secret(zone,'ums-nubus-credentials') is None:continue
 d=f'{zone}.{settings.SUFFIX}'
 rows+=[(f'{zone} portal and applications',f'https://portal.{d}/','Administrator',value(zone,'ums-nubus-credentials','administrator_password'),'Domain admin, and admin in Files, Projects, Wiki and Chat. zone-users.py sets the application flags.')]
 test_user=settings.PRIVATE/f'zones/{zone}/test-user-password'
 if test_user.exists():rows.append((f'{zone} portal and applications',f'https://portal.{d}/','test.user',test_user.read_text().strip(),'Normal user in every in-scope application.'))
 rows+=[(f'{zone} Keycloak admin console',f'https://id.{d}/admin/master/console/','kcadmin',value(zone,'keycloak-admin-password','adminPassword'),'The console signs in to `master`. The zone users are in `opendesk`.'),
  (f'{zone} Nextcloud internal admin',f'https://files.{d}/login?direct=1','nextcloud',value(zone,'nextcloud-admin-password','password'),'The direct login skips Keycloak.'),
  (f'{zone} OpenProject internal admin',f'https://projects.{d}/login/internal','admin',value(zone,'openproject-admin-password','password'),'The internal login skips Keycloak.'),
  (f'{zone} Collabora admin console',f'http://collabora.{zone}.svc:9980/browser/dist/admin/admin.html',value(zone,'collabora-admin-password','username'),value(zone,'collabora-admin-password','password'),'In the cluster only. openDesk blocks this page at the ingress.'),
  (f'{zone} LDAP admin',f'ldap://ums-ldap-server-primary.{zone}.svc:389','cn=admin,dc=swp-ldap,dc=internal',value(zone,'ums-ldap-server-admin','password'),'In the cluster only.'),
  (f'{zone} openDesk master password','-','-',(settings.PRIVATE/f'zones/{zone}/master-password').read_text().strip(),'It generates the zone secrets. It is not a login.')]
 # The stores of a zone run in the zone namespace with their own credentials. The openDesk chart gives the
 # PostgreSQL superuser password to the container environment.
 try:
  env=json.loads(subprocess.check_output(['kubectl','-n',zone,'get','statefulset','postgresql','-o','json'],text=True,stderr=subprocess.DEVNULL))['spec']['template']['spec']['containers'][0]['env']
  pg=next((e.get('value','(from a Secret)') for e in env if e['name']=='POSTGRES_PASSWORD'),'(missing)')
 except subprocess.CalledProcessError:pg='(missing StatefulSet)'
 rows.append((f'{zone} PostgreSQL superuser',f'postgresql.{zone}.svc:5432','postgres',pg,'In the cluster only.'))
 stores=secret(zone,'hoover-stores')
 if stores:
  rows+=[(f'{zone} Hoover ClickHouse admin',f'clickhouse.{zone}.svc:8123','hoover_admin',stores.get('clickhouse-admin','(missing)'),'In the cluster only.'),
   (f'{zone} Hoover Manticore admin',f'manticore.{zone}.svc:9306 and manticore-vectors','hoover_admin',stores.get('manticore-admin','(missing)'),'In the cluster only.'),
   (f'{zone} Hoover Garage admin API',f'garage.{zone}.svc:3903','-',stores.get('garage-admin-token','(missing)'),'A bearer token, in the cluster only.')]
USERS_BEGIN='<!-- fixture users begin: write-password-table.py writes this block -->';USERS_END='<!-- fixture users end -->'
fixture=json.loads((root.parent/'zones/zone-users.json').read_text())['users']
password_file=settings.PRIVATE/'fixture-user-passwords.json'
passwords=json.loads(password_file.read_text()) if password_file.exists() else {}
def place(text,block,begin,end):
 """Replace the marked block in text, or put it below the title line when the text has no such block."""
 if begin in text:before,rest=text.split(begin,1);return before+'\n'.join(block)+rest.split(end,1)[1]
 title,body=text.split('\n',1);return title+'\n\n'+'\n'.join(block)+'\n'+body
if '--insert' in sys.argv:
 # Put a block that --print wrote on another host at the top of the local inventory.
 block=sys.stdin.read().strip('\n').split('\n');begin,end=block[0],block[-1]
 assert begin.startswith('<!-- ') and end.startswith('<!-- '),'the input is not a marked block'
 INVENTORY.write_text(place(INVENTORY.read_text(),block,begin,end));print(f'inserted {len(block)} lines');sys.exit()
if '--print' in sys.argv:
 # Print the logins of this host as one marked block. The local copy of the script inserts it with --insert.
 label=sys.argv[sys.argv.index('--print')+1]
 rows+=[(f'{zone} portal and applications',f'https://portal.{zone}.{settings.SUFFIX}/',e['username'],passwords.get(e['username'],'(not created yet)'),'Zone user from zone-users.json.')
  for zone in ZONES if secret(zone,'ums-nubus-credentials') is not None for e in fixture]
 # The person-facing logins come first: the zone portal Administrator, the operator portal, then the zone users.
 def priority(row):
  if row[2]=='Administrator':return 0
  if row[0]=='Operator portal':return 1
  if row[0].endswith('portal and applications'):return 2
  return 3
 rows.sort(key=priority)
 block=[f'<!-- {label} passwords begin: write-password-table.py --print writes this block -->','',f'## {label} logins and passwords','',
  f'These values are in clear text. They come from the live Secrets of {label}. Run `write-password-table.py --print {label}` on {label} and pipe the output to `write-password-table.py --insert` on the local host to write them again.','',
  '| Login | Address | User | Password | Note |','|---|---|---|---|---|',*[f'| {a} | {b} | `{c}` | `{d}` | {e} |' for a,b,c,d,e in rows],'',f'<!-- {label} passwords end -->']
 print('\n'.join(block));sys.exit()
table=[BEGIN,'','## Deployment logins and passwords','',
 'These values are in clear text. Run `k3s/tools/write-password-table.py` to write them again.',
 'Run `k3s/tools/verify-lab-logins.py` to check every login.',
 'The XWiki superadmin is off, because openDesk turns it on only in debug mode. Administrator is an XWiki admin.','',
 '| Login | Address | User | Password | Note |','|---|---|---|---|---|',*[f'| {a} | {b} | `{c}` | `{d}` | {e} |' for a,b,c,d,e in rows],'',END]
# A new site has no table yet. Its first run writes the title line.
text=place(INVENTORY.read_text() if INVENTORY.exists() else '# Logins and passwords\n',table,BEGIN,END)
users=[USERS_BEGIN,'','## Zone users','',
 'Each user is a normal user with every application, Hoover included, in every zone that `zone-users.py` prepares.',
 'A user has the same password in every zone and on every host. The hosts are in the sections below.','',
 '| User | Password |','|---|---|',*[f"| `{e['username']}` | `{passwords.get(e['username'],'(not created yet)')}` |" for e in fixture],'',USERS_END]
text=place(text,users,USERS_BEGIN,USERS_END)
INVENTORY.write_text(text);INVENTORY.chmod(0o600);print(f'wrote {len(rows)} logins and {len(fixture)} zone users')
