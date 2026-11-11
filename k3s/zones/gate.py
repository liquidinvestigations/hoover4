#!/usr/bin/env python3
"""Build the sign-in service of the zone gate: one oauth2-proxy in the zone namespace at auth.<zone>.<suffix>.

The HTTPS frontend (../platform/frontend/install-frontend.sh) asks this proxy at /oauth2/auth before it sends a request
to a gated route of the zone. The proxy uses the Keycloak client opendesk-gate of the zone (zones.py, gate_oidc).
Its cookie has the domain .<zone>.<suffix>, so one sign-in opens every application host of the zone.
The Secret gate-oidc holds the client secret and the cookie secret. zones.py writes it, and zone.py applies it.
The sessions are in a Redis container of the same pod, and the cookie holds only the session ticket. With a cookie
session each parallel request of a page refreshes the tokens itself, so the refresh of one page sends hundreds of token
requests to Keycloak. With Redis one request refreshes, and the others wait for its lock and read the new session.
Redis keeps no file, so a pod restart ends the sessions, and the browser signs in again through the Keycloak session.
Usage: gate.py <zone>    prints the objects as a JSON List
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings  # noqa: E402

IMAGE = 'quay.io/oauth2-proxy/oauth2-proxy:v7.12.0@sha256:786bed0f000c0f8a7b31619244ebab02406a8856a4faf3f5fb1df61fbd6c30ed'
REDIS = 'docker.io/library/redis:8.2.3-alpine@sha256:08ad0b1d280850169a790dba1393ff7a90aef951fc19632cf4d3ce4f78e679ba'
LABELS = {'app.kubernetes.io/name': 'gate'}


def objects(zone):
    domain = f'{zone}.{settings.SUFFIX}'
    args = ['--provider=oidc', f'--oidc-issuer-url=https://id.{domain}/realms/opendesk', '--client-id=opendesk-gate',
            '--client-secret-file=/secrets/client-secret', f'--redirect-url=https://auth.{domain}/oauth2/callback',
            '--http-address=0.0.0.0:4180', '--email-domain=*', '--reverse-proxy=true',
            # The client has only the profile scope (zones.py, gate_oidc). Its tokens carry no mail address, because
            # the zones send no mail and Keycloak marks no address as verified. The user name names the session.
            '--scope=openid profile', '--oidc-email-claim=preferred_username',
            '--skip-provider-button=true', '--upstream=static://202', '--silence-ping-logging=true',
            f'--cookie-domain=.{domain}', f'--whitelist-domain=.{domain}', '--cookie-name=_hoover_gate',
            '--cookie-secure=true', '--cookie-samesite=lax',
            # oauth2-proxy has no OIDC back-channel logout. It refreshes its tokens one minute after the last refresh.
            # Keycloak refuses the refresh after a logout, and the proxy then drops its session.
            '--cookie-refresh=1m', '--cookie-expire=16h',
            '--session-store-type=redis', '--redis-connection-url=redis://127.0.0.1:6379']
    security = {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}, 'readOnlyRootFilesystem': True,
                'runAsNonRoot': True, 'runAsUser': 65532, 'seccompProfile': {'type': 'RuntimeDefault'}}
    # A sidecar starts before the proxy and is ready when Redis answers. Only the containers of the pod reach it.
    redis = {'name': 'redis', 'image': REDIS, 'restartPolicy': 'Always',
             'command': ['redis-server', '--bind', '127.0.0.1', '--port', '6379', '--save', '', '--appendonly', 'no',
                         '--maxmemory', '40mb', '--maxmemory-policy', 'volatile-ttl'],
             'startupProbe': {'exec': {'command': ['redis-cli', 'ping']}, 'periodSeconds': 1, 'failureThreshold': 30},
             'resources': {'requests': {'cpu': '10m', 'memory': '16Mi'}, 'limits': {'cpu': '1', 'memory': '64Mi'}},
             'securityContext': security}
    container = {'name': 'oauth2-proxy', 'image': IMAGE, 'args': args,
                 'env': [{'name': 'OAUTH2_PROXY_COOKIE_SECRET', 'valueFrom': {'secretKeyRef': {'name': 'gate-oidc', 'key': 'cookie-secret'}}}],
                 'ports': [{'name': 'http', 'containerPort': 4180}],
                 'readinessProbe': {'httpGet': {'path': '/ping', 'port': 4180}, 'periodSeconds': 5},
                 # The load test of 16 tabs used 1 CPU and 175 MiB with the sandbox, at the old limits.
                 'resources': {'requests': {'cpu': '10m', 'memory': '32Mi'}, 'limits': {'cpu': '2', 'memory': '384Mi'}},
                 'securityContext': security,
                 'volumeMounts': [{'name': 'secrets', 'mountPath': '/secrets', 'readOnly': True}]}
    pod = {'automountServiceAccountToken': False, 'enableServiceLinks': False, 'initContainers': [redis], 'containers': [container],
           'volumes': [{'name': 'secrets', 'secret': {'secretName': 'gate-oidc', 'items': [{'key': 'client-secret', 'path': 'client-secret'}]}}]}
    return {'apiVersion': 'v1', 'kind': 'List', 'items': [
        {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': 'gate', 'namespace': zone, 'labels': LABELS},
         'spec': {'replicas': 1, 'selector': {'matchLabels': LABELS}, 'template': {'metadata': {'labels': LABELS}, 'spec': pod}}},
        {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': 'gate', 'namespace': zone, 'labels': LABELS},
         'spec': {'selector': LABELS, 'ports': [{'name': 'http', 'port': 4180, 'targetPort': 'http'}]}},
        {'apiVersion': 'networking.k8s.io/v1', 'kind': 'Ingress', 'metadata': {'name': 'gate', 'namespace': zone, 'labels': LABELS},
         'spec': {'ingressClassName': 'haproxy', 'rules': [{'host': f'auth.{domain}', 'http': {'paths': [{
             'path': '/', 'pathType': 'Prefix', 'backend': {'service': {'name': 'gate', 'port': {'number': 4180}}}}]}}]}}]}


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(json.dumps(objects(sys.argv[1]), indent=1))
