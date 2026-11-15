//! The manuals of `docs/user-manual/`: the page `/docs` and `/docs/admin`, and the agent
//! routes `manual/search` and `manual/read`.
//!
//! The image build copies `docs/user-manual/` into the image, and the development container
//! mounts it. `HOOVER4_MANUAL_DIR` names the folder, by default [`DEFAULT_MANUAL_DIR`]. The
//! server reads both manuals once at start ([`load`]) and keeps them in memory. A change of
//! the Markdown needs a restart.
//!
//! Each heading starts a section. Its anchor is the GitHub anchor of the heading text
//! (`common::manual::Slugger`), so `/docs#4-search` opens the section that
//! `User_Manual.md#4-search` opens on GitHub. The page HTML comes from `pulldown-cmark` with
//! the raw HTML of the manuals, because the source is the image and no model output reaches
//! this renderer. Image paths (`img/`, `crops/`) point at the asset route [`ASSET_PREFIX`].
//! Links to the two manuals point at the manual pages, and links to other repository
//! documents point at the public repository.

use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use common::agent_api::{AgentManualSection, ManualReadResponse};
use common::current_user::CurrentUser;
use common::manual::{
    section_link, ManualHeading, ManualPage, Slugger, ADMIN_MANUAL, USER_MANUAL,
};
use pulldown_cmark::{CowStr, Event, Options, Parser, Tag, TagEnd};

use crate::auth::guard;

/// The environment variable that names the manual folder.
pub const MANUAL_DIR_ENV: &str = "HOOVER4_MANUAL_DIR";
/// The manual folder of the image and of the development container.
pub const DEFAULT_MANUAL_DIR: &str = "/app/docs/user-manual";
/// The route of the images of the manuals (`server_extra::manual_assets`).
pub const ASSET_PREFIX: &str = "/_manual/";
/// The folders of the manual folder that the asset route serves.
pub const ASSET_FOLDERS: [&str; 2] = ["img/", "crops/"];

const USER_FILE: &str = "User_Manual.md";
const ADMIN_FILE: &str = "Admin_Manual.md";
/// The folder of the manuals in the public repository. A relative link to another
/// repository document resolves against it.
const REPOSITORY_FOLDER: &str = "https://github.com/liquidinvestigations/hoover4/blob/main/docs/user-manual/";

/// The longest section text that `manual/read` returns, in characters.
const MAX_READ_CHARS: usize = 16_000;
/// The most sections that `manual/search` returns.
const MAX_HITS: usize = 8;
/// The length of a search snippet, in characters.
const SNIPPET_CHARS: usize = 240;

/// One section: a heading and the text up to the next heading.
#[derive(Debug, Clone, PartialEq)]
pub struct Section {
    pub level: u8,
    pub title: String,
    pub slug: String,
    /// The byte offset of the heading in the source.
    pub start: usize,
    /// The byte offset of the next heading, which ends the text of this heading only.
    pub own_end: usize,
    /// The byte offset of the next heading of the same or a higher level, which ends the
    /// section with its subsections.
    pub tree_end: usize,
    /// The plain text of the heading and its own text, for the search.
    pub plain: String,
}

/// One manual.
#[derive(Debug, Clone)]
pub struct Manual {
    pub admin: bool,
    pub source: String,
    pub sections: Vec<Section>,
    pub page: ManualPage,
}

/// Both manuals, or the error of each that did not load.
#[derive(Debug)]
pub struct Manuals {
    pub user: Result<Manual, String>,
    pub admin: Result<Manual, String>,
    pub dir: PathBuf,
}

static MANUALS: OnceLock<Manuals> = OnceLock::new();

/// The manual folder.
pub fn manual_dir() -> PathBuf {
    std::env::var(MANUAL_DIR_ENV)
        .ok()
        .filter(|value| !value.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(DEFAULT_MANUAL_DIR))
}

/// Read both manuals, once. The server calls it at start and logs a manual that is absent.
pub fn load() -> &'static Manuals {
    MANUALS.get_or_init(|| {
        let dir = manual_dir();
        let read = |file: &str, admin: bool| -> Result<Manual, String> {
            let path = dir.join(file);
            std::fs::read_to_string(&path)
                .map(|source| Manual::parse(source, admin))
                .map_err(|e| format!("cannot read {}: {e}", path.display()))
        };
        let manuals = Manuals { user: read(USER_FILE, false), admin: read(ADMIN_FILE, true), dir };
        for result in [&manuals.user, &manuals.admin] {
            match result {
                Ok(manual) => tracing::info!("manual loaded: {} sections", manual.sections.len()),
                Err(error) => tracing::error!("manual not loaded: {error}"),
            }
        }
        manuals
    })
}

