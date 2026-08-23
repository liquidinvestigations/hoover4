//! Storage for AI Chat sessions and their message trajectories.
//!
//! **Every function here takes a `username` and filters on it.** Ownership is not
//! checked once at the edge and then trusted: a transcript can quote documents from
//! restricted collections, so the owner is part of the primary key of every query. A
//! session id alone is never sufficient to read a conversation.

pub mod artifacts;

use common::chat_types::{ChatMessageItem, ChatOptions, ChatRole, ChatSessionItem};
use time::format_description::well_known::Rfc3339;

use crate::db_auth::{insert_row, now};
use crate::db_utils::clickhouse_utils::get_global_client;

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct ChatSessionRow {
    pub session_id: String,
    pub username: String,
    pub title: String,
    #[serde(default)]
    pub summary: String,
    pub collections: Vec<String>,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub created_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub updated_at: time::OffsetDateTime,
    pub is_deleted: u8,
    #[serde(default)]
    pub use_internet_tools: u8,
    #[serde(default)]
    pub deep_research: u8,
    #[serde(default)]
    pub options_locked: u8,
    /// Running maximum of `ChatMessageRow::peak_context_tokens` over the conversation's
    /// turns, written by the worker. **Carried through every read-modify-write here**,
    /// like every other column on this row: `chat_sessions` is a ReplacingMergeTree, so
    /// a writer that omits a column writes a fresher row with the column's default and
    /// silently erases what another writer put there.
    #[serde(default)]
    pub peak_context_tokens: u32,
}

impl ChatSessionRow {
    pub fn options(&self) -> ChatOptions {
        // Before the first turn nothing is frozen, so the composer defaults apply
        // rather than the zeroes this row was created with.
        if self.options_locked == 0 {
            return ChatOptions::default();
        }
        ChatOptions {
            deep_research: self.deep_research != 0,
            internet_tools: self.use_internet_tools != 0,
            locked: true,
        }
    }
}

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct ChatMessageRow {
    pub session_id: String,
    pub username: String,
    pub seq: u32,
    pub role: String,
    pub content: String,
    pub tool_name: String,
    #[serde(default)]
    pub tool_input: String,
    #[serde(default)]
    pub tool_output: String,
    #[serde(default)]
    pub doc_refs: String,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub created_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub updated_at: time::OffsetDateTime,
    /// Milliseconds since Unix epoch. Matches `DateTime64(3)` on the wire.
    pub created_ms: i64,
    #[serde(default)]
    pub agent_duration_ms: u32,
    #[serde(default)]
    pub retry_errors: String,
    /// The model that produced this row, empty for user and tool rows. Recorded per
    /// message rather than per session: model selection is a per-message choice, and a
    /// transcript that mixes two models is only readable if each row says which.
    #[serde(default)]
    pub model: String,
    /// Reasoning content stripped out of the answer body, rendered behind a disclosure.
    /// A reasoning model narrates its plan on the same channel as its answer; keeping
    /// the two apart here is what stops the scratchpad reaching the transcript.
    #[serde(default)]
    pub reasoning: String,
    /// Per-turn uuid, shared by every row a turn writes. `next_seq` is max(seq)+1 with
    /// no database-side sequence, so two senders can pick the same seq; the uuid makes
    /// that collision detectable instead of silently keeping one message.
    #[serde(default)]
    pub message_uuid: String,
    /// Prompt tokens of the first model call of this turn, the conversation as the
    /// model received it. 0 means nothing counted it, never "no tokens".
    #[serde(default)]
    pub context_tokens: u32,
    /// Largest prompt plus completion any single model call in this turn was billed for,
    /// across every round a nag loop added. 0 means unknown.
    #[serde(default)]
    pub peak_context_tokens: u32,
    /// The model's context window as the catalog knew it at the time of the turn. 0
    /// means the provider never stated one and the percentage must not be shown.
    #[serde(default)]
    pub context_window: u32,
}

