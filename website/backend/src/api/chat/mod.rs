//! AI Chat API: sessions, trajectories, and asking the agent a question.
//!
//! The security property this module exists to hold: **an agent answering for a user
//! can only read collections that user could read in the search UI.** That is enforced
//! in one place. [`send_message`] resolves the live permission set and passes it to the
//! workflow, which passes it to the agent, which passes it to the MCP servers. The
//! collection selection stored on a session is a *preference*; it is intersected with
//! live permissions on every message, so a permission revoked after a chat started takes
//! effect on the next message.
//!
//! **Every turn is a Temporal workflow.** This process never holds an agent call open:
//! [`send_message`] writes the user row, reserves the transcript position and dispatches
//! `AgentRun`, then returns. The worker writes the answer back into the same tables the
//! poller was already reading, so a website restart, a closed tab or a timed-out request
//! costs nothing. The turn carries on and the page picks it up again.
//!
//! What follows from that, and is the whole reason for the shape of this module:
//!
//! * liveness is read from the transcript and the stream table, not from a registry in
//!   this process, and a stale turn asks Temporal whether a run of it waits for a model
//!   slot, see [`stream_state`];
//! * stopping a turn is a Temporal cancellation, not a flag another task polls;
//! * the admin live-run list is a Temporal visibility query, so it cannot show a run
//!   this process forgot about or hide one it never knew about;
//! * a new turn is refused by [`gate`] when no provider is configured, when a
//!   non-self-hosted provider has an empty API key, or when `chat_enabled` is false.
//!   An in-flight turn is left to finish.

pub mod gate;
pub mod llm_events;
pub mod plans;
pub mod run_queue;

use std::time::{Duration, Instant};

use rand::RngCore;

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

pub async fn list_chat_sessions(user: &CurrentUser) -> anyhow::Result<Vec<ChatSessionItem>> {
    let username = user.username.as_str();
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
    let username = user.username.as_str();
    let permitted = list_permitted_collections(user).await?;
    let selected = intersect_collections(&collections, &permitted);
    db_chat::create_session(username, "New chat", &selected).await
}

pub async fn get_chat_session(
    user: &CurrentUser,
    session_id: String,
) -> anyhow::Result<ChatSessionDetail> {
    let username = user.username.as_str();
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
        queued: tail.queued,
        queued_for: tail.queued_for,
    })
}

pub async fn delete_chat_session(user: &CurrentUser, session_id: String) -> anyhow::Result<()> {
    let username = user.username.as_str();
    db_chat::delete_session(username, &session_id).await
}

/// The search-detail JSON behind a `web_search` card's popup.
///
/// Served through a server function rather than the `/_chat_artifact/…` route because the
/// popup renders it, and a fetch from WASM would need its own credential handling and its
/// own copy of the ACL. Images and the archived-page iframe still use the HTTP route:
/// `<img src>` and `<iframe src>` cannot call a server function.
///
/// Same rule as the route: the id is a lookup key from an LLM-driven tool payload, so it
/// is resolved to its owner and checked, never trusted.
pub async fn get_chat_artifact_detail(
    user: &CurrentUser,
    artifact_id: String,
) -> anyhow::Result<String> {
    let username = user.username.as_str();
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
    let username = user.username.as_str();
    let permitted = list_permitted_collections(user).await?;
    let selected = intersect_collections(&collections, &permitted);
    db_chat::touch_session(username, &session_id, None, Some(&selected)).await
}

/// Keep only requested collections the user may actually read.
///
/// An empty request means "everything I am allowed to see". That is the useful default
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

