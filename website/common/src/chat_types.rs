//! DTOs for the AI Chat page, shared between frontend and backend.

use crate::search_result::DocumentIdentifier;

/// A conversation, as shown in the history list / homepage cards.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ChatSessionItem {
    pub session_id: String,
    pub title: String,
    /// One-or-two sentence LLM summary for homepage cards. Empty until the first turn.
    #[serde(default)]
    pub summary: String,
    /// Collections this chat searches. Always a subset of the owner's permitted
    /// collections *at the time each message was sent* — it is re-checked per message,
    /// so a stale selection here cannot widen access.
    pub collections: Vec<String>,
    pub created_at: String,
    pub updated_at: String,
    pub message_count: u32,
    /// The two agent switches, frozen at the first turn. See [`ChatOptions`].
    #[serde(default)]
    pub options: ChatOptions,
}

/// The Deep Research / Internet tools switches for one conversation.
///
/// They are a property of the *conversation*, not of the composer: they decide which
/// agent answers and therefore which tools exist. Letting them change mid-thread would
/// produce a transcript where some answers had web access and some did not, with
/// nothing on screen saying which was which. So the first message freezes them
/// (`locked`), and from then on the UI shows them read-only above the transcript.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct ChatOptions {
    pub deep_research: bool,
    pub internet_tools: bool,
    /// Set when the first message is sent. `false` means the composer may still change
    /// them and the values above are only defaults.
    pub locked: bool,
}

impl Default for ChatOptions {
    /// Internet tools **on**: the chat is more useful with them than without, and a
    /// user who wants a documents-only answer can untick before the first message.
    /// Deep research off: it costs a Temporal workflow and minutes of GPU time.
    fn default() -> Self {
        Self {
            deep_research: false,
            internet_tools: true,
            locked: false,
        }
    }
}

/// Who produced one entry in the trajectory.
///
/// `Tool` and `Error` are first-class rather than folded into `Assistant` because the
/// point of showing a trajectory is being able to see what the agent actually did and
/// where it failed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum ChatRole {
    User,
    Assistant,
    Tool,
    Error,
}

impl ChatRole {
    /// Wire value stored in ClickHouse.
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::User => "user",
            Self::Assistant => "assistant",
            Self::Tool => "tool",
            Self::Error => "error",
        }
    }

    /// Parse a stored value. Unknown values become `Error` rather than being dropped:
    /// a row we cannot interpret is still evidence that something happened, and hiding
    /// it would silently shorten a transcript.
    pub fn from_str(raw: &str) -> Self {
        match raw {
            "user" => Self::User,
            "assistant" => Self::Assistant,
            "tool" => Self::Tool,
            _ => Self::Error,
        }
    }

    /// Whether this entry is part of the conversation the LLM should be replayed, as
    /// opposed to a trace of how an answer was produced.
    pub fn is_conversational(&self) -> bool {
        matches!(self, Self::User | Self::Assistant)
    }
}

/// One document a tool step surfaced — enough to render a search-result card and open
/// the document preview (`DocumentIdentifier` = `collection_dataset` + `file_hash`).
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ChatDocRef {
    pub collection_dataset: String,
    pub file_hash: String,
    #[serde(default)]
    pub collectionname: String,
    #[serde(default)]
    pub path: String,
    #[serde(default)]
    pub page_id: Option<u32>,
    #[serde(default)]
    pub score: Option<f64>,
    #[serde(default)]
    pub snippet: String,
    /// Every dataset this document was found in, when it was found in more than one.
    ///
    /// A search returns one hit per PAGE, and the same bytes can be ingested into several
    /// collections, so a single document can arrive as a dozen rows. They are collapsed
    /// to one card and the datasets they came from are collected here; empty means the
    /// card's own `collection_dataset` is the whole story. Defaulted so rows stored
    /// before the field existed still deserialise.
    #[serde(default)]
    pub also_in: Vec<String>,
    /// The citation handle the agent was given for this document, `[D3]`. Empty for a
    /// document a search merely returned.
    ///
    /// It is what turns a pile of results into an argument: the handle appears in the
    /// answer's prose where the claim is made, and the reader can follow it to the
    /// document. Allocated per chat session, so a handle from the first turn still
    /// resolves in the ninth.
    #[serde(default)]
    pub handle: String,
    /// The span the agent quoted from this document.
    #[serde(default)]
    pub quote: String,
    /// What the agent says this document supports.
    #[serde(default)]
    pub why: String,
    /// The quoted span was found in the document's extracted text.
    ///
    /// False on a citation is not a refusal and must not be hidden: the citation is shown
    /// marked. A model that stops citing is a worse outcome than a marked quote, and a
    /// marked quote is a fact the reader can act on.
    #[serde(default)]
    pub quote_verified: bool,
}

impl ChatDocRef {
    pub fn document_identifier(&self) -> DocumentIdentifier {
        DocumentIdentifier {
            collection_dataset: self.collection_dataset.clone(),
            file_hash: self.file_hash.clone(),
        }
    }

    /// Display title for a card: basename of `path`, or the file hash prefix.
    pub fn display_title(&self) -> String {
        if !self.path.is_empty() {
            self.path
                .rsplit('/')
                .next()
                .unwrap_or(self.path.as_str())
                .to_string()
        } else if self.file_hash.len() >= 12 {
            self.file_hash[..12].to_string()
        } else {
            self.file_hash.clone()
        }
    }