/// One version of an in-flight row in `chat_message_stream`.
#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct ChatStreamRow {
    pub session_id: String,
    pub username: String,
    pub seq: u32,
    pub role: String,
    pub content: String,
    #[serde(default)]
    pub reasoning: String,
    #[serde(default)]
    pub tool_name: String,
    pub is_final: u8,
    /// Milliseconds since Unix epoch. Matches `DateTime64(3)` on the wire, same as
    /// `ChatMessageRow::created_ms`.
    pub updated_at: i64,
    #[serde(default)]
    pub message_uuid: String,
    #[serde(default)]
    pub tool_call_index: u32,
}

const SESSION_SELECT: &str = "SELECT session_id, username, title, summary, collections, created_at, \
     updated_at, is_deleted, use_internet_tools, deep_research, options_locked, \
     peak_context_tokens FROM chat_sessions FINAL";

const MESSAGE_SELECT: &str = "SELECT session_id, username, seq, role, content, tool_name, \
     tool_input, tool_output, doc_refs, created_at, updated_at, created_ms, agent_duration_ms, \
     retry_errors, model, reasoning, message_uuid, context_tokens, peak_context_tokens, \
     context_window FROM chat_messages FINAL";

fn fmt(dt: time::OffsetDateTime) -> String {
    dt.format(&Rfc3339).unwrap_or_else(|_| dt.to_string())
}

fn fmt_ms(ms: i64) -> String {
    match time::OffsetDateTime::from_unix_timestamp_nanos((ms as i128) * 1_000_000) {
        Ok(dt) => fmt(dt),
        Err(_) => ms.to_string(),
    }
}

/// Random id for a new chat. Reuses the web-session generator rather than adding a uuid
/// dependency. It is the same shape of value (opaque, unguessable, hex) and this
/// codebase already trusts it for auth cookies.
fn generate_chat_session_id() -> String {
    crate::db_auth::sessions::generate_session_id()
}

pub async fn create_session(
    username: &str,
    title: &str,
    collections: &[String],
) -> anyhow::Result<String> {
    let session_id = generate_chat_session_id();
    let row = ChatSessionRow {
        session_id: session_id.clone(),
        username: username.to_string(),
        title: title.to_string(),
        summary: String::new(),
        collections: collections.to_vec(),
        created_at: now(),
        updated_at: now(),
        is_deleted: 0,
        use_internet_tools: 0,
        deep_research: 0,
        options_locked: 0,
        // Nothing has been counted yet. The worker raises it as turns complete.
        peak_context_tokens: 0,
    };
    insert_row("chat_sessions", &row).await?;
    Ok(session_id)
}

pub async fn get_session(
    username: &str,
    session_id: &str,
) -> anyhow::Result<Option<ChatSessionRow>> {
    let client = get_global_client();
    let mut rows = client
        .query(&format!(
            "{SESSION_SELECT} WHERE username = ? AND session_id = ? AND is_deleted = 0"
        ))
        .bind(username)
        .bind(session_id)
        .fetch_all::<ChatSessionRow>()
        .await?;
    Ok(rows.pop())
}

/// Session headers by id, for the admin live-run panel.
///
/// **The one function here that does not filter on a username**, because its caller does
/// not have one: a Temporal visibility query knows the session a running turn belongs to
/// and nothing else. The exception is narrow on purpose. It returns the header a panel
/// renders (owner, title, frozen switches) and never a message, so it cannot become a way
/// to read someone's transcript. The caller checks for admin before it asks.
pub async fn sessions_by_ids(session_ids: &[String]) -> anyhow::Result<Vec<ChatSessionRow>> {
    if session_ids.is_empty() {
        return Ok(Vec::new());
    }
    let client = get_global_client();
    let rows = client
        .query(&format!(
            "{SESSION_SELECT} WHERE session_id IN ? AND is_deleted = 0"
        ))
        .bind(session_ids)
        .fetch_all::<ChatSessionRow>()
        .await?;
    Ok(rows)
}

