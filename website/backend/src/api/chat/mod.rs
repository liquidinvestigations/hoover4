//! AI Chat API: sessions, trajectories, and asking the agent a question.
//!
//! The security property this module exists to hold: **an agent answering for a user
//! can only read collections that user could read in the search UI.** That is enforced
//! in one place — [`send_message`] resolves the live permission set and passes it to the
//! workflow, which passes it to the agent, which passes it to the MCP servers. The
//! collection selection stored on a session is a *preference*; it is intersected with
//! live permissions on every message, so a permission revoked after a chat started takes
//! effect on the next message.
//!
//! **Every turn is a Temporal workflow.** This process never holds an agent call open:
//! [`send_message`] writes the user row, reserves the transcript position and dispatches
//! `ChatTurn`, then returns. The worker writes the answer back into the same tables the
//! poller was already reading, so a website restart, a closed tab or a timed-out request
//! costs nothing — the turn carries on and the page picks it up again.
//!
//! What follows from that, and is the whole reason for the shape of this module:
//!
//! * liveness is read from the transcript and the stream table, not from a registry in
//!   this process — see [`stream_state`];
//! * stopping a turn is a Temporal cancellation, not a flag another task polls;
//! * the admin live-run list is a Temporal visibility query, so it cannot show a run
//!   this process forgot about or hide one it never knew about.

pub mod llm_events;

use std::time::{Duration, Instant};

use common::chat_types::{
    title_from_message, ChatOptions, ChatPollResult, ChatRole, ChatSendResult, ChatSessionDetail,
    ChatSessionItem, StreamToolRow, StreamTurn, MAX_MESSAGE_CHARS,
};
use common::current_user::CurrentUser;
use time::format_description::well_known::Rfc3339;

use crate::api::rate_limit::{check_and_record, RateLimitKind};
use crate::api::telemetry::{self, EVENT_LLM_CHAT_MESSAGE};
use crate::db_chat::{self, AppendMessageExtras};
use crate::db_utils::clickhouse_utils::list_permitted_collections;

/// Cap on sessions returned to the history sidebar / homepage.
const SESSION_LIST_LIMIT: u32 = 100;

/// Reject anonymous use. Guests are allowed only when demo mode is on
/// (`HOOVER4_DEMO_MODE`), keyed by their `guest-*` username like any other user.
///
/// Which users may chat follows from the deployment's mode — see
/// `docs/architecture/Chat_And_Agents.md`.
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

