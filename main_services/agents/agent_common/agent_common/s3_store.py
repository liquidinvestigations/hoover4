"""S3 access for the MCP servers.

Mirrors `main_services/processing/database/s3.py`, same server, same environment
variables. Endpoint and credentials come from the environment on both sides, which is
what lets these containers also be run from the host during development, where a literal
container hostname is unreachable.

**Artifacts go in the system bucket, never in a collection's.** A chat artifact belongs
to a session and not to any collection, and putting it outside every collection's bucket
is what makes "`P0_scan_disk` must never walk derived material" a structural property
instead of a prefix check somebody has to remember. An artifact the ingest walker can see
becomes a `vfs_files` row, gets ingested, gets captured again, and produces another
artifact, and that loop does not end. `verify-stack.sh` asserts no `blobs` row references
the prefix.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

#: The bucket for everything that belongs to no collection.
BUCKET_NAME = os.getenv("S3_SYSTEM_BUCKET", "hoover4-system")

#: Everything an agent writes lives under here. See the module docstring.
DERIVED_PREFIX = "derived/chat-artifacts"


def _endpoint() -> str:
    """`host:port` for the S3 API, without a scheme.

    Accepts either spelling in `S3_ENDPOINT`, because the website's copy of the variable
    carries `http://` and the others do not.
    """
    raw = os.getenv("S3_ENDPOINT") or "garage:3900"
    return raw.replace("https://", "").replace("http://", "").rstrip("/")


def _secure() -> bool:
    return (os.getenv("S3_ENDPOINT") or "").startswith("https://")


def get_s3_client():
    """A configured S3 client. Imported lazily so a server that never writes an
    artifact does not need the dependency resolved at import time."""
    from minio import Minio

    return Minio(
        _endpoint(),
        access_key=os.getenv("S3_ACCESS_KEY", "hoover4-blobs-rw"),
        secret_key=os.getenv("S3_SECRET_KEY", "hoover4-garage-blob-secret-key-0"),
        secure=_secure(),
    )


def ensure_bucket(client=None, bucket: str = BUCKET_NAME) -> None:
    """Create the bucket if it is missing, tolerating a concurrent creator."""
    from minio.error import S3Error

    client = client or get_s3_client()
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
    generate, but only one of those is trustworthy. A header carrying `../../blobs`
    would otherwise write outside the derived prefix, which is exactly the boundary this
    module exists to hold.
    """
    cleaned = "".join(c for c in (component or "") if c.isalnum() or c in "-_.")
    cleaned = cleaned.lstrip(".") or "unknown"
    return cleaned[:128]


def put_bytes(key: str, data: bytes, content_type: str, client=None) -> int:
    """Store `data` at `key` and return its length."""
    import io

    client = client or get_s3_client()
    ensure_bucket(client)
    client.put_object(
        BUCKET_NAME,
        key,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return len(data)