    /// The snippet as a card may render it: collapsed whitespace, clamped length.
    ///
    /// A hit's snippet is up to `SEARCH_SNIPPET_CHARS` (1200) of page text chosen by a
    /// search server, and one turn can surface a dozen of them. Rendered whole, a single
    /// result put kilobytes into the transcript — and the worst offenders were exactly the
    /// results least worth reading, because extraction indexes an email attachment's
    /// base64 and an image's pixel rows as page text (`tasks/text_quality.py` now keeps
    /// those out of the *vector* index, but a keyword hit can still surface one, and a
    /// card must not depend on the pipeline having been perfect).
    ///
    /// This is a **display** clamp. The full text stays in the payload, and the document
    /// card links to the document itself, which is where reading it belongs.
    pub fn display_snippet(&self) -> String {
        clamp_display_text(&self.snippet, DOC_REF_SNIPPET_CHARS)
    }
}

/// Longest snippet a chat document card renders inline.
pub const DOC_REF_SNIPPET_CHARS: usize = 400;

/// Collapse runs of whitespace and cut to `max_chars` **characters**, never bytes.
///
/// Byte-slicing a `&str` panics mid-codepoint, and this text is arbitrary extracted
/// content: page data, OCR output, whatever a parser produced. Romanian diacritics alone
/// are enough to land a cut inside a two-byte sequence.
pub fn clamp_display_text(text: &str, max_chars: usize) -> String {
    let flat = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if flat.chars().count() <= max_chars {
        return flat;
    }
    let mut out: String = flat.chars().take(max_chars).collect();
    out.push('\u{2026}');
    out
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ChatMessageItem {
    pub seq: u32,
    pub role: ChatRole,
    pub content: String,
    /// Set for `Tool` entries.
    pub tool_name: String,
    /// JSON arguments the model passed to the tool (role = tool).
    #[serde(default)]
    pub tool_input: String,
    /// JSON result, truncated to [`TOOL_PAYLOAD_CHARS`] (role = tool).
    #[serde(default)]
    pub tool_output: String,
    /// JSON array of [`ChatDocRef`] this step surfaced.
    #[serde(default)]
    pub doc_refs: String,
    pub created_at: String,
    /// Millisecond creation time (RFC3339 with fractional seconds when available).
    #[serde(default)]
    pub created_ms: String,
    /// Wall time the agent took to produce this row. 0 for user turns.
    #[serde(default)]
    pub agent_duration_ms: u32,
    /// JSON array of one error per attempt the turn made, oldest first, including the
    /// attempt whose error is in `content` (role = error).
    #[serde(default)]
    pub retry_errors: String,
    /// Reasoning trace + pre-tool narration (role = assistant). Rendered behind a
    /// disclosure, never in the answer body.
    #[serde(default)]
    pub reasoning: String,
    /// Transient, never stored: true on entries synthesised from the in-flight stream
    /// (`chat_message_stream`) rather than read from `chat_messages`. The transcript
    /// renders these with a pending/running treatment instead of the finished one.
    #[serde(default)]
    pub streaming: bool,
}

impl ChatMessageItem {
    /// Parsed [`ChatDocRef`] list, or empty when the column is blank / invalid.
    pub fn parsed_doc_refs(&self) -> Vec<ChatDocRef> {
        if self.doc_refs.is_empty() {
            return Vec::new();
        }
        serde_json::from_str(&self.doc_refs).unwrap_or_default()
    }

    /// Errors from the attempts that preceded this one, oldest first.
    pub fn parsed_retry_errors(&self) -> Vec<String> {
        if self.retry_errors.is_empty() {
            return Vec::new();
        }
        serde_json::from_str(&self.retry_errors).unwrap_or_default()
    }
}

/// One agent run currently in flight, for the admin "live chats" panel.
///
/// Held in memory by the website process, not in ClickHouse: it describes work being
/// done *right now* by this process, and a row that outlives the process that was doing
/// the work would be a lie. See `backend::api::chat::live_runs`.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct LiveChatRun {
    pub run_id: u64,
    pub username: String,
    pub session_id: String,
    pub title: String,
    /// First ~200 chars of the message being answered.
    pub message_preview: String,
    pub deep_research: bool,
    pub internet_tools: bool,
    /// Milliseconds since this run started.
    pub running_ms: u64,
    /// RFC3339 start time.
    pub started_at: String,
    /// Which attempt is in flight (1-based).
    pub attempt: u32,
    /// Set when an admin has asked for it to stop and it has not noticed yet.
    pub cancel_requested: bool,
}

/// One in-flight tool call, as far as the stream has reported it.
///
/// `seq` is the position the finished row will take in `chat_messages` — the streaming
/// writer assigns it when the tool starts, so a poll and a refresh order identically.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct StreamToolRow {
    pub seq: u32,
    /// 0-based order of this call within its turn.
    pub tool_call_index: u32,
    pub tool_name: String,
    /// Input summary while running, output summary once `done`.
    pub summary: String,
    /// False between start_tool and end_tool — the card renders a running state.
    pub done: bool,
    /// How long this call has been running, in milliseconds, as of this poll.
    ///
    /// Computed server-side rather than from a start timestamp the client subtracts:
    /// this type is rendered by a component compiled into the server-side build too,
    /// where there is no browser clock, and a wrong-by-a-timezone counter is worse than
    /// none. Refreshing a page mid-tool-call used to restart the counter at 0 — a
    /// two-minute browse read as having just begun, which is the opposite of the signal
    /// the counter exists to give.
    #[serde(default)]
    pub elapsed_ms: u32,
}

/// The turn currently being produced, reconstructed from `chat_message_stream`.
///
/// Read-path rules (both load-bearing): the stream table is read with `argMax`, never a
/// bare SELECT, or the visible text can shrink mid-stream; and a finished
/// `chat_messages` row always wins over a stream row at the same `seq`.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct StreamTurn {
    /// `seq` the assistant row will take once finalised.
    pub answer_seq: u32,
    /// Answer text so far (content after the last tool call; earlier narration is
    /// moved to `reasoning` as each tool starts, mirroring the agent's own rule).
    pub content: String,
    #[serde(default)]
    pub reasoning: String,
    #[serde(default)]
    pub tool_rows: Vec<StreamToolRow>,
    /// Version stamp: milliseconds of the newest stream row. The poll loop's change
    /// detection is built on it.
    pub updated_ms: i64,
}

