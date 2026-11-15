//! The Hoover addresses that a person can paste, and the references that the chat and the
//! boards build from them.
//!
//! [`parse_link`] decodes every address of the frontend `Route` that names an item: a
//! search, a document, the storage pages, a folder, an email graph, a chat and a board. It
//! reads only the segments that name the item and skips the viewer segments, so the
//! frontend viewer types stay in the frontend. A segment that does not decode is an error,
//! and the caller then keeps the text as text.
//!
//! [`HooverLink::tool_call`] gives the agent tool and the arguments that read the item.
//!
//! A reference ([`ChatReference`]) is a resolved link in a text that a person sends to a
//! model. The text holds the marker `[Rn]` at the place of the reference, and
//! [`RichText`] carries the text and its references. A citation is different: the agent
//! writes it, as `[Dn]` or `[Wn]`.

use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};

use crate::agent_api::SEARCH_FACETS;
use crate::search_query::{SearchQuery, SortKey, SortSpec};
use crate::search_result::{DocumentIdentifier, FacetOriginalValue};
use crate::url_param::UrlParam;
use crate::vfs::{make_node_key, PathDescriptor};

/// One item that a Hoover address names.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum HooverLink {
    /// `/search/:query/:page/:selected/:viewer`. `selected` is the document of the preview.
    Search { query: SearchQuery, selected: Option<DocumentIdentifier> },
    /// `/view_document/:document/:viewer/:tab`.
    Document { document: DocumentIdentifier },
    /// `/file_browser?q&page`, the storage page of every collection.
    Storage { q: String },
    /// `/file_browser/c/:collectionname?q&page`.
    Collection { collectionname: String, q: String },
    /// `/file_browser/:collection_dataset/:path/:selected/:viewer`.
    Folder { collection_dataset: String, path: PathDescriptor, selected: Option<DocumentIdentifier> },
    /// `/email_graph/:centre/:selected/:viewer`.
    EmailGraph { centre: DocumentIdentifier },
    /// `/ai_chat/c/:session_id/:selected/:viewer`.
    Chat { session_id: String },
    /// `/ai_chat/boards/:board_id?selected`. `node` is the slug or the id of the selected
    /// node, empty for none.
    Board { board_id: String, node: String },
}

impl HooverLink {
    /// The kind name, as the `kind` tag of the JSON form.
    pub fn kind(&self) -> &'static str {
        match self {
            HooverLink::Search { .. } => "search",
            HooverLink::Document { .. } => "document",
            HooverLink::Storage { .. } => "storage",
            HooverLink::Collection { .. } => "collection",
            HooverLink::Folder { .. } => "folder",
            HooverLink::EmailGraph { .. } => "email_graph",
            HooverLink::Chat { .. } => "chat",
            HooverLink::Board { .. } => "board",
        }
    }

    /// The tool call that reads the item, or `None` when a dataset of the link has no
    /// collection in `collection_of`. `collection_of` gives the collection of a dataset
    /// that the caller can read, so `None` also means that the caller cannot read it.
    pub fn tool_call(&self, collection_of: &dyn Fn(&str) -> Option<String>) -> Option<ToolCall> {
        let call = |tool: &str, arguments: serde_json::Value| ToolCall {
            tool: tool.to_string(),
            arguments,
            note: String::new(),
        };
        match self {
            HooverLink::Search { query, .. } => search_tool_call(query, collection_of),
            HooverLink::Document { document } => Some(call("read_documents", serde_json::json!({
                "collection": collection_of(&document.collection_dataset)?,
                "file_hash": [document.file_hash],
            }))),
            HooverLink::Storage { .. } => Some(call("list_collections", serde_json::json!({}))),
            HooverLink::Collection { collectionname, .. } => {
                Some(call("folder_overview", serde_json::json!({"collection": collectionname})))
            }
            HooverLink::Folder { collection_dataset, path, .. } => Some(call("folder_list", serde_json::json!({
                "collection": collection_of(collection_dataset)?,
                "dataset": collection_dataset,
                "node_id": make_node_key(collection_dataset, &path.container_hash, &path.path),
            }))),
            HooverLink::EmailGraph { centre } => Some(call("doc_email", serde_json::json!({
                "collection": collection_of(&centre.collection_dataset)?,
                "file_hash": centre.file_hash,
            }))),
            HooverLink::Chat { session_id } => Some(call("read_chat", serde_json::json!({"session_id": session_id}))),
            HooverLink::Board { board_id, node } => {
                let mut arguments = serde_json::json!({"board_id": board_id});
                if !node.is_empty() {
                    arguments["node"] = serde_json::Value::String(node.clone());
                }
                Some(call("read_board", arguments))
            }
        }
    }
}

