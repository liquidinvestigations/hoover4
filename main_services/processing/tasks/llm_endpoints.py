"""The language-model endpoint of each model name.

The selfhosted provider can have a second, quality endpoint beside its base endpoint.
`LLM_BASE_URL` serves `LLM_MODEL` and every short call: titles, summaries, board labels and
assessments. `LLM_QUALITY_BASE_URL` serves `LLM_QUALITY_MODEL`, the model of agent turns when
it is set (`chat_model`). A request goes to the quality endpoint when it names the quality
model, and to the base endpoint otherwise.

The research agent applies the same rule in `research_agent/endpoints.py`. Both read the
variables that `deploy.py` renders from `[llm_provider.selfhosted]`.
"""

import os
import re
from dataclasses import dataclass

#: The bearer token sent to a quality endpoint when the provider has no API key. The
#: OpenAI clients refuse an empty key, and a server without login ignores this one.
QUALITY_PLACEHOLDER_KEY = "unused"


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    api_key: str
    label: str


def quality_model() -> str:
    """The model that the quality endpoint serves, or empty when there is none."""
    if not (os.getenv("LLM_QUALITY_BASE_URL") or "").strip():
        return ""
    return (os.getenv("LLM_QUALITY_MODEL") or "").strip()


def chat_model() -> str:
    """The model of agent turns: the quality model when there is one, else `LLM_MODEL`.

    `hoover4.ini` sets both. No setting overrides them.
    **Mirrored in `website/backend/src/api/admin/llm.rs`** (`agent_model`)."""
    return quality_model() or short_model()


def short_model() -> str:
    """The model of short calls: titles, summaries, board labels and assessments."""
    return (os.getenv("LLM_MODEL") or "").strip()


def _label(base_url: str) -> str:
    from tasks.llm_catalog import provider_label

    host = re.sub(r"^https?://", "", base_url).split("/")[0]
    return provider_label(host) if host else "unknown"


def base_api_key() -> str:
    """The key of the base endpoint: `LLM_API_KEY`, else the bind-mounted key file."""
    key = (os.getenv("LLM_API_KEY") or "").strip()
    if key:
        return key
    path = (os.getenv("LLM_API_KEY_FILE") or "").strip()
    if path:
        try:
            with open(path) as handle:
                return handle.read().strip()
        except OSError:
            return ""
    return ""


def endpoint_for(model: str) -> Endpoint:
    """The endpoint that serves `model`. An empty base URL means no provider."""
    quality = quality_model()
    if quality and (model or "").strip() == quality:
        base = (os.getenv("LLM_QUALITY_BASE_URL") or "").strip().rstrip("/")
        return Endpoint(base, base_api_key() or QUALITY_PLACEHOLDER_KEY, _label(base))
    base = (os.getenv("LLM_BASE_URL") or "").strip().rstrip("/")
    name = (os.getenv("LLM_PROVIDER_NAME") or "").strip()
    return Endpoint(base, base_api_key(), name or (_label(base) if base else "unknown"))
