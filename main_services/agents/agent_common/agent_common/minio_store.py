"""MinIO access for the MCP servers.

Mirrors `main_services/processing/database/minio.py` — same bucket, same server — but
reads endpoint and credentials from the environment instead of hardcoding them. The
processing copy predates the deploy.py-rendered env and hardcodes `minio-s3:9000`; do not
copy that habit here, because these containers are also run from the host during
development and a literal hostname is unreachable there.

Everything these servers write goes under :data:`DERIVED_PREFIX`. That prefix is the one
part of the bucket `P0_scan_disk` must never walk: an artifact the ingest walker can see
becomes a `vfs_files` row, gets ingested, gets captured again, and produces another
artifact — forever. `verify-stack.sh` asserts no `blobs` row references it.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

#: Same bucket the pipeline's blobs live in. One bucket keeps the retention and backup
#: story single; the prefix below is what separates derived bytes from ingested ones.
BUCKET_NAME = os.getenv("MINIO_BUCKET", "hoover4-blobs")

#: Everything an agent writes lives under here. See the module docstring.
DERIVED_PREFIX = "derived/chat-artifacts"


def _endpoint() -> str:
    """`host:port` for the MinIO API, without a scheme.

    Accepts either form in `S3_ENDPOINT` (the website's variable carries `http://…`)
    because both spellings are already in use in this stack.
    """
    raw = os.getenv("MINIO_ENDPOINT") or os.getenv("S3_ENDPOINT") or "minio-s3:9000"
    return raw.replace("https://", "").replace("http://", "").rstrip("/")


def _secure() -> bool:
    return (os.getenv("S3_ENDPOINT") or "").startswith("https://")


def get_minio_client():
    """A configured MinIO client. Imported lazily so a server that never writes an
    artifact does not need the dependency resolved at import time."""
    from minio import Minio

    return Minio(
        _endpoint(),
        access_key=os.getenv("MINIO_ACCESS_KEY", "hoover4"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "hoover4-secret"),
        secure=_secure(),
    )


def ensure_bucket(client=None, bucket: str = BUCKET_NAME) -> None:
    """Create the bucket if it is missing, tolerating a concurrent creator."""
    from minio.error import S3Error

    client = client or get_minio_client()
    try:
        if client.bucket_exists(bucket):
            return
        log.info("creating s3 bucket %s", bucket)
        client.make_bucket(bucket)
    except S3Error as exc:
        if exc.code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
            raise


def artifact_key(session_id: str, artifact_id: str, filename: str) -> str:
    """Object key for one artifact file.

    `derived/chat-artifacts/<session>/<id>/<filename>`. The session is in the path so the
    sweeper can drop a deleted chat's objects with one prefix listing, and so a human
    poking at the bucket can tell whose bytes these are.
    """
    return f"{DERIVED_PREFIX}/{_safe(session_id)}/{_safe(artifact_id)}/{_safe(filename)}"


def session_prefix(session_id: str) -> str:
    return f"{DERIVED_PREFIX}/{_safe(session_id)}/"


def _safe(component: str) -> str:
    """Keep a path component to characters that cannot escape the prefix.

    The session id comes from an HTTP header and the artifact id from a UUID we
    generate, but only one of those is trustworthy — a header carrying `../../blobs`
    would otherwise write outside the derived prefix, which is exactly the boundary this
    module exists to hold.
    """
    cleaned = "".join(c for c in (component or "") if c.isalnum() or c in "-_.")
    cleaned = cleaned.lstrip(".") or "unknown"
    return cleaned[:128]


def put_bytes(key: str, data: bytes, content_type: str, client=None) -> int:
    """Store `data` at `key` and return its length."""
    import io

    client = client or get_minio_client()
    ensure_bucket(client)
    client.put_object(
        BUCKET_NAME,
        key,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return len(data)
