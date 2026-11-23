//! The group of a chat or an investigation board.
//!
//! Every chat and every board belongs to one group (`owner_group`). Every member of the group
//! reads it, continues a chat and acts on a board. Only the creator and administrators delete
//! it. The collections of an item are limited to the collections that its group can read.
//!
//! A new item can belong only to a group of the person with the AI flag
//! (`user_groups.ai_enabled`). The backend lists these groups (`backend::auth::item_access`).

use serde::{Deserialize, Serialize};

/// One group that a person can choose for a new chat or board.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GroupChoice {
    pub name: String,
    /// The collections that the group can read, sorted. The collection choice of a new item
    /// offers only these.
    pub collections: Vec<String>,
}

/// The group that a create form selects first: the first group, else empty.
pub fn default_group(choices: &[GroupChoice]) -> String {
    choices.first().map(|c| c.name.clone()).unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn choice(name: &str) -> GroupChoice {
        GroupChoice { name: name.into(), collections: vec![] }
    }

    #[test]
    fn the_form_selects_the_first_group() {
        assert_eq!(default_group(&[choice("admin"), choice("user")]), "admin");
        assert_eq!(default_group(&[]), "");
    }
}
