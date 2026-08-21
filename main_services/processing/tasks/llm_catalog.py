"""Discover LLM models from each provider and store them in `llm_models`.

Why discovery instead of a constant
-----------------------------------
NIM retires model ids. A hardcoded one turns into a 404 months after the code was
written, in a code path nobody exercises until a user opens the chat. So the chat and
summarisation models are *matched by pattern* against the live `/v1/models` list and the
result is written into `server_settings`, where an admin can see and change it.

Refresh discipline
------------------
"Refresh if older than 3h" with N concurrent readers is a thundering herd against every
provider, on the request path. This module is therefore:

* **single-flight** — an in-process lock, so N concurrent callers make one round of
  requests;
* **time-boxed per provider** — one slow provider cannot hold the refresh open;
* **stale-tolerant** — `fetched_at` marks rows as stale, and callers serve stale rows
  rather than waiting.

It never blocks a request path itself: it is invoked from the CLI and from a background
task, and readers query `llm_models` directly.
"""

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

#: Connect fast, read patiently but finitely — the same two-tuple discipline
#: `tasks/remote.py` exists to enforce. A provider that is down must not cost more than
#: a couple of seconds per refresh.
CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = float(os.getenv("LLM_CATALOG_READ_TIMEOUT_SECONDS", "5"))

#: Preference order for the chat model. Matched as regexes, case-insensitively, against
#: the ids the account actually returns — never used as ids themselves.
#:
#: Nemotron Super before Ultra deliberately: measured against this account, Super
#: answers a tool-calling smoke test in 1.4 s and Ultra in 7.3 s for the same tool call.
#: Ultra stays as the fallback pattern because Super is the one more likely to be
#: retired first.
CHAT_MODEL_PATTERNS = (
    r"nemotron.*super",
    r"nemotron.*ultra",
    r"nemotron.*\d+b",
)

#: Summarisation runs in the background on every conversation, so it prefers something
#: small. A nano/mini Nemotron first, then whatever the chat model turned out to be.
SUMMARIZATION_MODEL_PATTERNS = (
    r"nemotron.*nano",
    r"nemotron.*mini",
    r"nemotron.*super",
)

SETTING_CHAT_MODEL = "llm_default_chat_model"
SETTING_SUMMARIZATION_MODEL = "llm_summarization_model"

_refresh_lock = threading.Lock()


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str = ""
    enabled: bool = True


@dataclass
class RefreshResult:
    provider: str
    ok: bool
    model_count: int = 0
    error: str = ""
    models: List[str] = field(default_factory=list)
    #: `{model_id: context_window}` for the models whose listing said. Absent means the
    #: provider did not say, and the stored value stays 0 — a consumer showing "% of
    #: context used" hides the percentage rather than dividing by an invented number.
    context_windows: Dict[str, int] = field(default_factory=dict)


def providers_from_env() -> List[ProviderConfig]:
    """The providers this container was configured with.

    Only one is rendered into the environment today (`LLM_BASE_URL` / `LLM_MODEL` /
    `LLM_API_KEY_FILE`, from the ini's single active provider). Returning a list keeps
    the caller shaped for the multi-provider catalog the admin page wants, without
    pretending the extra providers exist.
    """
    base_url = (os.getenv("LLM_BASE_URL") or "").strip()
    if not base_url:
        return []

    api_key = ""
    key_file = (os.getenv("LLM_API_KEY_FILE") or "").strip()
    if key_file and os.path.exists(key_file):
        try:
            api_key = open(key_file).read().strip()
        except OSError:
            log.warning("could not read LLM_API_KEY_FILE at %s", key_file)

    # The provider *name* is not rendered separately, so derive a stable one from the
    # host. It is only a label -- the base_url is what identifies the endpoint.
    name = (os.getenv("LLM_PROVIDER_NAME") or "").strip()
    if not name:
        name = provider_label(re.sub(r"^https?://", "", base_url).split("/")[0])
    return [ProviderConfig(name=name, base_url=base_url.rstrip("/"), api_key=api_key)]


def provider_label(host: str) -> str:
    """A short, stable name for one endpoint's host.

    A registrable domain is named by its second-to-last label: `api.moonshot.ai` is
    `moonshot`. An address literal has no such label, and taking one anyway names the
    provider after an octet of its IP -- `10.69.70.115:21960` becomes `70` -- so the
    host and its port are kept whole. That is also the string the admin page synthesises
    for a configured endpoint with no catalog rows yet, so the row a refresh writes
    lands on the same provider the page was already showing rather than beside it.
    """
    host = host.strip()
    if host.startswith("["):
        return host
    bare = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    if re.fullmatch(r"[0-9.]+", bare):
        return host
    if bare.count(".") >= 1:
        return bare.split(".")[-2]
    return bare