/// Send one user message; the turn runs as an `AgentRun` workflow on `chat-queue`.
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
/// question the poller asks. That is the check that actually holds across processes.
///
/// When the rate limiter refuses, nothing is written and `retry_after_seconds` is set.
///
/// `requested_options` only has effect on the **first** turn of a conversation; after
/// that the frozen values on the session win, so a client that forgets to send them
/// (or forges them) cannot change which agent a thread is talking to mid-way.
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
    gate::require_chat_open().await?;
    let username = user.username.as_str();

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
    // returns. Long before the worker writes the answer at the seq reserved here. So
    // ask the same question the poller asks: is a turn still being produced? Without
    // this, a second send during a running turn took the reserved seq and one of the two
    // messages was silently dropped by ReplacingMergeTree.
    if stream_state(username, &session_id).await?.active {
        anyhow::bail!("a turn is already running in this conversation");
    }
    // The pending plan rule: a plan that waits for review or runs owns the conversation.
    if db_chat::plans::session_has_open_plan(username, &session_id).await? {
        anyhow::bail!(plans::PLAN_PENDING_TEXT);
    }

    // Everything that decides seqs happens before the dispatch, so the transcript this
    // returns is the one the poller continues from.
    let turn_uuid = crate::db_auth::sessions::generate_session_id();
    let user_seq = db_chat::next_seq(username, &session_id).await?;
    // Read, not inferred from the seq. `next_seq` starts a fresh session at 1, not 0.
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
    // Reported, not prevented. See `detect_seq_collision`. Refusing here costs the user
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
    // An empty *stream* row, written before the dispatch and required rather than
    // decorative. This process runs nothing for the turn, so an open stream row is the
    // only thing telling the poller the turn exists, without it the page would stop
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

    // The input holds ids and settings only. The worker reads the message text from the
    // user row written above, so no text crosses a Temporal payload. The worker decides
    // whether this is the first turn, and titles the session then.
    if let Err(e) = start_agent_workflow(AgentWorkflowStart {
        workflow_type: "AgentRun",
        task_queue: CHAT_TASK_QUEUE,
        workflow_id: &chat_workflow_id(&session_id, start_seq),
        input: serde_json::json!({
            "run_id": new_run_id(),
            "username": username,
            "session_id": &session_id,
            "kind": "chat",
            "turn_seq": user_seq,
            "start_seq": start_seq,
            "turn_uuid": &turn_uuid,
            "allowed_collections": &allowed,
            "llm_model": &llm_model,
            // The conversation's own switch. It selects the agent service.
            "internet_tools": options.internet_tools,
        }),
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


// ---------------------------------------------------------------------------
// Polling the in-flight turn
// ---------------------------------------------------------------------------

/// How long one poll holds the request when nothing changes. The 500 ms step doubles
/// as the floor while content is flowing. See the loop in [`poll_chat`].
const POLL_HOLD: Duration = Duration::from_secs(15);
const POLL_STEP: Duration = Duration::from_millis(500);

/// Concurrently-held polls per user. A held request is a cheap way to exhaust a
/// server, so past this cap a poll answers immediately with the current state instead
/// of holding. The client polls again sooner. Eight covers twelve tabs of one user:
/// eight hold, and four take the 500 ms floor. Override with
/// `HOOVER4_MAX_HELD_POLLS_PER_USER`.
const DEFAULT_MAX_HELD_POLLS_PER_USER: usize = 8;

static MAX_HELD_POLLS_PER_USER: std::sync::LazyLock<usize> = std::sync::LazyLock::new(|| {
    std::env::var("HOOVER4_MAX_HELD_POLLS_PER_USER")
        .ok()
        .and_then(|v| v.trim().parse::<usize>().ok())
        .filter(|n| *n >= 1)
        .unwrap_or(DEFAULT_MAX_HELD_POLLS_PER_USER)
});

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
        if *count >= *MAX_HELD_POLLS_PER_USER {
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
/// **Liveness comes from the transcript, the run rows and the stream table, and from
/// nothing in this process.** A turn is unfinished when the last user row has no
/// assistant or error row after it, or when a run of that turn is `running` or
/// `waiting_for_children`. The second test holds a nag round and a delegation open,
/// because both follow an assistant or tool row. The stream rows and the run rows say
/// how recently something happened.
///
/// A step that waits in its Temporal task queue for a free slot writes no row, and a long
/// tool call writes no row while it runs. When the rows of an open turn are older than
/// [`CHAT_QUIET_MS`], this function asks Temporal what the steps of each `running` run
/// do. A step on a worker keeps the turn `active`. A step that waits on a queue that a
/// worker polls makes the turn `queued`, with `queued_for` `model` or `tool`: it stays
/// `active` and is not `interrupted`. See [`run_queue`]. Deriving `active`
/// from "a non-final stream row exists right now" looked equivalent and was not: the
/// writer finalises one row and opens the next as two separate inserts, and a poll
/// landing in that gap reported the turn as over.
///
/// Every turn is a workflow now, so there is no registry of runs this process is holding
/// open, and there must not be one: a website restart would empty it while the turns
/// themselves carried on, and every one of them would read as interrupted. That is why
/// [`send_message`] opens the stream row before it dispatches. The row is the turn's
/// heartbeat from the moment it is accepted, and the worker keeps it beating.
async fn stream_state(username: &str, session_id: &str) -> anyhow::Result<TurnTail> {
    let (last_user_seq, last_answer_seq) = db_chat::turn_boundaries(username, session_id).await?;
    // The runs of the last turn. A nag round writes an assistant row and then runs again,
    // and a delegation waits for its sub-agents after its tool rows. In both cases the
    // transcript test below reads the turn as closed while a run of it is still open.
    let runs = match last_user_seq {
        Some(user) => db_chat::turn_runs(username, session_id, user).await?,
        None => Vec::new(),
    };
    let run_open = runs.iter().any(|r| r.is_open());
    let turn_open = turn_is_open(last_user_seq, last_answer_seq, &runs);

    let rows = db_chat::read_stream_rows(username, session_id).await?;
    // Freshness is measured over every row of the turn, final or not, and over the run
    // rows, whose keepalive moves `updated_at` every 30 s while a run works. The last thing
    // that happened is the clock, whichever row it happened on.
    let newest_ms = rows
        .iter()
        .filter(|r| Some(r.seq) > last_user_seq)
        .map(|r| r.updated_at)
        .chain(runs.iter().map(|r| r.updated_ms))
        .max();
    let subagent_runs = if run_open {
        load_subagent_runs(username, session_id, &runs).await?
    } else {
        Vec::new()
    };
    let now_ms = time::OffsetDateTime::now_utc().unix_timestamp_nanos() as i64 / 1_000_000;
    let stall_ms = stream_stall().as_millis() as i64;
    let advancing = newest_ms.is_some_and(|ms| now_ms - ms <= stall_ms);

    // Interrupted = an unfinished turn whose stream rows stopped advancing a stall window
    // ago. A turn that never wrote a stream row at all is not "interrupted": nothing has
    // claimed it yet, and `send_message` writes that row before it dispatches precisely
    // so the window does not exist for an accepted turn.
    // A plan that waits for review or runs a long execution writes no stream rows for a
    // while, so its turn is never reported as interrupted (the pending plan rule).
    let plan_pending = db_chat::plans::session_has_open_plan(username, session_id).await?;
    // A step that waits for a slot writes no row, and a long tool call writes no row while
    // it runs. After the quiet time, Temporal says what the steps of the turn do.
    let quiet = turn_open
        && !plan_pending
        && newest_ms.is_none_or(|ms| now_ms - ms > CHAT_QUIET_MS);
    let (working, queued_for) = if quiet {
        turn_step_state(&runs).await
    } else {
        (false, "")
    };
    let (active, queued, interrupted) = run_queue::turn_verdict(
        turn_open,
        advancing || working,
        plan_pending,
        newest_ms.is_some(),
        !queued_for.is_empty(),
    );
    let queued_for = if queued { queued_for.to_string() } else { String::new() };

    // A tool row stays live past `is_final`: the writer marks it final at `tool_result`,
    // well before the durable `chat_messages` row exists, which the workflow only
    // writes once the whole agent activity returns. Dropping a tool row the moment it
    // finalises left a completed tool with no displayed representation for that
    // interval. An assistant row keeps the old rule (`is_final == 0` only), because the
    // writer reopens a fresh assistant row on every finalisation (see `_write_assistant`
    // in `stream_writer.py`), so a finalised assistant row is always superseded by a
    // newer live one and never needs to stay.
    let live: Vec<_> = rows
        .iter()
        .filter(|r| r.is_final == 0 || r.role == ChatRole::Tool.as_str())
        .collect();
    if live.is_empty() {
        return Ok(TurnTail {
            stream: waiting_turn(subagent_runs, last_user_seq),
            active,
            queued,
            queued_for: queued_for.clone(),
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
            stream: waiting_turn(subagent_runs, last_user_seq),
            active,
            queued,
            queued_for: queued_for.clone(),
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
            // `is_final` on a tool row means `tool_result` has been seen, not that the
            // durable row exists yet: the row above stays live in that interval on
            // purpose (see the comment on `live`), and the card reads this to switch
            // from a running state to a completed one before the durable row arrives.
            done: r.is_final != 0,
            // A running tool's stream row is written once, at `tool_start`, and not
            // touched again until the call finalises into `chat_messages`, the keepalive
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
        subagent_runs,
    };

    Ok(TurnTail {
        stream: Some(turn),
        active,
        queued,
        queued_for,
        interrupted,
    })
}

/// How long an open turn writes no row before the page asks Temporal what its steps do.
const CHAT_QUIET_MS: i64 = 45_000;

/// What the steps of the `running` runs of a turn do: `(working, queued_for)`.
///
/// The first run with a step on a worker gives `(true, "")`. The first run with a model
/// step that waits on a polled model queue gives `"model"`, and with a tool step that
/// waits on the polled tool queue gives `"tool"`. A failed read counts as neither.
async fn turn_step_state(runs: &[db_chat::AgentRunRow]) -> (bool, &'static str) {
    for run in runs
        .iter()
        .filter(|r| r.state == "running" && !r.workflow_id.is_empty())
    {
        match run_queue::run_step_state(&run.workflow_id).await {
            run_queue::StepState::Working => return (true, ""),
            run_queue::StepState::QueuedModel if run_queue::queue_has_poller(&run.queue).await => {
                return (false, "model");
            }
            run_queue::StepState::QueuedTool
                if run_queue::queue_has_poller(AGENT_TOOL_TASK_QUEUE).await =>
            {
                return (false, "tool");
            }
            _ => {}
        }
    }
    (false, "")
}

/// A turn is open when its user row has no assistant or error row after it, or when a
/// run of the turn is `running` or `waiting_for_children`.
fn turn_is_open(
    last_user_seq: Option<u32>,
    last_answer_seq: Option<u32>,
    runs: &[db_chat::AgentRunRow],
) -> bool {
    runs.iter().any(|r| r.is_open())
        || match (last_user_seq, last_answer_seq) {
            (Some(user), Some(answer)) => answer < user,
            (Some(_), None) => true,
            // No user row: nothing has been asked, so nothing can be in flight.
            (None, _) => false,
        }
}

/// The in-flight turn while it has no live stream row and has sub-agent runs to show.
///
/// A delegating run writes its `run_subagent` tool rows and ends its stream rows, then
/// waits for its sub-agents. The entries travel on an empty [`StreamTurn`], so the page
/// shows the sub-agents and a working marker under the finished tool rows.
fn waiting_turn(
    subagent_runs: Vec<common::chat_types::SubagentRunEntry>,
    last_user_seq: Option<u32>,
) -> Option<StreamTurn> {
    if subagent_runs.is_empty() {
        return None;
    }
    Some(StreamTurn {
        answer_seq: last_user_seq.unwrap_or(0) + 1,
        content: String::new(),
        reasoning: String::new(),
        tool_rows: Vec::new(),
        updated_ms: 0,
        subagent_runs,
    })
}

/// The `subagent_runs` of the poll: the entries of [`subagent_entries`], with the message
/// tails of the running entries and the tool counts of every entry.
async fn load_subagent_runs(
    username: &str,
    session_id: &str,
    runs: &[db_chat::AgentRunRow],
) -> anyhow::Result<Vec<common::chat_types::SubagentRunEntry>> {
    let mut entries = subagent_entries(runs);
    if entries.is_empty() {
        return Ok(entries);
    }
    let threads: Vec<String> = entries.iter().map(|e| e.run_id.clone()).collect();
    let running: Vec<String> = entries
        .iter()
        .filter(|e| e.state == "running")
        .map(|e| e.run_id.clone())
        .collect();
    let counts: std::collections::HashMap<String, u64> =
        db_chat::thread_tool_counts(username, session_id, &threads)
            .await?
            .into_iter()
            .collect();
    let tails = db_chat::thread_message_tails(
        username,
        session_id,
        &running,
        common::chat_types::SUBAGENT_MESSAGES_PER_RUN,
    )
    .await?;
    for entry in &mut entries {
        entry.tool_calls = counts.get(&entry.run_id).copied().unwrap_or(0) as u32;
        if entry.state != "running" {
            continue;
        }
        // The query returns the newest first. The card reads them oldest first.
        let mut messages: Vec<&db_chat::RunMessageHead> =
            tails.iter().filter(|m| m.thread == entry.run_id).collect();
        messages.sort_by_key(|m| m.idx);
        entry.messages = messages.into_iter().map(subagent_message).collect();
    }
    Ok(entries)
}

fn subagent_message(m: &db_chat::RunMessageHead) -> common::chat_types::SubagentMessage {
    let calls = serde_json::from_str::<Vec<serde_json::Value>>(&m.tool_calls_json)
        .unwrap_or_default()
        .iter()
        .filter_map(|c| c.get("name").and_then(|n| n.as_str()).map(str::to_string))
        .collect();
    common::chat_types::SubagentMessage {
        role: m.role.clone(),
        content: m.text.clone(),
        tool_name: m.tool_name.clone(),
        calls,
        is_final: m.is_final != 0,
    }
}

/// The entries of the current delegation batches of one turn, without messages or tool
/// counts.
///
/// For each depth 0 thread, take its newest run, which is the run that no other run
/// continues. When that run waits for its children, list the children of its batch.
/// For each listed thread, list the children of its newest waiting run the same way.
/// Earlier runs of a thread also stay `waiting_for_children` until the last continuation
/// ends, so reading every waiting run would list every past batch. The newest run of a
/// thread is what bounds the list to 5 + 25 = 30 entries. A thread whose newest run no
/// longer waits has a batch that ended, and its card reads the reports from the tool row.
fn subagent_entries(runs: &[db_chat::AgentRunRow]) -> Vec<common::chat_types::SubagentRunEntry> {
    let continued: std::collections::HashSet<&str> = runs
        .iter()
        .filter(|r| !r.continues.is_empty())
        .map(|r| r.continues.as_str())
        .collect();
    // The newest run of a thread: the run of that thread that nothing continues.
    fn newest_of<'a>(
        runs: &'a [db_chat::AgentRunRow],
        continued: &std::collections::HashSet<&str>,
        thread: &str,
    ) -> Option<&'a db_chat::AgentRunRow> {
        runs.iter()
            .filter(|r| r.thread == thread && !continued.contains(r.rid.as_str()))
            .max_by_key(|r| r.started_ms)
    }
    let newest = |thread: &str| newest_of(runs, &continued, thread);
    // The first runs of the batch that `waiting` started, in start order.
    let children = |waiting: &db_chat::AgentRunRow| -> Vec<&db_chat::AgentRunRow> {
        if waiting.state != "waiting_for_children" || waiting.delegated_batch.is_empty() {
            return Vec::new();
        }
        runs.iter()
            .filter(|r| {
                r.parent_rid == waiting.rid
                    && r.batch == waiting.delegated_batch
                    && r.continues.is_empty()
            })
            .collect()
    };
    let entry = |first: &db_chat::AgentRunRow, parent_thread: &str| {
        let last = newest(&first.thread).unwrap_or(first);
        let objective = serde_json::from_str::<serde_json::Value>(&first.briefing)
            .ok()
            .and_then(|b| b.get("objective").and_then(|o| o.as_str()).map(str::to_string))
            .unwrap_or_default();
        let mut e = common::chat_types::SubagentRunEntry {
            run_id: first.rid.clone(),
            parent_run_id: parent_thread.to_string(),
            depth: first.depth,
            batch_id: first.batch.clone(),
            tool_call_id: first.tool_call_id.clone(),
            state: last.state.clone(),
            objective,
            tool_calls: 0,
            messages: Vec::new(),
            report: String::new(),
        };
        if e.is_terminal() {
            e.report = if last.error_head.is_empty() {
                last.result_head.clone()
            } else {
                last.error_head.clone()
            };
        }
        e
    };

    // Each entry with the start time of its batch's delegating run, for the cap below.
    let mut out: Vec<(i64, common::chat_types::SubagentRunEntry)> = Vec::new();
    let leads = runs
        .iter()
        .filter(|r| r.depth == 0 && r.continues.is_empty());
    for lead in leads {
        let Some(lead_last) = newest(&lead.thread) else {
            continue;
        };
        for child in children(lead_last) {
            out.push((lead_last.started_ms, entry(child, &lead.thread)));
            if let Some(child_last) = newest(&child.thread) {
                for grandchild in children(child_last) {
                    out.push((child_last.started_ms, entry(grandchild, &child.thread)));
                }
            }
        }
    }
    // The cap. A plan's organizer counts its runs against the plan budget, not the turn
    // limit, so the 5 + 25 bound needs the cap to hold. Past it the newest batches stay.
    if out.len() > SUBAGENT_ENTRIES_CAP {
        out.sort_by_key(|(batch_ms, _)| std::cmp::Reverse(*batch_ms));
        out.truncate(SUBAGENT_ENTRIES_CAP);
    }
    out.into_iter().map(|(_, e)| e).collect()
}

/// The most entries in the poll's `subagent_runs`: 5 depth 1 runs and 5 x 5 depth 2 runs.
const SUBAGENT_ENTRIES_CAP: usize = 30;

/// What the poll and the session load both need to know about the tail of a session.
struct TurnTail {
    stream: Option<StreamTurn>,
    active: bool,
    /// A step of the turn waits for a free slot. `active` is true with it.
    queued: bool,
    /// `model` or `tool` while `queued`, else empty.
    queued_for: String,
    interrupted: bool,
}

/// One version stamp for the poll's change detection. `updated_ms` moves on every
/// stream write, the finished tail moves on every finalised row, and the hash of the
/// sub-agent entries moves on every sub-agent message and state. Together they cover
/// everything a client can see.
fn poll_sig(finished_max_seq: Option<u32>, tail: &TurnTail) -> String {
    use std::hash::{Hash, Hasher};
    format!(
        "{}:{}:{}:{}:{}",
        finished_max_seq.map(|s| s.to_string()).unwrap_or_default(),
        tail.stream
            .as_ref()
            .map(|t| {
                let mut hasher = std::collections::hash_map::DefaultHasher::new();
                serde_json::to_string(&t.subagent_runs)
                    .unwrap_or_default()
                    .hash(&mut hasher);
                format!(
                    "{}:{}:{}:{:x}",
                    t.updated_ms,
                    t.content.len(),
                    t.tool_rows.len(),
                    hasher.finish()
                )
            })
            .unwrap_or_default(),
        tail.active,
        tail.interrupted,
        tail.queued_for,
    )
}

/// Long-poll the tail of a conversation.
///
/// Returns finished rows with `seq > after_seq` plus the in-flight turn. Holds up to
/// [`POLL_HOLD`] when nothing changes and returns immediately when the signature moves,
/// one poll updates the whole tail of the transcript.
///
/// Every poll after the first takes at least [`POLL_STEP`]. That floor is not a
/// courtesy: with content flowing, each poll finds a change and returns at once, so
/// without it a client would spin as fast as the network allows, and so would every
/// client past the held-poll cap, which returns immediately by design.
pub async fn poll_chat(
    user: &CurrentUser,
    session_id: String,
    after_seq: Option<u32>,
    sig: String,
) -> anyhow::Result<ChatPollResult> {
    let username = user.username.as_str();
    // Typed, not prose. The client counts consecutive poll failures and declares "lost
    // contact with the chat" at three, and a rate limit is the opposite of lost contact:
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
                queued: tail.queued,
                queued_for: tail.queued_for,
                sig: current_sig,
            });
        }
        tokio::time::sleep(POLL_STEP).await;
    }
}

