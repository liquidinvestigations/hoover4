"""The size of the next model request, measured before the request is sent.

`/model_step` measures the whole input of the call: the system text, the schemas of the
bound tools, and every message of the list that the model receives, with the tool results
that the worker stored after the previous reply. The billed tokens of the previous reply are
telemetry. They do not include those new results, so they are not the size of this request.

**Two methods.** When the model's context window is known, the service asks the served
tokenizer (`agent_common.result_pages.TokenCounter`, `POST .../tokenize`) to count the text
of the request, and adds `MESSAGE_FRAME_TOKENS` for each message. The count has method
`tokenizer`. When the tokenizer fails or the window is unknown, the size is the estimate of
`compaction.Estimator`: the characters of the request times the ratio of tokens to
characters that the newest billed call gives, between 1/6 and 1/1.5, with a 5 percent
margin, and 1/3 when no call is billed. The size then has method `estimate`. A failed
tokenizer is not asked again for `TOKENIZER_RETRY_SECONDS`, so a provider with no tokenizer
route costs one failed request in that time.

**The safe input.** The safe input of a request is the context window less the output
reserve. The reserve is `AGENT_MAX_OUTPUT_TOKENS` when it is set, because the model client
sends the same value as its output cap. When it is not set, the reserve is
`ESTIMATED_OUTPUT_RESERVE`, and its source is `estimate`: the service sends no cap, so the
fit of a reply is not guaranteed. An unknown window (0) has no safe input.

`RequestSize.record()` is the `request_size` object that the `model_turn` frame carries in
its usage. The worker stores it with the reply.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Sequence

from agent_common.result_pages import TokenCounter
from research_agent import compaction, model_params
from research_agent.run_messages import RunMessage

log = logging.getLogger(__name__)

#: The tokens that the chat template adds around one message. An upper value for the
#: served templates, which wrap a message in a role marker and an end marker.
MESSAGE_FRAME_TOKENS = 8

#: The output reserve when `AGENT_MAX_OUTPUT_TOKENS` is not set. An estimate of one long
#: answer. The request sends no cap in that case.
ESTIMATED_OUTPUT_RESERVE = 8192

#: The time after a failed tokenizer request in which the service uses the estimate and
#: sends no tokenizer request.
TOKENIZER_RETRY_SECONDS = 300.0

#: The monotonic time until which the tokenizer of a base URL is not asked, after a failure.
_tokenizer_down: Dict[str, float] = {}


@dataclass(frozen=True)
class RequestSize:
    """The measured size of one model request, and the limits it is compared with."""

    #: The tokens of the whole request input.
    tokens: int
    #: `tokenizer` or `estimate`.
    method: str
    #: The model's stated context window, or 0 when no catalog states it.
    window: int
    output_reserve: int
    #: `configured` when `AGENT_MAX_OUTPUT_TOKENS` sets the reserve, else `estimate`.
    reserve_source: str
    model: str = ""
    #: Why the tokenizer was not used, when the method is `estimate` with a known window.
    error: str = ""

    @property
    def safe_input(self) -> int:
        """The window less the output reserve, or 0 when the window is unknown."""
        if self.window <= 0:
            return 0
        return max(0, self.window - self.output_reserve)

    @property
    def fits(self) -> bool:
        """False when the window is known and the request passes the safe input."""
        return self.window <= 0 or self.tokens <= self.safe_input

    def record(self) -> Dict[str, Any]:
        """The `request_size` object of the reply's usage."""
        return {
            "tokens": self.tokens, "method": self.method, "model": self.model,
            "window": self.window, "window_known": self.window > 0,
            "output_reserve": self.output_reserve, "reserve_source": self.reserve_source,
            "safe_input": self.safe_input, "fits": self.fits, "error": self.error,
        }


def output_reserve() -> tuple[int, str]:
    """The output reserve and its source: `configured` or `estimate`."""
    cap = model_params.max_output_tokens()
    if cap is not None:
        return cap, "configured"
    return ESTIMATED_OUTPUT_RESERVE, "estimate"


def request_text(system_text: str, schemas_json: str, messages: Sequence[RunMessage]) -> str:
    """The text of a request that the tokenizer counts: the system text, the tool schemas,
    and each message's content, call names and call arguments."""
    parts = [system_text or "", schemas_json or ""]
    for m in messages:
        parts.append(m.content or "")
        for call in m.tool_calls:
            parts.append(call.name)
            parts.append(json.dumps(call.args, ensure_ascii=False))
    return "\n".join(parts)


def _api_key() -> Optional[str]:
    value = (os.getenv("LLM_API_KEY") or "").strip()
    path = (os.getenv("LLM_API_KEY_FILE") or "").strip()
    if not value and path and os.path.exists(path):
        with open(path) as handle:
            value = handle.read().strip()
    return value or None


def _default_counter(model_id: str) -> Any:
    return TokenCounter(os.getenv("LLM_BASE_URL") or "", model_id, _api_key())


def measure(system_text: str, schemas_json: str, messages: Sequence[RunMessage], *,
            model_id: str, window: int,
            counter_for: Optional[Callable[[str], Any]] = None,
            now: Optional[float] = None) -> RequestSize:
    """Measure one request. `messages` is the list that the model receives, with the
    stored compactions applied. `counter_for(model_id)` returns an object with `count`,
    and a test passes a fake one."""
    reserve, source = output_reserve()
    clock = time.monotonic() if now is None else now
    base = os.getenv("LLM_BASE_URL") or ""
    error = ""
    if window > 0:
        if _tokenizer_down.get(base, 0.0) > clock:
            error = "the tokenizer failed within the last retry interval"
        else:
            try:
                counter = (counter_for or _default_counter)(model_id)
                tokens = counter.count(request_text(system_text, schemas_json, messages))
                return RequestSize(int(tokens) + MESSAGE_FRAME_TOKENS * len(messages),
                                   "tokenizer", window, reserve, source, model_id)
            except Exception as exc:  # noqa: BLE001 - every count failure uses the estimate
                _tokenizer_down[base] = clock + TOKENIZER_RETRY_SECONDS
                error = f"{type(exc).__name__}: {exc}"[:300]
                log.warning("the tokenizer did not count the request of %s, the size is an "
                            "estimate: %s", model_id, error)
    est = compaction.Estimator.calibrate(messages, system_text, schemas_json)
    tokens = est.fixed + est.list_size(messages)
    return RequestSize(tokens, "estimate", window, reserve, source, model_id, error)


__all__ = [
    "ESTIMATED_OUTPUT_RESERVE", "MESSAGE_FRAME_TOKENS", "RequestSize", "TOKENIZER_RETRY_SECONDS",
    "measure", "output_reserve", "request_text",
]
