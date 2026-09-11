#!/usr/bin/env python3
"""Turn the measurements into the numbers a plan uses, and show every step.

    derive.py [passes.jsonl]

`report.py` prints distributions. This prints the figures that go into
`estimating.md`, with the arithmetic beside each one, so a reader can check a pinned
number without re-deriving it.

TWO ACCOUNTS, KEPT APART

**The pass's own account** decides its context cap and its tool-call budget. A pass starts
with a fresh context, so it pays its own fixed cost of reading its package and reporting,
and nothing else. The coordinator's calls are spent in another context and never enter it.

**The plan's account** decides how many passes to write. Every pass costs its coordinator
calls and money before it runs, and that cost is paid again for each pass. It is what
packing removes, and it is why a one-task pass is expensive even though the pass itself
spends most of its own calls on work.

The efficiency floor is a plan-level figure for that reason, and it is labelled as one.
"""

import argparse
import collections
import json
import statistics as st

from prices import cost_of

#: The context cap on a pass that writes, chosen 2026-09-11. The p90 pass measured here
#: peaks at 288,230 and 8 of 150 passes compacted, so the earlier 250,000 was below what
#: the corpus already does.
CAP_WRITE = 300_000

#: The context cap on a pass that only reads. Unchanged.
CAP_READ = 150_000

#: What a LATER task costs, as a fraction of a whole first pass. Measured in another
#: repository, where one agent took four work packages into one context and spent 62
#: minutes on the first and 25.6, 12.5 and 12.3 on the rest. A ratio is the one thing a
#: borrowed corpus lends, so it is applied to this repository's own call count.
#:
#: The first task is not in this tuple. It costs the measured marginal figure, being the
#: whole pass less its fixed cost, because that is what a recorded pass carrying about one
#: task actually spent. Multiplying the whole pass by 1.00 and adding the fixed cost again
#: would charge the fixed cost twice.
LATER_TASK_DECAY = (0.41, 0.20, 0.20, 0.20, 0.20)

