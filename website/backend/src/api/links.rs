//! The references of a text that a person sends to a model (`common::links`).
//!
//! A pasted link becomes a reference only when the person can read its item. The read rule
//! is the rule of the page that the link opens: the dataset permission for a search, a
//! document, a folder and an email graph, the collection permission for a collection page,
//! and the group rule of `auth::item_access` for a chat and a board. An item that the person
//! cannot read and an item that does not exist give the same error, so the error does not
//! show that an item exists.
//!
//! The chat send and the board commands resolve every reference again from its `url`, so
//! a request body cannot set the label, the tool or the arguments of a reference.

use std::collections::{HashMap, HashSet};

use common::current_user::CurrentUser;
use common::links::{
    marked_parts, marker, parse_link, ChatReference, HooverLink, LinkHost, MarkedPart, RichText,
};

use crate::api::{list_datasets, vfs};

/// The most references in one text.
pub const MAX_REFERENCES: usize = 20;

/// The error of an item that the person cannot read or that does not exist.
const NOT_READABLE: &str = "the link names an item that you cannot read, or that does not exist";

/// The collections and datasets that one person can read, for the checks of a batch.
pub struct LinkReader {
    collection_of: HashMap<String, String>,
    collections: HashMap<String, String>,
}

impl LinkReader {
    /// The readable collections of `user`. `only` limits them to the names it holds, as
    /// the collections of a chat limit the agent routes.
    pub async fn new(user: &CurrentUser, only: Option<&HashSet<String>>) -> anyhow::Result<Self> {
        let tree = list_datasets::list_permitted_collection_tree(user).await?;
        let mut collection_of = HashMap::new();
        let mut collections = HashMap::new();
        for node in tree {
            if only.is_some_and(|names| !names.contains(&node.collectionname)) {
                continue;
            }
            for dataset in &node.datasets {
                collection_of.insert(dataset.collection_dataset.clone(), node.collectionname.clone());
            }
            let label = node.display_name.clone().filter(|name| !name.is_empty()).unwrap_or_else(|| node.collectionname.clone());
            collections.insert(node.collectionname, label);
        }
        Ok(Self { collection_of, collections })
    }

    fn collection_of(&self, dataset: &str) -> Option<String> {
        self.collection_of.get(dataset).cloned()
    }

    /// The reference of one link, without a handle, or the reason that it is not one.
    pub async fn resolve(&self, user: &CurrentUser, url: &str) -> Result<ChatReference, String> {
        let link = parse_link(url, LinkHost::Any).map_err(|error| error.to_string())?;
        let label = self.label(user, &link).await.ok_or_else(|| NOT_READABLE.to_string())?;
        let call = link.tool_call(&|dataset| self.collection_of(dataset)).ok_or_else(|| NOT_READABLE.to_string())?;
        Ok(ChatReference {
            handle: String::new(),
            kind: link.kind().to_string(),
            label,
            tool: call.tool,
            arguments: call.arguments,
            note: call.note,
            url: path_of(url),
            link,
        })
    }

    /// The label of an item that `user` can read, or `None`.
    async fn label(&self, user: &CurrentUser, link: &HooverLink) -> Option<String> {
        match link {
            HooverLink::Search { query, .. } => {
                let datasets = query.collection_datasets.iter().cloned().chain(
                    query.facet_filters.get("collection_dataset").into_iter().flatten().map(|value| match value {
                        common::search_result::FacetOriginalValue::String(name) => name.clone(),
                        common::search_result::FacetOriginalValue::Int(id) => id.to_string(),
                    }),
                );
                for dataset in datasets {
                    self.collection_of(&dataset)?;
                }
                Some(query.query_string.trim().to_string())
            }
            HooverLink::Document { document } => self.file_name(user, document).await,
            HooverLink::EmailGraph { centre } => self.file_name(user, centre).await,
            HooverLink::Storage { q } => Some(q.trim().to_string()),
            HooverLink::Collection { collectionname, .. } => self.collections.get(collectionname).cloned(),
            HooverLink::Folder { collection_dataset, path, .. } => {
                self.collection_of(collection_dataset)?;
                Some(path.path.clone())
            }
            HooverLink::Chat { session_id } => {
                super::chat::readable_session(user, session_id).await.ok().map(|row| row.title)
            }
            HooverLink::Board { board_id, .. } => {
                super::boards::readable_board_title(user, board_id).await.ok()
            }
        }
    }

