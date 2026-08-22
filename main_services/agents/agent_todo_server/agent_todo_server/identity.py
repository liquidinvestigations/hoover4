"""Who is calling, and which conversation they are calling about.

Same two headers every other ACL-aware server reads, and the same bearer token in
front of them:

``Authorization: Bearer <MCP_SHARED_SECRET>``
    Proves the caller is the agent tier. Without a correct secret nothing is served.

``X-Hoover4-User``
    The username the todo belongs to. It is half the storage key, so it is also the
    permission boundary: a call can only ever reach the list stored under the name the
    website resolved.

``X-Hoover4-Chat-Session``
    The conversation. The other half of the storage key, forwarded by the research
    agent exactly as it is for the browser server's per-chat isolation.

Neither is a tool argument, and that is the point: a session id the model could write
would let it read and rewrite another conversation's plan.
"""

from __future__ import annotations

import hmac
import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)

USER_HEADER = "x-hoover4-user"
SESSION_HEADER = "x-hoover4-chat-session"


class CallerUnknown(Exception):
    """The call is unauthenticated, or names no conversation to keep a plan for."""


@dataclass(frozen=True)
class Caller:
    """Whose todo the in-flight call is about."""

    username: str
    session_id: str


def _shared_secret() -> str | None:
    secret = os.getenv("MCP_SHARED_SECRET", "").strip()
    if not secret:
        # deploy.py bind-mounts the shared-secret file (hoover4.ini stores host paths,
        # never values); the env var names the in-container path.
        key_file = os.getenv("MCP_SHARED_SECRET_FILE", "").strip()
        if key_file and os.path.exists(key_file):
            with open(key_file) as fh:
                secret = fh.read().strip()
    return secret or None


def parse_caller(headers: dict[str, str]) -> Caller:
    """Build the caller from request headers, or raise :class:`CallerUnknown`.

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
            raise CallerUnknown("missing or invalid bearer token")
    else:
        # Refusing to start would be worse for a prototype than running open on a
        # loopback-bound port, but this must never be silent.
        log.warning(
            "MCP_SHARED_SECRET is not set: serving without caller authentication. "
            "Do not expose this port beyond localhost."
        )

    session_id = (lowered.get(SESSION_HEADER) or "").strip()
    if not session_id:
        raise CallerUnknown(
            f"missing {SESSION_HEADER} header; a todo belongs to one conversation and "
            "the caller must say which"
        )
    return Caller(
        username=(lowered.get(USER_HEADER) or "").strip() or "unknown",
        session_id=session_id,
    )
