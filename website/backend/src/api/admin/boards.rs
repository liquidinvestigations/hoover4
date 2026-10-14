//! Investigation boards: the admin server functions.
//!
//! The website writes three kinds of rows: the board definition at creation and its
//! tombstone at a drop, the origin, goal and correction facts, and person events (hints,
//! rejections, pause and resume, review decisions, drop). Every other row belongs to the
//! worker: the `board_plan` activity folds the events into `board_state` and
//! `board_intents`, and the explore activities write the facts of intents. So no row has two
//! writers.
//!
//! The worker's dispatcher reads the events every few seconds, so a person action needs no
//! signal. A drop is the exception: it cancels the running explores at once and deletes the
//! explore sessions through the chat deletion path, because the dispatcher no longer sees a
//! tombstoned board.
//!
//! Only the owner of a board can read it or act on it. Anyone else gets not-found, which is
//! the convention of `auth::guard::NOT_FOUND`.

use std::collections::HashMap;

use common::board_types::{
    BoardCitation, BoardCreateRequest, BoardDefinition, BoardEvent, BoardFact, BoardIntent,
    BoardListItem, BoardSnapshot, BOARD_SESSION_PREFIX,
};
use common::current_user::CurrentUser;
use time::OffsetDateTime;

use crate::auth::guard;
use crate::db_auth::insert_row;
use crate::db_utils::clickhouse_utils::get_global_client;

/// The queue of the board workflows.
///
/// **Mirrored in `main_services/processing/tasks/P_board/model.py`** (`BOARD_TASK_QUEUE`).
/// The website starts no board workflow today, and the name is declared here so that the
/// two sides cannot drift when it does.
#[allow(dead_code)]
pub const BOARD_TASK_QUEUE: &str = "board-queue";

