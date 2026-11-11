#!/usr/bin/env python3
"""Check a short audio call in one zone with Jitsi and with MatrixRTC. Usage: call-check.py <zone> [jitsi] [matrixrtc] [turn] [matrixrtc-relay]

The browser uses Chrome fake media devices, so no microphone is needed. The check passes when each stack reports
the call. It does not judge the audio.
- Jitsi: the browser signs in through the portal as test.user and joins a meeting. The script then reads the
  conference count from the zone Jicofo and from the shared JVB.
- MatrixRTC: MAS issues a device token for test.user. The script creates an encrypted room, asks Synapse for an
  OpenID token and asks the zone lk-jwt for a LiveKit token. The browser joins the shared LiveKit and publishes the
  fake microphone. The script reads the room list of LiveKit and the ICE candidate type. At the end it leaves the
  room and logs the device out.
- TURN: Chrome gathers relay candidates from coturn with a credential for the LiveKit TURN secret.
- matrixrtc-relay: the same join with relay-only ICE, so the media path goes through coturn. The LiveKit client creates
  its peer connection before the join response brings the TURN entry, so the check passes the TURN entry itself.
LAB_SUFFIX, LAB_KUBECONFIG, LAB_USER and LAB_PASSWORD_FILE check another host or user. JITSI_SECOND_USER and
JITSI_SECOND_PASSWORD_FILE let a second user join the Jitsi call from a second browser. Without them the second
participant is a second tab of the first user. JITSI_HOLD=<seconds> keeps both
Jitsi participants in the call and records every 10 s whether each tab keeps its media session, its ICE state, and the
local candidate type. A session that the client starts again, as after an ICE failure, fails the check. JITSI_P2P=1
keeps peer-to-peer on, as in a normal call of two people. Without it, the call uses the bridge.
The script writes k3s/private/checks/call-check-<zone>.json, or call-check-<zone>-<LAB_SUFFIX>.json for another
host, and prints no token or password.
Run it with the browser Python environment in k3s/private/browser-venv, which has nodriver.
"""
import asyncio,base64,hashlib,hmac,json,os,pathlib,re,subprocess,sys,time,urllib.error,urllib.request
root=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
OUT=settings.PRIVATE/'checks';OUT.mkdir(parents=True,exist_ok=True)
os.environ['KUBECONFIG']=os.environ.get('LAB_KUBECONFIG',settings.KUBECONFIG)
sys.path.insert(0,str(settings.HOOVER4/'website/tools'))
from browser_lifecycle import start_browser,stop_browser
zone=sys.argv[1];parts=sys.argv[2:] or ['jitsi','matrixrtc','turn','matrixrtc-relay'];d=f"{zone}.{os.environ.get('LAB_SUFFIX',settings.SUFFIX)}"
USER=os.environ.get('LAB_USER','test.user')
PASSWORD_FILE=pathlib.Path(os.environ.get('LAB_PASSWORD_FILE',settings.PRIVATE/f'zones/{zone}/test-user-password'))
HOLD=int(os.environ.get('JITSI_HOLD','0'));P2P='true' if os.environ.get('JITSI_P2P')=='1' else 'false'
secrets=json.loads((settings.PRIVATE/'zones/secrets.json').read_text())
def kubectl(*args):
 r=subprocess.run(['kubectl',*args],check=True,capture_output=True,text=True);return r.stdout+r.stderr
def http(method,url,body=None,token=None):
 headers={'Content-Type':'application/json'}
 if token:headers['Authorization']='Bearer '+token
 request=urllib.request.Request(url,method=method,data=json.dumps(body).encode() if body is not None else None,headers=headers)
 with urllib.request.urlopen(request,timeout=60) as r:return json.loads(r.read() or b'{}')
