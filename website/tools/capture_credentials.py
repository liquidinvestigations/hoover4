"""Resolve capture-login credentials from environment and login files.

Credential values do not belong in process arguments. Wrappers export
``HOOVER4_TEST_USERNAME`` and ``HOOVER4_TEST_PASSWORD`` into their own
environment, then pass those names to ``docker exec -e NAME`` with no
``=value``. Python entry points read the same names.
"""

from __future__ import annotations

import os
from pathlib import Path


USERNAME_ENV = "HOOVER4_TEST_USERNAME"
PASSWORD_ENV = "HOOVER4_TEST_PASSWORD"
REVISION_ENV = "HOOVER4_CAPTURE_REVISION"
IMAGE_REVIEW_PENDING = 'unreviewed'


class CredentialError(ValueError):
    """An incomplete username and password pair."""


def read_credentials(environ: dict[str, str] | None = None) -> tuple[str, str]:
    """Return the inherited username and password pair, or empty strings."""
    env = os.environ if environ is None else environ
    username = env.get(USERNAME_ENV, "")
    password = env.get(PASSWORD_ENV, "")
    if bool(username) != bool(password):
        raise CredentialError(
            "a username with no password, or a password with no username, "
            "is a validation failure"
        )
    return username, password


def docker_env_name_flags(username: str, password: str, revision: str = "") -> list[str]:
    """Docker ``-e NAME`` flags. Values stay in the caller environment."""
    flags: list[str] = []
    if username or password:
        flags.extend(["-e", USERNAME_ENV, "-e", PASSWORD_ENV])
    if revision:
        flags.extend(["-e", REVISION_ENV])
    return flags


def credentials_in_argv(argv: list[str], username: str, password: str) -> list[str]:
    """Return argv items that equal a supplied credential value."""
    secrets = {value for value in (username, password) if value}
    return [item for item in argv if item in secrets]


def capture_revision(environ: dict[str, str] | None = None) -> str:
    """Revision recorded beside capture evidence, or empty when unset."""
    env = os.environ if environ is None else environ
    return env.get(REVISION_ENV, "")


def image_inventory_entry(
    relative_path: str,
    target: str,
    revision: str,
    workflow: str,
    resolution: str,
    review_state: str = IMAGE_REVIEW_PENDING,
) -> dict[str, str]:
    """One saved image, with review state kept apart from assertion verdicts."""
    return {
        "path": relative_path,
        "target": target,
        "revision": revision,
        "workflow": workflow,
        "resolution": resolution,
        "review_state": review_state,
    }


def collect_image_inventory(
    run_dir: Path,
    target: str,
    revision: str,
) -> list[dict[str, str]]:
    """List every PNG under a run directory. Review state starts as pending."""
    entries = []
    for path in sorted(run_dir.rglob("*.png")):
        relative = path.relative_to(run_dir)
        parts = relative.parts
        resolution = parts[0] if len(parts) > 1 else ""
        entries.append(
            image_inventory_entry(
                relative.as_posix(),
                target,
                revision,
                path.stem,
                resolution,
            )
        )
    return entries