/// The Markdown extensions of GitHub that the manuals use.
fn options() -> Options {
    Options::ENABLE_TABLES | Options::ENABLE_STRIKETHROUGH | Options::ENABLE_TASKLISTS
}

impl Manual {
    /// Split and render one manual.
    pub fn parse(source: String, admin: bool) -> Manual {
        let sections = split_sections(&source);
        let html = render_html(&source, admin, &sections);
        let title = sections.iter().find(|s| s.level == 1).map(|s| s.title.clone()).unwrap_or_default();
        let headings = sections
            .iter()
            .filter(|s| (2..=3).contains(&s.level))
            .map(|s| ManualHeading { level: s.level, title: s.title.clone(), slug: s.slug.clone() })
            .collect();
        Manual { admin, source, sections, page: ManualPage { title, html, headings } }
    }

    /// The `manual` value of the agent routes.
    pub fn name(&self) -> &'static str {
        if self.admin { ADMIN_MANUAL } else { USER_MANUAL }
    }

    fn hit(&self, section: &Section, snippet: String) -> AgentManualSection {
        AgentManualSection {
            manual: self.name().to_string(),
            section: section.slug.clone(),
            title: section.title.clone(),
            link: section_link(self.admin, &section.slug),
            snippet,
        }
    }

    /// The section and its subsections for an agent, or the contents of the manual when
    /// `slug` is empty. `None` for an unknown anchor.
    pub fn read(&self, slug: &str) -> Option<ManualReadResponse> {
        if slug.is_empty() {
            let mut text = String::new();
            for section in self.sections.iter().filter(|s| s.level >= 2) {
                let indent = "  ".repeat(usize::from(section.level.saturating_sub(2)));
                text.push_str(&format!("{indent}- [{}]({})\n", section.title, section_link(self.admin, &section.slug)));
            }
            return Some(ManualReadResponse {
                manual: self.name().to_string(),
                section: String::new(),
                title: self.page.title.clone(),
                link: section_link(self.admin, ""),
                text,
                subsections: Vec::new(),
                truncated: false,
            });
        }
        let index = self.sections.iter().position(|s| s.slug == slug)?;
        let section = &self.sections[index];
        let raw = &self.source[section.start..section.tree_end];
        let mut text = agent_text(raw, self.admin);
        let truncated = text.chars().count() > MAX_READ_CHARS;
        if truncated {
            text = text.chars().take(MAX_READ_CHARS).collect();
        }
        let subsections = self.sections[index + 1..]
            .iter()
            .take_while(|s| s.start < section.tree_end)
            .map(|s| self.hit(s, String::new()))
            .collect();
        Some(ManualReadResponse {
            manual: self.name().to_string(),
            section: section.slug.clone(),
            title: section.title.clone(),
            link: section_link(self.admin, &section.slug),
            text,
            subsections,
            truncated,
        })
    }
}

/// The sections of a manual, one for each heading, in order. A heading inside a code block
/// is not a heading.
pub fn split_sections(source: &str) -> Vec<Section> {
    let mut slugger = Slugger::default();
    let mut sections: Vec<Section> = Vec::new();
    let mut heading: Option<(u8, usize, String)> = None;
    for (event, range) in Parser::new_ext(source, options()).into_offset_iter() {
        match event {
            Event::Start(Tag::Heading { level, .. }) => heading = Some((level as u8, range.start, String::new())),
            Event::End(TagEnd::Heading(_)) => {
                if let Some((level, start, title)) = heading.take() {
                    let title = title.trim().to_string();
                    let slug = slugger.slug(&title);
                    sections.push(Section {
                        level,
                        plain: title.clone(),
                        title,
                        slug,
                        start,
                        own_end: source.len(),
                        tree_end: source.len(),
                    });
                }
            }
            Event::Text(text) | Event::Code(text) => match heading.as_mut() {
                Some((_, _, title)) => title.push_str(&text),
                None => {
                    if let Some(section) = sections.last_mut() {
                        section.plain.push(' ');
                        section.plain.push_str(&text);
                    }
                }
            },
            Event::SoftBreak | Event::HardBreak => {
                if let Some((_, _, title)) = heading.as_mut() {
                    title.push(' ');
                }
            }
            _ => {}
        }
    }
    for i in 0..sections.len() {
        if let Some(next) = sections.get(i + 1) {
            sections[i].own_end = next.start;
        }
        let level = sections[i].level;
        if let Some(next) = sections[i + 1..].iter().find(|s| s.level <= level) {
            sections[i].tree_end = next.start;
        }
    }
    sections
}