/// One poll of the tail of a transcript.
///
/// `messages` are finished rows with `seq > after_seq`. `stream` is the in-flight
/// turn, if any. `interrupted` means a stream row has stopped advancing with no live
/// run owning it (the website restarted mid-turn): render a marker, never a spinner.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ChatPollResult {
    pub messages: Vec<ChatMessageItem>,
    #[serde(default)]
    pub stream: Option<StreamTurn>,
    /// A turn is still being produced for this session. **This, not `stream`, is what
    /// says "keep polling".** A turn is registered before the agent is called and the
    /// first stream row only appears with the first event, so there is a window —
    /// often several seconds of model latency — where the turn is alive and `stream`
    /// is still `None`. A poller that stopped on `stream.is_none()` would abandon
    /// every turn in exactly that window.
    #[serde(default)]
    pub active: bool,
    #[serde(default)]
    pub interrupted: bool,
    /// Opaque change-detection token: the client echoes it back on the next poll, and
    /// the server returns early when the current state produces a different one.
    pub sig: String,
}

/// Result of [`send_message`](crate::api::chat) / the matching server function.
///
/// When `retry_after_seconds` is `Some`, the rate limiter refused the turn and
/// `messages` is unchanged (nothing was written). The composer shows "try again in N s".
///
/// With streaming chat, `messages` is the trajectory *so far* — the turn itself runs in
/// a spawned task and the client follows it through `chat_poll`.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ChatSendResult {
    pub messages: Vec<ChatMessageItem>,
    #[serde(default)]
    pub retry_after_seconds: Option<u64>,
}

/// A session plus its full trajectory.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ChatSessionDetail {
    pub session: ChatSessionItem,
    pub messages: Vec<ChatMessageItem>,
    /// The collections the owner may currently read — what the collection picker offers.
    /// Resolved fresh on every load, so a revoked permission disappears from the picker
    /// even in an old conversation.
    pub available_collections: Vec<String>,
    /// The in-flight turn, when the page is (re)loaded mid-answer — a refresh shows
    /// exactly what a poller sees.
    #[serde(default)]
    pub stream: Option<StreamTurn>,
    /// A turn is in flight for this session: the page resumes polling on load. See
    /// [`ChatPollResult::active`] for why this is separate from `stream`.
    #[serde(default)]
    pub active: bool,
    /// A stale stream row with no live run behind it (the website restarted mid-turn).
    #[serde(default)]
    pub interrupted: bool,
}

/// Maximum length of one user message. Guards the agent's context window and keeps a
/// pasted document out of the chat table (that is what the collections are for).
pub const MAX_MESSAGE_CHARS: usize = 8_000;

/// How many characters of the first user message become the session title fallback.
pub const TITLE_CHARS: usize = 60;

/// Cap on `tool_output` (and a soft cap on `tool_input`) stored in `chat_messages`.
/// A `search_collections` result set with long snippets is large; this table is read on
/// every page load. Sized for the richer web_search payload — the search-detail artifact
/// absorbs anything bigger.
pub const TOOL_PAYLOAD_CHARS: usize = 24_000;

/// Derive a session title from its first user message.
pub fn title_from_message(message: &str) -> String {
    let flat: String = message.split_whitespace().collect::<Vec<_>>().join(" ");
    if flat.is_empty() {
        return "New chat".to_string();
    }
    if flat.chars().count() <= TITLE_CHARS {
        return flat;
    }
    format!("{}\u{2026}", flat.chars().take(TITLE_CHARS).collect::<String>())
}

/// Prefix a rate-limit refusal carries through the server-function boundary.
///
/// The typed [`crate::chat_types::rate_limited_seconds`] pair is the whole contract: a
/// rate limit is not a broken connection, and a client that cannot tell the two apart
/// declares the chat lost while the turn is still running.
pub const RATE_LIMITED_PREFIX: &str = "rate_limited:";

/// The retry-after seconds in a rate-limit error, or `None` if it is a different error.
///
/// Searches rather than matching a prefix: by the time the browser sees it the message has
/// been through `ServerFnError`, which is free to wrap it in prose. Anything this does not
/// recognise is a real error and must stay one — silently treating an unknown failure as
/// "wait and retry" is how a dead backend looks like a slow one forever.
pub fn rate_limited_seconds(message: &str) -> Option<u64> {
    let at = message.find(RATE_LIMITED_PREFIX)? + RATE_LIMITED_PREFIX.len();
    let digits: String = message[at..]
        .trim_start()
        .chars()
        .take_while(char::is_ascii_digit)
        .collect();
    digits.parse().ok()
}

/// Truncate a text payload for storage, by cutting it off.
///
/// For anything that is **not** a JSON document. A tool result is one — use
/// [`truncate_tool_payload`], which keeps it parseable.
pub fn truncate_payload(text: &str, max_chars: usize) -> String {
    if text.chars().count() <= max_chars {
        return text.to_string();
    }
    format!("{}\u{2026}", text.chars().take(max_chars).collect::<String>())
}

/// Headroom left for the `"truncated": true` markers before they are added.
const TRUNCATION_MARK_RESERVE: usize = 64;

/// Below this a string is not worth clipping — the quotes and key cost nearly as much.
const MIN_CLIPPABLE_STRING: usize = 80;

