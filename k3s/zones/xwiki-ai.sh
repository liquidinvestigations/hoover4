#!/usr/bin/env bash
# Install the XWiki LLM Application and connect it to the model in k3s/private/ai.json. Usage: xwiki-ai.sh <zone>
# Administrator must be an XWiki admin. The LDAP group jobs give that right within a minute after the wiki starts.
# XWiki installs the extension from the extension repository (manifests/xwiki-extensions.yaml).
# The key goes to the script through a private file, so it is not in a command line.
set -euo pipefail
cd "$(dirname "$0")"
zone=$1
version=0.11
# The browser Python environment has nodriver.
py=${BROWSER_PYTHON:-../private/browser-venv/bin/python}
read -r endpoint model keyfile < <(python3 -c "import json;a=json.load(open('../private/ai.json'));print(a['endpoint'].rstrip('/')+'/',a['model'],a['api_key_file'])")
context=$(python3 - "$endpoint" "$model" "$keyfile" <<'P'
import json,sys,urllib.request
endpoint,model,keyfile=sys.argv[1:]
request=urllib.request.Request(endpoint+'models',headers={'Authorization':'Bearer '+open(keyfile).read().strip()})
print(next(m.get('max_model_len',32768) for m in json.load(urllib.request.urlopen(request,timeout=20))['data'] if m['id']==model))
P
)
$py xwiki-admin-script.py "$zone" xwiki/install-extension.vm id=org.xwiki.contrib.llm:application-ai-llm-models-ui version=$version | grep -E '^(state|installed|ERROR)'
$py xwiki-admin-script.py "$zone" xwiki/ai-setup.vm url="$endpoint" model="$model" token="file:$keyfile" context="$context" | grep -E '^(servers|models)'
$py xwiki-admin-script.py "$zone" xwiki/chat-check.js model="$model"
