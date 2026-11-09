"""Per-dataset settings, read **per activity** rather than at import.

A setting saved on the admin page has to reach activities that are already running,
and a module-level constant read once at worker start would ignore it until the next
restart.

The OCR language settings are retired. New ingestion and new processing updates use
automatic OCR (`tasks/automatic_ocr.py`), which reads no language setting, and the
website refuses a new language change. The readers below remain only for work that
Temporal histories still run on their earlier branches: workflows without the
`automatic-ocr-v1` patch, the `ChangeOcrLanguages` apply job, and recorded OCR update
steps with a `languages` detail. Remove them only when no stored history and no
retained data needs them.

The OCR languages of such work have one resolution order:

1. the dataset's own row (`ocr.<engine>.languages`), which can hold an empty EasyOCR
   value that turns EasyOCR off,
2. the collection default row (`ocr.default.<engine>.languages`, stored under the
   collection name),
3. the fixed installation defaults in `DEFAULTS`, which are the defaults of the
   removed `hoover4.ini` settings `tesseract_languages` and `easyocr_languages`.

A deleted row is a tombstone and resolution continues with the next level.
`resolve_ocr_languages` returns the value, its source and a version, and
`tasks/ocr_resolution_cases.json` tests it.

The cost of reading per activity is one ClickHouse query per file, which is why there is
a short process-local cache: `_CACHE_SECONDS` turns it into one query per activity burst
while still picking a change up within seconds.
"""

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Sequence

from tasks.text_sources import ENGINE_EASYOCR, ENGINE_TESSERACT, easyocr_language_groups

log = logging.getLogger(__name__)

#: Setting keys. Values are `+`-joined language codes in Tesseract's convention.
KEY_TESSERACT_LANGUAGES = "ocr.tesseract.languages"
KEY_EASYOCR_LANGUAGES = "ocr.easyocr.languages"

#: Collection defaults, stored in `dataset_settings` under the collection name. Every
#: dataset of the collection without its own row inherits them, including datasets that
#: existed before the default was saved.
KEY_DEFAULT_TESSERACT_LANGUAGES = "ocr.default.tesseract.languages"
KEY_DEFAULT_EASYOCR_LANGUAGES = "ocr.default.easyocr.languages"

#: The collection feature switch for vectors, stored under the collection name. `true`
#: or `false`. A collection without the row follows the installation, which is on when
#: an embeddings endpoint is configured.
KEY_FEATURE_VECTORS = "features.vectors"

#: The installation OCR defaults of the earlier branches. A dataset without a row of its
#: own and without a collection default uses these. They are constants, because no
#: setting sets them now.
DEFAULTS: Dict[str, str] = {
    KEY_TESSERACT_LANGUAGES: "eng",
    KEY_EASYOCR_LANGUAGES: "en",
}

#: The source names of a resolved OCR value. The website shows them.
SOURCE_DATASET = "dataset"
SOURCE_COLLECTION = "collection"
SOURCE_INSTALLATION = "installation"

#: The dataset key and the collection default key of each engine.
OCR_KEYS: Dict[str, tuple] = {
    ENGINE_TESSERACT: (KEY_TESSERACT_LANGUAGES, KEY_DEFAULT_TESSERACT_LANGUAGES),
    ENGINE_EASYOCR: (KEY_EASYOCR_LANGUAGES, KEY_DEFAULT_EASYOCR_LANGUAGES),
}

#: How long a read is reused. Short on purpose -- see the module docstring.
_CACHE_SECONDS = 10.0

_lock = threading.Lock()
_cache: Dict[str, tuple] = {}


@dataclass(frozen=True)
class SettingRow:
    """The latest stored row of one setting key."""

    value: str
    is_deleted: bool
    #: Microseconds since the epoch, the order of the rows of one key.
    version_us: int
    #: False when the version was copied from the earlier whole-second time.
    is_precise: bool


#: The latest complete row of each key. The value, the deletion flag and the version come
#: from one write, chosen by `setting_version_us`.
_LATEST_ROWS_SQL = (
    "SELECT key, argMax((value, is_deleted, setting_version_us, version_is_precise), "
    "setting_version_us) FROM dataset_settings "
    "WHERE collection_dataset = {cd:String} {keys}GROUP BY key"
)


def _latest_rows(client, collection_dataset: str,
                 keys: Sequence[str] = ()) -> Dict[str, SettingRow]:
    parameters = {"cd": collection_dataset}
    clause = ""
    if keys:
        clause = "AND key IN {keys:Array(String)} "
        parameters["keys"] = list(keys)
    rows = client.query(_LATEST_ROWS_SQL.replace("{keys}", clause),
                        parameters=parameters).result_rows
    return {key: SettingRow(str(value), bool(deleted), int(version), bool(precise))
            for key, (value, deleted, version, precise) in rows}


@dataclass(frozen=True)
class EffectiveSetting:
    """One resolved OCR language value, where it came from, and its version.

    `version_us` is the newest version among the rows that resolution read, tombstones
    included, so a reset to an inherited value has a version above the row it reset.
    It is 0 when no row exists. An OCR error newer than it belongs to this value
    (`tasks/ocr_targets.error_is_current`).
    """

    value: str
    source: str
    version_us: int = 0
    is_precise: bool = True


