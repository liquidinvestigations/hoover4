//! AI Chat API: sessions, trajectories, and asking the agent a question.
//!
//! The security property this module exists to hold: **an agent answering for a user
//! can only read collections that user could read in the search UI.** That is enforced
//! in one place — [`send_message`] resolves the live permission set and passes it to the
//! agent, which passes it to the MCP servers. The collection selection stored on a
//! session is a *preference*; it is intersected with live permissions on every message,
//! so a permission revoked after a chat started takes effect on the next message.

pub mod agent_client;
pub mod live_runs;
pub mod llm_events;
pub mod summarize;

use std::time::{Duration, Instant};

use common::chat_types::{
    extract_doc_refs, title_from_message, truncate_tool_payload, ChatOptions, ChatPollResult, ChatRole,
    ChatSendResult, ChatSessionDetail, ChatSessionItem, StreamToolRow, StreamTurn,
    MAX_MESSAGE_CHARS, TOOL_PAYLOAD_CHARS,
};
use common::current_user::CurrentUser;

use crate::api::rate_limit::{check_and_record, RateLimitKind};
use crate::api::telemetry::{self, EVENT_LLM_CHAT_MESSAGE, EVENT_LLM_MCP_TOOL_CALL};
use crate::db_chat::{self, AppendMessageExtras};
use crate::db_utils::clickhouse_utils::list_permitted_collections;

/// Cap on sessions returned to the history sidebar / homepage.
const SESSION_LIST_LIMIT: u32 = 100;

/// How much of a tool call's payload is stored in the short `content` summary column.
const TOOL_SUMMARY_CHARS: usize = 400;

/// Reject anonymous use. Guests are allowed only when demo mode is on
/// (`HOOVER4_DEMO_MODE`), keyed by their `guest-*` username like any other user.
///
/// Revisit whether guests should have LLM access at all — see `website/Readme.md`.
fn require_named_user(user: &CurrentUser) -> anyhow::Result<&str> {
    require_named_user_inner(user, crate::auth::session_middleware::demo_mode())
}

fn require_named_user_inner(user: &CurrentUser, demo: bool) -> anyhow::Result<&str> {
    if user.username.is_empty() {
        anyhow::bail!("no user in session");
    }
    if user.is_guest && !demo {
        anyhow::bail!("AI Chat requires a signed-in user; guest sessions have no chat history outside demo mode");
    }
    Ok(&user.username)
}

pub async fn list_chat_sessions(user: &CurrentUser) -> anyhow::Result<Vec<ChatSessionItem>> {
    let username = require_named_user(user)?;
    db_chat::list_sessions(username, SESSION_LIST_LIMIT).await
}

/// Start a new conversation.
///
/// The requested collections are intersected with what the user may actually read, so a
/// crafted request cannot seed a session with a collection the user has no access to.
pub async fn create_chat_session(
    user: &CurrentUser,
    collections: Vec<String>,
) -> anyhow::Result<String> {
    let username = require_named_user(user)?;
    let permitted = list_permitted_collections(user).await?;
    let selected = intersect_collections(&collections, &permitted);
    db_chat::create_session(username, "New chat", &selected).await
}

pub async fn get_chat_session(
    user: &CurrentUser,
    session_id: String,
) -> anyhow::Result<ChatSessionDetail> {
    let username = require_named_user(user)?;
    let row = db_chat::get_session(username, &session_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("chat session not found"))?;
    let messages = db_chat::list_messages(username, &session_id).await?;
    let available_collections = list_permitted_collections(user).await?;
    let tail = stream_state(username, &session_id).await?;

    let options = row.options();
    Ok(ChatSessionDetail {
        session: ChatSessionItem {
            session_id: row.session_id,
            title: row.title,
            summary: row.summary,
            collections: row.collections,
            created_at: String::new(),
            updated_at: String::new(),
            message_count: messages.len() as u32,
            options,
        },
        messages,
        available_collections,
        stream: tail.stream,
        active: tail.active,
        interrupted: tail.interrupted,
    })
}

pub async fn delete_chat_session(user: &CurrentUser, session_id: String) -> anyhow::Result<()> {
    let username = require_named_user(user)?;
    db_chat::delete_session(username, &session_id).await
}

/// The search-detail JSON behind a `web_search` card's popup.
///
/// Served through a server function rather than the `/_chat_artifact/…` route because the
/// popup renders it, and a fetch from WASM would need its own credential handling and its
/// own copy of the ACL. Images and the archived-page iframe still use the HTTP route —
/// `<img src>` and `<iframe src>` cannot call a server function.
///
/// Same rule as the route: the id is a lookup key from an LLM-driven tool payload, so it
/// is resolved to its owner and checked, never trusted.
pub async fn get_chat_artifact_detail(
    user: &CurrentUser,
    artifact_id: String,
) -> anyhow::Result<String> {
    let username = require_named_user(user)?;
    let Some(row) = db_chat::artifacts::get_artifact(&artifact_id).await? else {
        // Phrased to match `guard::is_not_found`, so this answers 404 rather than 500.
        anyhow::bail!("artifact not found");
    };
    if row.username != username && !user.is_admin {
        anyhow::bail!("forbidden: this artifact belongs to another user");
    }
    if row.body_key.is_empty() {
        anyhow::bail!(
            "{}",
            if row.detail.is_empty() { "this artifact has no detail document" } else { &row.detail }
        );
    }
    crate::server_extra::chat_artifact::fetch_artifact_object(&row.body_key)
        .await
        .map(|bytes| String::from_utf8_lossy(&bytes).into_owned())
}

/// Change which collections a conversation searches.
pub async fn set_chat_collections(
    user: &CurrentUser,
    session_id: String,
    collections: Vec<String>,
) -> anyhow::Result<()> {
    let username = require_named_user(user)?;
    let permitted = list_permitted_collections(user).await?;
    let selected = intersect_collections(&collections, &permitted);
    db_chat::touch_session(username, &session_id, None, Some(&selected)).await
}

/// Serialise the failed-attempt list for the `retry_errors` column. Empty stays empty
/// rather than becoming `"[]"`, so "no retries" costs no bytes on the overwhelmingly
/// common row.
fn encode_errors(errors: &[String]) -> String {
    if errors.is_empty() {
        return String::new();
    }
    serde_json::to_string(errors).unwrap_or_default()
}

/// Keep only requested collections the user may actually read.
///
/// An empty request means "everything I am allowed to see" — that is the useful default
/// for a chat, and it stays correct as permissions change because it is re-resolved on
/// every message rather than frozen into the session.
pub fn intersect_collections(requested: &[String], permitted: &[String]) -> Vec<String> {
    if requested.is_empty() {
        return permitted.to_vec();
    }
    let allowed: std::collections::HashSet<&String> = permitted.iter().collect();
    let mut out: Vec<String> = requested
        .iter()
        .filter(|c| allowed.contains(c))
        .cloned()
        .collect();
    out.sort();
    out.dedup();
    out
}

