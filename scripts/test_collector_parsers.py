"""Checks collector parsers against a retained report and controlled verdict inputs.

Usage: python3 test_collector_parsers.py <extracted report root>
Exits 0 when every check passes. Expected values come from the report input.
The verdict cases at the end use only a temporary folder and hand-written log lines.
"""

import datetime
import importlib.util
import json
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("collector", HERE / "collect-debug-report.py")
col = importlib.util.module_from_spec(spec)
spec.loader.exec_module(col)

failures = []


def check(name, got, want):
    ok = got == want
    print("%s %s: got %r, want %r" % ("ok  " if ok else "FAIL", name, got, want))
    if not ok:
        failures.append(name)


# parse_ts: the three time forms the collector reads.
check("docker time", col.parse_ts("2026-09-26T12:23:27.509135817Z").isoformat(),
      "2026-09-26T12:23:27.509135+00:00")
check("journal time", col.parse_ts("2026-09-28T08:37:46.123456+02:00 host kernel: x").isoformat(),
      "2026-09-28T06:37:46.123456+00:00")
check("clickhouse time", col.parse_ts("2026-09-27 05:48:00").isoformat(),
      "2026-09-27T05:48:00+00:00")
check("no time", col.parse_ts("no time here"), None)

# mysql_rows: both output forms.
check("pipe table", col.mysql_rows("+---+\n| a | rt |\n| b | rt |\n+---+"), [["a", "rt"], ["b", "rt"]])
check("tabs", col.mysql_rows("a\trt\nb\trt\n"), [["a", "rt"], ["b", "rt"]])

# collect_oom_kills over the production journal, converted to the ISO form the new script asks
# journalctl for. Journal times on that host are UTC+2.
root = pathlib.Path(sys.argv[1])
months = {m: i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
iso_lines = []
for line in (root / "host" / "journal-oom-kills-30d.txt").read_text().splitlines():
    m = re.match(r"(\w{3}) +(\d+) (\d\d:\d\d:\d\d) (.*)", line)
    if m:
        iso_lines.append("2026-%02d-%02dT%s.000000+02:00 %s" % (
            months[m.group(1)], int(m.group(2)), m.group(3), m.group(4)))

ids = {}
for line in (root / "engine" / "container-ids.txt").read_text().splitlines():
    parts = line.split()
    if len(parts) >= 2:
        ids[parts[0]] = parts[1]
containers = [{"Id": cid, "Name": "/" + name} for cid, name in ids.items()]

with tempfile.TemporaryDirectory() as tmp:
    r = col.Report(tmp, redact=True, default_timeout=10)
    (pathlib.Path(tmp) / "host").mkdir()
    (pathlib.Path(tmp) / "host" / "journal-oom-kills-30d.txt").write_text("\n".join(iso_lines))
    deployed = col.parse_ts("2026-09-26T12:24:09Z")
    out = col.collect_oom_kills(r, containers, deployed, None, 0)
    check("manticore kills since deploy", out["manticore"]["kills_since_deploy"], 1679)
    check("worker kills since deploy", out["hoover4-worker"]["kills_since_deploy"], 239)
    check("ocr-pdf kills since deploy", out["hoover4-ocr-pdf"]["kills_since_deploy"], 1)
    check("ocr-pdf max anon MB", out["hoover4-ocr-pdf"]["max_anon_rss_mb"], 195557)
    check("worker first kill", out["hoover4-worker"]["first"], "2026-09-26T13:44:05Z")


def verdict_row(checks, name):
    return next((c for c in checks if c["check"] == name), {})


# A worker log longer than the tail that logs/ keeps. The one deadlock line is near the start,
# after the deployment, so only a count over the whole log finds it.
with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    deployed = col.parse_ts("2026-10-01T09:00:00Z")
    start = datetime.datetime(2026, 10, 1, 8, 59, 0)
    lines = []
    for i in range(400000):
        ts = (start + datetime.timedelta(milliseconds=i)).strftime("%Y-%m-%dT%H:%M:%S.%f")
        text = "worker heartbeat %d" % i
        if i == 5:
            text = "Potential deadlock detected in workflow before the deployment"
        if i == 70000:
            text = "Potential deadlock detected in workflow abc"
        lines.append("%s000Z %s\n" % (ts, text))
    logs = tmp / "engine-logs"
    logs.mkdir()
    (logs / "hoover4-worker.log").write_text("".join(lines))
    engine = tmp / "fake-engine"
    engine.write_text('#!/bin/sh\nif [ "$1" = logs ]; then cat "%s/$3.log"; fi\n' % logs)
    engine.chmod(0o755)
    root = tmp / "report"
    r = col.Report(root, redact=True, default_timeout=10)
    r.engine = str(engine)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "logs" / "hoover4-worker.log").write_text("".join(lines[-300000:]))
    col.collect_lifetime_logs(r, str(engine), {"hoover4-worker"}, 300000, deployed)
    counts = json.loads((root / "summary" / "verdict-log-counts.json").read_text())
    entry = counts["containers"]["hoover4-worker"]
    check("whole log lines read", entry["lines_read"], 400000)
    check("deadlock matches since deploy", entry["needles"]["Potential deadlock"], 1)
    check("tail count misses it", col._count_since(root / "logs" / "hoover4-worker.log",
                                                    ("Potential deadlock",), deployed), 0)
    checks = col.build_verdict(r, tmp, [], deployed, {}, {})
    check("deadlock check fails", verdict_row(checks, "workflow deadlocks").get("status"), "FAIL")
    check("no rotation warning", [c["check"] for c in checks
                                  if c["check"].startswith("log reaches")], [])

    # The first line read is later than the deployment: Docker rotated the start away.
    late = col.parse_ts("2026-10-01T08:00:00Z")
    col.collect_lifetime_logs(r, str(engine), {"hoover4-worker"}, 300000, late)
    checks = col.build_verdict(r, tmp, [], late, {}, {})
    check("rotation warning", verdict_row(
        checks, "log reaches the deployment: lifetime-logs/hoover4-worker.log").get("status"),
        "WARN")

    # Without the counts file the check reads the tail and says so. The tail starts after the
    # deployment, so it did not read every line since then.
    (root / "summary" / "verdict-log-counts.json").unlink()
    checks = col.build_verdict(r, tmp, [], deployed, {}, {})
    row = verdict_row(checks, "workflow deadlocks")
    check("tail fallback status", row.get("status"), "UNKNOWN")
    check("tail fallback detail", "tail only" in row.get("detail", ""), True)


