"""The language-model endpoint of the research agent.

`LLM_BASE_URL` serves `LLM_MODEL`, the one model of the self-hosted model server.

**Mirrored in `main_services/processing/tasks/llm_endpoints.py`.** The worker reads the
same variables for its own calls. The two readers change in the same patch.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: The bearer token sent when the model server has no API key. The OpenAI client refuses
#: an empty key, and a server without login ignores this one.
PLACEHOLDER_KEY = "unused"


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    api_key: str


def base_api_key() -> str:
    """The key of the endpoint: `LLM_API_KEY`, else the bind-mounted key file."""
    value = (os.getenv("LLM_API_KEY") or "").strip()
    if value:
        return value
    path = (os.getenv("LLM_API_KEY_FILE") or "").strip()
    if path and os.path.exists(path):
        with open(path) as handle:
            return handle.read().strip()
    return ""


def endpoint() -> Endpoint:
    """The endpoint of the model server. The key is `PLACEHOLDER_KEY` when the server has
    none."""
    return Endpoint((os.getenv("LLM_BASE_URL") or "").strip().rstrip("/"),
                    base_api_key() or PLACEHOLDER_KEY)