/// The agent tool and the arguments that read one item. `note` names the parts of the
/// address that the arguments cannot express, empty when there is none.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ToolCall {
    pub tool: String,
    pub arguments: serde_json::Value,
    #[serde(default)]
    pub note: String,
}

/// Why a text is not a Hoover address.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LinkError {
    /// The text is not a URL or a path.
    NotALink,
    /// The URL names another host than the deployment.
    OtherHost,
    /// The path names no item, for example `/admin`.
    UnknownAddress,
    /// The path names an item but has fewer or more segments than its address.
    Incomplete,
    /// One segment does not decode. The value names the segment.
    BadSegment(&'static str),
}

impl std::fmt::Display for LinkError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LinkError::NotALink => write!(f, "the text is not a URL or a path"), // i18n: data, an agent tool result
            LinkError::OtherHost => write!(f, "the link names another host"), // i18n: data, an agent tool result
            LinkError::UnknownAddress => write!(f, "the link names no Hoover item"), // i18n: data, an agent tool result
            LinkError::Incomplete => write!(f, "the link is incomplete"), // i18n: data, an agent tool result
            LinkError::BadSegment(name) => write!(f, "the {name} part of the link does not decode"), // i18n: data, an agent tool result
        }
    }
}

/// The hosts that [`parse_link`] accepts.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LinkHost<'a> {
    /// A path, or a URL of this origin, such as `https://hoover.example.org`.
    Own(&'a str),
    /// A path, or a URL of any host. The agent route uses it, because the website does not
    /// know the address that the person used.
    Any,
}

/// Decode `%XX` escapes. `None` for a bad escape or for bytes that are not UTF-8.
fn percent_decode(text: &str) -> Option<String> {
    let bytes = text.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' {
            let hex = text.get(i + 1..i + 3)?;
            out.push(u8::from_str_radix(hex, 16).ok()?);
            i += 3;
        } else {
            out.push(bytes[i]);
            i += 1;
        }
    }
    String::from_utf8(out).ok()
}

/// The path, query and fragment of `text`, after the origin check of `host`.
fn path_part<'t>(text: &'t str, host: LinkHost) -> Result<&'t str, LinkError> {
    if text.starts_with("//") {
        return Err(LinkError::NotALink);
    }
    if text.starts_with('/') {
        return Ok(text);
    }
    let lower = text.to_ascii_lowercase();
    let scheme_end = if lower.starts_with("https://") {
        8
    } else if lower.starts_with("http://") {
        7
    } else {
        return Err(LinkError::NotALink);
    };
    let rest = &text[scheme_end..];
    let authority_end = rest.find(['/', '?', '#']).unwrap_or(rest.len());
    if authority_end == 0 {
        return Err(LinkError::NotALink);
    }
    if let LinkHost::Own(origin) = host {
        let origin = origin.trim_end_matches('/');
        if !text[..scheme_end + authority_end].eq_ignore_ascii_case(origin) {
            return Err(LinkError::OtherHost);
        }
    }
    let path = &rest[authority_end..];
    Ok(if path.is_empty() { "/" } else { path })
}

fn decode_param<T: for<'de> Deserialize<'de>>(segment: &str, name: &'static str) -> Result<T, LinkError> {
    segment.parse::<UrlParam<T>>().map(|param| param.0).map_err(|_| LinkError::BadSegment(name))
}

/// The value of `name` in a query string that the router wrote, empty when absent.
fn query_value(query: &str, name: &str) -> String {
    query
        .split('&')
        .filter_map(|pair| pair.split_once('='))
        .find(|(key, _)| *key == name)
        .map(|(_, value)| value.to_string())
        .unwrap_or_default()
}