/// Send one user message; the agent turn runs in a spawned task.
///
/// The user row, the seq allocation and the history read happen **here**, under the
/// session's turn lock, before this returns: the caller gets a transcript that already
/// contains the message it just sent, and the returned `seq` is the one the poller
/// counts from. Only the agent call and the finalisation move to the spawned task,
/// which inherits the lock guard and the live-run registration and holds both until the
/// turn is completely written.
///
/// The lock is taken with `try_lock`: one turn at a time per session. A second send
/// while a turn is running is a client bug (the composer shows a stop button, not a
/// send button), and blocking the request for the length of an agent run would be worse
/// than saying so.
///
/// When the rate limiter refuses, nothing is written and `retry_after_seconds` is set.
///
/// `requested_options` only has effect on the **first** turn of a conversation; after
/// that the frozen values on the session win, so a client that forgets to send them —
/// or forges them — cannot change which agent a thread is talking to mid-way.
pub async fn send_message(
    user: &CurrentUser,
    session_id: String,
    message: String,
    requested_options: ChatOptions,
    requested_model: Option<String>,
) -> anyhow::Result<ChatSendResult> {
    let username = require_named_user(user)?;

    if let Err(e) = check_and_record(username, RateLimitKind::ChatMessage) {
        return Ok(ChatSendResult {
            messages: Vec::new(),
            retry_after_seconds: Some(e.retry_after_seconds),
        });
    }

    let message = message.trim().to_string();
    if message.is_empty() {
        anyhow::bail!("message is empty");
    }
    if message.chars().count() > MAX_MESSAGE_CHARS {
        anyhow::bail!("message is too long (max {MAX_MESSAGE_CHARS} characters)");
    }

    // Resolve the model before allocating a seq: a forged id must be refused, not merely
    // absent from the dropdown.
    let llm_model = crate::api::admin::llm::resolve_chat_model(
        requested_model.as_deref(),
        user.is_guest,
    )
    .await?;

    let session = db_chat::get_session(username, &session_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("chat session not found"))?;

    // Live permissions win over whatever the session was created with.
    let permitted = list_permitted_collections(user).await?;
    let allowed = intersect_collections(&session.collections, &permitted);

    // Freeze the agent switches onto the conversation on the first turn; afterwards
    // this returns what was frozen and ignores what the client asked for.
    let options = db_chat::lock_session_options(username, &session_id, requested_options).await?;

    let guard = db_chat::turn_lock(username, &session_id)
        .try_lock_owned()
        .map_err(|_| anyhow::anyhow!("a turn is already running in this conversation"))?;

    // The lock above only covers turns this process is running. A deep-research turn is
    // run by a Temporal worker and its lock was released the moment `start_research_task`
    // returned — minutes before the workflow writes its answer at the seq it reserved. So
    // ask the same question the poller asks: is a turn still being produced? Without
    // this, an inline send during a research turn took the reserved seq and one of the
    // two messages was silently dropped by ReplacingMergeTree.
    if stream_state(username, &session_id).await?.active {
        anyhow::bail!("a turn is already running in this conversation");
    }

    // Everything that decides seqs happens before the spawn, so the transcript this
    // returns is the one the poller continues from.
    let history = db_chat::list_messages(username, &session_id).await?;
    let is_first_turn = history.is_empty();
    let turn_uuid = crate::db_auth::sessions::generate_session_id();
    let user_seq = db_chat::next_seq(username, &session_id).await?;
    db_chat::append_message(
        username,
        &session_id,
        user_seq,
        ChatRole::User,
        &message,
        AppendMessageExtras {
            message_uuid: turn_uuid.clone(),
            ..Default::default()
        },
    )
    .await?;
    // Reported, not prevented — see `detect_seq_collision`. Refusing here costs the user
    // a resend; not checking costs them the message.
    db_chat::detect_seq_collision(username, &session_id, user_seq, &turn_uuid).await?;

    // Provisional title from the first user turn; LLM title/summary replaces it at the
    // end of the turn.
    let provisional_title = title_from_message(&message);
    if is_first_turn {
        db_chat::touch_session(username, &session_id, Some(&provisional_title), None).await?;
    } else {
        db_chat::touch_session(username, &session_id, None, None).await?;
    }

    // Registered before the spawn: `poll_chat` reports the turn as active from the
    // moment this function returns, so the client never sees a gap between "sent" and
    // "the first stream row exists".
    let run = live_runs::register(
        username,
        &session_id,
        &provisional_title,
        &message,
        options,
    );

    let ctx = TurnContext {
        username: username.to_string(),
        session_id: session_id.clone(),
        message,
        allowed,
        options,
        llm_model,
        history,
        is_first_turn,
        turn_uuid,
        user_seq,
    };
    tokio::spawn(async move {
        let session_id = ctx.session_id.clone();
        // The guard rides along and is released only when the turn is fully written.
        let _guard = guard;
        if let Err(e) = run_turn(ctx, run).await {
            tracing::error!("chat turn for {session_id} could not be finalised: {e:#}");
        }
    });

    let messages = db_chat::list_messages(username, &session_id).await?;
    Ok(ChatSendResult {
        messages,
        retry_after_seconds: None,
    })
}

// ---------------------------------------------------------------------------
// Polling the in-flight turn
// ---------------------------------------------------------------------------

/// How long one poll holds the request when nothing changes. The 500 ms step doubles
/// as the floor while content is flowing — see the loop in [`poll_chat`].
const POLL_HOLD: Duration = Duration::from_secs(15);
const POLL_STEP: Duration = Duration::from_millis(500);

/// Concurrently-held polls per user. A held request is a cheap way to exhaust a
/// server, so past this cap a poll answers immediately with the current state instead
/// of holding — the client simply polls again sooner.
const MAX_HELD_POLLS_PER_USER: usize = 2;

static HELD_POLLS: std::sync::LazyLock<
    std::sync::Mutex<std::collections::HashMap<String, usize>>,
> = std::sync::LazyLock::new(|| std::sync::Mutex::new(std::collections::HashMap::new()));

/// Decrements the held-poll count on drop, however the poll ends.
struct HeldPollGuard {
    username: String,
}

impl HeldPollGuard {
    /// `Some` while this user is under the held-poll cap, `None` when at it.
    fn try_acquire(username: &str) -> Option<Self> {
        let mut held = HELD_POLLS.lock().unwrap_or_else(|e| e.into_inner());
        let count = held.entry(username.to_string()).or_insert(0);
        if *count >= MAX_HELD_POLLS_PER_USER {
            return None;
        }
        *count += 1;
        Some(Self {
            username: username.to_string(),
        })
    }
}

