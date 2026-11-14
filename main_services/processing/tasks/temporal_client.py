"""The Temporal connection of every Hoover process: the address, the namespace and the key.

Compose runs one Temporal for one installation, and every process uses its namespace
``default`` without a key. A k3s site runs one Temporal for all of its zones. Each zone
has its own namespace there, and the zone key permits only that namespace. The
installation gives both in the environment:

- ``TEMPORAL_NAMESPACE``: the namespace of the installation. Empty or absent means ``default``.
- ``TEMPORAL_API_KEY``: the key that the client sends as ``Authorization: Bearer <key>``.
  Empty or absent means no key.

Every client of this package connects through :func:`connect`, every request that
names a namespace uses :func:`namespace`, and every request to the HTTP API of Temporal
sends :func:`http_headers`.
"""

import os

TEMPORAL_ADDRESS = "temporal:7233"


def namespace() -> str:
    """The Temporal namespace of the installation."""
    return os.environ.get("TEMPORAL_NAMESPACE", "").strip() or "default"


def api_key() -> str | None:
    """The key of the installation for Temporal, or None."""
    return os.environ.get("TEMPORAL_API_KEY", "").strip() or None


def http_headers() -> dict:
    """The headers of a request to the HTTP API of Temporal: the key, when the installation has one."""
    key = api_key()
    return {"Authorization": f"Bearer {key}"} if key else {}


async def connect(address: str = TEMPORAL_ADDRESS, **options):
    """Connect to Temporal with the namespace and the key of the installation."""
    from temporalio.client import Client

    return await Client.connect(address, namespace=namespace(), api_key=api_key(), **options)
