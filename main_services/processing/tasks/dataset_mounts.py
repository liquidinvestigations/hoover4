"""Read the dataset mounts from ``HOOVER4_DATASET_MOUNTS``.

``deploy.py`` renders the value from the ``[dataset_mount.*]`` sections of ``hoover4.ini``
into the generated Compose overlay of the worker and the website. It is a JSON list of
objects with the fields ``name``, ``path`` (the container path) and ``writable``.

A missing or empty value gives one mount named ``testdata`` at ``DATASETS_MOUNT_PATH``
(``/testdata`` when that is also empty), which is not writable. A value that is set and
malformed raises :class:`DatasetMountsError`.

``website/backend/src/dataset_mounts.rs`` holds the same parser. Both unit tests read
``dataset_mounts_cases.json`` beside this file. Change the two parsers together.

The parser checks the shape of the list only. It does not open the folders, so a path in
the list is not proof that a path beneath it stays inside the mount.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
from dataclasses import dataclass

LEGACY_MOUNT_NAME = "testdata"
LEGACY_MOUNT_PATH = "/testdata"
_NAME = re.compile(r"[a-z0-9_]{1,32}")
_FIELDS = {"name", "path", "writable"}


class DatasetMountsError(ValueError):
    """``HOOVER4_DATASET_MOUNTS`` is set and malformed."""


@dataclass(frozen=True)
class DatasetMount:
    name: str
    path: str
    writable: bool


def _within(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def parse_dataset_mounts(value: str | None, legacy_path: str | None) -> list[DatasetMount]:
    """Return the mounts that ``value`` names, or the legacy mount when ``value`` is empty."""
    if value is None or not value.strip():
        path = (legacy_path or "").strip() or LEGACY_MOUNT_PATH
        return [DatasetMount(LEGACY_MOUNT_NAME, path, False)]
    try:
        items = json.loads(value)
    except ValueError as exc:
        raise DatasetMountsError(f"HOOVER4_DATASET_MOUNTS is not JSON: {exc}") from exc
    if not isinstance(items, list) or not items:
        raise DatasetMountsError("HOOVER4_DATASET_MOUNTS must be a non-empty JSON list")
    mounts: list[DatasetMount] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict) or set(item) != _FIELDS:
            raise DatasetMountsError(
                f"HOOVER4_DATASET_MOUNTS item {index} must have exactly the fields "
                "name, path and writable")
        name, path, writable = item["name"], item["path"], item["writable"]
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise DatasetMountsError(
                f"HOOVER4_DATASET_MOUNTS item {index}: the name must match [a-z0-9_]{{1,32}}")
        if (not isinstance(path, str) or not path.startswith("/") or path.startswith("//")
                or posixpath.normpath(path) != path):
            raise DatasetMountsError(
                f"HOOVER4_DATASET_MOUNTS item {index}: the path must be absolute and normalized")
        if not isinstance(writable, bool):
            raise DatasetMountsError(
                f"HOOVER4_DATASET_MOUNTS item {index}: writable must be true or false")
        for other in mounts:
            if other.name == name:
                raise DatasetMountsError(f"HOOVER4_DATASET_MOUNTS names {name!r} twice")
            if _within(path, other.path) or _within(other.path, path):
                raise DatasetMountsError(
                    f"HOOVER4_DATASET_MOUNTS paths {other.path!r} and {path!r} overlap")
        mounts.append(DatasetMount(name, path, writable))
    return mounts


def dataset_mounts() -> list[DatasetMount]:
    """Read the dataset mounts from the environment of this process."""
    return parse_dataset_mounts(
        os.environ.get("HOOVER4_DATASET_MOUNTS"), os.environ.get("DATASETS_MOUNT_PATH"))
