//! User groups and membership CRUD.

use std::collections::HashSet;
use std::sync::LazyLock;

use crate::db_auth::{insert_row, lock_key, now, KeyedLocks};
use crate::db_utils::clickhouse_utils::get_global_client;

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

/// One stored membership of a user in a group.
///
/// The website is the only writer. Every write goes through the functions below, which hold
/// the lock of the user, read the stored row, and write the complete row with a version
/// above every stored version of it. A change of one flag therefore keeps the other flag.
#[derive(Debug, Clone, PartialEq, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct MembershipRow {
    pub username: String,
    pub groupname: String,
    pub is_group_admin: bool,
    pub origin: String,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub created_at: time::OffsetDateTime,
    /// The ReplacingMergeTree version, in whole seconds.
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub updated_at: time::OffsetDateTime,
    pub is_deleted: u8,
    /// 1 when the member may upload into the upload dataset of each collection that the
    /// group can read (`00049_membership_uploader.sql`).
    pub is_uploader: u8,
}

impl MembershipRow {
    /// A new live membership. The uploader flag starts clear.
    pub fn new(username: &str, groupname: &str, origin: &str, is_group_admin: bool) -> Self {
        let now = now();
        MembershipRow {
            username: username.to_string(),
            groupname: groupname.to_string(),
            is_group_admin,
            origin: origin.to_string(),
            created_at: now,
            updated_at: now,
            is_deleted: 0,
            is_uploader: 0,
        }
    }
}

/// The column list of every membership read. `clickhouse::Row` binds by column name.
const MEMBERSHIP_SELECT: &str = "SELECT username, groupname, is_group_admin, origin, \
     created_at, updated_at, is_deleted, is_uploader FROM user_group_membership FINAL";

/// The membership write locks, keyed by username. The header sync writes the rows of one
/// user, so one key covers it.
static MEMBERSHIP_LOCKS: KeyedLocks = LazyLock::new(Default::default);

pub async fn list_groups() -> anyhow::Result<Vec<GroupRow>> {
    let client = get_global_client();
    client
        .query("SELECT groupname, fullname, created_at, updated_at, is_deleted FROM user_groups FINAL WHERE is_deleted = 0 ORDER BY groupname")
        .fetch_all::<GroupRow>()
        .await
        .map_err(Into::into)
}

pub async fn get_group(groupname: &str) -> anyhow::Result<Option<GroupRow>> {
    let client = get_global_client();
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
    let client = get_global_client();
    client
        .query(&format!("{MEMBERSHIP_SELECT} WHERE username = ? AND is_deleted = 0 ORDER BY groupname"))
        .bind(username)
        .fetch_all::<MembershipRow>()
        .await
        .map_err(Into::into)
}

pub async fn list_memberships_for_group(groupname: &str) -> anyhow::Result<Vec<MembershipRow>> {
    let client = get_global_client();
    client
        .query(&format!("{MEMBERSHIP_SELECT} WHERE groupname = ? AND is_deleted = 0 ORDER BY username"))
        .bind(groupname)
        .fetch_all::<MembershipRow>()
        .await
        .map_err(Into::into)
}

pub async fn get_membership(username: &str, groupname: &str) -> anyhow::Result<Option<MembershipRow>> {
    let client = get_global_client();
    let mut rows = client
        .query(&format!("{MEMBERSHIP_SELECT} WHERE username = ? AND groupname = ? AND is_deleted = 0"))
        .bind(username)
        .bind(groupname)
        .fetch_all::<MembershipRow>()
        .await?;
    Ok(rows.pop())
}

/// The highest stored version of a membership, tombstones included. The Unix epoch when
/// no row exists.
async fn stored_version(username: &str, groupname: &str) -> anyhow::Result<time::OffsetDateTime> {
    #[derive(clickhouse::Row, serde::Deserialize)]
    struct Version {
        #[serde(with = "clickhouse::serde::time::datetime")]
        version: time::OffsetDateTime,
    }
    let client = get_global_client();
    let row = client
        .query("SELECT max(updated_at) AS version FROM user_group_membership WHERE username = ? AND groupname = ?")
        .bind(username)
        .bind(groupname)
        .fetch_one::<Version>()
        .await?;
    Ok(row.version)
}

/// The version of a new membership row: the current whole second, and above the stored
/// version. Two writes in one second therefore have distinct versions, and the later write
/// is the current row.
fn next_membership_version(
    now: time::OffsetDateTime,
    stored: time::OffsetDateTime,
) -> time::OffsetDateTime {
    let now = now.replace_nanosecond(0).unwrap_or(now);
    if now > stored {
        now
    } else {
        stored + time::Duration::seconds(1)
    }
}

/// Write one membership row. The caller holds the lock of the user.
async fn write_locked(mut row: MembershipRow) -> anyhow::Result<()> {
    let stored = stored_version(&row.username, &row.groupname).await?;
    row.updated_at = next_membership_version(now(), stored);
    insert_row("user_group_membership", &row).await
}

/// The row that adding a member writes, or `None` when the live membership exists. A
/// repeated add keeps the stored row, with its origin and both flags.
fn membership_to_add(
    existing: Option<&MembershipRow>,
    username: &str,
    groupname: &str,
    origin: &str,
    is_group_admin: bool,
) -> Option<MembershipRow> {
    if existing.is_some() {
        return None;
    }
    Some(MembershipRow::new(username, groupname, origin, is_group_admin))
}