def resolve_ocr_languages(dataset_rows: Dict[str, SettingRow],
                          collection_rows: Dict[str, SettingRow],
                          installation: Dict[str, str]) -> Dict[str, EffectiveSetting]:
    """The effective languages of each OCR engine, by the order of the module docstring.

    `dataset_rows` are keyed by `ocr.<engine>.languages`, `collection_rows` by
    `ocr.default.<engine>.languages`, and `installation` by engine. Pure, so that the
    case file can test it.
    """
    resolved = {}
    for engine, (dataset_key, default_key) in OCR_KEYS.items():
        read = []
        chosen = None
        for row, source in ((dataset_rows.get(dataset_key), SOURCE_DATASET),
                            (collection_rows.get(default_key), SOURCE_COLLECTION)):
            if row is None:
                continue
            read.append(row)
            if not row.is_deleted:
                chosen = (row.value, source)
                break
        if chosen is None:
            chosen = (installation.get(engine, ""), SOURCE_INSTALLATION)
        newest = max(read, key=lambda row: row.version_us, default=None)
        resolved[engine] = EffectiveSetting(
            value=chosen[0], source=chosen[1],
            version_us=newest.version_us if newest else 0,
            is_precise=newest.is_precise if newest else True)
    return resolved


def installation_ocr_defaults() -> Dict[str, str]:
    """The fixed installation OCR languages of each engine."""
    return {engine: DEFAULTS[dataset_key] for engine, (dataset_key, _) in OCR_KEYS.items()}


def effective_ocr_settings(collection_dataset: str,
                           collectionname: str = "") -> Dict[str, EffectiveSetting]:
    """The effective OCR languages of one dataset, read now and not from the cache.

    Reads the dataset rows and the collection default rows in one query. Raises when
    the table cannot be read.
    """
    collectionname = collectionname or collection_of_dataset(collection_dataset)
    dataset_rows = latest_setting_rows(collection_dataset, [keys[0] for keys in OCR_KEYS.values()])
    collection_rows = (latest_setting_rows(collectionname, [keys[1] for keys in OCR_KEYS.values()])
                       if collectionname else {})
    return resolve_ocr_languages(dataset_rows, collection_rows, installation_ocr_defaults())


def collection_of_dataset(collection_dataset: str) -> str:
    """The collection of a registered dataset, or an empty string for another key."""
    from database.clickhouse import UnknownDatasetError, resolve_collection

    try:
        return resolve_collection(collection_dataset)
    except UnknownDatasetError:
        return ""


def collection_vectors_enabled(collectionname: str) -> bool:
    """Whether a collection uses vectors: its `features.vectors` row, else the installation.

    The installation is on when `EMBEDDINGS_URL` is set. A collection row cannot turn on
    a service that the installation does not run. The embedding stage then records its
    usual skip.
    """
    installation = bool((os.getenv("EMBEDDINGS_URL") or "").strip())
    if not installation:
        return False
    row = get_dataset_settings(collectionname).get(KEY_FEATURE_VECTORS, "")
    if row in ("true", "false"):
        return row == "true"
    return installation


def latest_setting_rows(collection_dataset: str, keys: Sequence[str]) -> Dict[str, SettingRow]:
    """The latest row of each of `keys`, read now and not from the cache.

    For a reader that needs a value together with its version. Raises when the table
    cannot be read.
    """
    from database.clickhouse import get_global_client

    with get_global_client() as client:
        return _latest_rows(client, collection_dataset, keys)


def _load(collection_dataset: str) -> Dict[str, str]:
    """Every stored setting of a key, with the OCR languages resolved.

    The key can also be a collection name, for the collection rows. The OCR values of a
    dataset follow `resolve_ocr_languages`. A key that is not a registered dataset keeps
    the installation OCR defaults.
    """
    from database.clickhouse import get_global_client

    values = dict(DEFAULTS)
    try:
        with get_global_client() as client:
            rows = _latest_rows(client, collection_dataset)
            collectionname = collection_of_dataset(collection_dataset)
            collection_rows = (_latest_rows(client, collectionname,
                                            [keys[1] for keys in OCR_KEYS.values()])
                               if collectionname else {})
    except Exception:
        # A settings read must never fail an activity: the defaults are the documented
        # behaviour, and failing here would turn a missing table into a failed dataset.
        log.warning("[config] could not read dataset_settings for %s, using defaults",
                    collection_dataset, exc_info=True)
        return values

    for key, row in rows.items():
        if not row.is_deleted:
            values[key] = row.value
    for engine, effective in resolve_ocr_languages(rows, collection_rows,
                                                   installation_ocr_defaults()).items():
        values[OCR_KEYS[engine][0]] = effective.value
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
    """Write one setting and drop this process's cache entry for the dataset.

    An unchanged live value writes nothing, so the setting keeps its version, and an OCR
    error written under it stays current. A new or changed value gets a version above the
    version of the row it replaces, in microseconds. The write waits for storage.
    """
    from database.clickhouse import get_global_client, insert_arrow_durable
    import pyarrow as pa

    with get_global_client() as client:
        latest = _latest_rows(client, collection_dataset, [key]).get(key)
        if latest is not None and not latest.is_deleted and latest.value == value:
            invalidate(collection_dataset)
            return
        now = datetime.now(timezone.utc)
        version = int(now.timestamp() * 1_000_000)
        if latest is not None:
            version = max(version, latest.version_us + 1)
        insert_arrow_durable(client, "dataset_settings", pa.table({
            "collection_dataset": pa.array([collection_dataset], type=pa.string()),
            "key": pa.array([key], type=pa.string()),
            "value": pa.array([value], type=pa.string()),
            "updated_at": pa.array([now.replace(tzinfo=None, microsecond=0)],
                                   type=pa.timestamp("s")),
            "setting_version_us": pa.array([version], type=pa.uint64()),
            "version_is_precise": pa.array([1], type=pa.uint8()),
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
