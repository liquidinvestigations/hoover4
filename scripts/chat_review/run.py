"""Run immutable export, review, replay, grade, and comparison attempts."""

import argparse
from pathlib import Path
import sys

from .client import (TransportFailure, begin_attempt, finish_attempt, read_json,
                     validate_config, write_json)
from .schema import Incomplete, Invalid, array, digest, obj, require, string, validate_packet


def execute(command, inputs, out, resume=False):
    out = Path(out)
    cached = begin_attempt(out, {"command": command, **inputs}, resume)
    if cached:
        return cached["result"], cached["exit_code"]
    try:
        if command == "export":
            from .export import export_turn
            packet, manifest = export_turn(inputs["owner"], inputs["session"], inputs["turn"],
                                           requirements=inputs.get("requirements"))
            write_json(out / "packet.json", packet)
            write_json(out / "export-manifest.json", manifest)
            result, code = {"state": "export_complete", "packet_digest": packet["identity"]["packet_digest"]}, 0
        elif command in ("review", "replay"):
            packet, config = validate_packet(inputs["packet"]), validate_config(inputs["config"])
            if command == "review":
                from .review import run_review
                result, code = run_review(packet, packet["delivery"], config, out)
            else:
                from .replay import run_replay
                result, code = run_replay(packet, inputs["review"], config, out)
        elif command == "grade":
            from .grade import grade
            result = grade(inputs["packet"], inputs["delivery"], inputs["reference"], inputs["labels"])
            code = {"delivery_pass": 0, "delivery_fail": 1, "review_incomplete": 2}[result["verdict"]]
            write_json(out / "grade.json", result)
        elif command == "compare":
            result, code = compare(inputs["schedule"], out)
        else:
            raise Invalid("Unknown command.")
    except Incomplete as exc:
        result, code = {"state": "review_incomplete", "reason": str(exc)}, 2
    except TransportFailure as exc:
        result, code = {"state": "transport_failed", "reason": str(exc)}, 3
    except (Invalid, ValueError, KeyError, TypeError):
        result, code = {"state": "invalid", "reason": "Arguments, configuration, or input schema are invalid."}, 4
    except KeyboardInterrupt:
        result, code = {"state": "interrupted", "outcome": "unknown"}, 130
    except Exception as exc:
        # Storage exceptions can contain credentials or connection parameters.
        result, code = {"state": "execution_failed", "error_type": type(exc).__name__}, 3
    return finish_attempt(out, result, code)


def compare(schedule, out):
    obj(schedule, ("schema_version", "attempts"))
    require(type(schedule["schema_version"]) is int and schedule["schema_version"] == 1, "Unknown schedule schema.")
    require(bool(array(schedule["attempts"])), "The comparison schedule is empty.")
    ids = set()
    for attempt in schedule["attempts"]:
        obj(attempt, ("id", "pair", "command", "inputs"), ("grade_inputs",))
        from .schema import filename
        filename(attempt["id"])
        string(attempt["pair"])
        require(attempt["id"] not in ids, "Repeated attempt identity.")
        ids.add(attempt["id"])
        require(attempt["command"] in ("review", "replay"), "Comparison supports review and replay attempts.")
        validate_packet(attempt["inputs"]["packet"])
        validate_config(attempt["inputs"]["config"])
    pairs = {}
    for a in schedule["attempts"]:
        identity = a["inputs"]["packet"]["identity"]["packet_digest"]
        require(pairs.setdefault(a["pair"], identity) == identity, "Matched attempts require the same packet.")
    results = []
    for a in schedule["attempts"]:
        directory = out / a["id"]
        result, code = execute(a["command"], a["inputs"], directory)
        grade_result = None
        if a.get("grade_inputs"):
            g = dict(a["grade_inputs"])
            g["packet"] = a["inputs"]["packet"]
            if a["command"] == "replay" and (directory / "delivery.json").exists():
                g["delivery"] = read_json(directory / "delivery.json")
            elif a["command"] == "review":
                g["delivery"] = g["packet"]["delivery"]
            else:
                g = None
            if g:
                grade_result, _ = execute("grade", g, directory / "grade")
        calls = []
        for p in directory.rglob("request.json"):
            status_path = p.parent / "status.json"
            status = read_json(status_path)
            response_path = p.parent / "response.json"
            try:
                response = read_json(response_path) if response_path.exists() else {}
            except (ValueError, Invalid):
                response = {}
            calls.append({"elapsed_s": status.get("elapsed_s"), "state": status["state"],
                          "usage": response.get("usage") if isinstance(response, dict) else None})
        results.append({"id": a["id"], "pair": a["pair"], "execution_code": code,
                        "review_state": result.get("state"), "grade": grade_result, "calls": calls})
        if code == 130:
            break
    summary = {"schema_version": 1, "schedule_digest": digest(schedule), "attempts": results,
               "quality": [{"id": r["id"], "verdict": (r["grade"] or {}).get("verdict", "ungraded")} for r in results],
               "cost": [{"id": r["id"], "calls": r["calls"]} for r in results]}
    write_json(out / "comparison.json", summary)
    if any(r["execution_code"] == 130 for r in results):
        return summary, 130
    complete = len(results) == len(schedule["attempts"]) and all(
        r["execution_code"] in (0, 2, 3) and
        ("grade_inputs" not in a or (r["grade"] or {}).get("verdict") in
         ("delivery_pass", "delivery_fail", "review_incomplete"))
        for a, r in zip(schedule["attempts"], results))
    return summary, 0 if complete else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for command, fields in {"export": ("owner", "session", "turn"),
                            "review": ("packet", "config"),
                            "replay": ("packet", "review", "config"),
                            "grade": ("packet", "delivery", "reference", "labels"),
                            "compare": ("schedule",)}.items():
        p = subs.add_parser(command)
        for field in fields:
            p.add_argument("--" + field, required=True, type=int if field == "turn" else str)
        p.add_argument("--out", required=True)
        p.add_argument("--resume", action="store_true")
        if command == "export":
            p.add_argument("--requirements")
    args = vars(parser.parse_args(argv))
    command, out, resume = args.pop("command"), args.pop("out"), args.pop("resume")
    try:
        inputs = {k: read_json(v) if k not in ("owner", "session", "turn") and v is not None else v
                  for k, v in args.items()}
        result, code = execute(command, inputs, out, resume)
    except (Invalid, ValueError, OSError):
        print("The input or attempt directory is invalid.")
        return 4
    print(result.get("verdict", result.get("state", "comparison_complete")))
    return code


if __name__ == "__main__":
    sys.exit(main())
