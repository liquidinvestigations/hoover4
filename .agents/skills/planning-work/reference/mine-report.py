#!/usr/bin/env python3
"""Print the distributions that a reference class is made of.

    report.py [passes.jsonl] [--kind pass] [--section all]

Reads the normalized records `extract.py` writes and prints every table the estimating
reference needs. It changes no file, and it prints a sample count beside every row so a
thin row cannot be read as a measurement.

SECTIONS

    buckets   minutes, tool calls and peak context by bucket, per harness and pooled
    models    the same by model, which is what decides whether one pack of numbers holds
    growth    prompt growth per tool call, which converts a context cap into a budget
    fixed     the fixed cost of a pass, measured as its prologue plus its epilogue
    rates     seconds a tool call, and the correlations that say what the size unit is

HOW THE FIXED COST IS MEASURED

Calls before a pass's first code write are it reading its package and orienting. Calls
after its last code write are it running checks and writing its report. Neither produces
work, so their sum is the fixed cost of being a pass. The rest is marginal.

A pass's own report is a prose write, so the measurement uses code writes alone. Counting
every write puts the report inside the work and leaves an epilogue of about one call.

The marginal figure this produces is the cost of the FIRST task, which pays to read the
tree. A later task in the same context is cheaper, and no pass recorded here carried more
than about one task, so that discount cannot be measured here. It is applied in
`estimating.md` as a ratio from a corpus that did measure it.
"""

import argparse
import collections
import json
import math
import statistics as st
import sys


def pct(values, q):
    values = sorted(values)
    if not values:
        return float("nan")
    return values[min(len(values) - 1, int(len(values) * q))]


def field(records, name):
    return [r[name] for r in records if r.get(name) is not None]


def line(label, values, width=26):
    if not values:
        print(f"{label:<{width}} {'-':>5}")
        return
    print(f"{label:<{width}} {len(values):5d} {st.median(values):9.0f} "
          f"{pct(values, 0.75):9.0f} {pct(values, 0.9):9.0f} {max(values):9.0f}")


def header(title, unit):
    print(f"\n{title}")
    print(f"{'':26} {'n':>5} {unit+' p50':>9} {'p75':>9} {'p90':>9} {'max':>9}")


BUCKETS = ("implementation", "read-only review", "documentation", "operational")


def section_buckets(records):
    print("\n" + "=" * 78)
    print("BUCKETS")
    print("=" * 78)
    for harness in ("claude", "codex", "kimi", "cursor", "ALL"):
        rows = records if harness == "ALL" else [
            r for r in records if r["harness"] == harness]
        if not rows:
            continue
        print(f"\n-- {harness} --")
        print(f"{'bucket':<20} {'n':>4} {'min p50':>8} {'p90':>7} "
              f"{'calls p50':>10} {'p90':>7} {'ctx p50':>9} {'p90':>9}")
        for bucket in BUCKETS:
            group = [r for r in rows if r["bucket"] == bucket]
            if not group:
                continue
            minutes = field(group, "minutes")
            calls = field(group, "tool_calls")
            ctx = field(group, "peak_context")
            def show(values, q):
                return f"{pct(values, q):.0f}" if values else "-"
            print(f"{bucket:<20} {len(group):4d} {show(minutes,0.5):>8} "
                  f"{show(minutes,0.9):>7} {show(calls,0.5):>10} "
                  f"{show(calls,0.9):>7} {show(ctx,0.5):>9} {show(ctx,0.9):>9}")


def section_models(records):
    print("\n" + "=" * 78)
    print("MODELS")
    print("=" * 78)
    print("One row a model. The spread across rows is what decides whether one pack of")
    print("numbers holds or whether the models have to be grouped into bins.\n")
    print(f"{'model':<28} {'harness':<8} {'n':>4} {'min p50':>8} {'calls p50':>10} "
          f"{'ctx p50':>9} {'grow/call':>10}")
    by_model = collections.defaultdict(list)
    for r in records:
        if r.get("model"):
            by_model[(r["model"], r["harness"])].append(r)
    for (model, harness), group in sorted(
            by_model.items(), key=lambda kv: -len(kv[1])):
        minutes = field(group, "minutes")
        calls = field(group, "tool_calls")
        ctx = field(group, "peak_context")
        growth = growth_rates(group)
        def show(values, q=0.5):
            return f"{pct(values, q):.0f}" if values else "-"
        print(f"{model:<28} {harness:<8} {len(group):4d} {show(minutes):>8} "
              f"{show(calls):>10} {show(ctx):>9} {show(growth):>10}")


