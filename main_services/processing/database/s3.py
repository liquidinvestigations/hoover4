"""S3 client helpers for blob storage access.

The store is Garage; the `minio` pip package is a generic S3 client and is what talks to
it. Endpoint and credentials come from the environment so that a deployment can move the
store without a code change — the values here are only the compose defaults restated.
"""

import logging
import os

log = logging.getLogger(__name__)
from minio import Minio
from minio.error import S3Error

S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "garage:3900")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "hoover4-blobs-rw")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "hoover4-garage-blob-secret-key-0")

# Default bucket used by the application
BUCKET_NAME = os.environ.get("S3_BUCKET", "hoover4-blobs")


def _hostport(endpoint: str) -> str:
    """`minio.Minio` wants host:port and rejects a scheme; callers write either."""
    return endpoint.split("://", 1)[-1].rstrip("/")


def get_s3_client() -> Minio:
    """Return an S3 client for the configured blob store."""
    return Minio(
        _hostport(S3_ENDPOINT),
        access_key=S3_ACCESS_KEY,
        secret_key=S3_SECRET_KEY,
        secure=S3_ENDPOINT.startswith("https://"),
    )


def ensure_bucket(bucket_name: str) -> None:
    """Create the bucket if it does not already exist."""
    client = get_s3_client()
    try:
        if client.bucket_exists(bucket_name):
            return
        log.info(f"Creating s3 bucket {bucket_name}")
        client.make_bucket(bucket_name)
    except S3Error as exc:
        # If another process created it in the meantime, ignore AlreadyOwnedByYou/BucketAlreadyOwnedByYou
        if exc.code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
            raise


__all__ = [
    "BUCKET_NAME",
    "get_s3_client",
    "ensure_bucket",
]
