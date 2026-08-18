//! Admin group management API.

use common::admin_types::{AdminGroupDetail, AdminGroupItem, AdminGroupMemberItem};
use common::current_user::CurrentUser;

use crate::auth::guard;
use crate::db_auth::{
    collections,
    groups::{self, GroupRow, MembershipRow},
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
        },
        members: members
            .into_iter()
            .map(|m| AdminGroupMemberItem {
                username: m.username,
                is_group_admin: m.is_group_admin,
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
    groups::upsert_membership(MembershipRow {
        username,
        groupname,
        is_group_admin,
        origin: "manual".to_string(),
        created_at: time::OffsetDateTime::now_utc(),
        updated_at: time::OffsetDateTime::now_utc(),
        is_deleted: 0,
    })
    .await
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
    let Some(mut row) = groups::get_membership(&username, &groupname).await? else {
        anyhow::bail!("membership not found");
    };
    row.is_group_admin = is_group_admin;
    groups::upsert_membership(row).await
}
