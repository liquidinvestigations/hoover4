#!/usr/bin/env python3
"""Collect a debug report of one hoover4 deployment into one zip file.

Run it from the root of the checkout with this command:

    python3 scripts/collect-debug-report.py

The script uses the Python standard library only. It calls the `docker` (or `podman`)
binary, and the host tools that exist (`lscpu`, `free`, `vmstat`, `journalctl` and others).
A tool that is missing gives one "not found" entry in the report. It does not stop the run.

The script only reads. It starts, stops and changes nothing. It runs read-only queries
against ClickHouse, Manticore, Cassandra, Elasticsearch, Redis, Garage and Temporal through
`docker exec`. The script writes the zip into `<checkout>/tmp/`. The `--out-dir` flag names
another folder.

If `docker ps` needs root on this host, run the script with `sudo`.

Values of environment variables and ini keys whose names contain KEY, SECRET, PASSWORD or
TOKEN are replaced with `<redacted>` in the copies. `--no-redact` keeps them.
"""

import argparse
import concurrent.futures
import datetime
import json
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

# Compose projects that belong to hoover4. deploy.py names them.
PROJECTS = {"hoover4", "ai_services", "hoover4-devtools"}

# Container names that the main compose file fixes with `container_name`. A container
# with one of these names is collected even if its project label is missing.
KNOWN_NAMES = {
    "zookeeper", "manticore", "clickhouse", "temporal-cassandra", "temporal-elasticsearch",
    "temporal", "temporal-ui", "garage", "garage-init", "redis",
}

# The Temporal task queues the worker polls. The script adds every queue name it finds
# in the worker source, so a queue added later is also described.
BASE_QUEUES = [
    "processing-common-queue", "processing-tika-queue", "processing-ocr-queue",
    "processing-nlp-queue", "processing-embed-queue", "processing-indexing-queue",
    "processing-index-planner-queue", "operations-queue",
]

TEMPORAL_ADDR = "temporal:7233"

SECRET_NAME = re.compile(r"(KEY|SECRET|PASSWORD|PASSWD|TOKEN|CREDENTIAL)", re.I)

# Log lines that point at a known failure. Each one is counted in every captured log.
SIGNATURES = [
    "mbind", "Operation not permitted", "shard status unknown", "GRPC Message too large",
    "GrpcMessageTooLarge", "message too large", "ResourceExhausted", "DeadlineExceeded",
    "context deadline exceeded", "Unavailable", "ShardOwnershipLost", "shard ownership lost",
    "Persistent store operation failure", "Operation timed out", "WriteTimeout",
    "ReadTimeout", "NoHostAvailable", "OutOfMemory", "OOM", "Killed", "Traceback",
    "Exception", "ERROR", "WARN", "heartbeat", "Heartbeat timeout", "timed out",
    "Connection refused", "No space left", "Too many open files", "GC pause",
    "GCInspector", "Dropped", "DROPPED", "blocked", "history size exceeds",
    "history count exceeds", "Workflow task failed", "Failing workflow task",
    "workflow task timed out", "non-determinism", "Nondeterminism",
]

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
HEX_RE = re.compile(r"\b[0-9a-f]{12,}\b", re.I)
TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?Z?")
NUM_RE = re.compile(r"\d+")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class Report:
    """The staging directory, the manifest of every step, and the command runner."""

    def __init__(self, root, redact, default_timeout):
        self.root = Path(root)
        self.redact_on = redact
        self.default_timeout = default_timeout
        self.manifest = []
        self.lock = threading.Lock()
        self.notes = []

    def path(self, name):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def note(self, text):
        with self.lock:
            self.notes.append(text)

    def record(self, entry):
        with self.lock:
            self.manifest.append(entry)

    def write_text(self, name, text):
        self.path(name).write_text(text, encoding="utf-8", errors="replace")

    def write_json(self, name, obj):
        self.write_text(name, json.dumps(obj, indent=2, sort_keys=True, default=str))

    def run(self, name, argv, timeout=None, max_bytes=64 * 1024 * 1024, capture=False,
            merge=False):
        """Run one command. Write stdout into `name`, and stderr into `name.stderr`.

        With `merge`, stderr goes into `name` too, in the order the process wrote it.
        The command, its exit code, its run time and any failure go into the manifest.
        A missing binary, a timeout or a non-zero exit does not stop the report.
        With `capture`, return stdout as text, or None when the command did not run.
        """
        timeout = timeout or self.default_timeout
        started = time.time()
        entry = {"file": name, "argv": argv, "timeout_s": timeout}
        stdout_text = None
        try:
            with tempfile.TemporaryFile() as fo, tempfile.TemporaryFile() as fe:
                proc = subprocess.Popen(argv, stdout=fo,
                                        stderr=subprocess.STDOUT if merge else fe,
                                        stdin=subprocess.DEVNULL)
                try:
                    proc.wait(timeout=timeout)
                    entry["exit_code"] = proc.returncode
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    entry["exit_code"] = None
                    entry["error"] = "timeout after %ss" % timeout
                size = fo.tell()
                entry["bytes"] = size
                if size > max_bytes:
                    entry["truncated_to"] = max_bytes
                fo.seek(0)
                if name:
                    # Keep the tail of an oversized output: for a log it is the newest part.
                    if size > max_bytes:
                        fo.seek(size - max_bytes)
                    with open(self.path(name), "wb") as f:
                        shutil.copyfileobj(fo, f, 1024 * 1024)
                    fo.seek(0)
                if capture:
                    stdout_text = fo.read(max_bytes).decode("utf-8", errors="replace")
                fe.seek(0)
                err = fe.read(4 * 1024 * 1024)
                if err:
                    entry["stderr_head"] = err[:300].decode("utf-8", errors="replace")
                    if name:
                        with open(self.path(name + ".stderr"), "wb") as f:
                            f.write(err)
        except FileNotFoundError:
            entry["error"] = "not found: %s" % argv[0]
        except Exception as exc:  # the report must go on after any one failure
            entry["error"] = "%s: %s" % (type(exc).__name__, exc)
            entry["traceback"] = traceback.format_exc()
        entry["seconds"] = round(time.time() - started, 2)
        self.record(entry)
        return stdout_text if capture else None

    def sh(self, name, script, timeout=None, **kw):
        return self.run(name, ["sh", "-c", script], timeout=timeout, **kw)

    def redact_line(self, line):
        """Redact `NAME=value` and `name = value` when NAME looks like a credential."""
        if not self.redact_on:
            return line
        m = re.match(r"^(\s*[;#]?\s*)([A-Za-z0-9_.\-]+)(\s*[=:]\s*)(.*)$", line)
        if not m:
            return line
        key, value = m.group(2), m.group(4)
        if not SECRET_NAME.search(key) or key.upper().endswith("_FILE") \
                or key.upper().endswith("_FILE_HOST") or not value.strip() \
                or value.strip().startswith(("/", ";", "#")):
            return line
        return "%s%s%s<redacted>" % (m.group(1), key, m.group(3))

    def redact_text(self, text):
        return "\n".join(self.redact_line(l) for l in text.splitlines())

    def copy_file(self, name, src, redact=True):
        src = Path(src)
        entry = {"file": name, "copied_from": str(src)}
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            self.write_text(name, self.redact_text(text) if redact else text)
            entry["bytes"] = len(text)
        except FileNotFoundError:
            entry["error"] = "missing"
        except Exception as exc:
            entry["error"] = "%s: %s" % (type(exc).__name__, exc)
        self.record(entry)


def find_repo(explicit):
    if explicit:
        return Path(explicit).resolve()
    # This file is `<checkout>/scripts/collect-debug-report.py`, so the checkout is one level up.
    here = Path(__file__).resolve().parent
    for cand in [here.parent, Path.cwd(), *Path.cwd().parents]:
        if (cand / "hoover4.ini").is_file() and (cand / "deploy.py").is_file():
            return cand
    return here.parent


def find_engine(name):
    if name:
        return name
    for cand in ("docker", "podman"):
        if shutil.which(cand):
            return cand
    return None


# --------------------------------------------------------------------------------------
# Host
# --------------------------------------------------------------------------------------

