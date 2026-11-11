"""S3 client helpers for blob storage access.

The store is Garage; the `minio` pip package is a generic S3 client and is what talks to
it. Endpoint and credentials come from the environment so that a deployment can move the
store without a code change. The values here are only the compose defaults restated.

**There is a bucket per collection and one system bucket, never a single shared one.**
The key the application holds carries `--create-bucket`, so a collection's bucket is
created at runtime when the collection is. Every caller therefore has to say which bucket
it means, which is the point: a call that could reach any collection's objects is a call
that can reach the wrong one.
"""

import logging
import os

log = logging.getLogger(__name__)
from minio import Minio
from minio.error import S3Error

from database import storage_identity

S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "garage:3900")
# The key and the bucket names come from database/storage_identity.py.
S3_ACCESS_KEY = storage_identity.setting("s3_access_key")
S3_SECRET_KEY = storage_identity.setting("s3_secret_key")

#: Everything that is not a collection's data: chat artifacts, and anything else global.
#:
#: Its own bucket rather than a prefix inside a collection's, so that "P0 must never walk
#: derived material" stops being a prefix check somebody has to remember and becomes a
#: structural property. A scan of a collection's bucket cannot reach it at all.
SYSTEM_BUCKET = storage_identity.setting("system_bucket")

#: Prefix of a collection's own bucket. Per-collection *stores* are impossible. Garage
#: has one shared metadata database and globally content-addressed data blocks, but
#: per-collection buckets are not, and they are what makes a collection's objects
#: enumerable without prefix filtering and deletable in one call. Block dedup is global,
#: so the split costs no storage.
COLLECTION_BUCKET_PREFIX = storage_identity.setting("collection_bucket_prefix")


def collection_bucket(collectionname: str) -> str:
    """The bucket holding one collection's ingested blobs and derived objects.

    An S3 bucket name allows `-` and refuses `_`, and a collection name allows `_` and
    refuses `-`. Each `_` therefore becomes `-`. The mapping is one to one, so two
    collections never share a bucket. The website builds the same name, and both test
    suites read `tasks/collection_bucket_cases.json`.
    """
    from database.clickhouse import validate_collectionname
    validate_collectionname(collectionname)
    return f"{COLLECTION_BUCKET_PREFIX}{collectionname.replace('_', '-')}"


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


def ensure_collection_storage(collectionname: str) -> str:
    """Provision both halves of a collection's storage and return its database name.

    A collection owns a ClickHouse database and a bucket, and every path that can bring a
    collection into existence goes through here so the two cannot drift apart. One that
    creates only the database ingests fine until the first writer that does not create
    buckets of its own reaches for it: the scan stage makes the bucket before its first
    upload, but a corpus small enough to keep every blob inline in ClickHouse never
    uploads, so the first thing to touch the bucket is the searchable-PDF builder, which
    answers 500 and parks the plan behind an activity that can never succeed.
    """
    from database.clickhouse import migrate_collection

    db_name = migrate_collection(collectionname)
    ensure_bucket(collection_bucket(collectionname))
    return db_name


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
    "COLLECTION_BUCKET_PREFIX",
    "SYSTEM_BUCKET",
    "collection_bucket",
    "ensure_bucket",
    "ensure_collection_storage",
    "get_s3_client",
]
