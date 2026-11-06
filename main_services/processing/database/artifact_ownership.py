"""Repair browser artifacts only when durable run ownership proves the actual chat."""
from datetime import timedelta

from database.clickhouse import insert_durable


def repair_browser_ownership(*, apply: bool = False, limit: int = 100, after: tuple[str, str, str] = ("", "", "")) -> dict:
    """Inspect one bounded page. Preserve artifact IDs and object keys during replacement."""
    if not 1 <= limit <= 1000:
        raise ValueError("The repair limit must be between 1 and 1000.")
    from database.clickhouse import get_global_client
    result = {"proven": 0, "repaired": 0, "unproven": 0, "next": None, "conflicted": 0}
    with get_global_client() as client:
        rows = client.query(
            "SELECT * FROM chat_artifacts FINAL WHERE is_deleted=0 AND kind='page_capture' "
            "AND match(session_id, '^[0-9a-fA-F-]{36}$') "
            "AND (username,session_id,artifact_id) > {after:Tuple(String,String,String)} "
            "ORDER BY username,session_id,artifact_id LIMIT {limit:UInt32}",
            parameters={"limit": limit, "after": after})
        for values in rows.result_rows:
            row = dict(zip(rows.column_names, values))
            old_session = row["session_id"]
            result["next"] = [row["username"], old_session, row["artifact_id"]]
            mappings = client.query(
                "SELECT DISTINCT session_id FROM agent_runs FINAL WHERE username={u:String} "
                "AND toString(run_id)={run:String}",
                parameters={"u": row["username"], "run": old_session}).result_rows
            if len(mappings) != 1 or mappings[0][0] == old_session:
                result["unproven"] += 1
                continue
            target = mappings[0][0]
            sessions = client.query(
                "SELECT DISTINCT is_deleted FROM chat_sessions WHERE username={u:String} AND session_id={s:String} "
                "AND updated_at=(SELECT max(updated_at) FROM chat_sessions WHERE username={u:String} AND session_id={s:String})",
                parameters={"u": row["username"], "s": target}).result_rows
            if len(sessions) != 1:
                result["unproven"] += 1
                continue
            existing = client.query(
                "SELECT * FROM chat_artifacts WHERE username={u:String} "
                "AND session_id={s:String} AND artifact_id={a:String} ORDER BY updated_at DESC LIMIT 1",
                parameters={"u": row["username"], "s": target, "a": row["artifact_id"]})
            if existing.result_rows:
                target_row = dict(zip(existing.column_names, existing.result_rows[0]))
                if (target_row["body_key"], target_row["thumb_key"]) != (row["body_key"], row["thumb_key"]):
                    result["conflicted"] += 1
                    result["unproven"] += 1
                    continue
                row = target_row
            result["proven"] += 1
            if not apply:
                continue
            if not existing.result_rows:
                row["session_id"] = target
                row["is_deleted"] = int(sessions[0][0])
                row["updated_at"] += timedelta(seconds=1)
                insert_durable(client, "chat_artifacts", [list(row.values())], column_names=list(row))
            deleted = client.query(
                "SELECT count() FROM chat_sessions WHERE username={u:String} AND session_id={s:String} AND is_deleted=1",
                parameters={"u": row["username"], "s": target}).result_rows[0][0]
            if deleted and not row["is_deleted"]:
                row["is_deleted"] = 1
                row["updated_at"] += timedelta(seconds=1)
                insert_durable(client, "chat_artifacts", [list(row.values())], column_names=list(row))
            # The corrected row is durable before the old key is physically removed.
            client.command(
                "DELETE FROM chat_artifacts WHERE username={u:String} AND session_id={s:String} "
                "AND artifact_id={a:String} SETTINGS mutations_sync=2",
                parameters={"u": row["username"], "s": old_session, "a": row["artifact_id"]})
            result["repaired"] += 1
    return result
