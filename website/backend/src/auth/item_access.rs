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
//! and the groups of the current request. A group that the identity provider gives to every
//! user is implicit. `HOOVER4_IMPLICIT_GROUPS` (`[main_services] implicit_groups`) lists the
//! implicit groups as a comma list: an entry that ends in `*` is a name prefix, every other
//! entry is an exact name. Absent or empty gives [`DEFAULT_IMPLICIT_GROUPS`]. The create
//! forms list implicit groups only when the person asks for them.

use std::collections::HashMap;
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

use common::current_user::CurrentUser;
use common::item_groups::GroupChoice;

use crate::auth::guard;
use crate::db_auth::groups;
use crate::db_utils::clickhouse_utils::{get_global_client, list_permitted_collections};

/// The implicit groups when `HOOVER4_IMPLICIT_GROUPS` is absent. **Mirrored in `deploy.py`**
/// (`DEFAULTS["main_services"]["implicit_groups"]`): the groups that liquid-core and openDesk
/// give to every user, and their application groups.
pub const DEFAULT_IMPLICIT_GROUPS: &str = "user, Guests, hoover, hoover4, nextcloud, nextcloud28, \
     nextcloud-admin, wikijs, dokuwiki, codimd, grist, matrix, prophecies, bbb, xwiki, Domain Users, \
     Domain Admins, IAM API - Full Access, managed-by-attribute-*";

/// The entries of an implicit group list: comma separated, trimmed, empty entries dropped.
/// An absent or empty value gives the default list.
pub fn implicit_rules_from(value: Option<&str>) -> Vec<String> {
    value
        .filter(|v| !v.trim().is_empty())
        .unwrap_or(DEFAULT_IMPLICIT_GROUPS)
        .split(',')
        .map(str::trim)
        .filter(|entry| !entry.is_empty())
        .map(str::to_string)
        .collect()
}

static IMPLICIT_RULES: LazyLock<Vec<String>> =
    LazyLock::new(|| implicit_rules_from(std::env::var("HOOVER4_IMPLICIT_GROUPS").ok().as_deref()));

/// True when `name` matches an entry of `rules`: the same name, or a name that starts with
/// the text before the `*` of an entry that ends in `*`.
pub fn is_implicit_in(name: &str, rules: &[String]) -> bool {
    rules.iter().any(|rule| match rule.strip_suffix('*') {
        Some(prefix) => name.starts_with(prefix),
        None => name == rule,
    })
}

/// True when the configured list names `name` as an implicit group.
pub fn is_implicit(name: &str) -> bool {
    is_implicit_in(name, &IMPLICIT_RULES)
}

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

/// The groups that the person can choose for a new chat or board, explicit groups first, each
/// with the collections that the person and the group can both read.
pub async fn group_choices(user: &CurrentUser) -> anyhow::Result<Vec<GroupChoice>> {
    let permitted = list_permitted_collections(user).await?;
    let mut choices = Vec::new();
    for name in member_groups(user).await? {
        let collections = group_collections(&name).await?.into_iter().filter(|c| permitted.contains(c)).collect();
        choices.push(GroupChoice { implicit: is_implicit(&name), name, collections });
    }
    choices.sort_by(|a, b| (a.implicit, a.name.to_lowercase()).cmp(&(b.implicit, b.name.to_lowercase())));
    Ok(choices)
}

/// The refusal of a create request without a group.
pub const CHOOSE_A_GROUP: &str = "Choose a group.";
/// The refusal of a create request for a group of which the person is not a member.
pub const NOT_A_MEMBER: &str = "You are not a member of this group.";
/// The refusal of a collection that the group or the person cannot read.
pub const GROUP_CANNOT_READ: &str = "The group cannot read one of the selected collections.";

/// The group of a new item, checked: the person must be a member.
pub async fn require_member(user: &CurrentUser, group: &str) -> anyhow::Result<String> {
    let group = group.trim();
    if group.is_empty() {
        return Err(guard::InvalidInput(CHOOSE_A_GROUP.into()).into());
    }
    if !member_groups(user).await?.iter().any(|g| g == group) {
        return Err(guard::Forbidden(NOT_A_MEMBER.into()).into());
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
    fn an_implicit_group_is_an_exact_name_or_a_name_with_a_listed_prefix() {
        let rules = implicit_rules_from(None);
        for name in ["user", "Guests", "Domain Users", "IAM API - Full Access", "managed-by-attribute-Notes",
                     "managed-by-attribute-FileshareAdmin", "nextcloud"] {
            assert!(is_implicit_in(name, &rules), "{name}");
        }
        for name in ["users", "team-a", "demo_fr", "admin", "managed-by-attr", "Domain Users 2"] {
            assert!(!is_implicit_in(name, &rules), "{name}");
        }
        let custom = implicit_rules_from(Some(" staff , ,org-* "));
        assert_eq!(custom, names(&["staff", "org-*"]));
        assert!(is_implicit_in("org-sales", &custom) && is_implicit_in("staff", &custom));
        assert!(!is_implicit_in("user", &custom));
        assert_eq!(implicit_rules_from(Some(" ")), rules);
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