/// Fit a tool result into `max_chars` **without breaking its JSON**.
///
/// Byte-chopping a serialised document at a character count leaves a `{` with no `}`, and
/// everything downstream then treats a recorded result as an absent one: the card parsed
/// nothing, fell through to `tool_content == None`, and told the user "the result payload
/// was not recorded" about data sitting in the row it was reading. Truncating a document
/// is a thing you do *inside* it.
///
/// So: drop whole elements off the biggest array (the result list, almost always), mark the
/// object that owned it with `"truncated": true`, and only clip long strings if dropping
/// alone cannot get there. A payload that is not JSON at all — or that is one enormous
/// scalar with nothing to drop — falls back to [`truncate_payload`]; the cards render the
/// raw bytes in that case rather than claiming there was nothing to render.
pub fn truncate_tool_payload(text: &str, max_chars: usize) -> String {
    if text.chars().count() <= max_chars {
        return text.to_string();
    }
    let Ok(mut value) = serde_json::from_str::<serde_json::Value>(text) else {
        return truncate_payload(text, max_chars);
    };

    let target = max_chars.saturating_sub(TRUNCATION_MARK_RESERVE);
    let mut marked: Vec<String> = Vec::new();
    shrink_to_fit(&mut value, target, &mut marked);
    for pointer in &marked {
        if let Some(serde_json::Value::Object(map)) = value.pointer_mut(pointer) {
            map.insert("truncated".to_string(), serde_json::Value::Bool(true));
        }
    }

    let out = serde_json::to_string(&value).unwrap_or_default();
    if out.chars().count() <= max_chars && !out.is_empty() {
        return out;
    }
    // The markers themselves pushed it back over, or the document has nothing left to
    // give. Cutting the text is the last resort it always was — but now a rare one.
    truncate_payload(text, max_chars)
}

fn json_len(v: &serde_json::Value) -> usize {
    serde_json::to_string(v).map(|s| s.chars().count()).unwrap_or(usize::MAX)
}

/// JSON Pointer segment escaping (RFC 6901).
fn escape_pointer(key: &str) -> String {
    key.replace('~', "~0").replace('/', "~1")
}

/// Every array in the document with something to give, as (pointer, serialised size).
fn collect_arrays(v: &serde_json::Value, at: &str, out: &mut Vec<(String, usize)>) {
    match v {
        serde_json::Value::Array(items) => {
            if !items.is_empty() {
                out.push((at.to_string(), json_len(v)));
            }
            for (i, item) in items.iter().enumerate() {
                collect_arrays(item, &format!("{at}/{i}"), out);
            }
        }
        serde_json::Value::Object(map) => {
            for (k, item) in map {
                collect_arrays(item, &format!("{at}/{}", escape_pointer(k)), out);
            }
        }
        _ => {}
    }
}

/// Every string long enough to be worth clipping, as (pointer, length in chars).
fn collect_strings(v: &serde_json::Value, at: &str, out: &mut Vec<(String, usize)>) {
    match v {
        serde_json::Value::String(s) => {
            let n = s.chars().count();
            if n > MIN_CLIPPABLE_STRING {
                out.push((at.to_string(), n));
            }
        }
        serde_json::Value::Array(items) => {
            for (i, item) in items.iter().enumerate() {
                collect_strings(item, &format!("{at}/{i}"), out);
            }
        }
        serde_json::Value::Object(map) => {
            for (k, item) in map {
                collect_strings(item, &format!("{at}/{}", escape_pointer(k)), out);
            }
        }
        _ => {}
    }
}

/// The pointer to whatever contains the node at `pointer`, or `None` for the root.
fn parent_pointer(pointer: &str) -> Option<String> {
    let cut = pointer.rfind('/')?;
    Some(pointer[..cut].to_string())
}

/// Reduce `value` until it serialises to at most `target` chars.
///
/// Arrays first and biggest-first: dropping the tail of a result list costs the reader the
/// results they were least likely to read, while clipping strings costs every result a
/// little. Strings are the fallback for a document whose bulk is one long field.
fn shrink_to_fit(value: &mut serde_json::Value, target: usize, marked: &mut Vec<String>) {
    while json_len(value) > target {
        let mut arrays = Vec::new();
        collect_arrays(value, "", &mut arrays);
        arrays.sort_by_key(|(_, size)| std::cmp::Reverse(*size));
        let Some((pointer, _)) = arrays.into_iter().next() else {
            break;
        };
        let over = json_len(value).saturating_sub(target);
        let Some(serde_json::Value::Array(items)) = value.pointer_mut(&pointer) else {
            break;
        };
        // Pop by measured size rather than one-at-a-time-then-reserialise: a hundred
        // results would otherwise mean a hundred serialisations of the whole document.
        let mut freed = 0usize;
        while !items.is_empty() && freed <= over {
            let dropped = items.pop().unwrap_or(serde_json::Value::Null);
            freed += json_len(&dropped) + 1;
        }
        let owner = parent_pointer(&pointer).unwrap_or_default();
        if !marked.contains(&owner) {
            marked.push(owner);
        }
    }

    // Every array is empty and it still does not fit: the bulk is in the strings.
    while json_len(value) > target {
        let mut strings = Vec::new();
        collect_strings(value, "", &mut strings);
        strings.sort_by_key(|(_, len)| std::cmp::Reverse(*len));
        let Some((pointer, len)) = strings.into_iter().next() else {
            return;
        };
        let Some(serde_json::Value::String(s)) = value.pointer_mut(&pointer) else {
            return;
        };
        let keep = (len / 2).max(MIN_CLIPPABLE_STRING / 2);
        *s = format!("{}\u{2026}", s.chars().take(keep).collect::<String>());
        if let Some(owner) = parent_pointer(&pointer) {
            if !marked.contains(&owner) {
                marked.push(owner);
            }
        }
    }
}

