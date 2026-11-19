"""The readiness of the NER and embedding capabilities, for the processing update coordinator.

`probe_capability_readiness` reads each capability once and returns one state for each:

* `disabled`: the installation has no endpoint for the capability, so it creates no work;
* `ready`: the service answers `/health` and reports its model as loaded;
* `unavailable`: the service does not answer, answers with an HTTP error, or reports its
  model as not loaded;
* `misconfigured`: a setting that the work needs is absent, for example the probed
  embedding model in `server_settings`.

The coordinator starts no automatic NER or vector operation unless its capability is
`ready`. A `ready` answer does not prove that a later request succeeds, so the activities
of that work also wait for outages (`tasks/remote_busy_retry.py`). The probe does not send
the GPU key, because `/health` needs none, and no error text names a key.
"""

import logging
import os

import requests
from temporalio import activity

from tasks.heartbeat import with_heartbeat

log = logging.getLogger(__name__)

DISABLED = "disabled"
READY = "ready"
UNAVAILABLE = "unavailable"
MISCONFIGURED = "misconfigured"

#: Each capability: its endpoint variable and the `/health` key of its model.
CAPABILITIES = {
    "ner": ("NER_URL", "ner_model_loaded"),
    "embeddings": ("EMBEDDINGS_URL", "embedding_model_loaded"),
}

#: The read timeout of one `/health` request, in seconds.
HEALTH_READ_TIMEOUT = 10.0


def capability_readiness(name: str, session=None) -> str:
    """The state of one capability. See the module docstring."""
    from tasks.remote import CONNECT_TIMEOUT

    variable, loaded_key = CAPABILITIES[name]
    base = (os.getenv(variable) or "").strip().rstrip("/")
    if not base:
        return DISABLED
    if name == "embeddings":
        from database.clickhouse import get_server_setting

        if not get_server_setting("embeddings_serving_model") or not get_server_setting("embeddings_serving_dim"):
            return MISCONFIGURED
    try:
        response = (session or requests).get(f"{base}/health",
                                             timeout=(CONNECT_TIMEOUT, HEALTH_READ_TIMEOUT))
    except (requests.ConnectionError, requests.Timeout) as exc:
        log.info("capability %s is unavailable: %s", name, type(exc).__name__)
        return UNAVAILABLE
    if response.status_code != 200:
        log.info("capability %s is unavailable: HTTP %s", name, response.status_code)
        return UNAVAILABLE
    try:
        health = response.json()
    except ValueError:
        return UNAVAILABLE
    if not isinstance(health, dict) or health.get(loaded_key) is False:
        return UNAVAILABLE
    return READY


@activity.defn
@with_heartbeat
def probe_capability_readiness(names: list[str]) -> dict[str, str]:
    """The state of each named capability. An unknown name is `misconfigured`."""
    return {name: capability_readiness(name) if name in CAPABILITIES else MISCONFIGURED
            for name in names}