def livekit_rooms():
 # Each zone key of LiveKit may list the rooms.
 key=secrets[zone]['livekit_secret']
 def part(v):return base64.urlsafe_b64encode(json.dumps(v,separators=(',',':')).encode()).rstrip(b'=')
 now=int(time.time());head=part({'alg':'HS256','typ':'JWT'})+b'.'+part({'iss':zone,'nbf':now-5,'exp':now+60,'video':{'roomList':True}})
 token=(head+b'.'+base64.urlsafe_b64encode(hmac.new(key.encode(),head,hashlib.sha256).digest()).rstrip(b'=')).decode()
 out=kubectl('-n','calls','exec','deploy/livekit','--','wget','-qO-','--header','Content-Type: application/json',
  '--header',f'Authorization: Bearer {token}','--post-data','{}','http://127.0.0.1:7880/twirp/livekit.RoomService/ListRooms')
 return [{'participants':r.get('num_participants',0)} for r in json.loads(out[out.index('{'):]).get('rooms',[])]
def jitsi_stats():
 pod=json.loads(kubectl('-n',zone,'get','pods','-l','app.kubernetes.io/component=jicofo','-o','json'))['items'][0]['metadata']['name']
 jicofo=json.loads(kubectl('-n',zone,'exec',pod,'--','curl','-s','http://127.0.0.1:8888/stats'))
 jvb=json.loads(kubectl('-n','calls','exec','deploy/jvb','--','curl','-s','http://127.0.0.1:8080/colibri/stats'))
 return {'jicofo_conferences':jicofo.get('conferences'),'jicofo_participants':jicofo.get('participants'),
  'jicofo_bridges':(jicofo.get('bridge_selector') or {}).get('operational_bridge_count'),
  'jvb_conferences':jvb.get('conferences'),'jvb_participants':jvb.get('participants')}
async def ev(tab,script,**kw):
 # nodriver returns an ExceptionDetails object for a script error, so the helper turns that into None.
 value=await tab.evaluate(script,**kw)
 if type(value).__name__=='ExceptionDetails':
  if os.environ.get('CALL_CHECK_DEBUG'):print('script error',str(value)[:400],file=sys.stderr)
  return None
 return value
SECOND_USER=os.environ.get('JITSI_SECOND_USER');SECOND_FILE=pathlib.Path(os.environ.get('JITSI_SECOND_PASSWORD_FILE','/nonexistent'))
async def sign_in(browser,user=USER,password_file=PASSWORD_FILE):
 password=password_file.read_text().strip()
 tab=await browser.get(f'https://portal.{d}/univention/oidc/?location=/univention/portal/');await asyncio.sleep(4)
 await (await tab.select('input[name="username"]',timeout=20)).send_keys(user)
 await (await tab.select('input[name="password"]',timeout=10)).send_keys(password)
 await (await tab.select('#kc-login',timeout=10)).click();await asyncio.sleep(6)
 return tab
