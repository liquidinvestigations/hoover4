import logging
log = logging.getLogger(__name__)
from minio import Minio
from minio.error import S3Error

# MinIO connection settings (server runs on localhost)
MINIO_ENDPOINT_HOSTPORT = "minio-s3:9000"
MINIO_ACCESS_KEY = "hoover4"
MINIO_SECRET_KEY = "hoover4-secret"

# Default bucket used by the application
BUCKET_NAME = "hoover4-blobs"


def get_minio_client() -> Minio:
    """Return a MinIO client configured for the local server."""
    return Minio(
        MINIO_ENDPOINT_HOSTPORT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )


def ensure_bucket(bucket_name: str) -> None:
    """Create the bucket if it does not already exist."""
    client = get_minio_client()
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
    "get_minio_client",
    "ensure_bucket",
]