impl Drop for HeldPollGuard {
    fn drop(&mut self) {
        if let Ok(mut held) = HELD_POLLS.lock() {
            if let Some(count) = held.get_mut(&self.username) {
                *count = count.saturating_sub(1);
                if *count == 0 {
                    held.remove(&self.username);
                }
            }
        }
    }
}

/// The live tail of a transcript, as [`TurnTail`]. Shared by the poll endpoint and
/// session load, so a refresh mid-answer shows exactly what a poller sees.
///
/// **Liveness comes from the transcript, not from an open stream row.** A turn is
/// unfinished when the last user row has no assistant or error row after it; the stream
/// table only says how recently something happened. Deriving `active` from "a non-final
/// stream row exists right now" looked equivalent and was not: the writer finalises one
/// row and opens the next as two separate inserts, and a poll landing in that gap
/// reported the turn as over. Inline turns hid it behind their `live_runs` entry;
/// Temporal research turns, which have no entry in this process, dropped the page out of
/// its poll loop a couple of seconds in.
async fn stream_state(username: &str, session_id: &str) -> anyhow::Result<TurnTail> {
    // A turn registered by `send_message` is running before it has written any stream
    // row at all, and that window is the other place a poller must not give up.
    let running = live_runs::has_run_for(username, session_id);
    let (last_user_seq, last_answer_seq) = db_chat::turn_boundaries(username, session_id).await?;
    let turn_open = match (last_user_seq, last_answer_seq) {
        (Some(user), Some(answer)) => answer < user,
        (Some(_), None) => true,
        // No user row: nothing has been asked, so nothing can be in flight.
        (None, _) => false,
    };

    let rows = db_chat::read_stream_rows(username, session_id).await?;
    // Freshness is measured over every row of the turn, final or not: the last thing
    // that happened is the clock, whichever row it happened on.
    let newest_ms = rows
        .iter()
        .filter(|r| Some(r.seq) > last_user_seq)
        .map(|r| r.updated_at)
        .max();
    let now_ms = time::OffsetDateTime::now_utc().unix_timestamp_nanos() as i64 / 1_000_000;
    let stall_ms = stream_stall().as_millis() as i64;
    let advancing = newest_ms.is_some_and(|ms| now_ms - ms <= stall_ms);

    // Interrupted = an unfinished turn that nothing is working on any more: no live run
    // here, and its stream rows stopped advancing a stall window ago. A turn that never
    // wrote a stream row at all is not "interrupted", it is a turn this process is
    // simply not running — that is what `running` covers.
    let interrupted = turn_open && !running && newest_ms.is_some() && !advancing;
    let active = turn_open && (running || advancing);

    let live: Vec<_> = rows.iter().filter(|r| r.is_final == 0).collect();
    if live.is_empty() {
        return Ok(TurnTail {
            stream: None,
            active,
            interrupted,
        });
    }

    // chat_messages wins: a stream row whose seq already has a finished row lost the
    // finalisation race and must not be shown.
    let min_seq = live.iter().map(|r| r.seq).min().unwrap_or(0);
    let finished = db_chat::list_messages_after(username, session_id, i64::from(min_seq) - 1).await?;
    let finished_seqs: std::collections::HashSet<u32> = finished.iter().map(|m| m.seq).collect();
    let live: Vec<_> = live
        .into_iter()
        .filter(|r| !finished_seqs.contains(&r.seq))
        .collect();
    if live.is_empty() {
        return Ok(TurnTail {
            stream: None,
            active,
            interrupted,
        });
    }

    let updated_ms = live.iter().map(|r| r.updated_at).max().unwrap_or(0);
    let tool_rows: Vec<StreamToolRow> = live
        .iter()
        .filter(|r| r.role == ChatRole::Tool.as_str())
        .map(|r| StreamToolRow {
            seq: r.seq,
            tool_call_index: r.tool_call_index,
            tool_name: r.tool_name.clone(),
            summary: r.content.clone(),
            done: false,
            // A running tool's stream row is written once, at `start_tool`, and not
            // touched again until the call finalises into `chat_messages` — the keepalive
            // rewrites the *assistant* row. So its `updated_at` is when the call started,
            // which is what the card's counter needs to survive a refresh.
            elapsed_ms: now_ms.saturating_sub(r.updated_at).clamp(0, i64::from(u32::MAX)) as u32,
        })
        .collect();
    let assistant = live
        .iter()
        .filter(|r| r.role == ChatRole::Assistant.as_str())
        .max_by_key(|r| r.seq);

    // An in-flight turn always has an assistant row once content starts; before the
    // first token there may be only a running tool row (or nothing at all, which was
    // filtered above). answer_seq sits after the last tool row, as the writer assigns.
    let answer_seq = assistant
        .map(|r| r.seq)
        .unwrap_or_else(|| live.iter().map(|r| r.seq).max().unwrap_or(0) + 1);
    let turn = StreamTurn {
        answer_seq,
        content: assistant.map(|r| r.content.clone()).unwrap_or_default(),
        reasoning: assistant.map(|r| r.reasoning.clone()).unwrap_or_default(),
        tool_rows,
        updated_ms,
    };

    Ok(TurnTail {
        stream: Some(turn),
        active,
        interrupted,
    })
}

/// What the poll and the session load both need to know about the tail of a session.
struct TurnTail {
    stream: Option<StreamTurn>,
    active: bool,
    interrupted: bool,
}

/// One version stamp for the poll's change detection. `updated_ms` moves on every
/// stream write; the finished tail moves on every finalised row; together they cover
/// everything a client can see.
fn poll_sig(finished_max_seq: Option<u32>, tail: &TurnTail) -> String {
    format!(
        "{}:{}:{}:{}",
        finished_max_seq.map(|s| s.to_string()).unwrap_or_default(),
        tail.stream
            .as_ref()
            .map(|t| format!("{}:{}:{}", t.updated_ms, t.content.len(), t.tool_rows.len()))
            .unwrap_or_default(),
        tail.active,
        tail.interrupted,
    )
}

