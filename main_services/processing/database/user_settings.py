"""The website settings of a user (`user_settings`). The website is the only writer."""

from __future__ import annotations


def read_user_settings(username: str) -> dict[str, str]:
    """The saved settings of `username` by key. A cleared setting is absent."""
    from database.clickhouse import get_global_client

    with get_global_client() as client:
        result = client.query(
            "SELECT key, value FROM user_settings FINAL "
            "WHERE username = {u:String} AND is_deleted = 0",
            parameters={"u": username},
        )
    return {key: value for key, value in result.result_rows}