/// The stop button: stop the conversation's in-flight turn and every run of it.
///
/// Three steps, in this order:
///
/// 1. Write the stop row of the turn with a synchronous insert. A run whose workflow
///    starts after this, such as a sub-agent that a delegation is starting now, reads the
///    row in `open_run` and closes as `cancelled`, and a fan-in that reads it starts no
///    continuation.
/// 2. Cancel the workflow of every `running` run of the turn, read from `agent_runs`.
///    `AgentRun` catches the cancellation and writes the ending of the run. A run that
///    waits for its children has no open workflow, and its children end it.
///
/// A 404 from a cancellation counts as success, because the workflow ended before the
/// request. The turn is found from the transcript and the run rows, so a stop during a
/// nag round or a delegation finds it, although an assistant or tool row follows the user
/// row.
///
/// `false` means nothing was in flight, which is the ordinary outcome of a stop that
/// arrives just after the turn finished.
pub async fn stop_chat_turn(user: &CurrentUser, session_id: String) -> anyhow::Result<bool> {
    let username = user.username.as_str();
    // Ownership: stopping another user's turn is not allowed even though the id is theirs.
    db_chat::get_session(username, &session_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("chat session not found"))?;

    let (last_user_seq, last_answer_seq) = db_chat::turn_boundaries(username, &session_id).await?;
    let Some(user_seq) = last_user_seq else {
        return Ok(false);
    };
    let runs = db_chat::turn_runs(username, &session_id, user_seq).await?;
    let transcript_open = last_answer_seq.is_none_or(|answer| answer < user_seq);
    if !transcript_open && !runs.iter().any(|r| r.is_open()) {
        return Ok(false);
    }

    db_chat::write_turn_stop(username, &session_id, user_seq).await?;
    for run in runs.iter().filter(|r| r.state == "running") {
        // A failed cancellation of one run does not keep the others running. The stop row
        // still ends that run at its next `open_run`, fan-in or sweep.
        if let Err(e) = cancel_workflow(&run.workflow_id).await {
            tracing::warn!("stop of session {session_id}: {e}");
        }
    }
    telemetry::record_event(username, EVENT_LLM_CHAT_MESSAGE, "chat_stopped");
    Ok(true)
}