def fetch_models(provider: ProviderConfig) -> RefreshResult:
    """List one provider's models. Never raises: a dead provider is a result, not a crash."""
    import requests

    headers = {"Accept": "application/json"}
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"

    try:
        response = requests.get(
            f"{provider.base_url}/models",
            headers=headers,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return RefreshResult(provider=provider.name, ok=False,
                             error=f"{type(exc).__name__}: {exc}")

    entries = [m for m in (payload.get("data") or []) if m.get("id")]
    models = [m["id"] for m in entries]
    return RefreshResult(provider=provider.name, ok=True,
                         model_count=len(models), models=sorted(models),
                         context_windows={
                             m["id"]: window for m in entries
                             if (window := _context_window(m))
                         })


#: Where a provider states a model's context length, in the order to try.
#:
#: `max_model_len` is vLLM's; `context_length` is what most OpenAI-compatible gateways
#: use; `context_window` is the name the table itself uses and some providers echo it.
#: There is no fallback guess: a wrong denominator is worse than none, because every
#: number computed from it looks calculated.
_CONTEXT_WINDOW_KEYS = ("max_model_len", "context_length", "context_window")


def _context_window(entry: dict) -> int:
    for key in _CONTEXT_WINDOW_KEYS:
        raw = entry.get(key)
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0


def pick_model(model_ids: List[str], patterns) -> Optional[str]:
    """First id matching the first pattern that matches anything.

    Patterns are tried in order and the *shortest* matching id wins within a pattern,
    which reliably prefers `nemotron-3-super-120b-a12b` over a dated or suffixed variant
    of the same family without hardcoding either.
    """
    for pattern in patterns:
        rx = re.compile(pattern, re.IGNORECASE)
        matches = sorted((m for m in model_ids if rx.search(m)), key=lambda m: (len(m), m))
        if matches:
            return matches[0]
    return None


def _is_reasoning(model_id: str) -> bool:
    """Nemotron emits reasoning content that must be stripped from the answer body.

    Recorded per model so the chat path can decide without a second probe -- shipping the
    model's scratchpad into a transcript is a visible bug, and detecting it at render
    time is too late.
    """
    return bool(re.search(r"nemotron|reason|thinking|deepseek-r", model_id, re.IGNORECASE))


def _prior_allowed(client, provider: str) -> Dict[str, int]:
    """`{model_id: is_allowed}` as the table stands now, for one provider.

    `llm_models` is a ReplacingMergeTree read through `argMax(..., updated_at)`, and
    `is_allowed` defaults to 1. So an insert that simply omits the column writes a fresher
    "allowed" version and **undoes an admin's disallow** — silently, on a schedule. The
    allowlist is enforced server-side against forged model ids, so that is a security
    control being reset by a background task, not a cosmetic dropdown.

    The website's own refresh (`api/admin/llm.rs`) carries the same state forward for the
    same reason. Both writers must, or whichever runs last wins.
    """
    rows = client.query(
        "SELECT model_id, argMax(is_allowed, updated_at) AS is_allowed "
        "FROM llm_models WHERE provider = %(provider)s GROUP BY model_id LIMIT 5000",
        parameters={"provider": provider},
    ).result_rows
    return {row[0]: int(row[1]) for row in rows}


def store_models(result: RefreshResult, base_url: str) -> int:
    """Upsert one provider's models into `llm_models`. Returns rows written."""
    from datetime import datetime, timezone

    import pyarrow as pa

    from database.clickhouse import get_global_client

    if not result.ok or not result.models:
        return 0

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    count = len(result.models)
    with get_global_client() as client:
        prior = _prior_allowed(client, result.provider)
        client.insert_arrow("llm_models", pa.table({
            "provider": pa.array([result.provider] * count, type=pa.string()),
            "model_id": pa.array(result.models, type=pa.string()),
            "display_name": pa.array([m.split("/")[-1] for m in result.models], type=pa.string()),
            # 0 where the provider did not say. Nothing downstream may substitute a
            # default: a token-budget percentage against a made-up denominator reads as
            # a measurement.
            "context_window": pa.array(
                [result.context_windows.get(m, 0) for m in result.models], type=pa.uint32()
            ),
            "is_reasoning": pa.array([1 if _is_reasoning(m) else 0 for m in result.models],
                                     type=pa.uint8()),
            # Carried forward, never re-defaulted. A model nobody has ruled on is allowed.
            "is_allowed": pa.array([prior.get(m, 1) for m in result.models], type=pa.uint8()),
            "fetched_at": pa.array([now] * count, type=pa.timestamp("s")),
            "updated_at": pa.array([now] * count, type=pa.timestamp("s")),
        }))
    log.info("stored %d models for provider %s (%s)", count, result.provider, base_url)
    return count


def set_server_setting(key: str, value: str) -> None:
    import pyarrow as pa

    from database.clickhouse import get_global_client

    with get_global_client() as client:
        client.insert_arrow("server_settings", pa.table({
            "key": pa.array([key], type=pa.string()),
            "value": pa.array([value], type=pa.string()),
        }))


def refresh_catalog(*, choose_defaults: bool = True) -> List[RefreshResult]:
    """Refresh every configured provider and, optionally, pick the default models.

    Single-flight: a second concurrent caller returns immediately with an empty list
    rather than duplicating the round of requests.
    """
    if not _refresh_lock.acquire(blocking=False):
        log.info("catalog refresh already in flight; serving stale rows")
        return []
    try:
        results = []
        all_ids: List[str] = []
        for provider in providers_from_env():
            started = time.time()
            result = fetch_models(provider)
            elapsed_ms = int((time.time() - started) * 1000)
            if result.ok:
                store_models(result, provider.base_url)
                all_ids.extend(result.models)
                log.info("provider %s: %d models in %d ms",
                         result.provider, result.model_count, elapsed_ms)
            else:
                log.warning("provider %s failed in %d ms: %s",
                            result.provider, elapsed_ms, result.error)
            results.append(result)

        if choose_defaults and all_ids:
            chat = pick_model(all_ids, CHAT_MODEL_PATTERNS)
            summary = pick_model(all_ids, SUMMARIZATION_MODEL_PATTERNS) or chat
            if chat:
                set_server_setting(SETTING_CHAT_MODEL, chat)
                log.info("chat model: %s", chat)
            if summary:
                set_server_setting(SETTING_SUMMARIZATION_MODEL, summary)
                log.info("summarisation model: %s", summary)

        return results
    finally:
        _refresh_lock.release()
