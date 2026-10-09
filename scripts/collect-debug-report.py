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

The report opens with a verdict, in `summary/verdict.txt` and at the top of `README.txt`.
Each check there says PASS, FAIL or UNKNOWN, and names the file that holds its evidence.
Most checks count only what happened after the deployment time. That time is the start of
`hoover4-worker`, or the value of `--deployed-at`.

The script works on Python 3.9 and later.
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
    "zookeeper", "manticore", "manticore-vectors", "clickhouse", "temporal-cassandra",
    "temporal-elasticsearch",
    "temporal", "temporal-ui", "garage", "garage-init", "redis",
}

# The Temporal task queues the worker polls. The script adds every queue name it finds
# in the worker source, so a queue added later is also described.
BASE_QUEUES = [
    "processing-common-queue", "processing-tika-queue", "processing-ocr-queue",
    "processing-ocr-pdf-queue", "processing-nlp-queue", "processing-embed-queue",
    "processing-indexing-queue", "processing-index-planner-queue", "operations-queue",
]

TEMPORAL_ADDR = "temporal:7233"

SECRET_NAME = re.compile(r"(KEY|SECRET|PASSWORD|PASSWD|TOKEN|CREDENTIAL)", re.I)

# Log lines that point at a known failure. Each one is counted in every captured log.
# `java.lang.OutOfMemoryError` and "messages were dropped" are the exact texts. The bare words
# `OutOfMemory` and `Dropped` also match the JVM flag `HeapDumpOnOutOfMemoryError` and the
# Cassandra table `dropped_columns`, which every start logs.
SIGNATURES = [
    "mbind", "Operation not permitted", "shard status unknown", "GRPC Message too large",
    "GrpcMessageTooLarge", "message too large", "ResourceExhausted", "DeadlineExceeded",
    "context deadline exceeded", "Unavailable", "ShardOwnershipLost", "shard ownership lost",
    "Persistent store operation failure", "Operation timed out", "WriteTimeout",
    "ReadTimeout", "NoHostAvailable", "java.lang.OutOfMemoryError", "Killed", "Traceback",
    "Exception", "ERROR", "WARN", "heartbeat", "Heartbeat timeout", "timed out",
    "Connection refused", "No space left", "Too many open files", "GC pause",
    "GCInspector", "messages were dropped", "blocked", "history size exceeds",
    "history count exceeds", "Workflow task failed", "Failing workflow task",
    "workflow task timed out", "non-determinism", "Nondeterminism",
    "Segmentation fault", "core dumped", "corrupted", "panicked", "memory limit exceeded",
    "MEMORY_LIMIT_EXCEEDED", "Potential deadlock", "CRC mismatch", "replay error",
    "starting daemon", "exited with code -9", "ContainerFolderMissing",
    "operation_failures", "circuit opened", "queue is full",
]

# Signatures that the verdict counts after the deployment time, per log. A non-zero count
# fails the check named beside it.
VERDICT_LOG_SIGNATURES = [
    ("ocr-pdf native crashes", "hoover4-ocr-pdf.log",
     ("Segmentation fault", "core dumped", "corrupted", "Aborted")),
    ("scanner panics", "hoover4-regex-entity-scanner.log", ("panicked",)),
    ("failure capture writes", "hoover4-worker.log",
     ("operation_failures ClickHouse is unreachable", "operation_failures insert of",
      "parent_index")),
    ("workflow deadlocks", "hoover4-worker.log", ("Potential deadlock",)),
    ("worker OOM exits", "hoover4-worker.log", ("exited with code -9",)),
    ("ClickHouse memory errors seen by the worker", "hoover4-worker.log",
     ("memory limit exceeded", "Out of memory: allocation")),
    ("Manticore refused by the worker", "hoover4-worker.log",
     ("Can't connect to MySQL server on 'manticore",)),
    ("Manticore refused by the website", "hoover4-website.log",
     ("http://manticore:9308/sql): client error (Connect)",)),
]

# Code markers of the fixes that the production debug plan designs. A marker is a string
# that the fixed file contains. The verdict reports each one as found or not found, so a
# person can see which fixes the deployed checkout carries. A marker is a text search and
# proves nothing about behaviour.
FIX_MARKERS = [
    ("manticore limit from the ini", "deploy.py", "manticore_mem_limit"),
    ("clickhouse limit from the ini", "deploy.py", "clickhouse_mem_limit"),
    ("ocr-pdf limit from the ini", "deploy.py", "ocr_pdf_mem_limit"),
    ("manticore flush period", "main_services/ops/docker/docker-compose.yaml",
     "searchd_rt_flush_period"),
    ("ocr-pdf render process", "main_services/ocr_pdf/render_worker.py", "render"),
    ("byte-bounded text reads", "main_services/processing/tasks/text_sources.py",
     "def plan_text_batches"),
    ("P6 retry policy", "main_services/processing/tasks/P6_index_data/workflows.py",
     "MANTICORE_RETRY"),
    ("failure-capture slots", "main_services/processing/tasks/operation_failure_tree.py",
     "(1 << 23) - 1"),
    ("error groups activity", "main_services/processing/tasks/P2_execute_plan/activities.py",
     "record_processing_error_groups"),
    ("member scan recovery", "main_services/processing/tasks/P3_parse_files/member_scan.py",
     "vfs_files"),
    ("scanner char boundary",
     "main_services/regex_entity_scanner/src/rules/extras.rs", "label.get(from..)"),
    ("1bit vector tables", "main_services/processing/database/manticore.py", "1bit"),
    ("separate vectors container", "main_services/ops/docker/docker-compose.yaml",
     "manticore-vectors"),
    ("ocr-pdf slots from the ini", "deploy.py", "ocr_pdf_concurrency"),
    ("ocr-pdf own queue", "main_services/processing/tasks/P3_parse_files/batch_runner.py",
     "processing-ocr-pdf-queue"),
    ("target-based OCR run", "main_services/processing/tasks/P_admin/workflows.py",
     "class OcrRunPlan"),
]

# The two Manticore containers. `manticore` holds the pages, vfs and entities tables, and
# `manticore-vectors` holds the `_vectors` tables. Each gets its own folder in the report.
MANTICORE_CONTAINERS = ("manticore", "manticore-vectors")

