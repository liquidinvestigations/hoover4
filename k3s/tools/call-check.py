#!/usr/bin/env python3
"""Check a short audio call in one zone with Jitsi, and the TURN server. Usage: call-check.py <zone> [jitsi] [turn]

The browser uses Chrome fake media devices, so no microphone is needed. The check passes when each stack reports
the call. It does not judge the audio.
- Jitsi: the browser signs in through the portal as test.user and joins a meeting. The script then reads the
  conference count from the zone Jicofo and from the shared JVB.
- TURN: Chrome gathers relay candidates from coturn with a credential for the TURN secret of the zone, as Prosody
  gives it to the Jitsi clients.
LAB_SUFFIX, LAB_KUBECONFIG, LAB_USER and LAB_PASSWORD_FILE check another host or user. JITSI_SECOND_USER and
JITSI_SECOND_PASSWORD_FILE let a second user join the Jitsi call from a second browser. Without them the second
participant is a second tab of the first user. JITSI_HOLD=<seconds> keeps both
Jitsi participants in the call and records every 10 s whether each tab keeps its media session, its ICE state, and the
local candidate type. A session that the client starts again, as after an ICE failure, fails the check. JITSI_P2P=1
keeps peer-to-peer on, as in a normal call of two people. Without it, the call uses the bridge.
The script writes <state folder>/checks/call-check-<zone>.json, or call-check-<zone>-<LAB_SUFFIX>.json for another
host, and prints no token or password.
Run it with the browser Python environment in <state folder>/browser-venv, which has nodriver.
"""
import asyncio,base64,hashlib,hmac,json,os,pathlib,re,subprocess,sys,time,urllib.error,urllib.request
root=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
OUT=settings.PRIVATE/'checks';OUT.mkdir(parents=True,exist_ok=True)
os.environ['KUBECONFIG']=os.environ.get('LAB_KUBECONFIG',settings.KUBECONFIG)
sys.path.insert(0,str(settings.HOOVER4/'website/tools'))
from browser_lifecycle import start_browser,stop_browser
zone=sys.argv[1];parts=sys.argv[2:] or ['jitsi','turn'];S=os.environ.get('LAB_SUFFIX',settings.SUFFIX)
USER=os.environ.get('LAB_USER','test.user')
PASSWORD_FILE=pathlib.Path(os.environ.get('LAB_PASSWORD_FILE',settings.PRIVATE/f'zones/{zone}/test-user-password'))
HOLD=int(os.environ.get('JITSI_HOLD','0'));P2P='true' if os.environ.get('JITSI_P2P')=='1' else 'false'
import secretstore
secrets={'calls':secretstore.read('site/calls'),zone:secretstore.zone_secrets(zone)}
def kubectl(*args):
 r=subprocess.run(['kubectl',*args],check=True,capture_output=True,text=True);return r.stdout+r.stderr
def http(method,url,body=None,token=None):
 headers={'Content-Type':'application/json'}
 if token:headers['Authorization']='Bearer '+token
 request=urllib.request.Request(url,method=method,data=json.dumps(body).encode() if body is not None else None,headers=headers)
 with urllib.request.urlopen(request,timeout=60) as r:return json.loads(r.read() or b'{}')
def jitsi_stats():
 pod=json.loads(kubectl('-n',zone,'get','pods','-l','app.kubernetes.io/component=jicofo','-o','json'))['items'][0]['metadata']['name']
 jicofo=json.loads(kubectl('-n',zone,'exec',pod,'--','curl','-s','http://127.0.0.1:8888/stats'))
 jvb=json.loads(kubectl('-n','calls','exec','deploy/jvb','-c','jitsi','--','curl','-s','http://127.0.0.1:8080/colibri/stats'))
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
 tab=await browser.get(f'https://{zone}-portal.{S}/univention/oidc/?location=/univention/portal/');await asyncio.sleep(4)
 await (await tab.select('input[name="username"]',timeout=20)).send_keys(user)
 await (await tab.select('input[name="password"]',timeout=10)).send_keys(password)
 await (await tab.select('#kc-login',timeout=10)).click();await asyncio.sleep(6)
 return tab
async def jitsi(browser,tab):
 room=f'hoovercheck{int(time.time())}'
 await tab.get(f'https://{zone}-meet.{S}/{room}#config.prejoinConfig.enabled=false&config.startWithVideoMuted=true&config.p2p.enabled={P2P}')
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
  await second.get(f'https://{zone}-meet.{S}/{room}#config.prejoinConfig.enabled=false&config.startWithVideoMuted=true&config.p2p.enabled={P2P}')
  result['second_user']=SECOND_USER
 else:
  second=await browser.get(f'https://{zone}-meet.{S}/{room}#config.prejoinConfig.enabled=false&config.startWithVideoMuted=true&config.p2p.enabled={P2P}',new_tab=True)
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
async def turn(tab):
 # Chrome gathers relay candidates from coturn with a credential for the TURN secret of the zone.
 name=f"{int(time.time())+600}:call-check";secret=secrets[zone]['turn_secret']
 credential=base64.b64encode(hmac.new(secret.encode(),name.encode(),hashlib.sha1).digest()).decode()
 await tab.get(f'https://{zone}-meet.{S}/')
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
  if 'turn' in parts:results['turn']=await turn(tab);print(json.dumps({'turn':results['turn']}),flush=True)
 finally:
  # Another host keeps its own result file, so a check of that host does not replace the local result.
  name=f"call-check-{zone}-{os.environ['LAB_SUFFIX']}.json" if os.environ.get('LAB_SUFFIX') else f'call-check-{zone}.json'
  (OUT/name).write_text(json.dumps(results,indent=1)+'\n')
  await stop_browser(browser)
import urllib.parse
asyncio.run(main())