/// Decode one Hoover address. `text` is a path, such as `/view_document/...`, or a URL.
pub fn parse_link(text: &str, host: LinkHost) -> Result<HooverLink, LinkError> {
    let text = text.trim();
    if text.is_empty() || text.chars().any(char::is_whitespace) {
        return Err(LinkError::NotALink);
    }
    let path = path_part(text, host)?;
    let path = path.split_once('#').map_or(path, |(before, _)| before);
    let (path, query) = path.split_once('?').unwrap_or((path, ""));
    let query = percent_decode(query).ok_or(LinkError::BadSegment("query"))?;
    let path = path.strip_suffix('/').unwrap_or(path);
    let mut segments = Vec::new();
    for raw in path.split('/').skip(1) {
        segments.push(percent_decode(raw).ok_or(LinkError::BadSegment("path"))?);
    }
    let parts: Vec<&str> = segments.iter().map(String::as_str).collect();
    let nonempty = |value: &str, name: &'static str| {
        if value.is_empty() { Err(LinkError::BadSegment(name)) } else { Ok(value.to_string()) }
    };
    match parts.as_slice() {
        ["search", query_segment, page, selected, _viewer] => {
            page.parse::<u64>().map_err(|_| LinkError::BadSegment("page"))?;
            Ok(HooverLink::Search {
                query: decode_param(query_segment, "query")?,
                selected: decode_param(selected, "selected")?,
            })
        }
        ["search", ..] => Err(LinkError::Incomplete),
        ["view_document", document, _viewer, _tab] => {
            Ok(HooverLink::Document { document: decode_param(document, "document")? })
        }
        ["view_document", ..] => Err(LinkError::Incomplete),
        ["file_browser"] => Ok(HooverLink::Storage { q: query_value(&query, "q") }),
        ["file_browser", "c", name] => Ok(HooverLink::Collection {
            collectionname: nonempty(name, "collection")?,
            q: query_value(&query, "q"),
        }),
        ["file_browser", dataset, folder, selected, _viewer] => Ok(HooverLink::Folder {
            collection_dataset: nonempty(dataset, "dataset")?,
            path: decode_param(folder, "path")?,
            selected: decode_param(selected, "selected")?,
        }),
        ["file_browser", ..] => Err(LinkError::Incomplete),
        ["email_graph", centre, _selected, _viewer] => {
            Ok(HooverLink::EmailGraph { centre: decode_param(centre, "centre")? })
        }
        ["email_graph", ..] => Err(LinkError::Incomplete),
        ["ai_chat", "c", session_id, _selected, _viewer] => {
            Ok(HooverLink::Chat { session_id: nonempty(session_id, "chat")? })
        }
        ["ai_chat", "boards", "new"] => Err(LinkError::UnknownAddress),
        ["ai_chat", "boards", board_id] => Ok(HooverLink::Board {
            board_id: nonempty(board_id, "board")?,
            node: query_value(&query, "selected"),
        }),
        ["ai_chat", "c", ..] | ["ai_chat", "boards", ..] => Err(LinkError::Incomplete),
        _ => Err(LinkError::UnknownAddress),
    }
}

/// The byte range and the item of each Hoover address in `text`. A word is a candidate
/// when it starts with `/`, `http://` or `https://`. Brackets and punctuation round it do
/// not belong to it.
pub fn find_links(text: &str, host: LinkHost) -> Vec<(std::ops::Range<usize>, HooverLink)> {
    const LEADING: &[char] = &['(', '<', '[', '"', '\''];
    const TRAILING: &[char] = &['.', ',', ';', ':', '!', '?', ')', ']', '>', '"', '\''];
    let mut out = Vec::new();
    let mut offset = 0;
    for word in text.split_inclusive(char::is_whitespace) {
        let start = offset;
        offset += word.len();
        let trimmed_end = word.trim_end();
        let lead = trimmed_end.len() - trimmed_end.trim_start_matches(LEADING).len();
        let candidate = trimmed_end[lead..].trim_end_matches(TRAILING);
        let lower = candidate.to_ascii_lowercase();
        if !(candidate.starts_with('/') || lower.starts_with("http://") || lower.starts_with("https://")) {
            continue;
        }
        if let Ok(link) = parse_link(candidate, host) {
            let begin = start + lead;
            out.push((begin..begin + candidate.len(), link));
        }
    }
    out
}