async def jitsi(browser,tab):
 room=f'hoovercheck{int(time.time())}'
 await tab.get(f'https://meet.{d}/{room}#config.prejoinConfig.enabled=false&config.startWithVideoMuted=true&config.p2p.enabled={P2P}')
 joined=None;start=time.monotonic();clicks=0;last_click=0.0;trail=[]
 for _ in range(60):
  await asyncio.sleep(2)
  here=((await ev(tab,'location.href')) or '').split('?')[0][:80]
  if not trail or trail[-1]!=here:trail.append(here)
  # A meeting starts only with a moderator. The Keycloak adapter signs the user in after a click on Log-in.
  # The Jitsi client of Keycloak asks for the password again, although the portal session exists.
  if await ev(tab,"location.hostname.startsWith('id.') && !!document.querySelector('input[name=password]')"):
   password=PASSWORD_FILE.read_text().strip()
   await (await tab.select('input[name="password"]',timeout=10)).send_keys(password)
   await (await tab.select('#kc-login',timeout=10)).click();continue
  if clicks<3 and time.monotonic()-last_click>10 and await ev(tab,'''(() => { const b = [...document.querySelectorAll('button, [role=button], a')]
    .find(e => (e.innerText || '').trim() === 'Log-in'); if (b) { b.click(); return true; } return false; })()'''):
   clicks+=1;last_click=time.monotonic();continue
  try:joined=await ev(tab,'typeof APP!=="undefined" && APP.conference && APP.conference.isJoined && APP.conference.isJoined()')
  except Exception:joined=None
  if joined:break
 result={'joined':bool(joined),'seconds':round(time.monotonic()-start,1),'url':(await ev(tab,'location.href')).split('#')[0][:120]}
 # A second participant in a new tab makes Jicofo use the bridge, so the shared JVB must report the conference.
 other=None
 if SECOND_USER:
  other=await start_browser(OUT/'browser-second.log',['--window-size=1400,900','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream'],timeout=45)
  second=await sign_in(other,SECOND_USER,SECOND_FILE)
  await second.get(f'https://meet.{d}/{room}#config.prejoinConfig.enabled=false&config.startWithVideoMuted=true&config.p2p.enabled={P2P}')
  result['second_user']=SECOND_USER
 else:
  second=await browser.get(f'https://meet.{d}/{room}#config.prejoinConfig.enabled=false&config.startWithVideoMuted=true&config.p2p.enabled={P2P}',new_tab=True)
 for _ in range(30):
  await asyncio.sleep(2)
  if await ev(second,'typeof APP!=="undefined" && APP.conference && APP.conference.isJoined && APP.conference.isJoined()'):break
 await asyncio.sleep(8)
 if not joined:result['trail']=trail;result['clicks']=clicks
 if not joined:result['page']=(await ev(tab,'document.body ? document.body.innerText.slice(0,300) : ""') or '')
 await asyncio.sleep(5)
 result.update(jitsi_stats())
 if HOLD:result['hold']=await jitsi_hold([tab,second])
 try:result['ice']=await ev(tab,'APP.conference.getConnectionState ? String(APP.conference.getConnectionState()) : ""')
 except Exception:pass
 if other:await stop_browser(other)
 else:await second.close()
 await tab.get('about:blank');await asyncio.sleep(3)
 result['passed']=result['joined'] and (result['jvb_conferences'] or 0)>=1 and (not HOLD or result['hold']['passed'])
 return result
# The media session of the tab: the peer-to-peer session when it is active, else the bridge session.
SESSION_STATE='''(async () => { const r = APP.conference._room; if (!r) return JSON.stringify({session: null});
 const p2p = r.isP2PActive && r.isP2PActive(); const s = p2p ? r.p2pJingleSession : r.jvbJingleSession;
 if (!s) return JSON.stringify({session: null});
 const key = p2p ? '__p2pSession' : '__jvbSession'; window[key] = window[key] || s;
 const pc = s.peerconnection && s.peerconnection.peerconnection; let local = null;
 if (pc) { const stats = await pc.getStats(); stats.forEach(x => { if (x.type === 'candidate-pair' && x.nominated && x.state === 'succeeded') {
   const c = stats.get(x.localCandidateId); if (c) local = c.candidateType; } }); }
 const jingle = r.xmpp && r.xmpp.connection && r.xmpp.connection.jingle;
 const servers = jingle ? ((p2p ? jingle.p2pIceConfig : jingle.jvbIceConfig) || {}).iceServers || [] : [];
 return JSON.stringify({session: p2p ? 'p2p' : 'jvb', same: window[key] === s, ice: pc ? pc.iceConnectionState : null, local: local,
  turn_udp: !!config.useTurnUdp, ice_servers: servers.map(x => String(x.urls))}); })()'''
async def jitsi_hold(tabs):
 samples=[];start=time.monotonic()
 while time.monotonic()-start<HOLD:
  row={'t':round(time.monotonic()-start)}
  for i,t in enumerate(tabs):
   value=await ev(t,SESSION_STATE,await_promise=True)
   row[f'tab{i}']=json.loads(value) if value else None
  samples.append(row);await asyncio.sleep(10)
 states=[r[k] for r in samples for k in r if k.startswith('tab')]
 ok=bool(states) and all(s and s.get('same') and s.get('ice') in ('connected','completed') for s in states)
 return {'seconds':HOLD,'passed':ok,'local_candidates':sorted({str(s.get('local')) for s in states if s}),
  'sessions':sorted({str(s.get('session')) for s in states if s}),'samples':samples}
