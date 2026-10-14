"""The language-model endpoint of each model name.

`LLM_BASE_URL` serves `LLM_MODEL` and every model that is not the quality model.
`LLM_QUALITY_BASE_URL` serves `LLM_QUALITY_MODEL`, the model that the chat profiles select
for agent turns. A request goes to the quality endpoint when it names the quality model.

**Mirrored in `main_services/processing/tasks/llm_endpoints.py`.** The worker applies the
same rule to its own calls. The two readers change in the same patch.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: The bearer token sent to a quality endpoint when the provider has no API key. The
#: OpenAI client refuses an empty key, and a server without login ignores this one.
QUALITY_PLACEHOLDER_KEY = "unused"


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    api_key: str
    is_quality: bool


def quality_model() -> str:
    """The model that the quality endpoint serves, or empty when there is none."""
    if not (os.getenv("LLM_QUALITY_BASE_URL") or "").strip():
        return ""
    return (os.getenv("LLM_QUALITY_MODEL") or "").strip()


def base_api_key() -> str:
    """The key of the base endpoint: `LLM_API_KEY`, else the bind-mounted key file."""
    value = (os.getenv("LLM_API_KEY") or "").strip()
    if value:
        return value
    path = (os.getenv("LLM_API_KEY_FILE") or "").strip()
    if path and os.path.exists(path):
        with open(path) as handle:
            return handle.read().strip()
    return ""


def endpoint_for(model: str) -> Endpoint:
    """The endpoint that serves `model`."""
    quality = quality_model()
    if quality and (model or "").strip() == quality:
        return Endpoint((os.getenv("LLM_QUALITY_BASE_URL") or "").strip().rstrip("/"),
                        base_api_key() or QUALITY_PLACEHOLDER_KEY, True)
    return Endpoint((os.getenv("LLM_BASE_URL") or "").strip().rstrip("/"), base_api_key(), False)