const MAX_TEXT: usize = 4000;

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
struct BoardRow {
    board_id: String,
    owner: String,
    title: String,
    goal: String,
    context: String,
    collections: Vec<String>,
    llm_model: String,
    max_explores: u16,
    max_parallel: u8,
    explore_step_budget: u16,
    #[serde(with = "clickhouse::serde::time::datetime64::millis")]
    created_at: OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime64::millis")]
    updated_at: OffsetDateTime,
    is_deleted: u8,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
struct EventRow {
    board_id: String,
    event_id: String,
    event_type: String,
    actor: String,
    subject: String,
    payload_json: String,
    #[serde(with = "clickhouse::serde::time::datetime64::millis")]
    created_at: OffsetDateTime,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
struct FactRow {
    board_id: String,
    fact_id: String,
    kind: String,
    text: String,
    intent_id: String,
    session_id: String,
    answer_seq: u32,
    open_questions: Vec<String>,
    problems: Vec<String>,
    created_by: String,
    #[serde(with = "clickhouse::serde::time::datetime64::millis")]
    created_at: OffsetDateTime,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct CitationRow {
    fact_id: String,
    label: String,
    collection_dataset: String,
    collectionname: String,
    file_hash: String,
    path: String,
    page_id: u32,
    quote: String,
    quote_verified: u8,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct StateRow {
    board_id: String,
    status: String,
    explores_used: u32,
    reasons_done: u32,
    stall_count: u8,
    summary_json: String,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct IntentRow {
    intent_id: String,
    from_facts: Vec<String>,
    objective: String,
    brief: String,
    state: String,
    attempts: u8,
    session_id: String,
    fact_id: String,
    question: String,
    last_error: String,
    #[serde(with = "clickhouse::serde::time::datetime64::millis")]
    created_at: OffsetDateTime,
}

fn now() -> OffsetDateTime {
    OffsetDateTime::now_utc()
}

fn millis(t: OffsetDateTime) -> i64 {
    (t.unix_timestamp_nanos() / 1_000_000) as i64
}

fn new_id() -> String {
    crate::db_auth::sessions::generate_session_id()[..32].to_string()
}

fn clip(text: &str) -> String {
    text.trim().chars().take(MAX_TEXT).collect()
}

/// The board, when it exists, is not dropped, and belongs to `user`. Not-found otherwise.
async fn owned_board(user: &CurrentUser, board_id: &str) -> anyhow::Result<BoardRow> {
    guard::require_admin(user)?;
    let rows = get_global_client()
        .query("SELECT ?fields FROM boards FINAL WHERE board_id = ? AND is_deleted = 0")
        .bind(board_id)
        .fetch_all::<BoardRow>()
        .await?;
    match rows.into_iter().next() {
        Some(row) if row.owner == user.username => Ok(row),
        _ => anyhow::bail!("board {}", guard::NOT_FOUND),
    }
}

async fn write_event(board_id: &str, event_type: &str, actor: &str, subject: &str,
                     payload: serde_json::Value) -> anyhow::Result<()> {
    let row = EventRow {
        board_id: board_id.to_string(),
        event_id: format!("{event_type}:{}", new_id()),
        event_type: event_type.to_string(),
        actor: actor.to_string(),
        subject: subject.to_string(),
        payload_json: payload.to_string(),
        created_at: now(),
    };
    insert_row("board_events", &row).await
}

async fn write_fact(board_id: &str, fact_id: &str, kind: &str, text: &str, by: &str) -> anyhow::Result<()> {
    let row = FactRow {
        board_id: board_id.to_string(),
        fact_id: fact_id.to_string(),
        kind: kind.to_string(),
        text: text.to_string(),
        intent_id: String::new(),
        session_id: String::new(),
        answer_seq: 0,
        open_questions: Vec::new(),
        problems: Vec::new(),
        created_by: by.to_string(),
        created_at: now(),
    };
    insert_row("board_facts", &row).await
}

/// Every board of the caller.
pub async fn admin_list_boards(user: &CurrentUser) -> anyhow::Result<Vec<BoardListItem>> {
    guard::require_admin(user)?;
    let client = get_global_client();
    let boards = client
        .query("SELECT ?fields FROM boards FINAL WHERE owner = ? AND is_deleted = 0 ORDER BY created_at DESC")
        .bind(&user.username)
        .fetch_all::<BoardRow>()
        .await?;
    let ids: Vec<String> = boards.iter().map(|b| b.board_id.clone()).collect();
    let states: HashMap<String, StateRow> = client
        .query("SELECT ?fields FROM board_state FINAL WHERE board_id IN ?")
        .bind(&ids)
        .fetch_all::<StateRow>()
        .await?
        .into_iter()
        .map(|s| (s.board_id.clone(), s))
        .collect();
    let fact_counts: Vec<(String, String, u64)> = client
        .query("SELECT board_id, kind, count() FROM board_facts FINAL WHERE board_id IN ? GROUP BY board_id, kind")
        .bind(&ids)
        .fetch_all()
        .await?;
    let newest: HashMap<String, i64> = client
        .query("SELECT board_id, toUnixTimestamp64Milli(max(created_at)) FROM board_events FINAL WHERE board_id IN ? GROUP BY board_id")
        .bind(&ids)
        .fetch_all::<(String, i64)>()
        .await?
        .into_iter()
        .collect();
    Ok(boards
        .into_iter()
        .map(|b| {
            let state = states.get(&b.board_id);
            let summary: serde_json::Value = state
                .and_then(|s| serde_json::from_str(&s.summary_json).ok())
                .unwrap_or_default();
            let intents = &summary["intents"];
            let count = |kind: &str| {
                fact_counts
                    .iter()
                    .filter(|(id, k, _)| *id == b.board_id && k == kind)
                    .map(|(_, _, n)| *n as u32)
                    .sum()
            };
            BoardListItem {
                status: state.map(|s| s.status.clone()).unwrap_or_else(|| "active".to_string()),
                facts_sourced: count("sourced"),
                facts_inferred: count("inferred"),
                facts_not_found: count("not_found"),
                running: intents["running"].as_u64().unwrap_or(0) as u32,
                open: intents["open"].as_u64().unwrap_or(0) as u32,
                explores_used: state.map(|s| s.explores_used).unwrap_or(0),
                max_explores: u32::from(b.max_explores),
                updated_ms: newest.get(&b.board_id).copied().unwrap_or_else(|| millis(b.created_at)),
                board_id: b.board_id,
                title: b.title,
            }
        })
        .collect())
}

/// Create a board: its definition, its origin and goal facts, and its first events.
pub async fn admin_create_board(user: &CurrentUser, request: BoardCreateRequest) -> anyhow::Result<String> {
    guard::require_admin(user)?;
    let title = clip(&request.title);
    let goal = clip(&request.goal);
    if title.is_empty() || goal.is_empty() {
        anyhow::bail!("a board needs a title and a goal");
    }
    let existing = crate::db_utils::clickhouse_utils::list_collections().await?;
    let collections: Vec<String> = request
        .collections
        .iter()
        .filter(|c| existing.contains(c))
        .cloned()
        .collect();
    if collections.is_empty() {
        anyhow::bail!("choose at least one collection that exists");
    }
    let board_id = new_id();
    let created = now();
    let row = BoardRow {
        board_id: board_id.clone(),
        owner: user.username.clone(),
        title,
        goal: goal.clone(),
        context: clip(&request.context),
        collections: collections.clone(),
        llm_model: request.llm_model.trim().to_string(),
        max_explores: request.max_explores.clamp(1, 100),
        max_parallel: request.max_parallel.clamp(1, 4),
        explore_step_budget: request.explore_step_budget.clamp(8, 200),
        created_at: created,
        updated_at: created,
        is_deleted: 0,
    };
    insert_row("boards", &row).await?;
    let origin = format!(
        "The investigation searches the collections {}. {}",
        collections.join(", "),
        row.context
    );
    write_fact(&board_id, "origin", "origin", origin.trim(), &user.username).await?;
    write_fact(&board_id, "goal", "goal", &goal, &user.username).await?;
    write_event(&board_id, "board_created", &user.username, "", serde_json::json!({})).await?;
    for hint in request.hints.iter().map(|h| clip(h)).filter(|h| !h.is_empty()) {
        write_event(&board_id, "hint_added", &user.username, "", serde_json::json!({"text": hint})).await?;
    }
    Ok(board_id)
}

/// A sentence for one event, from its type and payload.
fn summarise(event_type: &str, subject: &str, payload: &serde_json::Value) -> String {
    let text = |key: &str| payload[key].as_str().unwrap_or("").to_string();
    match event_type {
        "board_created" => "The board was created.".to_string(),
        "hint_added" => format!("Hint: {}", text("text")),
        "fact_rejected" => format!("Fact {subject} was rejected: {}", text("reason")),
        "pause_requested" => "A pause was requested.".to_string(),
        "resume_requested" => "A resume was requested.".to_string(),
        "review_accepted" => "The review was accepted. The board is complete.".to_string(),
        "review_rejected" => format!("The review was rejected: {}", text("correction")),
        "drop_requested" => "The board was dropped.".to_string(),
        "reason_started" => format!("Reason {subject} started."),
        "reason_result" => {
            let outcome = text("outcome");
            let problems = payload["problems"].as_array().map(|p| p.len()).unwrap_or(0);
            let detail = match outcome.as_str() {
                "intents" => format!(
                    "{} new intents",
                    payload["intents"].as_array().map(|i| i.len()).unwrap_or(0)
                ),
                "review" => "it proposes review".to_string(),
                "noop" => "no new intent".to_string(),
                _ => format!("an invalid reply {}", text("error")),
            };
            let checks = if problems > 0 { format!(", {problems} checks changed it") } else { String::new() };
            format!("Reason {subject}: {detail}{checks}.")
        }
        "explore_started" => format!("Explore of {subject} started, attempt {}.", payload["attempt"]),
        "explore_concluded" => format!("{subject} concluded in {} ({}).", text("fact_id"), text("kind")),
        "explore_failed" => format!("{subject} failed: {}", text("error")),
        "explore_cancelled" => format!("{subject} was cancelled: {}", text("error")),
        "explore_question" => format!("{subject} asked a question: {}", text("question")),
        "review_proposed" => format!("The board went to review: {}", text("statement")),
        other => other.replace('_', " "),
    }
}

/// The whole board.
pub async fn admin_board_snapshot(user: &CurrentUser, board_id: String) -> anyhow::Result<BoardSnapshot> {
    let board = owned_board(user, &board_id).await?;
    let client = get_global_client();
    let state = client
        .query("SELECT ?fields FROM board_state FINAL WHERE board_id = ?")
        .bind(&board_id)
        .fetch_all::<StateRow>()
        .await?
        .into_iter()
        .next();
    let events = client
        .query("SELECT ?fields FROM board_events FINAL WHERE board_id = ? ORDER BY created_at, event_id")
        .bind(&board_id)
        .fetch_all::<EventRow>()
        .await?;
    let facts = client
        .query("SELECT ?fields FROM board_facts FINAL WHERE board_id = ? ORDER BY created_at, fact_id")
        .bind(&board_id)
        .fetch_all::<FactRow>()
        .await?;
    let citations = client
        .query("SELECT ?fields FROM board_fact_citations FINAL WHERE board_id = ? ORDER BY fact_id, label")
        .bind(&board_id)
        .fetch_all::<CitationRow>()
        .await?;
    let intents = client
        .query("SELECT ?fields FROM board_intents FINAL WHERE board_id = ? ORDER BY created_at, intent_id")
        .bind(&board_id)
        .fetch_all::<IntentRow>()
        .await?;
    let rejected: Vec<String> = events
        .iter()
        .filter(|e| e.event_type == "fact_rejected")
        .map(|e| e.subject.clone())
        .collect();
    let summary: serde_json::Value = state
        .as_ref()
        .and_then(|s| serde_json::from_str(&s.summary_json).ok())
        .unwrap_or_default();
    Ok(BoardSnapshot {
        status: state.as_ref().map(|s| s.status.clone()).unwrap_or_else(|| "active".to_string()),
        explores_used: state.as_ref().map(|s| s.explores_used).unwrap_or(0),
        reasons_done: state.as_ref().map(|s| s.reasons_done).unwrap_or(0),
        stall_count: state.as_ref().map(|s| u32::from(s.stall_count)).unwrap_or(0),
        review_statement: summary["review_statement"].as_str().unwrap_or("").to_string(),
        review_from: summary["review_from"]
            .as_array()
            .map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect())
            .unwrap_or_default(),
        facts: facts
            .into_iter()
            .map(|f| BoardFact {
                rejected: rejected.contains(&f.fact_id),
                citations: citations
                    .iter()
                    .filter(|c| c.fact_id == f.fact_id)
                    .map(|c| BoardCitation {
                        label: c.label.clone(),
                        collection_dataset: c.collection_dataset.clone(),
                        collectionname: c.collectionname.clone(),
                        file_hash: c.file_hash.clone(),
                        path: c.path.clone(),
                        page_id: c.page_id,
                        quote: c.quote.clone(),
                        quote_verified: c.quote_verified != 0,
                    })
                    .collect(),
                created_ms: millis(f.created_at),
                fact_id: f.fact_id,
                kind: f.kind,
                text: f.text,
                intent_id: f.intent_id,
                session_id: f.session_id,
                open_questions: f.open_questions,
                problems: f.problems,
            })
            .collect(),
        intents: intents
            .into_iter()
            .map(|i| BoardIntent {
                created_ms: millis(i.created_at),
                intent_id: i.intent_id,
                from_facts: i.from_facts,
                objective: i.objective,
                brief: i.brief,
                state: i.state,
                attempts: u32::from(i.attempts),
                session_id: i.session_id,
                fact_id: i.fact_id,
                question: i.question,
                last_error: i.last_error,
            })
            .collect(),
        events: events
            .into_iter()
            .map(|e| {
                let payload: serde_json::Value = serde_json::from_str(&e.payload_json).unwrap_or_default();
                BoardEvent {
                    summary: summarise(&e.event_type, &e.subject, &payload),
                    created_ms: millis(e.created_at),
                    event_id: e.event_id,
                    event_type: e.event_type,
                    actor: e.actor,
                    subject: e.subject,
                }
            })
            .collect(),
        board: BoardDefinition {
            created_ms: millis(board.created_at),
            board_id: board.board_id,
            owner: board.owner,
            title: board.title,
            goal: board.goal,
            context: board.context,
            collections: board.collections,
            llm_model: board.llm_model,
            max_explores: board.max_explores,
            max_parallel: board.max_parallel,
            explore_step_budget: board.explore_step_budget,
        },
    })
}

pub async fn admin_board_add_hint(user: &CurrentUser, board_id: String, text: String) -> anyhow::Result<()> {
    owned_board(user, &board_id).await?;
    let text = clip(&text);
    if text.is_empty() {
        anyhow::bail!("the hint is empty");
    }
    write_event(&board_id, "hint_added", &user.username, "", serde_json::json!({"text": text})).await
}

pub async fn admin_board_reject_fact(user: &CurrentUser, board_id: String, fact_id: String,
                                     reason: String) -> anyhow::Result<()> {
    owned_board(user, &board_id).await?;
    if fact_id == "origin" || fact_id == "goal" {
        anyhow::bail!("the origin and the goal cannot be rejected");
    }
    write_event(&board_id, "fact_rejected", &user.username, &fact_id,
                serde_json::json!({"reason": clip(&reason)})).await
}

pub async fn admin_board_set_paused(user: &CurrentUser, board_id: String, paused: bool) -> anyhow::Result<()> {
    owned_board(user, &board_id).await?;
    let kind = if paused { "pause_requested" } else { "resume_requested" };
    write_event(&board_id, kind, &user.username, "", serde_json::json!({})).await
}

/// Accept the proposed review, or reject it with a correction that becomes a fact.
pub async fn admin_board_review(user: &CurrentUser, board_id: String, accept: bool,
                                correction: String) -> anyhow::Result<()> {
    owned_board(user, &board_id).await?;
    if accept {
        return write_event(&board_id, "review_accepted", &user.username, "", serde_json::json!({})).await;
    }
    let correction = clip(&correction);
    if correction.is_empty() {
        anyhow::bail!("a rejected review needs a correction");
    }
    let fact_id = format!("c{}", &new_id()[..8]);
    write_fact(&board_id, &fact_id, "correction", &correction, &user.username).await?;
    write_event(&board_id, "review_rejected", &user.username, &fact_id,
                serde_json::json!({"correction": correction})).await
}

/// Drop a board: cancel its running explores, delete its explore sessions through the chat
/// deletion path, delete its rows, and keep the tombstone of the definition.
pub async fn admin_board_drop(user: &CurrentUser, board_id: String) -> anyhow::Result<()> {
    let mut board = owned_board(user, &board_id).await?;
    write_event(&board_id, "drop_requested", &user.username, "", serde_json::json!({})).await?;
    board.is_deleted = 1;
    board.updated_at = now();
    insert_row("boards", &board).await?;
    let client = get_global_client();
    let running: Vec<String> = client
        .query("SELECT intent_id FROM board_intents FINAL WHERE board_id = ? AND state = 'running'")
        .bind(&board_id)
        .fetch_all()
        .await?;
    for intent_id in running {
        let workflow_id = format!("board-explore-{board_id}-{intent_id}");
        if let Err(e) = crate::api::chat::cancel_workflow(&workflow_id).await {
            tracing::warn!("could not cancel {workflow_id}: {e:#}");
        }
    }
    let sessions: Vec<String> = client
        .query("SELECT session_id FROM chat_sessions FINAL WHERE username = ? AND startsWith(session_id, ?) AND is_deleted = 0")
        .bind(&user.username)
        .bind(format!("{BOARD_SESSION_PREFIX}{board_id}-"))
        .fetch_all()
        .await?;
    for session_id in sessions {
        crate::db_chat::delete_session(&user.username, &session_id).await?;
    }
    for table in ["board_events", "board_state", "board_intents", "board_facts", "board_fact_citations"] {
        client
            .query(&format!("DELETE FROM {table} WHERE board_id = ?"))
            .bind(&board_id)
            .execute()
            .await?;
    }
    Ok(())
}