def growth_rates(records):
    """Prompt tokens added per tool call, one figure a pass."""
    out = []
    for r in records:
        peak = r.get("peak_context")
        base = r.get("first_context")
        calls = r.get("tool_calls")
        if not peak or base is None or not calls:
            continue
        if r.get("peak_is_final_only"):
            continue
        rate = (peak - base) / calls
        if rate > 0:
            out.append(rate)
    return out


def section_growth(records):
    print("\n" + "=" * 78)
    print("GROWTH PER TOOL CALL")
    print("=" * 78)
    print("Peak prompt minus first prompt, over the pass's tool calls. This is the one")
    print("rate that has been measured to transfer between repositories.\n")
    header("growth, tokens a call", "rate")
    for harness in ("claude", "codex", "kimi", "cursor"):
        rows = [r for r in records if r["harness"] == harness]
        line(f"  {harness}", growth_rates(rows))
    allrates = growth_rates(records)
    line("  ALL", allrates)
    if not allrates:
        return
    print("\nFirst-turn prompt, which the cap must allow for before any call:")
    header("first prompt", "tok")
    for harness in ("claude", "codex", "kimi", "cursor"):
        rows = [r for r in records if r["harness"] == harness]
        line(f"  {harness}", field(rows, "first_context"))
    base = st.median(field(records, "first_context") or [0])
    print("\nA context cap converts into a tool-call budget at the median rate:")
    print(f"{'cap':>10} {'calls at p50 rate':>18} {'at p90 rate':>14} "
          f"{'packing target':>16}")
    p50 = st.median(allrates)
    p90 = pct(allrates, 0.9)
    for cap in (150_000, 250_000, 350_000):
        at50 = cap / p50
        at90 = cap / p90
        target = (cap - base) / p50
        print(f"{cap:>10,} {at50:>18.0f} {at90:>14.0f} {target:>16.0f}")


def section_fixed(records):
    print("\n" + "=" * 78)
    print("THE FIXED COST OF A PASS")
    print("=" * 78)
    print("Prologue is calls before the first code write. Epilogue is calls after the")
    print("last one. Their sum buys no work. The remainder is one task's marginal cost,")
    print("and it is the cost of the first task, which pays to read the tree.\n")
    print(f"{'harness':<10} {'bucket':<18} {'n':>4} {'calls':>6} {'prolog':>7} "
          f"{'epilog':>7} {'fixed':>6} {'marg':>6} {'ratio':>6} {'work':>6}")
    for harness in ("claude", "codex", "cursor", "ALL"):
        for bucket in ("implementation", "operational"):
            rows = [r for r in records
                    if r["bucket"] == bucket
                    and (harness == "ALL" or r["harness"] == harness)
                    and r.get("calls_before_first_code_write") is not None]
            if len(rows) < 3:
                continue
            pro = [r["calls_before_first_code_write"] for r in rows]
            epi = [r["calls_after_last_code_write"] for r in rows]
            tot = [r["tool_calls"] for r in rows]
            fixed = [p + e for p, e in zip(pro, epi)]
            f50 = st.median(fixed)
            t50 = st.median(tot)
            marg = t50 - f50
            print(f"{harness:<10} {bucket:<18} {len(rows):4d} {t50:6.0f} "
                  f"{st.median(pro):7.0f} {st.median(epi):7.0f} {f50:6.0f} "
                  f"{marg:6.0f} {marg / max(f50, 1):6.2f} "
                  f"{marg / max(t50, 1) * 100:5.0f}%")
    print("\nA read-only pass writes nothing, so its fixed cost cannot be measured this")
    print("way. Its whole call count is the row below.")
    header("read-only review, calls", "calls")
    for harness in ("claude", "codex", "cursor"):
        rows = [r for r in records
                if r["harness"] == harness and r["bucket"] == "read-only review"]
        line(f"  {harness}", field(rows, "tool_calls"))


def section_agents(records):
    print("\n" + "=" * 78)
    print("AGENT TYPES")
    print("=" * 78)
    print("The bucket rule files a reviewer that wrote its report under documentation,")
    print("because the rule looks at what was produced. The agent type is what decides a")
    print("pass's tool-call budget, so it is reported beside the bucket.\n")
    print(f"{'agent':<20} {'harness':<8} {'n':>4} {'min p50':>8} {'calls p50':>10} "
          f"{'p90':>7} {'ctx p50':>9}")
    by_agent = collections.defaultdict(list)
    for r in records:
        by_agent[(r.get("agent") or "unnamed", r["harness"])].append(r)
    for (agent, harness), group in sorted(
            by_agent.items(), key=lambda kv: -len(kv[1])):
        minutes = field(group, "minutes")
        calls = field(group, "tool_calls")
        ctx = field(group, "peak_context")
        def show(values, q=0.5):
            return f"{pct(values, q):.0f}" if values else "-"
        print(f"{agent:<20} {harness:<8} {len(group):4d} {show(minutes):>8} "
              f"{show(calls):>10} {show(calls,0.9):>7} {show(ctx):>9}")


