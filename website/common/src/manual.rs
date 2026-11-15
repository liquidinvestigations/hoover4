//! The manuals that the website shows at `/docs` and `/docs/admin`.
//!
//! The backend reads the Markdown of `docs/user-manual/` (`backend::manual`). Each heading
//! gets the anchor that GitHub gives it ([`Slugger`]), so a link to a section of the
//! repository file and a link to the same section of the page use the same anchor.

use serde::{Deserialize, Serialize};

/// The address of the user manual.
pub const USER_MANUAL_PATH: &str = "/docs";
/// The address of the administration manual. Only administrators read it.
pub const ADMIN_MANUAL_PATH: &str = "/docs/admin";

/// The `manual` value of the agent routes for the user manual.
pub const USER_MANUAL: &str = "user";
/// The `manual` value of the agent routes for the administration manual.
pub const ADMIN_MANUAL: &str = "admin";

/// The address of one section, or of the manual when `slug` is empty.
pub fn section_link(admin: bool, slug: &str) -> String {
    let base = if admin { ADMIN_MANUAL_PATH } else { USER_MANUAL_PATH };
    if slug.is_empty() { base.to_string() } else { format!("{base}#{slug}") }
}

/// One heading of a manual, for the contents list of the page.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct ManualHeading {
    pub level: u8,
    pub title: String,
    pub slug: String,
}

/// One manual as the page shows it. `html` comes from the Markdown of the image, which is
/// trusted. Model output never reaches it.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct ManualPage {
    pub title: String,
    pub html: String,
    pub headings: Vec<ManualHeading>,
}

/// The GitHub anchor of a heading text, before the number that a repeated anchor gets:
/// lower case, every character removed except letters, digits, marks, `_`, `-` and spaces,
/// and each space replaced by `-`. `4. Search` gives `4-search`.
pub fn github_slug(text: &str) -> String {
    text.trim()
        .to_lowercase()
        .chars()
        .filter(|c| c.is_alphanumeric() || *c == '_' || *c == '-' || *c == ' ')
        .map(|c| if c == ' ' { '-' } else { c })
        .collect()
}

/// The anchors of the headings of one document, in order. A repeated anchor gets `-1`,
/// `-2` and so on, as on GitHub.
#[derive(Debug, Default)]
pub struct Slugger {
    used: std::collections::HashSet<String>,
}

impl Slugger {
    /// The unique anchor of the next heading with this text.
    pub fn slug(&mut self, text: &str) -> String {
        let base = github_slug(text);
        let mut slug = base.clone();
        let mut n = 0;
        while self.used.contains(&slug) {
            n += 1;
            slug = format!("{base}-{n}");
        }
        self.used.insert(slug.clone());
        slug
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn headings_get_the_github_anchors() {
        assert_eq!(github_slug("4. Search"), "4-search");
        assert_eq!(github_slug("8. Storage: browsing by folder"), "8-storage-browsing-by-folder");
        assert_eq!(github_slug("Apply a search scope."), "apply-a-search-scope");
        assert_eq!(github_slug("Detected OCR language and Detected OCR script"), "detected-ocr-language-and-detected-ocr-script");
        assert_eq!(github_slug("Export, restore, and collect diagnostics."), "export-restore-and-collect-diagnostics");
        assert_eq!(github_slug("Hoover: user manual"), "hoover-user-manual");
        assert_eq!(github_slug("Année  2001 – re_run"), "année--2001--re_run");
    }

    #[test]
    fn a_repeated_heading_gets_a_number() {
        let mut slugger = Slugger::default();
        assert_eq!(slugger.slug("Entities"), "entities");
        assert_eq!(slugger.slug("Entities"), "entities-1");
        assert_eq!(slugger.slug("Entities"), "entities-2");
        assert_eq!(slugger.slug("Entities 1"), "entities-1-1");
    }

    #[test]
    fn section_links_name_the_manual() {
        assert_eq!(section_link(false, "4-search"), "/docs#4-search");
        assert_eq!(section_link(true, "datasets"), "/docs/admin#datasets");
        assert_eq!(section_link(true, ""), "/docs/admin");
    }
}