    async fn file_name(&self, user: &CurrentUser, document: &common::search_result::DocumentIdentifier) -> Option<String> {
        self.collection_of(&document.collection_dataset)?;
        let path = vfs::get_first_vfs_path(user, document.clone()).await.ok()?;
        let name = path.path.rsplit('/').find(|part| !part.is_empty()).unwrap_or(&path.path);
        Some(name.to_string())
    }
}

/// The path, query and fragment of a link, which opens the item on this deployment.
fn path_of(url: &str) -> String {
    let url = url.trim();
    if url.starts_with('/') {
        return url.to_string();
    }
    let rest = url.split_once("://").map_or(url, |(_, rest)| rest);
    match rest.find(['/', '?', '#']) {
        Some(index) => rest[index..].to_string(),
        None => "/".to_string(),
    }
}

/// The reference of each link, or the reason that it is not one, in request order.
pub async fn resolve_references(user: &CurrentUser, urls: Vec<String>) -> anyhow::Result<Vec<Result<ChatReference, String>>> {
    if urls.len() > MAX_REFERENCES {
        anyhow::bail!("Send at most {MAX_REFERENCES} links at once.");
    }
    let reader = LinkReader::new(user, None).await?;
    let mut out = Vec::with_capacity(urls.len());
    for url in urls {
        out.push(reader.resolve(user, &url).await);
    }
    Ok(out)
}

/// `rich` with every reference resolved again from its `url` and numbered from `[R1]` in
/// text order. The marker of a reference that does not resolve becomes its link text, and a
/// reference without a marker is dropped.
pub async fn resolve_rich_text(user: &CurrentUser, rich: &RichText) -> anyhow::Result<RichText> {
    let rich = rich.trimmed();
    if rich.references.is_empty() {
        return Ok(rich);
    }
    if rich.references.len() > MAX_REFERENCES {
        anyhow::bail!("A text holds at most {MAX_REFERENCES} links.");
    }
    let reader = LinkReader::new(user, None).await?;
    let mut resolved: HashMap<String, Result<ChatReference, String>> = HashMap::new();
    for reference in &rich.references {
        resolved.insert(reference.handle.clone(), reader.resolve(user, &reference.url).await);
    }
    let mut text = String::new();
    let mut references: Vec<ChatReference> = Vec::new();
    let mut numbers: HashMap<String, usize> = HashMap::new();
    for part in marked_parts(&rich.text) {
        match part {
            MarkedPart::Text(plain) => text.push_str(&plain),
            MarkedPart::Reference(n) => {
                let handle = marker(n);
                match (resolved.get(&handle), rich.reference(n)) {
                    (Some(Ok(reference)), _) => {
                        let next = references.len() + 1;
                        let number = *numbers.entry(handle).or_insert(next);
                        if number == next {
                            references.push(ChatReference { handle: marker(number), ..reference.clone() });
                        }
                        text.push_str(&marker(number));
                    }
                    (_, Some(original)) => text.push_str(&original.url),
                    _ => text.push_str(&handle),
                }
            }
        }
    }
    Ok(RichText { text, references })
}

#[cfg(test)]
mod tests {
    use super::path_of;

    #[test]
    fn the_path_of_a_link_drops_the_origin() {
        assert_eq!(path_of("https://hoover.example.org/ai_chat/boards/b1?selected=x"), "/ai_chat/boards/b1?selected=x");
        assert_eq!(path_of("/file_browser"), "/file_browser");
        assert_eq!(path_of("https://hoover.example.org"), "/");
    }
}
