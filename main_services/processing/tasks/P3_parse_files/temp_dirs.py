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




#: The `ApplicationError.type` of a parse or detector input path that does not exist.
TEMP_COPY_MISSING = "TempCopyMissing"


def require_input_file(file_path: str) -> None:
    """Raise a non-retryable error when the input file of an activity does not exist.

    The P2 download step writes a temporary copy of each plan file, and the P3 activities
    read that copy. When the copy is missing, every retry reads the same missing path, and
    a detector that runs on it reports its own error text as a file type. This check stops
    the activity at its first attempt, with an error that names the path.
    """
    if os.path.exists(file_path):
        return
    from temporalio.exceptions import ApplicationError

    raise ApplicationError(
        f"input file {file_path} does not exist: the temporary copy of this file is missing",
        type=TEMP_COPY_MISSING,
        non_retryable=True,
    )


def has_application_error_type(error: BaseException | None, error_type: str) -> bool:
    """Whether an exception, or a cause in its chain, is an `ApplicationError` of `error_type`."""
    current = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        if getattr(current, "type", None) == error_type:
            return True
        seen.add(id(current))
        temporal_cause = getattr(current, "cause", None)
        current = temporal_cause if isinstance(temporal_cause, BaseException) else current.__cause__
    return False


def is_temp_copy_missing(error: BaseException | None) -> bool:
    """Whether an exception, or a cause in its chain, is a `TEMP_COPY_MISSING` error."""
    return has_application_error_type(error, TEMP_COPY_MISSING)
