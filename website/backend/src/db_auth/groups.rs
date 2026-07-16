//! User groups and membership CRUD.

use std::collections::HashSet;

use crate::db_auth::{insert_row, now};
use crate::db_utils::clickhouse_utils::get_clickhouse_client;

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct GroupRow {
    pub groupname: String,
    pub fullname: String,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub created_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub updated_at: time::OffsetDateTime,
    pub is_deleted: u8,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct MembershipRow {
    pub username: String,
    pub groupname: String,
    pub is_group_admin: bool,
    pub origin: String,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub created_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub updated_at: time::OffsetDateTime,
    pub is_deleted: u8,
}

pub async fn list_groups() -> anyhow::Result<Vec<GroupRow>> {
    let client = get_clickhouse_client();
    client
        .query("SELECT groupname, fullname, created_at, updated_at, is_deleted FROM user_groups FINAL WHERE is_deleted = 0 ORDER BY groupname")
        .fetch_all::<GroupRow>()
        .await
        .map_err(Into::into)
}

pub async fn get_group(groupname: &str) -> anyhow::Result<Option<GroupRow>> {
    let client = get_clickhouse_client();
    let mut rows = client
        .query("SELECT groupname, fullname, created_at, updated_at, is_deleted FROM user_groups FINAL WHERE groupname = ? AND is_deleted = 0")
        .bind(groupname)
        .fetch_all::<GroupRow>()
        .await?;
    Ok(rows.pop())
}

pub async fn upsert_group(mut row: GroupRow) -> anyhow::Result<()> {
    let existing = get_group(&row.groupname).await?;
    if let Some(existing) = existing {
        row.created_at = existing.created_at;
    } else {
        row.created_at = now();
    }
    row.updated_at = now();
    row.is_deleted = 0;
    insert_row("user_groups", &row).await
}

pub async fn soft_delete_group(groupname: &str) -> anyhow::Result<()> {
    let Some(mut row) = get_group(groupname).await? else {
        return Ok(());
    };
    row.updated_at = now();
    row.is_deleted = 1;
    insert_row("user_groups", &row).await
}

pub async fn list_memberships_for_user(username: &str) -> anyhow::Result<Vec<MembershipRow>> {
    let client = get_clickhouse_client();
    client
        .query("SELECT username, groupname, is_group_admin, origin, created_at, updated_at, is_deleted FROM user_group_membership FINAL WHERE username = ? AND is_deleted = 0 ORDER BY groupname")
        .bind(username)
        .fetch_all::<MembershipRow>()
        .await
        .map_err(Into::into)
}

pub async fn list_memberships_for_group(groupname: &str) -> anyhow::Result<Vec<MembershipRow>> {
    let client = get_clickhouse_client();
    client
        .query("SELECT username, groupname, is_group_admin, origin, created_at, updated_at, is_deleted FROM user_group_membership FINAL WHERE groupname = ? AND is_deleted = 0 ORDER BY username")
        .bind(groupname)
        .fetch_all::<MembershipRow>()
        .await
        .map_err(Into::into)
}

pub async fn get_membership(username: &str, groupname: &str) -> anyhow::Result<Option<MembershipRow>> {
    let client = get_clickhouse_client();
    let mut rows = client
        .query("SELECT username, groupname, is_group_admin, origin, created_at, updated_at, is_deleted FROM user_group_membership FINAL WHERE username = ? AND groupname = ? AND is_deleted = 0")
        .bind(username)
        .bind(groupname)
        .fetch_all::<MembershipRow>()
        .await?;
    Ok(rows.pop())
}

pub async fn upsert_membership(mut row: MembershipRow) -> anyhow::Result<()> {
    let existing = get_membership(&row.username, &row.groupname).await?;
    if let Some(existing) = existing {
        row.created_at = existing.created_at;
    } else {
        row.created_at = now();
    }
    row.updated_at = now();
    row.is_deleted = 0;
    insert_row("user_group_membership", &row).await
}

pub async fn soft_delete_membership(username: &str, groupname: &str) -> anyhow::Result<()> {
    let Some(mut row) = get_membership(username, groupname).await? else {
        return Ok(());
    };
    row.updated_at = now();
    row.is_deleted = 1;
    insert_row("user_group_membership", &row).await
}

pub async fn sync_header_memberships(username: &str, groups: &[String]) -> anyhow::Result<()> {
    let desired: HashSet<String> = groups.iter().cloned().collect();
    let existing = list_memberships_for_user(username).await?;
    let header_rows: Vec<_> = existing
        .into_iter()
        .filter(|m| m.origin == "header")
        .collect();

    for row in header_rows {
        if !desired.contains(&row.groupname) {
            soft_delete_membership(username, &row.groupname).await?;
        }
    }

    for groupname in groups {
        if get_membership(username, groupname).await?.is_none() {
            upsert_membership(MembershipRow {
                username: username.to_string(),
                groupname: groupname.clone(),
                is_group_admin: false,
                origin: "header".to_string(),
                created_at: now(),
                updated_at: now(),
                is_deleted: 0,
            })
            .await?;
        }
    }
    Ok(())
}
