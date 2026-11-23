//! One page of the chat history or the board list.
//!
//! Both pages read one page at a time from the server: a search text, a group, a time order
//! and a page number. The chat history also filters by creator and shows board chats on
//! request. The search matches a part of the title or the summary, with no regard to case.
//! The route query holds every value, so a link opens the same page.

use serde::{Deserialize, Serialize};

/// The items of one page.
pub const ITEM_LIST_PAGE_SIZE: u32 = 25;

/// The longest search text, in characters, that the server applies.
pub const MAX_SEARCH_CHARS: usize = 200;

/// The request for one page.
#[derive(Debug, Clone, PartialEq, Eq, Default, Serialize, Deserialize)]
pub struct ItemListQuery {
    /// A part of the title or the summary. Empty matches every item.
    pub search: String,
    /// One group, or empty for every group of the person.
    pub group: String,
    /// Only the chats that the person created. The board list ignores it.
    pub mine: bool,
    /// The chat history shows the explore chats of the boards too. The board list ignores it.
    pub include_boards: bool,
    /// The oldest item first. The default is the newest item first.
    pub oldest_first: bool,
    /// The page, from 1.
    pub page: u32,
}

impl ItemListQuery {
    /// The query of the route values. An empty or a bad value takes its default, so an older
    /// link keeps working.
    pub fn from_route(search: &str, group: &str, mine: &str, boards: &str, sort: &str, page: &str) -> Self {
        ItemListQuery {
            search: search.to_string(),
            group: group.to_string(),
            mine: mine == "1",
            include_boards: boards == "1",
            oldest_first: sort == "oldest",
            page: page.parse::<u32>().unwrap_or(1).max(1),
        }
    }

    /// The search text that the server applies: trimmed and cut to `MAX_SEARCH_CHARS`.
    pub fn search_text(&self) -> String {
        self.search.trim().chars().take(MAX_SEARCH_CHARS).collect()
    }

    /// The count of items before the page.
    pub fn offset(&self) -> u64 {
        u64::from(self.page.max(1) - 1) * u64::from(ITEM_LIST_PAGE_SIZE)
    }
}

/// The route value of a flag: `1` or empty.
pub fn flag_value(on: bool) -> String {
    if on { "1".into() } else { String::new() }
}

/// The route value of the time order: `oldest` or empty.
pub fn sort_value(oldest_first: bool) -> String {
    if oldest_first { "oldest".into() } else { String::new() }
}

/// One page of items.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ItemPage<T> {
    pub items: Vec<T>,
    /// The count of every item that matches the query.
    pub total: u64,
    /// The groups that own at least one item that the person can read, sorted. The group
    /// filter lists them.
    pub groups: Vec<String>,
}

/// The count of pages for `total` items, at least 1.
pub fn page_count(total: u64) -> u32 {
    (total.div_ceil(u64::from(ITEM_LIST_PAGE_SIZE)).max(1)).min(u64::from(u32::MAX)) as u32
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_route_value_takes_its_default_when_it_is_empty_or_bad() {
        let q = ItemListQuery::from_route("", "", "", "", "", "");
        assert_eq!(q, ItemListQuery { page: 1, ..Default::default() });
        let q = ItemListQuery::from_route("water", "team-a", "1", "1", "oldest", "3");
        assert!(q.mine && q.include_boards && q.oldest_first);
        assert_eq!((q.page, q.offset()), (3, 50));
        assert_eq!(ItemListQuery::from_route("", "", "yes", "", "newest", "0").page, 1);
        assert!(!ItemListQuery::from_route("", "", "yes", "", "newest", "x").mine);
    }

    #[test]
    fn the_search_text_is_trimmed_and_cut() {
        let q = ItemListQuery { search: format!("  {}  ", "a".repeat(300)), ..Default::default() };
        assert_eq!(q.search_text().len(), MAX_SEARCH_CHARS);
    }

    #[test]
    fn the_page_count_is_at_least_one() {
        assert_eq!(page_count(0), 1);
        assert_eq!(page_count(25), 1);
        assert_eq!(page_count(26), 2);
    }
}