def fake_engine(folder, body):
    engine = folder / "fake-engine"
    engine.write_text("#!/bin/sh\n" + body + "\n")
    engine.chmod(0o755)
    return str(engine)


# Short worker logs. deployed_at is 09:00:00, and each expected value comes from the rules
# in the script: a read counts only when `logs` exits 0, a line with no time takes the time
# of the line before it, and a read that starts after deployed_at says UNKNOWN.
with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    deployed = col.parse_ts("2026-10-01T09:00:00Z")
    before_after = ("2026-10-01T08:59:00.000000000Z worker heartbeat\n"
                    "Potential deadlock detected, no time, before the deployment\n"
                    "2026-10-01T09:01:00.000000000Z Traceback (most recent call last):\n"
                    "Potential deadlock detected, no time, after the deployment\n")
    quiet = "2026-10-01T08:59:00.000000000Z worker heartbeat\n"

    # A failed read: the engine prints an error line and exits 1.
    root = tmp / "failed"
    r = col.Report(root, redact=True, default_timeout=10)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "logs" / "hoover4-worker.log").write_text(quiet)
    engine = fake_engine(tmp, 'echo "Error: no such container"; exit 1')
    col.collect_lifetime_logs(r, engine, {"hoover4-worker"}, 100, deployed, watch_names=False)
    counts = json.loads((root / "summary" / "verdict-log-counts.json").read_text())
    check("failed read has no counts", "hoover4-worker" in counts["containers"], False)
    check("failed read recorded", counts["failed"].get("hoover4-worker"), "exit 1")
    row = verdict_row(col.build_verdict(r, tmp, [], deployed, {}, {}), "workflow deadlocks")
    check("failed read falls back", (row.get("status"), row.get("detail")),
          ("PASS", "the whole-log read failed (exit 1), 0 lines since deploy, tail only"))

    # A line with no time counts when the line with a time before it is after deployed_at.
    logs = tmp / "engine-logs"
    logs.mkdir()
    (logs / "hoover4-worker.log").write_text(before_after)
    engine = fake_engine(tmp, 'cat "%s/$3.log"' % logs)
    root = tmp / "untimed"
    r = col.Report(root, redact=True, default_timeout=10)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "logs" / "hoover4-worker.log").write_text(before_after)
    col.collect_lifetime_logs(r, engine, {"hoover4-worker"}, 100, deployed, watch_names=False)
    counts = json.loads((root / "summary" / "verdict-log-counts.json").read_text())
    check("untimed line, whole log",
          counts["containers"]["hoover4-worker"]["needles"]["Potential deadlock"], 1)
    check("untimed line, tail", col._count_since(root / "logs" / "hoover4-worker.log",
                                                 ("Potential deadlock",), deployed), 1)

    # A whole log whose first line is later than deployed_at, with no match in it.
    (logs / "hoover4-worker.log").write_text(
        "2026-10-01T09:05:00.000000000Z worker heartbeat\n")
    root = tmp / "late"
    r = col.Report(root, redact=True, default_timeout=10)
    col.collect_lifetime_logs(r, engine, {"hoover4-worker"}, 100, deployed, watch_names=False)
    checks = col.build_verdict(r, tmp, [], deployed, {}, {})
    check("late whole log status", verdict_row(checks, "workflow deadlocks").get("status"),
          "UNKNOWN")
    check("late whole log warning", verdict_row(
        checks, "log reaches the deployment: lifetime-logs/hoover4-worker.log").get("status"),
        "WARN")