/// The `search_collections` arguments of a search address.
///
/// The search page stores facet values as term ids, and `search_collections` accepts a
/// term id as a decimal string in `facet_filters`. The datasets of the page become the
/// `collection_dataset` facet and the collections that hold them. A facet or a range that
/// the tool has no argument for is named in the note.
fn search_tool_call(query: &SearchQuery, collection_of: &dyn Fn(&str) -> Option<String>) -> Option<ToolCall> {
    let mut arguments = serde_json::Map::new();
    let mut unsupported: Vec<String> = Vec::new();
    let mut datasets: BTreeSet<String> = query.collection_datasets.iter().cloned().collect();
    if let Some(values) = query.facet_filters.get("collection_dataset") {
        for value in values {
            match value {
                FacetOriginalValue::String(name) => datasets.insert(name.clone()),
                FacetOriginalValue::Int(id) => datasets.insert(id.to_string()),
            };
        }
    }
    if !datasets.is_empty() {
        let mut collections = BTreeSet::new();
        for dataset in &datasets {
            collections.insert(collection_of(dataset)?);
        }
        arguments.insert("collection".into(), serde_json::json!(collections));
    }
    arguments.insert("query".into(), serde_json::Value::String(query.query_string.clone()));
    let sort = query.sort.normalized();
    if sort != SortSpec::default() {
        let field = match sort.key {
            SortKey::Relevance => "relevance",
            SortKey::Date => "date",
            SortKey::FileSize => "file_size",
            SortKey::Name => "name",
        };
        arguments.insert("sort".into(), serde_json::json!({
            "field": field,
            "direction": if sort.desc { "desc" } else { "asc" },
        }));
    }
    let mut facets = serde_json::Map::new();
    if !datasets.is_empty() {
        facets.insert("collection_dataset".into(), serde_json::json!(datasets));
    }
    for (name, values) in &query.facet_filters {
        if name == "collection_dataset" || values.is_empty() {
            continue;
        }
        if name == "extracted_by" && values.iter().all(|v| *v == FacetOriginalValue::String(FILENAME_EXTRACTED_BY.into())) {
            arguments.insert("filename_only".into(), serde_json::Value::Bool(true));
            continue;
        }
        if !SEARCH_FACETS.iter().any(|(facet, _)| facet == name) {
            unsupported.push(name.clone());
            continue;
        }
        let values: Vec<String> = values
            .iter()
            .map(|value| match value {
                FacetOriginalValue::Int(id) => id.to_string(),
                FacetOriginalValue::String(text) => text.clone(),
            })
            .collect();
        facets.insert(name.clone(), serde_json::json!(values));
    }
    if !facets.is_empty() {
        arguments.insert("facet_filters".into(), serde_json::Value::Object(facets));
    }
    for (name, range) in query.active_range_filters() {
        let (low, high, unknown) = match name.as_str() {
            "dates" => ("date_after", "date_before", Some("date_unknown_only")),
            "mentioned_dates" => ("mentioned_date_after", "mentioned_date_before", None),
            "file_size_bytes" => ("size_min", "size_max", None),
            _ => {
                unsupported.push(name.clone());
                continue;
            }
        };
        if let Some(min) = range.min {
            arguments.insert(low.into(), serde_json::json!(min));
        }
        if let Some(max) = range.max {
            arguments.insert(high.into(), serde_json::json!(max));
        }
        if range.include_unknown {
            match unknown {
                Some(key) => {
                    arguments.insert(key.into(), serde_json::Value::Bool(true));
                }
                None => unsupported.push(format!("{name} unknown")),
            }
        }
    }
    let note = if unsupported.is_empty() {
        String::new()
    } else {
        format!("The search page also filters by {}, and the tool has no argument for it.", unsupported.join(", "))
    };
    Some(ToolCall { tool: "search_collections".into(), arguments: serde_json::Value::Object(arguments), note })
}

/// The `extracted_by` value of the file name rows of the index. The search page sets the
/// facet `extracted_by` to it for a search of file names only. **Mirrors
/// `FILENAME_INDEX_EXTRACTED_BY` in `backend/src/api/search/search_sql.rs`.**
pub const FILENAME_EXTRACTED_BY: &str = "filename_index";

/// A resolved link in a text that a person sends to a model.
///
/// The backend builds it after it checks that the person can read the item. `handle` is
/// the marker of the reference in its text, `[R1]` for the first. `url` is the path that
/// opens the item. `label` names the item: the search text, the file name, the folder path,
/// the collection name, or the title of the chat or the board.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ChatReference {
    #[serde(default)]
    pub handle: String,
    pub link: HooverLink,
    pub label: String,
    pub kind: String,
    pub tool: String,
    pub arguments: serde_json::Value,
    pub url: String,
    /// The parts of the link that the tool call cannot express, empty when none.
    #[serde(default)]
    pub note: String,
}

/// The marker of reference `n`: `[R1]` for 1.
pub fn marker(n: usize) -> String {
    format!("[R{n}]")
}

/// The number of a marker: 1 for `[R1]`, `None` for another text.
pub fn marker_number(handle: &str) -> Option<usize> {
    handle.strip_prefix("[R")?.strip_suffix(']')?.parse().ok().filter(|n| *n > 0)
}

/// One part of a text with reference markers.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MarkedPart {
    Text(String),
    /// The number of a marker `[Rn]`.
    Reference(usize),
}

/// The text and marker parts of `text`. Only `[R` with digits and `]` is a marker.
pub fn marked_parts(text: &str) -> Vec<MarkedPart> {
    let mut parts = Vec::new();
    let mut plain = String::new();
    let mut rest = text;
    while let Some(start) = rest.find("[R") {
        let after = &rest[start + 2..];
        let digits = after.chars().take_while(char::is_ascii_digit).count();
        let number = (digits > 0 && after[digits..].starts_with(']'))
            .then(|| after[..digits].parse::<usize>().ok())
            .flatten()
            .filter(|n| *n > 0);
        match number {
            Some(n) => {
                plain.push_str(&rest[..start]);
                if !plain.is_empty() {
                    parts.push(MarkedPart::Text(std::mem::take(&mut plain)));
                }
                parts.push(MarkedPart::Reference(n));
                rest = &after[digits + 1..];
            }
            None => {
                plain.push_str(&rest[..start + 2]);
                rest = after;
            }
        }
    }
    plain.push_str(rest);
    if !plain.is_empty() {
        parts.push(MarkedPart::Text(plain));
    }
    parts
}