/// Sessions of one user, most recently active first.
pub async fn list_sessions(username: &str, limit: u32) -> anyhow::Result<Vec<ChatSessionItem>> {
    let client = get_global_client();
    let rows = client
        .query(&format!(
            "{SESSION_SELECT} WHERE username = ? AND is_deleted = 0 \
             ORDER BY updated_at DESC LIMIT ?"
        ))
        .bind(username)
        .bind(limit)
        .fetch_all::<ChatSessionRow>()
        .await?;

    // Message counts in one grouped query rather than one per session.
    let counts: Vec<(String, u64)> = client
        .query(
            "SELECT session_id, count() FROM chat_messages FINAL \
             WHERE username = ? GROUP BY session_id",
        )
        .bind(username)
        .fetch_all()
        .await?;
    let counts: std::collections::HashMap<String, u64> = counts.into_iter().collect();

    Ok(rows
        .into_iter()
        .map(|r| ChatSessionItem {
            message_count: counts.get(&r.session_id).copied().unwrap_or(0) as u32,
            options: r.options(),
            session_id: r.session_id,
            title: r.title,
            summary: r.summary,
            collections: r.collections,
            created_at: fmt(r.created_at),
            updated_at: fmt(r.updated_at),
        })
        .collect())
}

pub async fn list_messages(
    username: &str,
    session_id: &str,
) -> anyhow::Result<Vec<ChatMessageItem>> {
    let client = get_global_client();
    let rows = client
        .query(&format!(
            "{MESSAGE_SELECT} WHERE username = ? AND session_id = ? ORDER BY seq"
        ))
        .bind(username)
        .bind(session_id)
        .fetch_all::<ChatMessageRow>()
        .await?;

    Ok(rows
        .into_iter()
        .map(|r| ChatMessageItem {
            seq: r.seq,
            role: ChatRole::from_str(&r.role),
            content: r.content,
            tool_name: r.tool_name,
            tool_input: r.tool_input,
            tool_output: r.tool_output,
            doc_refs: r.doc_refs,
            created_at: fmt(r.created_at),
            created_ms: fmt_ms(r.created_ms),
            agent_duration_ms: r.agent_duration_ms,
            retry_errors: r.retry_errors,
            reasoning: r.reasoning,
            context_tokens: r.context_tokens,
            peak_context_tokens: r.peak_context_tokens,
            context_window: r.context_window,
            streaming: false,
        })
        .collect())
}

/// Finished rows with `seq > after_seq`. The poll endpoint's incremental read.
/// `after_seq` of -1 returns the whole transcript (a client that has nothing yet).
pub async fn list_messages_after(
    username: &str,
    session_id: &str,
    after_seq: i64,
) -> anyhow::Result<Vec<ChatMessageItem>> {
    let client = get_global_client();
    let rows = client
        .query(&format!(
            "{MESSAGE_SELECT} WHERE username = ? AND session_id = ? AND seq > ? ORDER BY seq"
        ))
        .bind(username)
        .bind(session_id)
        .bind(after_seq)
        .fetch_all::<ChatMessageRow>()
        .await?;

    Ok(rows
        .into_iter()
        .map(|r| ChatMessageItem {
            seq: r.seq,
            role: ChatRole::from_str(&r.role),
            content: r.content,
            tool_name: r.tool_name,
            tool_input: r.tool_input,
            tool_output: r.tool_output,
            doc_refs: r.doc_refs,
            created_at: fmt(r.created_at),
            created_ms: fmt_ms(r.created_ms),
            agent_duration_ms: r.agent_duration_ms,
            retry_errors: r.retry_errors,
            reasoning: r.reasoning,
            context_tokens: r.context_tokens,
            peak_context_tokens: r.peak_context_tokens,
            context_window: r.context_window,
            streaming: false,
        })
        .collect())
}

/// The next free `seq` in a session.
///
/// ClickHouse has no sequences and no row locks, so this is only safe under
/// [`turn_lock`]: every caller that allocates seqs for a session holds that session's
/// lock for the whole turn, which serialises allocation *and* keeps a second turn's
/// history read from racing the first turn's writes. [`detect_seq_collision`] is the
/// detector for anything that still slips through (two website processes, say).
///
/// **`chat_message_stream` counts too.** Deep research allocates its answer seq up front
/// and reserves it as a *stream* row. The transcript row only appears when the Temporal
/// workflow finishes, minutes later. A `next_seq` that looked only at `chat_messages`
/// therefore handed the reserved seq straight back to the next inline send, and since
/// `chat_messages` is read `FINAL`, the later write won and one message disappeared from
/// the conversation with no error anywhere. The turn lock does not cover this: it is
/// released when `start_research_task` returns, long before the workflow writes.
pub async fn next_seq(username: &str, session_id: &str) -> anyhow::Result<u32> {
    let client = get_global_client();
    // ClickHouse types `max(seq) + 1` as UInt64; cast so the client can decode it.
    let max: u32 = client
        .query(
            "SELECT toUInt32(ifNull(max(seq) + 1, 0)) FROM ( \
                 SELECT seq FROM chat_messages FINAL \
                 WHERE username = ? AND session_id = ? \
                 UNION ALL \
                 SELECT seq FROM chat_message_stream \
                 WHERE username = ? AND session_id = ? \
                   AND updated_at > now64(3) - INTERVAL 1 DAY \
             )",
        )
        .bind(username)
        .bind(session_id)
        .bind(username)
        .bind(session_id)
        .fetch_one()
        .await?;
    Ok(max)
}