def section_coordinator(path, kind):
    """What a session spends, and how much of that one pass costs it."""
    print("\n" + "=" * 78)
    print("THE COORDINATOR")
    print("=" * 78)
    print("A session that launches passes spends its own calls on writing packages and")
    print("reading diffs. That cost is paid once a pass and it belongs in a plan's")
    print("estimate, because it is the largest part of what packing removes.\n")
    records = [json.loads(line) for line in open(path)]
    sessions = [r for r in records if r["kind"] == "session"]
    passes = [r for r in records if r["kind"] == "pass"]
    launched = collections.Counter(r["session"] for r in passes)
    rows = [(s, launched.get(s["id"], 0)) for s in sessions]
    with_passes = [(s, n) for s, n in rows if n]
    print(f"{'harness':<10} {'sessions':>9} {'with passes':>12} {'calls p50':>10} "
          f"{'passes p50':>11} {'calls a pass':>13} {'span min p50':>13}")
    for harness in ("claude", "codex", "kimi", "cursor", "ALL"):
        group = with_passes if harness == "ALL" else [
            (s, n) for s, n in with_passes if s["harness"] == harness]
        every = sessions if harness == "ALL" else [
            s for s in sessions if s["harness"] == harness]
        if not group:
            print(f"{harness:<10} {len(every):9d} {0:12d}")
            continue
        calls = [s["tool_calls"] for s, _ in group if s.get("tool_calls")]
        counts = [n for _, n in group]
        per = [s["tool_calls"] / n for s, n in group if s.get("tool_calls")]
        spans = [s["minutes"] / n for s, n in group if s.get("minutes")]
        print(f"{harness:<10} {len(every):9d} {len(group):12d} "
              f"{st.median(calls) if calls else 0:10.0f} {st.median(counts):11.0f} "
              f"{st.median(per) if per else 0:13.1f} "
              f"{st.median(spans) if spans else 0:13.0f}")


def section_rates(records):
    print("\n" + "=" * 78)
    print("RATES")
    print("=" * 78)
    for harness in ("claude", "codex", "kimi", "cursor", "ALL"):
        rows = records if harness == "ALL" else [
            r for r in records if r["harness"] == harness]
        pairs = [(r["minutes"], r["tool_calls"]) for r in rows
                 if r.get("minutes") and r.get("tool_calls")]
        if len(pairs) < 3:
            continue
        seconds = [m * 60 / c for m, c in pairs]
        minutes = [p[0] for p in pairs]
        calls = [p[1] for p in pairs]
        corr = st.correlation(minutes, calls) if len(pairs) > 2 else float("nan")
        print(f"{harness:<8} n={len(pairs):4d}  seconds a call p50={st.median(seconds):6.1f}"
              f"  corr(minutes, calls)={corr:5.2f}")
    print()
    compacted = [r for r in records if r.get("compactions")]
    measurable = [r for r in records if r.get("compactions") is not None]
    print(f"passes that compacted at all: {len(compacted)} of {len(measurable)} measurable")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", nargs="?", default="passes.jsonl")
    parser.add_argument("--kind", default="pass",
                        choices=("pass", "session", "guard", "any"))
    parser.add_argument("--section", default="all",
                        choices=("all", "buckets", "models", "growth", "fixed",
                                 "rates", "agents", "coordinator"))
    args = parser.parse_args()

    records = [json.loads(line) for line in open(args.source)]
    if args.kind != "any":
        records = [r for r in records if r["kind"] == args.kind]
    if not records:
        sys.exit(f"no records of kind {args.kind} in {args.source}")

    print(f"{len(records)} records of kind {args.kind} from {args.source}")
    counts = collections.Counter(r["harness"] for r in records)
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    run = {
        "buckets": section_buckets,
        "models": section_models,
        "agents": section_agents,
        "growth": section_growth,
        "fixed": section_fixed,
        "rates": section_rates,
        "coordinator": lambda _: section_coordinator(args.source, args.kind),
    }
    if args.section == "all":
        for name in ("buckets", "models", "agents", "growth", "fixed",
                     "rates", "coordinator"):
            run[name](records)
    else:
        run[args.section](records)
    print("\nThis changed no file.")


if __name__ == "__main__":
    main()
