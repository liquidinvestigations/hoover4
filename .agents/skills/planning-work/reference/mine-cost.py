#!/usr/bin/env python3
"""What a pass costs, per bucket, per model and per tool call.

    cost.py [passes.jsonl] [--kind pass]

Applies the list prices in `prices.py` to the token counts `extract.py` recorded. It
changes no file.

A cost per tool call is the figure a plan actually uses, because a plan forecasts tool
calls and not tokens. It is computed per pass and then taken at the median, so one very
large pass cannot set the rate.

A pass whose model has no published price, or whose harness recorded no token counts, is
counted as unpriced and named. Cursor records no per-turn usage at all, so no Cursor pass
carries a cost here.
"""

import argparse
import collections
import json
import statistics as st

from prices import PRICES, cost_of, price_of, tier_of


def pct(values, q):
    values = sorted(values)
    if not values:
        return float("nan")
    return values[min(len(values) - 1, int(len(values) * q))]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", nargs="?", default="passes.jsonl")
    parser.add_argument("--kind", default="pass",
                        choices=("pass", "session", "guard", "any"))
    args = parser.parse_args()

    records = [json.loads(line) for line in open(args.source)]
    if args.kind != "any":
        records = [r for r in records if r["kind"] == args.kind]

    priced, unpriced = [], collections.Counter()
    for r in records:
        value = cost_of(r)
        if value is None:
            reason = ("no price for " + str(r.get("model"))
                      if price_of(r.get("model")) is None else "no token counts")
            unpriced[(r["harness"], reason)] += 1
            continue
        r["cost"] = value
        r["cost_per_call"] = value / r["tool_calls"] if r.get("tool_calls") else None
        priced.append(r)

    print(f"{len(priced)} of {len(records)} records priced")
    for (harness, reason), count in sorted(unpriced.items()):
        print(f"  unpriced  {harness:<8} {count:4d}  {reason}")

    print("\n" + "=" * 78)
    print("COST BY BUCKET")
    print("=" * 78)
    print(f"{'bucket':<20} {'n':>4} {'p50':>9} {'p75':>9} {'p90':>9} {'max':>9} "
          f"{'$/call p50':>11}")
    for bucket in ("implementation", "read-only review", "documentation", "operational"):
        group = [r for r in priced if r["bucket"] == bucket]
        if not group:
            continue
        costs = [r["cost"] for r in group]
        per = [r["cost_per_call"] for r in group if r.get("cost_per_call")]
        print(f"{bucket:<20} {len(group):4d} {st.median(costs):9.2f} "
              f"{pct(costs, 0.75):9.2f} {pct(costs, 0.9):9.2f} {max(costs):9.2f} "
              f"{st.median(per) if per else 0:11.3f}")

    print("\n" + "=" * 78)
    print("COST BY MODEL")
    print("=" * 78)
    print("The spread across these rows is what decides whether one money figure can")
    print("stand for a pass, or whether a plan has to name the tier it will run on.\n")
    print(f"{'model':<26} {'tier':<10} {'n':>4} {'cost p50':>9} {'p90':>9} "
          f"{'$/call p50':>11} {'calls p50':>10}")
    by_model = collections.defaultdict(list)
    for r in priced:
        by_model[r["model"]].append(r)
    for model, group in sorted(by_model.items(), key=lambda kv: -len(kv[1])):
        costs = [r["cost"] for r in group]
        per = [r["cost_per_call"] for r in group if r.get("cost_per_call")]
        calls = [r["tool_calls"] for r in group if r.get("tool_calls")]
        print(f"{model:<26} {tier_of(model) or '-':<10} {len(group):4d} "
              f"{st.median(costs):9.2f} {pct(costs, 0.9):9.2f} "
              f"{st.median(per) if per else 0:11.3f} "
              f"{st.median(calls) if calls else 0:10.0f}")

    print("\n" + "=" * 78)
    print("WHAT THE SAME WORK WOULD COST ON ANOTHER MODEL")
    print("=" * 78)
    print("The token counts of every priced implementation pass, repriced. This is the")
    print("only comparison that holds, because it holds the work constant.\n")
    work = [r for r in priced if r["bucket"] == "implementation"]
    print(f"{'model':<26} {'tier':<10} {'total':>10} {'per pass p50':>13} "
          f"{'vs opus 5':>10}")
    baseline = None
    for model in PRICES:
        repriced = []
        for r in work:
            copy = dict(r)
            copy["model"] = model
            value = cost_of(copy)
            if value is not None:
                repriced.append(value)
        if not repriced:
            continue
        total = sum(repriced)
        if model == "claude-opus-5":
            baseline = total
        ratio = f"{total / baseline:9.2f}x" if baseline else "        -"
        print(f"{model:<26} {tier_of(model) or '-':<10} {total:10.2f} "
              f"{st.median(repriced):13.2f} {ratio:>10}")
    print(f"\n{len(work)} implementation passes repriced. The work is identical in every")
    print("row, so the spread is the price of the model and nothing else.")
    print("\nThis changed no file.")


if __name__ == "__main__":
    main()
