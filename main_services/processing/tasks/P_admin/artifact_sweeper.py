"""Retention for chat artifacts: delete the MinIO objects, then the ClickHouse rows.

**A ClickHouse TTL does not delete MinIO objects.** That is the whole reason this exists.
If `chat_artifacts` simply expired its rows, the bytes would stay in the bucket with
nothing left pointing at them and no way to find them again except a full prefix walk.

So the order is fixed and is the opposite of what feels natural:

1. find rows that are soft-deleted (the chat was deleted) or older than the TTL;
2. delete their objects;
3. **only then** hard-delete the rows.

A crash between 2 and 3 leaves a row pointing at a missing object, which renders as a
broken artifact — recoverable, and the next sweep finishes the job. A crash the other way
round leaks bytes permanently.

Step 4 catches what a crash *between the object write and the row insert* leaves behind:
list the `derived/chat-artifacts/` prefix and delete any object with no row at all. The
writers store bytes before the row precisely so that this is the failure they leave.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

GLOBAL_DB = "Hoover4_Processing"

#: Default retention. Overridden by the `chat_artifact_ttl_days` server_setting, so an
#: admin can change it without a redeploy.
DEFAULT_TTL_DAYS = int(os.getenv("CHAT_ARTIFACT_TTL_DAYS", "30"))

TTL_SETTING_KEY = "chat_artifact_ttl_days"

#: An object younger than this is never treated as an orphan. A capture in flight has its
#: bytes written seconds before its row, and a sweeper racing that window would delete a
#: live artifact.
ORPHAN_GRACE_SECONDS = int(os.getenv("CHAT_ARTIFACT_ORPHAN_GRACE_SECONDS", "3600"))

DERIVED_PREFIX = "derived/chat-artifacts/"
BUCKET = "hoover4-blobs"


@dataclass
class SweepResult:
    expired_rows: int = 0
    deleted_objects: int = 0
    deleted_rows: int = 0
    orphan_objects: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.expired_rows} expired/deleted artifact rows, "
            f"{self.deleted_objects} objects removed, {self.deleted_rows} rows dropped, "
            f"{self.orphan_objects} orphaned objects collected"
            + (f", {len(self.errors)} error(s)" if self.errors else "")
        )


def ttl_days() -> int:
    """Retention window, from `server_settings` with the env default behind it."""
    from database.clickhouse import get_global_client

    try:
        with get_global_client() as client:
            rows = client.query(
                "SELECT argMax(value, updated_at) FROM server_settings WHERE key = %(k)s",
                parameters={"k": TTL_SETTING_KEY},
            ).result_rows
        if rows and rows[0][0]:
            return max(1, int(rows[0][0]))
    except Exception as exc:  # noqa: BLE001 - a missing setting is normal, not an error
        log.debug("could not read %s: %s", TTL_SETTING_KEY, exc)
    return DEFAULT_TTL_DAYS


def sweep() -> SweepResult:
    """One retention pass. Never raises: a failed sweep must be visible, not fatal."""
    from database.clickhouse import get_global_client
    from database.minio import get_minio_client

    result = SweepResult()
    days = ttl_days()

    with get_global_client() as client:
        # 1. Rows to remove: tombstoned by a session delete, or past the TTL.
        rows = client.query(
            """
            SELECT artifact_id, session_id, username, thumb_key, body_key
            FROM chat_artifacts FINAL
            WHERE is_deleted = 1 OR created_at < now() - INTERVAL %(days)s DAY
            LIMIT 10000
            """,
            parameters={"days": days},
        ).result_rows
        result.expired_rows = len(rows)

        minio = get_minio_client()
        result = _sweep_rows(client, minio, rows, result)

    log.info("[artifact-sweeper] %s", result.summary())
    return result


def _sweep_rows(client, minio, rows, result: SweepResult) -> SweepResult:
    doomed_ids: list[str] = []
    doomed = {row[0] for row in rows}

    # **A body_key can be shared.** The capture path reuses the previous snapshot when the
    # page has not changed between two actions, so two artifacts can point at one object.
    # Deleting it because the older one expired would silently break the newer one, which
    # would then render as an artifact whose page will not load — with nothing saying why.
    # So a key any *surviving* row still references is left alone.
    still_referenced = {
        key
        for artifact_id, _thumb, _body in _all_keys(client)
        if artifact_id not in doomed
        for key in (_thumb, _body)
        if key
    }

    for artifact_id, _session_id, _username, thumb_key, body_key in rows:
        ok = True
        for key in (k for k in (thumb_key, body_key) if k):
            if key in still_referenced:
                log.debug("[artifact-sweeper] keeping %s, a live artifact still uses it", key)
                continue
            try:
                minio.remove_object(BUCKET, key)
                result.deleted_objects += 1
            except Exception as exc:  # noqa: BLE001
                message = f"could not delete {key}: {exc}"
                log.warning("[artifact-sweeper] %s", message)
                result.errors.append(message)
                ok = False
        if ok:
            doomed_ids.append(artifact_id)

    # 3. Only rows whose objects are gone. A row kept because its object would not delete
    #    is the record of the leak, and the next sweep retries it.
    if doomed_ids:
        client.command(
            "DELETE FROM chat_artifacts WHERE artifact_id IN %(ids)s",
            parameters={"ids": tuple(doomed_ids)},
        )
        result.deleted_rows = len(doomed_ids)

    # 4. Orphans: objects under the prefix with no row at all.
    try:
        live_keys = _live_object_keys(client)
        result.orphan_objects = _collect_orphans(minio, live_keys)
    except Exception as exc:  # noqa: BLE001
        message = f"orphan scan failed: {exc}"
        log.warning("[artifact-sweeper] %s", message)
        result.errors.append(message)

    return result


def _all_keys(client) -> list[tuple[str, str, str]]:
    return [
        (row[0], row[1], row[2])
        for row in client.query(
            "SELECT artifact_id, thumb_key, body_key FROM chat_artifacts FINAL"
        ).result_rows
    ]


def _live_object_keys(client) -> set[str]:
    return {key for _id, thumb, body in _all_keys(client) for key in (thumb, body) if key}


def _collect_orphans(minio, live_keys: set[str]) -> int:
    """Delete objects under the derived prefix that no row references."""
    import datetime

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=ORPHAN_GRACE_SECONDS
    )
    removed = 0
    for obj in minio.list_objects(BUCKET, prefix=DERIVED_PREFIX, recursive=True):
        if obj.object_name in live_keys:
            continue
        modified = getattr(obj, "last_modified", None)
        if modified is not None and modified > cutoff:
            # Written in the last hour: this is very likely a capture whose row has not
            # landed yet, not garbage.
            continue
        try:
            minio.remove_object(BUCKET, obj.object_name)
            removed += 1
            log.info("[artifact-sweeper] removed orphaned object %s", obj.object_name)
        except Exception as exc:  # noqa: BLE001
            log.warning("[artifact-sweeper] could not remove orphan %s: %s", obj.object_name, exc)
    return removed


def sweep_json() -> str:
    """`sweep()` as a JSON string, for the Temporal activity's return value."""
    result = sweep()
    return json.dumps(
        {
            "expired_rows": result.expired_rows,
            "deleted_objects": result.deleted_objects,
            "deleted_rows": result.deleted_rows,
            "orphan_objects": result.orphan_objects,
            "errors": result.errors[:20],
            "ttl_days": ttl_days(),
        }
    )
