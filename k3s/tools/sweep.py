#!/usr/bin/env python3
"""Print every pod that is not ready in the named namespaces, with its reason, and the recent Warning events.

One call shows all failures of a batch, so one fix round can correct all of them.
--wait SECONDS repeats the sweep every 3 s. It stops when all pods are ready (exit 0), when a pod reaches a state
that waiting does not repair (exit 2), or at the deadline (exit 1). The final sweep is always printed.
Usage: sweep.py <namespace>... [--wait SECONDS]
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings  # noqa: E402
K = ['kubectl', '--kubeconfig', settings.KUBECONFIG]
# A pod in one of these states stays there until something changes its input.
FATAL = {'CrashLoopBackOff', 'ErrImageNeverPull', 'ErrImagePull', 'ImagePullBackOff', 'InvalidImageName',
         'CreateContainerConfigError', 'CreateContainerError', 'RunContainerError', 'OOMKilled', 'Error'}


def get(namespace, kind):
    r = subprocess.run(K + ['-n', namespace, 'get', kind, '-o', 'json'], capture_output=True, text=True)
    return json.loads(r.stdout)['items'] if r.returncode == 0 else []


def pod_rows(pod):
    """Return (ready, fatal, text) for one pod."""
    name = pod['metadata']['name']
    if pod['status'].get('phase') == 'Succeeded':
        return True, False, ''
    # A failed Job pod stays for its record. It holds no running work, so it does not block the readiness of a batch.
    if pod['status'].get('phase') == 'Failed' and any(o.get('kind') == 'Job' for o in pod['metadata'].get('ownerReferences', [])):
        return True, False, f"job   {pod['metadata']['namespace']}/{pod['metadata']['name']} failed"

    statuses = pod['status'].get('initContainerStatuses', []) + pod['status'].get('containerStatuses', [])
    ready = bool(pod['status'].get('containerStatuses')) and all(s.get('ready') for s in pod['status']['containerStatuses'])
    if ready:
        return True, False, ''
    parts, fatal = [], False
    for s in statuses:
        if s.get('ready') or 'terminated' in s.get('state', {}) and s['state']['terminated'].get('exitCode') == 0:
            continue
        state = s.get('state', {})
        reason = (state.get('waiting') or state.get('terminated') or {}).get('reason') or ('running' if 'running' in state else '?')
        last = s.get('lastState', {}).get('terminated', {})
        message = (state.get('waiting') or {}).get('message', '')[:160]
        fatal |= reason in FATAL or (last.get('reason') in FATAL and s.get('restartCount', 0) >= 2)
        parts.append(f"{s['name']}={reason} restarts={s.get('restartCount', 0)}"
                     + (f" last={last.get('reason')}:{last.get('exitCode')}" if last else '') + (f' msg={message}' if message else ''))
    if not statuses:
        for c in pod['status'].get('conditions', []):
            if c.get('status') != 'True' and c.get('message'):
                parts.append(f"{c['type']}: {c['message'][:160]}")
    return False, fatal, f"{pod['metadata']['namespace']}/{name} phase={pod['status'].get('phase')} " + '; '.join(parts)


def sweep(namespaces, since):
    lines, all_ready, fatal = [], True, False
    for ns in namespaces:
        for pod in get(ns, 'pods'):
            if pod['metadata'].get('deletionTimestamp'):
                continue
            ready, bad, text = pod_rows(pod)
            all_ready &= ready
            fatal |= bad
            if text:
                lines.append(('FATAL ' if bad else 'wait  ') + text)
        # A rollout with the Recreate strategy has a moment with no pod at all, so the controllers count too.
        for kind in ('deployments', 'statefulsets'):
            for item in get(ns, kind):
                want, have = item['spec'].get('replicas', 1), item['status'].get('readyReplicas', 0)
                if have < want:
                    all_ready = False
                    lines.append(f"wait  {ns}/{kind[:-1]}/{item['metadata']['name']} ready={have}/{want}")
        for e in get(ns, 'events'):
            stamp = e.get('lastTimestamp') or e.get('eventTime') or ''
            if e.get('type') == 'Warning' and stamp >= since:
                lines.append(f"event {ns}/{e['involvedObject']['name']} {e['reason']}: {e.get('message', '')[:200]}")
    return all_ready, fatal, lines


def main():
    args = sys.argv[1:]
    wait = 0
    if '--wait' in args:
        i = args.index('--wait')
        wait = int(args[i + 1])
        del args[i:i + 2]
    if not args:
        raise SystemExit(__doc__)
    since = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - 600))
    deadline = time.monotonic() + wait
    while True:
        ready, fatal, lines = sweep(args, since)
        if ready or fatal or time.monotonic() >= deadline:
            break
        time.sleep(3)
    print('\n'.join(lines) or 'all pods ready')
    print(json.dumps({'ready': ready, 'fatal': fatal}))
    sys.exit(0 if ready else 2 if fatal else 1)


if __name__ == '__main__':
    main()
