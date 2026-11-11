#!/usr/bin/env python3
"""Print text lines from the memory of a running Kata guest, read through /proc of its VMM. The read changes nothing.

A guest whose agent no longer answers keeps its kernel log and the agent log buffer in memory. "watchdog" prints the
last lines of guest-watchdog.sh (prefix hooverwd) from the guest kernel log. "agent" prints the last JSON log lines of
the kata agent, sorted by their timestamp.
Usage (as root): guest-memory-lines.py watchdog|agent <sandbox id> [count]
"""
import json, os, re, sys

CHUNK = 64 << 20


def vmm_pid(sandbox):
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        try:
            if (open(f'/proc/{entry}/comm').read().startswith('cloud-hyperviso')
                    and sandbox.encode() in open(f'/proc/{entry}/cmdline', 'rb').read()):
                return int(entry)
        except OSError:
            continue
    raise SystemExit(f'no VMM runs for sandbox {sandbox}')


def matches(pid, pattern):
    """Yield each match of pattern in the guest RAM, which is a shared mapping of 64 MiB or more in the VMM."""
    regions = []
    for line in open(f'/proc/{pid}/maps'):
        fields = line.split()
        start, end = (int(x, 16) for x in fields[0].split('-'))
        if end - start >= 64 << 20 and 's' in fields[1]:
            regions.append((start, end))
    with open(f'/proc/{pid}/mem', 'rb', 0) as memory:
        for start, end in regions:
            for offset in range(start, end, CHUNK):
                memory.seek(offset)
                yield from re.finditer(pattern, memory.read(min(CHUNK, end - offset)))


def main():
    kind, sandbox = sys.argv[1], sys.argv[2]
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    pid = vmm_pid(sandbox)
    if kind == 'watchdog':
        lines = {m.group(0): int(m.group(1)) for m in matches(pid, rb'hooverwd (\d+) [^\x00\n]{0,900}')}
        last = max(lines.values(), default=0)
        rows = sorted((n, line.decode('latin1')) for line, n in lines.items() if n > last - count)
    elif kind == 'agent':
        rows = set()
        for m in matches(pid, rb'\{"msg":"[^\x00\n]{0,600}?"\}'):
            try:
                record = json.loads(m.group(0))
            except ValueError:
                continue
            rows.add((record.get('ts', ''), f"{record.get('ts', '')} {record.get('subsystem', '')} {record.get('msg', '')[:200]}"))
        rows = sorted(rows)[-count:]
    else:
        raise SystemExit(__doc__)
    for _, line in rows:
        print(line)


if __name__ == '__main__':
    main()
