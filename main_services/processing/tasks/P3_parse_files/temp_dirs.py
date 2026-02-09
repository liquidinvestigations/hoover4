"""Temporary directory helpers for file parsing jobs."""

import os
import tempfile


def make_temp_dir(collection_dataset: str, kind: str, file_hash: str) -> str:
    """Create and return a temp directory path namespaced by dataset.

    The directory name format is: hoover4/<dataset>/<kind>_<hash>
    Example: .../tmp/hoover4/mydataset/pdf_abcd1234
    """
    base_tmp = tempfile.gettempdir()
    root = os.path.join(base_tmp, "hoover4", collection_dataset)
    out_dir = os.path.join(root, f"{kind}_{file_hash}")
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