/// Pull document references out of a completed tool call's name + input + output JSON.
///
/// Observed shapes (LangGraph tool events):
/// - start: `{"input": {…}}`
/// - end:   `{"output": {"content": …, "type": "tool", "name": "…", "tool_call_id": "…"}, …}`
///
/// `search_collections` content is `{"results":[{collection_dataset,file_hash,path,…}]}`.
/// `get_document_text` / `list_document_entities` / `show_document` content is a single
/// document object. Unknown tools are scanned for document-shaped objects generically.
pub fn extract_doc_refs(tool_name: &str, tool_output_json: &str) -> Vec<ChatDocRef> {
    let Ok(root) = serde_json::from_str::<serde_json::Value>(tool_output_json) else {
        return Vec::new();
    };
    let content = root
        .get("output")
        .and_then(|o| o.get("content"))
        .or_else(|| root.get("content"))
        .unwrap_or(&root);

    match tool_name {
        "search_collections" => extract_from_search_results(content),
        "cite_documents" => extract_from_citations(content),
        "get_document_text" | "list_document_entities" | "show_document" => {
            doc_ref_from_value(content).into_iter().collect()
        }
        _ => {
            // Generic: walk for document-shaped objects (have file_hash + a dataset key).
            let mut out = Vec::new();
            collect_document_shaped(content, &mut out);
            out
        }
    }
}

/// The documents the agent put forward as evidence, in handle order.
///
/// Not collapsed the way search results are. A citation is a statement the agent made,
/// and two citations of one document with different quotes are two statements — the
/// handle table already guarantees they share a handle, so they render as one entry in
/// the Sources strip and keep both quotes.
fn extract_from_citations(content: &serde_json::Value) -> Vec<ChatDocRef> {
    let citations = content
        .get("citations")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let mut out: Vec<ChatDocRef> = Vec::new();
    for value in &citations {
        let Some(mut doc) = doc_ref_from_value(value) else {
            continue;
        };
        doc.handle = value.get("handle").and_then(|v| v.as_str()).unwrap_or("").to_string();
        doc.quote = value.get("quote").and_then(|v| v.as_str()).unwrap_or("").to_string();
        doc.why = value.get("why").and_then(|v| v.as_str()).unwrap_or("").to_string();
        doc.quote_verified =
            value.get("quote_verified").and_then(|v| v.as_bool()).unwrap_or(false);
        // The snippet slot carries the quote, so the card shows what was cited rather
        // than an unrelated passage of the same file.
        if doc.snippet.is_empty() {
            doc.snippet = doc.quote.clone();
        }
        out.push(doc);
    }
    out
}

/// One entry per document across every citation in a turn, in handle order.
///
/// De-duplicated WITHIN this group and never across groups: a search card and a citation
/// card for the same document are two different statements about it, and collapsing them
/// would hide that the agent chose one of the things it found.
pub fn merge_citations(refs: Vec<ChatDocRef>) -> Vec<ChatDocRef> {
    let mut order: Vec<String> = Vec::new();
    let mut best: std::collections::HashMap<String, ChatDocRef> = std::collections::HashMap::new();
    for item in refs {
        let key = format!("{}\u{1f}{}", item.collection_dataset, item.file_hash);
        match best.get_mut(&key) {
            None => {
                order.push(key.clone());
                best.insert(key, item);
            }
            Some(kept) => {
                // A verified quote outranks an unverified one for the same document: the
                // reader should see the strongest form of the claim that was made.
                if item.quote_verified && !kept.quote_verified {
                    *kept = item;
                }
            }
        }
    }
    let mut merged: Vec<ChatDocRef> =
        order.into_iter().filter_map(|key| best.remove(&key)).collect();
    // Handle order, not arrival order: `[D1]` before `[D2]` is the only ordering a reader
    // following a handle out of the prose can predict. Handle-less entries sort last.
    merged.sort_by_key(|doc| (handle_number(&doc.handle).unwrap_or(u32::MAX), doc.handle.clone()));
    merged
}

/// The number inside a `[Dn]` handle, or `None` when the string is not one.
pub fn handle_number(handle: &str) -> Option<u32> {
    handle
        .strip_prefix("[D")
        .and_then(|rest| rest.strip_suffix(']'))
        .and_then(|digits| digits.parse().ok())
}

fn extract_from_search_results(content: &serde_json::Value) -> Vec<ChatDocRef> {
    let results = content
        .get("results")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    collapse_by_document(results.iter().filter_map(doc_ref_from_value).collect())
}

/// One card per document, however many rows the tool returned for it.
///
/// `search_collections` answers with one hit per PAGE — `page_id` is part of the search
/// server's own dedup key, deliberately, because two pages of one document are two pieces
/// of evidence — and the same bytes can also be ingested into more than one collection. A
/// reader wants neither of those as repetition: the transcript showed the same title three
/// times over, and the disclosure counted page-hits while calling them "documents".
///
/// Rows are keyed on `file_hash` alone, so the cross-collection case collapses too, and
/// the surviving row is the best-scoring one — the same argument the search server's
/// fusion step makes for keeping the nearest chunk's snippet rather than the last one.
/// Input order is otherwise preserved, because it is rank order.
fn collapse_by_document(refs: Vec<ChatDocRef>) -> Vec<ChatDocRef> {
    let mut order: Vec<String> = Vec::new();
    let mut best: std::collections::HashMap<String, ChatDocRef> = std::collections::HashMap::new();
    for item in refs {
        match best.get_mut(&item.file_hash) {
            None => {
                order.push(item.file_hash.clone());
                best.insert(item.file_hash.clone(), item);
            }
            Some(kept) => {
                if !item.collection_dataset.is_empty()
                    && item.collection_dataset != kept.collection_dataset
                    && !kept.also_in.contains(&item.collection_dataset)
                {
                    kept.also_in.push(item.collection_dataset.clone());
                }
                // A missing score sorts below any score rather than winning by accident.
                if item.score.unwrap_or(f64::MIN) > kept.score.unwrap_or(f64::MIN) {
                    let also_in = std::mem::take(&mut kept.also_in);
                    let previous = kept.collection_dataset.clone();
                    *kept = item;
                    kept.also_in = also_in;
                    if !previous.is_empty()
                        && previous != kept.collection_dataset
                        && !kept.also_in.contains(&previous)
                    {
                        kept.also_in.push(previous);
                    }
                    kept.also_in.retain(|d| d != &kept.collection_dataset);
                }
            }
        }
    }
    order
        .into_iter()
        .filter_map(|hash| best.remove(&hash))
        .collect()
}