/// Send one user message; the turn runs as a `ChatTurn` workflow on `chat-queue`.
///
/// The user row, the seq allocation and the provisional title happen **here**, under
/// the session's turn lock, before this returns: the caller gets a transcript that
/// already contains the message it just sent, and the returned rows are what the poller
/// counts from. Everything after the dispatch belongs to the worker, so this process
/// holds nothing open and a restart costs the turn nothing.
///
/// The lock is taken with `try_lock`: one turn at a time per session. A second send
/// while a turn is running is a client bug (the composer shows a stop button, not a
/// send button), and blocking the request while a turn runs would be worse than saying
/// so. The lock only covers this process, so [`stream_state`] is asked the same
/// question the poller asks — that is the check that actually holds across processes.
///
/// When the rate limiter refuses, nothing is written and `retry_after_seconds` is set.
///
/// `requested_options` only has effect on the **first** turn of a conversation; after
/// that the frozen values on the session win, so a client that forgets to send them —
/// or forges them — cannot change which agent a thread is talking to mid-way.
///
/// The model is resolved **here**, where the caller's identity is known: a forged id has
/// to be refused where the user is, not in a worker that cannot check it.
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

    let session = db_chat::get_session(username, &session_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("chat session not found"))?;

    // Which profile this turn runs as decides which model setting applies to it, so the
    // session is read first. Frozen options win where they exist; before the first turn
    // nothing is frozen and what the client asked for is what will be frozen.
    let turn_options = if session.options().locked {
        session.options()
    } else {
        requested_options
    };
    // Resolve the model before allocating a seq: a forged id must be refused, not merely
    // absent from the dropdown.
    let llm_model = crate::api::admin::llm::resolve_chat_model(
        requested_model.as_deref(),
        user.is_guest,
        crate::api::admin::llm::ChatProfile::of(turn_options),
    )
    .await?;

    // Live permissions win over whatever the session was created with.
    let permitted = list_permitted_collections(user).await?;
    let allowed = intersect_collections(&session.collections, &permitted);

    // Freeze the agent switches onto the conversation on the first turn; afterwards
    // this returns what was frozen and ignores what the client asked for.
    let options = db_chat::lock_session_options(username, &session_id, requested_options).await?;

    let _guard = db_chat::turn_lock(username, &session_id)
        .try_lock_owned()
        .map_err(|_| anyhow::anyhow!("a turn is already running in this conversation"))?;

    // The lock above only covers this process, and it is released when this function
    // returns — long before the worker writes the answer at the seq reserved here. So
    // ask the same question the poller asks: is a turn still being produced? Without
    // this, a second send during a running turn took the reserved seq and one of the two
    // messages was silently dropped by ReplacingMergeTree.
    if stream_state(username, &session_id).await?.active {
        anyhow::bail!("a turn is already running in this conversation");
    }

    // Everything that decides seqs happens before the dispatch, so the transcript this
    // returns is the one the poller continues from.
    let turn_uuid = crate::db_auth::sessions::generate_session_id();
    let user_seq = db_chat::next_seq(username, &session_id).await?;
    // Read, not inferred from the seq. `next_seq` starts a fresh session at 1, not 0 —
    // ClickHouse's `max()` over an empty UInt32 column is 0 rather than NULL, so the
    // "no rows yet" case and "one row at seq 0" case produce the same number. Deriving
    // the first turn from it silently stopped the conversation ever being titled.
    let is_first_turn = db_chat::list_messages(username, &session_id).await?.is_empty();
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

    // Provisional title from the first user turn; the summariser replaces it at the end
    // of the turn, and it stays as the fallback when the summariser produces nothing.
    if is_first_turn {
        let provisional_title = title_from_message(&message);
        db_chat::touch_session(username, &session_id, Some(&provisional_title), None).await?;
    } else {
        db_chat::touch_session(username, &session_id, None, None).await?;
    }

    let start_seq = user_seq + 1;
    // An empty *stream* row, written before the dispatch and load-bearing rather than
    // decorative. This process runs nothing for the turn, so an open stream row is the
    // only thing telling the poller the turn exists — without it the page would stop
    // following the turn in the seconds before the worker picks the activity up. The
    // worker takes this same seq over and keeps rewriting it, which is what stops the
    // stall detector calling a healthy run interrupted.
    db_chat::append_stream_row(
        username,
        &session_id,
        start_seq,
        ChatRole::Assistant,
        "",
        "",
        "",
        0,
        false,
        &turn_uuid,
    )
    .await?;

    if let Err(e) = start_agent_workflow(AgentWorkflowStart {
        workflow_type: "ChatTurn",
        task_queue: CHAT_TASK_QUEUE,
        workflow_id: &chat_workflow_id(&session_id, start_seq),
        username,
        session_id: &session_id,
        query: &message,
        allowed_collections: &allowed,
        start_seq,
        internet_tools: options.internet_tools,
        llm_model: &llm_model,
        turn_uuid: &turn_uuid,
        summarize_session: is_first_turn,
    })
    .await
    {
        // Nothing will ever rewrite that stream row, so the turn owes the transcript an
        // ending here rather than leaving the page spinning until the stall timeout.
        tracing::error!("could not dispatch the chat turn for {session_id}: {e:#}");
        let _ = db_chat::append_message(
            username,
            &session_id,
            start_seq,
            ChatRole::Error,
            &format!("The assistant could not be reached: {e}"),
            AppendMessageExtras {
                message_uuid: turn_uuid.clone(),
                ..Default::default()
            },
        )
        .await;
        let _ = db_chat::mark_stream_final(username, &session_id).await;
        return Err(e);
    }
    telemetry::record_event(username, EVENT_LLM_CHAT_MESSAGE, "chat");

    let messages = db_chat::list_messages(username, &session_id).await?;
    Ok(ChatSendResult {
        messages,
        retry_after_seconds: None,
    })
}

/// The workflow id one chat turn runs under.
///
/// Session- and seq-keyed so a double submit is a no-op rather than two agents racing to
/// write the same transcript row, and so the stop button and the admin panel can address
/// a running turn without a lookup table.
fn chat_workflow_id(session_id: &str, start_seq: u32) -> String {
    format!("chat-{session_id}-{start_seq}")
}

