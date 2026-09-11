#!/usr/bin/env python3
"""Print the actuals row of one sub-agent pass, read from its own transcript.

    python pass-actuals.py <transcript.jsonl> [more.jsonl ...]
    python pass-actuals.py <project-dir>            # every pass under it
    python pass-actuals.py <project-dir> --agent <id>

The organizer runs this after a pass reports, to fill the actuals column of the plan's
estimate table. A pass cannot run it on itself, because a pass cannot see its own
transcript.

It prints wall clock, tool calls, peak prompt tokens and cost. An agent counts its own
tool calls correctly. It reads its own clock, its own context and its own cost wrongly.
Every actuals column written from inside a pass has held tool calls alone for that
reason, and the transcript held the other three the whole time.

It reads. It refuses nothing and it writes no file.

Wall clock is the first to the last timestamp in the transcript. Peak prompt is
input_tokens + cache_read_input_tokens + cache_creation_input_tokens on the largest
assistant turn. Cost is priced at the rates of the model the pass really ran on.
"""
import argparse
import json
import pathlib
import sys
from datetime import datetime

from prices import PRICES, price_of

#: The model an unrecognised name is priced at. It is the dearer of the two tiers a pass
#: here runs on, so an unknown model is priced high rather than low.
FALLBACK_MODEL = "claude-opus-5"

#: A drop of more than this many prompt tokens between two assistant turns is a compaction.
COMPACTION_DROP = 50_000


def rates(model):
    """The four rates for a model name, in the order this file uses them.

    `prices.py` is the one home of a price, and it stores them as
    (input, cache write, cache read, output). This returns
    (input, output, cache write, cache read), which is the order below.

    A name `prices.py` does not know is priced at `FALLBACK_MODEL`, which is the dearer of
    the two tiers a pass here runs on, so an unknown model is priced high rather than low.
    """
    found = price_of(model)
    if found is None:
        # A harness name often carries a date or an effort suffix. Match on a prefix
        # before giving up, so `claude-opus-5-20260701` prices as `claude-opus-5`.
        name = (model or "").lower()
        for known in PRICES:
            if name.startswith(known):
                found = PRICES[known]
                break
    if found is None:
        found = PRICES[FALLBACK_MODEL]
    rate_in, rate_write, rate_read, rate_out = found
    return rate_in, rate_out, rate_write, rate_read


def stamp(raw):
    """The timestamp of one record, or nothing when it carries none."""
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None


def rows(path):
    """Yield one parsed record per line, and skip a line that does not parse.

    A transcript is a JSON Lines file. It is streamed, because a session file here can
    be larger than 40 MB.
    """
    with path.open(errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def measure(path):
    """Return the actuals of one transcript, or nothing when it holds no assistant turn."""
    prompts = []
    stamps = []
    tool_names = {}
    model = ""
    turns = 0
    cost = 0.0

    for row in rows(path):
        moment = stamp(row.get("timestamp"))
        if moment:
            stamps.append(moment)
        if row.get("type") != "assistant":
            continue
        turns += 1
        message = row.get("message") or {}
        model = message.get("model") or model
        usage = message.get("usage") or {}
        if usage:
            rate_in, rate_out, rate_write, rate_read = rates(model)
            tokens_in = usage.get("input_tokens", 0)
            cache_write = usage.get("cache_creation_input_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)
            tokens_out = usage.get("output_tokens", 0)
            prompts.append(tokens_in + cache_write + cache_read)
            cost += (tokens_in * rate_in + cache_write * rate_write
                     + cache_read * rate_read + tokens_out * rate_out) / 1e6
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name") or "?"
                tool_names[name] = tool_names.get(name, 0) + 1

    if not prompts:
        return None
    tools = sum(tool_names.values())
    minutes = (max(stamps) - min(stamps)).total_seconds() / 60 if len(stamps) > 1 else 0.0
    compactions = sum(1 for i in range(1, len(prompts))
                      if prompts[i - 1] - prompts[i] > COMPACTION_DROP)
    return {
        "agent": path.stem[len("agent-"):] if path.stem.startswith("agent-") else path.stem,
        "model": model or "unknown",
        "minutes": minutes,
        "turns": turns,
        "tools": tools,
        "tool_names": tool_names,
        "peak": max(prompts),
        "compactions": compactions,
        "cost": cost,
        "seconds_a_call": minutes * 60 / tools if tools else 0.0,
        "growth_a_call": (max(prompts) - prompts[0]) / tools if tools else 0.0,
    }


def describe(path):
    """The pass description from the meta file beside a transcript, or an empty string."""
    meta_path = path.with_name(path.stem + ".meta.json")
    if not meta_path.exists():
        return ""
    try:
        meta = json.loads(meta_path.read_text(errors="replace"))
    except (OSError, ValueError):
        return ""
    return str(meta.get("description") or "")


def transcripts(target, agent):
    """The transcript files named by one argument, sorted by name.

    A file is used as it stands. A directory is searched for the sub-agent transcripts
    of every session under it.
    """
    target = pathlib.Path(target)
    if target.is_file():
        return [target]
    found = sorted(target.glob("*/subagents/agent-*.jsonl"))
    if agent:
        found = [p for p in found if agent in p.stem]
    return found


def report(record, description):
    """Print one pass as a labelled block and as a row for the actuals column."""
    print("pass %s" % record["agent"])
    if description:
        print("  description        %s" % description)
    print("  model              %s" % record["model"])
    print("  wall clock         %.1f min" % record["minutes"])
    print("  tool calls         %d" % record["tools"])
    print("  peak prompt        %s tokens" % f"{record['peak']:,}")
    print("  cost               $%.2f" % record["cost"])
    print("  assistant turns    %d" % record["turns"])
    print("  compactions        %d" % record["compactions"])
    print("  seconds a call     %.1f" % record["seconds_a_call"])
    print("  growth a call      %.0f tokens" % record["growth_a_call"])
    busiest = sorted(record["tool_names"].items(), key=lambda kv: -kv[1])[:5]
    print("  most used tools    %s" % ", ".join("%s %d" % kv for kv in busiest))
    print("  actuals row        | %.0f min | %d calls | %s ctx | $%.2f |"
          % (record["minutes"], record["tools"], f"{record['peak']:,}", record["cost"]))
    print("")


def main():
    parser = argparse.ArgumentParser(
        description="Print the actuals row of one sub-agent pass from its transcript.",
        epilog="Prints wall clock, tool calls, peak prompt tokens and cost. The organizer "
               "runs it after a pass reports, to fill the actuals column of the estimate "
               "table. A pass cannot run it on itself. It writes no file.")
    parser.add_argument("target", nargs="+",
                        help="a transcript .jsonl file, or a Claude Code project directory")
    parser.add_argument("--agent", default="",
                        help="keep only the transcripts whose agent id contains this text")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    except (AttributeError, ValueError):
        pass

    paths = []
    for target in args.target:
        paths.extend(transcripts(target, args.agent))
    if not paths:
        print("no transcript found under %s" % ", ".join(args.target))
        return 1

    printed = 0
    for path in paths:
        record = measure(path)
        if not record:
            print("pass %s holds no assistant turn" % path.name)
            continue
        report(record, describe(path))
        printed += 1
    if printed > 1:
        print("%d passes" % printed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
