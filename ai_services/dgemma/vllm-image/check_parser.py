"""Compare the streamed and the final tool call arguments of the gemma4 parser.

usage: check_parser.py <fixture.json> [<tokenizer folder>]

The fixture is main_services/agents/research_agent/tests/producer_fixtures/
gemma4_tool_calls.json. For each entry whose raw text starts a tool call, the check
feeds the raw text to the parser of the installed vLLM one token at a time, as the
streaming chat endpoint does, and joins the argument deltas. It also parses the raw
text in one pass, as the endpoint without streaming does. A case passes when the
joined deltas are JSON and equal the one-pass arguments.

Run it inside the model server image, with the weights folder mounted for the
tokenizer. It needs no GPU. The exit status is 1 when a case fails.
"""

import json
import sys

from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionRequest
from vllm.parser.gemma4 import Gemma4Parser
from vllm.tokenizers import get_tokenizer


def request():
    return ChatCompletionRequest(
        model="dgemma",
        messages=[{"role": "user", "content": "check"}],
        stream=True,
        skip_special_tokens=False,
    )


def streamed(tokenizer, raw):
    """The joined argument deltas of each call, by call index."""
    parser = Gemma4Parser(tokenizer, None)
    req = request()
    ids = tokenizer.encode(raw, add_special_tokens=False)
    calls = {}
    for n, token in enumerate(ids):
        text = tokenizer.decode([token], skip_special_tokens=False)
        delta = parser.parse_delta(text, [token], req, None, finished=n == len(ids) - 1)
        for call in (delta.tool_calls if delta else None) or []:
            if call.function is not None and call.function.arguments:
                calls[call.index] = calls.get(call.index, "") + call.function.arguments
    return calls


def one_pass(tokenizer, raw):
    info = Gemma4Parser(tokenizer, None).extract_tool_calls(raw, request())
    return {n: call.function.arguments for n, call in enumerate(info.tool_calls)}


def check(tokenizer, entry):
    raw = entry["raw"]
    got = streamed(tokenizer, raw)
    want = one_pass(tokenizer, raw)
    problems = []
    if sorted(got) != sorted(want):
        problems.append("streamed calls %s, one-pass calls %s" % (sorted(got), sorted(want)))
    for n in sorted(want):
        text = got.get(n, "")
        try:
            value = json.loads(text)
        except ValueError:
            problems.append("call %d: the streamed arguments are not JSON: %r" % (n, text[-80:]))
            continue
        if value != json.loads(want[n]):
            problems.append("call %d: the streamed arguments differ from the one-pass parse" % n)
    return problems


def main(argv):
    fixture = json.load(open(argv[1]))
    tokenizer = get_tokenizer(argv[2] if len(argv) > 2 else "/models/dgemma")
    failed = 0
    for entry in fixture["entries"]:
        if not (entry.get("raw") or "").startswith("<|tool_call>"):
            continue
        print("case %s" % entry["case"])
        problems = check(tokenizer, entry)
        for problem in problems:
            print("  FAIL " + problem)
        if problems:
            failed += 1
        else:
            print("  PASS")
    print("%d failed" % failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
