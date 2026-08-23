#!/usr/bin/env python3
"""Report how much context a sub-agent pass actually uses.

    mine-context.py ~/.claude/projects/<project-dir>/

Run this only when a person asks for it. The context table in `estimating.md` is pinned. It is
a recorded measurement and it is not refreshed as a side effect of planning work. This script
prints numbers and changes no file.

The estimation reference class measures how long a pass runs. This measures how much of the
model's context window a pass consumes, which is the other limit on how much work one pass
can carry. It reads two shapes of transcript. A modern sub-agent file under
`<session>/subagents/agent-*.jsonl`, and an older sidechain interleaved into the session
file with `isSidechain: true`.

Both shapes are written by one harness. Another harness, another editor, or a fresh checkout
produces a small sample or none at all. A small sample is worse than the pinned table, because
it looks like a measurement. MIN_SAMPLE below is the floor under which this script says so and
stops offering percentiles.

Peak prompt size is `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` on
the largest assistant turn. That sum is the whole prompt the model saw, cached or not. A drop
of more than 50,000 tokens between consecutive turns is counted as a compaction.
"""

import json
import pathlib
import statistics as st
import sys
from datetime import datetime

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
DROP = 50_000

#: Below this many passes the distribution is noise. The pinned table stands instead.
MIN_SAMPLE = 20


def rows(path):
    for line in path.open(errors="replace"):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            yield json.loads(line)
        except ValueError:
            continue


def measure(seq, label):
    """Return one record per pass, or None when the sequence holds no assistant turn."""
    prompts, outputs, stamps, tools, edits = [], 0, [], 0, 0
    for row in seq:
        raw = row.get("timestamp")
        if raw:
            try:
                stamps.append(datetime.fromisoformat(raw.replace("Z", "+00:00")))
            except ValueError:
                pass
        if row.get("type") != "assistant":
            continue
        message = row.get("message") or {}
        usage = message.get("usage") or {}
        if usage:
            prompts.append(
                usage.get("input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0)
            )
            outputs += usage.get("output_tokens", 0)
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tools += 1
                if block.get("name") in ("Edit", "Write", "NotebookEdit"):
                    edits += 1
    if not prompts:
        return None
    compactions = sum(
        1 for i in range(1, len(prompts)) if prompts[i - 1] - prompts[i] > DROP
    )
    minutes = (max(stamps) - min(stamps)).total_seconds() / 60 if len(stamps) > 1 else 0.0
    return {
        "label": label,
        "peak": max(prompts),
        "turns": len(prompts),
        "output": outputs,
        "tools": tools,
        "edits": edits,
        "compactions": compactions,
        "minutes": minutes,
    }


def collect():
    found = []
    for path in sorted(ROOT.glob("*/subagents/agent-*.jsonl")):
        record = measure(rows(path), f"{path.parent.parent.name[:8]}/{path.stem[6:14]}")
        if record:
            found.append(record)
    for path in sorted(ROOT.glob("*.jsonl")):
        groups = {}
        for row in rows(path):
            if not row.get("isSidechain"):
                continue
            groups.setdefault(row.get("agentId") or "sidechain", []).append(row)
        for name, seq in groups.items():
            record = measure(seq, f"{path.stem[:8]}/{name[:8]}")
            if record:
                found.append(record)
    return found


def main():
    found = collect()
    if not found:
        print(f"no sub-agent transcripts under {ROOT}")
        return
    found.sort(key=lambda r: -r["peak"])
    print(f"{len(found)} sub-agent passes under {ROOT}\n")
    print(f"{'pass':<20}{'peak ctx':>10}{'turns':>7}{'output':>9}{'tools':>7}{'edits':>7}{'compact':>9}{'min':>7}")
    for record in found:
        print(
            f"{record['label']:<20}{record['peak']:>10,}{record['turns']:>7}"
            f"{record['output']:>9,}{record['tools']:>7}{record['edits']:>7}"
            f"{record['compactions']:>9}{record['minutes']:>7.1f}"
        )
    peaks = sorted(r["peak"] for r in found)
    if len(found) < MIN_SAMPLE:
        print(f"\n{len(found)} passes is below the {MIN_SAMPLE}-pass floor. No percentiles are "
              f"printed, because a distribution this thin reads like a measurement and is not "
              f"one. Keep the pinned table in estimating.md.")
        return
    print(f"\npeak prompt tokens: p50 {st.median(peaks):,.0f}  "
          f"p90 {peaks[int(0.9 * (len(peaks) - 1))]:,.0f}  max {peaks[-1]:,.0f}")
    print(f"passes that compacted at all: {sum(1 for r in found if r['compactions'])} of {len(found)}")
    print(f"total tool calls {sum(r['tools'] for r in found):,}, "
          f"total edits {sum(r['edits'] for r in found):,}")
    print("\nThis changed no file. The table in estimating.md is pinned and is edited only "
          "when a person asks for it.")


main()
