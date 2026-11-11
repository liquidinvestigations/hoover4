#!/usr/bin/env python3
"""Connect Notes and Collabora of each zone to the private LLM in k3s/private/ai.json. Usage: zone-ai.py [zone ...]

openDesk wires Notes and Collabora through one ai setting (endpoint, API key, model). zones.py writes the same
setting into the zone values, so a zone install applies it. This script applies it to the running zones.
It sets the Notes key in the Secret and the base URL and model in the backend and worker Deployments.
It adds the options that the Collabora chart renders to the collabora ConfigMap. Collabora restarts when they change.
The script prints no key.
"""
import base64,json,os,pathlib,subprocess,sys
from urllib.parse import urlparse
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import settings
settings.use_kubeconfig()
ai=json.loads((settings.PRIVATE/'ai.json').read_text());key=pathlib.Path(ai['api_key_file']).read_text().strip()
def kubectl(*args,data=None):return subprocess.run(['kubectl',*args],input=data,text=True,check=True,capture_output=True).stdout
def collabora_options():
 # The same options as helmfile/apps/collabora/values.yaml.gotmpl renders for a set ai.endpoint.
 host=urlparse(ai['endpoint']).hostname.replace('.','\\.')
 # The openDesk template leaves a trailing slash after it removes /v1. Collabora then calls //v1/chat/completions,
 # and vLLM answers 404 for that path. This script removes the slash.
 base=ai['endpoint'].rstrip('/').removesuffix('v1').rstrip('/')
 return ['--o:ai.enabled=true','--o:ai.allow_user_settings=false',f'--o:ai.api_url={base}',f"--o:ai.model={ai['model']}",f'--o:ai.api_key={key}',f'--o:net.lok_allow.host[0]={host}']
for zone in sys.argv[1:] or ['zone-a','zone-b']:
 kubectl('-n',zone,'patch','secret','impress-backend','-p',json.dumps({'data':{'aiApiKey':base64.b64encode(key.encode()).decode()}}))
 for deployment in ('impress-backend','impress-backend-worker'):
  kubectl('-n',zone,'set','env',f'deployment/{deployment}',f"OPENAI_SDK_BASE_URL={ai['endpoint']}",f"AI_MODEL={ai['model']}")
 config=json.loads(kubectl('-n',zone,'get','configmap','collabora','-o','json'))
 params=[p for p in config['data']['extra_params'].split() if not p.startswith(('--o:ai.','--o:net.lok_allow.host'))]
 wanted=' '.join(params+collabora_options());changed=wanted!=config['data']['extra_params']
 # Collabora reads the options only at start, so it restarts only when they change.
 if changed:
  kubectl('-n',zone,'patch','configmap','collabora','-p',json.dumps({'data':{'extra_params':wanted}}))
  kubectl('-n',zone,'rollout','restart','deployment/collabora')
 print(json.dumps({'zone':zone,'endpoint':ai['endpoint'],'model':ai['model'],'notes':'set','collabora':'set and restarted' if changed else 'unchanged'}))
