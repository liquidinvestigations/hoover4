#!/usr/bin/env python3
"""Check the MCP servers behind loopback ports with the streamable HTTP protocol that the development clients use.

For each port the check sends initialize, the initialized notification and tools/list to http://127.0.0.1:<port>/mcp,
as Claude Code does for an entry of .mcp.json. It prints one JSON line for each server: the HTTP status, the server
name and the tool names. With --secret-from the collections and todo servers get the bearer token of their shared
secret: `k3s:<namespace>` reads the item mcp-shared-secret of the Secret hoover-runtime, and a path reads a file.
The check calls list_collections of the collections server, which checks the token. It repeats each request without
the token for the servers that need one, and records the refusal.
A server fails the check when its HTTP status is not 200, it lists no tool, its server name does not match the name of
the argument, the tool call returns an error result or no content, or the call without the token is not refused. SERVER_NAMES
holds the reported name of each known server. Another name matches when it is equal after the removal of the words
mcp, hoover4 and server and of every character that is not a letter or a digit. A tool result with success false
counts as an error. --user names the Hoover user of the calls, which must exist in the installation. It prints no secret.
Usage: mcp-relay-check.py [--secret-from k3s:<namespace>|<file>] <name>=<port> ...
"""
import argparse
import base64
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings  # noqa: E402

SECRET_SERVERS = {'mcp-collections', 'mcp-todo'}
# The headers that the agents send. The collections server needs the permitted collections of the caller.
CALLER = {'x-hoover4-user': 'relay-check', 'x-hoover4-collections': '', 'x-hoover4-chat-session': 'relay-check'}


def secret(source):
    if not source:
        return ''
    if source.startswith('k3s:'):
        out = subprocess.run(['kubectl', '--kubeconfig', settings.KUBECONFIG, '-n', source[4:], 'get', 'secret', 'hoover-runtime',
                              '-o', 'jsonpath={.data.mcp-shared-secret}'], capture_output=True, text=True, check=True).stdout
        return base64.b64decode(out).decode().strip()
    return Path(source).read_text().strip()


def post(port, body, headers):
    request = urllib.request.Request(f'http://127.0.0.1:{port}/mcp', data=json.dumps(body).encode(), method='POST',
                                     headers={'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream', **headers})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode()
            return response.status, response.headers.get('mcp-session-id'), text
    except urllib.error.HTTPError as error:
        return error.code, None, error.read().decode(errors='replace')


def message(text):
    """The JSON-RPC message of a JSON or event-stream answer."""
    for line in text.splitlines():
        if line.startswith('data:'):
            return json.loads(line[5:])
    return json.loads(text) if text.strip() else {}


def session(port, headers):
    status, sid, text = post(port, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'mcp-relay-check', 'version': '1'}}}, headers)
    if status != 200:
        return {'status': status, 'error': text[:200]}
    server = message(text).get('result', {}).get('serverInfo', {}).get('name')
    headers = {**headers, **({'mcp-session-id': sid} if sid else {})}
    post(port, {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, headers)
    status, _, text = post(port, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, headers)
    answer = message(text) if status == 200 else {}
    tools = sorted(t['name'] for t in answer.get('result', {}).get('tools', []))
    result = {'status': status, 'server': server, 'tools': tools, 'error': answer.get('error') or (text[:200] if status != 200 else None)}
    if 'list_collections' in tools:
        # The collections server checks the bearer token on a tool call.
        status, _, text = post(port, {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                                      'params': {'name': 'list_collections', 'arguments': {}}}, headers)
        answer = message(text) if status == 200 else {}
        call = answer.get('result', {})
        content = ' '.join(c.get('text', '') for c in call.get('content', []) if isinstance(c, dict))
        # The tools of the collections server answer a refusal as a result with success false, not as isError.
        try:
            body = json.loads(content)
        except ValueError:
            body = None
        failed = isinstance(body, dict) and (body.get('success') is False or 'error' in body)
        reason = str(body.get('error') or body.get('message') or '') if isinstance(body, dict) else ''
        result['call'] = {'tool': 'list_collections', 'status': status,
                          'is_error': bool(call.get('isError') or answer.get('error') or status != 200 or failed),
                          'refused': 'bearer token' in content or reason in ('unauthenticated', 'unauthorized', 'forbidden'),
                          'reason': reason, 'has_content': bool(content.strip())}
    return result


# The server name that each MCP server reports in its initialize answer.
SERVER_NAMES = {'mcp-collections': 'hoover4_collection_search', 'mcp-todo': 'hoover4_todo', 'mcp-whois': 'whois_lookup',
                'mcp-metasearch': 'hoover4_metasearch', 'mcp-browser': 'hoover4_browser'}


def same_server(name, reported):
    if name in SERVER_NAMES:
        return reported == SERVER_NAMES[name]
    def key(text):
        words = re.split(r'[^a-z0-9]+', (text or '').lower())
        return ''.join(w for w in words if w not in ('mcp', 'hoover4', 'server'))
    return bool(reported) and key(name) == key(reported)


def problems(name, result, token):
    """The reasons why a server fails the check, as a list of texts."""
    found = []
    if result['status'] != 200:
        found.append(f'HTTP status {result["status"]}')
    if not result.get('tools'):
        found.append('no tool')
    if result.get('server') is not None and not same_server(name, result.get('server')):
        found.append(f'the server name is {result.get("server")}')
    call = result.get('call')
    if call and (call['is_error'] or call['refused'] or not call['has_content']):
        found.append('list_collections returned an error result or no content')
    refused = (result.get('without_token') or {}).get('call')
    if name in SECRET_SERVERS and token and refused and not (refused['is_error'] or refused['refused']):
        found.append('the call without the token was not refused')
    return found


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--secret-from')
    parser.add_argument('--user', default='relay-check', help='a Hoover user of the installation')
    parser.add_argument('--collections', default='', help='the permitted collections of the calls, separated by commas')
    parser.add_argument('servers', nargs='+')
    args = parser.parse_args(argv)
    token = secret(args.secret_from)
    failed = False
    for item in args.servers:
        name, port = item.split('=')
        caller = {**CALLER, 'x-hoover4-user': args.user, 'x-hoover4-collections': args.collections}
        headers = dict(caller)
        if name in SECRET_SERVERS and token:
            headers['Authorization'] = f'Bearer {token}'
        if name == 'mcp-browser':
            headers = {'x-hoover4-chat-session': 'host-mcp-client', 'x-hoover4-user': 'host'}
        result = {'name': name, 'port': int(port), **session(int(port), headers)}
        if name in SECRET_SERVERS and token:
            refused = session(int(port), dict(caller))
            result['without_token'] = {'status': refused['status'], 'tools': len(refused.get('tools') or []), 'call': refused.get('call')}
        result['problems'] = problems(name, result, token)
        failed |= bool(result['problems'])
        print(json.dumps(result), flush=True)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main(sys.argv[1:])