/// Confirm that `seq` in this session belongs to the turn that just claimed it.
///
/// This is what `message_uuid` is *for*. Every row of one turn carries the same uuid, so
/// two rows at the same seq with different uuids means two writers allocated the same
/// seq. The exact outcome `next_seq` cannot rule out without a database-side sequence.
/// Until now the column was written by every path and read by none, which detected
/// nothing; a write-only detector is worse than no detector, because it reads as covered.
///
/// Called after the claiming row is written, so the collision is reported rather than
/// prevented: `chat_messages` is a ReplacingMergeTree and one of the two rows is already
/// doomed. The caller's job is to refuse the turn and tell the user to resend, which
/// loses a keystroke instead of a message.
///
/// Reads **without** `FINAL` on purpose: `FINAL` collapses the versions to one and that
/// is precisely the evidence being looked for.
pub async fn detect_seq_collision(
    username: &str,
    session_id: &str,
    seq: u32,
    expected_uuid: &str,
) -> anyhow::Result<()> {
    if expected_uuid.is_empty() {
        return Ok(());
    }
    let client = get_global_client();
    let others: Vec<String> = client
        .query(
            "SELECT DISTINCT message_uuid FROM chat_messages \
             WHERE username = ? AND session_id = ? AND seq = ? AND message_uuid != ? \
               AND message_uuid != '' LIMIT 5",
        )
        .bind(username)
        .bind(session_id)
        .bind(seq)
        .bind(expected_uuid)
        .fetch_all::<String>()
        .await?;
    if others.is_empty() {
        return Ok(());
    }
    tracing::error!(
        "seq collision in session {session_id} at seq {seq}: this turn is {expected_uuid}, \
         but {others:?} already claimed it, so a message will be lost to ReplacingMergeTree"
    );
    anyhow::bail!(
        "another message was written to this conversation at the same time; please send it again"
    )
}


/// Fields written for one trajectory row beyond the required role/content.
#[derive(Debug, Clone, Default)]
pub struct AppendMessageExtras {
    pub tool_name: String,
    pub tool_input: String,
    pub tool_output: String,
    pub doc_refs: String,
    pub agent_duration_ms: u32,
    /// JSON array of errors from earlier attempts, for an `error` row.
    pub retry_errors: String,
    /// Model that produced the row, empty for user and tool rows.
    pub model: String,
    /// Reasoning kept out of the answer body.
    pub reasoning: String,
    /// Per-turn uuid, see `ChatMessageRow::message_uuid`.
    pub message_uuid: String,
    /// Token accounting for an assistant row, see `ChatMessageRow`. Left at 0 by every
    /// writer that is not the one the model answered through, which readers show as
    /// unknown.
    pub context_tokens: u32,
    pub peak_context_tokens: u32,
    pub context_window: u32,
}

pub async fn append_message(
    username: &str,
    session_id: &str,
    seq: u32,
    role: ChatRole,
    content: &str,
    extras: AppendMessageExtras,
) -> anyhow::Result<()> {
    let ts = now();
    let row = ChatMessageRow {
        session_id: session_id.to_string(),
        username: username.to_string(),
        seq,
        role: role.as_str().to_string(),
        content: content.to_string(),
        tool_name: extras.tool_name,
        tool_input: extras.tool_input,
        tool_output: extras.tool_output,
        doc_refs: extras.doc_refs,
        created_at: ts,
        updated_at: ts,
        created_ms: ts.unix_timestamp_nanos() as i64 / 1_000_000,
        agent_duration_ms: extras.agent_duration_ms,
        retry_errors: extras.retry_errors,
        model: extras.model,
        reasoning: extras.reasoning,
        message_uuid: extras.message_uuid,
        context_tokens: extras.context_tokens,
        peak_context_tokens: extras.peak_context_tokens,
        context_window: extras.context_window,
    };
    insert_row("chat_messages", &row).await
}