/// Dismiss an interrupted turn's leftover stream rows.
///
/// Refused while the turn is still advancing. Dismissing a running turn would hide it
/// from the poller that is following it. "Advancing" is the same question the poller
/// asks, so the button is enabled exactly when the page is showing the interrupted
/// marker.
pub async fn dismiss_interrupted_turn(user: &CurrentUser, session_id: String) -> anyhow::Result<()> {
    let username = user.username.as_str();
    if stream_state(username, &session_id).await?.active {
        anyhow::bail!("a turn is still running in this session");
    }
    db_chat::mark_stream_final(username, &session_id).await
}

/// How long a turn's stream rows may stand still before the page calls it interrupted.
///
/// **This number and the worker's chat-activity heartbeat timeout are one pair and must
/// be read together.** The heartbeat timeout of a step (`STEP_HEARTBEAT_TIMEOUT` in
/// `main_services/processing/tasks/P_agent/model_timeouts.py`, 30 s) is how long a dead worker
/// goes unnoticed; this is how long the page waits before saying so. This one is
/// deliberately the larger, by a wide margin, because the marker's advice is "ask again
/// to retry" and Temporal reschedules the activity on its own: a page that gave up first
/// would talk a user into a second question while the first answer was still coming, and
/// they would get the same answer twice from two workflows.
///
/// 180 s against a 30 s heartbeat timeout leaves 150 s for the reschedule to be noticed,
/// a worker to pick the activity up and its first row to land. Raising the heartbeat
/// timeout without raising this by more reintroduces the defect; setting them equal
/// reintroduces it at a different scale.
const CHAT_STREAM_STALL_DEFAULT_SECONDS: u64 = 180;