/// The page HTML of a manual. Each heading gets the anchor of its section.
pub fn render_html(source: &str, admin: bool, sections: &[Section]) -> String {
    let mut slugs = sections.iter().map(|s| s.slug.clone());
    let events = Parser::new_ext(source, options()).map(|event| match event {
        Event::Start(Tag::Heading { level, classes, attrs, .. }) => Event::Start(Tag::Heading {
            level,
            id: slugs.next().map(CowStr::from),
            classes,
            attrs,
        }),
        Event::Start(Tag::Link { link_type, dest_url, title, id }) => Event::Start(Tag::Link {
            link_type,
            dest_url: rewrite_href(admin, &dest_url).into(),
            title,
            id,
        }),
        Event::Start(Tag::Image { link_type, dest_url, title, id }) => Event::Start(Tag::Image {
            link_type,
            dest_url: rewrite_href(admin, &dest_url).into(),
            title,
            id,
        }),
        Event::Html(html) => Event::Html(rewrite_html(&html).into()),
        Event::InlineHtml(html) => Event::InlineHtml(rewrite_html(&html).into()),
        other => other,
    });
    let mut out = String::new();
    pulldown_cmark::html::push_html(&mut out, events);
    out
}

/// The target of a link of a manual on the manual page.
///
/// - `#slug` opens the section of the same manual.
/// - `img/…` and `crops/…` go to the asset route.
/// - `User_Manual.md#slug` and `Admin_Manual.md#slug` open the manual pages.
/// - A URL, an absolute path and a `mailto:` link stay as they are.
/// - Any other relative path opens the document in the public repository.
pub fn rewrite_href(admin: bool, href: &str) -> String {
    if let Some(slug) = href.strip_prefix('#') {
        return section_link(admin, slug);
    }
    if ASSET_FOLDERS.iter().any(|folder| href.starts_with(folder)) {
        return format!("{ASSET_PREFIX}{href}");
    }
    if href.contains("://") || href.starts_with('/') || href.starts_with("mailto:") {
        return href.to_string();
    }
    let (path, fragment) = href.split_once('#').unwrap_or((href, ""));
    match path {
        USER_FILE | "./User_Manual.md" => return section_link(false, fragment),
        ADMIN_FILE | "./Admin_Manual.md" => return section_link(true, fragment),
        _ => {}
    }
    let mut parts: Vec<&str> = REPOSITORY_FOLDER.trim_end_matches('/').split('/').collect();
    let root = "https://github.com/liquidinvestigations/hoover4/blob/main".split('/').count();
    for part in path.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                if parts.len() > root {
                    parts.pop();
                }
            }
            other => parts.push(other),
        }
    }
    let mut url = parts.join("/");
    if !fragment.is_empty() {
        url.push('#');
        url.push_str(fragment);
    }
    url
}

/// Raw HTML of a manual with the image paths on the asset route.
pub fn rewrite_html(html: &str) -> String {
    let mut out = html.to_string();
    for attribute in ["src=\"", "href=\""] {
        for folder in ASSET_FOLDERS {
            out = out.replace(&format!("{attribute}{folder}"), &format!("{attribute}{ASSET_PREFIX}{folder}"));
        }
    }
    out
}

/// The Markdown of a section for an agent: each image as `(Image: description)`, the image
/// links removed, and each Markdown link on its page address.
pub fn agent_text(raw: &str, admin: bool) -> String {
    let mut text = String::with_capacity(raw.len());
    let mut rest = raw;
    while let Some(open) = rest.find('<') {
        text.push_str(&rest[..open]);
        let after = &rest[open..];
        let Some(close) = after.find('>') else {
            text.push_str(after);
            rest = "";
            break;
        };
        let tag = &after[..=close];
        let lower = tag.to_ascii_lowercase();
        if lower.starts_with("<img") {
            let alt = attribute(tag, "alt");
            if !alt.is_empty() {
                text.push_str(&format!("(Image: {alt})"));
            }
        } else if !(lower.starts_with("<a ") || lower == "</a>") {
            // Not an image tag: the `<` is text, for example in `<collection>`.
            text.push('<');
            rest = &after[1..];
            continue;
        }
        rest = &after[close + 1..];
    }
    text.push_str(rest);
    // Markdown link targets: `](target)`.
    let mut out = String::with_capacity(text.len());
    let mut rest = text.as_str();
    while let Some(open) = rest.find("](") {
        out.push_str(&rest[..open + 2]);
        let after = &rest[open + 2..];
        match after.find(')') {
            Some(close) => {
                out.push_str(&rewrite_href(admin, &after[..close]));
                out.push(')');
                rest = &after[close + 1..];
            }
            None => rest = after,
        }
    }
    out.push_str(rest);
    // Blank lines that the removed images left.
    let mut collapsed = String::with_capacity(out.len());
    let mut blank = 0;
    for line in out.lines() {
        if line.trim().is_empty() {
            blank += 1;
            if blank > 1 {
                continue;
            }
        } else {
            blank = 0;
        }
        collapsed.push_str(line.trim_end());
        collapsed.push('\n');
    }
    collapsed.trim().to_string()
}