#[cfg(test)]
mod live_tests {
    use super::*;
    use common::chat_types::ChatRole;

    /// Run with: cargo test -p backend --lib db_chat::live_tests -- --ignored --nocapture
    #[tokio::test]
    #[ignore = "needs live clickhouse"]
    async fn can_append_and_list_a_tool_payload_row() {
        let username = "live-test-chat";
        let session_id = create_session(username, "live", &[])
            .await
            .expect("create_session");
        let seq = next_seq(username, &session_id).await.expect("next_seq");
        append_message(
            username,
            &session_id,
            seq,
            ChatRole::User,
            "hello from live test",
            AppendMessageExtras::default(),
        )
        .await
        .expect("append_message");
        let msgs = list_messages(username, &session_id).await.expect("list");
        assert!(msgs.iter().any(|m| m.content.contains("hello from live test")));
        assert!(msgs.iter().any(|m| !m.created_ms.is_empty()));
    }
}

/// Update a session's title and/or collection selection, and bump `updated_at` so it
/// rises to the top of the history list.
pub async fn touch_session(
    username: &str,
    session_id: &str,
    title: Option<&str>,
    collections: Option<&[String]>,
) -> anyhow::Result<()> {
    let Some(mut row) = get_session(username, session_id).await? else {
        anyhow::bail!("chat session not found");
    };
    if let Some(t) = title {
        row.title = t.to_string();
    }
    if let Some(c) = collections {
        row.collections = c.to_vec();
    }
    row.updated_at = now();
    insert_row("chat_sessions", &row).await
}

/// Freeze the Deep Research / Internet tools switches onto the conversation.
///
/// Called once, from the first message. Later calls are no-ops so a second turn cannot
/// silently change which agent the transcript was produced by, which is what the lock
/// is for. Returns the options now in force.
pub async fn lock_session_options(
    username: &str,
    session_id: &str,
    requested: ChatOptions,
) -> anyhow::Result<ChatOptions> {
    let Some(mut row) = get_session(username, session_id).await? else {
        anyhow::bail!("chat session not found");
    };
    if row.options_locked != 0 {
        return Ok(row.options());
    }
    row.use_internet_tools = u8::from(requested.internet_tools);
    row.deep_research = u8::from(requested.deep_research);
    row.options_locked = 1;
    row.updated_at = now();
    insert_row("chat_sessions", &row).await?;
    Ok(row.options())
}

/// Set title and/or summary without clearing the other.
pub async fn set_session_title_summary(
    username: &str,
    session_id: &str,
    title: Option<&str>,
    summary: Option<&str>,
) -> anyhow::Result<()> {
    let Some(mut row) = get_session(username, session_id).await? else {
        anyhow::bail!("chat session not found");
    };
    if let Some(t) = title {
        row.title = t.to_string();
    }
    if let Some(s) = summary {
        row.summary = s.to_string();
    }
    row.updated_at = now();
    insert_row("chat_sessions", &row).await
}

pub async fn delete_session(username: &str, session_id: &str) -> anyhow::Result<()> {
    let Some(mut row) = get_session(username, session_id).await? else {
        return Ok(());
    };
    // Artifacts go with the conversation, in the same operation. A tombstone rather than
    // a delete: the sweeper needs the row to know which blob-store objects to remove, and a
    // ClickHouse delete would leave those bytes with nothing pointing at them.
    //
    // Failure here is logged and does not block the session delete: the user asked for
    // the chat to go, and the sweeper's prefix scan collects orphaned objects anyway.
    if let Err(e) = artifacts::soft_delete_session_artifacts(username, session_id).await {
        tracing::error!("could not soft-delete artifacts for session {session_id}: {e}");
    }
    row.is_deleted = 1;
    row.updated_at = now();
    insert_row("chat_sessions", &row).await
}