async def matrixrtc(browser,tab,policy='relay'):
 out=kubectl('-n',zone,'exec','deploy/element-matrix-authentication-service','-c','matrix-authentication-service','--',
  'mas-cli','manage','issue-compatibility-token',USER,'HOOVERCALLCHECK')
 token=re.search(r'(mct_\S+)',out).group(1);base=f'https://matrix.{d}/_matrix/client/v3'
 user=http('GET',base+'/account/whoami',token=token)['user_id']
 room=http('POST',base+'/createRoom',{'name':'Call check','preset':'private_chat'},token)['room_id']
 result={}
 try:
  openid=http('POST',base+f'/user/{urllib.parse.quote(user)}/openid/request_token',{},token)
  grant=http('POST',f'https://mrtc.{d}/sfu/get',{'room':room,'openid_token':openid,'device_id':'HOOVERCALLCHECK'})
  result['sfu_url']=grant.get('url')
  # The LiveKit client creates its peer connection before the join response, which carries the TURN entry.
  # A relay-only connection then gathers nothing, so the relay test passes the TURN entry itself. The credential uses
  # the LiveKit TURN secret and the format that LiveKit uses for its clients.
  rtc={'iceTransportPolicy':policy}
  if policy=='relay':
   name=f"{int(time.time())+600}:call-check";secret=secrets['calls']['livekit_turn_secret']
   rtc['iceServers']=[{'urls':[f'turn:turn.{settings.SUFFIX}:3478?transport=udp'],'username':name,
    'credential':base64.b64encode(hmac.new(secret.encode(),name.encode(),hashlib.sha1).digest()).decode()}]
  await tab.get(f'https://sfu.{d}/')
  await ev(tab,'''new Promise((ok, fail) => { const s = document.createElement('script');
   s.src = 'https://cdn.jsdelivr.net/npm/livekit-client@2/dist/livekit-client.umd.js'; s.onload = ok; s.onerror = fail; document.head.appendChild(s); })''',await_promise=True)
  # Relay-only ICE makes the media path go through coturn.
  state=await ev(tab,'''(async () => { try {
   // The wrapper records the ICE servers of each peer connection, without the passwords.
   window.lkIce = []; const Native = window.RTCPeerConnection;
   window.RTCPeerConnection = function (config, ...rest) {
    window.lkIce.push(((config && config.iceServers) || []).map(s => ({urls: s.urls, user: !!s.username, credential: !!s.credential})));
    const pc = new Native(config, ...rest); (window.lkPcs = window.lkPcs || []).push(pc);
    window.lkEvents = window.lkEvents || [];
    pc.addEventListener('icecandidate', e => window.lkEvents.push(e.candidate ? 'local ' + e.candidate.candidate.split(' ').slice(4,8).join(' ') : 'gathering done'));
    pc.addEventListener('icecandidateerror', e => window.lkEvents.push('error ' + e.errorCode + ' ' + e.errorText));
    pc.addEventListener('iceconnectionstatechange', () => window.lkEvents.push('ice ' + pc.iceConnectionState));
    return pc; };
   window.RTCPeerConnection.prototype = Native.prototype;
   const room = new LivekitClient.Room(); window.lkLast = room;
   await room.connect(%s, %s, {rtcConfig: %s});
   await room.localParticipant.setMicrophoneEnabled(true);
   await new Promise(r => setTimeout(r, 5000));
   const pc = room.engine.pcManager && room.engine.pcManager.publisher && room.engine.pcManager.publisher.getConnectedAddress ? await room.engine.pcManager.publisher.getConnectedAddress() : '';
   const stats = await room.engine.pcManager.publisher._pc.getStats();
   let candidate = '';
   stats.forEach(s => { if (s.type === 'candidate-pair' && s.state === 'succeeded' && s.nominated) {
     const local = stats.get(s.localCandidateId); candidate = local ? local.candidateType : ''; } });
   window.lkRoom = room;
   return JSON.stringify({state: room.state, candidate, address: String(pc), ice: window.lkIce});
  } catch (e) {
   // The ICE servers that LiveKit sent show whether the TURN entry reached the browser. The password is left out.
   let ice = [];
   ice = window.lkIce;
   // The candidate pairs of each peer connection show where the relay path stops.
   const pairs = [];
   for (const pc of window.lkPcs || []) { try { const stats = await pc.getStats(); stats.forEach(s => { if (s.type === 'candidate-pair') {
     const l = stats.get(s.localCandidateId), r = stats.get(s.remoteCandidateId);
     pairs.push([s.state, l && l.candidateType, l && l.address, r && r.candidateType, r && (r.address + ':' + r.port), r && r.protocol].join(' ')); } });
     pairs.push('config ' + JSON.stringify((pc.getConfiguration().iceServers || []).map(x => x.urls))); } catch (x) { pairs.push(String(x)); } }
   return JSON.stringify({error: String(e), ice, pairs, events: (window.lkEvents || []).slice(0, 30)});
  } })()'''%(json.dumps(grant['url']),json.dumps(grant['jwt']),json.dumps(rtc)),await_promise=True)
  result.update(json.loads(state))
  result['livekit_rooms']=livekit_rooms()
  await ev(tab,'window.lkRoom.disconnect()',await_promise=True)
 finally:
  http('POST',base+f'/rooms/{room}/leave',{},token);http('POST',base+f'/rooms/{room}/forget',{},token);http('POST',base+'/logout',{},token)
 result['policy']=policy
 result['passed']=result.get('state')=='connected' and (policy!='relay' or result.get('candidate')=='relay') and any(r['participants']>=1 for r in result.get('livekit_rooms',[]))
 return result