# A container that restarted after the deployment time: the detail names its start time.
with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    r = col.Report(tmp / "report", redact=True, default_timeout=10)
    worker = {"Name": "/hoover4-worker", "RestartCount": 3,
              "State": {"Running": True, "StartedAt": "2026-10-01T09:04:12.123456789Z"}}
    checks = col.build_verdict(r, tmp, [worker], col.parse_ts("2026-10-01T09:00:00Z"), {}, {})
    row = verdict_row(checks, "restarts since deploy")
    check("restart status", row.get("status"), "FAIL")
    check("restart detail", row.get("detail"), "hoover4-worker=3 (started 2026-10-01T09:04:12Z)")

    # deployed_at is the worker's own start time, as printed, cut to seconds, or one second
    # earlier. Only a start later in whole seconds fails.
    for label, dep, want in [
            ("start as printed", "2026-10-01T09:04:12.123456789Z", ("PASS", "no restarts")),
            ("start cut to seconds", "2026-10-01T09:04:12Z", ("PASS", "no restarts")),
            ("one second before the start", "2026-10-01T09:04:11Z",
             ("FAIL", "hoover4-worker=3 (started 2026-10-01T09:04:12Z)"))]:
        row = verdict_row(col.build_verdict(r, tmp, [worker], col.parse_ts(dep), {}, {}),
                          "restarts since deploy")
        check("restart, " + label, (row.get("status"), row.get("detail")), want)

# The quantization parser, on the exact text that Manticore 14.1.0 prints.
DDL = ("embedding float_vector knn_type='hnsw' knn_dims='384' hnsw_similarity='COSINE' "
       "quantization='1BIT'")
check("quantization 1BIT", col.parse_quantization(DDL), "1bit")
check("quantization absent", col.parse_quantization(DDL.replace(" quantization='1BIT'", "")),
      None)
try:
    col.parse_quantization(DDL.replace("1BIT", "2BIT"))
    got = "no error"
except ValueError:
    got = "ValueError"
check("quantization 2BIT", got, "ValueError")
check("knn_dims", col.parse_knn_setting(DDL, "knn_dims"), 384)

# Bytes a vector at 384 dimensions and hnsw_m 16: data + 8 x 16 + 40 = data + 168.
# float 4 x 384 + 168 = 1704, 8bit 384 + 168 = 552, 1bit 384 / 8 + 168 = 216.
check("bytes a vector", [col.hnsw_bytes_per_vector(384, q) for q in (None, "8bit", "1bit")],
      [1704, 552, 216])

# The budget against a limit of 32 GiB = 34,359,738,368 bytes. The reserve is
# 34,359,738,368 // 10 = 3,435,973,836. One 1bit table of 384 dimensions, 216 bytes a vector,
# so the resident size and the largest merge are both n x 216, and the RAM chunks are
# 1 x 134,217,728. The fixed terms are 134,217,728 + 3,435,973,836 = 3,570,191,564.
LIMIT = 32 * 2**30