// ---------------------------------------------------------------------------
// Streaming: chat_message_stream holds the in-flight turn, one row per partial
// write, so chat_messages keeps its write-once-per-completed-row discipline.
// ---------------------------------------------------------------------------

/// One turn runs at a time per session. The lock is what makes `next_seq` safe and
/// what keeps a fast second send from reading a history the first turn has not
/// finished writing. Same `Mutex<HashMap>` idiom as `api/chat/live_runs.rs`.
static TURN_LOCKS: std::sync::LazyLock<
    std::sync::Mutex<std::collections::HashMap<String, std::sync::Arc<tokio::sync::Mutex<()>>>>,
> = std::sync::LazyLock::new(|| std::sync::Mutex::new(std::collections::HashMap::new()));

/// The per-session turn lock. Hold the guard for the whole turn (user row through
/// finalisation). Never await the agent without holding it.
///
/// Entries are evicted opportunistically, on the way in. Nothing ever removed them, so a
/// long-lived process accumulated one `Arc<Mutex>` per conversation it had ever served.
/// Small, but unbounded and proportional to traffic, which is the definition of a leak. An
/// entry nobody else holds an `Arc` to has no waiter and no holder, so dropping it is
/// invisible: the next caller for that session simply gets a fresh lock.
pub fn turn_lock(username: &str, session_id: &str) -> std::sync::Arc<tokio::sync::Mutex<()>> {
    let key = format!("{username}:{session_id}");
    let mut locks = TURN_LOCKS.lock().unwrap_or_else(|e| e.into_inner());
    // Cheap enough to do on every call at this map's size, and it keeps the eviction next
    // to the insertion where the invariant is readable. `strong_count == 1` means this map
    // is the only owner.
    locks.retain(|k, lock| k == &key || std::sync::Arc::strong_count(lock) > 1);
    std::sync::Arc::clone(
        locks
            .entry(key)
            .or_insert_with(|| std::sync::Arc::new(tokio::sync::Mutex::new(()))),
    )
}

/// Write (or rewrite) one in-flight row. Same (username, session_id, seq) replaces by
/// `updated_at`, so a growing assistant partial is one logical row rewritten as tokens
/// arrive. `tool_call_index` orders a turn's tool rows; the assistant row keeps 0.
#[allow(clippy::too_many_arguments)]
pub async fn append_stream_row(
    username: &str,
    session_id: &str,
    seq: u32,
    role: ChatRole,
    content: &str,
    reasoning: &str,
    tool_name: &str,
    tool_call_index: u32,
    is_final: bool,
    message_uuid: &str,
) -> anyhow::Result<()> {
    let row = ChatStreamRow {
        session_id: session_id.to_string(),
        username: username.to_string(),
        seq,
        role: role.as_str().to_string(),
        content: content.to_string(),
        reasoning: reasoning.to_string(),
        tool_name: tool_name.to_string(),
        is_final: u8::from(is_final),
        updated_at: now().unix_timestamp_nanos() as i64 / 1_000_000,
        message_uuid: message_uuid.to_string(),
        tool_call_index,
    };
    insert_row("chat_message_stream", &row).await
}

