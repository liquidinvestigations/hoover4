//! The group rule of chats and investigation boards.
//!
//! Every chat (`chat_sessions.owner_group`) and every board (`boards.owner_group`) belongs to
//! one group. A person reads an item when they are a member of its group. Every member
//! continues a chat and acts on a board. Only the creator and administrators delete an item.
//! A person outside the group gets "not found", as before for the chat or board of another
//! user. A delete by a member who is not the creator is refused with 403.
//!
//! The collections of an item are limited to the collections that its group can read: the
//! collections granted to the group and the public collections. A turn also intersects them
//! with the live permission of the person who sends it.
//!
//! The memberships are the stored rows of `user_group_membership` (header and manual origin)
//! and the groups of the current request. A new chat or board can belong only to a group of
//! the person with the AI flag (`user_groups.ai_enabled`). An administrator sets the flag on
//! the admin page of the group.

use std::collections::HashMap;
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

use common::current_user::CurrentUser;
use common::item_groups::GroupChoice;

use crate::auth::guard;
use crate::db_auth::groups;
use crate::db_utils::clickhouse_utils::{get_global_client, list_permitted_collections};

/// What one person may do with one item.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ItemAccess {
    /// Read, continue a chat, act on a board.
    pub read: bool,
    /// Delete a chat, drop a board.
    pub delete: bool,
}

/// The rule, from the groups of the person. An item without a group belongs to nobody.
/// An administrator deletes every item, also an item of a group that they are not a member of.
pub fn item_access(user: &CurrentUser, member_of: &[String], owner_group: &str, creator: &str) -> ItemAccess {
    let read = !owner_group.is_empty() && member_of.iter().any(|g| g == owner_group);
    ItemAccess { read, delete: user.is_admin || (read && user.username == creator) }
}

/// One item that an agent route looks up by id. The agent routes answer 404 for a missing
/// item and 403 for an item of a group that the caller is not a member of.
#[derive(Debug, Clone, PartialEq)]
pub enum ItemLookup<T> {
    Missing,
    Unreadable,
    Readable(T),
}

/// The groups of the person are read again after this time, so a membership change applies
/// to the next request after it.
const MEMBER_CACHE_TTL: Duration = Duration::from_secs(10);

static MEMBER_CACHE: LazyLock<Mutex<HashMap<String, (Instant, Vec<String>)>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

/// The groups of the person: the stored memberships and the groups of the current request,
/// sorted, without duplicates.
pub async fn member_groups(user: &CurrentUser) -> anyhow::Result<Vec<String>> {
    if let Some((at, list)) = MEMBER_CACHE.lock().unwrap_or_else(|e| e.into_inner()).get(&user.username) {
        if at.elapsed() < MEMBER_CACHE_TTL {
            let mut list = list.clone();
            list.extend(user.groups.iter().cloned());
            list.sort();
            list.dedup();
            return Ok(list);
        }
    }
    let stored: Vec<String> = groups::list_memberships_for_user(&user.username)
        .await?
        .into_iter()
        .map(|m| m.groupname)
        .collect();
    MEMBER_CACHE
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .insert(user.username.clone(), (Instant::now(), stored.clone()));
    let mut list = stored;
    list.extend(user.groups.iter().cloned());
    list.sort();
    list.dedup();
    Ok(list)
}

/// The access of the person to one item.
pub async fn access(user: &CurrentUser, owner_group: &str, creator: &str) -> anyhow::Result<ItemAccess> {
    Ok(item_access(user, &member_groups(user).await?, owner_group, creator))
}

/// The collections that `group` can read: the collections granted to it and the public
/// collections, sorted. Deleted collections are left out.
pub async fn group_collections(group: &str) -> anyhow::Result<Vec<String>> {
    let mut list: Vec<String> = get_global_client()
        .query(
            "SELECT DISTINCT collectionname FROM collections FINAL WHERE is_deleted = 0 AND (is_public = 1 \
             OR collectionname IN (SELECT collectionname FROM collection_group_permissions FINAL \
             WHERE groupname = ? AND is_deleted = 0))",
        )
        .bind(group)
        .fetch_all()
        .await?;
    list.sort();
    Ok(list)
}

/// The collections that both the person and `group` can read, sorted.
pub async fn shared_collections(user: &CurrentUser, group: &str) -> anyhow::Result<Vec<String>> {
    let permitted = list_permitted_collections(user).await?;
    Ok(group_collections(group).await?.into_iter().filter(|c| permitted.contains(c)).collect())
}

/// The groups that the person can choose for a new chat or board: the groups of the person
/// with the AI flag, sorted by name, each with the collections that the person and the group
/// can both read.
pub async fn group_choices(user: &CurrentUser) -> anyhow::Result<Vec<GroupChoice>> {
    let permitted = list_permitted_collections(user).await?;
    let mut choices = Vec::new();
    for name in groups::ai_enabled_among(&member_groups(user).await?).await? {
        let collections = group_collections(&name).await?.into_iter().filter(|c| permitted.contains(c)).collect();
        choices.push(GroupChoice { name, collections });
    }
    choices.sort_by_key(|c| c.name.to_lowercase());
    Ok(choices)
}

/// The refusal of a create request without a group.
pub const CHOOSE_A_GROUP: &str = "Choose a group.";
/// The refusal of a create request for a group of which the person is not a member.
pub const NOT_A_MEMBER: &str = "You are not a member of this group.";
/// The refusal of a create request for a group without the AI flag.
pub const NO_AI_CONTENT: &str = "This group cannot hold AI chats and boards.";
/// The refusal of a collection that the group or the person cannot read.
pub const GROUP_CANNOT_READ: &str = "The group cannot read one of the selected collections.";