/// Long-poll the tail of a conversation.
///
/// Returns finished rows with `seq > after_seq` plus the in-flight turn. Holds up to
/// [`POLL_HOLD`] when nothing changes and returns immediately when the signature moves
/// — one poll updates the whole tail of the transcript.
///
/// Every poll after the first takes at least [`POLL_STEP`]. That floor is not a
/// courtesy: with content flowing, each poll finds a change and returns at once, so
/// without it a client would spin as fast as the network allows — and so would every
/// client past the held-poll cap, which returns immediately by design.
pub async fn poll_chat(
    user: &CurrentUser,
    session_id: String,
    after_seq: Option<u32>,
    sig: String,
) -> anyhow::Result<ChatPollResult> {
    let username = require_named_user(user)?;
    // Typed, not prose. The client counts consecutive poll failures and declares "lost
    // contact with the chat" at three — and a rate limit is the opposite of lost contact:
    // the server is answering, the turn is still running, and the only correct response is
    // to wait exactly this long and ask again.
    check_and_record(username, RateLimitKind::ChatPoll).map_err(|e| {
        anyhow::anyhow!(
            "{}{} polling too fast ({} window)",
            common::chat_types::RATE_LIMITED_PREFIX,
            e.retry_after_seconds,
            e.window
        )
    })?;

    // Ownership: reading another user's transcript is not allowed even to poll it.
    db_chat::get_session(username, &session_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("chat session not found"))?;

    let held = HeldPollGuard::try_acquire(username);
    let started = Instant::now();
    let deadline = started + POLL_HOLD;
    let floor = if sig.is_empty() { Duration::ZERO } else { POLL_STEP };
    let after_seq = after_seq.map(i64::from).unwrap_or(-1);

    loop {
        let messages = db_chat::list_messages_after(username, &session_id, after_seq).await?;
        let tail = stream_state(username, &session_id).await?;
        let finished_max = db_chat::next_seq(username, &session_id)
            .await
            .ok()
            .and_then(|next| next.checked_sub(1));
        let current_sig = poll_sig(finished_max, &tail);

        let changed = !messages.is_empty() || current_sig != sig || tail.interrupted;
        if changed || held.is_none() || Instant::now() >= deadline {
            if let Some(remaining) = floor.checked_sub(started.elapsed()) {
                tokio::time::sleep(remaining).await;
            }
            return Ok(ChatPollResult {
                messages,
                stream: tail.stream,
                active: tail.active,
                interrupted: tail.interrupted,
                sig: current_sig,
            });
        }
        tokio::time::sleep(POLL_STEP).await;
    }
}

/// The stop button: ask this user's in-flight turn on this session to stop.
///
/// Cooperative and quick: the turn notices within a poll step and finalises the
/// partial answer with a truncation marker. `false` means nothing was in flight.
pub fn stop_chat_turn(user: &CurrentUser, session_id: String) -> anyhow::Result<bool> {
    let username = require_named_user(user)?;
    Ok(live_runs::request_cancel_for(username, &session_id))
}

/// Dismiss an interrupted turn's leftover stream rows.
///
/// Refused while a live run owns the session — dismissing a running turn would hide
/// it from the poller that is following it.
pub async fn dismiss_interrupted_turn(user: &CurrentUser, session_id: String) -> anyhow::Result<()> {
    let username = require_named_user(user)?;
    if live_runs::has_run_for(username, &session_id) {
        anyhow::bail!("a turn is still running in this session");
    }
    db_chat::mark_stream_final(username, &session_id).await
}

/// Mutable state of one streaming turn, folded over the agent's event feed.
struct TurnState {
    /// Visible answer so far — content produced after the last tool call.
    answer: String,
    /// Reasoning trace plus pre-tool narration (the agent's own rule: content before a
    /// tool call is narration about the call, not the answer).
    reasoning: String,
    /// How many tool calls have started; the assistant partial lives at
    /// `first_tool_seq + tool_count`, always after the last tool.
    tool_count: u32,
    /// `seq` of the first tool row (== user seq + 1).
    first_tool_seq: u32,
    /// Start payloads not yet paired with an end, each with the `seq` its stream row
    /// was written at, in arrival order. The seq travels **with the start**, not in a
    /// "currently running" slot: a graph node may run several tools at once, and a
    /// single slot would let the second start overwrite the first, finalising the
    /// wrong row when its end arrived.
    pending_starts: Vec<(u32, agent_client::AgentToolCall)>,
    /// Whether the assistant stream row has ever been written.
    assistant_row_started: bool,
    last_stream_write: Instant,
}

impl TurnState {
    fn new(first_tool_seq: u32) -> Self {
        Self {
            answer: String::new(),
            reasoning: String::new(),
            tool_count: 0,
            first_tool_seq,
            pending_starts: Vec::new(),
            assistant_row_started: false,
            last_stream_write: Instant::now() - Duration::from_secs(60),
        }
    }

    fn answer_seq(&self) -> u32 {
        self.first_tool_seq + self.tool_count
    }
}

/// How often the growing assistant partial is rewritten at most. Each rewrite is a
/// ClickHouse insert, so per-token writes are out; 300 ms is brisk enough to read as
/// live and slow enough to keep the stream table small.
const STREAM_WRITE_MIN_INTERVAL: Duration = Duration::from_millis(300);

/// A stream row that has not advanced for this long with no live run owning it is an
/// interrupted turn (the website restarted mid-turn), not a slow one.
fn stream_stall() -> Duration {
    let secs = std::env::var("CHAT_STREAM_STALL_SECONDS")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(60);
    Duration::from_secs(secs.clamp(5, 3600))
}

/// Everything [`send_message`] settled before spawning the turn.
struct TurnContext {
    username: String,
    session_id: String,
    message: String,
    allowed: Vec<String>,
    options: ChatOptions,
    /// Resolved, allowlist-checked model id for this turn.
    llm_model: String,
    /// The transcript as it stood *before* the user row — what the agent is told.
    history: Vec<common::chat_types::ChatMessageItem>,
    is_first_turn: bool,
    turn_uuid: String,
    user_seq: u32,
}

/// Run the agent half of a turn and write its ending. The turn lock and the live-run
/// registration are both held by the caller's spawned task for the whole of this.
async fn run_turn(ctx: TurnContext, run: live_runs::RunGuard) -> anyhow::Result<()> {
    let username = ctx.username.clone();
    let session_id = ctx.session_id.clone();
    let turn_uuid = ctx.turn_uuid.clone();
    if let Err(e) = run_turn_inner(ctx, run).await {
        // A turn that dies outside its own error handling still owes the transcript an
        // ending — an orphaned stream row would otherwise render "interrupted" for an
        // hour. Still under the turn lock, so the error row's seq allocation is safe.
        tracing::error!("chat turn for {session_id} failed outside the agent call: {e:#}");
        // If even the seq allocation fails, the write is dropped. `unwrap_or(0)` wrote the
        // row at seq 0 instead, which is a real seq in every session and therefore an
        // error message landing on top of whatever is already there. Losing the error row
        // when the database is unreachable is the lesser outcome — and `mark_stream_final`
        // below still ends the turn, so the page stops spinning either way.
        match db_chat::next_seq(&username, &session_id).await {
            Ok(seq) => {
                let _ = db_chat::append_message(
                    &username,
                    &session_id,
                    seq,
                    ChatRole::Error,
                    &format!("The assistant could not answer: {e}"),
                    AppendMessageExtras {
                        message_uuid: turn_uuid,
                        ..Default::default()
                    },
                )
                .await;
            }
            Err(seq_err) => tracing::error!(
                "could not allocate a seq for the error row in {session_id}: {seq_err:#} \
                 — dropping it rather than colliding at seq 0"
            ),
        }
        let _ = db_chat::mark_stream_final(&username, &session_id).await;
    }
    Ok(())
}

