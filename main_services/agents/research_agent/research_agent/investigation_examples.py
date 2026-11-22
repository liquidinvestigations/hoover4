"""English investigation examples for detailed tool discovery and skills."""

import json
from pathlib import Path

EXCHANGES = json.loads(Path(__file__).with_suffix(".json").read_text())


def examples_for(name, names):
    from research_agent.code_mode import FUNCTIONS

    for exchange in EXCHANGES:
        if exchange["tool"] != name:
            continue
        examples = {"direct": exchange}
        if "execute" in names and name in FUNCTIONS:
            arguments = json.dumps(exchange["arguments"])
            examples["execute"] = {"language": "javascript", "code": f"return {name}({arguments});"}
        return examples
    return {}