# The terms of the vector memory budget. The RAM chunk limit is the Manticore default of each
# table, and the reserve is a tenth of the limit of `manticore-vectors`.
RAM_CHUNK_BYTES = 128 * 2**20
BUDGET_WARN_RATIO = 0.85

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
    pressure = []
    for kind in ("cpu", "io", "memory"):
        path = "/proc/pressure/" + kind
        try:
            with open(path) as source:
                pressure.extend(("== " + path, source.read().rstrip()))
        except OSError as exc:
            pressure.extend(("== " + path, "unavailable: " + str(exc)))
    r.write_text(j + "pressure.txt", "\n".join(pressure) + "\n")
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
    # A user outside the systemd-journal group reads no kernel entries at all, and then an
    # empty kill list means nothing. The verdict reads this probe to tell the two apart.
    r.sh(j + "journal-kernel-probe.txt", "journalctl -k -n 1 --no-pager 2>&1")
    # ISO timestamps with the zone offset, so collect_oom_kills can compare a kill with the
    # start time of a container. The default journal format has no year and no zone.
    r.sh(j + "journal-oom-kills-30d.txt",
         "journalctl -k --no-pager -o short-iso-precise --since '-30 days' 2>&1 | grep -E "
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
    # the unfiltered stream. The daemon keeps a bounded buffer of events, so this file can
    # be empty on a host with many restarts. summary/oom-kills.json and the restart counts
    # do not depend on it.
    until = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    r.run(j + "events-7d.txt", [engine, "events", "--since", "168h", "--until", until,
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


def host_cgroup_dir(c):
    """The cgroup v2 folder of a running container, read from the host, or None."""
    pid = (c.get("State") or {}).get("Pid") or 0
    if not pid:
        return None
    try:
        with open("/proc/%d/cgroup" % pid) as f:
            rel = [l.strip().split(":", 2)[2] for l in f if l.startswith("0::")]
    except OSError:
        return None
    return ("/sys/fs/cgroup" + rel[0]) if rel else None


def counter_delta(samples, name, key):
    """Return a counter increase only when every sample belongs to one uninterrupted generation."""
    values = [sample["containers"].get(name, {}) for sample in samples]
    if not values or any(value.get(key) is None for value in values):
        return None
    if any(x.get("cgroup_generation") != y.get("cgroup_generation")
           or y[key] < x[key] for x, y in zip(values, values[1:])):
        return None
    return values[-1][key] - values[0][key]


def nested_counter_delta(samples, name, group, key):
    """Return a nested counter increase across one cgroup generation."""
    values = [sample["containers"].get(name, {}) for sample in samples]
    numbers = [value.get(group, {}).get(key) for value in values]
    if not numbers or any(number is None for number in numbers):
        return None
    if any(x.get("cgroup_generation") != y.get("cgroup_generation")
           or end < start
           for x, y, start, end in zip(values, values[1:], numbers, numbers[1:])):
        return None
    return numbers[-1] - numbers[0]


def _read_pressure_totals(path):
    """Read cumulative PSI stall microseconds, or omit unavailable lines."""
    totals = {}
    try:
        with open(path) as source:
            for line in source:
                parts = line.split()
                if parts and parts[0] in ("some", "full"):
                    total = next((part[6:] for part in parts[1:]
                                  if part.startswith("total=")), None)
                    if total is not None:
                        totals[parts[0]] = int(total)
    except (OSError, ValueError):
        return {}
    return totals


def _read_io_totals(path, device_root="/sys/dev/block"):
    """Read top device counters without counting mapped storage twice."""
    rows = {}
    keys = ("rbytes", "wbytes", "rios", "wios")
    try:
        with open(path) as source:
            for index, line in enumerate(source):
                if index >= 64:
                    return {}
                parts = line.split()
                if not parts:
                    continue
                row = {key: 0 for key in keys}
                for part in parts[1:]:
                    key, _, value = part.partition("=")
                    if key in row:
                        row[key] = int(value)
                rows[parts[0]] = row
    except (OSError, ValueError):
        return {}
    lower = set()
    visited = set()

    def descendants(device):
        if device in visited:
            return
        visited.add(device)
        folder = Path(device_root) / device
        try:
            for slave in ((folder / "slaves").iterdir() if (folder / "slaves").is_dir() else []):
                identity = (slave / "dev").read_text().strip()
                lower.add(identity)
                descendants(identity)
            # A partition also contributes to its whole device's I/O counters.
            if (folder / "partition").exists():
                lower.add((folder.resolve().parent / "dev").read_text().strip())
        except OSError:
            pass

    for device in rows:
        descendants(device)
    return {key: sum(row[key] for device, row in rows.items() if device not in lower)
            for key in keys}


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
        row["host_pressure"] = {
            kind: _read_pressure_totals("/proc/pressure/" + kind)
            for kind in ("cpu", "io", "memory")}
        per = {}
        for name, (pid, cg) in targets.items():
            cpu = _read_kv(cg + "/cpu.stat")
            ev = _read_kv(cg + "/memory.events")
            memory = _read_kv(cg + "/memory.stat")
            io = _read_io_totals(cg + "/io.stat")
            try:
                generation = os.stat(cg).st_ino
            except OSError:
                generation = None
            rx, tx = _net_bytes(pid)
            per[name] = {"cgroup_generation": generation,
                         "anon": memory.get("anon"), "file": memory.get("file"),
                         "workingset_refault_anon": memory.get("workingset_refault_anon"),
                         "workingset_refault_file": memory.get("workingset_refault_file"),
                         "usage_usec": cpu.get("usage_usec"),
                         "nr_periods": cpu.get("nr_periods"),
                         "nr_throttled": cpu.get("nr_throttled"),
                         "throttled_usec": cpu.get("throttled_usec"),
                         "mem": _read_int(cg + "/memory.current"),
                         "mem_max": _read_int(cg + "/memory.max"),
                         "oom_kill": ev.get("oom_kill"), "mem_high_events": ev.get("high"),
                         "mem_max_events": ev.get("max"), "rx": rx, "tx": tx}
            per[name]["io"] = io
            per[name]["pressure"] = {
                kind + "_" + level: total
                for kind in ("cpu", "io", "memory")
                for level, total in _read_pressure_totals(
                    cg + "/" + kind + ".pressure").items()}
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
        b = last["containers"].get(name, {})

        def delta(k):
            return counter_delta(samples, name, k)
        def nested_delta(group, key):
            return nested_counter_delta(samples, name, group, key)
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
            "tx_mb_per_s": None if delta("tx") is None else round(delta("tx") / 2**20 / span, 2),
            "io_read_bytes": nested_delta("io", "rbytes"),
            "io_write_bytes": nested_delta("io", "wbytes"),
            "pressure_stall_usec": {
                key: nested_delta("pressure", key)
                for key in ("cpu_some", "cpu_full", "io_some", "io_full",
                            "memory_some", "memory_full")}}
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
    # Read from the host, so a container with no shell (garage) and a container at its
    # memory limit are read the same way, and no process starts inside the container.
    cg = host_cgroup_dir(c)
    if cg:
        lines = []
        for f in ("memory.max", "memory.current", "memory.peak", "memory.swap.max",
                  "memory.events", "memory.pressure", "cpu.max", "cpu.stat", "cpu.pressure",
                  "io.stat", "io.pressure", "pids.current",
                  "pids.max", "memory.stat"):
            try:
                with open(os.path.join(cg, f)) as fh:
                    lines += ["== " + f, fh.read().rstrip()]
            except OSError:
                pass
        r.write_text(d + "cgroup-host.txt", "\n".join(lines) + "\n")
    ex = [engine, "exec", name]
    has_shell = subprocess.run(ex + ["sh", "-c", "true"], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                               timeout=30).returncode == 0
    if not has_shell:
        r.run(d + "top.txt", [engine, "top", name], timeout=30)
        r.note("%s has no shell: ps and cgroup come from `%s top` and the host" % (name, engine))
        return
    r.run(d + "ps.txt", ex + ["sh", "-c",
          "ps aux 2>/dev/null || for p in /proc/[0-9]*; do "
          "printf '%s ' \"${p#/proc/}\"; tr '\\0' ' ' < $p/cmdline; echo; done"],
          timeout=30)
    r.run(d + "proc1-status.txt", ex + ["cat", "/proc/1/status"], timeout=30)
    r.run(d + "cgroup.txt", ex + ["sh", "-c",
          "cd /sys/fs/cgroup 2>/dev/null && for f in memory.max memory.current memory.peak "
          "memory.swap.max memory.swap.current memory.events memory.pressure cpu.max "
          "cpu.stat cpu.pressure io.stat io.pressure pids.current pids.max; do "
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


def collect_clickhouse(r, since_hours, deployed_at):
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
    # The memory cap of the server and what it is computed from. With max_server_memory_usage
    # at 0 the server takes the ratio of the memory it sees, and CGroupMemoryTotal is that
    # memory inside a container.
    ch(r, j + "memory-settings.tsv",
       "SELECT name, value, changed FROM system.server_settings WHERE name IN "
       "('max_server_memory_usage', 'max_server_memory_usage_to_ram_ratio', "
       "'uncompressed_cache_size', 'mark_cache_size') UNION ALL "
       "SELECT metric, toString(value), 0 FROM system.asynchronous_metrics WHERE metric IN "
       "('CGroupMemoryTotal', 'CGroupMemoryUsed', 'OSMemoryTotal', 'MemoryResident')")
    # The override file removes query_log and crash_log on the stacks deploy.py renders. Ask
    # which exist, so a removed table is a note and not four failed steps.
    present = ch(r, None, "SELECT name FROM system.tables WHERE database = 'system' AND "
                 "name IN ('query_log', 'crash_log')", fmt="TSV", capture=True) or ""
    present = set(present.split())
    for table in ("query_log", "crash_log"):
        if table not in present:
            r.note("clickhouse: system.%s is not enabled on this server, so its queries are "
                   "skipped" % table)
    if "crash_log" in present:
        ch(r, j + "crash-log.tsv", "SELECT * FROM system.crash_log ORDER BY event_time DESC "
           "LIMIT 50")
    if "query_log" not in present:
        return collect_clickhouse_processing(r, h, deployed_at)
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
    return collect_clickhouse_processing(r, h, deployed_at)


# The root cause of a processing_errors row: the last `ApplicationError:` line of its chain,
# or the head of the text when it has none, with hashes, temporary paths and numbers
# replaced, so that rows with one cause fall in one group.
ERROR_CAUSE_SQL = (
    "replaceRegexpAll(replaceRegexpAll(replaceRegexpAll("
    "if(length(extractAll(error_logs, 'ApplicationError: ([^\\r\\n]{1,160})')) > 0, "
    "arrayElement(extractAll(error_logs, 'ApplicationError: ([^\\r\\n]{1,160})'), -1), "
    "substring(error_logs, 1, 160)), "
    "'[0-9a-f]{16,}', 'H'), '/tmp/[^ :\\'\"]+', '/tmp/F'), '[0-9]+', 'N')")


def collect_vector_counts(r, dbs):
    """Rows of `text_chunk_vectors` per collection and embedding model.

    ClickHouse holds every vector, so the count exists also when Manticore does not answer.
    `rows` is `count()` without FINAL, so it can include versions of a row that a merge has
    not yet replaced. A collection with no vectors, or with no table, gets one row that says so.
    """
    head = ["collection", "embedding_model", "rows", "dims"]
    out = ["\t".join(head)]
    have = ch(r, None, "SELECT database FROM system.tables WHERE name = 'text_chunk_vectors' "
              "AND database LIKE 'Hoover4_Collection_%'", fmt="TSV", capture=True)
    have = set((have or "").split())
    for db in sorted(dbs):
        collection = db[len("Hoover4_Collection_"):]
        if db not in have:
            out.append("\t".join([collection, "(no table)", "0", ""]))
            continue
        # The row `(total)` comes back from every query that ran, so its absence means the
        # query failed. A failed query writes nothing to stdout.
        text = ch(r, None, "SELECT embedding_model, count() n, toString(any(dims)) d FROM "
                  "{t} GROUP BY embedding_model UNION ALL SELECT '(total)', count(), '' "
                  "FROM {t}".format(t=db + ".text_chunk_vectors"),
                  fmt="TSV", capture=True, timeout=300)
        rows = [l.split("\t") for l in (text or "").splitlines() if l.strip()]
        if not any(row[0] == "(total)" for row in rows):
            out.append("\t".join([collection, "(query failed)", "", ""]))
            continue
        rows = sorted(row for row in rows if row[0] != "(total)")
        if not rows:
            out.append("\t".join([collection, "(no vectors)", "0", ""]))
        for row in rows:
            out.append("\t".join([collection] + (row + ["", "", ""])[:3]))
    r.write_text("clickhouse/vectors-by-collection.tsv", "\n".join(out) + "\n")


def collect_clickhouse_processing(r, h, deployed_at):
    j = "clickhouse/"
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
    collect_vector_counts(r, (dbs or "").split())
    for db in (dbs or "").split():
        d = "clickhouse/collections/%s/" % db
        ch(r, d + "errors-by-task.tsv",
           "SELECT collection_dataset, task_name, count() n, uniqExact(hash) docs, "
           "max(timestamp) last, max(attempt) max_attempt, "
           "substring(any(error_logs),1,1500) sample_error FROM %s.processing_errors "
           "GROUP BY collection_dataset, task_name ORDER BY n DESC" % db, timeout=300)
        # Every error row grouped by root cause, so the causes are counted and not sampled.
        ch(r, d + "errors-by-cause.tsv",
           "SELECT task_name, %s AS cause, count() n, uniqExact(hash) docs, "
           "min(timestamp) first, max(timestamp) last FROM %s.processing_errors "
           "GROUP BY task_name, cause ORDER BY n DESC LIMIT 500" % (ERROR_CAUSE_SQL, db),
           timeout=300)
        ch(r, d + "errors-by-cause-since-deploy.tsv",
           "SELECT task_name, %s AS cause, count() n, uniqExact(hash) docs, "
           "min(timestamp) first, max(timestamp) last FROM %s.processing_errors "
           "WHERE timestamp >= parseDateTimeBestEffort('%s') "
           "GROUP BY task_name, cause ORDER BY n DESC LIMIT 500"
           % (ERROR_CAUSE_SQL, db, deployed_at), timeout=300)
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

def mysql_rows(text):
    """The cells of each row of mysql client output, as a pipe table or as tab-separated."""
    rows = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("+"):
            continue
        if s.startswith("|"):
            cells = [x.strip() for x in s.strip("|").split("|")]
        else:
            cells = [x.strip() for x in s.split("\t")]
        rows.append(cells)
    return rows


def manticore_data_dir(c):
    """The host folder mounted at /var/lib/manticore, or None."""
    for m in c.get("Mounts") or []:
        if m.get("Destination") == "/var/lib/manticore":
            return m.get("Source")
    return None


def parse_quantization(text):
    """The `quantization` of a `SHOW CREATE TABLE` text: "1bit", "8bit", or None when absent.

    Manticore 14.1.0 prints the value in capitals, `quantization='1BIT'`, so the case is
    folded. Any other value raises ValueError. It is never read as float, because a float
    reading counts a 1bit table at 8 times its size.
    """
    m = re.search(r"quantization\s*=\s*'([^']*)'", text or "", re.I)
    if not m:
        return None
    value = m.group(1).strip().lower()
    if value in ("1bit", "8bit"):
        return value
    raise ValueError("unrecognised quantization %r" % m.group(1))


def parse_knn_setting(text, name):
    """An integer KNN setting of a `SHOW CREATE TABLE` text, such as knn_dims, or None."""
    m = re.search(r"\b%s\s*=\s*'(\d+)'" % name, text or "", re.I)
    return int(m.group(1)) if m else None


def hnsw_bytes_per_vector(dims, quantization, hnsw_m=16):
    """Resident bytes of one vector in an HNSW index.

    Data bytes (4, 1 or 1/8 byte a dimension) + 8 x hnsw_m + 40. Measured on 14.1.0 at 384
    dimensions: float 1,684, 8bit 536, 1bit 213. The formula gives 1,704, 552 and 216.
    """
    if quantization == "1bit":
        data = (dims + 7) // 8
    elif quantization == "8bit":
        data = dims
    elif quantization is None:
        data = 4 * dims
    else:
        raise ValueError("unrecognised quantization %r" % quantization)
    return data + 8 * hnsw_m + 40


def vector_budget(tables, limit):
    """The vector memory budget of `manticore-vectors`, as (status, detail).

    `tables` holds one dict for each `_vectors` table, with the text values of
    vector-tables.tsv: indexed_documents, knn_dims, hnsw_m and quantization ("1bit", "8bit",
    "none", or another text that is not read). `limit` is the memory limit in bytes, or None.

    need = resident (the sum of vectors x bytes a vector) + tables x 128 MiB of RAM chunk
         + the largest table (one merge) + a reserve of 10 % of the limit.
    FAIL when need is above the limit, WARN above 85 % of it, PASS otherwise. UNKNOWN when a
    term cannot be read.
    """
    if tables is None:
        return "UNKNOWN", "no vector table list"
    if not limit:
        return "UNKNOWN", "manticore-vectors has no memory limit"
    sizes = []
    for t in tables:
        quant = (t.get("quantization") or "").strip()
        try:
            n = int(t.get("indexed_documents") or "")
            dims = int(t.get("knn_dims") or "")
            m = int(t.get("hnsw_m") or 16)
            if quant not in ("1bit", "8bit", "none"):
                raise ValueError(quant or "no quantization read")
            per = hnsw_bytes_per_vector(dims, None if quant == "none" else quant, m)
        except ValueError as exc:
            return "UNKNOWN", "%s: a term cannot be read (%s)" % (t.get("table"), exc)
        sizes.append(n * per)
    resident = sum(sizes)
    ram_chunks = len(sizes) * RAM_CHUNK_BYTES
    merge = max(sizes) if sizes else 0
    reserve = limit // 10
    need = resident + ram_chunks + merge + reserve
    if need > limit:
        status = "FAIL"
    elif need > BUDGET_WARN_RATIO * limit:
        status = "WARN"
    else:
        status = "PASS"
    detail = ("need %d of %d bytes (%.0f%%): resident %d in %d tables, RAM chunks %d, "
              "largest merge %d, reserve %d" % (need, limit, 100.0 * need / limit, resident,
                                                len(sizes), ram_chunks, merge, reserve))
    return status, detail


def collect_manticore(r, c, name="manticore"):
    """What one Manticore container holds and how it uses memory, with or without a daemon.

    `name` is the container, `manticore` or `manticore-vectors`, and its files go into the
    folder of that name. The data folder is read from the host, so a daemon that the kernel
    kills during its start still gives the table sizes and the binlog it replays. The daemon
    logs to stdout, which collect_container already captures.
    """
    j = name + "/"
    data = manticore_data_dir(c) if c else None
    running = bool(((c or {}).get("State") or {}).get("Running"))

    def inventory(root, prefix):
        q = shlex.quote(root)
        r.run(j + "data-du.txt", prefix + ["sh", "-c", "du -sb %s/* 2>&1 | sort -n" % q],
              timeout=300)
        r.run(j + "binlog.txt", prefix + ["sh", "-c",
              "ls -la --time-style=full-iso %s/binlog 2>&1; echo; du -sb %s/binlog 2>&1"
              % (q, q)], timeout=60)
        # Disk chunks per table: one .spa, .spc or .spd family per chunk. A table with many
        # chunks is what OPTIMIZE merges.
        r.run(j + "chunk-files.txt", prefix + ["sh", "-c",
              "for t in %s/*/; do n=$(ls \"$t\" 2>/dev/null | grep -cE '\\.(spa|spc|spd)$'); "
              "printf '%%s %%s\\n' \"$n\" \"$(basename \"$t\")\"; done | sort -n" % q],
              timeout=120)
        # Bytes of the HNSW files (.spknn) per table. Every HNSW index is held in anonymous
        # memory, so these files give the resident size of the vector indexes on disk.
        r.run(j + "spknn-bytes.txt", prefix + ["sh", "-c",
              "for t in %s/*/; do b=$(ls -ln \"$t\" 2>/dev/null | "
              "awk '/\\.spknn$/ {s+=$5} END {print s+0}'); "
              "printf '%%s %%s\\n' \"$b\" \"$(basename \"$t\")\"; done | sort -n" % q],
              timeout=120)

    if data:
        inventory(data, [])
        refused = "Permission denied" in (r.root / j / "binlog.txt").read_text(errors="replace") \
            if (r.root / j / "binlog.txt").exists() else True
        if refused and running:
            # The folder belongs to the container's user. Without root on the host, read it
            # from inside, which works while the daemon runs and fails while it restarts.
            r.note("%s: the host refused the data folder, so it is read inside the "
                   "container. Run the script as root to read it while the daemon is down"
                   % name)
            inventory("/var/lib/manticore", [r.engine, "exec", name])
    else:
        r.note("%s: no mount at /var/lib/manticore found in `inspect`" % name)
    # Memory from the host side, so it is read the same way whether the daemon answers.
    pid = ((c or {}).get("State") or {}).get("Pid") or 0
    if pid:
        r.sh(j + "searchd-memory.txt",
             "grep -E 'VmRSS|RssAnon|RssFile|Threads' /proc/%d/status; echo; "
             "cat /proc/%d/smaps_rollup 2>&1" % (pid, pid), timeout=30)
    mysql = [r.engine, "exec", name, "mysql", "-h127.0.0.1", "-P9306",
             "--protocol=tcp", "-umanticore", "-pmanticore", "-e"]
    up = r.run(j + "probe.txt", mysql + ["SELECT 1"], timeout=30, capture=True)
    with r.lock:
        probe = next(entry for entry in reversed(r.manifest)
                     if entry.get("file") == j + "probe.txt")
    if probe.get("exit_code") != 0 or not any(row == ["1"] for row in mysql_rows(up)):
        r.note("%s: the daemon does not answer on 9306, so its SQL steps are skipped" % name)
        return
    for name, sql in (("status", "SHOW STATUS"),
                      ("threads", "SHOW THREADS OPTION format=all"),
                      ("settings", "SHOW SETTINGS"), ("variables", "SHOW VARIABLES")):
        r.run(j + name + ".txt", mysql + [sql], timeout=90)
    # The client in the Manticore image prints a pipe table with `-e` even with `--batch`, and
    # another client prints tab-separated rows. mysql_rows reads both.
    tables = r.run(j + "tables.txt", mysql + ["SHOW TABLES"], timeout=60, capture=True)
    with r.lock:
        probe = next(entry for entry in reversed(r.manifest)
                     if entry.get("file") == j + "tables.txt")
    inventory = mysql_rows(tables)
    if probe.get("exit_code") != 0 or (inventory and inventory[0][0] not in ("Index", "Table")):
        r.note("%s: SHOW TABLES failed or returned no valid inventory" % j.rstrip("/"))
        return
    rows = []
    for cells in inventory:
        name = cells[0]
        if not re.fullmatch(r"[A-Za-z0-9_]+", name) or name in ("Table", "Index"):
            continue
        text = r.run(None, mysql + ["SHOW TABLE %s STATUS" % name], timeout=60,
                     capture=True) or ""
        status = {}
        for kv in mysql_rows(text):
            if len(kv) >= 2 and kv[0] != "Variable_name":
                status[kv[0]] = kv[1]
        status["table"] = name
        rows.append(status)
        r.run(j + "table-settings/" + name + ".txt",
              mysql + ["SHOW CREATE TABLE %s" % name], timeout=30)
    keys = ["table", "indexed_documents", "ram_bytes", "disk_bytes", "disk_mapped",
            "disk_mapped_cached", "ram_chunk", "ram_chunk_segments_count", "disk_chunks",
            "mem_limit", "mem_limit_rate", "killed_rate", "optimizing", "tid", "tid_saved"]
    out = ["\t".join(keys)] + ["\t".join(str(row.get(k, "")) for k in keys) for row in rows]
    r.write_text(j + "table-status.tsv", "\n".join(out) + "\n")
    collect_vector_tables(r, j, mysql, rows)


def collect_performance(r, samples, interval, running):
    """Capture repeated service counters without reading document bodies."""
    for index in range(samples):
        started = time.monotonic()
        folder = "performance/%03d/" % index
        r.write_text(folder + "time.txt", datetime.datetime.now(
            datetime.timezone.utc).isoformat() + "\n")
        if "clickhouse" in running:
            ch(r, folder + "clickhouse-processes.tsv",
               "SELECT query_id, elapsed, read_rows, read_bytes, memory_usage, "
               "normalizedQueryHash(query) query_hash FROM system.processes "
               "ORDER BY memory_usage DESC LIMIT 100", timeout=10)
            ch(r, folder + "clickhouse-events.tsv",
               "SELECT event, value FROM system.events WHERE event IN "
               "('Query', 'SelectQuery', 'FailedQuery', 'SelectedRows', 'SelectedBytes', "
               "'OSReadBytes', 'OSWriteBytes')", timeout=10)
        for name in MANTICORE_CONTAINERS:
            if name not in running:
                continue
            mysql = [r.engine, "exec", name, "mysql", "-h127.0.0.1", "-P9306",
                     "--protocol=tcp", "-umanticore", "-pmanticore", "-e"]
            r.run(folder + name + "-status.txt", mysql + ["SHOW STATUS"], timeout=10)
            r.run(folder + name + "-threads.txt",
                  mysql + ["SHOW THREADS OPTION format=all"], timeout=10)
            tables = r.run(folder + name + "-tables.txt", mysql + ["SHOW TABLES"],
                           timeout=10, capture=True)
            names = [row[0] for row in mysql_rows(tables)
                     if len(row) >= 2 and row[1] == "rt"
                     and re.fullmatch(r"[A-Za-z0-9_]+", row[0])]
            r.write_json(folder + name + "-coverage.json",
                         {"tables_listed": len(names), "tables_sampled": names[:64]})
            if names:
                sql = "; ".join("SHOW TABLE %s STATUS" % name for name in names[:64])
                r.run(folder + name + "-table-status.txt", mysql + [sql], timeout=10)
        r.write_text(folder + "finished.txt", datetime.datetime.now(
            datetime.timezone.utc).isoformat() + "\n")
        if index + 1 < samples:
            time.sleep(max(0, interval - (time.monotonic() - started)))


def collect_vector_tables(r, j, mysql, status_rows):
    """One row for each `_vectors` table: its count, KNN settings and .spknn bytes.

    `status_rows` are the `SHOW TABLE <t> STATUS` rows of the container. The quantization is
    "none" when `SHOW CREATE TABLE` has no such attribute (a float table), the error text
    "unrecognised quantization '<value>'" for a value that parse_quantization refuses, and
    empty when `SHOW CREATE TABLE` gave no text.
    """
    spknn = {}
    path = r.root / j / "spknn-bytes.txt"
    if path.exists():
        for line in path.read_text(errors="replace").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0].isdigit():
                spknn[parts[1]] = parts[0]
    keys = ["table", "indexed_documents", "knn_dims", "hnsw_m", "quantization", "spknn_bytes",
            "bytes_per_vector", "resident_bytes"]
    out = ["\t".join(keys)]
    for status in status_rows:
        table = status["table"]
        if not table.endswith("_vectors"):
            continue
        text = r.run(None, mysql + ["SHOW CREATE TABLE %s" % table], timeout=60,
                     capture=True) or ""
        dims = parse_knn_setting(text, "knn_dims")
        hnsw_m = parse_knn_setting(text, "hnsw_m") or 16
        try:
            quant = parse_quantization(text)
            quant_text = quant or "none"
        except ValueError as exc:
            quant, quant_text = "?", str(exc)
        if not text.strip():
            quant, quant_text = "?", ""
        per, resident = "", ""
        n = status.get("indexed_documents", "")
        if dims is not None and quant != "?":
            per = hnsw_bytes_per_vector(dims, quant, hnsw_m)
            if n.isdigit():
                resident = int(n) * per
        row = [table, n, "" if dims is None else dims, hnsw_m, quant_text,
               spknn.get(table, ""), per, resident]
        out.append("\t".join(str(x) for x in row))
    r.write_text(j + "vector-tables.tsv", "\n".join(out) + "\n")


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


ERROR_WORDS = re.compile(r"Traceback|ERROR|Error|Exception|error=|level\":\"error|"
                         r"failed|FAILED|Killed|OutOfMemoryError|timed out|Timeout|"
                         r"Segmentation fault|core dumped|panicked|corrupted|CRC mismatch")
# Lines that repeat thousands of times an hour and carry no new fact after the first.
SPAM = re.compile(r"GRPC Message too large|Unspecified task queue kind|mbind: Operation not "
                  r"permitted|Critical attempts processing workflow task|"
                  r"respond_workflow_task_failed retried")
TIMELINE_SIGNATURES = ["GRPC Message too large", "shard status unknown", "Traceback",
                       "java.lang.OutOfMemoryError", "history size exceeds",
                       "Persistent store operation",
                       "Critical attempts processing workflow task", "mbind",
                       "context deadline exceeded", "no hosts available", "Heartbeat",
                       "ERROR", "Startup complete", "starting daemon", "Segmentation fault",
                       "panicked", "memory limit exceeded", "exited with code -9",
                       "Potential deadlock", "Connection refused"]


def collect_lifetime_logs(r, engine, running_names, max_lines, deployed_at=None,
                          watch_names=True):
    """Read the whole log of each running project container once.

    Keep the lines that name a recent operation or dataset, and the error lines that are
    not repeats of a known flood. Count every timeline signature per hour of all lines.
    Docker keeps only `container_log_max_files` files of `container_log_max_size`, so the
    first line read says how far back the kept log reaches. It is recorded as `first_line`.

    Count each `VERDICT_LOG_SIGNATURES` needle over every line at or after deployed_at, and
    write the counts and the time of the first line read to `summary/verdict-log-counts.json`.
    The verdict reads them, because `logs/<name>.log` holds only a tail of the log. A read
    whose `logs` command does not exit 0 goes under `failed`, with no counts.

    With `watch_names` false, ClickHouse is not asked for the recent operation names.
    """
    j = "lifetime-logs/"
    text = ""
    if watch_names:
        text = ch(r, None, "SELECT DISTINCT op_id, collection_dataset FROM "
                  "Hoover4_Processing.operations FINAL WHERE started_at > now() - "
                  "INTERVAL 14 DAY", fmt="TSV", capture=True) or ""
    names = set()
    for line in text.splitlines():
        for part in line.split("\t"):
            part = part.strip()
            if len(part) >= 6:
                names.add(part)
    r.write_json(j + "watched-names.json", sorted(names))
    watch = re.compile("|".join(re.escape(n) for n in sorted(names))) if names else None
    needles_of = defaultdict(set)
    for _check, log, needles in VERDICT_LOG_SIGNATURES:
        needles_of[log[:-len(".log")]].update(needles)
    verdict_counts = {}
    failed = {}
    timeline = {}
    for name in sorted(running_names):
        needles = sorted(needles_of.get(name, ()))
        found = Counter()
        rule = SinceDeploy(deployed_at)
        complete = False
        hours = defaultdict(Counter)
        kept = 0
        total = 0
        first_line = None
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
                    if first_line is None:
                        first_line = line[:40]
                    # The rule reads every line, because a line with no time takes the
                    # time of the line before it.
                    if rule.after(line):
                        found.update(s for s in needles if s in line)
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
            code = proc.wait(timeout=60)
            if code == 0:
                complete = True
            else:
                failed[name] = "exit %s" % code
                r.note("lifetime log of %s failed: `%s logs` exited %s" % (name, engine, code))
        except Exception as exc:
            failed[name] = str(exc)[:200]
            r.note("lifetime log of %s failed: %s" % (name, exc))
        if complete:
            first_ts = parse_ts(first_line)
            verdict_counts[name] = {
                "first_line_time": first_ts.isoformat() if first_ts else None,
                "lines_read": total, "needles": {s: found[s] for s in needles}}
        r.record({"file": j + name + ".log", "lines_read": total, "lines_kept": kept,
                  "first_line": first_line, "seconds": round(time.time() - started, 1)})
        timeline[name] = {h: dict(c) for h, c in sorted(hours.items())}
    r.write_json("summary/verdict-log-counts.json", {
        "deployed_at": deployed_at.isoformat() if deployed_at else None,
        "containers": verdict_counts, "failed": failed})
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
# Kernel OOM kills, per container
# --------------------------------------------------------------------------------------

_TS_PARTS = re.compile(
    r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:[.,](\d+))?\s*(Z|[+-]\d{2}:?\d{2})?")


def parse_ts(text):
    """An ISO time with any fraction and zone, as an aware UTC datetime, or None.

    Docker writes nanoseconds and `Z`, journalctl writes microseconds and `+02:00`, and
    Python 3.9's `fromisoformat` accepts neither form of the first.
    """
    m = _TS_PARTS.search(text or "")
    if not m:
        return None
    frac = (m.group(3) or "0")[:6].ljust(6, "0")
    zone = m.group(4) or "Z"
    if zone == "Z":
        offset = datetime.timedelta(0)
    else:
        sign = 1 if zone[0] == "+" else -1
        digits = zone[1:].replace(":", "")
        offset = sign * datetime.timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
    try:
        naive = datetime.datetime.strptime("%s %s.%s" % (m.group(1), m.group(2), frac),
                                           "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None
    return (naive - offset).replace(tzinfo=datetime.timezone.utc)


MEMCG_RE = re.compile(r"task_memcg=\S*?(?:docker|libpod)-([0-9a-f]{12,64})\.scope\S*?,task=([^,]+)")
KILLED_RE = re.compile(r"Killed process (\d+) \(([^)]+)\) total-vm:(\d+)kB, anon-rss:(\d+)kB")


def collect_oom_kills(r, containers, deployed_at, engine, windows):
    """Map every kernel OOM kill in the journal to its container and summarise it.

    Docker's `State.OOMKilled` misses a kill of a process that Docker restarts, and misses
    every kill of a child process. The kernel journal names the memory cgroup of each kill,
    and the cgroup name holds the container id. For each container with a kill after the
    deployment, the container log around the first and the last kills is saved, because
    rotation removes that part of the log first.
    """
    path = r.root / "host" / "journal-oom-kills-30d.txt"
    by_id = {(c.get("Id") or ""): container_name(c) for c in containers}
    per = defaultdict(lambda: {"kills_30d": 0, "kills_since_deploy": 0, "first": None,
                               "last": None, "max_anon_rss_mb": 0, "processes": Counter(),
                               "since_deploy_times": []})
    if path.exists():
        pending = None
        for line in path.read_text(errors="replace").splitlines():
            m = MEMCG_RE.search(line)
            if m:
                cid = m.group(1)
                name = next((n for i, n in by_id.items() if i.startswith(cid)), cid[:12])
                pending = name
                continue
            k = KILLED_RE.search(line)
            if not k or pending is None:
                continue
            ts = parse_ts(line)
            row = per[pending]
            row["kills_30d"] += 1
            row["processes"][k.group(2)] += 1
            row["max_anon_rss_mb"] = max(row["max_anon_rss_mb"], int(k.group(4)) // 1024)
            if ts is not None:
                iso = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
                row["first"] = row["first"] or iso
                row["last"] = iso
                if deployed_at is not None and ts >= deployed_at:
                    row["kills_since_deploy"] += 1
                    row["since_deploy_times"].append(ts)
            pending = None
    else:
        r.note("oom kills: host/journal-oom-kills-30d.txt is missing")
    out = {}
    for name, row in per.items():
        times = row.pop("since_deploy_times")
        row["processes"] = dict(row["processes"])
        out[name] = row
        if engine and name in by_id.values() and times and windows > 0:
            picked = times[:windows] + [t for t in times[-windows:] if t not in times[:windows]]
            for n, t in enumerate(picked):
                since = (t - datetime.timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
                until = (t + datetime.timedelta(seconds=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
                r.run("logs/oom-windows/%s-%02d.log" % (name, n),
                      [engine, "logs", "--timestamps", "--since", since, "--until", until,
                       name], timeout=120, merge=True, max_bytes=20 * 1024 * 1024)
    r.write_json("summary/oom-kills.json", out)
    return out


# --------------------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------------------

# processing_errors causes that name the platform rather than the file. One of these after
# the deployment fails the verdict. Every other cause is reported as a per-file failure.
INFRA_CAUSES = re.compile(
    r"Can't connect to MySQL|Lost connection to MySQL|memory limit exceeded|Out of memory|"
    r"queue is full|ContainerFolderMissing|Heartbeat timeout|attempts of the stage activity|"
    r"circuit open|Connection refused|Gateway Timeout|renderer stopped with signal", re.I)


def _read_tsv(path):
    if not path.exists():
        return None
    lines = path.read_text(errors="replace").splitlines()
    if not lines:
        return []
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in lines[1:]]


class SinceDeploy:
    """Decide for each line of a `--timestamps` log if it is at or after deployed_at.

    Both log counts of the verdict use this one rule. A line with a parsable time counts when
    that time is at or after deployed_at. A line with no parsable time, such as the next line
    of a traceback, counts when the previous line with a time is at or after deployed_at. A
    line with no time before any line with a time does not count. With no deployed_at, every
    line counts.
    """

    def __init__(self, deployed_at):
        self.deployed_at = deployed_at
        self.last = None

    def after(self, line):
        if self.deployed_at is None:
            return True
        ts = parse_ts(line[:40])
        if ts is not None:
            self.last = ts
        return self.last is not None and self.last >= self.deployed_at


def _count_since(path, needles, deployed_at):
    """Lines of a `--timestamps` log at or after deployed_at that hold any needle."""
    if not path.exists():
        return None
    n = 0
    rule = SinceDeploy(deployed_at)
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if rule.after(line) and any(s in line for s in needles):
                n += 1
    return n


def _first_line_time(path):
    """The time of the first line of a `--timestamps` log, or None."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        return parse_ts(fh.readline()[:40])


def _read_misses_deploy(first_ts, amount_read, deployed_at):
    """True when a log read cannot show every line at or after deployed_at.

    That is so when the read is not empty and its first line is later than deployed_at, or
    has no time. `amount_read` is a line count or a byte count, and only zero matters.
    """
    if deployed_at is None or not amount_read:
        return False
    return first_ts is None or first_ts > deployed_at


def build_verdict(r, repo, containers, deployed_at, oom, expected_limits):
    checks = []

    def add(name, status, detail, evidence):
        checks.append({"check": name, "status": status, "detail": detail,
                       "evidence": evidence})

    ours = [c for c in containers if container_name(c) != "garage-init"]
    down = [container_name(c) for c in ours if not (c.get("State") or {}).get("Running")
            or (c.get("State") or {}).get("Restarting")]
    add("containers running", "FAIL" if down else "PASS",
        "not running: %s" % ", ".join(down) if down else "all running",
        "README.txt, engine/ps-all.txt")

    # Compare whole seconds. The runbook gives deployed_at as the worker's own start time, as
    # printed or cut to whole seconds, and that start is no restart after the deployment.
    restarted = []
    dep_s = deployed_at.replace(microsecond=0) if deployed_at is not None else None
    for c in ours:
        started = parse_ts((c.get("State") or {}).get("StartedAt"))
        if c.get("RestartCount") and (dep_s is None or started is None
                                      or started.replace(microsecond=0) > dep_s):
            restarted.append("%s=%s (started %s)" % (
                container_name(c), c.get("RestartCount"),
                started.strftime("%Y-%m-%dT%H:%M:%SZ") if started else "unknown"))
    add("restarts since deploy", "FAIL" if restarted else "PASS",
        ", ".join(restarted) or "no restarts", "containers/*/summary.json")

    killed = ["%s=%d (max anon %d MB)" % (n, row["kills_since_deploy"], row["max_anon_rss_mb"])
              for n, row in sorted(oom.items()) if row["kills_since_deploy"]]
    # The cgroup's own counter covers the life of the current container process tree, and
    # it needs no journal access. It resets when the container restarts.
    for c in ours:
        p = r.root / "containers" / container_name(c) / "cgroup-host.txt"
        if p.exists():
            m = re.search(r"^oom_kill (\d+)$", p.read_text(errors="replace"), re.M)
            if m and int(m.group(1)) and not (oom.get(container_name(c)) or {}).get(
                    "kills_since_deploy"):
                killed.append("%s=%s (cgroup counter)" % (container_name(c), m.group(1)))
    probe = r.root / "host" / "journal-kernel-probe.txt"
    readable = probe.exists() and "No entries" not in probe.read_text(errors="replace") \
        and probe.read_text(errors="replace").strip() != ""
    if killed:
        status = "FAIL"
    elif not readable:
        status = "UNKNOWN"
    else:
        status = "PASS"
    add("kernel OOM kills since deploy", status,
        ", ".join(killed) or ("none" if readable else
                              "the kernel journal returned no entries: run the script as root"),
        "summary/oom-kills.json, containers/*/cgroup-host.txt, logs/oom-windows/")

    limits = []
    status = "PASS"
    names = {container_name(c): c for c in containers}
    for name in ("manticore", "manticore-vectors", "clickhouse", "hoover4-worker",
                 "hoover4-ocr-pdf"):
        c = names.get(name)
        if not c:
            # A container whose limit the person expects must exist.
            if name in expected_limits:
                status = "FAIL"
                limits.append("%s=missing (expected >= %.1fG)"
                              % (name, expected_limits[name] / 2**30))
            continue
        mem = (c.get("HostConfig") or {}).get("Memory") or 0
        want = expected_limits.get(name)
        ok = mem > 0 and (want is None or mem >= want)
        status = status if ok else "FAIL"
        limits.append("%s=%s%s" % (name, "%.1fG" % (mem / 2**30) if mem else "none",
                                   "" if want is None else " (expected >= %.1fG)" % (want / 2**30)))
    add("memory limits", status, ", ".join(limits), "containers/*/summary.json")

    heads = []
    status = "PASS"
    unread = []
    for c in ours:
        name = container_name(c)
        text = (r.root / "containers" / name / "cgroup-host.txt")
        if not text.exists():
            # The file the exec-based reader writes, from a report of the version before.
            text = (r.root / "containers" / name / "cgroup.txt")
        if not text.exists():
            unread.append("%s: no cgroup file" % name)
            continue
        body = text.read_text(errors="replace")
        mx = re.search(r"== memory.max\n(\d+)", body)
        anon = re.search(r"^anon (\d+)$", body, re.M)
        thp = re.search(r"^anon_thp (\d+)$", body, re.M)
        if not mx or not anon or int(mx.group(1)) == 0:
            unread.append("%s: memory.max or anon cannot be read" % name)
            continue
        ratio = int(anon.group(1)) / int(mx.group(1))
        if ratio > 0.85:
            status = "FAIL"
        if ratio > 0.5 or container_name(c) in MANTICORE_CONTAINERS:
            heads.append("%s anon %.0f%% of limit%s" % (
                container_name(c), ratio * 100,
                "" if not thp else ", huge pages %.1f GB" % (int(thp.group(1)) / 1e9)))
    if unread and status != "FAIL":
        status = "UNKNOWN"
    add("memory headroom (anon over limit, fail above 85%)", status,
        "; ".join(heads + unread) or "no container above 50%",
        "containers/*/cgroup-host.txt")

    for mname in MANTICORE_CONTAINERS:
        if mname not in names:
            why = "container %s not found" % mname
            add("%s answers" % mname, "FAIL", why, "engine/ps-all.txt")
            add("%s rt_flush_period set" % mname, "UNKNOWN", why, "engine/ps-all.txt")
            add("%s binlog under 2 GB" % mname, "UNKNOWN", why, "engine/ps-all.txt")
            continue
        tables = r.root / mname / "table-status.tsv"
        if tables.exists():
            rows = _read_tsv(tables) or []
            add("%s answers" % mname, "PASS", "%d tables" % len(rows),
                "%s/table-status.tsv" % mname)
            settings = (r.root / mname / "settings.txt")
            flush = settings.exists() and "rt_flush_period" in settings.read_text(
                errors="replace")
            add("%s rt_flush_period set" % mname, "PASS" if flush else "FAIL",
                "found in SHOW SETTINGS" if flush else "not in SHOW SETTINGS",
                "%s/settings.txt" % mname)
        else:
            add("%s answers" % mname, "FAIL", "no SQL answer on 9306",
                "%s/, logs/%s.log" % (mname, mname))
        binlog = r.root / mname / "binlog.txt"
        if binlog.exists():
            body = binlog.read_text(errors="replace")
            m = re.search(r"^(\d+)\s+\S*binlog\s*$", body, re.M)
            if "Permission denied" in body or "No such file" in body:
                add("%s binlog under 2 GB" % mname, "UNKNOWN",
                    "the binlog folder could not be read", "%s/binlog.txt" % mname)
            elif m:
                size = int(m.group(1))
                add("%s binlog under 2 GB" % mname, "PASS" if size < 2 * 2**30 else "FAIL",
                    "%.2f GB" % (size / 2**30), "%s/binlog.txt" % mname)

    # After the split the text container holds no `_vectors` table. The worker's migrate
    # drops the old float tables from it at its start.
    text_rows = _read_tsv(r.root / "manticore" / "table-status.tsv")
    if text_rows is None:
        add("no _vectors tables in the text container", "UNKNOWN",
            "manticore/table-status.tsv missing, so the text container's tables were not read",
            "manticore/table-status.tsv")
    else:
        stale = sorted(t.get("table") for t in text_rows
                       if (t.get("table") or "").endswith("_vectors"))
        add("no _vectors tables in the text container", "FAIL" if stale else "PASS",
            ("%d on manticore: %s" % (len(stale), ", ".join(stale[:10])
                                      + (", ..." if len(stale) > 10 else "")))
            if stale else "none on manticore", "manticore/table-status.tsv")

    vec_path = r.root / "manticore-vectors" / "vector-tables.tsv"
    vec_rows = _read_tsv(vec_path)
    source_rows = _read_tsv(r.root / "clickhouse" / "vectors-by-collection.tsv")
    source_total = None
    source_missing = []
    if source_rows is not None:
        try:
            if any(not row.get("collection") for row in source_rows):
                raise ValueError("missing collection")
            source_total = sum(int(row["rows"]) for row in source_rows)
        except (KeyError, TypeError, ValueError):
            source_total = None
    if source_total is not None and vec_rows is not None:
        table_collections = set()
        for row in vec_rows:
            match = re.fullmatch(r"(.+)_\d+_vectors", row.get("table") or "")
            if match:
                table_collections.add(match.group(1))
        source_missing = sorted({row["collection"] for row in source_rows
                                 if int(row["rows"]) > 0
                                 and row["collection"] not in table_collections})
    if vec_rows is None:
        why = ("container manticore-vectors not found" if "manticore-vectors" not in names
               else "manticore-vectors/vector-tables.tsv missing, so the daemon did not answer")
        add("vector tables quantized", "UNKNOWN", why, "manticore-vectors/vector-tables.tsv")
    else:
        not_1bit = ["%s=%s" % (t.get("table"), t.get("quantization"))
                    for t in vec_rows if t.get("quantization") in ("none", "8bit")]
        unread = ["%s=%s" % (t.get("table"), t.get("quantization") or "not read")
                  for t in vec_rows if t.get("quantization") not in ("none", "8bit", "1bit")]
        if not_1bit:
            status, detail = "FAIL", "not 1bit: " + ", ".join(not_1bit)
        elif unread:
            status, detail = "UNKNOWN", "not read: " + ", ".join(unread)
        elif source_total is None:
            status, detail = "UNKNOWN", "durable vector count cannot be read"
        elif source_missing:
            status, detail = "FAIL", "no vector table for " + ", ".join(source_missing)
        else:
            status, detail = "PASS", "%d tables, all 1bit" % len(vec_rows)
        add("vector tables quantized", status, detail, "manticore-vectors/vector-tables.tsv")

    vc = names.get("manticore-vectors")
    limit = ((vc or {}).get("HostConfig") or {}).get("Memory") or None
    if vc is None:
        status, detail = "UNKNOWN", "container manticore-vectors not found"
    elif vec_rows is None:
        status, detail = "UNKNOWN", "manticore-vectors/vector-tables.tsv missing"
    elif source_total is None:
        status, detail = "UNKNOWN", "durable vector count cannot be read"
    elif source_missing:
        status, detail = "FAIL", "no vector table for " + ", ".join(source_missing)
    else:
        status, detail = vector_budget(vec_rows, limit)
    add("vector memory budget", status, detail,
        "manticore-vectors/vector-tables.tsv, containers/manticore-vectors/summary.json")

    # The counts over the whole log come from the lifetime log reader. A container it did
    # not read completely falls back to the tail in logs/, and the detail says so. A read
    # whose first line is later than deployed_at did not see every line since the
    # deployment, so its check says UNKNOWN, unless it found a match.
    full = {}
    failed_reads = {}
    counts_path = r.root / "summary" / "verdict-log-counts.json"
    if counts_path.exists():
        try:
            counts = json.loads(counts_path.read_text(errors="replace"))
            full = counts.get("containers") or {}
            failed_reads = counts.get("failed") or {}
        except (ValueError, AttributeError):
            full = {}
    for name, log, needles in VERDICT_LOG_SIGNATURES:
        cname = log[:-len(".log")]
        entry = full.get(cname)
        if entry is not None:
            n = sum(int((entry.get("needles") or {}).get(s) or 0) for s in needles)
            detail = "%d matches since deploy in the whole log" % n
            status = "FAIL" if n else "PASS"
            if _read_misses_deploy(parse_ts(entry.get("first_line_time")),
                                   entry.get("lines_read"), deployed_at):
                detail += ", but the kept log starts at %s, after the deployment" % (
                    entry.get("first_line_time") or "an unknown time")
                status = "FAIL" if n else "UNKNOWN"
            add(name, status, detail, "summary/verdict-log-counts.json, lifetime-logs/" + log)
            continue
        why = ("the whole-log read failed (%s), " % failed_reads[cname]
               if cname in failed_reads else "")
        path = r.root / "logs" / log
        n = _count_since(path, needles, deployed_at)
        if n is None:
            add(name, "UNKNOWN", why + "log missing", "logs/" + log)
            continue
        first = _first_line_time(path)
        detail = "%s%d lines since deploy, tail only" % (why, n)
        status = "FAIL" if n else "PASS"
        if _read_misses_deploy(first, path.stat().st_size, deployed_at):
            detail += ", and the tail starts at %s, after the deployment" % (
                first.strftime("%Y-%m-%dT%H:%M:%SZ") if first else "an unknown time")
            status = "FAIL" if n else "UNKNOWN"
        add(name, status, detail, "logs/" + log)

    errs = _read_tsv(r.root / "clickhouse" / "errors.tsv")
    if errs is None:
        add("ClickHouse memory errors", "UNKNOWN", "clickhouse/errors.tsv missing",
            "clickhouse/errors.tsv")
    else:
        hit = [e for e in errs if e.get("name") in ("MEMORY_LIMIT_EXCEEDED", "CANNOT_ALLOCATE_MEMORY")
               and (deployed_at is None or (parse_ts(e.get("last_error_time", "")) or deployed_at)
                    >= deployed_at)]
        add("ClickHouse memory errors", "FAIL" if hit else "PASS",
            ", ".join("%s=%s last %s" % (e["name"], e.get("value"), e.get("last_error_time"))
                      for e in hit) or "none since deploy", "clickhouse/errors.tsv")

    failed = r.root / "temporal" / "workflows-failed.json"
    if failed.exists():
        try:
            rows = parse_json_lines(failed.read_text(errors="replace"))
        except Exception:
            rows = []
        by_type = Counter(dig(w, "type", "name") or "?" for w in rows
                          if deployed_at is None
                          or (parse_ts(w.get("closeTime")) or deployed_at) >= deployed_at)
        add("failed workflows since deploy", "FAIL" if by_type else "PASS",
            ", ".join("%s=%d" % kv for kv in by_type.most_common()) or "none",
            "temporal/workflows-failed.json")

    ops = _read_tsv(r.root / "clickhouse" / "operations.tsv")
    if ops is not None:
        recent = [o for o in ops if deployed_at is None
                  or (parse_ts(o.get("started_at", "") + "Z") or deployed_at) >= deployed_at]
        states = Counter(o.get("state") for o in recent)
        add("operations since deploy", "FAIL" if states.get("errored") else "PASS",
            ", ".join("%s=%d" % kv for kv in states.most_common()) or "none",
            "clickhouse/operations.tsv")

    infra, per_file = Counter(), Counter()
    cause_files = sorted((r.root / "clickhouse" / "collections").glob(
        "*/errors-by-cause-since-deploy.tsv"))
    for p in cause_files:
        for row in _read_tsv(p) or []:
            key = "%s: %s" % (row.get("task_name"), (row.get("cause") or "")[:100])
            n = int(row.get("n") or 0)
            (infra if INFRA_CAUSES.search(row.get("cause") or "") else per_file)[key] += n
    add("platform causes in processing_errors since deploy",
        "FAIL" if infra else ("PASS" if cause_files else "UNKNOWN"),
        "; ".join("%d %s" % (n, k) for k, n in infra.most_common(8)) or "none",
        "clickhouse/collections/*/errors-by-cause-since-deploy.tsv")
    add("per-file causes in processing_errors since deploy", "INFO",
        "; ".join("%d %s" % (n, k) for k, n in per_file.most_common(8)) or "none",
        "clickhouse/collections/*/errors-by-cause-since-deploy.tsv")

    for label, rel, needle in FIX_MARKERS:
        p = repo / rel
        try:
            found = needle in p.read_text(errors="replace")
        except OSError:
            found = False
        add("fix marker: " + label, "INFO", "found" if found else "not found", rel)

    firsts = [("lifetime-logs/%s.log" % name, parse_ts(e.get("first_line_time")))
              for name, e in sorted(full.items())]
    if not full:
        # No counts file: read the first lines that the manifest recorded.
        firsts = [(m["file"], parse_ts(m.get("first_line"))) for m in r.manifest
                  if m.get("first_line")]
    if deployed_at is not None:
        for f, ts in firsts:
            if ts is not None and ts > deployed_at:
                add("log reaches the deployment: " + f, "WARN",
                    "the kept log starts at %s, after the deployment, so its counts start "
                    "there" % ts.strftime("%Y-%m-%dT%H:%M:%SZ"), f)

    order = {"FAIL": 0, "UNKNOWN": 1, "WARN": 2, "PASS": 3, "INFO": 4}
    checks.sort(key=lambda x: order.get(x["status"], 5))
    r.write_json("summary/verdict.json", {
        "deployed_at": deployed_at.isoformat() if deployed_at else None, "checks": checks})
    lines = ["deployed at: %s" % (deployed_at.isoformat() if deployed_at else "unknown"), ""]
    for x in checks:
        lines.append("%-7s %s: %s   [%s]" % (x["status"], x["check"], x["detail"], x["evidence"]))
    r.write_text("summary/verdict.txt", "\n".join(lines) + "\n")
    return checks


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


def write_readme(r, args, containers, sig_table, started, oom, checks):
    lines = ["hoover4 debug report", "",
             "created: %s" % datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z",
             "host: %s" % socket.gethostname(),
             "python: %s" % platform.python_version(),
             "engine: %s" % r.engine,
             "arguments: %s" % " ".join(sys.argv[1:]),
             "run time: %.0f s" % (time.time() - started), ""]
    counts = Counter(x["status"] for x in checks)
    lines += ["verdict: %s (summary/verdict.txt)" % ", ".join(
        "%s=%d" % kv for kv in sorted(counts.items()))]
    lines += ["  %-7s %s: %s" % (x["status"], x["check"], x["detail"][:160])
              for x in checks if x["status"] in ("FAIL", "UNKNOWN", "WARN")]
    lines += ["", "containers (hoover4 only). `docker_oom` is Docker's State.OOMKilled, and "
              "`kernel_kills` counts the kernel's memory-cgroup kills since the deployment "
              "(summary/oom-kills.json):"]
    for c in containers:
        s = container_summary(c)
        kills = (oom.get(s["name"]) or {}).get("kills_since_deploy", 0)
        lines.append("  %-40s %-10s health=%-9s restarts=%-4s docker_oom=%-5s kernel_kills=%-5s "
                     "exit=%s started=%s" % (
                         s["name"], s["status"], s["health"], s["restart_count"],
                         s["oom_killed"], kills, s["exit_code"], s["started_at"]))
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
    ap.add_argument("--performance-samples", type=int, default=0,
                    help="service counter samples, from 0 to 120 (default 0)")
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
    ap.add_argument("--deployed-at",
                    help="the deployment time the verdict counts from, as an ISO time "
                         "(default: the start time of hoover4-worker)")
    ap.add_argument("--expect-limit", action="append", default=[], metavar="NAME=SIZE",
                    help="a memory limit the verdict requires at least, such as "
                         "manticore=64G. Repeat the flag for each container")
    ap.add_argument("--oom-windows", type=int, default=3,
                    help="log windows kept around the first and the last kernel OOM kills "
                         "of each container since the deployment (default 3)")
    args = ap.parse_args()
    if not 0 <= args.performance_samples <= 120:
        ap.error("--performance-samples must be from 0 to 120")
    if args.sample_interval < 1:
        ap.error("--sample-interval must be positive")
    expected_limits = {}
    for item in args.expect_limit:
        name, _, size = item.partition("=")
        m = re.fullmatch(r"(\d+)\s*([KMGT]?)B?", size.strip(), re.I)
        if not name or not m:
            ap.error("--expect-limit takes NAME=SIZE, such as manticore=64G: %r" % item)
        unit = {"": 1, "K": 2**10, "M": 2**20, "G": 2**30, "T": 2**40}[m.group(2).upper()]
        expected_limits[name.strip()] = int(m.group(1)) * unit

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
    deployed_at = parse_ts(args.deployed_at) if args.deployed_at else None
    if args.deployed_at and deployed_at is None:
        ap.error("--deployed-at is not an ISO time: %r" % args.deployed_at)
    tasks = [("host", lambda: collect_host(r, args.since)),
             ("repo", lambda: collect_repo(r, repo, r.engine))]
    if r.engine:
        all_containers = list_containers(r, r.engine)
        containers = sorted([c for c in all_containers if is_ours(c)], key=container_name)
        if deployed_at is None:
            worker = next((c for c in containers if container_name(c) == "hoover4-worker"), None)
            deployed_at = parse_ts(((worker or {}).get("State") or {}).get("StartedAt"))
        print("deployed at: %s" % (deployed_at.isoformat() if deployed_at else "unknown"))
    deployed_iso = (deployed_at or datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
                    ).strftime("%Y-%m-%d %H:%M:%S")
    if r.engine:
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
        # The log checks of the verdict need the whole-log counts, so the reader runs also
        # when ClickHouse is down. It then keeps no lines by operation name.
        if args.lifetime_lines > 0:
            tasks.append(("lifetime logs", lambda: collect_lifetime_logs(
                r, r.engine, running, args.lifetime_lines, deployed_at,
                watch_names="clickhouse" in running)))
        if "clickhouse" in running:
            tasks.append(("clickhouse", lambda: collect_clickhouse(r, hours, deployed_iso)))
            if args.dataset_scan_seconds > 0 and "hoover4-worker" in running:
                tasks.append(("dataset shape", lambda: collect_dataset_shape(
                    r, args.dataset_scan_seconds)))
        # Also when it is not running: the data folder and the binlog are read from the host.
        if args.performance_samples:
            tasks.insert(0, ("performance", lambda: collect_performance(
                r, args.performance_samples, args.sample_interval, running)))
        for mname in MANTICORE_CONTAINERS:
            mc = next((c for c in containers if container_name(c) == mname), None)
            if mc is not None:
                tasks.append((mname, lambda mc=mc, mname=mname: collect_manticore(r, mc, mname)))
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
    first = ["timeseries", "performance", "cassandra", "temporal", "clickhouse", "lifetime logs"]
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
    oom = {}
    try:
        oom = collect_oom_kills(r, containers, deployed_at, r.engine, args.oom_windows)
        print("done: oom kills (%.0f s)" % (time.time() - started))
    except Exception:
        r.note("collector oom-kills failed: %s" % traceback.format_exc(limit=3))
    sig_table = summarise_logs(r)
    checks = []
    try:
        checks = build_verdict(r, repo, containers, deployed_at, oom, expected_limits)
    except Exception:
        r.note("verdict failed: %s" % traceback.format_exc(limit=3))
    r.write_json("manifest.json", r.manifest)
    write_readme(r, args, containers, sig_table, started, oom, checks)

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