def collect_host(r, since):
    j = "host/"
    r.run(j + "date.txt", ["date", "--iso-8601=seconds"])
    r.sh(j + "date-utc.txt", "date -u; echo; cat /proc/uptime")
    r.run(j + "uname.txt", ["uname", "-a"])
    r.sh(j + "os-release.txt", "cat /etc/os-release")
    r.run(j + "hostnamectl.txt", ["hostnamectl"])
    r.run(j + "timedatectl.txt", ["timedatectl"])
    r.run(j + "uptime.txt", ["uptime"])
    r.run(j + "nproc.txt", ["nproc", "--all"])
    r.run(j + "lscpu.txt", ["lscpu"])
    r.sh(j + "cpuinfo.txt", "cat /proc/cpuinfo")
    r.sh(j + "meminfo.txt", "cat /proc/meminfo")
    r.run(j + "free.txt", ["free", "-m", "-w"])
    r.run(j + "swapon.txt", ["swapon", "--show"])
    r.sh(j + "loadavg.txt", "cat /proc/loadavg")
    r.sh(j + "pressure.txt",
         "for f in /proc/pressure/*; do echo \"== $f\"; cat \"$f\"; done")
    r.run(j + "numactl-hardware.txt", ["numactl", "--hardware"])
    r.sh(j + "numa-sysfs.txt",
         "ls /sys/devices/system/node/ 2>&1; cat /proc/sys/kernel/numa_balancing 2>&1")
    r.sh(j + "thp.txt",
         "for f in enabled defrag; do echo \"== $f\"; "
         "cat /sys/kernel/mm/transparent_hugepage/$f; done")
    r.sh(j + "sysctl.txt",
         "sysctl -a 2>/dev/null | grep -E '^(vm\\.|kernel\\.(pid_max|threads-max|numa|sched)"
         "|fs\\.(file-max|file-nr|inotify|aio)|net\\.core\\.somaxconn|net\\.ipv4\\.ip_local)'")
    r.sh(j + "ulimit.txt", "ulimit -a")
    r.run(j + "df.txt", ["df", "-hT"])
    r.run(j + "df-inodes.txt", ["df", "-i"])
    r.run(j + "lsblk.txt", ["lsblk", "-o",
                            "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,ROTA,MODEL,SCHED,DISC-GRAN"])
    r.run(j + "findmnt.txt", ["findmnt", "-D"])
    r.sh(j + "mdstat.txt", "cat /proc/mdstat")
    r.sh(j + "diskstats.txt", "cat /proc/diskstats")
    r.sh(j + "cgroup.txt",
         "stat -fc %T /sys/fs/cgroup; echo; cat /sys/fs/cgroup/cgroup.controllers 2>&1")
    r.sh(j + "ps-by-cpu.txt",
         "ps -eo pid,ppid,user,pcpu,pmem,rss,vsz,nlwp,stat,etimes,comm,args --sort=-pcpu "
         "| head -120")
    r.sh(j + "ps-by-rss.txt",
         "ps -eo pid,ppid,user,pcpu,pmem,rss,vsz,nlwp,stat,etimes,comm,args --sort=-rss "
         "| head -120")
    r.sh(j + "ps-dstate.txt",
         "ps -eo pid,user,stat,wchan:32,etimes,comm,args | awk 'NR==1 || $3 ~ /D/'")
    r.sh(j + "top.txt", "top -b -n 1 -w 512 | head -80")
    r.run(j + "vmstat.txt", ["vmstat", "-w", "-t", "2", "15"], timeout=60)
    r.run(j + "mpstat.txt", ["mpstat", "-P", "ALL", "2", "5"], timeout=60)
    r.run(j + "iostat.txt", ["iostat", "-xz", "-t", "2", "5"], timeout=60)
    r.sh(j + "dmesg.txt", "dmesg -T 2>&1 | tail -n 5000")
    r.sh(j + "dmesg-alerts.txt",
         "dmesg -T 2>&1 | grep -iE 'oom|killed process|out of memory|hung task|blocked for"
         "|segfault|i/o error|nvme|ext4|xfs|btrfs|throttl|mce' | tail -n 2000")
    r.sh(j + "journal-kernel-alerts.txt",
         "journalctl -k --no-pager --since %s 2>&1 | grep -iE 'oom|killed process|"
         "out of memory|hung task|blocked for|segfault|i/o error|throttl' | tail -n 3000"
         % shlex.quote(since_to_journal(since)))
    # Every OOM kill of the last 30 days. The cgroup path names the container id, and
    # engine/container-ids.txt maps the id to a name.
    r.sh(j + "journal-oom-kills-30d.txt",
         "journalctl -k --no-pager --since '-30 days' 2>&1 | grep -E "
         "'invoked oom-killer|oom-kill:|Killed process|Memory cgroup out of memory' "
         "| tail -n 20000", timeout=300)
    r.sh(j + "journal-boots.txt", "journalctl --list-boots --no-pager 2>&1 | tail -n 20")
    r.sh(j + "journal-docker.txt",
         "journalctl --no-pager -u docker -u containerd -u podman --since %s 2>&1 "
         "| tail -n 5000" % shlex.quote(since_to_journal(since)))
    r.sh(j + "oom-daemons.txt",
         "for s in nohang nohang-desktop earlyoom systemd-oomd oomd; do "
         "echo \"== $s\"; systemctl is-active $s 2>&1; done; echo; "
         "ps -eo pid,user,args | grep -E 'nohang|earlyoom|oomd' | grep -v grep")
    r.sh(j + "journal-oom-daemons.txt",
         "journalctl --no-pager -u nohang -u nohang-desktop -u earlyoom -u systemd-oomd "
         "--since %s 2>&1 | tail -n 3000" % shlex.quote(since_to_journal(since)))
    r.sh(j + "services-running.txt",
         "systemctl list-units --type=service --state=running --no-pager 2>&1")
    r.sh(j + "services-failed.txt", "systemctl --failed --no-pager 2>&1")
    r.run(j + "nvidia-smi.txt", ["nvidia-smi"])
    r.sh(j + "sockets-summary.txt", "ss -s 2>&1")
    r.sh(j + "python.txt", "command -v python3; python3 --version")


def since_to_journal(since):
    m = re.fullmatch(r"(\d+)([smhd])", since)
    if not m:
        return since
    unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[m.group(2)]
    return "-%s %s" % (m.group(1), unit)


# --------------------------------------------------------------------------------------
# Repository and configuration
# --------------------------------------------------------------------------------------

def collect_repo(r, repo, engine):
    j = "repo/"
    for name in ("hoover4.ini", "hoover4.ini.release", "hoover4.ini.development"):
        r.copy_file(j + name, repo / name)
    r.copy_file(j + "main_services.env", repo / "main_services/ops/docker/.env")
    r.copy_file(j + "ai_services.env", repo / "ai_services/.env")
    r.copy_file(j + "nginx-proxy.conf", repo / "main_services/ops/docker/nginx-proxy.conf")
    dyn = repo / "main_services/ops/docker/temporal-dynamicconfig"
    if dyn.is_dir():
        for f in sorted(dyn.iterdir()):
            if f.is_file():
                r.copy_file(j + "temporal-dynamicconfig/" + f.name, f, redact=False)
    git = ["git", "-C", str(repo)]
    r.run(j + "git-head.txt", git + ["log", "-1", "--format=%H %ci %s"])
    r.run(j + "git-branch.txt", git + ["branch", "-vv"])
    r.run(j + "git-log.txt", git + ["log", "--oneline", "-40"])
    r.run(j + "git-status.txt", git + ["status", "--short", "--untracked-files=normal"])
    r.run(j + "git-diff-stat.txt", git + ["diff", "--stat", "HEAD"])
    r.run(j + "git-diff.txt", git + ["diff", "HEAD"], max_bytes=8 * 1024 * 1024)
    r.run(j + "git-remote.txt", git + ["remote", "-v"])
    py = sys.executable or "python3"
    for side, extra in (("main", []), ("ai", ["--ai-services"])):
        r.run(j + "deploy-print-env-%s.txt" % side,
              [py, str(repo / "deploy.py"), "--print-env"] + extra, timeout=60)
        cmd = r.run(j + "deploy-print-command-%s.txt" % side,
                    [py, str(repo / "deploy.py"), "--print-command"] + extra,
                    timeout=60, capture=True)
        if not cmd:
            continue
        first = cmd.strip().splitlines()[0] if cmd.strip() else ""
        files = re.findall(r"-f (\S+)", first)
        if files and engine:
            argv = [engine, "compose"]
            for f in files:
                argv += ["-f", f]
            text = r.run(None, argv + ["config"], timeout=90, capture=True)
            if text is not None:
                r.write_text(j + "compose-config-%s.yaml" % side, r.redact_text(text))
    # The redaction above works on single lines. This loop applies the same redaction to
    # the print-env output.
    for side in ("main", "ai"):
        p = r.root / (j + "deploy-print-env-%s.txt" % side)
        if p.exists():
            p.write_text(r.redact_text(p.read_text(errors="replace")))


# --------------------------------------------------------------------------------------
# Container engine
# --------------------------------------------------------------------------------------

def list_containers(r, engine):
    ids = r.run("engine/ps-ids.txt", [engine, "ps", "-a", "-q", "--no-trunc"], capture=True)
    ids = (ids or "").split()
    if not ids:
        return []
    text = r.run(None, [engine, "inspect"] + ids, timeout=120, capture=True)
    try:
        data = json.loads(text or "[]")
    except json.JSONDecodeError:
        r.note("could not parse `%s inspect` output" % engine)
        return []
    return data


def container_name(c):
    return (c.get("Name") or "").lstrip("/")


def container_labels(c):
    return (c.get("Config") or {}).get("Labels") or {}


def is_ours(c):
    name = container_name(c)
    project = container_labels(c).get("com.docker.compose.project", "")
    return (project in PROJECTS or name.startswith("hoover4") or name in KNOWN_NAMES
            or name.startswith("hoover4_"))


def redact_inspect(r, c):
    if not r.redact_on:
        return c
    c = json.loads(json.dumps(c))
    cfg = c.get("Config") or {}
    env = cfg.get("Env") or []
    cfg["Env"] = [r.redact_line(e) for e in env]
    return c


def container_summary(c):
    st = c.get("State") or {}
    hc = c.get("HostConfig") or {}
    health = (st.get("Health") or {})
    return {
        "name": container_name(c),
        "image": (c.get("Config") or {}).get("Image"),
        "project": container_labels(c).get("com.docker.compose.project"),
        "status": st.get("Status"),
        "running": st.get("Running"),
        "restarting": st.get("Restarting"),
        "oom_killed": st.get("OOMKilled"),
        "exit_code": st.get("ExitCode"),
        "error": st.get("Error"),
        "started_at": st.get("StartedAt"),
        "finished_at": st.get("FinishedAt"),
        "restart_count": c.get("RestartCount"),
        "health": health.get("Status"),
        "health_failing_streak": health.get("FailingStreak"),
        "memory_limit": hc.get("Memory"),
        "memory_swap": hc.get("MemorySwap"),
        "nano_cpus": hc.get("NanoCpus"),
        "cpu_quota": hc.get("CpuQuota"),
        "cpuset": hc.get("CpusetCpus"),
        "cap_add": hc.get("CapAdd"),
        "security_opt": hc.get("SecurityOpt"),
        "privileged": hc.get("Privileged"),
        "restart_policy": (hc.get("RestartPolicy") or {}).get("Name"),
        "ulimits": hc.get("Ulimits"),
        "pids_limit": hc.get("PidsLimit"),
        "shm_size": hc.get("ShmSize"),
    }


