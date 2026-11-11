#!/usr/bin/env python3
"""Check that new rooms are encrypted, except the rooms of the meetings bot. Usage: e2ee-check.py [zone]

MAS issues a short device token for test.user. The script creates a private room and a public room as test.user,
and one room with the meetings bot token. It reads the m.room.encryption state of each room, then leaves and
forgets the rooms and logs the test.user device out. The script prints no token.
"""
import base64,json,os,pathlib,re,subprocess,sys,urllib.error,urllib.request
lab=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
OUT=settings.PRIVATE/'checks';OUT.mkdir(parents=True,exist_ok=True)
settings.use_kubeconfig()
zone=sys.argv[1] if len(sys.argv)>1 else 'zone-a';base=f'https://matrix.{zone}.{settings.SUFFIX}/_matrix/client/v3'
def kubectl(*args):
 # mas-cli writes its result to the log on standard error, so the function returns both streams.
 r=subprocess.run(['kubectl','-n',zone,*args],check=True,capture_output=True,text=True);return r.stdout+r.stderr
def call(token,method,path,body=None):
 request=urllib.request.Request(base+path,method=method,data=json.dumps(body).encode() if body is not None else None,
  headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(request,timeout=60) as r:return json.loads(r.read() or b'{}')
 except urllib.error.HTTPError as error:
  if error.code==404:return None
  raise
out=kubectl('exec','deploy/element-matrix-authentication-service','-c','matrix-authentication-service','--','mas-cli','manage','issue-compatibility-token','test.user','HOOVERE2EECHECK')
user_token=re.search(r'(mct_\S+)',out).group(1)
bot_token=base64.b64decode(json.loads(subprocess.check_output(['kubectl','-n',zone,'get','secret','matrix-neodatefix-bot-account','-o','json'],text=True))['data']['access_token']).decode()
result={'zone':zone}
for name,token,body in [('private room',user_token,{'name':'E2EE check private','preset':'private_chat'}),
  ('public room',user_token,{'name':'E2EE check public','preset':'public_chat'}),
  ('bot room',bot_token,{'name':'E2EE check bot','preset':'private_chat'})]:
 room=call(token,'POST','/createRoom',body)['room_id']
 state=call(token,'GET',f'/rooms/{room}/state/m.room.encryption/')
 result[name]=state.get('algorithm') if state else None
 call(token,'POST',f'/rooms/{room}/leave',{});call(token,'POST',f'/rooms/{room}/forget',{})
call(user_token,'POST','/logout',{})
result['passed']=bool(result['private room'] and result['public room']) and result['bot room'] is None
print(json.dumps(result))
(OUT/f'e2ee-check-{zone}.json').write_text(json.dumps(result,indent=1)+'\n')