/// The turn body: the streamed agent call and the finalisation.
async fn run_turn_inner(ctx: TurnContext, run: live_runs::RunGuard) -> anyhow::Result<()> {
    let TurnContext {
        username,
        session_id,
        message,
        allowed,
        options,
        llm_model,
        history,
        is_first_turn,
        turn_uuid,
        user_seq,
    } = ctx;
    let (username, session_id, message) = (username.as_str(), session_id.as_str(), message.as_str());
    let allowed = allowed.as_slice();

    let agent_history: Vec<agent_client::AgentChatMessage> = history
        .iter()
        .filter(|m| m.role.is_conversational())
        .map(|m| agent_client::AgentChatMessage {
            r#type: match m.role {
                ChatRole::User => "human".to_string(),
                _ => "ai".to_string(),
            },
            content: m.content.clone(),
        })
        .collect();

    let seq = user_seq + 1;
    let message_id = format!("{session_id}-{user_seq}");
    let started = Instant::now();

    let mut state = TurnState::new(seq);

    // Open the assistant row before the agent is even called, so the turn owns exactly
    // one non-final stream row from here until finalisation. That invariant is what the
    // interrupted detector runs on: a process killed with nothing open leaves a
    // transcript that simply stops after the last tool row, with no marker and nothing
    // for the page to explain. Content is empty; the row exists to be a heartbeat.
    if let Err(e) = maybe_write_assistant_row(username, session_id, &turn_uuid, &mut state, true).await
    {
        tracing::warn!("opening the stream row for {session_id} failed: {e:#}");
    }

    let attempts = agent_client::agent_attempts();
    let base = agent_client::agent_retry_base();
    let mut attempt_errors: Vec<String> = Vec::new();
    let mut outcome: anyhow::Result<()> = Err(anyhow::anyhow!("no attempt ran"));

    for attempt in 1..=attempts {
        if attempt > 1 {
            if run.is_cancelled() {
                break;
            }
            tokio::time::sleep(agent_client::backoff_for_attempt(attempt, base)).await;
            if run.is_cancelled() {
                break;
            }
        }
        run.set_attempt(attempt);

        let mut saw_event = false;
        let result = stream_agent_attempt(
            username,
            session_id,
            &message_id,
            message,
            &agent_history,
            allowed,
            options.internet_tools,
            Some(llm_model.as_str()),
            &turn_uuid,
            &mut state,
            &mut saw_event,
            &run,
        )
        .await;
        match result {
            Ok(()) => {
                outcome = Ok(());
                break;
            }
            Err(e) => {
                attempt_errors.push(format!("attempt {attempt}/{attempts}: {e}"));
                outcome = Err(e);
                // A mid-stream failure must not be retried: the model may already have
                // produced visible content, and a second attempt would duplicate it.
                if saw_event {
                    break;
                }
            }
        }
    }

    let agent_duration_ms = started.elapsed().as_millis().min(u128::from(u32::MAX)) as u32;
    let cancelled = run.is_cancelled();

    let result = finalise_turn(FinaliseArgs {
        username,
        session_id,
        turn_uuid: &turn_uuid,
        llm_model: &llm_model,
        state: &state,
        outcome,
        cancelled,
        agent_duration_ms,
        attempt_errors,
        is_first_turn,
        message,
    })
    .await;
    // Deregistered only now, with the finished rows already written: `poll_chat`
    // reports `active` straight off the registry, and a gap between "no longer
    // running" and "the answer is in the transcript" is exactly the window in which a
    // poller would stop one write too early.
    drop(run);
    result
}

#[allow(clippy::too_many_arguments)]
struct FinaliseArgs<'a> {
    username: &'a str,
    session_id: &'a str,
    turn_uuid: &'a str,
    /// The model this turn actually ran on, resolved and allowlist-checked in
    /// `send_message`. Not `env LLM_MODEL`: that variable is unset in the website
    /// container, so every row recorded an empty string, and it would be the wrong answer
    /// anyway the moment a user picks a model from the dropdown.
    llm_model: &'a str,
    state: &'a TurnState,
    outcome: anyhow::Result<()>,
    cancelled: bool,
    agent_duration_ms: u32,
    attempt_errors: Vec<String>,
    is_first_turn: bool,
    message: &'a str,
}

/// Write the turn's ending: assistant row (or error row), stream rows to final, and —
/// on the first turn — the LLM title/summary.
async fn finalise_turn(args: FinaliseArgs<'_>) -> anyhow::Result<()> {
    let FinaliseArgs {
        username,
        session_id,
        turn_uuid,
        llm_model,
        state,
        outcome,
        cancelled,
        agent_duration_ms,
        attempt_errors,
        is_first_turn,
        message,
    } = args;

    let mut assistant_answer_for_summary: Option<String> = None;

    if cancelled {
        // The stop button: the partial is finalised (the user already read it) with an
        // explicit marker, and the stop is recorded.
        let partial = state.answer.trim();
        let content = if partial.is_empty() {
            "_(stopped before the assistant answered)_".to_string()
        } else {
            format!("{partial}\n\n_(stopped before the answer finished)_")
        };
        db_chat::append_message(
            username,
            session_id,
            state.answer_seq(),
            ChatRole::Assistant,
            &content,
            AppendMessageExtras {
                agent_duration_ms,
                retry_errors: encode_errors(&attempt_errors),
                reasoning: state.reasoning.clone(),
                model: llm_model.to_string(),
                message_uuid: turn_uuid.to_string(),
                ..Default::default()
            },
        )
        .await?;
        telemetry::record_event(username, EVENT_LLM_CHAT_MESSAGE, "chat_stopped");
    } else if let Err(e) = outcome {
        // A failed agent call belongs in the transcript: the user asked something and
        // deserves to see what went wrong in place, not a toast that vanishes. The
        // partial answer, if any, is NOT promoted — an interrupted transcript must not
        // contain half-sentences with no marker.
        db_chat::append_message(
            username,
            session_id,
            state.answer_seq(),
            ChatRole::Error,
            &format!("The assistant could not answer: {e}"),
            AppendMessageExtras {
                agent_duration_ms,
                retry_errors: encode_errors(&attempt_errors),
                message_uuid: turn_uuid.to_string(),
                ..Default::default()
            },
        )
        .await?;
    } else {
        let answer = if state.answer.trim().is_empty() {
            // A turn that called tools and then said nothing new: the narration is the
            // only thing the model produced, so it becomes the answer rather than
            // rendering as a blank bubble.
            if state.reasoning.trim().is_empty() {
                "(the assistant returned an empty answer)".to_string()
            } else {
                state.reasoning.trim().to_string()
            }
        } else {
            state.answer.trim().to_string()
        };
        assistant_answer_for_summary = Some(answer.clone());
        db_chat::append_message(
            username,
            session_id,
            state.answer_seq(),
            ChatRole::Assistant,
            &answer,
            AppendMessageExtras {
                agent_duration_ms,
                retry_errors: encode_errors(&attempt_errors),
                reasoning: state.reasoning.clone(),
                model: llm_model.to_string(),
                message_uuid: turn_uuid.to_string(),
                ..Default::default()
            },
        )
        .await?;
        telemetry::record_event(username, EVENT_LLM_CHAT_MESSAGE, "chat");
    }

    db_chat::mark_stream_final(username, session_id).await?;

    // Title/summary from the LLM after the first turn — never blocks / fails the turn.
    if is_first_turn {
        if let Some(answer) = assistant_answer_for_summary {
            let username_owned = username.to_string();
            let session_owned = session_id.to_string();
            let user_msg = message.to_string();
            tokio::spawn(async move {
                if let Some(ts) = summarize::generate_title_and_summary_for(
                    &user_msg,
                    &answer,
                    &username_owned,
                    &session_owned,
                )
                .await
                {
                    let _ = db_chat::set_session_title_summary(
                        &username_owned,
                        &session_owned,
                        Some(&ts.title),
                        Some(&ts.summary),
                    )
                    .await;
                }
            });
        }
    }
    Ok(())
}

