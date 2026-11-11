#!/usr/bin/env python3
"""Cut the sampler output by the app phases of monkey.py and summarise memory, CPU and OOM events for each pod.

Usage: analyze.py <samples.jsonl> <driver.json> <summary.json>
Each phase window runs from the first readiness request of the app to 15 s after its exercise. The summary holds, per phase,
every pod whose peak memory rose by 32 MiB or more over its value at the window start, or whose CPU passed 0.5 cores,
or that had an OOM kill or a container restart. It also holds the whole-run peak of every pod with its limit.
A pod limit is the cgroup memory.max of the pod, or else the sum of its container limits when each container has one.
Kata pods show the whole VM on the host. An OOM kill inside a Kata guest appears only as a restart with the reason OOMKilled.
"""
import json
import sys

MIB = 1 << 20


def load(path):
    samples, maps = [], []
    for line in open(path):
        row = json.loads(line)
        (maps if 'map' in row else samples).append(row)
    return samples, maps


def pod_limit(entry):
    if entry.get('max'):
        return entry['max']
    limits = [c.get('max') for c in entry.get('c', {}).values()]
    return sum(limits) if limits and all(limits) else None


def name_of(maps, uid, t):
    for m in reversed(maps):
        pod = m['map'].get('pods', {}).get(uid)
        if pod and m['t'] <= t + 120:
            return f"{pod['ns']}/{pod['name']}", pod.get('runtime') or 'runc'
    for m in maps:
        pod = m['map'].get('pods', {}).get(uid)
        if pod:
            return f"{pod['ns']}/{pod['name']}", pod.get('runtime') or 'runc'
    return uid, '?'


def restarts(maps, t0, t1):
    """Container restarts between the last map before t0 and the first map after t1."""
    before = next((m for m in reversed(maps) if m['t'] <= t0), maps[0])['map'].get('containers', {})
    after = next((m for m in maps if m['t'] >= t1), maps[-1])['map'].get('containers', {})
    pods_after = next((m for m in maps if m['t'] >= t1), maps[-1])['map'].get('pods', {})
    by_key = lambda cs: {(c['pod'], c['name']): c for c in cs.values()}
    b, a = by_key(before), by_key(after)
    out = []
    for key, c in a.items():
        old = b.get(key)
        if old and c['restarts'] > old['restarts']:
            pod = pods_after.get(key[0], {})
            out.append({'pod': f"{pod.get('ns')}/{pod.get('name')}", 'container': key[1], 'restarts': c['restarts'] - old['restarts'],
                        'last_reason': c.get('last_reason')})
    return out