def one_table(n, quant="1bit"):
    return [{"table": "c_1_vectors", "indexed_documents": str(n), "knn_dims": "384",
             "hnsw_m": "16", "quantization": quant}]


# n = 30,000,000: 2 x 6,480,000,000 + 3,570,191,564 = 16,530,191,564, which is 48 % of the
# limit, so PASS.
status, detail = col.vector_budget(one_table(30000000), LIMIT)
check("budget at 48 %", (status, detail.split(":")[0]),
      ("PASS", "need 16530191564 of 34359738368 bytes (48%)"))
# n = 63,000,000: 2 x 13,608,000,000 + 3,570,191,564 = 30,786,191,564, which is 89.6 %, above
# 85 %, so WARN.
status, detail = col.vector_budget(one_table(63000000), LIMIT)
check("budget at 90 %", (status, detail.split(":")[0]),
      ("WARN", "need 30786191564 of 34359738368 bytes (90%)"))
# n = 72,000,000: 2 x 15,552,000,000 + 3,570,191,564 = 34,674,191,564, above the limit, so FAIL.
status, detail = col.vector_budget(one_table(72000000), LIMIT)
check("budget above the limit", (status, detail.split(":")[0]),
      ("FAIL", "need 34674191564 of 34359738368 bytes (101%)"))
check("budget detail names each term", detail.split(": ", 1)[1],
      "resident 15552000000 in 1 tables, RAM chunks 134217728, largest merge 15552000000, "
      "reserve 3435973836")
# A float table of the same 30,000,000 vectors is 1704 bytes a vector: 2 x 51,120,000,000 +
# 3,570,191,564 = 105,810,191,564, so FAIL. The 1bit case above passes at 48 %.
check("budget of a float table", col.vector_budget(one_table(30000000, "none"), LIMIT)[0],
      "FAIL")
# A missing term: an unrecognised quantization, no indexed_documents, or no limit.
check("budget, unrecognised quantization",
      col.vector_budget(one_table(1000, "unrecognised quantization '2BIT'"), LIMIT)[0],
      "UNKNOWN")
check("budget, no count", col.vector_budget(one_table(""), LIMIT)[0], "UNKNOWN")
check("budget, no limit", col.vector_budget(one_table(1000), None)[0], "UNKNOWN")


def write_tsv(path, head, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(["\t".join(head)] + ["\t".join(r) for r in rows]) + "\n")