async def turn(tab):
 # Chrome gathers relay candidates from coturn with a credential for the LiveKit TURN secret.
 name=f"{int(time.time())+600}:call-check";secret=secrets['calls']['livekit_turn_secret']
 credential=base64.b64encode(hmac.new(secret.encode(),name.encode(),hashlib.sha1).digest()).decode()
 await tab.get(f'https://sfu.{d}/')
 found=json.loads(await ev(tab,'''(async () => { try { const pc = new RTCPeerConnection({iceTransportPolicy: 'relay',
   iceServers: [{urls: %s, username: %s, credential: %s}]});
  const found = []; pc.onicecandidate = e => { if (e.candidate) found.push(e.candidate.candidate.split(' ').slice(4,8).join(' ')); };
  pc.onicecandidateerror = e => found.push('error ' + e.errorCode + ' ' + e.errorText + ' ' + e.url);
  pc.createDataChannel('check'); await pc.setLocalDescription(await pc.createOffer());
  await new Promise(r => setTimeout(r, 8000)); pc.close(); return JSON.stringify(found); } catch (e) { return JSON.stringify(['error ' + String(e)]); } })()'''%(json.dumps(f'turn:turn.{settings.SUFFIX}:3478?transport=udp'),json.dumps(name),json.dumps(credential)),await_promise=True) or '[]')
 return {'relay_candidates':found,'passed':any('typ relay' in c for c in found)}
async def main():
 browser=await start_browser(OUT/'browser.log',['--window-size=1400,900','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream'],timeout=45)
 results={'zone':zone}
 try:
  tab=await sign_in(browser)
  if 'jitsi' in parts:results['jitsi']=await jitsi(browser,tab);print(json.dumps({'jitsi':results['jitsi']}),flush=True)
  if 'matrixrtc' in parts:results['matrixrtc']=await matrixrtc(browser,tab,'all');print(json.dumps({'matrixrtc':results['matrixrtc']}),flush=True)
  if 'turn' in parts:results['turn']=await turn(tab);print(json.dumps({'turn':results['turn']}),flush=True)
  if 'matrixrtc-relay' in parts:results['matrixrtc_relay']=await matrixrtc(browser,tab,'relay');print(json.dumps({'matrixrtc_relay':results['matrixrtc_relay']}),flush=True)
 finally:
  # Another host keeps its own result file, so a check of that host does not replace the local result.
  name=f"call-check-{zone}-{os.environ['LAB_SUFFIX']}.json" if os.environ.get('LAB_SUFFIX') else f'call-check-{zone}.json'
  (OUT/name).write_text(json.dumps(results,indent=1)+'\n')
  await stop_browser(browser)
import urllib.parse
asyncio.run(main())