/// The group of a new item, checked: the person must be a member, and the group must have
/// the AI flag.
pub async fn require_member(user: &CurrentUser, group: &str) -> anyhow::Result<String> {
    let group = group.trim();
    if group.is_empty() {
        return Err(guard::InvalidInput(CHOOSE_A_GROUP.into()).into());
    }
    if !member_groups(user).await?.iter().any(|g| g == group) {
        return Err(guard::Forbidden(NOT_A_MEMBER.into()).into());
    }
    if groups::ai_enabled_among(&[group.to_string()]).await?.is_empty() {
        return Err(guard::Forbidden(NO_AI_CONTENT.into()).into());
    }
    Ok(group.to_string())
}

/// The requested collections of an item of `group`, checked against `allowed`, the collections
/// that the person and the group can both read. A collection outside `allowed` refuses the
/// request.
pub fn check_collections(requested: &[String], allowed: &[String]) -> Result<Vec<String>, guard::InvalidInput> {
    let mut out = Vec::new();
    for name in requested {
        if !allowed.contains(name) {
            return Err(guard::InvalidInput(GROUP_CANNOT_READ.into()));
        }
        if !out.contains(name) {
            out.push(name.clone());
        }
    }
    out.sort();
    Ok(out)
}

/// The header that names the chat session of an agent run.
pub const RUN_SESSION_HEADER: &str = "x-hoover4-chat-session";

/// The group of the chat that an agent run answers, or empty.
///
/// An agent run calls the agent routes as the creator of its chat, and a member of the chat
/// group can send its turn. The agent routes that read chats, boards and the manuals give a
/// run only what every member of the chat group can read. The website reads the chat from
/// the session header and the user of the run, so a run can name only a chat of its own
/// user. A run without the header or with an unknown chat has no group, and reads no chat
/// or board.
pub async fn run_group(user: &CurrentUser, headers: &axum::http::HeaderMap) -> anyhow::Result<String> {
    let session = headers
        .get(RUN_SESSION_HEADER)
        .and_then(|value| value.to_str().ok())
        .map(str::trim)
        .unwrap_or_default();
    if session.is_empty() {
        return Ok(String::new());
    }
    Ok(crate::db_chat::get_session(&user.username, session)
        .await?
        .map(|row| row.owner_group)
        .unwrap_or_default())
}

/// True when an item of `owner_group` is in the group of the run.
pub fn in_run_group(run_group: &str, owner_group: &str) -> bool {
    !run_group.is_empty() && run_group == owner_group
}

/// The caller as the manual routes of a run see it. The run reads the administration manual
/// only when its user is an administrator and every member of the chat group is one.
pub fn run_manual_reader(user: &CurrentUser, run_group: &str) -> CurrentUser {
    let mut reader = user.clone();
    reader.is_admin = user.is_admin && !run_group.is_empty() && crate::auth::session_middleware::is_admin_group(run_group);
    reader
}

#[cfg(test)]
mod tests {
    use super::*;

    fn user(name: &str, admin: bool) -> CurrentUser {
        CurrentUser { username: name.into(), fullname: String::new(), email: String::new(), is_admin: admin, groups: vec![] }
    }

    fn names(list: &[&str]) -> Vec<String> {
        list.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn a_run_reads_only_the_items_of_its_chat_group() {
        assert!(in_run_group("team-a", "team-a"));
        assert!(!in_run_group("team-a", "team-b"));
        assert!(!in_run_group("", ""));
        // HOOVER4_ADMIN_GROUPS is absent in the tests, so `admin` is an administrator group.
        assert!(run_manual_reader(&user("root", true), "admin").is_admin);
        assert!(!run_manual_reader(&user("root", true), "team-a").is_admin);
        assert!(!run_manual_reader(&user("root", true), "").is_admin);
        assert!(!run_manual_reader(&user("alice", false), "admin").is_admin);
    }

    #[test]
    fn a_member_reads_and_only_the_creator_and_an_administrator_delete() {
        let groups = names(&["team-a"]);
        let creator = item_access(&user("alice", false), &groups, "team-a", "alice");
        assert_eq!(creator, ItemAccess { read: true, delete: true });
        let member = item_access(&user("bob", false), &groups, "team-a", "alice");
        assert_eq!(member, ItemAccess { read: true, delete: false });
        let outsider = item_access(&user("carol", false), &names(&["team-b"]), "team-a", "alice");
        assert_eq!(outsider, ItemAccess { read: false, delete: false });
        let admin = item_access(&user("root", true), &groups, "team-a", "alice");
        assert_eq!(admin, ItemAccess { read: true, delete: true });
        // An administrator outside the group does not read the item, and can delete it.
        let admin_outside = item_access(&user("root", true), &[], "team-a", "alice");
        assert_eq!(admin_outside, ItemAccess { read: false, delete: true });
        // The creator who left the group no longer reads or deletes the item.
        let former = item_access(&user("alice", false), &[], "team-a", "alice");
        assert_eq!(former, ItemAccess { read: false, delete: false });
        // An item without a group belongs to nobody, also for a person in a group named "".
        assert!(!item_access(&user("alice", false), &names(&[""]), "", "alice").read);
    }

    #[test]
    fn a_collection_outside_the_group_refuses_the_request() {
        let allowed = names(&["enron", "tables"]);
        assert_eq!(check_collections(&names(&["tables", "enron", "tables"]), &allowed).unwrap(), allowed);
        assert_eq!(check_collections(&[], &allowed).unwrap(), Vec::<String>::new());
        assert_eq!(check_collections(&names(&["enron", "secret"]), &allowed).unwrap_err().0, GROUP_CANNOT_READ);
    }
}
