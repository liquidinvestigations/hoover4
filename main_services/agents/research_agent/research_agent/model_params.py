"""The request parameters that every model call of this service sends.

This module is the one owner of the provider rule in the agent service. Each variable is
rendered by `deploy.py` into both agent services.

| variable | key | empty or unset means |
|---|---|---|
| `LLM_SEND_TEMPERATURE` | `[llm_provider.*] send_temperature` | true: send `temperature` |
| `AGENT_MAX_OUTPUT_TOKENS` | `[main_services] agent_max_output_tokens` | no output cap |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `[main_services] llm_request_timeout_seconds` | the client defaults |

**Mirrored in `main_services/processing/tasks/P_agent/summarize.py`**, which reads
`LLM_SEND_TEMPERATURE` with the same rule for the conversation title. The two readers change
in the same patch.
"""

from __future__ import annotations

import os
from typing import Any, Dict

#: The connect timeout of a model request, in seconds.
CONNECT_TIMEOUT_SECONDS = 10.0


def send_temperature() -> bool:
    """`LLM_SEND_TEMPERATURE`. Empty or unset is true.

    A provider whose section sets `send_temperature = false` rejects `temperature`, so a
    request to it leaves the parameter out.
    """
    raw = (os.getenv("LLM_SEND_TEMPERATURE") or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _positive_number(name: str) -> float | None:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None
    if value <= 0:
        raise ValueError(f"{name} must be above 0, got {raw!r}")
    return value


def max_output_tokens() -> int | None:
    """`AGENT_MAX_OUTPUT_TOKENS`. Empty or unset is None, which sends no cap."""
    value = _positive_number("AGENT_MAX_OUTPUT_TOKENS")
    return int(value) if value is not None else None


def request_timeout() -> tuple[float, float] | None:
    """(connect, `LLM_REQUEST_TIMEOUT_SECONDS`). Unset is None, which keeps the client default."""
    value = _positive_number("LLM_REQUEST_TIMEOUT_SECONDS")
    return (CONNECT_TIMEOUT_SECONDS, value) if value is not None else None


def sampling_params(temperature: float) -> Dict[str, Any]:
    """The parameters every chat completion of this service sends.

    `{"temperature": t}` when `send_temperature()`, and `{"max_tokens": n}` when
    `max_output_tokens()` is set. Nothing else.
    """
    params: Dict[str, Any] = {}
    if send_temperature():
        params["temperature"] = temperature
    cap = max_output_tokens()
    if cap is not None:
        params["max_tokens"] = cap
    return params


def client_kwargs() -> Dict[str, Any]:
    """Return the `timeout` and `max_retries` of the agent's model client.

    When `LLM_REQUEST_TIMEOUT_SECONDS` is set, `timeout` is the tuple `request_timeout()`
    returns, (connect, read), and the client does not retry, because each retry would add
    one more timeout. `langchain-openai` accepts the tuple, and httpx reads it as the
    connect and read timeouts. It refuses an `httpx.Timeout`, which is not hashable. When
    the variable is unset, both are left out and the client keeps its own defaults.
    """
    timeout = request_timeout()
    if timeout is None:
        return {}
    return {"timeout": timeout, "max_retries": 0}