def collect_engine(r, engine):
    j = "engine/"
    r.run(j + "version.txt", [engine, "version"])
    r.run(j + "info.txt", [engine, "info"])
    r.run(j + "info.json", [engine, "info", "--format", "{{json .}}"])
    r.run(j + "compose-version.txt", [engine, "compose", "version"])
    r.run(j + "ps-all.txt", [engine, "ps", "-a", "--no-trunc", "--format",
                             "table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.CreatedAt}}"])
    r.run(j + "system-df.txt", [engine, "system", "df"], timeout=180)
    r.run(j + "volumes.txt", [engine, "volume", "ls"])
    r.run(j + "networks.txt", [engine, "network", "ls"])
    r.run(j + "images.txt", [engine, "images", "--no-trunc", "--digests"])
    # Lifecycle events only. `exec_die` from health checks and from this script fills
    # the unfiltered stream.
    r.run(j + "events-7d.txt", [engine, "events", "--since", "168h", "--until", "0s",
                                "--filter", "type=container", "--filter", "event=start",
                                "--filter", "event=die", "--filter", "event=oom",
                                "--filter", "event=kill", "--filter", "event=restart",
                                "--filter", "event=health_status", "--format",
                                "{{json .}}"],
          timeout=120)
    r.run(j + "container-ids.txt", [engine, "ps", "-a", "--no-trunc", "--format",
                                    "{{.ID}} {{.Names}}"], timeout=60)
    for i in range(3):
        r.run(j + "stats-%d.txt" % i,
              [engine, "stats", "--no-stream", "--no-trunc", "--format",
               "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}"
               "\t{{.BlockIO}}\t{{.PIDs}}"], timeout=90)
        if i < 2:
            time.sleep(5)


def _read_kv(path):
    out = {}
    try:
        with open(path) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    out[parts[0]] = int(parts[1])
    except (OSError, ValueError):
        pass
    return out


def _read_int(path):
    try:
        with open(path) as f:
            v = f.read().strip()
        return None if v == "max" else int(v)
    except (OSError, ValueError):
        return None


def _net_bytes(pid):
    rx = tx = 0
    try:
        with open("/proc/%d/net/dev" % pid) as f:
            for line in f.readlines()[2:]:
                name, data = line.split(":", 1)
                if name.strip() == "lo":
                    continue
                v = data.split()
                rx += int(v[0])
                tx += int(v[8])
    except (OSError, ValueError, IndexError):
        return None, None
    return rx, tx


def collect_timeseries(r, containers, seconds, interval):
    """Sample CPU, throttling, memory and network per container, from the host.

    The container's main PID gives its cgroup path and its network namespace. Reading
    them from the host adds no process inside a container that may be near its limit.
    """
    j = "timeseries/"
    targets = {}
    for c in containers:
        st = c.get("State") or {}
        pid = st.get("Pid") or 0
        if not st.get("Running") or not pid:
            continue
        try:
            with open("/proc/%d/cgroup" % pid) as f:
                rel = [l.strip().split(":", 2)[2] for l in f if l.startswith("0::")]
        except OSError:
            continue
        if rel:
            targets[container_name(c)] = (pid, "/sys/fs/cgroup" + rel[0])
    if not targets:
        r.note("timeseries: the host can read no cgroup v2 path, so this section is skipped")
        return
    samples = []
    end = time.time() + seconds
    while True:
        now = time.time()
        row = {"t": round(now, 2)}
        with open("/proc/loadavg") as f:
            row["loadavg"] = f.read().split()[:3]
        with open("/proc/stat") as f:
            row["host_cpu"] = [int(x) for x in f.readline().split()[1:]]
        mem = _read_kv("/proc/meminfo")
        row["host_mem_available_kb"] = mem.get("MemAvailable:")
        per = {}
        for name, (pid, cg) in targets.items():
            cpu = _read_kv(cg + "/cpu.stat")
            ev = _read_kv(cg + "/memory.events")
            rx, tx = _net_bytes(pid)
            per[name] = {"usage_usec": cpu.get("usage_usec"),
                         "nr_periods": cpu.get("nr_periods"),
                         "nr_throttled": cpu.get("nr_throttled"),
                         "throttled_usec": cpu.get("throttled_usec"),
                         "mem": _read_int(cg + "/memory.current"),
                         "mem_max": _read_int(cg + "/memory.max"),
                         "oom_kill": ev.get("oom_kill"), "mem_high_events": ev.get("high"),
                         "mem_max_events": ev.get("max"), "rx": rx, "tx": tx}
        row["containers"] = per
        samples.append(row)
        if now >= end:
            break
        time.sleep(interval)
    with open(r.path(j + "samples.jsonl"), "w") as f:
        for s in samples:
            f.write(json.dumps(s) + "\n")
    first, last = samples[0], samples[-1]
    span = max(1e-6, last["t"] - first["t"])
    summary = {"seconds": round(span, 1), "samples": len(samples), "containers": {}}
    for name in targets:
        a, b = first["containers"].get(name, {}), last["containers"].get(name, {})

        def delta(k):
            if a.get(k) is None or b.get(k) is None:
                return None
            return b[k] - a[k]
        periods = delta("nr_periods")
        mems = [s["containers"][name]["mem"] for s in samples
                if s["containers"].get(name, {}).get("mem") is not None]
        summary["containers"][name] = {
            "cpu_cores_avg": None if delta("usage_usec") is None
            else round(delta("usage_usec") / 1e6 / span, 2),
            "throttled_fraction": None if not periods
            else round((delta("nr_throttled") or 0) / periods, 3),
            "mem_max_seen_mb": round(max(mems) / 2**20) if mems else None,
            "mem_limit_mb": None if b.get("mem_max") is None else round(b["mem_max"] / 2**20),
            "oom_kills_in_window": delta("oom_kill"),
            "oom_kills_total": b.get("oom_kill"),
            "rx_mb_per_s": None if delta("rx") is None else round(delta("rx") / 2**20 / span, 2),
            "tx_mb_per_s": None if delta("tx") is None else round(delta("tx") / 2**20 / span, 2)}
    r.write_json(j + "summary.json", summary)


def collect_container(r, engine, c, since, tail):
    name = container_name(c)
    d = "containers/%s/" % name
    r.write_json(d + "inspect.json", redact_inspect(r, c))
    r.write_json(d + "summary.json", container_summary(c))
    r.run("logs/%s.log" % name,
          [engine, "logs", "--timestamps", "--since", since, "--tail", str(tail), name],
          timeout=300, max_bytes=400 * 1024 * 1024, merge=True)
    if not (c.get("State") or {}).get("Running"):
        return
    ex = [engine, "exec", name]
    r.run(d + "ps.txt", ex + ["sh", "-c",
          "ps aux 2>/dev/null || for p in /proc/[0-9]*; do "
          "printf '%s ' \"${p#/proc/}\"; tr '\\0' ' ' < $p/cmdline; echo; done"],
          timeout=30)
    r.run(d + "proc1-status.txt", ex + ["cat", "/proc/1/status"], timeout=30)
    r.run(d + "cgroup.txt", ex + ["sh", "-c",
          "cd /sys/fs/cgroup 2>/dev/null && for f in memory.max memory.current memory.peak "
          "memory.swap.max memory.swap.current memory.events memory.pressure cpu.max "
          "cpu.stat cpu.pressure io.pressure pids.current pids.max; do "
          "[ -f $f ] && { echo \"== $f\"; cat $f; }; done; "
          "[ -f memory.stat ] && { echo '== memory.stat'; head -40 memory.stat; }"],
          timeout=30)
    r.run(d + "nproc.txt", ex + ["sh", "-c", "nproc; cat /proc/loadavg"], timeout=30)


# --------------------------------------------------------------------------------------
# Temporal
# --------------------------------------------------------------------------------------

def temporal(r, name, args, timeout=120, capture=False, max_bytes=64 * 1024 * 1024):
    return r.run(name, [r.engine, "exec", "temporal", "temporal"] + args
                 + ["--address", TEMPORAL_ADDR],
                 timeout=timeout, capture=capture, max_bytes=max_bytes)


def queues_from_source(repo):
    found = set(BASE_QUEUES)
    src = repo / "main_services" / "processing"
    if not src.is_dir():
        return sorted(found)
    pat = re.compile(r"""["']([a-z0-9][a-z0-9\-]*-queue)["']""")
    for root, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x not in (".venv", "__pycache__", "tests", "node_modules")]
        for f in files:
            if f.endswith(".py"):
                try:
                    found.update(pat.findall(Path(root, f).read_text(errors="replace")))
                except OSError:
                    pass
    return sorted(found)