/// The value of a double-quoted attribute of an HTML tag, empty when absent.
fn attribute(tag: &str, name: &str) -> String {
    let key = format!("{name}=\"");
    tag.find(&key)
        .and_then(|start| {
            let value = &tag[start + key.len()..];
            value.find('"').map(|end| value[..end].to_string())
        })
        .unwrap_or_default()
}

/// The words of a search, in lower case: at least two characters, at most twelve words.
fn search_terms(query: &str) -> Vec<String> {
    let mut terms: Vec<String> = Vec::new();
    for word in query.to_lowercase().split(|c: char| !c.is_alphanumeric()) {
        if word.chars().count() >= 2 && !terms.iter().any(|t| t == word) {
            terms.push(word.to_string());
        }
    }
    terms.truncate(12);
    terms
}

/// The sections of `manuals` that hold the words of `query`, the best first. A word in the
/// heading counts more than a word in the text.
pub fn search(manuals: &[&Manual], query: &str) -> Vec<AgentManualSection> {
    let terms = search_terms(query);
    if terms.is_empty() {
        return Vec::new();
    }
    let mut scored: Vec<(u32, &Manual, &Section)> = Vec::new();
    for manual in manuals {
        for section in manual.sections.iter().filter(|s| s.level >= 2) {
            let title = section.title.to_lowercase();
            let plain = section.plain.to_lowercase();
            let mut score = 0;
            let mut found = 0;
            for term in &terms {
                let count = plain.matches(term.as_str()).count() as u32;
                if count > 0 {
                    found += 1;
                }
                score += count.min(5) + if title.contains(term.as_str()) { 10 } else { 0 };
            }
            if score > 0 {
                scored.push((score + 5 * found * found, manual, section));
            }
        }
    }
    scored.sort_by(|a, b| b.0.cmp(&a.0).then(a.2.start.cmp(&b.2.start)));
    scored
        .into_iter()
        .take(MAX_HITS)
        .map(|(_, manual, section)| manual.hit(section, snippet(&section.plain, &terms)))
        .collect()
}

/// About [`SNIPPET_CHARS`] characters of `plain` round the first word of `terms` that it holds.
fn snippet(plain: &str, terms: &[String]) -> String {
    let chars: Vec<char> = plain.split_whitespace().collect::<Vec<_>>().join(" ").chars().collect();
    let lower: Vec<char> = chars.iter().flat_map(|c| c.to_lowercase()).collect();
    // `to_lowercase` can change the length of a character. The position is then approximate.
    let lower_text: String = lower.iter().collect();
    let at = terms
        .iter()
        .filter_map(|t| lower_text.find(t.as_str()).map(|byte| lower_text[..byte].chars().count()))
        .min()
        .unwrap_or(0)
        .min(chars.len());
    let start = at.saturating_sub(SNIPPET_CHARS / 3);
    let end = (start + SNIPPET_CHARS).min(chars.len());
    let mut text: String = chars[start..end].iter().collect();
    if start > 0 {
        text.insert(0, '…');
    }
    if end < chars.len() {
        text.push('…');
    }
    text
}

/// Why a caller does not get a manual.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ManualRefusal {
    /// The administration manual, and the caller is not an administrator.
    NotAdmin,
    /// The manual is not in this installation.
    Missing(String),
}

/// The manual that `user` asks for. Only an administrator gets the administration manual.
pub fn manual_for<'m>(manuals: &'m Manuals, user: &CurrentUser, admin: bool) -> Result<&'m Manual, ManualRefusal> {
    if admin && !user.is_admin {
        return Err(ManualRefusal::NotAdmin);
    }
    let result = if admin { &manuals.admin } else { &manuals.user };
    result.as_ref().map_err(|error| ManualRefusal::Missing(error.clone()))
}

