//! The group of a chat or an investigation board.
//!
//! Every chat and every board belongs to one group (`owner_group`). Every member of the group
//! reads it, continues a chat and acts on a board. Only the creator and administrators delete
//! it. The collections of an item are limited to the collections that its group can read.
//!
//! A group is implicit when the identity provider gives it to every user, for example `user`
//! or `Domain Users`. The create forms list the explicit groups of the person, and a checkbox
//! adds the implicit groups. The backend decides which groups are implicit
//! (`backend::auth::item_access`).

use serde::{Deserialize, Serialize};

/// One group that a person can choose for a new chat or board.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GroupChoice {
    pub name: String,
    /// The identity provider gives this group to every user.
    pub implicit: bool,
    /// The collections that the group can read, sorted. The collection choice of a new item
    /// offers only these.
    pub collections: Vec<String>,
}

/// The groups that a create form lists: the explicit groups, and the implicit groups too when
/// `show_implicit` is true. The order of `choices` stays.
pub fn listed_groups(choices: &[GroupChoice], show_implicit: bool) -> Vec<GroupChoice> {
    choices.iter().filter(|c| show_implicit || !c.implicit).cloned().collect()
}

/// The group that a create form selects first: the first explicit group, else empty.
pub fn default_group(choices: &[GroupChoice]) -> String {
    choices.iter().find(|c| !c.implicit).map(|c| c.name.clone()).unwrap_or_default()
}

/// The selected group after a change of the list: the current group when the list still
/// holds it, else the first listed group, else empty.
pub fn keep_or_first(listed: &[GroupChoice], current: &str) -> String {
    if listed.iter().any(|c| c.name == current) {
        current.to_string()
    } else {
        listed.first().map(|c| c.name.clone()).unwrap_or_default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn choice(name: &str, implicit: bool) -> GroupChoice {
        GroupChoice { name: name.into(), implicit, collections: vec![] }
    }

    #[test]
    fn the_form_lists_explicit_groups_and_selects_the_first_explicit_group() {
        let choices = vec![choice("Domain Users", true), choice("team-a", false), choice("team-b", false)];
        let names = |list: Vec<GroupChoice>| list.into_iter().map(|c| c.name).collect::<Vec<_>>();
        assert_eq!(names(listed_groups(&choices, false)), vec!["team-a", "team-b"]);
        assert_eq!(names(listed_groups(&choices, true)), vec!["Domain Users", "team-a", "team-b"]);
        assert_eq!(default_group(&choices), "team-a");
        assert_eq!(default_group(&[choice("user", true)]), "");
        assert_eq!(default_group(&[]), "");
    }

    #[test]
    fn a_change_of_the_list_keeps_the_selected_group_when_it_stays() {
        let listed = vec![choice("team-a", false), choice("team-b", false)];
        assert_eq!(keep_or_first(&listed, "team-b"), "team-b");
        assert_eq!(keep_or_first(&listed, "user"), "team-a");
        assert_eq!(keep_or_first(&[], "team-a"), "");
    }
}