/// A text that a person sends to a model, with the references of its markers.
///
/// It decodes from a JSON string as a text without references, so a request body or a
/// stored board command written before references keeps its meaning.
#[derive(Debug, Clone, PartialEq, Default, Serialize)]
pub struct RichText {
    pub text: String,
    pub references: Vec<ChatReference>,
}

impl<'de> Deserialize<'de> for RichText {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        #[derive(Deserialize)]
        struct Fields {
            #[serde(default)]
            text: String,
            #[serde(default)]
            references: Vec<ChatReference>,
        }
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Form {
            Plain(String),
            Rich(Fields),
        }
        Ok(match Form::deserialize(deserializer)? {
            Form::Plain(text) => RichText { text, references: Vec::new() },
            Form::Rich(fields) => RichText { text: fields.text, references: fields.references },
        })
    }
}

impl RichText {
    /// A text without references.
    pub fn plain(text: impl Into<String>) -> Self {
        Self { text: text.into(), references: Vec::new() }
    }

    /// True when the text has no character other than white space.
    pub fn is_blank(&self) -> bool {
        self.text.trim().is_empty()
    }

    /// The reference of marker `n`.
    pub fn reference(&self, n: usize) -> Option<&ChatReference> {
        self.references.iter().find(|r| r.handle == marker(n))
    }

    /// The text with white space removed at both ends, and only the references that a
    /// marker of the text names, in marker order. A marker without a reference stays text.
    pub fn trimmed(&self) -> Self {
        let text = self.text.trim().to_string();
        let mut references = Vec::new();
        for part in marked_parts(&text) {
            if let MarkedPart::Reference(n) = part {
                if let Some(reference) = self.reference(n) {
                    if !references.iter().any(|r: &ChatReference| r.handle == reference.handle) {
                        references.push(reference.clone());
                    }
                }
            }
        }
        Self { text, references }
    }

    /// The text and the references with the number of each marker that has a reference
    /// raised by `offset`, so the first reference becomes `[R{offset + 1}]`. A marker
    /// without a reference is text, and it stays as it is.
    pub fn shifted(&self, offset: usize) -> Self {
        let shift = |n: usize| marker(n + offset);
        let text = marked_parts(&self.text)
            .into_iter()
            .map(|part| match part {
                MarkedPart::Text(text) => text,
                MarkedPart::Reference(n) if self.reference(n).is_some() => shift(n),
                MarkedPart::Reference(n) => marker(n),
            })
            .collect();
        let references = self
            .references
            .iter()
            .map(|r| ChatReference { handle: marker_number(&r.handle).map(shift).unwrap_or_default(), ..r.clone() })
            .collect();
        Self { text, references }
    }

    /// The text with each marker that has a reference replaced by its label, for a title
    /// or another place that shows no chip.
    pub fn display_text(&self) -> String {
        marked_parts(&self.text)
            .into_iter()
            .map(|part| match part {
                MarkedPart::Text(text) => text,
                MarkedPart::Reference(n) => match self.reference(n) {
                    Some(reference) if !reference.label.is_empty() => reference.label.clone(),
                    Some(reference) => reference.url.clone(),
                    None => marker(n),
                },
            })
            .collect()
    }

    /// The JSON array of the references, as the `references_json` columns store it. Empty
    /// for none.
    pub fn references_json(&self) -> String {
        if self.references.is_empty() {
            String::new()
        } else {
            serde_json::to_string(&self.references).unwrap_or_default()
        }
    }
}