/// The live state of every non-final stream row in a session.
///
/// `argMax` per `seq`, never a bare SELECT: a ReplacingMergeTree read without an
/// aggregate can return an older part and the visible text would shrink mid-stream.
/// The TTL is applied lazily at merge time, so the freshness filter is part of the
/// query, not something to trust the table with.
///
/// Two rules collide here, and the nesting is what satisfies both.
///
/// * ClickHouse resolves identifiers against SELECT aliases first, so
///   `max(updated_at) AS updated_at` makes every sibling `argMax(…, updated_at)` read as
///   an aggregate inside an aggregate: `Code: 184, ILLEGAL_AGGREGATION`, whole query
///   dead. The aggregates therefore land on `last_*` aliases.
/// * `clickhouse::Row` matches columns **by name**, not by position. A `last_role`
///   column with a `role` field is `schema mismatch: … column last_role … not found in
///   the struct definition`, which fails just as hard.
///
/// So: aggregate under `last_*` in the inner query, rename back to the struct's names in
/// the outer one.
pub async fn read_stream_rows(
    username: &str,
    session_id: &str,
) -> anyhow::Result<Vec<ChatStreamRow>> {
    let client = get_global_client();
    let rows = client
        .query(
            "SELECT session_id, username, seq, \
                    last_role AS role, \
                    last_content AS content, \
                    last_reasoning AS reasoning, \
                    last_tool_name AS tool_name, \
                    last_is_final AS is_final, \
                    last_updated_at AS updated_at, \
                    last_message_uuid AS message_uuid, \
                    last_tool_call_index AS tool_call_index \
             FROM ( \
                 SELECT session_id, username, seq, \
                        argMax(role, updated_at) AS last_role, \
                        argMax(content, updated_at) AS last_content, \
                        argMax(reasoning, updated_at) AS last_reasoning, \
                        argMax(tool_name, updated_at) AS last_tool_name, \
                        argMax(is_final, updated_at) AS last_is_final, \
                        max(updated_at) AS last_updated_at, \
                        argMax(message_uuid, updated_at) AS last_message_uuid, \
                        argMax(tool_call_index, updated_at) AS last_tool_call_index \
                 FROM chat_message_stream \
                 WHERE username = ? AND session_id = ? \
                   AND updated_at > now64(3) - INTERVAL 1 HOUR \
                 GROUP BY session_id, username, seq \
             ) \
             ORDER BY seq",
        )
        .bind(username)
        .bind(session_id)
        .fetch_all::<ChatStreamRow>()
        .await?;
    Ok(rows)
}

/// `(last user seq, last assistant-or-error seq)` in a session, `None` for absent.
///
/// This is how "is a turn still being produced" is answered: a turn is open when the
/// last user row has no assistant or error row after it. Deriving that from the
/// *transcript* rather than from an open stream row is what makes it reliable. The
/// stream writer finalises one row and opens the next as two separate inserts, and a
/// poll landing between them would otherwise see a turn that had vanished.
///
/// `seq` starts at 1 (`next_seq` on an empty session returns 1), so 0 safely means
/// "no such row".
pub async fn turn_boundaries(
    username: &str,
    session_id: &str,
) -> anyhow::Result<(Option<u32>, Option<u32>)> {
    let client = get_global_client();
    let (user_seq, answer_seq) = client
        .query(
            "SELECT maxIf(seq, role = 'user') AS last_user, \
                    maxIf(seq, role IN ('assistant', 'error')) AS last_answer \
             FROM chat_messages FINAL \
             WHERE username = ? AND session_id = ?",
        )
        .bind(username)
        .bind(session_id)
        .fetch_one::<(u32, u32)>()
        .await?;
    Ok((
        (user_seq > 0).then_some(user_seq),
        (answer_seq > 0).then_some(answer_seq),
    ))
}

/// Mark one stream row final (a finalised tool row, or an assistant partial whose seq
/// a starting tool is taking over). Re-inserts the newest version with `is_final = 1`.
pub async fn mark_stream_row_final(
    username: &str,
    session_id: &str,
    seq: u32,
) -> anyhow::Result<()> {
    let rows = read_stream_rows(username, session_id).await?;
    for row in rows.into_iter().filter(|r| r.seq == seq && r.is_final == 0) {
        append_stream_row(
            username,
            session_id,
            row.seq,
            ChatRole::from_str(&row.role),
            &row.content,
            &row.reasoning,
            &row.tool_name,
            row.tool_call_index,
            true,
            &row.message_uuid,
        )
        .await?;
    }
    Ok(())
}

/// Mark every stream row of a session final. The turn is over (one way or another)
/// and the rows are only kept around for the TTL to collect. Reads filter on
/// `is_final = 0`, so this is also how an interrupted turn is dismissed.
pub async fn mark_stream_final(username: &str, session_id: &str) -> anyhow::Result<()> {
    let rows = read_stream_rows(username, session_id).await?;
    for row in rows.into_iter().filter(|r| r.is_final == 0) {
        append_stream_row(
            username,
            session_id,
            row.seq,
            ChatRole::from_str(&row.role),
            &row.content,
            &row.reasoning,
            &row.tool_name,
            row.tool_call_index,
            true,
            &row.message_uuid,
        )
        .await?;
    }
    Ok(())
}