#: The floor a pass must meet on the plan's account, chosen 2026-09-11. One task comes out
#: below it and two above it, which is the shape this floor exists to refuse.
FLOOR = 0.60


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * q))]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", nargs="?", default="passes.jsonl")
    args = parser.parse_args()
    records = [json.loads(line) for line in open(args.source)]
    passes = [r for r in records if r["kind"] == "pass"]
    sessions = [r for r in records if r["kind"] == "session"]
    work = [r for r in passes if r["bucket"] == "implementation"]

    print("POOLED ACROSS ALL FOUR HARNESSES")
    print(f"  passes {len(passes)}, of which implementation {len(work)}")
    print("  A tool call is not the same unit in every harness. Cursor issues one read a")
    print("  file where Codex routes a pipeline through one exec, so the pooled call")
    print("  count spans a 5x difference in granularity. This is a known cost of pooling.")

    calls = [r["tool_calls"] for r in work if r["tool_calls"]]
    minutes = [r["minutes"] for r in work if r["minutes"]]
    ctx = [r["peak_context"] for r in work if r["peak_context"]]
    print("\n1. THE IMPLEMENTATION PASS AS RECORDED")
    print(f"   tool calls    p50 {st.median(calls):6.0f}   p90 {pct(calls, 0.9):6.0f}"
          f"   n={len(calls)}")
    print(f"   minutes       p50 {st.median(minutes):6.0f}   p90 {pct(minutes, 0.9):6.0f}"
          f"   n={len(minutes)}")
    print(f"   peak context  p50 {st.median(ctx):6.0f}   p90 {pct(ctx, 0.9):6.0f}"
          f"   n={len(ctx)}")
    one_pass = st.median(calls)

    sized = [r for r in work if r.get("calls_before_first_code_write") is not None]
    fixed_each = [r["calls_before_first_code_write"] + r["calls_after_last_code_write"]
                  for r in sized]
    fixed = st.median(fixed_each)
    marginal = one_pass - fixed
    print("\n2. THE PASS'S OWN FIXED COST")
    print(f"   prologue, calls before the first code write   p50 "
          f"{st.median([r['calls_before_first_code_write'] for r in sized]):6.0f}")
    print(f"   epilogue, calls after the last code write     p50 "
          f"{st.median([r['calls_after_last_code_write'] for r in sized]):6.0f}")
    print(f"   fixed, the median of their sum               p50 {fixed:6.0f}"
          f"   n={len(sized)}")
    print(f"   marginal, being {one_pass:.0f} less {fixed:.0f}                 "
          f"     {marginal:6.0f}   the first task")

    launched = collections.Counter(r["session"] for r in passes)
    per_pass_calls, per_pass_cost, per_pass_span = [], [], []
    for s in sessions:
        n = launched.get(s["id"], 0)
        if not n:
            continue
        if s.get("tool_calls"):
            per_pass_calls.append(s["tool_calls"] / n)
        if s.get("minutes"):
            per_pass_span.append(s["minutes"] / n)
        value = cost_of(s)
        if value is not None:
            per_pass_cost.append(value / n)
    coord_calls = st.median(per_pass_calls)
    print("\n3. WHAT ONE PASS COSTS ITS COORDINATOR")
    print(f"   coordinator calls a pass   p50 {coord_calls:6.1f}   n={len(per_pass_calls)}")
    print(f"   coordinator dollars a pass p50 {st.median(per_pass_cost):6.2f}"
          f"   n={len(per_pass_cost)}")
    print(f"   session span a pass        p50 {st.median(per_pass_span):6.0f} min"
          f"   n={len(per_pass_span)}")
    print("   Spent in the coordinator's context, never in the pass's. It sets the pass")
    print("   count and the money, and it does not enter the pass's own budget.")

    rates = []
    bases = []
    for r in passes:
        if r.get("peak_is_final_only") or not r.get("tool_calls"):
            continue
        if r.get("peak_context") and r.get("first_context") is not None:
            rate = (r["peak_context"] - r["first_context"]) / r["tool_calls"]
            if rate > 0:
                rates.append(rate)
            bases.append(r["first_context"])
    growth = st.median(rates)
    base = st.median(bases)
    print("\n4. GROWTH PER TOOL CALL, AND THE BUDGET IT GIVES")
    print(f"   growth per call  p50 {growth:6.0f}  p75 {pct(rates, 0.75):6.0f}"
          f"  p90 {pct(rates, 0.9):6.0f}   n={len(rates)}")
    print(f"   first-turn prompt p50 {base:6.0f}   n={len(bases)}")
    for name, cap in (("writes", CAP_WRITE), ("reads only", CAP_READ)):
        budget = cap / growth
        target = (cap - base) / growth
        print(f"   a pass that {name:<10} cap {cap:>7,}  budget {budget:4.0f} calls"
              f"  packing target {target:4.0f} calls")
    target_write = (CAP_WRITE - base) / growth

    def in_pass_calls(count):
        """Calls a pass spends carrying `count` tasks, fixed cost included."""
        later = sum(one_pass * d for d in LATER_TASK_DECAY[:count - 1])
        return fixed + marginal + later

    print("\n5. WHAT ONE PASS HOLDS")
    print(f"   {'tasks':>5} {'in-pass':>8} {'fits':>6} {'plan':>6} {'work':>6} "
          f"{'floor':>6}   forecast peak context")
    for count in range(1, 6):
        in_pass = in_pass_calls(count)
        marginal_total = in_pass - fixed
        plan_total = in_pass + coord_calls
        fraction = marginal_total / plan_total
        peak = base + growth * in_pass
        fits = "yes" if in_pass <= target_write else "no"
        ok = "pass" if fraction >= FLOOR else "FAIL"
        print(f"   {count:>5} {in_pass:8.0f} {fits:>6} {plan_total:6.0f} "
              f"{fraction * 100:5.0f}% {ok:>6}   {peak:>10,.0f}")
    print(f"   The floor is {FLOOR:.0%} of a plan's calls spent on work. The target is the")
    print(f"   largest task count whose in-pass calls stay under {target_write:.0f}.")

    print("\n6. WHAT PACKING SAVES")
    for count in (1, 2, 3):
        per_plan = in_pass_calls(count) + coord_calls
        passes_needed = math_ceil(9, count)
        print(f"   nine tasks at {count} a pass: {passes_needed:2d} passes, "
              f"{passes_needed * per_plan:6.0f} calls")

    print("\n7. RATES")
    pairs = [(r["minutes"], r["tool_calls"]) for r in passes
             if r.get("minutes") and r.get("tool_calls")]
    seconds = [m * 60 / c for m, c in pairs]
    print(f"   seconds a tool call  p50 {st.median(seconds):5.1f}   n={len(pairs)}")
    priced = [(cost_of(r), r["tool_calls"]) for r in work if r.get("tool_calls")]
    per_call = [c / n for c, n in priced if c is not None]
    print(f"   dollars a tool call  p50 {st.median(per_call):5.3f}   n={len(per_call)}")
    print("\nThis changed no file.")


def math_ceil(total, per):
    return -(-total // per)


if __name__ == "__main__":
    main()
