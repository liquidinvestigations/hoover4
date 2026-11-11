#!/usr/bin/env python3
"""Check that the zone gate ends a session after a Keycloak logout. Usage: gate-logout-check.py <zone>

The check signs in at the gate as Administrator and asks auth.<zone>.<suffix>/oauth2/auth with the gate cookie. It then
ends the Keycloak sessions of Administrator through the Keycloak admin API, and asks the gate again every 15 seconds.
The gate refreshes its tokens one minute after the last refresh, so it must answer 401 within 120 seconds.
The check prints one JSON line for each step and no password. It exits with 1 when the gate still answers 202.
"""
import base64
import html
import http.cookiejar
import ipaddress
import json
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings  # noqa: E402

settings.use_kubeconfig()


def secret(zone, name, key):
    data = json.loads(subprocess.check_output(['kubectl', '-n', zone, 'get', 'secret', name, '-o', 'json']))['data'][key]
    return base64.b64decode(data).decode()


def request(opener, url, data=None):
    try:
        with opener.open(urllib.request.Request(url, data=data), timeout=60) as r:
            return r.status, r.read().decode(errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors='replace')


def logout(zone, opener):
    """End the Keycloak sessions of Administrator through the Keycloak admin API.

    The frontend answers the admin routes only from the VPN, so the host id.<zone>.<suffix> connects to the VPN address
    of the frontend. The requests carry the gate cookie of the opener.
    """
    host = f'id.{zone}.{settings.SUFFIX}'
    vpn = ipaddress.ip_network(settings.HOST['vpn_cidr'])
    address = next(a for a in settings.FRONTEND_BIND if ipaddress.ip_address(a) in vpn)
    system = socket.getaddrinfo
    socket.getaddrinfo = lambda name, *args, **kwargs: system(address if name == host else name, *args, **kwargs)
    form = {'grant_type': 'password', 'client_id': 'admin-cli', 'username': 'kcadmin',
            'password': secret(zone, 'keycloak-admin-password', 'adminPassword')}
    with opener.open(f'https://{host}/realms/master/protocol/openid-connect/token', urllib.parse.urlencode(form).encode()) as r:
        headers = {'Authorization': 'Bearer ' + json.load(r)['access_token']}
    users = f'https://{host}/admin/realms/opendesk/users'
    with opener.open(urllib.request.Request(f'{users}?username=administrator&exact=true', headers=headers)) as r:
        user = json.load(r)[0]['id']
    with opener.open(urllib.request.Request(f'{users}/{user}/logout', data=b'', headers=headers)) as r:
        return f'logout answered {r.status}'


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    zone = sys.argv[1]
    domain = f'{zone}.{settings.SUFFIX}'
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [('Accept', 'text/html,*/*')]
    _, page = request(opener, f'https://auth.{domain}/oauth2/start?rd=/')
    form = re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', page)
    password = secret(zone, 'ums-nubus-credentials', 'administrator_password')
    request(opener, html.unescape(form.group(1)), urllib.parse.urlencode({'username': 'Administrator', 'password': password, 'credentialId': ''}).encode())
    auth = f'https://auth.{domain}/oauth2/auth'
    status, _ = request(opener, auth)
    print(json.dumps({'at': time.strftime('%H:%M:%S'), 'step': 'signed in', 'status': status}), flush=True)
    if status != 202:
        sys.exit(1)
    print(json.dumps({'at': time.strftime('%H:%M:%S'), 'step': 'keycloak logout of Administrator', 'out': logout(zone, opener)}), flush=True)
    start = time.monotonic()
    while time.monotonic() - start <= 120:
        status, _ = request(opener, auth)
        print(json.dumps({'at': time.strftime('%H:%M:%S'), 'seconds': round(time.monotonic() - start), 'status': status}), flush=True)
        if status == 401:
            return
        time.sleep(15)
    sys.exit(1)


if __name__ == '__main__':
    main()
