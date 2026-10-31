"""The worker's language check passes the cases shared with the website resolver."""

import json
from pathlib import Path

from tasks.P_agent import language

VECTORS = json.loads((Path(language.__file__).parent / "language_vectors.json").read_text())


def test_supported_code_matches_shared_cases():
    for case in VECTORS["supported_code"]:
        assert language.supported_code(case["tag"]) == case["expected"], case


def test_accept_language_matches_shared_cases():
    for case in VECTORS["accept_language"]:
        assert language.from_accept_language(case["header"]) == case["expected"], case


def test_resolution_matches_shared_cases():
    for case in VECTORS["resolve"]:
        interface = language.interface_language(case["saved_interface"], case["accept_language"])
        assert interface == case["interface"], case
        assert language.agent_language(case["saved_agent"], interface) == case["agent"], case


def test_turn_language_falls_back_to_english():
    assert language.turn_language("de") == "de"
    assert language.turn_language("") == "en"
    assert language.turn_language(None) == "en"
    assert language.turn_language("tlh") == "en"
    assert language.english_name("nb") == "Norwegian Bokmål"