/// One attempt of the streamed agent call, folding events into `state` and writing
/// stream rows as they arrive.
///
/// Cancellation aborts the consumer task — and with it the in-flight HTTP request —
/// instead of waiting out a slow generation. A failed *stream-row* write is logged and
/// skipped: it only degrades the live progress display, and must not cost the turn an
/// answer the model already produced.
#[allow(clippy::too_many_arguments)]
async fn stream_agent_attempt(
    username: &str,
    session_id: &str,
    message_id: &str,
    message: &str,
    agent_history: &[agent_client::AgentChatMessage],
    allowed: &[String],
    internet_tools: bool,
    llm_model: Option<&str>,
    turn_uuid: &str,
    state: &mut TurnState,
    saw_event: &mut bool,
    run: &live_runs::RunGuard,
) -> anyhow::Result<()> {
    let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<agent_client::AgentStreamEvent>();
    let handle = {
        let username = username.to_string();
        let session_id = session_id.to_string();
        let message_id = message_id.to_string();
        let message = message.to_string();
        let history = agent_history.to_vec();
        let allowed = allowed.to_vec();
        let llm_model = llm_model.map(str::to_string);
        tokio::spawn(async move {
            agent_client::ask_agent_stream_once(
                &username,
                &session_id,
                &message_id,
                &message,
                &history,
                &allowed,
                internet_tools,
                llm_model.as_deref(),
                &mut |event| {
                    let _ = tx.send(event);
                },
            )
            .await
        })
    };

    loop {
        if run.is_cancelled() {
            handle.abort();
            break;
        }
        tokio::select! {
            event = rx.recv() => {
                let Some(event) = event else { break };
                *saw_event = true;
                if let Err(e) = handle_stream_event(username, session_id, turn_uuid, state, event).await {
                    tracing::warn!("stream-row write failed for {session_id}: {e:#}");
                }
            }
            // The cancel flag is polled between events too, or a model that goes quiet
            // for minutes would ignore the stop button until it spoke again.
            _ = tokio::time::sleep(Duration::from_millis(200)) => {}
        }
    }

    match handle.await {
        Ok(result) => result,
        Err(e) if e.is_cancelled() && run.is_cancelled() => Ok(()),
        Err(e) => Err(anyhow::anyhow!("agent stream task failed: {e}")),
    }
}

/// Fold one agent event into the turn state, writing stream rows as needed.
async fn handle_stream_event(
    username: &str,
    session_id: &str,
    turn_uuid: &str,
    state: &mut TurnState,
    event: agent_client::AgentStreamEvent,
) -> anyhow::Result<()> {
    use agent_client::AgentStreamEvent as Ev;
    match event {
        Ev::Start => {}
        Ev::Reasoning(text) => {
            state.reasoning.push_str(&text);
            maybe_write_assistant_row(username, session_id, turn_uuid, state, false).await?;
        }
        Ev::Response(text) => {
            state.answer.push_str(&text);
            maybe_write_assistant_row(username, session_id, turn_uuid, state, false).await?;
        }
        Ev::StartTool(payload) => {
            // Content before a tool call is narration about the call, not the answer.
            if !state.answer.trim().is_empty() {
                if !state.reasoning.is_empty() {
                    state.reasoning.push_str("\n\n");
                }
                state.reasoning.push_str(state.answer.trim());
                state.answer.clear();
            }
            // The running tool takes the seq the assistant partial occupied (if any);
            // the assistant row resumes one seq later. Ordering stays user, tools,
            // answer — identical between the live stream and the finalised transcript.
            let tool_seq = state.answer_seq();
            if state.assistant_row_started {
                db_chat::mark_stream_row_final(username, session_id, tool_seq).await?;
            }
            state.assistant_row_started = false;
            let call = agent_client::AgentToolCall {
                phase: "start".to_string(),
                content: payload,
            };
            let tool_name = call.tool_name();
            db_chat::append_stream_row(
                username,
                session_id,
                tool_seq,
                ChatRole::Tool,
                &call.summary(TOOL_SUMMARY_CHARS),
                "",
                &tool_name,
                state.tool_count,
                false,
                turn_uuid,
            )
            .await?;
            state.pending_starts.push((tool_seq, call.clone()));
            state.tool_count += 1;
        }
        Ev::EndTool(payload) => {
            let end = agent_client::AgentToolCall {
                phase: "end".to_string(),
                content: payload,
            };
            // Pair with the matching start (by tool_call_id when present, else FIFO) —
            // the same rules as `pair_tool_calls`, applied one call at a time.
            let end_id = end.tool_call_id().map(str::to_string);
            let matched = end_id
                .as_ref()
                .and_then(|tid| {
                    state
                        .pending_starts
                        .iter()
                        .position(|(_, c)| c.tool_call_id() == Some(tid.as_str()))
                        .map(|pos| state.pending_starts.remove(pos))
                })
                // FIFO, not LIFO: with several tools in flight the oldest unmatched
                // start is the one an id-less end most likely belongs to.
                .or_else(|| {
                    if state.pending_starts.is_empty() {
                        None
                    } else {
                        Some(state.pending_starts.remove(0))
                    }
                });
            let start = matched.as_ref().map(|(_, c)| c);
            let tool_name = {
                let from_end = end.tool_name();
                if from_end != "tool" {
                    from_end
                } else if let Some(s) = start {
                    s.tool_name()
                } else {
                    "tool".to_string()
                }
            };
            let tool_input = start
                .map(|s| s.input_json())
                .filter(|s| s != "{}")
                .unwrap_or_else(|| end.input_json());
            let paired = agent_client::PairedToolCall {
                tool_name,
                tool_input,
                tool_output: end.output_json(),
                summary: end.summary(TOOL_SUMMARY_CHARS),
            };
            // The tool's result is a completed fact: it is finalised into
            // chat_messages immediately, and its stream row goes final. Only the
            // *answer* waits for the end of the turn.
            let tool_seq = matched
                .as_ref()
                .map(|(seq, _)| *seq)
                .unwrap_or_else(|| state.answer_seq().saturating_sub(1));
            finalize_tool_row(username, session_id, tool_seq, turn_uuid, &paired).await?;
            db_chat::mark_stream_row_final(username, session_id, tool_seq).await?;
            telemetry::record_event(username, EVENT_LLM_MCP_TOOL_CALL, &paired.tool_name);
            // Reopen the assistant row immediately. The model can spend a long time
            // between one tool ending and the next starting, and a process killed in
            // that gap would otherwise leave nothing non-final behind — the turn would
            // vanish without an interrupted marker.
            maybe_write_assistant_row(username, session_id, turn_uuid, state, true).await?;
        }
        Ev::End => {
            maybe_write_assistant_row(username, session_id, turn_uuid, state, true).await?;
        }
    }
    Ok(())
}

