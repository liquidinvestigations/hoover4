#!/usr/bin/env python3
"""Run the descheduler once, as a Job with a deadline, and delete the Job when it ends.

deploy-k3s up runs this script as its last step, after the zones and the call services. descheduler.yaml holds the
policy, which setup.sh applies. The Job runs the descheduler without --descheduling-interval, so it makes one pass and
exits. The script waits for the end of the Job, prints the eviction lines of its log, and deletes the Job and its
pod. A Deployment of an earlier version, which ran the descheduler every 10 minutes, is deleted first. So no
descheduler runs between deployments, and no pod moves outside a deployment.
Usage: deschedule.py [--deadline SECONDS]. KUBECONFIG names the admin kubeconfig.
"""
import json
import re
import subprocess
import sys
import time

NS = 'kube-system'
IMAGE = ('registry.k8s.io/descheduler/descheduler:v0.36.0'
         '@sha256:7ca92c0a7b4f1c51d306409da6b832005fcadb224e384795646376726734c6e5')
DEADLINE = 300


def kubectl(*args, input_text=None, check=True):
    proc = subprocess.run(['kubectl', *args], input=input_text, capture_output=True, text=True)
    if check and proc.returncode:
        raise SystemExit(f'kubectl {" ".join(args[:4])} failed: {(proc.stderr or proc.stdout).strip()[-400:]}')
    return proc.stdout


def job(name, deadline):
    """The Job of one descheduler pass. The pod gets no restart and the Job no retry, so a failure ends the step."""
    return {
        'apiVersion': 'batch/v1', 'kind': 'Job',
        'metadata': {'name': name, 'namespace': NS, 'labels': {'app.kubernetes.io/name': 'descheduler'}},
        'spec': {
            'backoffLimit': 0,
            'activeDeadlineSeconds': deadline,
            'ttlSecondsAfterFinished': 600,
            'template': {
                'metadata': {'labels': {'app.kubernetes.io/name': 'descheduler'}},
                'spec': {
                    'serviceAccountName': 'descheduler',
                    'priorityClassName': 'system-cluster-critical',
                    'restartPolicy': 'Never',
                    'containers': [{
                        'name': 'descheduler', 'image': IMAGE, 'command': ['/bin/descheduler'],
                        'args': ['--policy-config-file=/policy/policy.yaml', '--v=3'],
                        'resources': {'requests': {'cpu': '10m', 'memory': '64Mi'},
                                      'limits': {'cpu': '500m', 'memory': '256Mi'}},
                        'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                                            'runAsNonRoot': True, 'runAsUser': 65534,
                                            'capabilities': {'drop': ['ALL']}},
                        'volumeMounts': [{'name': 'policy', 'mountPath': '/policy', 'readOnly': True}],
                    }],
                    'volumes': [{'name': 'policy', 'configMap': {'name': 'descheduler-policy'}}],
                },
            },
        },
    }


def state(name):
    """'done', 'failed' or '' of the Job."""
    status = json.loads(kubectl('-n', NS, 'get', 'job', name, '-o', 'json')).get('status', {})
    for condition in status.get('conditions') or []:
        if condition.get('status') == 'True' and condition.get('type') in ('Complete', 'Failed'):
            return 'done' if condition['type'] == 'Complete' else f"failed: {condition.get('reason')} {condition.get('message', '')}"
    return ''


def main():
    deadline = int(sys.argv[sys.argv.index('--deadline') + 1]) if '--deadline' in sys.argv else DEADLINE
    kubectl('-n', NS, 'delete', 'deployment', 'descheduler', '--ignore-not-found', '--wait=true')
    name = f'descheduler-{int(time.time())}'
    kubectl('apply', '-f', '-', input_text=json.dumps(job(name, deadline)))
    end = time.time() + deadline + 60
    result = ''
    while time.time() < end and not result:
        time.sleep(3)
        result = state(name)
    log = kubectl('-n', NS, 'logs', f'job/{name}', check=False)
    evicted = [line for line in log.splitlines() if re.search(r'Evicted pod|"Number of evicted pods"|evicted', line)]
    kubectl('-n', NS, 'delete', 'job', name, '--ignore-not-found', '--wait=true', '--cascade=foreground')
    print(json.dumps({'job': name, 'result': result or 'no end before the deadline', 'evictions': evicted[-20:]}))
    if result != 'done':
        raise SystemExit(f'the descheduler Job {name} did not complete: {result or "no end before the deadline"}')


if __name__ == '__main__':
    main()