def parse_json_lines(text):
    """The CLI prints one JSON value, or one JSON object per line. Accept both."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        v = json.loads(text)
        return v if isinstance(v, list) else [v]
    except json.JSONDecodeError:
        pass
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def dig(obj, *keys):
    for k in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def collect_temporal(r, repo, max_describe, max_histories, history_bytes):
    j = "temporal/"
    ex = [r.engine, "exec", "temporal"]
    # Health and latency, sampled over about 30 seconds. "shard status unknown" is a
    # history-service state that comes and goes, so one sample is not enough.
    samples = []
    for i in range(10):
        t0 = time.time()
        out = temporal(r, None, ["operator", "cluster", "health"], timeout=30, capture=True)
        t1 = time.time()
        lst = temporal(r, None, ["workflow", "list", "--limit", "1"], timeout=30,
                       capture=True)
        t2 = time.time()
        samples.append({"at": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z",
                        "health": (out or "").strip()[:200], "health_s": round(t1 - t0, 3),
                        "list_ok": lst is not None and "error" not in (lst or "").lower(),
                        "list_s": round(t2 - t1, 3)})
        time.sleep(2)
    r.write_json(j + "health-samples.json", samples)
    # These read Cassandra directly and fail while it restarts. Try three times.
    for name, args in (
            ("cluster-describe.json", ["operator", "cluster", "describe", "-o", "json"]),
            ("cluster-system.json", ["operator", "cluster", "system", "-o", "json"]),
            ("namespace-list.json", ["operator", "namespace", "list", "-o", "json"]),
            ("namespace-default.json",
             ["operator", "namespace", "describe", "-n", "default", "-o", "json"])):
        for attempt in range(3):
            out = temporal(r, j + name, args, capture=True)
            if out and out.strip():
                break
            time.sleep(20)
    temporal(r, j + "search-attributes.txt", ["operator", "search-attribute", "list"])
    r.run(j + "tctl-admin-cluster-describe.json",
          ex + ["tctl", "--address", TEMPORAL_ADDR, "admin", "cluster", "describe"],
          timeout=60)
    r.run(j + "server-config.yaml", ex + ["sh", "-c",
          "cat /etc/temporal/config/docker.yaml 2>/dev/null"], timeout=30)
    r.run(j + "dynamicconfig-in-container.txt", ex + ["sh", "-c",
          "ls -la /etc/temporal/config/dynamicconfig/ && "
          "cat /etc/temporal/config/dynamicconfig/*"], timeout=30)

    counts = {}
    for status in ("Running", "Completed", "Failed", "Terminated", "Canceled", "TimedOut",
                   "ContinuedAsNew"):
        out = temporal(r, None, ["workflow", "count", "--query",
                                 'ExecutionStatus="%s"' % status], timeout=90, capture=True)
        counts[status] = (out or "").strip()
    out = temporal(r, None, ["workflow", "count"], timeout=90, capture=True)
    counts["all"] = (out or "").strip()
    r.write_json(j + "workflow-counts.json", counts)

    running_text = temporal(r, j + "workflows-running.json",
                            ["workflow", "list", "--query", 'ExecutionStatus="Running"',
                             "--limit", "20000", "-o", "json"],
                            timeout=300, capture=True, max_bytes=200 * 1024 * 1024)
    running = parse_json_lines(running_text)
    for status in ("Failed", "Terminated", "TimedOut", "Canceled"):
        temporal(r, j + "workflows-%s.json" % status.lower(),
                 ["workflow", "list", "--query",
                  'ExecutionStatus="%s" AND CloseTime > "%s"' % (
                      status, (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(days=7))
                      .strftime("%Y-%m-%dT%H:%M:%SZ")),
                  "--limit", "2000", "-o", "json"], timeout=300)

    by_type = Counter()
    by_queue = Counter()
    oldest = {}
    for w in running:
        wtype = dig(w, "type", "name") or "?"
        by_type[wtype] += 1
        by_queue[w.get("taskQueue") or "?"] += 1
        st = w.get("startTime") or ""
        if wtype not in oldest or st < oldest[wtype]:
            oldest[wtype] = st
    r.write_json(j + "running-summary.json", {
        "running_listed": len(running), "by_type": dict(by_type.most_common()),
        "by_task_queue": dict(by_queue.most_common()), "oldest_start_by_type": oldest})

    # Describe running workflows. Take them round-robin across types, so that one type with
    # thousands of executions does not hide the others. Inside a type, take the oldest first.
    groups = defaultdict(list)
    for w in sorted(running, key=lambda w: w.get("startTime") or ""):
        groups[dig(w, "type", "name") or "?"].append(w)
    picked = []
    while len(picked) < max_describe and any(groups.values()):
        for k in list(groups):
            if groups[k] and len(picked) < max_describe:
                picked.append(groups[k].pop(0))
    stuck = []
    pending_acts = []
    for w in picked:
        wid = dig(w, "execution", "workflowId")
        rid = dig(w, "execution", "runId")
        if not wid:
            continue
        text = temporal(r, None, ["workflow", "describe", "-w", wid, "-r", rid, "-o", "json"],
                        timeout=60, capture=True)
        try:
            d = json.loads(text or "{}")
        except json.JSONDecodeError:
            continue
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", wid)[:150]
        r.write_json(j + "describe/%s.json" % safe, d)
        pwt = d.get("pendingWorkflowTask") or {}
        info = d.get("workflowExecutionInfo") or {}
        attempt = int(pwt.get("attempt") or 0)
        row = {"workflow_id": wid, "run_id": rid, "type": dig(info, "type", "name"),
               "start": info.get("startTime"), "history_length": info.get("historyLength"),
               "history_size_bytes": info.get("historySizeBytes"),
               "pending_wft_attempt": attempt, "pending_wft_state": pwt.get("state"),
               "pending_wft_scheduled": pwt.get("scheduledTime"),
               "pending_activities": len(d.get("pendingActivities") or []),
               "pending_children": len(d.get("pendingChildren") or [])}
        if attempt > 1:
            stuck.append(row)
        for a in d.get("pendingActivities") or []:
            pending_acts.append({
                "workflow_id": wid, "type": row["type"],
                "activity": dig(a, "activityType", "name"), "state": a.get("state"),
                "attempt": a.get("attempt"), "scheduled": a.get("scheduledTime"),
                "last_started": a.get("lastStartedTime"),
                "last_heartbeat": a.get("lastHeartbeatTime"),
                "last_worker": a.get("lastWorkerIdentity"),
                "last_failure": (dig(a, "lastFailure", "message") or "")[:500]})
    r.write_json(j + "stuck-workflow-tasks.json",
                 sorted(stuck, key=lambda x: -x["pending_wft_attempt"]))
    r.write_json(j + "pending-activities.json", pending_acts)
    r.write_json(j + "described.json", {"described": len(picked), "stuck": len(stuck)})

    # Full histories of the stuck executions with the most workflow task attempts. The
    # failed workflow task and its cause are at the end of the history.
    for row in sorted(stuck, key=lambda x: -x["pending_wft_attempt"])[:max_histories]:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", row["workflow_id"])[:150]
        temporal(r, j + "histories/%s.json" % safe,
                 ["workflow", "show", "-w", row["workflow_id"], "-r", row["run_id"],
                  "-o", "json"], timeout=300, max_bytes=history_bytes)

    for q in queues_from_source(repo):
        for kind in ("workflow", "activity"):
            temporal(r, j + "task-queues/%s-%s.json" % (q, kind),
                     ["task-queue", "describe", "--task-queue", q,
                      "--task-queue-type", kind, "-o", "json"], timeout=60)


FAILING_RUN_RE = re.compile(
    r"Failing workflow task run_id=([0-9a-f-]{36}).*?message: \"([^\"]{0,200})\"")


def collect_failing_runs(r, max_runs, history_bytes):
    """Describe the executions whose workflow tasks the worker logs name as failing.

    The worker log names only a run id. Visibility finds the workflow id and type from it.
    This runs after the container logs are written, because it reads them.
    """
    j = "temporal/failing-runs/"
    per_run = Counter()
    reason = {}
    for log in ("hoover4-worker.log", "hoover4-ops.log"):
        p = r.root / "logs" / log
        if not p.exists():
            continue
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if "Failing workflow task" not in line:
                    continue
                m = FAILING_RUN_RE.search(ANSI_RE.sub("", line))
                if m:
                    per_run[m.group(1)] += 1
                    reason.setdefault(m.group(1), m.group(2))
    rows = []
    for run_id, n in per_run.most_common(max_runs):
        text = temporal(r, None, ["workflow", "list", "--query", 'RunId="%s"' % run_id,
                                  "--limit", "1", "-o", "json"], timeout=60, capture=True)
        found = parse_json_lines(text)
        row = {"run_id": run_id, "log_lines": n, "reason": reason.get(run_id)}
        if found:
            w = found[0]
            row.update({"workflow_id": dig(w, "execution", "workflowId"),
                        "type": dig(w, "type", "name"), "status": w.get("status"),
                        "start": w.get("startTime"), "close": w.get("closeTime"),
                        "history_length": w.get("historyLength"),
                        "history_size_bytes": w.get("historySizeBytes"),
                        "task_queue": w.get("taskQueue")})
            if row["workflow_id"]:
                safe = re.sub(r"[^A-Za-z0-9_.-]", "_", row["workflow_id"])[:150]
                temporal(r, j + "describe-%s.json" % safe,
                         ["workflow", "describe", "-w", row["workflow_id"], "-r", run_id,
                          "-o", "json"], timeout=60)
        rows.append(row)
    by_type = Counter(row.get("type") or "?" for row in rows)
    r.write_json(j + "summary.json", {"distinct_runs_in_logs": len(per_run),
                                      "by_type": dict(by_type.most_common()), "runs": rows})
    # One full history per workflow type, so the command that grows too large is visible.
    seen = set()
    for row in rows:
        if not row.get("workflow_id") or row.get("type") in seen:
            continue
        seen.add(row.get("type"))
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", row["workflow_id"])[:150]
        temporal(r, j + "history-%s.json" % safe,
                 ["workflow", "show", "-w", row["workflow_id"], "-r", row["run_id"],
                  "-o", "json"], timeout=300, max_bytes=history_bytes)


# --------------------------------------------------------------------------------------
# Cassandra, Elasticsearch
# --------------------------------------------------------------------------------------

def collect_cassandra(r):
    j = "cassandra/"
    ex = [r.engine, "exec", "temporal-cassandra"]
    # The kernel can kill Cassandra while this report runs. `nodetool` then fails on a
    # closed JMX port. Wait until JMX answers, and run a failed command once more.
    waited = []
    deadline = time.time() + 240
    while time.time() < deadline:
        t0 = time.time()
        out = r.run(None, ex + ["nodetool", "statusbinary"], timeout=60, capture=True)
        waited.append({"at": time.time(), "seconds": round(time.time() - t0, 2),
                       "output": (out or "").strip()[:80]})
        if out and "running" in out:
            break
        time.sleep(10)
    r.write_json(j + "readiness.json", waited)

    def nodetool(name, args, timeout=120):
        for attempt in range(2):
            out = r.run(j + name, ex + ["nodetool"] + args, timeout=timeout, capture=True)
            if out and out.strip():
                return
            time.sleep(20)

    for cmd in ("status", "info", "tpstats", "compactionstats", "gcstats", "proxyhistograms",
                "describecluster", "netstats", "getcompactionthroughput",
                "getconcurrentcompactors", "statusgossip", "statusbinary"):
        nodetool("nodetool-%s.txt" % cmd, [cmd])
    nodetool("nodetool-tablestats-temporal.txt", ["tablestats", "temporal"], timeout=180)
    for table in ("executions", "history_node", "history_tree", "tasks",
                  "cluster_membership"):
        nodetool("nodetool-tablehistograms-%s.txt" % table,
                 ["tablehistograms", "temporal", table])
    # Where the memory goes. The kernel kills the JVM at the container limit, so the
    # heap setting alone does not answer the question.
    r.run(j + "memory.txt", ex + ["sh", "-c",
          "for p in /proc/[0-9]*; do c=$(tr '\\0' ' ' < $p/cmdline 2>/dev/null); "
          "case \"$c\" in *CassandraDaemon*) echo \"== $p\"; "
          "grep -E 'VmRSS|RssAnon|RssFile|RssShmem|VmSwap|Threads' $p/status; "
          "echo '-- smaps_rollup'; cat $p/smaps_rollup 2>/dev/null; "
          "echo '-- memory flags'; echo \"$c\" | tr ' ' '\\n' | "
          "grep -E '^-X(mx|ms|mn|ss)|MaxDirectMemorySize|MaxMetaspace|UseNUMA|Heap|GC' ;; "
          "esac; done; echo '== cgroup memory.stat'; cat /sys/fs/cgroup/memory.stat; "
          "echo '== cgroup memory.events'; cat /sys/fs/cgroup/memory.events; "
          "echo '== memtable and cache settings'; grep -E "
          "'^(memtable_|key_cache|row_cache|counter_cache|file_cache|buffer_pool|"
          "native_transport_max|concurrent_)' /etc/cassandra/cassandra.yaml; "
          "echo '== heap dumps'; ls -la /var/lib/cassandra/*.hprof /*.hprof "
          "/opt/cassandra/*.hprof 2>&1 | head"], timeout=60)
    r.run(j + "log-system.txt", ex + ["sh", "-c",
          "tail -n 60000 /var/log/cassandra/system.log"], timeout=120,
          max_bytes=200 * 1024 * 1024)
    r.run(j + "log-debug.txt", ex + ["sh", "-c",
          "tail -n 60000 /var/log/cassandra/debug.log"], timeout=120,
          max_bytes=200 * 1024 * 1024)
    r.run(j + "log-gc.txt", ex + ["sh", "-c",
          "ls -la /var/log/cassandra/; f=$(ls -t /var/log/cassandra/gc.log* 2>/dev/null "
          "| head -1); [ -n \"$f\" ] && tail -n 30000 \"$f\""], timeout=120,
          max_bytes=100 * 1024 * 1024)
    r.run(j + "data-du.txt", ex + ["sh", "-c",
          "du -sh /var/lib/cassandra/* /var/lib/cassandra/data/* 2>&1; df -h /var/lib/cassandra"],
          timeout=180)
    r.run(j + "numa.txt", ex + ["sh", "-c",
          "echo '== numactl --show'; numactl --show 2>&1; "
          "echo '== numactl --interleave=all true'; numactl --interleave=all true; "
          "echo \"exit=$?\"; echo '== NUMA in jvm options and env'; "
          "grep -rn -i numa /etc/cassandra/ /opt/cassandra/bin/cassandra 2>/dev/null | head -40; "
          "echo '== pid 1 cmdline'; tr '\\0' ' ' < /proc/1/cmdline; echo; "
          "echo '== java cmdline'; for p in /proc/[0-9]*; do "
          "c=$(tr '\\0' ' ' < $p/cmdline 2>/dev/null); case \"$c\" in *java*) echo \"$p: $c\";; "
          "esac; done; echo '== capabilities of pid 1'; grep -i cap /proc/1/status"],
          timeout=60)
    r.run(j + "config.txt", ex + ["sh", "-c",
          "grep -vE '^\\s*(#|$)' /etc/cassandra/cassandra.yaml; echo '== jvm.options'; "
          "grep -vE '^\\s*(#|$)' /etc/cassandra/jvm.options 2>/dev/null"], timeout=60)


def collect_elasticsearch(r):
    j = "elasticsearch/"
    ex = [r.engine, "exec", "temporal-elasticsearch", "curl", "-sS", "--max-time", "60"]
    for name, path in (("cluster-health", "_cluster/health?pretty"),
                       ("cat-indices", "_cat/indices?v&s=index"),
                       ("cat-thread-pool", "_cat/thread_pool?v"),
                       ("cat-pending-tasks", "_cat/pending_tasks?v"),
                       ("cat-allocation", "_cat/allocation?v"),
                       ("nodes-stats", "_nodes/stats/jvm,os,process,fs,thread_pool,indices"
                                       "?pretty")):
        r.run(j + name + ".txt", ex + ["http://localhost:9200/" + path], timeout=90)


# --------------------------------------------------------------------------------------
# ClickHouse
# --------------------------------------------------------------------------------------

def ch(r, name, query, timeout=180, fmt="TSVWithNames", capture=False):
    argv = [r.engine, "exec", "-i", "clickhouse", "sh", "-c",
            'clickhouse-client -u "${CLICKHOUSE_USER:-default}" '
            '--password "${CLICKHOUSE_PASSWORD:-}" --format "$1" --query "$2"',
            "_", fmt, query]
    return r.run(name, argv, timeout=timeout, capture=capture)


def collect_clickhouse(r, since_hours):
    j = "clickhouse/"
    h = int(since_hours)
    ch(r, j + "version.tsv", "SELECT version(), uptime()")
    ch(r, j + "disks.tsv", "SELECT name, path, formatReadableSize(free_space) free, "
       "formatReadableSize(total_space) total FROM system.disks")
    ch(r, j + "server-settings-changed.tsv",
       "SELECT name, value FROM system.server_settings WHERE changed")
    ch(r, j + "tables.tsv",
       "SELECT database, table, sum(rows) rows, count() parts, "
       "formatReadableSize(sum(bytes_on_disk)) size, sum(bytes_on_disk) bytes "
       "FROM system.parts WHERE active GROUP BY database, table ORDER BY bytes DESC")
    ch(r, j + "processes.tsv",
       "SELECT elapsed, query_id, user, read_rows, memory_usage, substring(query,1,2000) q "
       "FROM system.processes ORDER BY elapsed DESC")
    ch(r, j + "merges.tsv", "SELECT * FROM system.merges")
    ch(r, j + "mutations-pending.tsv", "SELECT * FROM system.mutations WHERE NOT is_done")
    ch(r, j + "errors.tsv",
       "SELECT name, code, value, last_error_time, substring(last_error_message,1,1000) msg "
       "FROM system.errors ORDER BY last_error_time DESC LIMIT 300")
    ch(r, j + "metrics.tsv", "SELECT metric, value FROM system.metrics")
    ch(r, j + "async-metrics.tsv",
       "SELECT metric, value FROM system.asynchronous_metrics WHERE metric LIKE 'OS%' "
       "OR metric LIKE 'Memory%' OR metric LIKE 'Load%' OR metric LIKE 'CGroup%' "
       "ORDER BY metric")
    ch(r, j + "crash-log.tsv", "SELECT * FROM system.crash_log ORDER BY event_time DESC "
       "LIMIT 50")
    ch(r, j + "query-exceptions.tsv",
       "SELECT exception_code, count() n, max(event_time) last, "
       "substring(any(exception),1,1500) ex, substring(any(query),1,800) q "
       "FROM system.query_log WHERE type IN ('ExceptionBeforeStart','ExceptionWhileProcessing') "
       "AND event_time > now() - INTERVAL %d HOUR GROUP BY exception_code, "
       "normalized_query_hash ORDER BY n DESC LIMIT 200" % h, timeout=300)
    ch(r, j + "query-slowest.tsv",
       "SELECT count() n, round(avg(query_duration_ms)) avg_ms, max(query_duration_ms) max_ms, "
       "formatReadableSize(sum(read_bytes)) read, formatReadableSize(max(memory_usage)) mem, "
       "substring(any(query),1,800) q FROM system.query_log WHERE type='QueryFinish' "
       "AND event_time > now() - INTERVAL 24 HOUR GROUP BY normalized_query_hash "
       "ORDER BY sum(query_duration_ms) DESC LIMIT 60", timeout=300)
    ch(r, j + "query-per-hour.tsv",
       "SELECT toStartOfHour(event_time) hr, countIf(type='QueryFinish') ok, "
       "countIf(type!='QueryFinish' AND type!='QueryStart') failed, "
       "round(avgIf(query_duration_ms, type='QueryFinish')) avg_ms "
       "FROM system.query_log WHERE event_time > now() - INTERVAL %d HOUR "
       "GROUP BY hr ORDER BY hr" % h, timeout=300)

    p = "Hoover4_Processing."
    ch(r, j + "collections.tsv", "SELECT * FROM %scollections FINAL" % p)
    ch(r, j + "datasets.tsv", "SELECT * FROM %sdataset FINAL" % p)
    ch(r, j + "operations.tsv",
       "SELECT * FROM %soperations FINAL ORDER BY started_at DESC LIMIT 1000" % p)
    ch(r, j + "operation-failures.tsv",
       "SELECT op_id, node_index, depth, error_class, error_type, "
       "substring(message,1,2000) message, substring(stack_trace,1,4000) stack_trace, "
       "signature, task_name, workflow_id, activity_id, attempt, collectionname, "
       "collection_dataset, stage, source, captured_at FROM %soperation_failures "
       "ORDER BY captured_at DESC LIMIT 3000" % p)
    ch(r, j + "task-runs-by-task.tsv",
       "SELECT task_queue, task_name, outcome, count() n, "
       "round(quantile(0.5)(run_time_ms)) p50_ms, round(quantile(0.95)(run_time_ms)) p95_ms, "
       "round(quantile(0.99)(run_time_ms)) p99_ms, max(run_time_ms) max_ms, "
       "round(quantile(0.5)(schedule_to_start_ms)) s2s_p50_ms, "
       "round(quantile(0.95)(schedule_to_start_ms)) s2s_p95_ms, max(attempt) max_attempt, "
       "sum(run_time_ms) total_ms FROM %sprocessing_task_runs "
       "WHERE started_at > now() - INTERVAL %d HOUR "
       "GROUP BY task_queue, task_name, outcome ORDER BY total_ms DESC" % (p, h), timeout=300)
    ch(r, j + "task-runs-per-10min.tsv",
       "SELECT toStartOfTenMinutes(started_at) t, task_queue, outcome, count() n, "
       "round(avg(run_time_ms)) avg_ms, round(avg(schedule_to_start_ms)) s2s_avg_ms, "
       "sum(run_time_ms) busy_ms FROM %sprocessing_task_runs "
       "WHERE started_at > now() - INTERVAL %d HOUR "
       "GROUP BY t, task_queue, outcome ORDER BY t, task_queue, outcome" % (p, h),
       timeout=300)
    ch(r, j + "task-runs-by-worker.tsv",
       "SELECT worker_id, task_queue, count() n, sum(run_time_ms) busy_ms, "
       "min(started_at) first, max(started_at) last FROM %sprocessing_task_runs "
       "WHERE started_at > now() - INTERVAL 24 HOUR GROUP BY worker_id, task_queue "
       "ORDER BY worker_id, task_queue" % p, timeout=300)
    ch(r, j + "task-runs-last-per-queue.tsv",
       "SELECT task_queue, max(started_at) last_start, count() n_total "
       "FROM %sprocessing_task_runs GROUP BY task_queue" % p, timeout=300)
    ch(r, j + "queue-backlog.tsv",
       "SELECT * FROM %sprocessing_queue_backlog WHERE sampled_at > now() - INTERVAL %d HOUR "
       "ORDER BY sampled_at DESC LIMIT 60000" % (p, h), timeout=300)
    ch(r, j + "eta-samples.tsv",
       "SELECT * FROM %sprocessing_eta_samples WHERE sampled_at > now() - INTERVAL 24 HOUR "
       "ORDER BY sampled_at DESC LIMIT 30000" % p, timeout=300)

    # What each recent operation ran, and when it stopped. Temporal forgets a closed
    # workflow after its retention, and Docker rotates the logs, so these rows can be the
    # only record of an operation that stalled days ago.
    ch(r, j + "operation-task-runs.tsv",
       "SELECT o.op_id, o.state, o.started_at, countIf(t.op_id != '') runs, min(t.started_at) first, "
       "max(t.started_at) last, groupUniqArray(20)(t.task_name) tasks, "
       "countIf(t.outcome != 'ok' AND t.op_id != '') not_ok FROM (SELECT op_id, state, "
       "started_at FROM %soperations FINAL WHERE started_at > now() - INTERVAL 30 DAY) o "
       "LEFT JOIN %sprocessing_task_runs t ON t.op_id = o.op_id "
       "GROUP BY o.op_id, o.state, o.started_at ORDER BY o.started_at DESC" % (p, p),
       timeout=300)
    dbs = ch(r, None, "SELECT name FROM system.databases WHERE name LIKE 'Hoover4_Collection_%'",
             fmt="TSV", capture=True)
    for db in (dbs or "").split():
        d = "clickhouse/collections/%s/" % db
        ch(r, d + "errors-by-task.tsv",
           "SELECT collection_dataset, task_name, count() n, uniqExact(hash) docs, "
           "max(timestamp) last, max(attempt) max_attempt, "
           "substring(any(error_logs),1,1500) sample_error FROM %s.processing_errors "
           "GROUP BY collection_dataset, task_name ORDER BY n DESC" % db, timeout=300)
        ch(r, d + "errors-by-identity.tsv",
           "SELECT task_name, error_identity, count() n, uniqExact(hash) docs, "
           "max(timestamp) last, substring(any(error_logs),1,1500) sample_error "
           "FROM %s.processing_errors GROUP BY task_name, error_identity "
           "ORDER BY n DESC LIMIT 300" % db, timeout=300)
        ch(r, d + "errors-latest.tsv",
           "SELECT timestamp, collection_dataset, task_name, hash, attempt, op_id, "
           "substring(error_logs,1,6000) error_logs FROM %s.processing_errors "
           "ORDER BY timestamp DESC LIMIT 400" % db, timeout=300)
        ch(r, d + "document-outcomes.tsv",
           "SELECT collection_dataset, outcome, error_task_name, activity_name, count() n, "
           "max(recorded_at) last FROM %s.processing_document_outcomes "
           "GROUP BY collection_dataset, outcome, error_task_name, activity_name "
           "ORDER BY n DESC" % db, timeout=300)
        ch(r, d + "operation-error-events.tsv",
           "SELECT created_at, op_id, collection_dataset, task_name, event, hash, "
           "substring(error_logs,1,3000) e FROM %s.operation_error_events "
           "ORDER BY created_at DESC LIMIT 400" % db, timeout=300)
        ch(r, d + "inflight-latest.tsv",
           "SELECT * FROM %s.processing_task_inflight "
           "WHERE sampled_at > now() - INTERVAL 6 HOUR ORDER BY sampled_at DESC LIMIT 5000"
           % db, timeout=300)
        ch(r, d + "plans.tsv",
           "SELECT p.collection_dataset, count() plans, sum(length(p.item_hashes)) items, "
           "max(length(p.item_hashes)) max_items, max(p.plan_size_bytes) max_plan_bytes, "
           "sum(p.plan_size_bytes) total_bytes, countIf(f.plan_hash = '') unfinished, "
           "min(p.created_at) first, max(p.created_at) last "
           "FROM %s.processing_plans p LEFT JOIN "
           "(SELECT DISTINCT collection_dataset, plan_hash FROM %s.processing_plan_finished) f "
           "ON p.collection_dataset = f.collection_dataset AND p.plan_hash = f.plan_hash "
           "GROUP BY p.collection_dataset" % (db, db), timeout=300)
        ch(r, d + "operation-task-runs.tsv",
           "SELECT op_id, collection_dataset, count() runs, min(started_at) first, "
           "max(started_at) last, countIf(outcome != 'ok') not_ok, "
           "argMax(task_name, started_at) last_task, groupUniqArray(30)(task_name) tasks "
           "FROM %s.processing_task_runs WHERE started_at > now() - INTERVAL 30 DAY "
           "GROUP BY op_id, collection_dataset ORDER BY last DESC" % db, timeout=300)
        ch(r, d + "task-runs-by-task.tsv",
           "SELECT collection_dataset, task_name, outcome, count() n, "
           "round(quantile(0.5)(run_time_ms)) p50_ms, round(quantile(0.95)(run_time_ms)) p95_ms, "
           "max(run_time_ms) max_ms, max(started_at) last FROM %s.processing_task_runs "
           "WHERE started_at > now() - INTERVAL %d HOUR "
           "GROUP BY collection_dataset, task_name, outcome ORDER BY n DESC" % (db, h),
           timeout=300)


# --------------------------------------------------------------------------------------
# Manticore, Garage, Redis, worker
# --------------------------------------------------------------------------------------

def collect_manticore(r):
    j = "manticore/"
    for name, sql in (("status", "SHOW STATUS"), ("tables", "SHOW TABLES"),
                      ("threads", "SHOW THREADS OPTION format=all"),
                      ("settings", "SHOW SETTINGS"), ("variables", "SHOW VARIABLES")):
        r.run(j + name + ".txt", [r.engine, "exec", "manticore", "mysql", "-h127.0.0.1",
                                  "-P9306", "--protocol=tcp", "-e", sql], timeout=90)
    r.run(j + "searchd-log.txt", [r.engine, "exec", "manticore", "sh", "-c",
          "tail -n 20000 /var/log/manticore/searchd.log 2>&1"], timeout=90)
    r.run(j + "query-log.txt", [r.engine, "exec", "manticore", "sh", "-c",
          "tail -n 5000 /var/log/manticore/query.log 2>&1"], timeout=90)


def collect_garage(r):
    j = "garage/"
    for name, args in (("status", ["status"]), ("stats", ["stats"]),
                       ("layout", ["layout", "show"]), ("buckets", ["bucket", "list"])):
        r.run(j + name + ".txt", [r.engine, "exec", "garage", "/garage"] + args, timeout=90)


def collect_redis(r):
    r.run("redis/info.txt", [r.engine, "exec", "redis", "redis-cli", "info", "all"],
          timeout=60)
    r.run("redis/dbsize.txt", [r.engine, "exec", "redis", "redis-cli", "dbsize"], timeout=60)


def collect_worker(r, name):
    j = "worker/%s/" % name
    ex = [r.engine, "exec", name]
    r.run(j + "ps-tree.txt", ex + ["ps", "-eo",
          "pid,ppid,pcpu,pmem,rss,nlwp,stat,etimes,args", "--forest"], timeout=30)
    r.run(j + "env.txt", ex + ["sh", "-c",
          "env | sort | grep -E '^(HOOVER4_|TEMPORAL|NER_|EMBED|OCR_|PDF_|GPU_|RERANK|S3_ENDPOINT"
          "|CLICKHOUSE_HOST|MANTICORE|TESSERACT|DATASETS)'"], timeout=30)
    r.run(j + "python-packages.txt", ex + ["sh", "-c",
          "cd /app && (uv pip list 2>/dev/null || pip list 2>/dev/null) "
          "| grep -iE 'temporal|clickhouse|protobuf|grpc|httpx|aiohttp'"], timeout=90)
    # Anonymous memory is what the process holds. File memory is page cache that the
    # kernel can take back. The container limit counts both.
    r.run(j + "process-memory.txt", ex + ["sh", "-c",
          "printf '%-8s %-10s %-10s %-10s %-8s %s\\n' PID RSS_KB ANON_KB FILE_KB THREADS CMD; "
          "for p in /proc/[0-9]*; do [ -r $p/status ] || continue; "
          "rss=$(awk '/^VmRSS/{print $2}' $p/status); [ -n \"$rss\" ] || continue; "
          "an=$(awk '/^RssAnon/{print $2}' $p/status); fi=$(awk '/^RssFile/{print $2}' $p/status); "
          "th=$(awk '/^Threads/{print $2}' $p/status); "
          "printf '%-8s %-10s %-10s %-10s %-8s %s\\n' ${p#/proc/} $rss $an $fi $th "
          "\"$(tr '\\0' ' ' < $p/cmdline | cut -c1-160)\"; done | sort -k2 -n -r"],
          timeout=60)
    r.run(j + "cgroup-memory-stat.txt", ex + ["sh", "-c",
          "cat /sys/fs/cgroup/memory.stat /sys/fs/cgroup/memory.events 2>&1"], timeout=30)


LIFETIME_CONTAINERS = ("hoover4-ops", "hoover4-worker", "temporal", "hoover4-website",
                       "temporal-cassandra")
ERROR_WORDS = re.compile(r"Traceback|ERROR|Error|Exception|error=|level\":\"error|"
                         r"failed|FAILED|Killed|OutOfMemory|timed out|Timeout")
# Lines that repeat thousands of times an hour and carry no new fact after the first.
SPAM = re.compile(r"GRPC Message too large|Unspecified task queue kind|mbind: Operation not "
                  r"permitted|Critical attempts processing workflow task|"
                  r"respond_workflow_task_failed retried")
TIMELINE_SIGNATURES = ["GRPC Message too large", "shard status unknown", "Traceback",
                       "OutOfMemory", "history size exceeds", "Persistent store operation",
                       "Critical attempts processing workflow task", "mbind",
                       "context deadline exceeded", "no hosts available", "Heartbeat",
                       "ERROR", "Startup complete"]


def collect_lifetime_logs(r, engine, running_names, max_lines):
    """Read the whole log of each key container once, since the container started.

    Keep the lines that name a recent operation or dataset, and the error lines that are
    not repeats of a known flood. Count every timeline signature per hour of all lines.
    """
    j = "lifetime-logs/"
    text = ch(r, None, "SELECT DISTINCT op_id, collection_dataset FROM "
              "Hoover4_Processing.operations FINAL WHERE started_at > now() - INTERVAL 14 DAY",
              fmt="TSV", capture=True) or ""
    names = set()
    for line in text.splitlines():
        for part in line.split("\t"):
            part = part.strip()
            if len(part) >= 6:
                names.add(part)
    r.write_json(j + "watched-names.json", sorted(names))
    watch = re.compile("|".join(re.escape(n) for n in sorted(names))) if names else None
    timeline = {}
    for name in LIFETIME_CONTAINERS:
        if name not in running_names:
            continue
        hours = defaultdict(Counter)
        kept = 0
        total = 0
        spam_seen = Counter()
        started = time.time()
        try:
            proc = subprocess.Popen([engine, "logs", "--timestamps", name],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL)
            with open(r.path(j + name + ".log"), "w", encoding="utf-8",
                      errors="replace") as out:
                for raw in proc.stdout:
                    total += 1
                    line = ANSI_RE.sub("", raw.decode("utf-8", errors="replace"))
                    hour = line[:13]
                    for s in TIMELINE_SIGNATURES:
                        if s in line:
                            hours[hour][s] += 1
                    if kept >= max_lines:
                        continue
                    if SPAM.search(line):
                        key = normalise(line)
                        spam_seen[key] += 1
                        if spam_seen[key] > 3:
                            continue
                    if (watch is not None and watch.search(line)) or ERROR_WORDS.search(line):
                        out.write(line)
                        kept += 1
            proc.wait(timeout=60)
        except Exception as exc:
            r.note("lifetime log of %s failed: %s" % (name, exc))
        r.record({"file": j + name + ".log", "lines_read": total, "lines_kept": kept,
                  "seconds": round(time.time() - started, 1)})
        timeline[name] = {h: dict(c) for h, c in sorted(hours.items())}
    r.write_json(j + "timeline-per-hour.json", timeline)
    lines = []
    for name, per_hour in timeline.items():
        lines.append("== " + name)
        for h, c in per_hour.items():
            lines.append("  %s  %s" % (h, ", ".join("%s=%d" % kv for kv in
                                                   sorted(c.items(), key=lambda x: -x[1]))))
    r.write_text(j + "timeline-per-hour.txt", "\n".join(lines) + "\n")


# --------------------------------------------------------------------------------------
# Dataset shape
# --------------------------------------------------------------------------------------

# Runs inside the worker container with its own python3. It walks each dataset once and
# reports the folders whose direct entries would make one large scan workflow task.
DATASET_SCAN_CODE = r'''
import json, os, sys, time
paths = json.loads(sys.argv[1]); budget = float(sys.argv[2])
out = {}
for ds, root in paths:
    t0 = time.time(); files = dirs = 0; size = 0; max_path = 0; top = []; timed_out = False
    stack = [root]
    while stack:
        if time.time() - t0 > budget:
            timed_out = True; break
        d = stack.pop()
        nf = nd = 0; path_bytes = 0
        try:
            with os.scandir(d) as it:
                for e in it:
                    rel = e.path[len(root):]
                    path_bytes += len(rel.encode("utf-8", "replace"))
                    max_path = max(max_path, len(rel.encode("utf-8", "replace")))
                    try:
                        if e.is_dir(follow_symlinks=False):
                            nd += 1; stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            nf += 1; size += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError as exc:
            top.append({"dir": d[len(root):] or "/", "error": str(exc)}); continue
        files += nf; dirs += nd
        top.append({"dir": d[len(root):] or "/", "files": nf, "dirs": nd,
                    "path_bytes": path_bytes})
        top = sorted(top, key=lambda x: -x.get("path_bytes", 0))[:40]
    out[ds] = {"root": root, "files": files, "dirs": dirs, "bytes": size,
               "max_path_bytes": max_path, "seconds": round(time.time() - t0, 1),
               "timed_out": timed_out, "largest_folders_by_path_bytes": top}
print(json.dumps(out, indent=1))
'''


def collect_dataset_shape(r, budget_per_dataset):
    text = ch(r, None, "SELECT collection_dataset, dataset_path FROM "
              "Hoover4_Processing.dataset FINAL WHERE is_deleted = 0 AND dataset_type = 'disk'",
              fmt="TSV", capture=True) or ""
    pairs = [l.split("\t", 1) for l in text.splitlines() if "\t" in l]
    if not pairs:
        r.note("dataset shape: no disk datasets found")
        return
    total = int(budget_per_dataset * len(pairs)) + 120
    r.run("datasets/shape.json", [r.engine, "exec", "hoover4-worker", "python3", "-c",
                                  DATASET_SCAN_CODE, json.dumps(pairs),
                                  str(budget_per_dataset)], timeout=total)


# --------------------------------------------------------------------------------------
# Log summaries
# --------------------------------------------------------------------------------------

def normalise(line):
    line = ANSI_RE.sub("", line.rstrip("\n"))
    # `docker logs --timestamps` puts an RFC3339 stamp first.
    line = re.sub(r"^\d{4}-\d{2}-\d{2}T\S+\s", "", line, count=1)
    s = line.strip()
    if s.startswith("{") and s.endswith("}"):
        try:
            obj = json.loads(s)
            parts = [str(obj.get(k, "")) for k in ("level", "msg", "error", "service",
                                                     "component", "operation")
                     if obj.get(k)]
            if parts:
                s = " | ".join(parts)
        except json.JSONDecodeError:
            pass
    s = TS_RE.sub("<ts>", s)
    s = UUID_RE.sub("<uuid>", s)
    s = HEX_RE.sub("<hex>", s)
    s = NUM_RE.sub("<n>", s)
    return s[:300]


def summarise_logs(r):
    out = []
    table = {}
    files = sorted(list((r.root / "logs").glob("*.log")) +
                   list((r.root / "cassandra").glob("log-*.txt")))
    for f in files:
        patterns = Counter()
        sig = Counter()
        first_ts = last_ts = None
        lines = 0
        with open(f, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                lines += 1
                m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
                if m:
                    first_ts = first_ts or m.group(1)
                    last_ts = m.group(1)
                patterns[normalise(line)] += 1
                for s in SIGNATURES:
                    if s in line:
                        sig[s] += 1
        table[f.name] = {"lines": lines, "first": first_ts, "last": last_ts,
                         "signatures": dict(sig.most_common())}
        out.append("=" * 100)
        out.append("%s  lines=%d  first=%s  last=%s" % (f.name, lines, first_ts, last_ts))
        if sig:
            out.append("  signatures: " + ", ".join("%s=%d" % kv for kv in sig.most_common()))
        for pat, n in patterns.most_common(40):
            out.append("  %8d  %s" % (n, pat))
    r.write_text("summary/log-patterns.txt", "\n".join(out) + "\n")
    r.write_json("summary/log-signatures.json", table)
    return table


def write_readme(r, args, containers, sig_table, started):
    lines = ["hoover4 debug report", "",
             "created: %s" % datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z",
             "host: %s" % socket.gethostname(),
             "python: %s" % platform.python_version(),
             "engine: %s" % r.engine,
             "arguments: %s" % " ".join(sys.argv[1:]),
             "run time: %.0f s" % (time.time() - started), "",
             "containers (hoover4 only):"]
    for c in containers:
        s = container_summary(c)
        lines.append("  %-40s %-10s health=%-9s restarts=%-4s oom=%-5s exit=%s started=%s" % (
            s["name"], s["status"], s["health"], s["restart_count"], s["oom_killed"],
            s["exit_code"], s["started_at"]))
    lines += ["", "log signatures (non-zero):"]
    for name, row in sorted(sig_table.items()):
        interesting = {k: v for k, v in row["signatures"].items()
                       if k not in ("WARN", "ERROR", "Exception")}
        if interesting:
            lines.append("  %s: %s" % (name, ", ".join(
                "%s=%d" % kv for kv in sorted(interesting.items(), key=lambda x: -x[1]))))
    failed = [m for m in r.manifest if m.get("error") or m.get("exit_code") not in (0, None)]
    lines += ["", "steps: %d, with an error or a non-zero exit: %d (see manifest.json)"
              % (len(r.manifest), len(failed))]
    if r.notes:
        lines += ["", "notes:"] + ["  " + n for n in r.notes]
    r.write_text("README.txt", "\n".join(lines) + "\n")


# --------------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="hoover4 checkout (default: the parent of this file's folder)")
    ap.add_argument("--out-dir", help="where to write the zip (default: <repo>/tmp)")
    ap.add_argument("--engine", help="container binary (default: docker, else podman)")
    ap.add_argument("--since", default="72h",
                    help="log window for container logs and journals (default 72h)")
    ap.add_argument("--log-lines", type=int, default=300000,
                    help="most lines kept per container log (default 300000)")
    ap.add_argument("--max-describe", type=int, default=400,
                    help="running workflows to describe (default 400)")
    ap.add_argument("--max-histories", type=int, default=6,
                    help="full histories of stuck workflows to save (default 6)")
    ap.add_argument("--history-mb", type=int, default=40,
                    help="most MB kept per workflow history (default 40)")
    ap.add_argument("--jobs", type=int, default=5,
                    help="collectors that run at the same time (default 5)")
    ap.add_argument("--sample-seconds", type=int, default=180,
                    help="length of the per-container time series, 0 to skip (default 180)")
    ap.add_argument("--sample-interval", type=int, default=10,
                    help="seconds between time-series samples (default 10)")
    ap.add_argument("--lifetime-lines", type=int, default=300000,
                    help="most lines kept per lifetime log, 0 to skip (default 300000)")
    ap.add_argument("--dataset-scan-seconds", type=int, default=120,
                    help="walk time per disk dataset, 0 to skip (default 120)")
    ap.add_argument("--timeout", type=int, default=120,
                    help="default timeout per command, in seconds (default 120)")
    ap.add_argument("--no-redact", action="store_true",
                    help="keep credential-like values in the copies")
    ap.add_argument("--keep-dir", action="store_true",
                    help="keep the staging folder beside the zip")
    args = ap.parse_args()

    started = time.time()
    repo = find_repo(args.repo)
    out_dir = Path(args.out_dir or repo / "tmp")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).strftime("%Y%m%dT%H%M%SZ")
    base = "hoover4-debug-%s-%s" % (re.sub(r"[^A-Za-z0-9_.-]", "_", socket.gethostname()),
                                    stamp)
    staging = out_dir / base
    staging.mkdir(parents=True)

    r = Report(staging, redact=not args.no_redact, default_timeout=args.timeout)
    r.engine = find_engine(args.engine)
    print("repo: %s" % repo)
    print("staging: %s" % staging)
    if not r.engine:
        r.note("no docker or podman binary found, so the container sections are skipped")
        print("warning: no docker or podman binary found", file=sys.stderr)
    else:
        probe = subprocess.run([r.engine, "ps", "-q"], capture_output=True, text=True)
        if probe.returncode != 0:
            print("error: `%s ps` failed: %s" % (r.engine, probe.stderr.strip()),
                  file=sys.stderr)
            print("hint: run this script with sudo, or as a user in the docker group",
                  file=sys.stderr)
            r.note("`%s ps` failed: %s" % (r.engine, probe.stderr.strip()))
            r.engine = None

    hours = 72
    m = re.fullmatch(r"(\d+)([smhd])", args.since)
    if m:
        n, u = int(m.group(1)), m.group(2)
        hours = max(1, {"s": n // 3600, "m": n // 60, "h": n, "d": n * 24}[u])

    containers = []
    tasks = [("host", lambda: collect_host(r, args.since)),
             ("repo", lambda: collect_repo(r, repo, r.engine))]
    if r.engine:
        all_containers = list_containers(r, r.engine)
        containers = sorted([c for c in all_containers if is_ours(c)], key=container_name)
        r.write_json("engine/all-containers-summary.json",
                     [container_summary(c) for c in all_containers])
        names = {container_name(c) for c in containers}
        running = {container_name(c) for c in containers
                   if (c.get("State") or {}).get("Running")}
        print("containers: %d in total, %d belong to hoover4, %d of those run"
              % (len(all_containers), len(containers), len(running)))
        tasks.append(("engine", lambda: collect_engine(r, r.engine)))
        for c in containers:
            tasks.append(("container " + container_name(c),
                          lambda c=c: collect_container(r, r.engine, c, args.since,
                                                        args.log_lines)))
        if "temporal" in running:
            tasks.append(("temporal", lambda: collect_temporal(
                r, repo, args.max_describe, args.max_histories,
                args.history_mb * 1024 * 1024)))
        if "temporal-cassandra" in running:
            tasks.append(("cassandra", lambda: collect_cassandra(r)))
        if "temporal-elasticsearch" in running:
            tasks.append(("elasticsearch", lambda: collect_elasticsearch(r)))
        if args.sample_seconds > 0:
            tasks.insert(0, ("timeseries", lambda: collect_timeseries(
                r, containers, args.sample_seconds, args.sample_interval)))
        if "clickhouse" in running:
            tasks.append(("clickhouse", lambda: collect_clickhouse(r, hours)))
            if args.lifetime_lines > 0:
                tasks.append(("lifetime logs", lambda: collect_lifetime_logs(
                    r, r.engine, running, args.lifetime_lines)))
            if args.dataset_scan_seconds > 0 and "hoover4-worker" in running:
                tasks.append(("dataset shape", lambda: collect_dataset_shape(
                    r, args.dataset_scan_seconds)))
        if "manticore" in running:
            tasks.append(("manticore", lambda: collect_manticore(r)))
        if "garage" in running:
            tasks.append(("garage", lambda: collect_garage(r)))
        if "redis" in running:
            tasks.append(("redis", lambda: collect_redis(r)))
        for w in ("hoover4-worker", "hoover4-ops"):
            if w in running:
                tasks.append(("worker " + w, lambda w=w: collect_worker(r, w)))
        missing = sorted((KNOWN_NAMES | {"hoover4-worker", "hoover4-website"}) - names)
        if missing:
            r.note("expected containers not found: %s" % ", ".join(missing))

    # Start the state that can change under the report first. Cassandra can be killed
    # mid-run, and the time series must overlap the other collectors.
    first = ["timeseries", "cassandra", "temporal", "clickhouse", "lifetime logs"]
    tasks.sort(key=lambda t: first.index(t[0]) if t[0] in first else len(first))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {pool.submit(fn): label for label, fn in tasks}
        for fut in concurrent.futures.as_completed(futures):
            label = futures[fut]
            try:
                fut.result()
                print("done: %s (%.0f s)" % (label, time.time() - started))
            except Exception:
                r.note("collector %s failed: %s" % (label, traceback.format_exc(limit=3)))
                print("failed: %s" % label, file=sys.stderr)

    if r.engine and "temporal" in {container_name(c) for c in containers
                                   if (c.get("State") or {}).get("Running")}:
        try:
            collect_failing_runs(r, args.max_describe // 4, args.history_mb * 1024 * 1024)
            print("done: failing runs (%.0f s)" % (time.time() - started))
        except Exception:
            r.note("collector failing-runs failed: %s" % traceback.format_exc(limit=3))
    sig_table = summarise_logs(r)
    r.write_json("manifest.json", r.manifest)
    write_readme(r, args, containers, sig_table, started)

    zip_path = out_dir / (base + ".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6) as z:
        for p in sorted(staging.rglob("*")):
            if p.is_file():
                z.write(p, arcname=str(Path(base) / p.relative_to(staging)))
    if not args.keep_dir:
        shutil.rmtree(staging, ignore_errors=True)
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print("wrote %s (%.1f MB) in %.0f s" % (zip_path, size_mb, time.time() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