/// Persist one completed tool call as a finished transcript row.
async fn finalize_tool_row(
    username: &str,
    session_id: &str,
    seq: u32,
    turn_uuid: &str,
    call: &agent_client::PairedToolCall,
) -> anyhow::Result<()> {
    // Inside the JSON, never across it: a `{` stored without its `}` is a result the whole
    // read path reports as missing. See `truncate_tool_payload`.
    let tool_input = truncate_tool_payload(&call.tool_input, TOOL_PAYLOAD_CHARS);
    let tool_output = truncate_tool_payload(&call.tool_output, TOOL_PAYLOAD_CHARS);
    let refs = extract_doc_refs(&call.tool_name, &call.tool_output);
    let doc_refs = if refs.is_empty() {
        String::new()
    } else {
        serde_json::to_string(&refs).unwrap_or_default()
    };
    db_chat::append_message(
        username,
        session_id,
        seq,
        ChatRole::Tool,
        &call.summary,
        AppendMessageExtras {
            tool_name: call.tool_name.clone(),
            tool_input,
            tool_output,
            doc_refs,
            agent_duration_ms: 0,
            retry_errors: String::new(),
            // A tool row is the tool's output, not the model's: leaving these empty is
            // what makes "which model wrote this" a question only the assistant rows
            // answer.
            model: String::new(),
            reasoning: String::new(),
            message_uuid: turn_uuid.to_string(),
        },
    )
    .await
}

/// Rewrite the assistant's in-flight row, throttled unless `force`d.
async fn maybe_write_assistant_row(
    username: &str,
    session_id: &str,
    turn_uuid: &str,
    state: &mut TurnState,
    force: bool,
) -> anyhow::Result<()> {
    if !force && state.last_stream_write.elapsed() < STREAM_WRITE_MIN_INTERVAL {
        return Ok(());
    }
    state.last_stream_write = Instant::now();
    state.assistant_row_started = true;
    db_chat::append_stream_row(
        username,
        session_id,
        state.answer_seq(),
        ChatRole::Assistant,
        &state.answer,
        &state.reasoning,
        "",
        0,
        false,
        turn_uuid,
    )
    .await
}

/// Hand a question to the long-running research workflow instead of answering it inline.
///
/// The synchronous path in [`send_message`] holds an HTTP request open for the whole
/// agent run, which is fine for a chat turn and wrong for an exhaustive research run.
/// This variant records the user's turn, reserves the transcript position, and starts a
/// Temporal `ResearchTask` that writes the answer back when it finishes — so the user
/// can close the tab.
///
/// Returns the Temporal run id, or a rate-limit refusal via the same `ChatSendResult`
/// shape used by [`send_message`] when limited (here encoded as an error string with
/// retry seconds — research returns only a run id on success).
pub async fn start_research_task(
    user: &CurrentUser,
    session_id: String,
    message: String,
    requested_options: ChatOptions,
) -> anyhow::Result<Result<String, u64>> {
    let username = require_named_user(user)?;

    if let Err(e) = check_and_record(username, RateLimitKind::ChatMessage) {
        // Nothing written — consistent with send_message's rate-limit path.
        return Ok(Err(e.retry_after_seconds));
    }

    let message = message.trim().to_string();
    if message.is_empty() {
        anyhow::bail!("message is empty");
    }
    if message.chars().count() > MAX_MESSAGE_CHARS {
        anyhow::bail!("message is too long (max {MAX_MESSAGE_CHARS} characters)");
    }

    let session = db_chat::get_session(username, &session_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("chat session not found"))?;
    let permitted = list_permitted_collections(user).await?;
    let allowed = intersect_collections(&session.collections, &permitted);

    // Deep research allocates transcript seqs exactly like an inline turn, so it takes
    // the same lock rather than racing one. `try_lock` for the same reason
    // `send_message` uses it: one turn at a time per session, said out loud.
    let _guard = db_chat::turn_lock(username, &session_id)
        .try_lock_owned()
        .map_err(|_| anyhow::anyhow!("a turn is already running in this conversation"))?;

    // ...and the same cross-process check `send_message` makes, for the same reason: this
    // guard is dropped when the function returns, so it cannot keep a *second* research
    // task (or an inline send) off the seq this one is about to reserve.
    if stream_state(username, &session_id).await?.active {
        anyhow::bail!("a turn is already running in this conversation");
    }

    // Deep research is one of the two frozen switches; a thread that started as a
    // research thread stays one.
    db_chat::lock_session_options(
        username,
        &session_id,
        ChatOptions {
            deep_research: true,
            ..requested_options
        },
    )
    .await?;

    let history = db_chat::list_messages(username, &session_id).await?;
    let mut seq = db_chat::next_seq(username, &session_id).await?;
    // The turn uuid every row of this research turn carries, transcript and stream alike.
    // The *stream* writer in the Temporal worker derives the identical string from
    // `(session_id, start_seq)` (`P_agent/stream_writer.py`) — it is a coordination key
    // between two processes that cannot pass one to each other, so the format is load
    // bearing on both sides. The user row was written without it, which left the turn's
    // first row unattributable and made the collision detector blind to exactly the
    // collision this path causes.
    let turn_uuid = format!("research-{session_id}-{}", seq + 1);
    db_chat::append_message(
        username,
        &session_id,
        seq,
        ChatRole::User,
        &message,
        AppendMessageExtras {
            message_uuid: turn_uuid.clone(),
            ..Default::default()
        },
    )
    .await?;
    db_chat::detect_seq_collision(username, &session_id, seq, &turn_uuid).await?;
    seq += 1;

    if history.is_empty() {
        db_chat::touch_session(username, &session_id, Some(&title_from_message(&message)), None)
            .await?;
    } else {
        db_chat::touch_session(username, &session_id, None, None).await?;
    }

    // No "Research task started" placeholder in `chat_messages`: the Temporal activity
    // streams its progress into chat_message_stream, so the turn renders live
    // exactly like an inline one and the workflow writes the finished rows at `seq`.
    //
    // An empty *stream* row does go in, though, and it is load-bearing rather than
    // decorative. A research turn has no `live_runs` entry in this process, so an open
    // stream row is the only thing that tells the poller the turn exists — without it
    // the page would stop following the turn in the seconds before the worker picks the
    // activity up. The activity rewrites this same seq (and keeps rewriting it on its
    // keepalive, which is what stops the stall detector calling a healthy run
    // interrupted).
    db_chat::append_stream_row(
        username,
        &session_id,
        seq,
        ChatRole::Assistant,
        "",
        "",
        "",
        0,
        false,
        &turn_uuid,
    )
    .await?;

    let run_id = match start_research_workflow(username, &session_id, &message, &allowed, seq).await
    {
        Ok(run_id) => run_id,
        Err(e) => {
            // The workflow never started, so nothing will ever rewrite that row. Close
            // it here rather than leaving the page spinning until the stall timeout.
            let _ = db_chat::mark_stream_final(username, &session_id).await;
            return Err(e);
        }
    };
    Ok(Ok(run_id))
}

