"""Shared test settings.

Most `/tool_call` tests send a call without the skill and tool reads that a live run makes
first. The prerequisite check (`research_agent.prerequisites`) is off for them. A test with
the marker `prerequisites` runs with the check on.
"""

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "prerequisites: run /tool_call with the read check on")


@pytest.fixture(autouse=True)
def _prerequisite_check(request, monkeypatch):
    if request.node.get_closest_marker("prerequisites") is None:
        from research_agent import steps

        monkeypatch.setattr(steps, "prerequisite_refusal", lambda *args, **kwargs: "")