# The text-container check and the quantization check, through build_verdict.
with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    root = tmp / "report"
    r = col.Report(root, redact=True, default_timeout=10)
    text_c = {"Name": "/manticore", "RestartCount": 0, "State": {"Running": True}}
    vec_c = {"Name": "/manticore-vectors", "RestartCount": 0, "State": {"Running": True},
             "HostConfig": {"Memory": LIMIT}}
    status_head = ["table", "indexed_documents"]
    vec_head = ["table", "indexed_documents", "knn_dims", "hnsw_m", "quantization"]

    # Before the migrate drop: the text container still lists a _vectors table.
    write_tsv(root / "manticore" / "table-status.tsv", status_head,
              [["c_1_pages", "10"], ["c_1_vectors", "10"]])
    write_tsv(root / "manticore-vectors" / "vector-tables.tsv", vec_head,
              [["c_1_vectors", "30000000", "384", "16", "1bit"],
               ["d_1_vectors", "10", "384", "16", "none"]])
    checks = col.build_verdict(r, tmp, [text_c, vec_c], None, {}, {})
    row = verdict_row(checks, "no _vectors tables in the text container")
    check("text container has vectors", (row.get("status"), row.get("detail")),
          ("FAIL", "1 on manticore: c_1_vectors"))
    row = verdict_row(checks, "vector tables quantized")
    check("float table not quantized", (row.get("status"), row.get("detail")),
          ("FAIL", "not 1bit: d_1_vectors=none"))

    # After the drop and the rebuild.
    write_tsv(root / "manticore" / "table-status.tsv", status_head, [["c_1_pages", "10"]])
    write_tsv(root / "clickhouse" / "vectors-by-collection.tsv",
              ["collection", "embedding_model", "rows", "dims"],
              [["c", "model", "30000000", "384"]])
    write_tsv(root / "manticore-vectors" / "vector-tables.tsv", vec_head,
              [["c_1_vectors", "30000000", "384", "16", "1bit"]])
    checks = col.build_verdict(r, tmp, [text_c, vec_c], None, {}, {})
    check("text container clean",
          verdict_row(checks, "no _vectors tables in the text container").get("status"), "PASS")
    check("all 1bit", verdict_row(checks, "vector tables quantized").get("status"), "PASS")
    check("budget row", verdict_row(checks, "vector memory budget").get("status"), "PASS")

    write_tsv(root / "clickhouse" / "vectors-by-collection.tsv",
              ["collection", "embedding_model", "rows", "dims"],
              [["c", "model", "30000000", "384"], ["d", "model", "1", "384"]])
    checks = col.build_verdict(r, tmp, [text_c, vec_c], None, {}, {})
    check("source collection without a table",
          verdict_row(checks, "vector tables quantized").get("status"), "FAIL")
    write_tsv(root / "clickhouse" / "vectors-by-collection.tsv",
              ["collection", "embedding_model", "rows", "dims"],
              [["c", "model", "30000000", "384"]])

    # An unrecognised value is UNKNOWN, never float.
    write_tsv(root / "manticore-vectors" / "vector-tables.tsv", vec_head,
              [["c_1_vectors", "10", "384", "16", "unrecognised quantization '2BIT'"]])
    checks = col.build_verdict(r, tmp, [text_c, vec_c], None, {}, {})
    check("unrecognised quantization",
          verdict_row(checks, "vector tables quantized").get("status"), "UNKNOWN")
    check("unrecognised budget",
          verdict_row(checks, "vector memory budget").get("status"), "UNKNOWN")

    # No manticore-vectors container: its rows name it as missing, and an expected limit fails.
    checks = col.build_verdict(r, tmp, [text_c], None, {}, {"manticore-vectors": LIMIT})
    check("vectors container missing", (verdict_row(checks, "manticore-vectors answers").get(
        "status"), verdict_row(checks, "manticore-vectors answers").get("detail")),
        ("FAIL", "container manticore-vectors not found"))
    check("missing expected limit", verdict_row(checks, "memory limits").get("status"), "FAIL")
    check("budget without container",
          verdict_row(checks, "vector memory budget").get("detail"),
          "container manticore-vectors not found")

    # A valid empty vector inventory is a failure when ClickHouse has source vectors.
    write_tsv(root / "manticore-vectors" / "vector-tables.tsv", vec_head, [])
    write_tsv(root / "clickhouse" / "vectors-by-collection.tsv",
              ["collection", "embedding_model", "rows", "dims"],
              [["c", "model", "2", "384"]])
    checks = col.build_verdict(r, tmp, [text_c, vec_c], None, {}, {})
    check("missing vector tables with source vectors",
          verdict_row(checks, "vector tables quantized").get("status"), "FAIL")
    check("missing vector tables budget",
          verdict_row(checks, "vector memory budget").get("status"), "FAIL")

    # A cgroup file with no parseable memory limit cannot prove headroom.
    worker = {"Name": "/hoover4-worker", "RestartCount": 0,
              "State": {"Running": True}}
    cg = root / "containers" / "hoover4-worker" / "cgroup-host.txt"
    cg.parent.mkdir(parents=True, exist_ok=True)
    cg.write_text("== memory.max\nmax\nanon 1\n")
    checks = col.build_verdict(r, tmp, [worker], None, {}, {})
    check("unreadable cgroup limit",
          verdict_row(checks, "memory headroom (anon over limit, fail above 85%)").get(
              "status"), "UNKNOWN")

# A failed SHOW TABLES keeps its command evidence and creates no table inventory.
with tempfile.TemporaryDirectory() as tmp:
    r = col.Report(tmp, redact=True, default_timeout=10)
    r.engine = "fake-engine"

    def failed_tables(name, argv, **_kwargs):
        failed = argv[-1] == "SHOW TABLES"
        r.record({"file": name, "exit_code": 1 if failed else 0})
        if name:
            r.write_text(name, "error" if failed else "")
        return "error" if failed else "1"

    r.run = failed_tables
    col.collect_manticore(r, {"State": {"Running": True}}, "manticore-vectors")
    check("failed SHOW TABLES leaves no status inventory",
          (r.root / "manticore-vectors" / "table-status.tsv").exists(), False)
    check("failed SHOW TABLES keeps command evidence",
          (r.root / "manticore-vectors" / "tables.txt").read_text(), "error")

print("failures: %d" % len(failures))
sys.exit(1 if failures else 0)