/// Every agent run this website process currently has in flight. Admin only.
///
/// Scope is honest about its limits: this is *this process's* inline chat turns. Deep
/// research runs in a Temporal worker and is visible in the Temporal UI instead — the
/// admin page links there rather than pretending to own that view.
pub fn admin_list_live_runs(user: &CurrentUser) -> anyhow::Result<Vec<common::chat_types::LiveChatRun>> {
    require_admin(user)?;
    Ok(live_runs::snapshot())
}

/// Ask an in-flight run to stop. Admin only.
///
/// Cooperative: the run notices between retry attempts and before it writes. It cannot
/// abort an HTTP call already in flight against the agent, so a kill during a slow
/// generation takes effect when that call returns.
pub fn admin_cancel_live_run(user: &CurrentUser, run_id: u64) -> anyhow::Result<bool> {
    require_admin(user)?;
    Ok(live_runs::request_cancel(run_id))
}

fn require_admin(user: &CurrentUser) -> anyhow::Result<()> {
    if !user.is_admin {
        anyhow::bail!("admin access required");
    }
    Ok(())
}

/// Start the `ResearchTask` workflow over Temporal's HTTP API.
///
/// The workflow id is session- and seq-keyed so a double submit is a no-op rather than
/// two agents racing to write the same transcript row.
async fn start_research_workflow(
    username: &str,
    session_id: &str,
    query: &str,
    allowed_collections: &[String],
    start_seq: u32,
) -> anyhow::Result<String> {
    let base_url = std::env::var("TEMPORAL_HTTP_URL")
        .unwrap_or_else(|_| "http://localhost:21908".to_string());
    let workflow_id = format!("research-{session_id}-{start_seq}");
    let url = format!("{base_url}/api/v1/namespaces/default/workflows/{workflow_id}");

    let body = serde_json::json!({
        "workflowType": { "name": "ResearchTask" },
        "taskQueue": { "name": "processing-common-queue" },
        "input": [{
            "username": username,
            "session_id": session_id,
            "query": query,
            "allowed_collections": allowed_collections,
            "start_seq": start_seq,
        }],
    });

    let response = reqwest::Client::new()
        .post(&url)
        .json(&body)
        .send()
        .await?;
    if !response.status().is_success() {
        let text = response.text().await.unwrap_or_default();
        anyhow::bail!("could not start research task: {text}");
    }
    let json: serde_json::Value = response.json().await?;
    Ok(json
        .get("runId")
        .and_then(|v| v.as_str())
        .unwrap_or("started")
        .to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v(items: &[&str]) -> Vec<String> {
        items.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn empty_request_means_every_permitted_collection() {
        assert_eq!(intersect_collections(&[], &v(&["a", "b"])), v(&["a", "b"]));
    }

    #[test]
    fn request_is_narrowed_to_permitted() {
        assert_eq!(
            intersect_collections(&v(&["a", "secret"]), &v(&["a", "b"])),
            v(&["a"])
        );
    }

    #[test]
    fn request_entirely_outside_permissions_yields_nothing() {
        // Not "fall back to everything": a selection of only forbidden collections must
        // narrow to the empty set, never widen.
        assert!(intersect_collections(&v(&["secret"]), &v(&["a"])).is_empty());
    }

    #[test]
    fn a_user_with_no_permissions_gets_nothing() {
        assert!(intersect_collections(&[], &[]).is_empty());
        assert!(intersect_collections(&v(&["a"]), &[]).is_empty());
    }

    #[test]
    fn duplicates_are_collapsed() {
        assert_eq!(intersect_collections(&v(&["a", "a"]), &v(&["a"])), v(&["a"]));
    }

    fn user(username: &str, is_guest: bool) -> CurrentUser {
        CurrentUser {
            username: username.to_string(),
            fullname: String::new(),
            email: String::new(),
            is_admin: false,
            is_guest,
            groups: Vec::new(),
        }
    }

    #[test]
    fn guests_and_anonymous_users_are_refused() {
        // Outside demo mode guests are refused; inside demo mode they are keyed by
        // guest-* username like any other user. Anonymous always refuses.
        assert!(require_named_user_inner(&user("guest-1", true), false).is_err());
        assert_eq!(
            require_named_user_inner(&user("guest-1", true), true).unwrap(),
            "guest-1"
        );
        assert!(require_named_user_inner(&user("", false), false).is_err());
        assert!(require_named_user_inner(&user("", true), true).is_err());
        assert_eq!(require_named_user_inner(&user("ann", false), false).unwrap(), "ann");
    }
}