def window(samples, maps, t0, t1):
    rows = [s for s in samples if t0 <= s['t'] <= t1]
    if len(rows) < 2:
        return None
    first, pods = rows[0]['pods'], {}
    for prev, cur in zip(rows, rows[1:]):
        dt = cur['t'] - prev['t']
        for uid, e in cur['pods'].items():
            p = pods.setdefault(uid, {'start': first.get(uid, {}).get('mem'), 'peak': 0, 'cpu_peak': 0.0, 'cpu_sum': 0.0,
                                      'oom0': first.get(uid, {}).get('oom_kill', e['oom_kill']), 'oom1': 0, 'limit': None,
                                      'swap_peak': 0, 'high0': first.get(uid, {}).get('high', e['high']), 'high1': 0})
            p['peak'] = max(p['peak'], e['mem'] or 0)
            p['swap_peak'] = max(p['swap_peak'], e.get('swap') or 0)
            p['oom1'], p['high1'], p['limit'] = e['oom_kill'], e['high'], pod_limit(e) or p['limit']
            old = prev['pods'].get(uid)
            if old and old.get('cpu') is not None and e.get('cpu') is not None and dt > 0:
                cores = (e['cpu'] - old['cpu']) / 1e6 / dt
                p['cpu_peak'] = max(p['cpu_peak'], cores)
                p['cpu_sum'] += cores * dt
    hosts = [r['host'] for r in rows]
    cpu = [(b['host']['cpu'] - a['host']['cpu']) / 1e6 / (b['t'] - a['t']) for a, b in zip(rows, rows[1:]) if b['t'] > a['t']]
    result = {'seconds': round(rows[-1]['t'] - rows[0]['t']),
              'host': {'avail_min_mib': min(h['avail'] for h in hosts) // MIB, 'avail_start_mib': hosts[0]['avail'] // MIB,
                       'swapfree_min_mib': min(h['swapfree'] for h in hosts) // MIB, 'load1_max': max(h['load1'] for h in hosts),
                       'slice_peak_mib': max(h['slice'] for h in hosts) // MIB, 'slice_cpu_peak_cores': round(max(cpu), 2) if cpu else None},
              'pods': [], 'restarts': restarts(maps, t0, t1)}
    for uid, p in pods.items():
        name, runtime = name_of(maps, uid, t0)
        grew = p['peak'] - (p['start'] or 0)
        entry = {'pod': name, 'runtime': runtime, 'start_mib': (p['start'] or 0) // MIB, 'peak_mib': p['peak'] // MIB,
                 'limit_mib': p['limit'] // MIB if p['limit'] else None,
                 'peak_of_limit': round(p['peak'] / p['limit'], 2) if p['limit'] else None,
                 'cpu_peak_cores': round(p['cpu_peak'], 2), 'cpu_mean_cores': round(p['cpu_sum'] / max(1, result['seconds']), 2),
                 'oom_kills': p['oom1'] - p['oom0'], 'memory_high_events': p['high1'] - p['high0'], 'swap_peak_mib': p['swap_peak'] // MIB}
        entry['_keep'] = grew >= 32 * MIB or p['cpu_peak'] >= 0.5 or entry['oom_kills'] > 0
        result['pods'].append(entry)
    return result


def main():
    samples, maps = load(sys.argv[1])
    driver = json.load(open(sys.argv[2]))
    offset = driver.get('clock_offset', 0)
    summary = {'users': driver['users'], 'clock_offset': offset, 'phases': []}
    for phase in driver['phases']:
        t0 = phase.get('ready_start', phase['start']) + offset
        t1 = phase['end'] + offset + 15
        cut = window(samples, maps, t0, t1)
        if not cut:
            continue
        ex = window(samples, maps, phase['start'] + offset, phase['end'] + offset)
        cut['exercise_host'] = ex['host'] if ex else None
        cut['pods'] = sorted([dict((k, v) for k, v in p.items() if k != '_keep') for p in cut['pods'] if p['_keep']],
                             key=lambda p: -p['peak_mib'])
        tabs = phase.get('tabs', {})
        totals = {}
        for stats in tabs.values():
            for key, value in stats.items():
                if isinstance(value, (int, float)):
                    totals[key] = totals.get(key, 0) + value
        summary['phases'].append({'app': phase['app'], 'ready_seconds': phase.get('ready_seconds'),
                                  'sign_in_seconds': phase.get('sign_in_seconds'), 'exercise_seconds': round(phase['end'] - phase['start']),
                                  'browser_totals': totals, 'finish': phase.get('finish'), **cut})
    whole = window(samples, maps, samples[0]['t'], samples[-1]['t'])
    whole['pods'] = sorted([dict((k, v) for k, v in p.items() if k != '_keep') for p in whole['pods']],
                           key=lambda p: -(p['peak_of_limit'] or 0))
    summary['whole_run'] = whole
    json.dump(summary, open(sys.argv[3], 'w'), indent=1)
    print(json.dumps({'phases': [(p['app'], p['host']['avail_min_mib'], len(p['pods']), sum(x['oom_kills'] for x in p['pods']),
                                  len(p['restarts'])) for p in summary['phases']],
                      'whole_avail_min_mib': whole['host']['avail_min_mib']}, indent=None))


if __name__ == '__main__':
    main()
