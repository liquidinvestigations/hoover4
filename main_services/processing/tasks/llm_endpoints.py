"""The language-model endpoint and its model name.

The self-hosted model server serves one model. `LLM_BASE_URL` serves `LLM_MODEL`, the
model of agent turns, board assessments, report conversions and every short call:
titles, summaries, follow-up suggestions and board labels.

The research agent reads the same variables in `research_agent/endpoints.py`. Both read
the variables that `deploy.py` renders from `[ai_services]` when `llm_enabled` is true.
"""

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    api_key: str
    label: str


def chat_model() -> str:
    """The model of every call, `LLM_MODEL`, or empty when the model server is off.

    `hoover4.ini` sets it. No setting overrides it.
    **Mirrored in `website/backend/src/api/admin/llm.rs`** (`agent_model`)."""
    return (os.getenv("LLM_MODEL") or "").strip()


def _label(base_url: str) -> str:
    from tasks.llm_catalog import provider_label

    host = re.sub(r"^https?://", "", base_url).split("/")[0]
    return provider_label(host) if host else "unknown"


def base_api_key() -> str:
    """The key of the endpoint: `LLM_API_KEY`, else the bind-mounted key file."""
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


def endpoint() -> Endpoint:
    """The endpoint of the model server. An empty base URL means that the model server is
    off."""
    base = (os.getenv("LLM_BASE_URL") or "").strip().rstrip("/")
    name = (os.getenv("LLM_PROVIDER_NAME") or "").strip()
    return Endpoint(base, base_api_key(), name or (_label(base) if base else "unknown"))
