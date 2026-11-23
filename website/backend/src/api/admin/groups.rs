//! Admin group management API.

use common::admin_types::{AdminGroupDetail, AdminGroupItem, AdminGroupMemberItem};
use common::current_user::CurrentUser;

use crate::auth::guard;
use crate::db_auth::{
    collections,
    groups::{self, GroupRow},
};

fn slug_valid(s: &str) -> bool {
    !s.is_empty()
        && s.chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-')
}

/// The nearest legal slug to what was typed, for the rejection message.
///
/// Naming the rule is not the same as showing it: the overwhelmingly common rejection is
/// a capital letter in an otherwise fine name, and `TestGroup` -> `testgroup` says more
/// than any sentence about character classes.
fn slug_suggestion(s: &str) -> String {
    let suggestion: String = s
        .trim()
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() {
                c.to_ascii_lowercase()
            } else {
                '_'
            }
        })
        .collect();
    if suggestion.is_empty() {
        "my_group".to_string()
    } else {
        suggestion
    }
}

pub async fn admin_list_groups(user: &CurrentUser) -> anyhow::Result<Vec<AdminGroupItem>> {
    guard::require_admin(user)?;
    let groups = groups::list_groups().await?;
    let mut result = Vec::with_capacity(groups.len());
    for g in groups {
        let members = groups::list_memberships_for_group(&g.groupname).await?;
        let perms = collections::list_permissions_for_group(&g.groupname).await?;
        result.push(AdminGroupItem {
            groupname: g.groupname,
            fullname: g.fullname,
            member_count: members.len() as u32,
            collection_count: perms.len() as u32,
            ai_enabled: g.ai_enabled == 1,
        });
    }
    Ok(result)
}

pub async fn admin_get_group(
    user: &CurrentUser,
    groupname: String,
) -> anyhow::Result<AdminGroupDetail> {
    guard::require_admin(user)?;
    let g = groups::get_group(&groupname)
        .await?
        .ok_or_else(|| anyhow::anyhow!("group not found"))?;
    let members = groups::list_memberships_for_group(&groupname).await?;
    let perms = collections::list_permissions_for_group(&groupname).await?;
    Ok(AdminGroupDetail {
        group: AdminGroupItem {
            groupname: g.groupname,
            fullname: g.fullname,
            member_count: members.len() as u32,
            collection_count: perms.len() as u32,
            ai_enabled: g.ai_enabled == 1,
        },
        members: members
            .into_iter()
            .map(|m| AdminGroupMemberItem {
                username: m.username,
                is_group_admin: m.is_group_admin,
                is_uploader: m.is_uploader == 1,
                origin: m.origin,
            })
            .collect(),
        collections: perms.into_iter().map(|p| p.collectionname).collect(),
    })
}

pub async fn admin_create_group(
    user: &CurrentUser,
    groupname: String,
    fullname: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    if !slug_valid(&groupname) {
        return Err(guard::InvalidInput(format!(
            "\u{201c}{groupname}\u{201d} is not a valid group name. Use lowercase letters, \
             digits, underscores and hyphens only \u{2014} for example \
             \u{201c}{}\u{201d}.",
            slug_suggestion(&groupname)
        ))
        .into());
    }
    if groups::get_group(&groupname).await?.is_some() {
        return Err(guard::InvalidInput(format!("The group \u{201c}{groupname}\u{201d} already exists.")).into());
    }
    groups::upsert_group(GroupRow {
        groupname,
        fullname,
        created_at: time::OffsetDateTime::now_utc(),
        updated_at: time::OffsetDateTime::now_utc(),
        is_deleted: 0,
        ai_enabled: 0,
    })
    .await
}

pub async fn admin_update_group(
    user: &CurrentUser,
    groupname: String,
    fullname: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    let Some(mut row) = groups::get_group(&groupname).await? else {
        anyhow::bail!("group not found");
    };
    row.fullname = fullname;
    groups::upsert_group(row).await
}

pub async fn admin_delete_group(user: &CurrentUser, groupname: String) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    if groupname == "admin" || groupname == "superuser" {
        anyhow::bail!("cannot delete reserved group");
    }
    let members = groups::list_memberships_for_group(&groupname).await?;
    for m in members {
        groups::soft_delete_membership(&m.username, &groupname).await?;
    }
    let perms = collections::list_permissions_for_group(&groupname).await?;
    for p in perms {
        collections::revoke_permission(&groupname, &p.collectionname).await?;
    }
    groups::soft_delete_group(&groupname).await
}

/// The refusal of a change that turns the AI flag off while the group owns chats or boards.
/// The values are the counts of chats and boards.
pub fn ai_content_left(chats: u64, boards: u64) -> String {
    format!(
        "Delete the chats and boards of this group first. Chats: {chats}. Boards: {boards}. \
         Join the group to see them on the history pages."
    )
}

/// Set the AI flag of a group. The flag goes off only when the group owns no chat and no
/// board. The explore chats of a board are not counted, because the board deletes them.
pub async fn admin_set_group_ai(user: &CurrentUser, groupname: String, on: bool) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    let Some(mut row) = groups::get_group(&groupname).await? else {
        anyhow::bail!("group not found");
    };
    if !on {
        let client = crate::db_utils::clickhouse_utils::get_global_client();
        let chats: u64 = client
            .query("SELECT count() FROM chat_sessions FINAL WHERE owner_group = ? AND is_deleted = 0 \
                    AND NOT startsWith(session_id, ?)")
            .bind(&groupname)
            .bind(common::board_types::BOARD_SESSION_PREFIX)
            .fetch_one()
            .await?;
        let boards: u64 = client
            .query("SELECT count() FROM boards FINAL WHERE owner_group = ? AND is_deleted = 0")
            .bind(&groupname)
            .fetch_one()
            .await?;
        if chats > 0 || boards > 0 {
            return Err(guard::InvalidInput(ai_content_left(chats, boards)).into());
        }
    }
    row.ai_enabled = u8::from(on);
    groups::upsert_group(row).await
}

/// Add a user to a group. A user who is already a member keeps the stored membership,
/// with its origin, its group admin flag and its uploader flag.
pub async fn admin_add_member(
    user: &CurrentUser,
    groupname: String,
    username: String,
    is_group_admin: bool,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    if groups::get_group(&groupname).await?.is_none() {
        anyhow::bail!("group not found");
    }
    if crate::db_auth::users::get_user(&username).await?.is_none() {
        anyhow::bail!("user not found");
    }
    groups::add_membership(&username, &groupname, "manual", is_group_admin).await?;
    Ok(())
}

pub async fn admin_remove_member(
    user: &CurrentUser,
    groupname: String,
    username: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    groups::soft_delete_membership(&username, &groupname).await
}

pub async fn admin_set_group_admin(
    user: &CurrentUser,
    groupname: String,
    username: String,
    is_group_admin: bool,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    groups::update_membership(&username, &groupname, |row| row.is_group_admin = is_group_admin)
        .await?
        .ok_or_else(|| anyhow::anyhow!("membership not found"))?;
    Ok(())
}

/// Set the uploader flag of a membership. The member may then upload into the upload
/// dataset of each collection that the group can read. The other columns keep their
/// stored values.
pub async fn admin_set_uploader(
    user: &CurrentUser,
    groupname: String,
    username: String,
    on: bool,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    groups::update_membership(&username, &groupname, |row| row.is_uploader = u8::from(on))
        .await?
        .ok_or_else(|| anyhow::anyhow!("membership not found"))?;
    Ok(())
}
