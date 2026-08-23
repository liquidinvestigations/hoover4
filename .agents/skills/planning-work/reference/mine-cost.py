#!/usr/bin/env python3
"""What a sub-agent pass costs, and what splitting it would have cost instead.

    mine-cost.py ~/.claude/projects/<project-dir>/ [cap] [reread]

Run this only when a person asks for it. The cost table in `estimating.md` is pinned. It is a
recorded measurement and it is not refreshed as a side effect of planning work. This script
prints numbers and changes no file.

It extends mine-context.py with the billing fields, so a pass has a dollar figure and a
counterfactual dollar figure under a peak-prompt cap. The counterfactual restarts a context
whenever the prompt passes the cap, keeps the first turn's prompt as the new base, and charges
`reread` times that base per restart to pay for reading again what the dropped context held.

Prices are Anthropic first-party, per million tokens, and they go stale. Check them before
quoting a total.
"""
import json, pathlib, statistics as st, sys
from datetime import datetime

ROOT = pathlib.Path(sys.argv[1])
CAP = int(sys.argv[2]) if len(sys.argv) > 2 else 250_000
REREAD = float(sys.argv[3]) if len(sys.argv) > 3 else 0.25
DROP = 50_000

PRICE = {  # in, out, cache_write, cache_read  ($/Mtok)
    "opus":   (5.0, 25.0, 6.25, 0.50),
    "sonnet": (3.0, 15.0, 3.75, 0.30),
    "haiku":  (1.0,  5.0, 1.25, 0.10),
}

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
    turns, stamps, tools = [], [], 0
    model = ""
    for row in seq:
        raw = row.get("timestamp")
        if raw:
            try: stamps.append(datetime.fromisoformat(raw.replace("Z", "+00:00")))
            except ValueError: pass
        if row.get("type") != "assistant":
            continue
        m = row.get("message") or {}
        model = m.get("model") or model
        u = m.get("usage") or {}
        if u:
            turns.append({
                "in": u.get("input_tokens", 0),
                "cw": u.get("cache_creation_input_tokens", 0),
                "cr": u.get("cache_read_input_tokens", 0),
                "out": u.get("output_tokens", 0),
            })
        for b in m.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                tools += 1
    if not turns:
        return None
    prompts = [t["in"] + t["cw"] + t["cr"] for t in turns]
    minutes = (max(stamps) - min(stamps)).total_seconds() / 60 if len(stamps) > 1 else 0.0
    return {"label": label, "model": model, "turns": turns, "prompts": prompts,
            "peak": max(prompts), "tools": tools, "minutes": minutes,
            "compactions": sum(1 for i in range(1, len(prompts)) if prompts[i-1]-prompts[i] > DROP)}

def family(model):
    for k in PRICE:
        if k in (model or ""):
            return k
    return "opus"

def cost(rec, fam=None):
    pi, po, pw, pr = PRICE[fam or family(rec["model"])]
    c = 0.0
    for t in rec["turns"]:
        c += t["in"]*pi/1e6 + t["cw"]*pw/1e6 + t["cr"]*pr/1e6 + t["out"]*po/1e6
    return c

def split_cost(rec, cap, fam=None, reread=0.0):
    """Cost if the pass had restarted a fresh context whenever the prompt passed `cap`.

    A fresh context keeps the first turn's prompt as its base (the work package plus the
    system prompt), and re-accumulates from there. `reread` adds a fraction of the base
    again per restart, to charge for re-reading what the dropped context held.
    """
    pi, po, pw, pr = PRICE[fam or family(rec["model"])]
    base = rec["prompts"][0]
    anchor = rec["prompts"][0]   # prompt size at the last restart
    carried = base      # base of the current segment
    total = 0.0
    segments = 1
    for t, p in zip(rec["turns"], rec["prompts"]):
        scaled = carried + (p - anchor)
        if scaled > cap and p != rec["prompts"][0]:
            segments += 1
            anchor = p
            carried = base * (1.0 + reread)
            scaled = carried
        ratio = scaled / p if p else 1.0
        total += (t["in"]*pi + t["cw"]*pw + t["cr"]*pr) * ratio / 1e6
        total += t["out"]*po/1e6
    return total, segments

def collect():
    found = []
    for path in sorted(ROOT.glob("*/subagents/agent-*.jsonl")):
        r = measure(rows(path), f"{path.parent.parent.name[:8]}/{path.stem[6:14]}")
        if r: found.append(r)
    for path in sorted(ROOT.glob("*.jsonl")):
        groups = {}
        for row in rows(path):
            if not row.get("isSidechain"): continue
            groups.setdefault(row.get("agentId") or "sidechain", []).append(row)
        for name, seq in groups.items():
            r = measure(seq, f"{path.stem[:8]}/{name[:8]}")
            if r: found.append(r)
    return found

found = collect()
found.sort(key=lambda r: -r["peak"])
print(f"{len(found)} sub-agent passes under {ROOT}; cap {CAP:,}\n")
print(f"{'pass':<20}{'peak':>10}{'turns':>7}{'tools':>7}{'$opus':>9}{'$split':>9}{'segs':>6}{'save%':>7}{'min':>7}")
tot_a = tot_s = 0.0
over = []
for r in found:
    a = cost(r, "opus")
    s, segs = split_cost(r, CAP, "opus", reread=REREAD)
    tot_a += a; tot_s += s
    if r["peak"] > CAP: over.append(r)
    print(f"{r['label']:<20}{r['peak']:>10,}{len(r['turns']):>7}{r['tools']:>7}"
          f"{a:>9.2f}{s:>9.2f}{segs:>6}{100*(a-s)/a if a else 0:>6.0f}%{r['minutes']:>7.1f}")
peaks = sorted(r["peak"] for r in found)
n = len(peaks)
print(f"\npeak prompt: p50 {st.median(peaks):,.0f}  p90 {peaks[int(0.9*(n-1))]:,.0f}  max {peaks[-1]:,.0f}")
print(f"passes over the {CAP:,} cap: {len(over)} of {n} ({100*len(over)/n:.0f}%)")
print(f"tokens in passes over the cap: {sum(r['peak'] for r in over):,} peak-sum")
print(f"total cost at opus rates: ${tot_a:,.2f}  split at cap: ${tot_s:,.2f}  "
      f"saved ${tot_a-tot_s:,.2f} ({100*(tot_a-tot_s)/tot_a:.0f}%)")
print(f"\nsaving concentrated in the over-cap passes:")
for r in over:
    a = cost(r, "opus"); s, segs = split_cost(r, CAP, "opus", reread=REREAD)
    print(f"  {r['label']:<20} ${a:>7.2f} -> ${s:>7.2f} in {segs} segments  (saves ${a-s:.2f})")
# what the whole corpus would cost on cheaper models
print(f"\nsame passes at other rates (no split): "
      f"sonnet ${sum(cost(r,'sonnet') for r in found):,.2f}  "
      f"haiku ${sum(cost(r,'haiku') for r in found):,.2f}")
