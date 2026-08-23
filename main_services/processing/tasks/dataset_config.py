"""Per-dataset settings, read **per activity** rather than at import.

A language change dispatched from the dataset admin page has to reach activities that
are already running, which is what the apply job exists for, and a module-level
constant read once at worker start would silently ignore it until the next restart.

The cost of reading per activity is one ClickHouse query per file, which is why there is
a short process-local cache: `_CACHE_SECONDS` turns it into one query per activity burst
while still picking a change up within seconds. Do not raise it to "one minute, nobody
will notice" -- the admin form waits on the job that depends on this.
"""

import logging
import os
import threading
import time
from typing import Dict, List

from tasks.text_sources import ENGINE_EASYOCR, ENGINE_TESSERACT, easyocr_language_groups

log = logging.getLogger(__name__)

#: Setting keys. Values are `+`-joined language codes in Tesseract's convention.
KEY_TESSERACT_LANGUAGES = "ocr.tesseract.languages"
KEY_EASYOCR_LANGUAGES = "ocr.easyocr.languages"

#: Collection-level defaults a newly created dataset inherits. A dataset's own row
#: always wins; these only fill in what was never set.
KEY_DEFAULT_TESSERACT_LANGUAGES = "ocr.default.tesseract.languages"
KEY_DEFAULT_EASYOCR_LANGUAGES = "ocr.default.easyocr.languages"

#: Stack-wide defaults, from hoover4.ini via the worker environment. A dataset that has
#: never been configured uses these; the moment the admin page writes a row, that row
#: wins for that dataset and the default stops applying to it.
#:
#: Read at import rather than per activity on purpose: this is deployment configuration,
#: which cannot change without recreating the container anyway. The per-*dataset* values
#: below it are the ones that must be re-read live.
DEFAULTS: Dict[str, str] = {
    KEY_TESSERACT_LANGUAGES: (os.getenv("TESSERACT_LANGUAGES") or "eng").strip() or "eng",
    KEY_EASYOCR_LANGUAGES: (os.getenv("EASYOCR_LANGUAGES") or "en").strip() or "en",
}

#: How long a read is reused. Short on purpose -- see the module docstring.
_CACHE_SECONDS = 10.0

_lock = threading.Lock()
_cache: Dict[str, tuple] = {}


def _load(collection_dataset: str) -> Dict[str, str]:
    from database.clickhouse import get_global_client

    values = dict(DEFAULTS)
    try:
        with get_global_client() as client:
            rows = client.query(
                "SELECT key, argMax(value, updated_at) FROM dataset_settings "
                "WHERE collection_dataset = {cd:String} "
                "GROUP BY key HAVING argMax(is_deleted, updated_at) = 0",
                parameters={"cd": collection_dataset},
            ).result_rows
    except Exception:
        # A settings read must never fail an activity: the defaults are the documented
        # behaviour, and failing here would turn a missing table into a failed dataset.
        log.warning("[config] could not read dataset_settings for %s, using defaults",
                    collection_dataset, exc_info=True)
        return values

    for key, value in rows:
        values[key] = value
    return values


def get_dataset_settings(collection_dataset: str) -> Dict[str, str]:
    """Every setting for one dataset, defaults filled in, cached for a few seconds."""
    now = time.monotonic()
    with _lock:
        entry = _cache.get(collection_dataset)
        if entry is not None and now - entry[0] < _CACHE_SECONDS:
            return dict(entry[1])

    values = _load(collection_dataset)
    with _lock:
        _cache[collection_dataset] = (now, values)
    return dict(values)


def get_setting(collection_dataset: str, key: str, default: str = "") -> str:
    return get_dataset_settings(collection_dataset).get(key, DEFAULTS.get(key, default))


def invalidate(collection_dataset: str = "") -> None:
    """Drop cached settings. Called by the apply job after it writes.

    Only clears *this* process's cache -- the workers run as seven processes and the
    others pick the change up on their own expiry. That bounded staleness is what
    `_CACHE_SECONDS` is sized for.
    """
    with _lock:
        if collection_dataset:
            _cache.pop(collection_dataset, None)
        else:
            _cache.clear()


def set_dataset_setting(collection_dataset: str, key: str, value: str) -> None:
    """Write one setting and drop this process's cache entry for the dataset."""
    from database.clickhouse import get_global_client
    import pyarrow as pa

    with get_global_client() as client:
        client.insert_arrow("dataset_settings", pa.table({
            "collection_dataset": pa.array([collection_dataset], type=pa.string()),
            "key": pa.array([key], type=pa.string()),
            "value": pa.array([value], type=pa.string()),
        }))
    invalidate(collection_dataset)


def tesseract_languages(collection_dataset: str) -> str:
    """The `+`-joined language set for one Tesseract pass.

    Tesseract takes them all at once and picks per region, so this is a single pass and
    a single text variant no matter how many languages are listed.
    """
    return get_setting(collection_dataset, KEY_TESSERACT_LANGUAGES)


def easyocr_passes(collection_dataset: str) -> List[str]:
    """The EasyOCR passes for one dataset, one `+`-joined language set per pass.

    Unlike Tesseract this is a *list*: EasyOCR builds one model per Reader and cannot mix
    scripts, so a dataset configured for `en+ru` runs twice and stores two variants.
    """
    return easyocr_language_groups(get_setting(collection_dataset, KEY_EASYOCR_LANGUAGES))


def ocr_language_key(engine: str) -> str:
    if engine == ENGINE_TESSERACT:
        return KEY_TESSERACT_LANGUAGES
    if engine == ENGINE_EASYOCR:
        return KEY_EASYOCR_LANGUAGES
    raise ValueError(f"unknown OCR engine {engine!r}")