fn doc_ref_from_value(v: &serde_json::Value) -> Option<ChatDocRef> {
    let file_hash = v.get("file_hash")?.as_str()?.to_string();
    if file_hash.is_empty() {
        return None;
    }
    // Prefer collection_dataset (DocumentIdentifier key). Fall back to nothing rather
    // than inventing one from collectionname — a wrong dataset id opens the wrong doc.
    let collection_dataset = v
        .get("collection_dataset")
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string();
    if collection_dataset.is_empty() {
        // Still record path/hash so the disclosure UI can show something; the preview
        // card is only clickable when collection_dataset is set (frontend checks).
    }
    Some(ChatDocRef {
        collection_dataset,
        file_hash,
        collectionname: v
            .get("collectionname")
            .and_then(|x| x.as_str())
            .unwrap_or("")
            .to_string(),
        path: v.get("path").and_then(|x| x.as_str()).unwrap_or("").to_string(),
        page_id: v.get("page_id").and_then(|x| x.as_u64()).map(|n| n as u32),
        score: v.get("score").and_then(|x| x.as_f64()),
        snippet: v
            .get("snippet")
            .and_then(|x| x.as_str())
            .unwrap_or("")
            .to_string(),
        also_in: Vec::new(),
        handle: String::new(),
        quote: String::new(),
        why: String::new(),
        quote_verified: false,
    })
}

