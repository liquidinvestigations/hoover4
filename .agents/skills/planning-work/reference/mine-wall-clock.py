#!/usr/bin/env python3
"""Regenerate the estimation reference class from the harness's own transcripts.

    mine-wall-clock.py ~/.claude/projects/<project-dir>/

Prints the bucket table that `estimating.md` carries, plus the two derived facts under it.
Run it when the table looks stale; a reference class that cannot be re-derived rots exactly
as hand-written day-costs did.

Wall clock for a sub-agent is first-to-last timestamp inside its own transcript. A sub-agent
runs with nobody watching, so unlike a session there are no idle gaps to strip: the span
IS the work. Session spans are reported separately and are only meaningful for sessions that
ran without long human absences, which is why the organizer multiplier below drops any
session whose span exceeds two days.
"""

import json
import pathlib
import re
import statistics as st
import sys
from datetime import datetime

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")

#: How a pass is classified. Order matters: the first match wins, and `edits` breaks the tie
#: between a review that happened to touch a file and an implementation pass.
BUCKETS = (
    ("deploy / remote", r"deploy|hetz|release|remote host"),
    ("verify / browser", r"verify|acceptance|smoke|qa|browser|screenshot"),
    ("read-only review", r"review|forensic|diff-hunt|hygiene|catalogue|mining|inventory|feasib"),
    ("documentation", r"\bdoc|readme|specification|comment"),
)


def stamp(raw):
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def span(path):
    first = last = None
    tools = edits = 0
    for line in path.open(errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        raw = row.get("timestamp")
        if raw:
            try:
                t = stamp(raw)
            except ValueError:
                t = None
            if t:
                first = t if first is None or t < first else first
                last = t if last is None or t > last else last
        for block in (row.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tools += 1
                if block.get("name") in ("Edit", "Write", "NotebookEdit"):
                    edits += 1
    if first is None:
        return None
    return (last - first).total_seconds() / 60.0, tools, edits


def bucket_of(description, edits):
    d = description.lower()
    for name, pattern in BUCKETS:
        if re.search(pattern, d) and (name == "deploy / remote" or edits < 10):
            return name
    return "read-only review" if edits == 0 else "implementation"


runs = []
for p in sorted(ROOT.glob("*/subagents/agent-*.jsonl")):
    s = span(p)
    if not s:
        continue
    minutes, tools, edits = s
    meta_path = p.with_suffix("").with_suffix(".meta.json")
    description = ""
    if meta_path.exists():
        try:
            description = json.loads(meta_path.read_text()).get("description", "")
        except ValueError:
            pass
    runs.append((bucket_of(description, edits), minutes, tools, edits, p.parent.parent.name))

if not runs:
    sys.exit("no sub-agent transcripts under %s" % ROOT)


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * q))]


print(f"{'bucket':20s} {'n':>3s} {'p50':>5s} {'p75':>5s} {'p90':>5s} {'tools p50':>10s}")
for name in ("implementation", "read-only review", "verify / browser",
             "deploy / remote", "documentation"):
    v = [r[1] for r in runs if r[0] == name]
    t = [r[2] for r in runs if r[0] == name]
    if not v:
        continue
    print(f"{name:20s} {len(v):3d} {st.median(v):5.0f} {pct(v,0.75):5.0f} "
          f"{pct(v,0.9):5.0f} {st.median(t):10.0f}")

allmin = [r[1] for r in runs]
alltools = [r[2] for r in runs]
alledits = [r[3] for r in runs]
print()
print("n = %d runs, %.1f h of recorded sub-agent wall clock" % (len(runs), sum(allmin) / 60))
print("a tool call costs %.2f min at the median" % st.median(
    [m / max(1, t) for m, t in zip(allmin, alltools)]))
print("corr(minutes, tool calls) = %.2f   corr(minutes, edits) = %.2f"
      % (st.correlation(allmin, alltools), st.correlation(allmin, alledits)))
print("a pass that writes: %.0f min median   a pass that only reads: %.0f min median"
      % (st.median([m for m, e in zip(allmin, alledits) if e]),
         st.median([m for m, e in zip(allmin, alledits) if not e])))
