#!/usr/bin/env python3
"""Watch one deploy record of `deploy-k3s` and exit at its first result, failure or stall.

It prints one line when a step starts, ends or fails, so it can feed a monitor that emits one event per line.
It reads only the record and its log in the state folder of the site, so it needs no cluster access.

Exit codes:
  0  the record is complete without an error
  1  the record or a step has an error
  2  stall: no step changed and the log did not grow for --stall seconds
  3  a running step is older than its limit (STEP_LIMITS, or --limit NAME=SECONDS)
  4  the --deadline passed

Usage: watch-record.py <state folder of the site> [--record ID] [--stall SECONDS] [--deadline SECONDS]
                       [--limit NAME=SECONDS ...]
Without --record it watches the newest record, and it waits up to 60 s for a new one to appear.
"""
import argparse
import calendar
import fnmatch
import json
import sys
import time
from pathlib import Path

# The seconds after which a running step counts as stalled. The values are the "investigate after" column of
# .agents/skills/batching-cluster-changes/reference/expected-durations.md, measured on the three-node test site.
STEP_LIMITS = {
    'hosts:prepare': 60,
    'hosts:k3s': 120,
    'hosts:verify': 60,
    'images': 120,
    'monitoring': 120,
    'stores': 420,
    'prepull': 180,
    'zone:*': 1500,
    'calls': 300,
    '*': 120,
}
POLL_SECONDS = 15


def limit_of(name, limits):
    for pattern, seconds in limits.items():
        if fnmatch.fnmatch(name, pattern):
            return seconds
    return None


def seconds_since(stamp):
    return time.time() - calendar.timegm(time.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ'))


def newest(records, after):
    found = sorted(p for p in records.glob('*.json') if p.stat().st_mtime >= after)
    return found[-1] if found else None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('state')
    parser.add_argument('--record')
    parser.add_argument('--stall', type=int, default=300)
    parser.add_argument('--deadline', type=int, default=3600)
    parser.add_argument('--limit', action='append', default=[])
    args = parser.parse_args()
    deploy = Path(args.state) / 'operator' / 'deploy'
    limits = dict(STEP_LIMITS)
    for item in args.limit:
        name, seconds = item.split('=', 1)
        limits = {name: int(seconds), **{k: v for k, v in limits.items() if k != name}}

    start = time.time()
    record = deploy / 'records' / f'{args.record}.json' if args.record else None
    while record is None or not record.exists():
        record = record if args.record else newest(deploy / 'records', start - 60)
        if record and record.exists():
            break
        if time.time() - start > 60:
            print(f'no record appeared in {deploy / "records"}', flush=True)
            return 4
        time.sleep(2)
    log = deploy / 'logs' / f'{record.stem}.log'
    print(f'watching {record.stem}', flush=True)

    seen, last_change, last_size = {}, time.time(), -1
    while True:
        try:
            data = json.loads(record.read_text())
        except (OSError, ValueError):
            time.sleep(1)
            continue
        size = log.stat().st_size if log.exists() else 0
        if size != last_size:
            last_size, last_change = size, time.time()
        for step in data.get('steps', []):
            key = (step.get('state'), bool(step.get('error')))
            if seen.get(step['name']) != key:
                seen[step['name']], last_change = key, time.time()
                if step.get('state') != 'pending':
                    error = f" error={step['error'][:300]}" if step.get('error') else ''
                    print(f"step {step['name']} {step.get('state')}{error}", flush=True)
        failed = [s['name'] for s in data.get('steps', []) if s.get('error')]
        if data.get('complete'):
            ok = not data.get('error') and not failed
            print(f"record {record.stem} complete {'ok' if ok else 'with errors: ' + ', '.join(failed)}", flush=True)
            return 0 if ok else 1
        if failed:
            print(f"record {record.stem} failed steps: {', '.join(failed)}", flush=True)
            return 1
        for step in data.get('steps', []):
            limit = limit_of(step['name'], limits)
            if step.get('state') == 'running' and step.get('started') and limit:
                age = seconds_since(step['started'])
                if age > limit:
                    print(f"step {step['name']} running {int(age)} s, over its limit of {limit} s", flush=True)
                    return 3
        if time.time() - last_change > args.stall:
            print(f'stall: no step change and no log growth for {args.stall} s', flush=True)
            return 2
        if time.time() - start > args.deadline:
            print(f'deadline of {args.deadline} s passed', flush=True)
            return 4
        time.sleep(POLL_SECONDS)


if __name__ == '__main__':
    sys.exit(main())