/// A stream row that has not advanced for this long is an interrupted turn rather than a
/// slow one. Nothing is writing it, and no reschedule is close enough to wait for. The
/// worker's keepalive rewrites the open rows every 30 s, so silence for longer than this
/// means neither the original attempt nor a retry of it is running.
fn stream_stall() -> Duration {
    let secs = std::env::var("CHAT_STREAM_STALL_SECONDS")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(CHAT_STREAM_STALL_DEFAULT_SECONDS);
    Duration::from_secs(secs.clamp(5, 3600))
}

/// Start a deep-research request: a plan run whose first run is a planner.
///
/// The planner builds the plan tree and answers with an orientation. The plan then waits
/// for review with no workflow open, and [`plans::decide_plan`] starts each later run. The
/// planner runs on `research-queue`, so a research run never sits behind a chat turn, and
/// a chat turn never sits behind it.
///
/// The internet switch is the conversation's frozen value, which `lock_session_options`
/// returns. The request's value is ignored once the conversation is locked, as for a chat
/// turn.
///
/// Returns the plan run id, or the retry delay of a rate limit.
pub async fn start_research_task(
    user: &CurrentUser,
    session_id: String,
    message: String,
    requested_options: ChatOptions,
) -> anyhow::Result<Result<String, u64>> {
    gate::require_chat_open().await?;
    let username = user.username.as_str();

    if let Err(e) = check_and_record(username, RateLimitKind::ChatMessage) {
        // Nothing written, consistent with send_message's rate-limit path.
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

    // Deep research reserves transcript seqs exactly like a chat turn, so it takes the
    // same lock, and it refuses rather than waits, as `send_message` does.
    let _guard = db_chat::turn_lock(username, &session_id)
        .try_lock_owned()
        .map_err(|_| anyhow::anyhow!("a turn is already running in this conversation"))?;
    if stream_state(username, &session_id).await?.active {
        anyhow::bail!("a turn is already running in this conversation");
    }
    if db_chat::plans::session_has_open_plan(username, &session_id).await? {
        anyhow::bail!(plans::PLAN_PENDING_TEXT);
    }

    // Deep research is one of the two frozen switches. A thread that started as a research
    // thread stays one. The returned options are the frozen ones.
    let frozen = db_chat::lock_session_options(
        username,
        &session_id,
        ChatOptions {
            deep_research: true,
            ..requested_options
        },
    )
    .await?;

    let is_first_turn = db_chat::list_messages(username, &session_id).await?.is_empty();
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
    db_chat::detect_seq_collision(username, &session_id, user_seq, &turn_uuid).await?;
    if is_first_turn {
        db_chat::touch_session(username, &session_id, Some(&title_from_message(&message)), None)
            .await?;
    } else {
        db_chat::touch_session(username, &session_id, None, None).await?;
    }

    // The empty stream row tells the poller that the turn exists before the worker picks
    // the run up, as in `send_message`.
    let start_seq = user_seq + 1;
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

    let plan_run_id = new_run_id();
    if let Err(e) = start_agent_workflow(AgentWorkflowStart {
        workflow_type: "AgentRun",
        task_queue: CHAT_TASK_QUEUE,
        workflow_id: &plans::planner_workflow_id(&plan_run_id, 0),
        input: plans::research_start_input(
            frozen,
            &new_run_id(),
            &plan_run_id,
            username,
            &session_id,
            user_seq,
            &turn_uuid,
            &allowed,
        ),
    })
    .await
    {
        tracing::error!("could not start the research plan for {session_id}: {e:#}");
        let _ = db_chat::append_message(
            username,
            &session_id,
            start_seq,
            ChatRole::Error,
            &format!("The research plan could not be started: {e}"),
            AppendMessageExtras {
                message_uuid: turn_uuid.clone(),
                ..Default::default()
            },
        )
        .await;
        let _ = db_chat::mark_stream_final(username, &session_id).await;
        return Err(e);
    }
    Ok(Ok(plan_run_id))
}

/// Every agent turn running anywhere right now. Admin only.
///
/// A Temporal visibility query, not a registry in this process. That is the difference
/// between a list that is true and one that was true: an in-process registry could not
/// see a turn started before the last website restart, and kept listing one whose
/// process died. A restart mid-turn left a run in this panel for ever.
///
/// Chat runs, sub-agent runs and research turns are all here, one entry for each open
/// workflow, so a delegated turn shows its lead and each sub-agent that runs. An admin
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
        // The question this turn is answering: the user row of the turn. One query per
        // running run, and there are tens of them at most.
        let message_preview = db_chat::list_messages_after(
            &session.username,
            &run.session_id,
            i64::from(run.turn_seq) - 1,
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
    // Longest-running first, the order an admin hunting a stuck chat wants, without
    // having to sort the table themselves.
    out.sort_by(|a, b| b.running_ms.cmp(&a.running_ms));
    Ok(out)
}

/// How much of the question is shown to the admin. Enough to recognise a runaway chat,
/// short enough that the panel is not a transcript viewer. An admin looking for "who is
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

/// The queue chat turns are dispatched to, and the queue that writes the transcript,
/// reads the todo list and titles the session.
///
/// **Mirrored in `main_services/processing/tasks/P_agent/workflows.py`**. The worker
/// polls the name it declares there and this addresses the name it declares here, and a
/// workflow addressed to a queue nothing polls waits for ever with no error anywhere. It
/// presents as chat hanging, so the queue names move in the same patch or not at all.
const CHAT_TASK_QUEUE: &str = "chat-queue";

/// The queue of the `model_step` activities of a chat turn and its sub-agents. The website
/// does not address this name. It is declared here so the queue names cannot drift from
/// the Python worker that polls them. One slot is one model call in flight.
#[allow(dead_code)]
const CHAT_MODEL_TASK_QUEUE: &str = "chat-model-queue";

/// The queue of every `tool_call` activity. One slot is one tool call in flight.
///
/// **Mirrored in `main_services/processing/tasks/P_agent/workflows.py`**, as the names
/// above. The worker polls the name it declares there, and the page reads the pollers of
/// the name it declares here. A name that drifts makes the page never show the wait for
/// a tool slot.
const AGENT_TOOL_TASK_QUEUE: &str = "agent-tool-queue";


fn temporal_base_url() -> String {
    std::env::var("TEMPORAL_HTTP_URL").unwrap_or_else(|_| "http://localhost:21908".to_string())
}

/// One durable agent workflow, as dispatched.
struct AgentWorkflowStart<'a> {
    workflow_type: &'a str,
    task_queue: &'a str,
    workflow_id: &'a str,
    /// The workflow's one argument. For `AgentRun` it holds ids and settings only.
    input: serde_json::Value,
}

