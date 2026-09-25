#!/usr/bin/env python3
"""Measure the result page and catalogue limits that the served model handles.

The probe sends synthetic agent turns to an OpenAI-compatible chat endpoint and writes one
JSONL record for each sample. It selects values for three `hoover4.ini` keys:
`agent_max_page_tokens`, `agent_completion_reserve_tokens` (the completion allowance of
the series) and `agent_catalogue_match_count`. It writes no configuration.

Two arms:

- `page` varies the page tokens for each count of parallel calls in `--parallel`. For each
  count it runs a doubling search from `--start-page-tokens`, then a bracketed binary search
  between the last passing point and the first failing point, to `--resolution` tokens. A
  point passes after `--screen-runs` runs (20) with zero hard and zero quality failures. The
  selected point then runs `--confirm-runs` more runs (59), and it is confirmed only when
  every one of them passes too.
- `catalogue` tests match counts from 6 to 12, and selects the smallest count whose screen
  passes on every fixture.

A series keeps the model, the parser, the temperature, the completion allowance, the
fixtures and the hardware label constant. The first record of the series file holds these
values, and a run with other values for the same series file is refused.

A fixture is a JSON object:

    {"name": "...", "profile": "core" | "deferred" | "normal",
     "system": "...", "question": "...",
     "core_tools": [OpenAI tool objects], "deferred_tools": [OpenAI tool objects],
     "page_tool": "tool name", "page_arguments": {...},
     "filler": "text repeated to fill a page", "sentinel": "text placed at the end of
     each page", "answer_key": ["words the answer must contain"],
     "expect": "answer" | "read_more",
     "catalogue_query": "...", "catalogue_ranking": ["tool names, best first"],
     "catalogue_target": "tool name"}

Exit status: 0 when every requested sample exists, 1 when the series is incomplete (a
transport failure stops it, and the records written so far stay in the file), 2 on a
configuration failure.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

SUPPORTED_PARSERS = ("qwen3_xml",)
MATCH_COUNTS = range(6, 13)
EXIT_OK, EXIT_INCOMPLETE, EXIT_CONFIG = 0, 1, 2


class ConfigurationFailure(Exception):
    """A setting, a fixture or the series file does not permit the run."""


class TransportFailure(Exception):
    """The endpoint gave no response to a request."""


class TokenizerFailure(Exception):
    """The tokenizer endpoint gave no usable count."""


class Model(Protocol):
    def tokenize(self, text: str) -> int: ...

    def chat(self, body: dict) -> tuple[int, dict, float, float]:
        """Return the HTTP status, the response body, the connect seconds and the total
        seconds. Raise `TransportFailure` when no response arrives."""


class HttpModel:
    """The served model over its OpenAI-compatible routes."""

    def __init__(self, base_url: str, api_key: str, timeout: float) -> None:
        self.base = base_url.rstrip("/")
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        self.timeout = timeout
        self.served_name = ""

    def _post(self, url: str, body: dict) -> tuple[int, dict, float, float]:
        started = time.monotonic()
        request = urllib.request.Request(url, json.dumps(body).encode("utf-8"), self.headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                connected = time.monotonic() - started
                data = json.loads(response.read() or b"{}")
                return response.status, data, connected, time.monotonic() - started
        except urllib.error.HTTPError as exc:
            elapsed = time.monotonic() - started
            try:
                data = json.loads(exc.read() or b"{}")
            except ValueError:
                data = {}
            return exc.code, data, elapsed, elapsed
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise TransportFailure(str(exc)) from exc

    def tokenize(self, text: str) -> int:
        url = self.base.removesuffix("/v1") + "/tokenize"
        try:
            status, data, _, _ = self._post(url, {"model": self.served_name, "prompt": text, "add_special_tokens": False})
        except TransportFailure as exc:
            raise TokenizerFailure(str(exc)) from exc
        tokens = data.get("tokens")
        if status != 200 or not isinstance(tokens, list) or data.get("count") != len(tokens):
            raise TokenizerFailure(f"tokenizer answered {status}")
        return len(tokens)

    def chat(self, body: dict) -> tuple[int, dict, float, float]:
        return self._post(self.base + "/chat/completions", body)


@dataclass
class Series:
    """The values a series keeps constant, and where its records go."""

    source_model: str
    served_name: str
    parser: str
    temperature: float
    completion_tokens: int
    hardware: str
    fixtures: list[dict]
    path: Path

    def constants(self) -> dict:
        return {
            "kind": "series", "source_model": self.source_model, "served_name": self.served_name,
            "parser": self.parser, "temperature": self.temperature,
            "completion_tokens": self.completion_tokens, "hardware": self.hardware,
            "fixtures": sorted(f["name"] for f in self.fixtures),
        }

    def open(self) -> None:
        """Write the series record, or check it against the existing file."""
        constants = self.constants()
        if self.path.exists() and self.path.stat().st_size:
            first = json.loads(self.path.read_text(encoding="utf-8").splitlines()[0])
            if first != constants:
                raise ConfigurationFailure(
                    f"{self.path} holds another series: {json.dumps(first)}. Start a new series name.")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.write(constants)

    def write(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()


REQUIRED_FIXTURE_KEYS = ("name", "profile", "system", "question", "core_tools", "page_tool",
                         "filler", "sentinel", "answer_key", "expect")


def load_fixture(path: str) -> dict:
    try:
        fixture = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigurationFailure(f"cannot read the fixture {path}: {exc}") from exc
    missing = [key for key in REQUIRED_FIXTURE_KEYS if key not in fixture]
    if missing:
        raise ConfigurationFailure(f"the fixture {path} has no {', '.join(missing)}")
    if fixture["profile"] not in ("core", "deferred", "normal"):
        raise ConfigurationFailure(f"the fixture {path} has the unknown profile {fixture['profile']!r}")
    if fixture["expect"] not in ("answer", "read_more"):
        raise ConfigurationFailure(f"the fixture {path} expects {fixture['expect']!r}")
    return fixture


# ---------------------------------------------------------------------------- one sample


class PageText:
    """The page content of a given token count, cut from the fixture filler with the
    served tokenizer. A failed count cuts by bytes, which is safe mode."""

    def __init__(self, model: Model, fixture: dict) -> None:
        self.model = model
        self.fixture = fixture
        self.cache: dict[int, tuple[str, bool]] = {}
        self.tokenizer_failures = 0

    def get(self, tokens: int) -> tuple[str, bool]:
        if tokens not in self.cache:
            self.cache[tokens] = self._build(tokens)
        return self.cache[tokens]

    def _build(self, tokens: int) -> tuple[str, bool]:
        sentinel = self.fixture["sentinel"]
        filler = self.fixture["filler"]
        base = (filler * (tokens * 8 // max(len(filler), 1) + 2))
        try:
            low, high = 0, len(base)
            while low < high:
                middle = (low + high + 1) // 2
                if self.model.tokenize(base[:middle] + sentinel) <= tokens:
                    low = middle
                else:
                    high = middle - 1
            return base[:low] + sentinel, False
        except TokenizerFailure:
            self.tokenizer_failures += 1
            data = (base.encode("utf-8")[:max(tokens - len(sentinel.encode("utf-8")), 0)])
            return data.decode("utf-8", "ignore") + sentinel, True


def continuation_token(fixture: dict) -> str:
    raw = json.dumps({"v": 1, "tool": fixture["page_tool"], "input": fixture.get("page_arguments", {}),
                      "position": {"start": 1}, "source": "probe"}, sort_keys=True, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def page_request(series: Series, fixture: dict, content: str, parallel: int, catalogue: list[str] | None = None) -> dict:
    """The chat request of one sample: the question, one model turn of `parallel` calls,
    and one result page for each call."""
    tools = list(fixture["core_tools"])
    if fixture["profile"] != "core":
        tools += fixture.get("deferred_tools", [])
    calls = [{"id": f"probe-{i}", "type": "function", "function": {
        "name": fixture["page_tool"], "arguments": json.dumps(fixture.get("page_arguments", {}))}}
        for i in range(parallel)]
    if catalogue is not None:
        # The bind step makes each listed match callable on the next model call, so the
        # request carries the schemas of the listed deferred tools.
        bound = {tool["function"]["name"]: tool for tool in fixture.get("deferred_tools", [])}
        listed = {tool["function"]["name"] for tool in tools}
        tools += [bound[name] for name in catalogue if name in bound and name not in listed]
        results = [json.dumps({"matches": catalogue, "query": fixture["catalogue_query"]})]
        calls = [{"id": "probe-0", "type": "function", "function": {
            "name": "search_agent_tools", "arguments": json.dumps({"query": fixture["catalogue_query"]})}}]
    else:
        continuation = continuation_token(fixture) if fixture["expect"] == "read_more" else None
        results = [json.dumps({"success": True, "kind": "result_page", "tool_name": fixture["page_tool"],
                               "shape": "blob", "items": [content], "returned_units": len(content.encode("utf-8")),
                               "total_units": len(content.encode("utf-8")) * (2 if continuation else 1),
                               "raw_artifact_id": None, "continuation": continuation},
                              ensure_ascii=False, sort_keys=True, separators=(",", ":"))] * parallel
    messages = [
        {"role": "system", "content": fixture["system"]},
        {"role": "user", "content": fixture["question"]},
        {"role": "assistant", "content": "", "tool_calls": calls},
        *({"role": "tool", "tool_call_id": call["id"], "content": result} for call, result in zip(calls, results)),
    ]
    return {"model": series.served_name, "messages": messages, "tools": tools,
            "temperature": series.temperature, "max_tokens": series.completion_tokens}


def judge(fixture: dict, body: dict, status: int, request: dict, catalogue: bool) -> dict:
    """The hard and quality verdict of one response."""
    names = {tool["function"]["name"] for tool in request["tools"]} | {"read_more", "search_agent_tools"}
    if catalogue:
        # A listed match is callable after the catalogue search, as the bind step makes it.
        names |= set(fixture["catalogue_ranking"])
    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    calls = message.get("tool_calls") or []
    answer = message.get("content") or ""
    malformed = repeated = 0
    called = []
    sent = {(c["function"]["name"], c["function"]["arguments"]) for c in request["messages"][2]["tool_calls"]}
    for call in calls:
        function = call.get("function") or {}
        try:
            json.loads(function.get("arguments") or "{}")
        except ValueError:
            malformed += 1
        if function.get("name") not in names:
            malformed += 1
        if (function.get("name"), function.get("arguments")) in sent:
            repeated += 1
        called.append(function.get("name"))
    hard = []
    if status != 200:
        hard.append(f"http {status}: {json.dumps(body)[:300]}")
    elif choice.get("finish_reason") == "length":
        hard.append("the completion allowance ran out")
    if malformed:
        hard.append(f"{malformed} malformed calls")
    if catalogue:
        outcome = "target" if fixture["catalogue_target"] in called else ("other_call" if called else "answer")
        quality = [] if outcome == "target" else [f"the model did not call {fixture['catalogue_target']}"]
        score = 1.0 if outcome == "target" else 0.0
    else:
        outcome = "read_more" if "read_more" in called else ("other_call" if called else "answer")
        found = [word for word in [fixture["sentinel"], *fixture["answer_key"]] if word.lower() in answer.lower()]
        score = len(found) / (1 + len(fixture["answer_key"]))
        quality = []
        if outcome != fixture["expect"]:
            quality.append(f"the outcome is {outcome}, and the fixture expects {fixture['expect']}")
        if fixture["expect"] == "answer" and score < 1.0:
            quality.append(f"the answer holds {len(found)} of {1 + len(fixture['answer_key'])} key words")
        if repeated:
            quality.append(f"{repeated} repeated calls")
    usage = body.get("usage") or {}
    return {"hard_failures": hard, "quality_failures": quality, "outcome": outcome, "score": score,
            "malformed_calls": malformed, "repeated_calls": repeated,
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
            "peak_context": (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)}


class Runner:
    """Runs samples and writes their records."""

    def __init__(self, series: Series, model: Model) -> None:
        self.series = series
        self.model = model
        self.pages = {f["name"]: PageText(model, f) for f in series.fixtures}
        self.schema_tokens: dict[str, tuple[int | None, int | None]] = {}

    def _schema_tokens(self, fixture: dict) -> tuple[int | None, int | None]:
        if fixture["name"] not in self.schema_tokens:
            try:
                core = self.model.tokenize(json.dumps(fixture["core_tools"]))
                deferred = self.model.tokenize(json.dumps(fixture.get("deferred_tools", []))) if fixture["profile"] != "core" else 0
            except TokenizerFailure:
                core = deferred = None
            self.schema_tokens[fixture["name"]] = (core, deferred)
        return self.schema_tokens[fixture["name"]]

    def sample(self, arm: str, stage: str, fixture: dict, run: int, *, page_tokens: int = 0,
               parallel: int = 1, match_count: int | None = None) -> bool:
        """Run one sample and write its record. Return whether it passed."""
        page = self.pages[fixture["name"]]
        failures_before = page.tokenizer_failures
        catalogue = None
        content, safe_mode = ("", False)
        if match_count is not None:
            ranking = fixture["catalogue_ranking"]
            catalogue = ranking[:match_count]
        else:
            content, safe_mode = page.get(page_tokens)
        request = page_request(self.series, fixture, content, parallel, catalogue)
        core, deferred = self._schema_tokens(fixture)
        record = {"kind": "sample", "arm": arm, "stage": stage, "fixture": fixture["name"],
                  "profile": fixture["profile"], "run": run, "page_tokens": page_tokens,
                  "parallel_calls": parallel, "match_count": match_count,
                  "core_schema_tokens": core, "deferred_schema_tokens": deferred,
                  "result_tokens": page_tokens * parallel if match_count is None else None,
                  "safe_mode": safe_mode}
        try:
            status, body, connect, total = self.model.chat(request)
        except TransportFailure as exc:
            record.update(missing=True, error=str(exc))
            self.series.write(record)
            raise
        verdict = judge(fixture, body, status, request, match_count is not None)
        record.update(verdict, missing=False, connect_seconds=round(connect, 3), total_seconds=round(total, 3),
                      tokenizer_failures=page.tokenizer_failures - failures_before + (core is None))
        record["passed"] = not verdict["hard_failures"] and not verdict["quality_failures"]
        self.series.write(record)
        return record["passed"]

    def point(self, arm: str, stage: str, runs: int, **kwargs: Any) -> bool:
        """Screen or confirm one point over every fixture. It stops at the first failure,
        because one failure settles the point."""
        for fixture in self.series.fixtures:
            for run in range(runs):
                if not self.sample(arm, stage, fixture, run, **kwargs):
                    return False
        return True


def bracket(passes: Callable[[int], bool], start: int, ceiling: int, resolution: int) -> int | None:
    """The largest passing value: a doubling search from `start`, then a binary search
    between the last passing and the first failing value, to `resolution`. `None` when
    `start` fails."""
    if not passes(start):
        return None
    good, bad = start, None
    while good * 2 <= ceiling:
        if passes(good * 2):
            good *= 2
        else:
            bad = good * 2
            break
    if bad is None:
        return good
    while bad - good > resolution:
        middle = (good + bad) // 2
        if passes(middle):
            good = middle
        else:
            bad = middle
    return good


def run_page_arm(runner: Runner, args: argparse.Namespace) -> None:
    for parallel in args.parallel:
        selected = bracket(
            lambda tokens: runner.point("page", "screen", args.screen_runs, page_tokens=tokens, parallel=parallel),
            args.start_page_tokens, args.max_page_tokens, args.resolution,
        )
        confirmed = bool(selected) and runner.point("page", "confirm", args.confirm_runs, page_tokens=selected, parallel=parallel)
        runner.series.write({"kind": "selection", "arm": "page", "parallel_calls": parallel,
                             "selected_page_tokens": selected, "confirmed": confirmed,
                             "completion_tokens": runner.series.completion_tokens})


def run_catalogue_arm(runner: Runner, args: argparse.Namespace) -> None:
    for fixture in runner.series.fixtures:
        if "catalogue_ranking" not in fixture or "catalogue_target" not in fixture:
            raise ConfigurationFailure(f"the fixture {fixture['name']} has no catalogue_ranking or catalogue_target")
    selected = None
    for count in MATCH_COUNTS:
        if runner.point("catalogue", "screen", args.screen_runs, match_count=count):
            selected = count
            break
    confirmed = selected is not None and runner.point("catalogue", "confirm", args.confirm_runs, match_count=selected)
    runner.series.write({"kind": "selection", "arm": "catalogue", "selected_match_count": selected,
                         "confirmed": confirmed})


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source-model", required=True, help="the source model id, for example Qwen/Qwen3.5-35B-A3B")
    parser.add_argument("--served-name", required=True, help="the name /v1/models lists")
    parser.add_argument("--parser", required=True, help="the tool call parser id of the server")
    parser.add_argument("--fixture", required=True, action="append", help="a profile fixture; repeat for more")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--series", required=True, help="the series name, and the JSONL file name")
    parser.add_argument("--arm", choices=("page", "catalogue"), default="page")
    parser.add_argument("--base-url", default=os.getenv("LLM_BASE_URL", ""), help="the OpenAI-compatible base, ending in /v1")
    parser.add_argument("--api-key-file", default=os.getenv("LLM_API_KEY_FILE", "/run/secrets/llm_api_key"))
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--completion-tokens", type=int, default=8192)
    parser.add_argument("--hardware", default=os.getenv("PROBE_HARDWARE", ""), help="a label for the serving hardware")
    parser.add_argument("--parallel", type=lambda v: [int(x) for x in v.split(",")], default=[1, 2, 3])
    parser.add_argument("--start-page-tokens", type=int, default=2048)
    parser.add_argument("--max-page-tokens", type=int, default=131072)
    parser.add_argument("--resolution", type=int, default=512)
    parser.add_argument("--screen-runs", type=int, default=20)
    parser.add_argument("--confirm-runs", type=int, default=59)
    parser.add_argument("--timeout", type=float, default=600.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, model: Model | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.parser not in SUPPORTED_PARSERS:
            raise ConfigurationFailure(f"the parser {args.parser!r} is not supported. Supported: {', '.join(SUPPORTED_PARSERS)}")
        if not args.hardware:
            raise ConfigurationFailure("--hardware or PROBE_HARDWARE must name the serving hardware")
        fixtures = [load_fixture(path) for path in args.fixture]
        if model is None:
            if not args.base_url:
                raise ConfigurationFailure("--base-url or LLM_BASE_URL must name the endpoint")
            key = Path(args.api_key_file).read_text().strip() if os.path.exists(args.api_key_file) else ""
            model = HttpModel(args.base_url, key, args.timeout)
            model.served_name = args.served_name
        series = Series(args.source_model, args.served_name, args.parser, args.temperature,
                        args.completion_tokens, args.hardware, fixtures,
                        Path(args.output_dir) / f"{args.series}.jsonl")
        series.open()
    except ConfigurationFailure as exc:
        print(f"configuration failure: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    runner = Runner(series, model)
    try:
        (run_page_arm if args.arm == "page" else run_catalogue_arm)(runner, args)
    except ConfigurationFailure as exc:
        print(f"configuration failure: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except TransportFailure as exc:
        print(f"incomplete series: a request got no response: {exc}. The records so far are in {series.path}.", file=sys.stderr)
        return EXIT_INCOMPLETE
    print(f"series complete: {series.path}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