fn collect_document_shaped(v: &serde_json::Value, out: &mut Vec<ChatDocRef>) {
    if let Some(r) = doc_ref_from_value(v) {
        out.push(r);
        return;
    }
    match v {
        serde_json::Value::Array(items) => {
            for item in items {
                collect_document_shaped(item, out);
            }
        }
        serde_json::Value::Object(map) => {
            for val in map.values() {
                collect_document_shaped(val, out);
            }
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roles_round_trip_through_their_wire_value() {
        for role in [ChatRole::User, ChatRole::Assistant, ChatRole::Tool, ChatRole::Error] {
            assert_eq!(ChatRole::from_str(role.as_str()), role);
        }
    }

    #[test]
    fn unknown_role_becomes_error_not_a_dropped_row() {
        assert_eq!(ChatRole::from_str("something_new"), ChatRole::Error);
        assert_eq!(ChatRole::from_str(""), ChatRole::Error);
    }

    #[test]
    fn only_user_and_assistant_replay_to_the_model() {
        assert!(ChatRole::User.is_conversational());
        assert!(ChatRole::Assistant.is_conversational());
        assert!(!ChatRole::Tool.is_conversational());
        assert!(!ChatRole::Error.is_conversational());
    }

    fn doc_ref(snippet: &str) -> ChatDocRef {
        ChatDocRef {
            collection_dataset: "coll_ds".into(),
            file_hash: "a".repeat(64),
            collectionname: "coll".into(),
            path: "/img/sample.xpm".into(),
            page_id: Some(4),
            score: Some(0.5),
            snippet: snippet.into(),
            also_in: Vec::new(),
            handle: String::new(),
            quote: String::new(),
            why: String::new(),
            quote_verified: false,
        }
    }

    fn citation_output(citations: &str) -> String {
        format!(r#"{{"output": {{"content": {{"success": true, "citations": {citations}}}}}}}"#)
    }

    #[test]
    fn a_citation_carries_its_handle_quote_and_verdict() {
        let output = citation_output(
            r#"[{"handle": "[D1]", "collectionname": "c", "collection_dataset": "c_ds",
                 "file_hash": "aa", "path": "/a.txt", "quote": "the board approved",
                 "why": "names the approver", "quote_verified": true}]"#,
        );
        let refs = extract_doc_refs("cite_documents", &output);
        assert_eq!(refs.len(), 1);
        assert_eq!(refs[0].handle, "[D1]");
        assert_eq!(refs[0].why, "names the approver");
        assert!(refs[0].quote_verified);
        // The snippet slot carries the quote, so the card shows what was cited rather
        // than an unrelated passage of the same file.
        assert_eq!(refs[0].snippet, "the board approved");
    }

    #[test]
    fn the_sources_strip_lists_each_document_once_in_handle_order() {
        let output = citation_output(
            r#"[{"handle": "[D2]", "collection_dataset": "c_ds", "file_hash": "bb", "quote": "q2"},
                {"handle": "[D1]", "collection_dataset": "c_ds", "file_hash": "aa", "quote": "q1"},
                {"handle": "[D1]", "collection_dataset": "c_ds", "file_hash": "aa", "quote": "q1 again"}]"#,
        );
        let merged = merge_citations(extract_doc_refs("cite_documents", &output));
        assert_eq!(merged.len(), 2, "one entry per document");
        assert_eq!(merged[0].handle, "[D1]", "handle order, not arrival order");
        assert_eq!(merged[1].handle, "[D2]");
    }

    /// A verified quote outranks an unverified one for the same document: the reader
    /// should see the strongest form of the claim that was actually made.
    #[test]
    fn a_verified_quote_wins_over_an_unverified_one_for_one_document() {
        let output = citation_output(
            r#"[{"handle": "[D1]", "collection_dataset": "c_ds", "file_hash": "aa",
                 "quote": "made up", "quote_verified": false},
                {"handle": "[D1]", "collection_dataset": "c_ds", "file_hash": "aa",
                 "quote": "really there", "quote_verified": true}]"#,
        );
        let merged = merge_citations(extract_doc_refs("cite_documents", &output));
        assert_eq!(merged.len(), 1);
        assert!(merged[0].quote_verified);
        assert_eq!(merged[0].quote, "really there");
    }

    /// A search group and a citation group showing the same document is correct and
    /// expected: they are two different statements about it. De-duplication is within a
    /// group and never across one.
    #[test]
    fn a_cited_document_is_not_removed_from_the_search_group_that_found_it() {
        let search = r#"{"output": {"content": {"results": [
            {"collection_dataset": "c_ds", "file_hash": "aa", "score": 1.0, "snippet": "s"}]}}}"#;
        let search_refs = extract_doc_refs("search_collections", search);
        let cited = extract_doc_refs(
            "cite_documents",
            &citation_output(
                r#"[{"handle": "[D1]", "collection_dataset": "c_ds", "file_hash": "aa"}]"#,
            ),
        );
        assert_eq!(search_refs.len(), 1);
        assert_eq!(cited.len(), 1);
        assert_eq!(search_refs[0].handle, "", "a search hit is not a citation");
        assert_eq!(cited[0].handle, "[D1]");
    }

    #[test]
    fn a_handle_number_is_read_only_out_of_a_real_handle() {
        assert_eq!(handle_number("[D12]"), Some(12));
        assert_eq!(handle_number("[D]"), None);
        assert_eq!(handle_number("[Dog]"), None);
        assert_eq!(handle_number("D1"), None);
        assert_eq!(handle_number(""), None);
    }

    #[test]
    fn a_doc_ref_snippet_is_clamped_before_it_reaches_the_transcript() {
        // One search hit carries up to SEARCH_SNIPPET_CHARS (1200) of page text, and a
        // turn surfaces a dozen. Rendered whole, one result buried the conversation.
        let long = "word ".repeat(500);
        let shown = doc_ref(&long).display_snippet();
        assert_eq!(shown.chars().count(), DOC_REF_SNIPPET_CHARS + 1);
        assert!(shown.ends_with('\u{2026}'));
    }

    #[test]
    fn a_short_snippet_is_passed_through_without_an_ellipsis() {
        let shown = doc_ref("  the matched   passage\n").display_snippet();
        assert_eq!(shown, "the matched passage");
    }

    #[test]
    fn clamping_never_cuts_a_multibyte_character_in_half() {
        // Extracted text is arbitrary: Romanian diacritics, CJK, base64 from an
        // attachment. Byte-slicing a &str here panics mid-codepoint.
        let text = "ă".repeat(DOC_REF_SNIPPET_CHARS + 50);
        let shown = clamp_display_text(&text, DOC_REF_SNIPPET_CHARS);
        assert_eq!(shown.chars().count(), DOC_REF_SNIPPET_CHARS + 1);
        assert!(shown.starts_with('ă'));

        let cjk = "埃菲尔铁塔".repeat(200);
        assert_eq!(
            clamp_display_text(&cjk, 10).chars().count(),
            11,
            "a clamp that counts bytes would split a 3-byte character"
        );
    }

    #[test]
    fn an_empty_snippet_clamps_to_empty_rather_than_an_ellipsis() {
        assert_eq!(clamp_display_text("", 400), "");
        assert_eq!(clamp_display_text("   \n  ", 400), "");
    }

    #[test]
    fn title_collapses_whitespace_and_truncates() {
        assert_eq!(title_from_message("  who   paid\nacme?  "), "who paid acme?");
        assert_eq!(title_from_message(""), "New chat");
        assert_eq!(title_from_message("   \n  "), "New chat");
        let long = "x".repeat(TITLE_CHARS + 10);
        let title = title_from_message(&long);
        assert_eq!(title.chars().count(), TITLE_CHARS + 1); // + the ellipsis
        assert!(title.ends_with('\u{2026}'));
    }

    #[test]
    fn title_of_exactly_the_limit_is_not_truncated() {
        let exact = "y".repeat(TITLE_CHARS);
        assert_eq!(title_from_message(&exact), exact);
    }

    /// One card per document, however many page-hits the tool returned for it.
    #[test]
    fn search_results_collapse_to_one_ref_per_document() {
        let row = |hash: &str, dataset: &str, page: u32, score: f64| {
            serde_json::json!({
                "collection_dataset": dataset,
                "collectionname": "c",
                "file_hash": hash,
                "path": "/a.txt",
                "page_id": page,
                "score": score,
                "snippet": format!("page {page}"),
            })
        };
        let content = serde_json::json!({"results": [
            row("aaa", "textfiles_extra", 1, 0.4),
            row("aaa", "textfiles_extra", 7, 0.9),
            row("bbb", "enron_maildir", 1, 0.5),
            row("aaa", "enron_maildir", 3, 0.2),
        ]});
        let refs = extract_from_search_results(&content);

        assert_eq!(refs.len(), 2, "three hits for `aaa` are one document");
        assert_eq!(refs[0].file_hash, "aaa", "rank order is preserved");
        assert_eq!(refs[1].file_hash, "bbb");
        // The best-scoring row survives, so the snippet is the passage worth reading.
        assert_eq!(refs[0].page_id, Some(7));
        assert_eq!(refs[0].snippet, "page 7");
        assert_eq!(refs[0].collection_dataset, "textfiles_extra");
        // The other dataset the same document was found in is kept, once.
        assert_eq!(refs[0].also_in, vec!["enron_maildir".to_string()]);
        assert!(refs[1].also_in.is_empty());
    }

    #[test]
    fn extract_doc_refs_from_search_collections() {
        let output = r#"{
            "output": {
                "content": {
                    "success": true,
                    "results": [{
                        "collectionname": "testdata",
                        "collection_dataset": "testdata_testfiles",
                        "file_hash": "abc123",
                        "path": "/pdf-scans/PublicWaterMassMailing.pdf",
                        "page_id": 0,
                        "score": 2921.0,
                        "snippet": "water testing"
                    }]
                },
                "name": "search_collections"
            }
        }"#;
        let refs = extract_doc_refs("search_collections", output);
        assert_eq!(refs.len(), 1);
        assert_eq!(refs[0].collection_dataset, "testdata_testfiles");
        assert_eq!(refs[0].file_hash, "abc123");
        assert_eq!(refs[0].display_title(), "PublicWaterMassMailing.pdf");
    }

    /// A realistic `web_search` payload: an envelope, a result list, long snippets.
    fn search_payload(results: usize, snippet_chars: usize) -> String {
        let rows: Vec<serde_json::Value> = (0..results)
            .map(|i| {
                serde_json::json!({
                    "title": format!("Result {i}"),
                    "url": format!("https://example.com/{i}"),
                    "snippet": "x".repeat(snippet_chars),
                    "sources": ["ddg_api", "yahoo"],
                })
            })
            .collect();
        serde_json::json!({
            "output": {
                "name": "web_search",
                "content": {
                    "success": true,
                    "query": "danube water level",
                    "sources_used": ["ddg_api", "yahoo", "wikipedia"],
                    "results": rows,
                }
            }
        })
        .to_string()
    }

    #[test]
    fn a_truncated_payload_is_still_parseable_json() {
        // The bug this replaces: chopping the serialised document at N chars left a `{`
        // with no `}`, the card parsed nothing, and the transcript told the user "the
        // result payload was not recorded" about a row it was holding.
        let raw = search_payload(60, 400);
        assert!(raw.chars().count() > 4_000);
        let out = truncate_tool_payload(&raw, 4_000);
        assert!(out.chars().count() <= 4_000);
        let v: serde_json::Value =
            serde_json::from_str(&out).expect("a truncated tool payload must still parse");
        assert_eq!(v["output"]["content"]["query"], "danube water level");
    }

    #[test]
    fn whole_results_are_dropped_rather_than_the_document_being_cut() {
        let raw = search_payload(60, 400);
        let out = truncate_tool_payload(&raw, 4_000);
        let v: serde_json::Value = serde_json::from_str(&out).unwrap();
        let results = v["output"]["content"]["results"].as_array().unwrap();
        assert!(!results.is_empty(), "some results must survive");
        assert!(results.len() < 60, "and some must have been dropped");
        // Best-first order: the ones kept are the ones the reader was going to read.
        assert_eq!(results[0]["title"], "Result 0");
        // Every surviving row is whole — no half-written last element.
        for row in results {
            assert!(row["url"].is_string() && row["snippet"].is_string());
        }
    }

    #[test]
    fn the_object_that_lost_rows_says_so() {
        let out = truncate_tool_payload(&search_payload(60, 400), 4_000);
        let v: serde_json::Value = serde_json::from_str(&out).unwrap();
        assert_eq!(v["output"]["content"]["truncated"], serde_json::json!(true));
    }

    #[test]
    fn a_payload_that_already_fits_is_returned_byte_for_byte() {
        let raw = search_payload(2, 40);
        assert_eq!(truncate_tool_payload(&raw, 24_000), raw);
    }

    #[test]
    fn a_document_whose_bulk_is_one_string_clips_the_string() {
        // Nothing to drop: a `get_document_text` result is one enormous field.
        let raw = serde_json::json!({"path": "/a.pdf", "text": "y".repeat(50_000)}).to_string();
        let out = truncate_tool_payload(&raw, 2_000);
        assert!(out.chars().count() <= 2_000);
        let v: serde_json::Value = serde_json::from_str(&out).expect("still JSON");
        assert_eq!(v["path"], "/a.pdf", "the fields that identify it survive");
        assert!(v["text"].as_str().unwrap().ends_with('\u{2026}'));
    }

    #[test]
    fn a_payload_that_is_not_json_falls_back_to_cutting_it() {
        // The cards render these bytes rather than claiming nothing was recorded.
        let raw = "z".repeat(500);
        let out = truncate_tool_payload(&raw, 100);
        assert_eq!(out.chars().count(), 101);
        assert!(out.ends_with('\u{2026}'));
    }

    #[test]
    fn a_rate_limit_error_yields_its_retry_after_however_it_is_wrapped() {
        // The message reaches the browser through ServerFnError, which is free to wrap it.
        // A prefix match got this right only by luck.
        assert_eq!(rate_limited_seconds("rate_limited:12"), Some(12));
        assert_eq!(
            rate_limited_seconds("error running server function: rate_limited:7 polling too fast (1min window)"),
            Some(7)
        );
        assert_eq!(rate_limited_seconds("rate_limited: 30 "), Some(30));
    }

    #[test]
    fn anything_else_stays_a_real_error() {
        // The failure mode this guards: treating an unknown error as "wait and retry"
        // makes a dead backend look like a slow one, forever.
        assert_eq!(rate_limited_seconds("connection refused"), None);
        assert_eq!(rate_limited_seconds("rate_limited:soon"), None);
        assert_eq!(rate_limited_seconds(""), None);
    }

    #[test]
    fn extract_doc_refs_from_get_document_text_without_dataset() {
        let output = r#"{
            "output": {
                "content": {
                    "collectionname": "testdata",
                    "file_hash": "abc123",
                    "path": "/x.pdf"
                },
                "name": "get_document_text"
            }
        }"#;
        let refs = extract_doc_refs("get_document_text", output);
        assert_eq!(refs.len(), 1);
        assert!(refs[0].collection_dataset.is_empty());
        assert_eq!(refs[0].file_hash, "abc123");
    }
}
