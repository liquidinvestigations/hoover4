"""Access-control plumbing for the collection search MCP server.

The agent that calls this server acts *on behalf of a user*, so every tool call has to
be bounded by that user's permitted collections. Two things carry that:

``Authorization: Bearer <MCP_SHARED_SECRET>``
    Proves the caller is the website/agent tier and not something else that found the
    port. Without a correct secret nothing is served at all.

``X-Hoover4-Collections: <comma separated collectionnames>``
    The user's permitted collections, resolved by the website backend (the only
    component that can read `collection_group_permissions`). This server never
    *derives* permissions; it only enforces the list it is handed.

That split is deliberate: putting the ACL in a tool argument would let the model choose
its own permissions, and re-deriving them here would mean a second implementation of the
group/public union that could drift from the website's.
"""

from __future__ import annotations

import hmac
import logging
import os
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

COLLECTIONS_HEADER = "x-hoover4-collections"
USER_HEADER = "x-hoover4-user"

#: Same rule as `validate_collectionname` in main_services and `collectionname_valid` in
#: the website: the name is interpolated into ClickHouse database and Manticore table
#: names, neither of which can be bound as a parameter. Enforced again here because this
#: process builds SQL from it too.
_COLLECTIONNAME_RE = re.compile(r"^[a-z0-9_]{1,48}$")


class AccessDenied(Exception):
    """Raised when a call is unauthenticated or reaches outside its ACL."""


@dataclass(frozen=True)
class CallerAcl:
    """The permissions of whoever is making the current tool call."""

    username: str
    collections: tuple[str, ...]

    def check(self, requested: list[str] | None) -> list[str]:
        """Resolve the collections a tool should actually touch.

        ``None``/empty means "everything I am allowed to see". Anything explicitly
        requested must be inside the ACL — a request for a collection the user cannot
        read is an error, not a silently-dropped filter, so the model gets told it asked
        for something it may not have rather than quietly receiving fewer results.
        """
        if not self.collections:
            raise AccessDenied(
                "this user has access to no collections; nothing can be searched"
            )
        if not requested:
            return list(self.collections)

        allowed = set(self.collections)
        denied = [c for c in requested if c not in allowed]
        if denied:
            raise AccessDenied(
                f"no access to collection(s): {', '.join(sorted(denied))}. "
                f"Available: {', '.join(self.collections)}"
            )
        return list(requested)


def validate_collectionname(name: str) -> str:
    if not _COLLECTIONNAME_RE.match(name):
        raise AccessDenied(f"invalid collectionname: {name!r}")
    return name


def _shared_secret() -> str | None:
    secret = os.getenv("MCP_SHARED_SECRET", "").strip()
    if not secret:
        # deploy.py bind-mounts the shared-secret file (hoover4.ini stores host
        # paths, never values); the env var names the in-container path.
        key_file = os.getenv("MCP_SHARED_SECRET_FILE", "").strip()
        if key_file and os.path.exists(key_file):
            with open(key_file) as fh:
                secret = fh.read().strip()
    return secret or None


def parse_acl(headers: dict[str, str]) -> CallerAcl:
    """Build the caller's ACL from request headers, or raise :class:`AccessDenied`.

    Header lookup is case-insensitive: HTTP header casing is not guaranteed and
    different clients normalise differently.
    """
    lowered = {k.lower(): v for k, v in headers.items()}

    secret = _shared_secret()
    if secret is not None:
        presented = lowered.get("authorization", "")
        expected = f"Bearer {secret}"
        # Constant-time compare: this is a bearer token, so a timing oracle on it is a
        # real (if unglamorous) leak.
        if not hmac.compare_digest(presented, expected):
            raise AccessDenied("missing or invalid bearer token")
    else:
        # Refusing to start would be worse for a prototype than running open on a
        # loopback-bound port, but this must never be silent.
        log.warning(
            "MCP_SHARED_SECRET is not set: serving without caller authentication. "
            "Do not expose this port beyond localhost."
        )

    raw = lowered.get(COLLECTIONS_HEADER)
    if raw is None:
        raise AccessDenied(
            f"missing {COLLECTIONS_HEADER} header; the caller must state the user's "
            "permitted collections"
        )

    collections = tuple(
        validate_collectionname(c.strip()) for c in raw.split(",") if c.strip()
    )
    return CallerAcl(username=lowered.get(USER_HEADER, "unknown"), collections=collections)