/// The references of a `references_json` column. Empty for an empty or a bad value.
pub fn references_from_json(value: &str) -> Vec<ChatReference> {
    if value.trim().is_empty() {
        return Vec::new();
    }
    serde_json::from_str(value).unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    use crate::search_query::RangeFilter;

    fn doc() -> DocumentIdentifier {
        DocumentIdentifier { collection_dataset: "enron_mail".into(), file_hash: "ab12".into() }
    }

    fn segment<T: Serialize>(value: T) -> String {
        UrlParam(value).to_string()
    }

    fn collection_of(dataset: &str) -> Option<String> {
        match dataset {
            "enron_mail" | "enron_files" => Some("enron".into()),
            _ => None,
        }
    }

    #[test]
    fn each_address_kind_parses() {
        let query = SearchQuery { query_string: "raptor".into(), ..Default::default() };
        let search = format!("/search/{}/0/{}/{}", segment(&query), segment(Some(doc())), segment(None::<u8>));
        assert_eq!(parse_link(&search, LinkHost::Any), Ok(HooverLink::Search { query, selected: Some(doc()) }));

        let view = format!("/view_document/{}/{}/{}", segment(doc()), segment(None::<u8>), segment(0u8));
        assert_eq!(parse_link(&view, LinkHost::Any), Ok(HooverLink::Document { document: doc() }));

        assert_eq!(parse_link("/file_browser?q=memo&page=2", LinkHost::Any), Ok(HooverLink::Storage { q: "memo".into() }));
        assert_eq!(parse_link("/file_browser", LinkHost::Any), Ok(HooverLink::Storage { q: String::new() }));
        assert_eq!(
            parse_link("/file_browser/c/enron?q=&page=0", LinkHost::Any),
            Ok(HooverLink::Collection { collectionname: "enron".into(), q: String::new() })
        );

        let path = PathDescriptor { container_hash: String::new(), path: "/a b/c".into() };
        let folder = format!("/file_browser/enron_files/{}/{}/{}", segment(&path), segment(None::<DocumentIdentifier>), segment(None::<u8>));
        assert_eq!(
            parse_link(&folder, LinkHost::Any),
            Ok(HooverLink::Folder { collection_dataset: "enron_files".into(), path, selected: None })
        );

        let graph = format!("/email_graph/{}/{}/{}", segment(doc()), segment(None::<DocumentIdentifier>), segment(None::<u8>));
        assert_eq!(parse_link(&graph, LinkHost::Any), Ok(HooverLink::EmailGraph { centre: doc() }));

        let chat = format!("/ai_chat/c/abc-123/{}/{}", segment(None::<DocumentIdentifier>), segment(None::<u8>));
        assert_eq!(parse_link(&chat, LinkHost::Any), Ok(HooverLink::Chat { session_id: "abc-123".into() }));

        assert_eq!(
            parse_link("/ai_chat/boards/0a1b?selected=finding-raptor&zoom=&assessment=", LinkHost::Any),
            Ok(HooverLink::Board { board_id: "0a1b".into(), node: "finding-raptor".into() })
        );
        assert_eq!(
            parse_link("/ai_chat/boards/0a1b", LinkHost::Any),
            Ok(HooverLink::Board { board_id: "0a1b".into(), node: String::new() })
        );
    }

    #[test]
    fn a_percent_encoded_segment_and_a_fragment_parse() {
        assert_eq!(
            parse_link("/file_browser/c/my%20files#top", LinkHost::Any),
            Ok(HooverLink::Collection { collectionname: "my files".into(), q: String::new() })
        );
        assert_eq!(
            parse_link("/ai_chat/boards/0a1b?selected=intent-ann%C3%A9e", LinkHost::Any),
            Ok(HooverLink::Board { board_id: "0a1b".into(), node: "intent-année".into() })
        );
    }

    #[test]
    fn a_corrupted_segment_is_an_error() {
        let view = format!("/view_document/{}/{}/{}", "not-cbor!!", segment(None::<u8>), segment(0u8));
        assert_eq!(parse_link(&view, LinkHost::Any), Err(LinkError::BadSegment("document")));
        let mut query = segment(SearchQuery::default());
        query.truncate(query.len() / 2);
        let search = format!("/search/{query}/0/{}/{}", segment(None::<DocumentIdentifier>), segment(None::<u8>));
        assert_eq!(parse_link(&search, LinkHost::Any), Err(LinkError::BadSegment("query")));
        let search = format!("/search/{}/x/{}/{}", segment(SearchQuery::default()), segment(None::<DocumentIdentifier>), segment(None::<u8>));
        assert_eq!(parse_link(&search, LinkHost::Any), Err(LinkError::BadSegment("page")));
        assert_eq!(parse_link("/file_browser/c/%ZZ", LinkHost::Any), Err(LinkError::BadSegment("path")));
    }

    #[test]
    fn a_partial_link_is_an_error() {
        let search = format!("/search/{}", segment(SearchQuery::default()));
        assert_eq!(parse_link(&search, LinkHost::Any), Err(LinkError::Incomplete));
        assert_eq!(parse_link(&format!("/view_document/{}", segment(doc())), LinkHost::Any), Err(LinkError::Incomplete));
        assert_eq!(parse_link("/ai_chat/c/abc", LinkHost::Any), Err(LinkError::Incomplete));
        assert_eq!(parse_link("/file_browser/enron_files", LinkHost::Any), Err(LinkError::Incomplete));
        assert_eq!(parse_link("/ai_chat/boards/new", LinkHost::Any), Err(LinkError::UnknownAddress));
        assert_eq!(parse_link("/admin/users", LinkHost::Any), Err(LinkError::UnknownAddress));
        assert_eq!(parse_link("just words", LinkHost::Any), Err(LinkError::NotALink));
        assert_eq!(parse_link("//host.example/x", LinkHost::Any), Err(LinkError::NotALink));
    }

    #[test]
    fn a_link_of_another_host_is_refused_for_the_own_origin() {
        let own = LinkHost::Own("https://hoover.example.org");
        assert_eq!(
            parse_link("https://HOOVER.example.org/ai_chat/boards/0a1b", own),
            Ok(HooverLink::Board { board_id: "0a1b".into(), node: String::new() })
        );
        assert_eq!(parse_link("https://other.example.org/ai_chat/boards/0a1b", own), Err(LinkError::OtherHost));
        assert_eq!(parse_link("http://hoover.example.org/ai_chat/boards/0a1b", own), Err(LinkError::OtherHost));
        assert_eq!(parse_link("/ai_chat/boards/0a1b", own), Ok(HooverLink::Board { board_id: "0a1b".into(), node: String::new() }));
        assert!(parse_link("https://other.example.org/ai_chat/boards/0a1b", LinkHost::Any).is_ok());
        assert_eq!(parse_link("ftp://hoover.example.org/ai_chat/boards/0a1b", own), Err(LinkError::NotALink));
    }

    #[test]
    fn links_are_found_in_text_without_their_punctuation() {
        let own = LinkHost::Own("https://hoover.example.org");
        let text = "See (https://hoover.example.org/ai_chat/boards/0a1b), and /file_browser/c/enron. Not https://x.org/ai_chat/boards/1 or /admin.";
        let found = find_links(text, own);
        assert_eq!(found.len(), 2);
        assert_eq!(&text[found[0].0.clone()], "https://hoover.example.org/ai_chat/boards/0a1b");
        assert_eq!(&text[found[1].0.clone()], "/file_browser/c/enron");
    }

    #[test]
    fn each_kind_gives_its_tool_call() {
        let call = |link: HooverLink| link.tool_call(&collection_of).map(|c| (c.tool, c.arguments));
        assert_eq!(
            call(HooverLink::Document { document: doc() }),
            Some(("read_documents".into(), serde_json::json!({"collection": "enron", "file_hash": ["ab12"]})))
        );
        assert_eq!(
            call(HooverLink::EmailGraph { centre: doc() }),
            Some(("doc_email".into(), serde_json::json!({"collection": "enron", "file_hash": "ab12"})))
        );
        assert_eq!(call(HooverLink::Storage { q: "x".into() }), Some(("list_collections".into(), serde_json::json!({}))));
        assert_eq!(
            call(HooverLink::Collection { collectionname: "enron".into(), q: String::new() }),
            Some(("folder_overview".into(), serde_json::json!({"collection": "enron"})))
        );
        assert_eq!(
            call(HooverLink::Folder {
                collection_dataset: "enron_files".into(),
                path: PathDescriptor { container_hash: String::new(), path: "/a".into() },
                selected: None,
            }),
            Some(("folder_list".into(), serde_json::json!({
                "collection": "enron", "dataset": "enron_files", "node_id": "enron_files\u{1f}\u{1f}/a",
            })))
        );
        assert_eq!(
            call(HooverLink::Chat { session_id: "s1".into() }),
            Some(("read_chat".into(), serde_json::json!({"session_id": "s1"})))
        );
        assert_eq!(
            call(HooverLink::Board { board_id: "b1".into(), node: "goal-01".into() }),
            Some(("read_board".into(), serde_json::json!({"board_id": "b1", "node": "goal-01"})))
        );
        assert_eq!(
            call(HooverLink::Board { board_id: "b1".into(), node: String::new() }),
            Some(("read_board".into(), serde_json::json!({"board_id": "b1"})))
        );
        assert_eq!(
            call(HooverLink::Search { query: SearchQuery { query_string: "a".into(), ..Default::default() }, selected: None }),
            Some(("search_collections".into(), serde_json::json!({"query": "a"})))
        );
        // A dataset that the caller cannot read gives no call.
        let other = DocumentIdentifier { collection_dataset: "secret_x".into(), file_hash: "1".into() };
        assert_eq!(call(HooverLink::Document { document: other }), None);
    }

    #[test]
    fn a_search_query_converts_to_search_collections_arguments() {
        let mut facets = BTreeMap::new();
        facets.insert("collection_dataset".to_string(), [FacetOriginalValue::String("enron_mail".into())].into());
        facets.insert("file_types".to_string(), [FacetOriginalValue::Int(7), FacetOriginalValue::Int(9)].into());
        facets.insert("extracted_by".to_string(), [FacetOriginalValue::String(FILENAME_EXTRACTED_BY.into())].into());
        facets.insert("virus_hit".to_string(), [FacetOriginalValue::Int(1)].into());
        let mut ranges = BTreeMap::new();
        ranges.insert("dates".to_string(), RangeFilter { min: Some(10), max: Some(20), include_unknown: true });
        ranges.insert("file_size_bytes".to_string(), RangeFilter { min: None, max: Some(500), include_unknown: false });
        ranges.insert("mentioned_dates".to_string(), RangeFilter { min: Some(1), max: None, include_unknown: false });
        let query = SearchQuery {
            collection_datasets: vec![],
            query_string: "pipeline".into(),
            facet_filters: facets,
            range_filters: ranges,
            sort: SortSpec { key: SortKey::Date, desc: false },
        };
        let call = search_tool_call(&query, &collection_of).unwrap();
        assert_eq!(call.tool, "search_collections");
        assert_eq!(call.arguments, serde_json::json!({
            "collection": ["enron"],
            "query": "pipeline",
            "sort": {"field": "date", "direction": "asc"},
            "filename_only": true,
            "facet_filters": {"collection_dataset": ["enron_mail"], "file_types": ["7", "9"]},
            "date_after": 10, "date_before": 20, "date_unknown_only": true,
            "size_max": 500,
            "mentioned_date_after": 1,
        }));
        assert!(call.note.contains("virus_hit"));
        // Relevance in either direction is the default order.
        let plain = SearchQuery { sort: SortSpec { key: SortKey::Relevance, desc: false }, ..Default::default() };
        assert_eq!(search_tool_call(&plain, &collection_of).unwrap().arguments, serde_json::json!({"query": ""}));
        // A dataset outside the readable set gives no call.
        let hidden = SearchQuery { collection_datasets: vec!["secret_x".into()], ..Default::default() };
        assert!(search_tool_call(&hidden, &collection_of).is_none());
    }

    fn reference(handle: &str, label: &str) -> ChatReference {
        ChatReference {
            handle: handle.into(),
            link: HooverLink::Chat { session_id: "s".into() },
            label: label.into(),
            kind: "chat".into(),
            tool: "read_chat".into(),
            arguments: serde_json::json!({"session_id": "s"}),
            url: "/ai_chat/c/s/x/y".into(),
            note: String::new(),
        }
    }

    #[test]
    fn markers_split_and_display_with_labels() {
        assert_eq!(
            marked_parts("a [R1] b [R12][D3] [R] [R0] [Rx]"),
            vec![
                MarkedPart::Text("a ".into()),
                MarkedPart::Reference(1),
                MarkedPart::Text(" b ".into()),
                MarkedPart::Reference(12),
                MarkedPart::Text("[D3] [R] [R0] [Rx]".into()),
            ]
        );
        let rich = RichText {
            text: "  Compare [R2] with [R1] and [R3]. ".into(),
            references: vec![reference("[R1]", "one"), reference("[R2]", "two"), reference("[R9]", "unused")],
        };
        let trimmed = rich.trimmed();
        assert_eq!(trimmed.text, "Compare [R2] with [R1] and [R3].");
        assert_eq!(trimmed.references.iter().map(|r| r.handle.as_str()).collect::<Vec<_>>(), vec!["[R2]", "[R1]"]);
        assert_eq!(trimmed.display_text(), "Compare two with one and [R3].");
        let shifted = trimmed.shifted(4);
        assert_eq!(shifted.text, "Compare [R6] with [R5] and [R3].");
        assert_eq!(shifted.references.iter().map(|r| r.handle.as_str()).collect::<Vec<_>>(), vec!["[R6]", "[R5]"]);
        assert_eq!((marker_number("[R12]"), marker_number("[R0]"), marker_number("[D1]")), (Some(12), None, None));
    }

    #[test]
    fn rich_text_decodes_from_a_plain_string() {
        let plain: RichText = serde_json::from_str("\"hello\"").unwrap();
        assert_eq!(plain, RichText::plain("hello"));
        let rich: RichText = serde_json::from_str("{\"text\": \"x [R1]\"}").unwrap();
        assert_eq!(rich, RichText::plain("x [R1]"));
        let full = RichText { text: "x [R1]".into(), references: vec![reference("[R1]", "c")] };
        let back: RichText = serde_json::from_str(&serde_json::to_string(&full).unwrap()).unwrap();
        assert_eq!(back, full);
        assert_eq!(references_from_json(&full.references_json()), full.references);
        assert!(references_from_json("").is_empty());
    }
}