/// Add a user to a group. A live membership stays as it is stored. Returns the current row.
pub async fn add_membership(
    username: &str,
    groupname: &str,
    origin: &str,
    is_group_admin: bool,
) -> anyhow::Result<MembershipRow> {
    let _guard = lock_key(&MEMBERSHIP_LOCKS, username).await;
    let existing = get_membership(username, groupname).await?;
    match membership_to_add(existing.as_ref(), username, groupname, origin, is_group_admin) {
        Some(row) => {
            write_locked(row.clone()).await?;
            Ok(row)
        }
        None => Ok(existing.expect("membership_to_add returns None only for a stored row")),
    }
}

/// Change a live membership: read the stored row, apply `change`, and write the complete
/// row. Returns `None` when the membership does not exist.
pub async fn update_membership(
    username: &str,
    groupname: &str,
    change: impl FnOnce(&mut MembershipRow),
) -> anyhow::Result<Option<MembershipRow>> {
    let _guard = lock_key(&MEMBERSHIP_LOCKS, username).await;
    let Some(mut row) = get_membership(username, groupname).await? else {
        return Ok(None);
    };
    change(&mut row);
    row.username = username.to_string();
    row.groupname = groupname.to_string();
    row.is_deleted = 0;
    write_locked(row.clone()).await?;
    Ok(Some(row))
}

async fn soft_delete_locked(username: &str, groupname: &str) -> anyhow::Result<()> {
    let Some(mut row) = get_membership(username, groupname).await? else {
        return Ok(());
    };
    row.is_deleted = 1;
    write_locked(row).await
}

pub async fn soft_delete_membership(username: &str, groupname: &str) -> anyhow::Result<()> {
    let _guard = lock_key(&MEMBERSHIP_LOCKS, username).await;
    soft_delete_locked(username, groupname).await
}

/// The changes of one header sync: the header memberships to remove, and the groups that
/// need a new header membership.
#[derive(Debug, PartialEq)]
struct HeaderSyncPlan {
    remove: Vec<String>,
    add: Vec<String>,
}

/// Remove each header membership whose group the proxy no longer sends, and add a header
/// membership for each sent group without a live membership. Every other row stays as it
/// is stored, so its flags survive the login.
fn header_sync_plan(existing: &[MembershipRow], groups: &[String]) -> HeaderSyncPlan {
    let desired: HashSet<&str> = groups.iter().map(String::as_str).collect();
    let remove = existing
        .iter()
        .filter(|m| m.origin == "header" && !desired.contains(m.groupname.as_str()))
        .map(|m| m.groupname.clone())
        .collect();
    let mut add: Vec<String> = Vec::new();
    for groupname in groups {
        if !existing.iter().any(|m| &m.groupname == groupname) && !add.contains(groupname) {
            add.push(groupname.clone());
        }
    }
    HeaderSyncPlan { remove, add }
}

/// Make the header memberships of a user match the groups that the login proxy sends.
/// A new header membership has both flags clear.
pub async fn sync_header_memberships(username: &str, groups: &[String]) -> anyhow::Result<()> {
    let _guard = lock_key(&MEMBERSHIP_LOCKS, username).await;
    let existing = list_memberships_for_user(username).await?;
    let plan = header_sync_plan(&existing, groups);
    for groupname in &plan.remove {
        soft_delete_locked(username, groupname).await?;
    }
    for groupname in &plan.add {
        write_locked(MembershipRow::new(username, groupname, "header", false)).await?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn stored(groupname: &str, origin: &str, is_group_admin: bool, is_uploader: u8) -> MembershipRow {
        MembershipRow {
            is_uploader,
            ..MembershipRow::new("ana", groupname, origin, is_group_admin)
        }
    }

    #[test]
    fn a_new_membership_has_the_uploader_flag_clear() {
        let row = MembershipRow::new("ana", "editors", "header", false);
        assert_eq!((row.is_uploader, row.is_group_admin, row.is_deleted), (0, false, 0));
    }

    #[test]
    fn the_header_sync_keeps_the_flags_of_an_existing_membership() {
        let existing = vec![
            stored("editors", "header", true, 1),
            stored("legal", "manual", false, 1),
            stored("old", "header", false, 1),
        ];
        let plan = header_sync_plan(&existing, &["editors".to_string(), "press".to_string(), "press".to_string()]);
        // `editors` and `legal` are written by neither list, so their stored rows and
        // flags stay. `old` left the header, and `press` is new.
        assert_eq!(
            plan,
            HeaderSyncPlan { remove: vec!["old".to_string()], add: vec!["press".to_string()] }
        );
    }

    #[test]
    fn a_group_sent_again_after_removal_gets_a_new_row_with_the_flag_clear() {
        // After the removal the live list has no `editors` row. The new row starts clear.
        let plan = header_sync_plan(&[], &["editors".to_string()]);
        assert_eq!(plan.add, vec!["editors".to_string()]);
        assert_eq!(MembershipRow::new("ana", "editors", "header", false).is_uploader, 0);
    }

    #[test]
    fn adding_an_existing_member_again_keeps_both_flags() {
        let existing = stored("editors", "header", true, 1);
        assert_eq!(membership_to_add(Some(&existing), "ana", "editors", "manual", false), None);
        let added = membership_to_add(None, "ana", "editors", "manual", false).unwrap();
        assert_eq!((added.origin.as_str(), added.is_group_admin, added.is_uploader), ("manual", false, 0));
    }

    #[test]
    fn a_membership_version_is_above_every_stored_version() {
        let t = |s: i64| time::OffsetDateTime::from_unix_timestamp(s).unwrap();
        let now = t(1_000) + time::Duration::milliseconds(400);
        assert_eq!(next_membership_version(now, t(0)), t(1_000));
        assert_eq!(next_membership_version(now, t(999)), t(1_000));
        // A second write in the same second, and a stored version ahead of this clock.
        assert_eq!(next_membership_version(now, t(1_000)), t(1_001));
        assert_eq!(next_membership_version(now, t(1_005)), t(1_006));
    }
}
