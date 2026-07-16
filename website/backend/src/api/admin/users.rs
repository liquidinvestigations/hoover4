//! Admin user management API.

use common::admin_types::{AdminMembershipItem, AdminUserDetail, AdminUserItem};
use common::current_user::CurrentUser;
use time::format_description::well_known::Rfc3339;

use crate::auth::guard;
use crate::db_auth::{
    groups::{self},
    sessions,
    users::{self, UserRow},
};

fn format_datetime(dt: time::OffsetDateTime) -> String {
    dt.format(&Rfc3339).unwrap_or_else(|_| dt.to_string())
}

fn slug_valid(s: &str) -> bool {
    !s.is_empty()
        && s.chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-')
}

pub async fn admin_list_users(user: &CurrentUser) -> anyhow::Result<Vec<AdminUserItem>> {
    guard::require_admin(user)?;
    let users = users::list_users().await?;
    let mut result = Vec::with_capacity(users.len());
    for u in users {
        let memberships = groups::list_memberships_for_user(&u.username).await?;
        result.push(AdminUserItem {
            username: u.username,
            fullname: u.fullname,
            email: u.email,
            is_admin: u.is_admin,
            created_at: format_datetime(u.created_at),
            group_count: memberships.len() as u32,
        });
    }
    Ok(result)
}

pub async fn admin_get_user(user: &CurrentUser, username: String) -> anyhow::Result<AdminUserDetail> {
    guard::require_admin(user)?;
    let u = users::get_user(&username)
        .await?
        .ok_or_else(|| anyhow::anyhow!("user not found"))?;
    let memberships = groups::list_memberships_for_user(&username).await?;
    let group_count = memberships.len() as u32;
    Ok(AdminUserDetail {
        user: AdminUserItem {
            username: u.username,
            fullname: u.fullname,
            email: u.email,
            is_admin: u.is_admin,
            created_at: format_datetime(u.created_at),
            group_count,
        },
        memberships: memberships
            .into_iter()
            .map(|m| AdminMembershipItem {
                groupname: m.groupname,
                is_group_admin: m.is_group_admin,
                origin: m.origin,
            })
            .collect(),
    })
}

pub async fn admin_create_user(
    user: &CurrentUser,
    username: String,
    fullname: String,
    email: String,
    is_admin: bool,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    if !slug_valid(&username) {
        anyhow::bail!("invalid username slug");
    }
    if users::get_user(&username).await?.is_some() {
        anyhow::bail!("user already exists");
    }
    users::upsert_user(UserRow {
        username,
        fullname,
        email,
        is_admin,
        created_at: time::OffsetDateTime::now_utc(),
        updated_at: time::OffsetDateTime::now_utc(),
        is_deleted: 0,
    })
    .await
}

pub async fn admin_update_user(
    user: &CurrentUser,
    username: String,
    fullname: String,
    email: String,
    is_admin: bool,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    let Some(mut row) = users::get_user(&username).await? else {
        anyhow::bail!("user not found");
    };
    row.fullname = fullname;
    row.email = email;
    row.is_admin = is_admin;
    users::upsert_user(row).await
}

pub async fn admin_delete_user(user: &CurrentUser, username: String) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    let memberships = groups::list_memberships_for_user(&username).await?;
    for m in memberships {
        groups::soft_delete_membership(&username, &m.groupname).await?;
    }
    sessions::delete_sessions_for_user(&username).await?;
    users::soft_delete_user(&username).await
}
