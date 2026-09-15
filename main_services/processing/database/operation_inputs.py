"""Project stored operation detail onto the inputs a re-run accepts."""

import json

INPUT_KEYS: dict[str, tuple[str, ...]] = {
    "add_dataset": ("dataset_path",),
    "rescan_dataset": ("dataset_path",),
    "change_ocr_languages": ("tesseract_languages", "easyocr_languages"),
    "retry_failed_files": ("task_name", "hash"),
    "refresh_document_locations": ("item_hashes",),
    "export_collection": ("destination",),
    "import_collection": ("source",),
}

REGISTRY_KEYS = ("add_dataset", "rescan_dataset")


class MissingOperationInput(ValueError):
    """A stored operation row lacks an input required for its re-run."""

    def __init__(self, kind: str, key: str):
        self.kind = kind
        self.key = key
        super().__init__(
            f"{kind} needs {key}, and the original row does not hold it"
        )


def registry_dataset_path(collection_dataset: str) -> str:
    """Read the live path for a dataset that remains in the registry."""
    from .clickhouse import get_global_client

    with get_global_client() as client:
        rows = client.query(
            "SELECT dataset_path FROM dataset FINAL "
            "WHERE collection_dataset = {ds:String} AND is_deleted = 0",
            parameters={"ds": collection_dataset},
        ).result_rows
    return str(rows[0][0]) if rows else ""


def _detail_object(raw_detail) -> dict:
    if isinstance(raw_detail, dict):
        return raw_detail
    try:
        detail = json.loads(raw_detail or "{}")
    except (TypeError, ValueError):
        return {}
    return detail if isinstance(detail, dict) else {}


def project_inputs(kind: str, collectionname: str, collection_dataset: str,
                   raw_detail) -> dict:
    """Return the stored inputs that a re-run may pass to its operation workflow."""
    del collectionname
    detail = _detail_object(raw_detail)
    projected = {
        key: detail[key] for key in INPUT_KEYS.get(kind, ()) if key in detail
    }

    if kind in REGISTRY_KEYS:
        path = registry_dataset_path(collection_dataset)
        if not path:
            raise MissingOperationInput(kind, "dataset_path")
        projected["dataset_path"] = path
    elif kind == "change_ocr_languages":
        if not any(str(projected.get(key, "")).strip()
                   for key in INPUT_KEYS[kind]):
            raise MissingOperationInput(kind, "tesseract_languages or easyocr_languages")
    elif kind == "retry_failed_files":
        if not any(str(projected.get(key, "")).strip()
                   for key in INPUT_KEYS[kind]):
            raise MissingOperationInput(kind, "task_name or hash")
    elif kind == "refresh_document_locations":
        hashes = projected.get("item_hashes")
        if not isinstance(hashes, list) or not hashes:
            raise MissingOperationInput(kind, "item_hashes")
    elif kind == "import_collection" and not str(projected.get("source", "")).strip():
        raise MissingOperationInput(kind, "source")

    return projected
