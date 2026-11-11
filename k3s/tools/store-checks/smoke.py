#!/usr/bin/env python3
"""Run the functional check of a store in a temporary pod and log the result.

Each check is a Python file in checks/. The pod mounts the secret that the check needs, so no credential leaves the cluster.
Usage: smoke.py <store> <label> <zone namespace>
A check runs in the zone namespace and gets ZONE in its environment. The stores run in Kata, and the check pod runs in
the runtime that the zone pod policy gives it.
The command exits with 1 when the pod fails, times out, or reports a failed operation.
"""
import json, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'hoover' / 'stores'))
import common  # noqa: E402

IMAGE = 'registry-1.docker.io/alpine/k8s@sha256:b421c2e9419edb98db39b6ab641669f4db7bb2acf354f22450c6b7e7176d1ff4'
CHECKS = {'seaweedfs': {'namespace': None, 'secret': 'seaweedfs-config'},
          'seaweedfs-load': {'namespace': None, 'secret': 'seaweedfs-config'},
          'garage': {'namespace': None, 'secret': 'garage-tenants'},
          'memcached': {'namespace': None, 'secret': None},
          'nats': {'namespace': None, 'secret': 'ums-provisioning-nats-admin', 'pod_ip_of': 'ums-provisioning-nats-0'},
          'redis': {'namespace': None, 'secret': 'redis-password'}}


def passed(store, result):
    """Verify the operations reported by the store check."""
    def load_ok(row):
        return row.get('identical') is True and all(
            row.get(key, [None])[0] == 0 for key in ('upload', 'download', 'delete'))

    if store == 'redis':
        return result.get('auth') == '+OK' and result.get('set_ok') == result.get('hits') == 10000
    if store == 'memcached':
        return result.get('hits') == 10000
    if store == 'nats':
        return (result.get('acks') == result.get('stream_messages') == 10000
                and isinstance(result.get('streams_after'), dict) and 'STORECHECK' not in result['streams_after'])
    if store == 'seaweedfs':
        return all(result.get(k) is True for k in ('put_ok', 'read_back_identical', 'delete_ok', 'other_bucket_list_refused'))
    if store == 'seaweedfs-load':
        return load_ok(result)
    if store == 'garage':
        return all(result.get(k) is True for k in ('round_trip', 'delete_ok', 'anonymous_list_refused')) and load_ok(result.get('load', {}))
    return False


def main():
    store, label = sys.argv[1], sys.argv[2]
    check = dict(CHECKS[store])
    check['namespace'] = sys.argv[3]
    name = f'store-check-{store}'
    script = (HERE / 'checks' / f'{store}.py').read_text()
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': check['namespace'], 'labels': {common.LABEL: 'smoke'}},
           'spec': {'restartPolicy': 'Never', 'terminationGracePeriodSeconds': 1,
                    'containers': [{'name': 'check', 'image': IMAGE, 'command': ['python3', '-c', script],
                                    'env': [{'name': 'ZONE', 'value': check['namespace']}] + (
                                        [{'name': 'POD_IP', 'value': common.kubectl_json('-n', check['namespace'], 'get', 'pod', check['pod_ip_of'])['status']['podIP']}]
                                        if check.get('pod_ip_of') else []),
                                    'volumeMounts': [{'name': 'secret', 'mountPath': '/secret', 'readOnly': True}] if check['secret'] else [],
                                    'resources': {'limits': {'cpu': '1', 'memory': '256Mi'}}}],
                    'volumes': [{'name': 'secret', 'secret': {'secretName': check['secret']}}] if check['secret'] else []}}
    common.kubectl('-n', check['namespace'], 'delete', 'pod', name, '--ignore-not-found', '--wait=true')
    common.apply(pod)
    t = time.time()
    deadline = time.time() + 600
    while time.time() < deadline and common.kubectl_json('-n', check['namespace'], 'get', 'pod', name)['status'].get('phase') not in ('Succeeded', 'Failed'):
        time.sleep(2)
    phase = common.kubectl_json('-n', check['namespace'], 'get', 'pod', name)['status'].get('phase')
    lines = common.kubectl('-n', check['namespace'], 'logs', name, check=False).strip().splitlines()
    try:
        result = json.loads(lines[-1])
    except (IndexError, ValueError):
        result = {'error': lines[-5:]}
    ok = phase == 'Succeeded' and isinstance(result, dict) and passed(store, result)
    common.log('smoke.jsonl', store=store, namespace=check['namespace'], label=label, seconds=round(time.time() - t, 1),
               phase=phase, ok=ok, result=result)
    common.kubectl('-n', check['namespace'], 'delete', 'pod', name, '--wait=false')
    if not ok:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