/// The page of a manual. A user who is not an administrator gets "not found" for the
/// administration manual, as for any page that does not exist.
pub async fn manual_page(user: &CurrentUser, admin: bool) -> anyhow::Result<ManualPage> {
    match manual_for(load(), user, admin) {
        Ok(manual) => Ok(manual.page.clone()),
        Err(ManualRefusal::NotAdmin) => anyhow::bail!("manual {}", guard::NOT_FOUND),
        Err(ManualRefusal::Missing(error)) => {
            tracing::error!("manual page: {error}");
            anyhow::bail!("This installation has no manual. The image build copies docs/user-manual.")
        }
    }
}

/// The file of an asset request, or `None` for a path outside the asset folders.
pub fn asset_path(dir: &Path, path: &str) -> Option<PathBuf> {
    let valid = ASSET_FOLDERS.iter().any(|folder| path.starts_with(folder))
        && path.split('/').all(|part| !part.is_empty() && part != "." && part != "..")
        && path.chars().all(|c| c.is_alphanumeric() || "-_./".contains(c));
    valid.then(|| dir.join(path))
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = "# Hoover: user manual\n\nIntro text.\n\n## Contents\n\n- [Search](#4-search)\n\n\
## 4. Search\n\nType a query.\n\n<a href=\"img/search.png\"><img src=\"img/search.png\" alt=\"Search results\" width=\"100%\"></a>\n\n\
```\n## not a heading\n```\n\n### What you can type\n\nUse `AND` and quotes.\n\n### Entities\n\nNames.\n\n\
## 5. Filters\n\nSee the [administration manual](Admin_Manual.md#datasets) and [backups](../operations/Backup_And_Restore.md).\n\n\
### Entities\n\nMore names.\n";

    #[test]
    fn a_manual_splits_at_headings_with_github_anchors() {
        let sections = split_sections(SAMPLE);
        let slugs: Vec<&str> = sections.iter().map(|s| s.slug.as_str()).collect();
        assert_eq!(slugs, vec!["hoover-user-manual", "contents", "4-search", "what-you-can-type", "entities", "5-filters", "entities-1"]);
        let search = &sections[2];
        assert_eq!((search.level, search.title.as_str()), (2, "4. Search"));
        // The section ends at the next heading of the same level, after its subsections.
        assert!(SAMPLE[search.start..search.tree_end].contains("### Entities\n\nNames."));
        assert!(!SAMPLE[search.start..search.tree_end].contains("## 5. Filters"));
        assert!(SAMPLE[search.start..search.own_end].contains("## not a heading"));
        assert!(!SAMPLE[search.start..search.own_end].contains("What you can type"));
        assert!(sections[3].plain.contains("AND"));
    }

    #[test]
    fn the_html_has_anchors_and_asset_paths() {
        let manual = Manual::parse(SAMPLE.to_string(), false);
        let html = &manual.page.html;
        assert!(html.contains("<h2 id=\"4-search\">4. Search</h2>"), "{html}");
        assert!(html.contains("<h3 id=\"entities-1\">Entities</h3>"));
        assert!(html.contains("<a href=\"/_manual/img/search.png\"><img src=\"/_manual/img/search.png\""));
        assert!(html.contains("href=\"/docs#4-search\""));
        assert!(html.contains("href=\"/docs/admin#datasets\""));
        assert!(html.contains("href=\"https://github.com/liquidinvestigations/hoover4/blob/main/docs/operations/Backup_And_Restore.md\""));
        assert_eq!(manual.page.title, "Hoover: user manual");
        assert_eq!(manual.page.headings.iter().map(|h| h.slug.as_str()).collect::<Vec<_>>(),
                   vec!["contents", "4-search", "what-you-can-type", "entities", "5-filters", "entities-1"]);
    }

    #[test]
    fn image_paths_and_links_are_rewritten() {
        assert_eq!(rewrite_href(false, "crops/a-b.png"), "/_manual/crops/a-b.png");
        assert_eq!(rewrite_href(true, "#users-and-groups"), "/docs/admin#users-and-groups");
        assert_eq!(rewrite_href(true, "User_Manual.md"), "/docs");
        assert_eq!(rewrite_href(false, "https://example.org/x"), "https://example.org/x");
        assert_eq!(
            rewrite_href(true, "../../main_services/processing/tasks/P_ops/Readme.md"),
            "https://github.com/liquidinvestigations/hoover4/blob/main/main_services/processing/tasks/P_ops/Readme.md"
        );
        assert_eq!(rewrite_html("<img src=\"img/a.png\"> <a href=\"crops/b.png\">"),
                   "<img src=\"/_manual/img/a.png\"> <a href=\"/_manual/crops/b.png\">");
    }

    #[test]
    fn an_agent_reads_a_section_with_page_links_and_image_descriptions() {
        let manual = Manual::parse(SAMPLE.to_string(), false);
        let read = manual.read("4-search").unwrap();
        assert_eq!(read.link, "/docs#4-search");
        assert!(read.text.starts_with("## 4. Search"));
        assert!(read.text.contains("(Image: Search results)"));
        assert!(!read.text.contains("<img"));
        assert!(!read.text.contains("<a "));
        assert_eq!(read.subsections.iter().map(|s| s.link.as_str()).collect::<Vec<_>>(),
                   vec!["/docs#what-you-can-type", "/docs#entities"]);
        let filters = manual.read("5-filters").unwrap();
        assert!(filters.text.contains("[administration manual](/docs/admin#datasets)"));
        assert!(manual.read("missing").is_none());
        let contents = manual.read("").unwrap();
        assert!(contents.text.contains("- [4. Search](/docs#4-search)\n  - [What you can type](/docs#what-you-can-type)"));
    }

    #[test]
    fn a_search_finds_the_section_with_the_words() {
        let manual = Manual::parse(SAMPLE.to_string(), false);
        let hits = search(&[&manual], "how to type quotes");
        assert_eq!(hits[0].section, "what-you-can-type");
        assert_eq!(hits[0].link, "/docs#what-you-can-type");
        assert!(search(&[&manual], "x").is_empty());
    }

    #[test]
    fn only_an_administrator_gets_the_administration_manual() {
        let manuals = Manuals {
            user: Ok(Manual::parse(SAMPLE.to_string(), false)),
            admin: Ok(Manual::parse("# Admin\n\n## Datasets\n\nText.\n".to_string(), true)),
            dir: PathBuf::from("/x"),
        };
        let person = |admin: bool| CurrentUser {
            username: "u".into(), fullname: String::new(), email: String::new(), is_admin: admin, groups: vec![],
        };
        assert!(manual_for(&manuals, &person(false), false).is_ok());
        assert_eq!(manual_for(&manuals, &person(false), true).err(), Some(ManualRefusal::NotAdmin));
        assert_eq!(manual_for(&manuals, &person(true), true).unwrap().read("datasets").unwrap().link, "/docs/admin#datasets");
    }

    #[test]
    fn the_asset_route_serves_only_the_image_folders() {
        let dir = Path::new("/m");
        assert_eq!(asset_path(dir, "img/home.png"), Some(PathBuf::from("/m/img/home.png")));
        assert_eq!(asset_path(dir, "crops/a_b-1.png"), Some(PathBuf::from("/m/crops/a_b-1.png")));
        assert_eq!(asset_path(dir, "img/../User_Manual.md"), None);
        assert_eq!(asset_path(dir, "User_Manual.md"), None);
        assert_eq!(asset_path(dir, "img//a.png"), None);
        assert_eq!(asset_path(dir, "img/a b.png"), None);
    }

    /// Every in-page link of the repository manuals names an anchor of the splitter.
    #[test]
    fn the_repository_manuals_link_to_existing_anchors() {
        let dir = [
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../docs/user-manual"),
            PathBuf::from("/repo/docs/user-manual"),
        ]
        .into_iter()
        .find(|dir| dir.join(USER_FILE).exists());
        let Some(dir) = dir else {
            eprintln!("docs/user-manual is not mounted here, so the check is skipped");
            return;
        };
        for (file, admin) in [(USER_FILE, false), (ADMIN_FILE, true)] {
            let manual = Manual::parse(std::fs::read_to_string(dir.join(file)).unwrap(), admin);
            let slugs: Vec<&str> = manual.sections.iter().map(|s| s.slug.as_str()).collect();
            assert!(slugs.contains(&if admin { "dashboard" } else { "4-search" }), "{slugs:?}");
            for (start, _) in manual.source.match_indices("](#") {
                let rest = &manual.source[start + 3..];
                let anchor = &rest[..rest.find(')').unwrap()];
                assert!(slugs.contains(&anchor), "{file}: #{anchor} names no section");
            }
        }
    }
}
