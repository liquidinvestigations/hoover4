"""The watch tools of a wait: sweep.py marks a pod that the scheduler cannot place, and watch-record.py exits at the
first result, failure or stall of a deploy record."""
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

K3S = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stamp(seconds_ago):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - seconds_ago))


def pending(seconds_ago):
    return {'metadata': {'name': 'w', 'namespace': 'z'},
            'status': {'phase': 'Pending', 'conditions': [
                {'type': 'PodScheduled', 'status': 'False', 'reason': 'Unschedulable',
                 'message': '0/3 nodes are available: 3 Insufficient memory', 'lastTransitionTime': stamp(seconds_ago)}]}}


def test_sweep_fails_a_pod_that_stays_unschedulable():
    sweep = load('sweep', K3S / 'tools' / 'sweep.py')
    assert sweep.pod_rows(pending(600))[1] is True
    assert sweep.pod_rows(pending(10))[1] is False


def record(tmp_path, steps, complete=False):
    deploy = tmp_path / 'operator' / 'deploy'
    (deploy / 'records').mkdir(parents=True)
    (deploy / 'logs').mkdir()
    (deploy / 'records' / 'r1.json').write_text(json.dumps({'complete': complete, 'error': '', 'steps': steps}))
    (deploy / 'logs' / 'r1.log').write_text('')


def watch(tmp_path, *args):
    return subprocess.run([sys.executable, str(K3S / 'tools' / 'watch-record.py'), str(tmp_path), '--record', 'r1', *args],
                          capture_output=True, text=True, timeout=60)


def test_watch_record_exits_at_completion(tmp_path):
    record(tmp_path, [{'name': 'stores', 'state': 'done'}], complete=True)
    out = watch(tmp_path)
    assert out.returncode == 0 and 'complete ok' in out.stdout


def test_watch_record_exits_at_a_step_error(tmp_path):
    record(tmp_path, [{'name': 'monitoring', 'state': 'failed', 'error': 'hook timed out'}])
    assert watch(tmp_path).returncode == 1


def test_watch_record_exits_at_a_stall(tmp_path):
    record(tmp_path, [{'name': 'zone:a', 'state': 'running', 'started': stamp(5)}])
    out = watch(tmp_path, '--stall', '2')
    assert out.returncode == 2 and 'stall' in out.stdout


def test_watch_record_exits_when_a_step_passes_its_limit(tmp_path):
    record(tmp_path, [{'name': 'zone:a', 'state': 'running', 'started': stamp(600)}])
    out = watch(tmp_path, '--limit', 'zone:*=60')
    assert out.returncode == 3 and 'over its limit' in out.stdout