/// The workflow id one deep-research turn runs under.
fn research_workflow_id(session_id: &str, start_seq: u32) -> String {
    format!("research-{session_id}-{start_seq}")
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
/// **Liveness comes from the transcript and the stream table, and from nothing in this
/// process.** A turn is unfinished when the last user row has no assistant or error row
/// after it; the stream table says how recently something happened. Deriving `active`
/// from "a non-final stream row exists right now" looked equivalent and was not: the
/// writer finalises one row and opens the next as two separate inserts, and a poll
/// landing in that gap reported the turn as over.
///
/// Every turn is a workflow now, so there is no registry of runs this process is holding
/// open, and there must not be one: a website restart would empty it while the turns
/// themselves carried on, and every one of them would read as interrupted. That is why
/// [`send_message`] opens the stream row before it dispatches — the row is the turn's
/// heartbeat from the moment it is accepted, and the worker keeps it beating.
async fn stream_state(username: &str, session_id: &str) -> anyhow::Result<TurnTail> {
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

    // Interrupted = an unfinished turn whose stream rows stopped advancing a stall window
    // ago. A turn that never wrote a stream row at all is not "interrupted": nothing has
    // claimed it yet, and `send_message` writes that row before it dispatches precisely
    // so the window does not exist for an accepted turn.
    let interrupted = turn_open && newest_ms.is_some() && !advancing;
    let active = turn_open && advancing;

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

/// The stop button: cancel this session's in-flight turn.
///
/// A Temporal cancellation, not a flag some other task in this process polls. That is
/// what makes the stop button mean the same thing after a website restart as before one,
/// and it is why a stopped turn cannot be orphaned: `ChatTurn` catches the cancellation
/// and writes an ending into the transcript, so the page stops following a turn that
/// will never speak again.
///
/// The turn is addressed by the seq it reserved, which is derived from the transcript
/// rather than remembered — the last user row with no answer after it is the running
/// turn, and its answer seq is the workflow's id. Both workflow kinds are tried because
/// the composer knows the conversation, not which of the two is running in it.
///
/// `false` means nothing was in flight, which is the ordinary outcome of a stop that
/// arrives just after the turn finished.
pub async fn stop_chat_turn(user: &CurrentUser, session_id: String) -> anyhow::Result<bool> {
    let username = require_named_user(user)?;
    // Ownership: stopping another user's turn is not allowed even though the id is theirs.
    db_chat::get_session(username, &session_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("chat session not found"))?;

    let (last_user_seq, last_answer_seq) = db_chat::turn_boundaries(username, &session_id).await?;
    let Some(user_seq) = last_user_seq else {
        return Ok(false);
    };
    if last_answer_seq.is_some_and(|answer| answer >= user_seq) {
        return Ok(false);
    }
    let start_seq = user_seq + 1;

    let mut cancelled = cancel_workflow(&chat_workflow_id(&session_id, start_seq)).await?;
    if !cancelled {
        cancelled = cancel_workflow(&research_workflow_id(&session_id, start_seq)).await?;
    }
    if cancelled {
        telemetry::record_event(username, EVENT_LLM_CHAT_MESSAGE, "chat_stopped");
    }
    Ok(cancelled)
}

/// Dismiss an interrupted turn's leftover stream rows.
///
/// Refused while the turn is still advancing — dismissing a running turn would hide it
/// from the poller that is following it. "Advancing" is the same question the poller
/// asks, so the button is enabled exactly when the page is showing the interrupted
/// marker.
pub async fn dismiss_interrupted_turn(user: &CurrentUser, session_id: String) -> anyhow::Result<()> {
    let username = require_named_user(user)?;
    if stream_state(username, &session_id).await?.active {
        anyhow::bail!("a turn is still running in this session");
    }
    db_chat::mark_stream_final(username, &session_id).await
}

/// A stream row that has not advanced for this long is an interrupted turn — the worker
/// running it died and Temporal has not rescheduled it — rather than a slow one. The
/// worker's keepalive rewrites the open rows well inside this window, so silence for
/// longer than it means nobody is writing.
fn stream_stall() -> Duration {
    let secs = std::env::var("CHAT_STREAM_STALL_SECONDS")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(60);
    Duration::from_secs(secs.clamp(5, 3600))
}

/// Hand a question to the research agent rather than the chat agent.
///
/// Both are durable now and both reserve their transcript position the same way; what
/// differs is which agent answers, how long it is allowed to take, and which queue it
/// waits on. A research run is exhaustive and measured in minutes, so it must never sit
/// behind a chat turn, and a chat turn must never sit behind it.
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
    // streams its progress into chat_message_stream, so the turn renders live exactly
    // like a chat turn and the workflow writes the finished rows at `seq`.
    //
    // An empty *stream* row does go in, though, and it is load-bearing rather than
    // decorative — the same reason it is in `send_message`. It is the only thing telling
    // the poller the turn exists before the worker picks the activity up, and the
    // activity keeps rewriting it, which is what stops the stall detector calling a
    // healthy run interrupted.
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

    let run_id = match start_agent_workflow(AgentWorkflowStart {
        workflow_type: "ResearchTask",
        task_queue: RESEARCH_TASK_QUEUE,
        workflow_id: &research_workflow_id(&session_id, seq),
        username,
        session_id: &session_id,
        query: &message,
        allowed_collections: &allowed,
        start_seq: seq,
        internet_tools: requested_options.internet_tools,
        llm_model: "",
        turn_uuid: &turn_uuid,
        // A research thread is titled from its first message. Its answer arrives minutes
        // later and is exhaustive rather than conversational, so a title drawn from it
        // describes the report, not the question that was asked.
        summarize_session: false,
    })
    .await
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

/// Every agent turn running anywhere right now. Admin only.
///
/// A Temporal visibility query, not a registry in this process. That is the difference
/// between a list that is true and one that was true: an in-process registry could not
/// see a turn started before the last website restart, and kept listing one whose
/// process died — a restart mid-turn left a run in this panel for ever.
///
/// Chat turns and research turns are both here, because both are workflows and an admin
/// hunting "who is on the GPU" wants one table rather than a page that lists half of them
/// and links elsewhere for the rest.
///
/// The session header behind each run is read from ClickHouse rather than carried in the
/// workflow's memo: the title changes when the summariser writes a better one, and a memo
/// stamped at dispatch would show the admin the old one for the length of the turn.
pub async fn admin_list_live_runs(
    user: &CurrentUser,
) -> anyhow::Result<Vec<common::chat_types::LiveChatRun>> {
    require_admin(user)?;
    let running = list_running_agent_workflows().await?;
    if running.is_empty() {
        return Ok(Vec::new());
    }

    let session_ids: Vec<String> = running.iter().map(|r| r.session_id.clone()).collect();
    let sessions = db_chat::sessions_by_ids(&session_ids).await?;
    let by_id: std::collections::HashMap<&str, &db_chat::ChatSessionRow> = sessions
        .iter()
        .map(|s| (s.session_id.as_str(), s))
        .collect();

    let now_ms = time::OffsetDateTime::now_utc().unix_timestamp_nanos() as i64 / 1_000_000;
    let mut out = Vec::with_capacity(running.len());
    for run in running {
        let Some(session) = by_id.get(run.session_id.as_str()) else {
            // A workflow whose session has been deleted. Skipped rather than shown with
            // blanks: the row would name a conversation nobody can open.
            continue;
        };
        let options = session.options();
        // The question this turn is answering: the user row one below the seq the turn
        // reserved. One query per running turn, and there are single digits of them.
        let message_preview = db_chat::list_messages_after(
            &session.username,
            &run.session_id,
            i64::from(run.start_seq) - 2,
        )
        .await
        .ok()
        .and_then(|rows| {
            rows.into_iter()
                .find(|m| m.role == ChatRole::User)
                .map(|m| preview(&m.content))
        })
        .unwrap_or_default();

        out.push(common::chat_types::LiveChatRun {
            workflow_id: run.workflow_id,
            username: session.username.clone(),
            session_id: run.session_id,
            title: session.title.clone(),
            message_preview,
            deep_research: options.deep_research,
            internet_tools: options.internet_tools,
            running_ms: now_ms.saturating_sub(run.started_ms).max(0) as u64,
            started_at: run.started_at,
        });
    }
    // Longest-running first — the order an admin hunting a stuck chat wants, without
    // having to sort the table themselves.
    out.sort_by(|a, b| b.running_ms.cmp(&a.running_ms));
    Ok(out)
}

/// How much of the question is shown to the admin. Enough to recognise a runaway chat,
/// short enough that the panel is not a transcript viewer — an admin looking for "who is
/// burning the GPU" does not need the whole prompt.
const PREVIEW_CHARS: usize = 200;

fn preview(message: &str) -> String {
    let flat: String = message.split_whitespace().collect::<Vec<_>>().join(" ");
    if flat.chars().count() <= PREVIEW_CHARS {
        return flat;
    }
    format!("{}\u{2026}", flat.chars().take(PREVIEW_CHARS).collect::<String>())
}

/// Cancel a running turn by its workflow id. Admin only.
///
/// The same cancellation the user's own stop button sends, so a turn an admin stops ends
/// the way a turn a user stops does: with an ending written into the transcript rather
/// than a workflow that vanishes. `false` means it had already finished.
pub async fn admin_cancel_live_run(user: &CurrentUser, workflow_id: String) -> anyhow::Result<bool> {
    require_admin(user)?;
    cancel_workflow(&workflow_id).await
}

fn require_admin(user: &CurrentUser) -> anyhow::Result<()> {
    if !user.is_admin {
        anyhow::bail!("admin access required");
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Temporal, over its HTTP API
// ---------------------------------------------------------------------------

/// The queue chat turns are dispatched to.
///
/// **Mirrored in `main_services/processing/tasks/P_agent/workflows.py`** — the worker
/// polls the name it declares there and this addresses the name it declares here, and a
/// workflow addressed to a queue nothing polls waits for ever with no error anywhere. It
/// presents as chat hanging, so the two move in the same patch or not at all.
const CHAT_TASK_QUEUE: &str = "chat-queue";

/// The queue research turns are dispatched to — the general processing queue, where a run
/// measured in minutes can sit behind ingestion without anyone watching it.
const RESEARCH_TASK_QUEUE: &str = "processing-common-queue";

fn temporal_base_url() -> String {
    std::env::var("TEMPORAL_HTTP_URL").unwrap_or_else(|_| "http://localhost:21908".to_string())
}

/// One durable agent turn, as dispatched.
struct AgentWorkflowStart<'a> {
    workflow_type: &'a str,
    task_queue: &'a str,
    workflow_id: &'a str,
    username: &'a str,
    session_id: &'a str,
    query: &'a str,
    allowed_collections: &'a [String],
    start_seq: u32,
    internet_tools: bool,
    /// Resolved and allowlist-checked against the caller's identity. Empty means "the
    /// worker's server default", which is what a research turn takes.
    llm_model: &'a str,
    turn_uuid: &'a str,
    summarize_session: bool,
}

/// Start one agent workflow over Temporal's HTTP API, and return its run id.
///
/// The workflow id is session- and seq-keyed so a double submit is a no-op rather than
/// two agents racing to write the same transcript row.
async fn start_agent_workflow(start: AgentWorkflowStart<'_>) -> anyhow::Result<String> {
    let url = format!(
        "{}/api/v1/namespaces/default/workflows/{}",
        temporal_base_url(),
        start.workflow_id
    );

    let body = serde_json::json!({
        "workflowType": { "name": start.workflow_type },
        "taskQueue": { "name": start.task_queue },
        "input": [{
            "username": start.username,
            "session_id": start.session_id,
            "query": start.query,
            "allowed_collections": start.allowed_collections,
            "start_seq": start.start_seq,
            // The conversation's own switch. Without it the turn always reaches the agent
            // that has the open web, whatever the thread was started with.
            "internet_tools": start.internet_tools,
            "llm_model": start.llm_model,
            // Passed rather than derived. The user row is written with this uuid before
            // the workflow exists, so both processes must agree on it, and passing it is
            // how they agree without a format string each side reimplements.
            "turn_uuid": start.turn_uuid,
            "summarize_session": start.summarize_session,
        }],
    });

    let response = reqwest::Client::new().post(&url).json(&body).send().await?;
    if !response.status().is_success() {
        let text = response.text().await.unwrap_or_default();
        anyhow::bail!("could not start {}: {text}", start.workflow_type);
    }
    let json: serde_json::Value = response.json().await?;
    Ok(json
        .get("runId")
        .and_then(|v| v.as_str())
        .unwrap_or("started")
        .to_string())
}

/// Request cancellation of one workflow. `false` means Temporal has never heard of it,
/// which is the ordinary outcome of stopping a turn that has already finished.
async fn cancel_workflow(workflow_id: &str) -> anyhow::Result<bool> {
    let url = format!(
        "{}/api/v1/namespaces/default/workflows/{workflow_id}/cancel",
        temporal_base_url()
    );
    let response = reqwest::Client::new()
        .post(&url)
        .json(&serde_json::json!({}))
        .send()
        .await?;
    if response.status() == reqwest::StatusCode::NOT_FOUND {
        return Ok(false);
    }
    if !response.status().is_success() {
        let text = response.text().await.unwrap_or_default();
        anyhow::bail!("could not cancel {workflow_id}: {text}");
    }
    Ok(true)
}

/// One running agent workflow, as Temporal's visibility index reports it.
struct RunningWorkflow {
    workflow_id: String,
    session_id: String,
    /// The seq the turn reserved for its answer.
    start_seq: u32,
    started_ms: i64,
    started_at: String,
}

/// Every `ChatTurn` and `ResearchTask` currently running.
async fn list_running_agent_workflows() -> anyhow::Result<Vec<RunningWorkflow>> {
    let query = "WorkflowType IN ('ChatTurn', 'ResearchTask') AND ExecutionStatus = 'Running'";
    let url = format!(
        "{}/api/v1/namespaces/default/workflows",
        temporal_base_url()
    );
    let response = reqwest::Client::new()
        .get(&url)
        .query(&[("query", query)])
        .send()
        .await?;
    if !response.status().is_success() {
        let text = response.text().await.unwrap_or_default();
        anyhow::bail!("could not list running agent turns: {text}");
    }
    let json: serde_json::Value = response.json().await?;
    let Some(executions) = json.get("executions").and_then(|v| v.as_array()) else {
        return Ok(Vec::new());
    };

    let mut out = Vec::new();
    for execution in executions {
        let Some(workflow_id) = execution
            .pointer("/execution/workflowId")
            .and_then(|v| v.as_str())
        else {
            continue;
        };
        let Some((session_id, start_seq)) = split_agent_workflow_id(workflow_id) else {
            continue;
        };
        let started_at = execution
            .get("startTime")
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .to_string();
        let started_ms = time::OffsetDateTime::parse(&started_at, &Rfc3339)
            .map(|t| t.unix_timestamp_nanos() as i64 / 1_000_000)
            .unwrap_or(0);
        out.push(RunningWorkflow {
            workflow_id: workflow_id.to_string(),
            session_id,
            start_seq,
            started_ms,
            started_at,
        });
    }
    Ok(out)
}

/// Split an agent workflow id back into the session and the seq it reserved.
///
/// The id is built by [`chat_workflow_id`] / [`research_workflow_id`] and is the only
/// thing Temporal's visibility index carries about the turn, so it is parsed rather than
/// looked up. A session id contains no `-`, so the last one separates the seq.
fn split_agent_workflow_id(workflow_id: &str) -> Option<(String, u32)> {
    let rest = workflow_id
        .strip_prefix("chat-")
        .or_else(|| workflow_id.strip_prefix("research-"))?;
    let (session_id, seq) = rest.rsplit_once('-')?;
    if session_id.is_empty() {
        return None;
    }
    Some((session_id.to_string(), seq.parse().ok()?))
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
    fn a_workflow_id_round_trips_through_its_split() {
        // The id is the only thing Temporal's visibility index carries about a turn, so
        // the admin panel depends on this being exactly the inverse of the builders.
        let session = "4f3a9c2b1d";
        for id in [
            chat_workflow_id(session, 7),
            research_workflow_id(session, 7),
        ] {
            assert_eq!(
                split_agent_workflow_id(&id),
                Some((session.to_string(), 7)),
                "failed on {id}"
            );
        }
    }

    #[test]
    fn a_workflow_id_from_somewhere_else_is_not_an_agent_turn() {
        // The query filters by workflow type, but the panel must not turn a stray id into
        // a row naming a conversation that does not exist.
        assert_eq!(split_agent_workflow_id("P0-ingest-abc-1"), None);
        assert_eq!(split_agent_workflow_id("chat-noseq"), None);
        assert_eq!(split_agent_workflow_id("chat--1"), None);
        assert_eq!(split_agent_workflow_id("chat-abc-notanumber"), None);
    }

    #[test]
    fn preview_collapses_whitespace_and_truncates() {
        assert_eq!(preview("  a\n b  "), "a b");
        let long = "x".repeat(PREVIEW_CHARS + 50);
        assert_eq!(preview(&long).chars().count(), PREVIEW_CHARS + 1);
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