/// A new agent run id: a random UUID of version 4, in its text form.
fn new_run_id() -> String {
    let mut bytes = [0u8; 16];
    rand::rng().fill_bytes(&mut bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    let hex: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
    format!(
        "{}-{}-{}-{}-{}",
        &hex[0..8],
        &hex[8..12],
        &hex[12..16],
        &hex[16..20],
        &hex[20..32]
    )
}

/// Start one agent workflow over Temporal's HTTP API, and return its run id.
///
/// The workflow id is session- and seq-keyed, and the start rejects a duplicate id. A
/// double submit therefore starts one workflow, not two agents that race to write the same
/// transcript row. Temporal answers a refused duplicate with HTTP 409. That counts as
/// success, because the workflow it names exists, and the function returns
/// `already-started` in place of a run id.
///
/// The start waits behind the readiness gate, so a start during a Temporal restart waits
/// for the server rather than failing the turn.
async fn start_agent_workflow(start: AgentWorkflowStart<'_>) -> anyhow::Result<String> {
    let url = format!(
        "{}/api/v1/namespaces/default/workflows/{}",
        temporal_base_url(),
        start.workflow_id
    );

    let body = serde_json::json!({
        "workflowType": { "name": start.workflow_type },
        "taskQueue": { "name": start.task_queue },
        "workflowIdReusePolicy": "WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE",
        "input": [start.input],
    });

    crate::temporal_ready::wait_for_temporal().await?;
    let response = crate::temporal_ready::start_client()
        .post(&url)
        .json(&body)
        .send()
        .await?;
    if response.status() == reqwest::StatusCode::CONFLICT {
        let text = response.text().await.unwrap_or_default();
        tracing::info!(
            "{} {} already started, counted as started: {text}",
            start.workflow_type,
            start.workflow_id
        );
        return Ok("already-started".to_string());
    }
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
    /// The seq of the user row of the turn.
    turn_seq: u32,
    started_ms: i64,
    started_at: String,
}

/// Every running `AgentRun`.
///
/// An `AgentRun` takes its session and turn from its row in `agent_runs`, because a
/// sub-agent or a continuation has the workflow id `run-{run_id}`, which names neither.
/// A lead whose row `open_run` has not written yet falls back to its workflow id, which
/// is `chat-{session_id}-{start_seq}`.
async fn list_running_agent_workflows() -> anyhow::Result<Vec<RunningWorkflow>> {
    let query = "WorkflowType = 'AgentRun' AND ExecutionStatus = 'Running'";
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

    let mut open = Vec::new();
    for execution in executions {
        let Some(workflow_id) = execution
            .pointer("/execution/workflowId")
            .and_then(|v| v.as_str())
        else {
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
        open.push((workflow_id.to_string(), started_at, started_ms));
    }

    let ids: Vec<String> = open.iter().map(|(id, _, _)| id.clone()).collect();
    let rows = db_chat::runs_by_workflow_ids(&ids).await?;
    let by_workflow: std::collections::HashMap<&str, &db_chat::AgentRunRow> =
        rows.iter().map(|r| (r.workflow_id.as_str(), r)).collect();

    let mut out = Vec::new();
    for (workflow_id, started_at, started_ms) in open {
        let (session_id, turn_seq) = match by_workflow.get(workflow_id.as_str()) {
            Some(row) => (row.sid.clone(), row.turn_seq),
            None => match split_agent_workflow_id(&workflow_id) {
                Some((session_id, start_seq)) => (session_id, start_seq.saturating_sub(1)),
                None => continue,
            },
        };
        out.push(RunningWorkflow {
            workflow_id,
            session_id,
            turn_seq,
            started_ms,
            started_at,
        });
    }
    Ok(out)
}

/// Split an agent workflow id back into the session and the seq it reserved.
///
/// The id is built by [`chat_workflow_id`] and is the only
/// thing Temporal's visibility index carries about the turn, so it is parsed rather than
/// looked up. A session id contains no `-`, so the last one separates the seq.
fn split_agent_workflow_id(workflow_id: &str) -> Option<(String, u32)> {
    let rest = workflow_id.strip_prefix("chat-")?;
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

    #[test]
    fn a_workflow_id_round_trips_through_its_split() {
        // The id is the only thing Temporal's visibility index carries about a turn, so
        // the admin panel depends on this being exactly the inverse of the builders.
        let session = "4f3a9c2b1d";
        let id = chat_workflow_id(session, 7);
        assert_eq!(split_agent_workflow_id(&id), Some((session.to_string(), 7)));
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

    fn run(rid: &str, depth: u8, state: &str) -> db_chat::AgentRunRow {
        db_chat::AgentRunRow {
            rid: rid.into(),
            owner: "u".into(),
            sid: "s".into(),
            turn_seq: 1,
            thread: rid.into(),
            parent_rid: String::new(),
            batch: String::new(),
            continues: String::new(),
            delegated_batch: String::new(),
            depth,
            kind: if depth == 0 { "chat".into() } else { "subagent".into() },
            state: state.into(),
            workflow_id: format!("run-{rid}"),
            queue: "chat-model-queue".into(),
            briefing: String::new(),
            tool_call_id: String::new(),
            result_head: String::new(),
            error_head: String::new(),
            started_ms: 0,
            updated_ms: 0,
        }
    }

    fn child(rid: &str, parent: &str, batch: &str, call: &str, depth: u8, state: &str, at: i64) -> db_chat::AgentRunRow {
        let mut r = run(rid, depth, state);
        r.parent_rid = parent.into();
        r.batch = batch.into();
        r.tool_call_id = call.into();
        r.briefing = format!("{{\"objective\":\"task {rid}\"}}");
        r.started_ms = at;
        r
    }

    fn continuation(rid: &str, of: &db_chat::AgentRunRow, state: &str, at: i64) -> db_chat::AgentRunRow {
        let mut r = of.clone();
        r.rid = rid.into();
        r.continues = of.rid.clone();
        r.state = state.into();
        r.delegated_batch = String::new();
        r.briefing = String::new();
        r.started_ms = at;
        r
    }

    #[test]
    fn a_nag_round_keeps_the_turn_open() {
        // A nag round: the assistant row at seq 3 follows the user row at seq 1, and the
        // lead run is still running. The transcript test alone reads the turn as closed.
        let lead = run("lead", 0, "running");
        assert!(turn_is_open(Some(1), Some(3), &[lead]));
        let done = run("lead", 0, "completed");
        assert!(!turn_is_open(Some(1), Some(3), &[done]));
        assert!(turn_is_open(Some(1), None, &[]));
        assert!(!turn_is_open(None, None, &[]));
    }

    #[test]
    fn a_delegation_keeps_the_turn_open() {
        let mut lead = run("lead", 0, "waiting_for_children");
        lead.delegated_batch = "b0".into();
        let kid = child("k1", "lead", "b0", "c1", 1, "running", 1);
        assert!(turn_is_open(Some(1), Some(1), &[lead, kid]));
    }

    #[test]
    fn a_delegated_turn_stays_open_until_its_last_run_ends() {
        // The run rows of one delegated turn, in the order the worker writes them. The
        // transcript already holds an answer row after the user row at every step.
        let mut lead = run("lead", 0, "waiting_for_children");
        lead.delegated_batch = "b0".into();
        let k1 = child("k1", "lead", "b0", "c1", 1, "running", 1);
        let k2 = child("k2", "lead", "b0", "c2", 1, "running", 2);
        let ended = |r: &db_chat::AgentRunRow| {
            let mut r = r.clone();
            r.state = "completed".into();
            r
        };
        // One child ended, and then both, before the continuation row exists.
        assert!(turn_is_open(Some(1), Some(3), &[lead.clone(), ended(&k1), k2.clone()]));
        assert!(turn_is_open(Some(1), Some(3), &[lead.clone(), ended(&k1), ended(&k2)]));
        // The continuation runs. `write_ending` ends the original lead first.
        let cont = continuation("cont", &lead, "running", 3);
        assert!(turn_is_open(Some(1), Some(3), &[lead.clone(), ended(&k1), ended(&k2), cont.clone()]));
        assert!(turn_is_open(Some(1), Some(3), &[ended(&lead), ended(&k1), ended(&k2), cont.clone()]));
        // Only the terminal row of the last run closes the turn.
        assert!(!turn_is_open(Some(1), Some(3), &[ended(&lead), ended(&k1), ended(&k2), ended(&cont)]));
    }

    #[test]
    fn the_poll_lists_only_the_newest_batch_of_each_thread() {
        // The lead delegated batch b0 (two children), was continued by lead2, which
        // delegated batch b1 (one child). The chain rule keeps lead waiting, but only b1
        // is listed. Child k3 delegated batch b2 and was continued by k3c, which runs.
        let mut lead = run("lead", 0, "waiting_for_children");
        lead.delegated_batch = "b0".into();
        let k1 = child("k1", "lead", "b0", "c1", 1, "completed", 1);
        let k2 = child("k2", "lead", "b0", "c1", 1, "completed", 2);
        let mut lead2 = continuation("lead2", &lead, "waiting_for_children", 3);
        lead2.delegated_batch = "b1".into();
        let mut k3 = child("k3", "lead2", "b1", "c2", 1, "waiting_for_children", 4);
        k3.delegated_batch = "b2".into();
        let g1 = child("g1", "k3", "b2", "d1", 2, "completed", 5);
        let mut k3c = continuation("k3c", &k3, "running", 6);
        k3c.delegated_batch = String::new();
        let entries = subagent_entries(&[lead.clone(), k1, k2, lead2, k3, g1, k3c]);
        let ids: Vec<&str> = entries.iter().map(|e| e.run_id.as_str()).collect();
        // k3's newest run k3c no longer waits, so batch b2 ended and g1 leaves the poll.
        assert_eq!(ids, vec!["k3"]);
        assert_eq!(entries[0].state, "running");
        assert_eq!(entries[0].batch_id, "b1");
        assert_eq!(entries[0].tool_call_id, "c2");
        assert_eq!(entries[0].parent_run_id, "lead");
        assert_eq!(entries[0].objective, "task k3");
    }

    #[test]
    fn a_depth_2_batch_nests_under_its_thread_and_carries_reports() {
        let mut lead = run("lead", 0, "waiting_for_children");
        lead.delegated_batch = "b0".into();
        let mut k1 = child("k1", "lead", "b0", "c1", 1, "waiting_for_children", 1);
        k1.delegated_batch = "b1".into();
        let mut g1 = child("g1", "k1", "b1", "d1", 2, "completed", 2);
        g1.result_head = "found it".into();
        let mut g2 = child("g2", "k1", "b1", "d1", 2, "failed", 3);
        g2.error_head = "timed out".into();
        let entries = subagent_entries(&[lead, k1, g1, g2]);
        let shape: Vec<(&str, &str, u8, &str)> = entries
            .iter()
            .map(|e| (e.run_id.as_str(), e.parent_run_id.as_str(), e.depth, e.report.as_str()))
            .collect();
        assert_eq!(
            shape,
            vec![("k1", "lead", 1, ""), ("g1", "k1", 2, "found it"), ("g2", "k1", 2, "timed out")]
        );
    }

    #[test]
    fn an_ended_batch_leaves_the_poll() {
        let mut lead = run("lead", 0, "waiting_for_children");
        lead.delegated_batch = "b0".into();
        let k1 = child("k1", "lead", "b0", "c1", 1, "completed", 1);
        let lead2 = continuation("lead2", &lead, "running", 2);
        assert!(subagent_entries(&[lead, k1, lead2]).is_empty());
    }
}
