//! Investigation boards: the server functions of the board pages under AI Chat.
//!
//! The website writes the board definition at creation and at a change of its internet
//! tools, its tombstone at a drop, and one command input for each person action
//! (`board_command_inputs`). The command writer of the board, `BoardCommands`
//! (`main_services/processing/tasks/P_board/commands.py`), checks each command against the
//! committed state, gives new nodes their ids, and writes the facts and events. The
//! `board_plan` activity folds the events into `board_state` and `board_intents`. So no row
//! has two writers.
//!
//! A person action returns its request id and the state of its command: `pending` until the
//! writer handles it, then `committed` or `rejected` with the reason. The page sends the same
//! request id again after a lost response, and reads `board_command_status` until the command
//! is decided. The request id of a person action starts with `web:`, so it never equals the
//! request id of a worker command.
//!
//! The dispatcher starts the command writer on its next pass, so a person action needs no
//! signal. A drop is the exception: it cancels the command writer and the running explores
//! at once and deletes the explore sessions through the chat deletion path, because the
//! dispatcher no longer sees a tombstoned board.
//!
//! A fact row that a command wrote carries the request id of the command. The reads here show
//! it only when an event carries the same request id, because the writer writes the facts
//! before their event.
//!
//! Every user can own boards. Only the owner of a board can read it or act on it. This
//! applies to administrators too. Anyone else gets not-found, which is the convention of
//! `auth::guard::NOT_FOUND`. A board starts only while AI chat is open
//! (`chat::gate::evaluate_live_chat_gate`), because its explores are chat turns.
//!
//! The explore model and the budgets are not inputs. The website writes the base values in
//! the board row, and the worker computes the budget from the events
//! (`tasks/P_board/fold.py`, `Folded.max_explores`). A board can have up to `MAX_GOALS`
//! goals: each is a fact of kind `goal`, in the order of `common::board_types::goal_slot`.
//!
//! The worker writes a generated slug, title and summary for each intent, fact and correction
//! in `board_labels` (`tasks/P_board/labels.py`), and one summary row for each board. The
//! reads here attach them to the nodes. A node created with a slug id has its id as its slug
//! from creation. A node without a slug yet shows its storage id, and a node without a title
//! yet shows the first words of its text (`common::board_types::fallback_label`). The storage
//! ids stay the keys of every write.

use std::collections::HashMap;

use std::collections::HashSet;

use common::board_types::{
    fallback_label, fixed_slug, BoardAction, BoardAssessment, BoardCitation, BoardCommandReceipt,
    BoardCreateRequest, BoardDefinition, BoardEvent, BoardFact, BoardGraphInput, BoardIntent,
    BoardListItem, BoardQuestionRef, BoardReviewGoal, BoardSnapshot, BOARD_SESSION_PREFIX,
    EXPLORE_LIMIT, MAX_GOALS,
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

/// The base budget that the website writes in a new board row. The worker reads the budget
/// from the events, so these values describe the start only.
/// **Mirrored in `main_services/processing/tasks/P_board/model.py`** (`BASE_EXPLORES`,
/// `BASE_EXPLORE_STEPS`, `EXTENSION_EXPLORES`).
const BASE_EXPLORES: u16 = 30;
const BASE_EXPLORE_STEPS: u16 = 60;
const EXTENSION_EXPLORES: u32 = 50;
/// The prefix of the request id of a person action.
const PERSON_REQUEST_PREFIX: &str = "web:";
/// The longest request id that a page may send, without the prefix.
const MAX_REQUEST_ID: usize = 64;
/// Explores of one board that may run at once.
const MAX_PARALLEL: u8 = 2;
/// The characters of a fact text in an overview thumbnail.
const THUMB_TEXT: usize = 80;

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
    internet_tools: u8,
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
    /// The command that wrote the fact, empty for a fact without a command.
    request_id: String,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
struct CommandInputRow {
    board_id: String,
    request_id: String,
    payload_digest: String,
    actor: String,
    kind: String,
    body_json: String,
    #[serde(with = "clickhouse::serde::time::datetime64::millis")]
    submitted_at: OffsetDateTime,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct ReceiptRow {
    state: String,
    error: String,
    result_json: String,
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
    board_id: String,
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

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct LabelRow {
    board_id: String,
    node_id: String,
    slug: String,
    title: String,
    summary: String,
}

/// The labels of the given boards, keyed by board id and node id. The board summary has an
/// empty node id.
async fn read_labels(ids: &[String]) -> anyhow::Result<HashMap<(String, String), LabelRow>> {
    Ok(get_global_client()
        .query("SELECT board_id, node_id, slug, title, summary FROM board_labels FINAL WHERE board_id IN ?")
        .bind(ids)
        .fetch_all::<LabelRow>()
        .await?
        .into_iter()
        .map(|row| ((row.board_id.clone(), row.node_id.clone()), row))
        .collect())
}

/// Set the slug, title and summary of a fact: fixed for the origin and the goals, generated
/// when a label exists, else the fallback.
fn label_fact(fact: &mut BoardFact, label: Option<&LabelRow>) {
    if let Some(slug) = fixed_slug(&fact.fact_id, &fact.kind) {
        fact.slug = slug;
        fact.title = String::new();
        fact.summary = fact.text.clone();
        return;
    }
    (fact.slug, fact.title, fact.summary) = node_label(&fact.fact_id, &fact.text, label);
}

fn label_intent(intent: &mut BoardIntent, label: Option<&LabelRow>) {
    (intent.slug, intent.title, intent.summary) = node_label(&intent.intent_id, &intent.objective, label);
}

/// The slug, title and summary of a node. A label row without a title yet, such as the row
/// that a new node gets at its creation, keeps its slug and takes the fallback title and
/// summary.
fn node_label(id: &str, text: &str, label: Option<&LabelRow>) -> (String, String, String) {
    let (fallback_slug, fallback_title, fallback_summary) = fallback_label(id, text);
    match label.filter(|l| !l.slug.is_empty()) {
        Some(l) if l.title.is_empty() => (l.slug.clone(), fallback_title, fallback_summary),
        Some(l) => (l.slug.clone(), l.title.clone(), l.summary.clone()),
        None => (fallback_slug, fallback_title, fallback_summary),
    }
}

fn now() -> OffsetDateTime {
    OffsetDateTime::now_utc()
}

fn millis(t: OffsetDateTime) -> i64 {
    (t.unix_timestamp_nanos() / 1_000_000) as i64
}

fn clip(text: &str) -> String {
    text.trim().chars().take(MAX_TEXT).collect()
}

/// The board, when it exists, is not dropped, and belongs to `user`. Not-found otherwise.
async fn owned_board(user: &CurrentUser, board_id: &str) -> anyhow::Result<BoardRow> {
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

/// The stored request id of a person action, or an error for an id that a page cannot send.
fn person_request(request_id: &str) -> anyhow::Result<String> {
    let id = request_id.trim();
    let valid = !id.is_empty()
        && id.len() <= MAX_REQUEST_ID
        && id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_');
    if !valid {
        anyhow::bail!("This page is out of date. Reload the page and try again.");
    }
    Ok(format!("{PERSON_REQUEST_PREFIX}{id}"))
}

/// Write the input of one person command and return its state. The same request with the
/// same body writes the same row again. The digest is the sha256 of the body as written.
async fn submit(user: &CurrentUser, board_id: &str, request_id: &str, kind: &str,
                body: serde_json::Value) -> anyhow::Result<BoardCommandReceipt> {
    let request_id = person_request(request_id)?;
    let body_json = body.to_string();
    let row = CommandInputRow {
        board_id: board_id.to_string(),
        request_id: request_id.clone(),
        payload_digest: sha256::digest(body_json.as_bytes()),
        actor: user.username.clone(),
        kind: kind.to_string(),
        body_json,
        submitted_at: now(),
    };
    insert_row("board_command_inputs", &row).await?;
    command_state(board_id, &request_id).await
}

/// The state of a command: its receipt, else `pending` when its input exists.
async fn command_state(board_id: &str, request_id: &str) -> anyhow::Result<BoardCommandReceipt> {
    let client = get_global_client();
    let receipt = client
        .query("SELECT state, error, result_json FROM board_command_receipts FINAL WHERE board_id = ? AND request_id = ?")
        .bind(board_id)
        .bind(request_id)
        .fetch_all::<ReceiptRow>()
        .await?
        .into_iter()
        .next();
    let shown = request_id.strip_prefix(PERSON_REQUEST_PREFIX).unwrap_or(request_id).to_string();
    if let Some(row) = receipt.filter(|r| r.state != "prepared") {
        return Ok(receipt_of(shown, row));
    }
    let submitted: u64 = client
        .query("SELECT count() FROM board_command_inputs FINAL WHERE board_id = ? AND request_id = ?")
        .bind(board_id)
        .bind(request_id)
        .fetch_one()
        .await?;
    if submitted == 0 {
        anyhow::bail!("The board has no such request. Reload the page.");
    }
    Ok(BoardCommandReceipt { request_id: shown, state: "pending".to_string(), ..Default::default() })
}

fn receipt_of(request_id: String, row: ReceiptRow) -> BoardCommandReceipt {
    let result: serde_json::Value = serde_json::from_str(&row.result_json).unwrap_or_default();
    BoardCommandReceipt {
        request_id,
        state: row.state,
        error: row.error,
        intent_id: result["intent_id"].as_str().unwrap_or("").to_string(),
        grant: result["grant"].as_u64().map(|g| g as u32),
    }
}

/// The request ids that the events of a board carry. A fact with a request id is visible
/// when this set holds it.
fn published(events: &[EventRow]) -> HashSet<String> {
    events
        .iter()
        .filter_map(|e| serde_json::from_str::<serde_json::Value>(&e.payload_json).ok())
        .filter_map(|p| p["request_id"].as_str().map(str::to_string))
        .collect()
}

fn is_visible(fact: &FactRow, published: &HashSet<String>) -> bool {
    fact.request_id.is_empty() || published.contains(&fact.request_id)
}

/// The events in the order of the fold: the events without a sequence number in their
/// stored order, then the sequenced events by number. Each `status_changed` row follows its
/// cause, in the order of its ordinal. A status row whose cause is not there comes last.
fn order_events(events: Vec<EventRow>) -> Vec<EventRow> {
    let payload = |e: &EventRow| serde_json::from_str::<serde_json::Value>(&e.payload_json).unwrap_or_default();
    let mut legacy = Vec::new();
    let mut sequenced = Vec::new();
    let mut derived: HashMap<String, Vec<(u64, EventRow)>> = HashMap::new();
    for event in events {
        let data = payload(&event);
        if event.event_type == "status_changed" {
            let cause = data["causal_event_id"].as_str().unwrap_or("").to_string();
            derived.entry(cause).or_default().push((data["ordinal"].as_u64().unwrap_or(0), event));
        } else if let Some(seq) = data["seq"].as_u64() {
            sequenced.push((seq, event));
        } else {
            legacy.push(event);
        }
    }
    sequenced.sort_by_key(|(seq, _)| *seq);
    let mut out = Vec::new();
    for event in legacy.into_iter().chain(sequenced.into_iter().map(|(_, e)| e)) {
        let mut rows = derived.remove(&event.event_id).unwrap_or_default();
        rows.sort_by_key(|(ordinal, _)| *ordinal);
        out.push(event);
        out.extend(rows.into_iter().map(|(_, e)| e));
    }
    let mut orphans: Vec<EventRow> = derived.into_values().flatten().map(|(_, e)| e).collect();
    orphans.sort_by(|a, b| (a.created_at, &a.event_id).cmp(&(b.created_at, &b.event_id)));
    out.extend(orphans);
    out
}

/// The rejection of each rejected fact (who, when, why), and the facts that each correction
/// corrects. A correction comes from a rejected review. It corrects the facts that the review
/// named: the `from` of its event, or for an event written before that field, the facts of the
/// newest review that reason proposed before it.
#[derive(Default)]
struct EventFacts {
    rejections: HashMap<String, (String, i64, String)>,
    corrects: HashMap<String, Vec<String>>,
    /// The open question that each intent `i0.N` follows.
    asked: HashMap<String, BoardQuestionRef>,
}

fn event_facts(events: &[EventRow]) -> EventFacts {
    let mut out = EventFacts::default();
    let mut last_review: Vec<String> = Vec::new();
    for event in events {
        let payload: serde_json::Value = serde_json::from_str(&event.payload_json).unwrap_or_default();
        match event.event_type.as_str() {
            "fact_rejected" => {
                let reason = payload["reason"].as_str().unwrap_or("").to_string();
                out.rejections.insert(event.subject.clone(), (event.actor.clone(), millis(event.created_at), reason));
            }
            "reason_result" if payload["outcome"] == "review" && payload.get("proposals").is_none() => {
                last_review = strings(&payload["review"]["from"]);
            }
            "review_rejected" => {
                let from = strings(&payload["from"]);
                out.corrects.insert(event.subject.clone(), if from.is_empty() { last_review.clone() } else { from });
            }
            "goal_answer_rejected" => {
                out.corrects.insert(event.subject.clone(), strings(&payload["from"]));
            }
            // An own question has no index, so it follows no open question.
            "question_explored" if !payload["own"].as_bool().unwrap_or(false) => {
                let intent = payload["intent_id"].as_str().unwrap_or(&event.subject).to_string();
                out.asked.entry(intent).or_insert_with(|| BoardQuestionRef {
                    fact_id: payload["fact_id"].as_str().unwrap_or("").to_string(),
                    index: payload["index"].as_u64().unwrap_or(0) as u32,
                });
            }
            _ => {}
        }
    }
    out
}

fn strings(value: &serde_json::Value) -> Vec<String> {
    value.as_array().map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect()).unwrap_or_default()
}

/// The goal answers of one list of the state summary: `answers_proposed` or
/// `answers_accepted` (`tasks/P_board/activities.py`).
fn answers(summary: &serde_json::Value, key: &str) -> Vec<BoardReviewGoal> {
    summary[key]
        .as_array()
        .map(|list| {
            list.iter()
                .map(|g| BoardReviewGoal {
                    goal: g["goal"].as_str().unwrap_or("").to_string(),
                    from: strings(&g["from"]),
                    statement: g["statement"].as_str().unwrap_or("").to_string(),
                    reason_no: g["reason_no"].as_u64().unwrap_or(0) as u32,
                    proposal_id: g["proposal_id"].as_str().unwrap_or("").to_string(),
                    answer_kind: g["answer_kind"].as_str().unwrap_or("").to_string(),
                    commentary: g["commentary"].as_str().unwrap_or("").to_string(),
                })
                .filter(|g| !g.goal.is_empty())
                .collect()
        })
        .unwrap_or_default()
}

fn board_fact(f: FactRow, marks: &EventFacts, citations: Vec<BoardCitation>) -> BoardFact {
    let rejection = marks.rejections.get(&f.fact_id).cloned();
    BoardFact {
        rejected: rejection.is_some(),
        rejected_by: rejection.as_ref().map(|r| r.0.clone()).unwrap_or_default(),
        rejected_ms: rejection.as_ref().map(|r| r.1).unwrap_or(0),
        rejected_reason: rejection.map(|r| r.2).unwrap_or_default(),
        corrects: marks.corrects.get(&f.fact_id).cloned().unwrap_or_default(),
        created_by: f.created_by,
        citations,
        created_ms: millis(f.created_at),
        fact_id: f.fact_id,
        kind: f.kind,
        text: f.text,
        intent_id: f.intent_id,
        session_id: f.session_id,
        open_questions: f.open_questions,
        problems: f.problems,
        slug: String::new(),
        title: String::new(),
        summary: String::new(),
    }
}

/// An intent row with its question keys and its origin from the state summary
/// (`intent_questions`, `intent_origins`).
fn board_intent(i: IntentRow, marks: &EventFacts, summary: &serde_json::Value) -> BoardIntent {
    let origin = &summary["intent_origins"][&i.intent_id];
    BoardIntent {
        questions: strings(&summary["intent_questions"][&i.intent_id]),
        origin: origin["origin"].as_str().unwrap_or("").to_string(),
        own: origin["own"].as_bool().unwrap_or(false),
        asked: marks.asked.get(&i.intent_id).cloned(),
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
        slug: String::new(),
        title: String::new(),
        summary: String::new(),
    }
}

/// Every board of the caller, with the graph of its thumbnail.
pub async fn list_boards(user: &CurrentUser) -> anyhow::Result<Vec<BoardListItem>> {
    let client = get_global_client();
    let boards = client
        .query("SELECT ?fields FROM boards FINAL WHERE owner = ? AND is_deleted = 0 ORDER BY created_at DESC")
        .bind(&user.username)
        .fetch_all::<BoardRow>()
        .await?;
    let ids: Vec<String> = boards.iter().map(|b| b.board_id.clone()).collect();
    if ids.is_empty() {
        return Ok(Vec::new());
    }
    let states: HashMap<String, StateRow> = client
        .query("SELECT ?fields FROM board_state FINAL WHERE board_id IN ?")
        .bind(&ids)
        .fetch_all::<StateRow>()
        .await?
        .into_iter()
        .map(|s| (s.board_id.clone(), s))
        .collect();
    let facts = client
        .query("SELECT ?fields FROM board_facts FINAL WHERE board_id IN ? ORDER BY created_at, fact_id")
        .bind(&ids)
        .fetch_all::<FactRow>()
        .await?;
    let intents = client
        .query("SELECT ?fields FROM board_intents FINAL WHERE board_id IN ? ORDER BY created_at, intent_id")
        .bind(&ids)
        .fetch_all::<IntentRow>()
        .await?;
    let events = client
        .query("SELECT ?fields FROM board_events FINAL WHERE board_id IN ? \
                AND event_type IN ('fact_rejected', 'review_rejected', 'reason_result') ORDER BY created_at, event_id")
        .bind(&ids)
        .fetch_all::<EventRow>()
        .await?;
    let requests: HashSet<(String, String)> = client
        .query("SELECT DISTINCT board_id, JSONExtractString(payload_json, 'request_id') FROM board_events FINAL \
                WHERE board_id IN ? AND JSONHas(payload_json, 'request_id')")
        .bind(&ids)
        .fetch_all::<(String, String)>()
        .await?
        .into_iter()
        .collect();
    let newest: HashMap<String, i64> = client
        .query("SELECT board_id, toUnixTimestamp64Milli(max(created_at)) FROM board_events FINAL WHERE board_id IN ? GROUP BY board_id")
        .bind(&ids)
        .fetch_all::<(String, i64)>()
        .await?
        .into_iter()
        .collect();
    let labels = read_labels(&ids).await?;
    let label = |board: &str, node: &str| labels.get(&(board.to_string(), node.to_string()));
    Ok(boards
        .into_iter()
        .map(|b| {
            let state = states.get(&b.board_id);
            let summary: serde_json::Value = state
                .and_then(|s| serde_json::from_str(&s.summary_json).ok())
                .unwrap_or_default();
            let board_events: Vec<EventRow> = events.iter().filter(|e| e.board_id == b.board_id).cloned().collect();
            let marks = event_facts(&board_events);
            let board_facts: Vec<BoardFact> = facts
                .iter()
                .filter(|f| f.board_id == b.board_id)
                .filter(|f| f.request_id.is_empty() || requests.contains(&(f.board_id.clone(), f.request_id.clone())))
                .cloned()
                .map(|mut f| {
                    f.text = f.text.chars().take(THUMB_TEXT).collect();
                    let mut fact = board_fact(f, &marks, Vec::new());
                    let id = fact.fact_id.clone();
                    label_fact(&mut fact, label(&b.board_id, &id));
                    fact
                })
                .collect();
            let count = |kind: &str| board_facts.iter().filter(|f| f.kind == kind && !f.rejected).count() as u32;
            let status = state.map(|s| s.status.clone()).unwrap_or_else(|| "active".to_string());
            BoardListItem {
                goals: count("goal"),
                facts_sourced: count("sourced"),
                facts_inferred: count("inferred"),
                facts_not_found: count("not_found"),
                running: summary["intents"]["running"].as_u64().unwrap_or(0) as u32,
                open: summary["intents"]["open"].as_u64().unwrap_or(0) as u32,
                explores_used: state.map(|s| s.explores_used).unwrap_or(0),
                max_explores: summary["max_explores"].as_u64().unwrap_or(u64::from(BASE_EXPLORES)) as u32,
                updated_ms: newest.get(&b.board_id).copied().unwrap_or_else(|| millis(b.created_at)),
                summary: label(&b.board_id, "").map(|l| l.summary.clone()).unwrap_or_default(),
                graph: BoardGraphInput {
                    status: status.clone(),
                    intents: intents
                        .iter()
                        .filter(|i| i.board_id == b.board_id)
                        .cloned()
                        .map(|i| {
                            let mut intent = board_intent(i, &marks, &summary);
                            let id = intent.intent_id.clone();
                            label_intent(&mut intent, label(&b.board_id, &id));
                            intent
                        })
                        .collect(),
                    facts: board_facts,
                    answers_proposed: answers(&summary, "answers_proposed"),
                    answers_accepted: answers(&summary, "answers_accepted"),
                },
                status,
                board_id: b.board_id,
                title: b.title,
            }
        })
        .collect())
}

/// Create a board: its definition, then the `create_board` command, which writes the
/// background, the goals, the creation event and the first hints. The board id comes from
/// the user and the request id, so the same request sent again names the same board.
pub async fn create_board_command(user: &CurrentUser, request_id: String,
                                  request: BoardCreateRequest) -> anyhow::Result<String> {
    if !crate::api::chat::gate::evaluate_live_chat_gate().await.is_open() {
        anyhow::bail!("AI chat is closed, so a board cannot start");
    }
    let stored_request = person_request(&request_id)?;
    let title = clip(&request.title);
    let goals: Vec<String> = request.goals.iter().map(|g| clip(g)).filter(|g| !g.is_empty()).collect();
    if title.is_empty() || goals.is_empty() {
        anyhow::bail!("a board needs a title and a goal");
    }
    if goals.len() > MAX_GOALS {
        anyhow::bail!("a board has at most {MAX_GOALS} goals");
    }
    // The rule of chat and search: an administrator reads every collection.
    let permitted = crate::db_utils::clickhouse_utils::list_permitted_collections(user).await?;
    let collections: Vec<String> = request
        .collections
        .iter()
        .filter(|c| permitted.contains(c))
        .cloned()
        .collect();
    if collections.is_empty() {
        anyhow::bail!("choose at least one collection that you can read");
    }
    let board_id = sha256::digest(format!("{}\n{stored_request}", user.username).as_bytes())[..32].to_string();
    let existing = get_global_client()
        .query("SELECT ?fields FROM boards FINAL WHERE board_id = ?")
        .bind(&board_id)
        .fetch_all::<BoardRow>()
        .await?
        .into_iter()
        .next();
    match existing {
        Some(row) if row.is_deleted != 0 => anyhow::bail!("The board was dropped."),
        Some(_) => {}
        None => {
            let created = now();
            let row = BoardRow {
                board_id: board_id.clone(),
                owner: user.username.clone(),
                title,
                goal: goals[0].clone(),
                context: clip(&request.context),
                collections: collections.clone(),
                llm_model: String::new(),
                max_explores: BASE_EXPLORES,
                max_parallel: MAX_PARALLEL,
                explore_step_budget: BASE_EXPLORE_STEPS,
                internet_tools: u8::from(request.internet_tools && super::chat::gate::internet_tools_enabled()),
                created_at: created,
                updated_at: created,
                is_deleted: 0,
            };
            insert_row("boards", &row).await?;
        }
    }
    let origin = format!("The investigation searches the collections {}. {}", collections.join(", "), clip(&request.context));
    let hints: Vec<String> = request.hints.iter().map(|h| clip(h)).filter(|h| !h.is_empty()).collect();
    submit(user, &board_id, &request_id, "create_board", serde_json::json!({
        "goals": goals, "origin": origin.trim(), "hints": hints,
    }))
    .await?;
    Ok(board_id)
}

/// A page loaded before the board commands calls this. It refuses, so the page reloads.
pub async fn create_board(_user: &CurrentUser, _request: BoardCreateRequest) -> anyhow::Result<String> {
    anyhow::bail!("This page is out of date. Reload the page and try again.")
}

/// Turn the internet tools of a board's later explores on or off. The board row gets a new
/// version, which the explores read, and a command records the change for the event log.
async fn set_internet_tools(user: &CurrentUser, mut board: BoardRow, request_id: &str,
                            on: bool) -> anyhow::Result<BoardCommandReceipt> {
    let on = on && super::chat::gate::internet_tools_enabled();
    if (board.internet_tools != 0) != on {
        board.internet_tools = u8::from(on);
        board.updated_at = now();
        insert_row("boards", &board).await?;
    }
    submit(user, &board.board_id, request_id, "set_internet_tools", serde_json::json!({"on": on})).await
}

/// One action of the board owner, as one command. The command writer checks it against the
/// committed state of the board, so a stale page cannot act on a newer review or answer.
pub async fn board_command(user: &CurrentUser, board_id: String, request_id: String,
                           action: BoardAction) -> anyhow::Result<BoardCommandReceipt> {
    let board = owned_board(user, &board_id).await?;
    let (kind, body) = match action {
        BoardAction::AddHint { text } => {
            let text = clip(&text);
            if text.is_empty() {
                anyhow::bail!("The hint is empty.");
            }
            ("add_hint", serde_json::json!({"text": text}))
        }
        BoardAction::RejectFact { fact_id, reason } => {
            ("reject_fact", serde_json::json!({"fact_id": fact_id, "reason": clip(&reason)}))
        }
        BoardAction::SetPaused { paused } => ("set_paused", serde_json::json!({"paused": paused})),
        BoardAction::SetInternetTools { on } => return set_internet_tools(user, board, &request_id, on).await,
        BoardAction::Review { review_id, accept, correction } => ("review_decision", serde_json::json!({
            "review_id": review_id, "accept": accept, "correction": clip(&correction),
        })),
        BoardAction::Answer { goal, proposal_id, accept, correction } => ("answer_decision", serde_json::json!({
            "goal": goal, "proposal_id": proposal_id, "accept": accept, "correction": clip(&correction),
        })),
        BoardAction::AddGoal { text } => {
            let text = clip(&text);
            if text.is_empty() {
                anyhow::bail!("The goal is empty.");
            }
            ("add_goal", serde_json::json!({"text": text}))
        }
        BoardAction::ExploreQuestion { fact_id, index, question } => {
            let question = clip(&question);
            match (index, question.is_empty()) {
                (Some(index), true) => ("explore_question", serde_json::json!({"fact_id": fact_id, "index": index})),
                (None, false) => ("explore_question", serde_json::json!({"fact_id": fact_id, "question": question})),
                _ => anyhow::bail!("Name an open question or write a question."),
            }
        }
        BoardAction::Reopen { expected_id } => ("extend_budget", serde_json::json!({"expected_id": expected_id})),
    };
    submit(user, &board.board_id, &request_id, kind, body).await
}

/// The state of one command of the owner's board.
pub async fn board_command_status(user: &CurrentUser, board_id: String,
                                  request_id: String) -> anyhow::Result<BoardCommandReceipt> {
    owned_board(user, &board_id).await?;
    command_state(&board_id, &person_request(&request_id)?).await
}

/// The fact that an intent of the owner's board concluded in, or `None` while it has none.
/// A fact whose event is not written yet is not shown.
pub async fn board_fact_for_intent(user: &CurrentUser, board_id: String,
                                   intent_id: String) -> anyhow::Result<Option<String>> {
    owned_board(user, &board_id).await?;
    let client = get_global_client();
    let facts = client
        .query("SELECT ?fields FROM board_facts FINAL WHERE board_id = ? AND intent_id = ?")
        .bind(&board_id)
        .bind(&intent_id)
        .fetch_all::<FactRow>()
        .await?;
    if facts.is_empty() {
        return Ok(None);
    }
    let events = client
        .query("SELECT ?fields FROM board_events FINAL WHERE board_id = ? AND event_type = 'explore_concluded' AND subject = ?")
        .bind(&board_id)
        .bind(&intent_id)
        .fetch_all::<EventRow>()
        .await?;
    let published = published(&events);
    let concluded: HashSet<String> = events
        .iter()
        .filter_map(|e| serde_json::from_str::<serde_json::Value>(&e.payload_json).ok())
        .filter_map(|p| p["fact_id"].as_str().map(str::to_string))
        .collect();
    Ok(facts
        .into_iter()
        .find(|f| is_visible(f, &published) && (f.request_id.is_empty() || concluded.contains(&f.fact_id)))
        .map(|f| f.fact_id))
}

/// The word of a board status in an event line.
fn status_word(status: &str) -> &str {
    match status {
        "review" => "waits for review",
        "completed" => "complete",
        other => other,
    }
}

/// The budget change of a budget event, in brackets after its fixed text. Empty for another
/// event. The page writes the person's text after the fixed text.
fn grant_text(grant: Option<i64>) -> String {
    match grant {
        Some(n) if n > 0 => format!(" (budget +{n} explores)"),
        Some(_) => " (budget unchanged, the board is at its explore limit)".to_string(),
        None => String::new(),
    }
}

/// The fixed text of one event and the text that a person wrote in it, from its type and
/// payload. `slug` gives the display name of a node id, and `grant` the budget change of the
/// event (`summary_json.grants`). The person's text (a hint, a rejection reason, a
/// correction) is the second value, so the page can set it apart.
fn summarise(event_type: &str, subject: &str, payload: &serde_json::Value,
             slug: &dyn Fn(&str) -> String, grant: Option<i64>) -> (String, String) {
    let text = |key: &str| payload[key].as_str().unwrap_or("").to_string();
    let fixed = |summary: String| (summary, String::new());
    let grown = grant_text(grant);
    match event_type {
        "board_created" => fixed("The board was created.".to_string()),
        "hint_added" => (format!("Added a hint{grown}"), text("text")),
        "fact_rejected" => (format!("Rejected {}{grown}", slug(subject)), text("reason")),
        "pause_requested" => fixed("A pause was requested.".to_string()),
        "resume_requested" => fixed("A resume was requested.".to_string()),
        "review_accepted" => fixed("The board was finished. It is complete.".to_string()),
        "review_rejected" => (format!("Continued the board with a correction{grown}"), text("correction")),
        "goal_answer_accepted" => fixed(format!("Accepted the answer of {}.", slug(subject))),
        "goal_answer_rejected" => (format!("Rejected the answer of {}{grown}", slug(&text("goal"))), text("correction")),
        "drop_requested" => fixed("The board was dropped.".to_string()),
        "goal_added" => (format!("Added the goal {}{grown}", slug(subject)), text("text")),
        "question_explored" if payload["own"].as_bool().unwrap_or(false) => {
            (format!("Asked a question about {} in {}{grown}", slug(&text("fact_id")), slug(subject)), text("question"))
        }
        "question_explored" => (format!("Asked to explore a question of {}{grown}", slug(&text("fact_id"))), text("question")),
        "budget_extended" => fixed(match payload["grant"].as_u64().or(grant.map(|g| g.max(0) as u64)) {
            Some(n) if n > 0 => format!("Reopened the board with {n} more explores."),
            _ => "Reopened the board with the remaining budget.".to_string(),
        }),
        "status_changed" => fixed(format!(
            "The board status changed from {} to {}.",
            status_word(&text("prior")),
            status_word(&text("status"))
        )),
        "settings_changed" => fixed(if payload["internet_tools"].as_bool().unwrap_or(false) {
            "The internet tools were turned on for later explores.".to_string()
        } else {
            "The internet tools were turned off for later explores.".to_string()
        }),
        "reason_started" if payload["final"].as_bool().unwrap_or(false) => fixed(format!(
            "Final assessment {subject} of the budget of {} explores started.",
            payload["assessed_budget"]
        )),
        "reason_started" => fixed(format!("Assessment {subject} started.")),
        "reason_result" => {
            let outcome = text("outcome");
            let problems = payload["problems"].as_array().map(|p| p.len()).unwrap_or(0);
            let count = |key: &str| payload[key].as_array().map(|i| i.len()).unwrap_or(0);
            let detail = match outcome.as_str() {
                "intents" => format!("{} new intents", count("intents")),
                "review" => "it proposes an answer for every open goal".to_string(),
                "partial" => format!("it proposes {} answers and {} new intents", count("proposals"), count("intents")),
                "noop" => "no new intent".to_string(),
                _ => format!("an invalid reply {}", text("error")),
            };
            let checks = if problems > 0 { format!(", {problems} checks changed it") } else { String::new() };
            let name = if payload["final"].as_bool().unwrap_or(false) { "Final assessment" } else { "Assessment" };
            fixed(format!("{name} {subject}: {detail}{checks}."))
        }
        "final_assessment_ended" => fixed(format!(
            "The final assessment of the budget of {} explores ended: {}.",
            payload["assessed_budget"],
            text("outcome")
        )),
        "explore_started" => fixed(format!("Explore of {} started, attempt {}.", slug(subject), payload["attempt"])),
        "explore_concluded" => fixed(format!("{} concluded in {} ({}).", slug(subject), slug(&text("fact_id")), text("kind"))),
        "explore_failed" => fixed(format!("{} failed: {}", slug(subject), text("error"))),
        "explore_cancelled" => fixed(format!("{} was cancelled: {}", slug(subject), text("error"))),
        "explore_question" => fixed(format!("{} asked a question: {}", slug(subject), text("question"))),
        "review_proposed" => fixed(match text("reason").as_str() {
            "budget" => format!(
                "The board used its budget of {} explores and waits for review.",
                payload["max_explores"]
            ),
            "stalled" => "The assessments gave no usable direction, and the board waits for review.".to_string(),
            _ => format!("The board went to review: {}", text("statement")),
        }),
        other => fixed(other.replace('_', " ")),
    }
}

/// The whole board.
pub async fn board_snapshot(user: &CurrentUser, board_id: String) -> anyhow::Result<BoardSnapshot> {
    read_snapshot(owned_board(user, &board_id).await?).await
}

/// The whole board of a row that the caller already checked with `owned_board`.
async fn read_snapshot(board: BoardRow) -> anyhow::Result<BoardSnapshot> {
    let board_id = board.board_id.clone();
    let client = get_global_client();
    let state = client
        .query("SELECT ?fields FROM board_state FINAL WHERE board_id = ?")
        .bind(&board_id)
        .fetch_all::<StateRow>()
        .await?
        .into_iter()
        .next();
    let events = order_events(
        client
            .query("SELECT ?fields FROM board_events FINAL WHERE board_id = ? ORDER BY created_at, event_id")
            .bind(&board_id)
            .fetch_all::<EventRow>()
            .await?,
    );
    let visible = published(&events);
    let facts: Vec<FactRow> = client
        .query("SELECT ?fields FROM board_facts FINAL WHERE board_id = ? ORDER BY created_at, fact_id")
        .bind(&board_id)
        .fetch_all::<FactRow>()
        .await?
        .into_iter()
        .filter(|f| is_visible(f, &visible))
        .collect();
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
    let marks = event_facts(&events);
    let labels = read_labels(std::slice::from_ref(&board_id)).await?;
    let label = |node: &str| labels.get(&(board_id.clone(), node.to_string()));
    let summary: serde_json::Value = state
        .as_ref()
        .and_then(|s| serde_json::from_str(&s.summary_json).ok())
        .unwrap_or_default();
    let facts: Vec<BoardFact> = facts
        .into_iter()
        .map(|f| {
            let cited = citations
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
                .collect();
            let mut fact = board_fact(f, &marks, cited);
            let id = fact.fact_id.clone();
            label_fact(&mut fact, label(&id));
            fact
        })
        .collect();
    let intents: Vec<BoardIntent> = intents
        .into_iter()
        .map(|i| {
            let mut intent = board_intent(i, &marks, &summary);
            let id = intent.intent_id.clone();
            label_intent(&mut intent, label(&id));
            intent
        })
        .collect();
    let slugs: HashMap<String, String> = facts
        .iter()
        .map(|f| (f.fact_id.clone(), f.slug.clone()))
        .chain(intents.iter().map(|i| (i.intent_id.clone(), i.slug.clone())))
        .collect();
    let slug = |id: &str| slugs.get(id).cloned().unwrap_or_else(|| id.to_string());
    let status = state.as_ref().map(|s| s.status.clone()).unwrap_or_else(|| "active".to_string());
    let max_explores = summary["max_explores"].as_u64().unwrap_or(u64::from(BASE_EXPLORES)) as u32;
    let answers_accepted = answers(&summary, "answers_accepted");
    let review_id = summary["decision_id"].as_str().unwrap_or("").to_string();
    let limit_reached = summary["limit_reached"].as_bool().unwrap_or(false);
    let open_goal = facts
        .iter()
        .any(|f| f.kind == "goal" && !answers_accepted.iter().any(|a| a.goal == f.fact_id));
    let reopened = summary["extended"].as_array().is_some_and(|ids| ids.iter().any(|id| id.as_str() == Some(&review_id)));
    let reopen_grant = (matches!(status.as_str(), "review" | "completed")
        && !review_id.is_empty()
        && open_goal
        && !limit_reached
        && !reopened)
        .then(|| EXTENSION_EXPLORES.min(EXPLORE_LIMIT.saturating_sub(max_explores)));
    let final_running = summary["final_ops"]
        .as_object()
        .is_some_and(|ops| ops.values().any(|op| op["state"] == "running"));
    let grants = &summary["grants"];
    Ok(BoardSnapshot {
        review_id,
        review_reason: summary["review_reason"].as_str().unwrap_or("").to_string(),
        limit_reached,
        reopen_grant,
        final_running,
        summary: label("").map(|l| l.summary.clone()).unwrap_or_default(),
        status,
        explores_used: state.as_ref().map(|s| s.explores_used).unwrap_or(0),
        reasons_done: state.as_ref().map(|s| s.reasons_done).unwrap_or(0),
        stall_count: state.as_ref().map(|s| u32::from(s.stall_count)).unwrap_or(0),
        review_statement: summary["review_statement"].as_str().unwrap_or("").to_string(),
        answers_proposed: answers(&summary, "answers_proposed"),
        answers_accepted,
        max_explores,
        explore_steps: summary["explore_steps"].as_u64().unwrap_or(u64::from(BASE_EXPLORE_STEPS)) as u32,
        facts,
        intents,
        events: events
            .into_iter()
            .map(|e| {
                let payload: serde_json::Value = serde_json::from_str(&e.payload_json).unwrap_or_default();
                let (summary, quote) = summarise(&e.event_type, &e.subject, &payload, &slug, grants[&e.event_id].as_i64());
                BoardEvent {
                    summary,
                    quote,
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
            max_parallel: board.max_parallel,
            internet_tools: board.internet_tools != 0 && super::chat::gate::internet_tools_enabled(),
        },
    })
}

/// The person actions of a page loaded before the board commands. Each refuses, so the page
/// reloads and sends its actions through `board_command`.
const OUTDATED_PAGE: &str = "This page is out of date. Reload the page and try again.";

pub async fn board_add_hint(_user: &CurrentUser, _board_id: String, _text: String) -> anyhow::Result<()> {
    anyhow::bail!(OUTDATED_PAGE)
}

pub async fn board_add_goal(_user: &CurrentUser, _board_id: String, _text: String) -> anyhow::Result<()> {
    anyhow::bail!(OUTDATED_PAGE)
}

pub async fn board_explore_question(_user: &CurrentUser, _board_id: String, _fact_id: String,
                                    _index: u32) -> anyhow::Result<()> {
    anyhow::bail!(OUTDATED_PAGE)
}

pub async fn board_reject_fact(_user: &CurrentUser, _board_id: String, _fact_id: String,
                               _reason: String) -> anyhow::Result<()> {
    anyhow::bail!(OUTDATED_PAGE)
}

pub async fn board_set_paused(_user: &CurrentUser, _board_id: String, _paused: bool) -> anyhow::Result<()> {
    anyhow::bail!(OUTDATED_PAGE)
}

pub async fn board_set_internet_tools(_user: &CurrentUser, _board_id: String, _on: bool) -> anyhow::Result<()> {
    anyhow::bail!(OUTDATED_PAGE)
}

pub async fn board_review(_user: &CurrentUser, _board_id: String, _accept: bool,
                          _correction: String) -> anyhow::Result<()> {
    anyhow::bail!(OUTDATED_PAGE)
}

pub async fn board_answer(_user: &CurrentUser, _board_id: String, _goal: String, _reason_no: u32,
                          _accept: bool, _correction: String) -> anyhow::Result<()> {
    anyhow::bail!(OUTDATED_PAGE)
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct AssessmentRow {
    prompt: String,
    reply: String,
    error: String,
    model: String,
}

/// The prompt, the reply and the outcome of one assessment. An assessment that ran before the
/// prompts were stored has no row, and shows the reply that its event holds.
pub async fn board_assessment(user: &CurrentUser, board_id: String, reason_no: u32) -> anyhow::Result<BoardAssessment> {
    owned_board(user, &board_id).await?;
    let client = get_global_client();
    let event = client
        .query("SELECT ?fields FROM board_events FINAL WHERE board_id = ? AND event_type = 'reason_result' AND subject = ?")
        .bind(&board_id)
        .bind(reason_no.to_string())
        .fetch_all::<EventRow>()
        .await?
        .into_iter()
        .next()
        .ok_or_else(|| anyhow::anyhow!("the board has no assessment {reason_no}"))?;
    let row = client
        .query("SELECT prompt, reply, error, model FROM board_assessments FINAL WHERE board_id = ? AND reason_no = ?")
        .bind(&board_id)
        .bind(reason_no)
        .fetch_all::<AssessmentRow>()
        .await?
        .into_iter()
        .next();
    let payload: serde_json::Value = serde_json::from_str(&event.payload_json).unwrap_or_default();
    Ok(assessment_of(reason_no, millis(event.created_at), &payload, row))
}

fn assessment_of(reason_no: u32, created_ms: i64, payload: &serde_json::Value, row: Option<AssessmentRow>) -> BoardAssessment {
    let text = |key: &str| payload[key].as_str().unwrap_or("").to_string();
    let number = |key: &str| payload[key].as_u64().unwrap_or(0);
    let mut out = BoardAssessment {
        reason_no,
        created_ms,
        outcome: text("outcome"),
        model: text("model"),
        latency_ms: number("latency_ms"),
        prompt_tokens: number("prompt_tokens"),
        completion_tokens: number("completion_tokens"),
        problems: strings(&payload["problems"]),
        reply: text("raw"),
        error: text("error"),
        ..Default::default()
    };
    if let Some(row) = row {
        out.prompt = row.prompt;
        out.reply = row.reply;
        out.error = row.error;
        if !row.model.is_empty() {
            out.model = row.model;
        }
        out.stored = true;
    }
    out
}

/// Drop a board: tombstone its definition, cancel its command writer and its running
/// explores, delete its explore sessions through the chat deletion path, and delete the rows
/// of its nine tables. The command writer refuses every command of a tombstoned board, so no
/// command writes after the delete.
pub async fn board_drop(user: &CurrentUser, board_id: String) -> anyhow::Result<()> {
    let mut board = owned_board(user, &board_id).await?;
    board.is_deleted = 1;
    board.updated_at = now();
    insert_row("boards", &board).await?;
    let commands = format!("board-commands-{board_id}");
    if let Err(e) = crate::api::chat::cancel_workflow(&commands).await {
        tracing::warn!("could not cancel {commands}: {e:#}");
    }
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
    for table in ["board_events", "board_state", "board_intents", "board_facts", "board_fact_citations",
                  "board_labels", "board_assessments", "board_command_inputs", "board_command_receipts"] {
        client
            .query(&format!("DELETE FROM {table} WHERE board_id = ?"))
            .bind(&board_id)
            .execute()
            .await?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn event(event_type: &str, subject: &str, payload: serde_json::Value, second: i64) -> EventRow {
        EventRow {
            board_id: "b".into(),
            event_id: format!("e{second}"),
            event_type: event_type.into(),
            actor: "alice".into(),
            subject: subject.into(),
            payload_json: payload.to_string(),
            created_at: OffsetDateTime::from_unix_timestamp(second).unwrap(),
        }
    }

    #[test]
    fn a_rejection_names_who_when_and_why_and_a_correction_names_the_facts_it_corrects() {
        let events = vec![
            event("fact_rejected", "f1.1", serde_json::json!({"reason": "wrong year"}), 10),
            event("reason_result", "2", serde_json::json!({"outcome": "review", "review": {"from": ["f1.2", "f2.1"]}}), 20),
            // Written before the event held `from`: the newest review gives the facts.
            event("review_rejected", "c1", serde_json::json!({"correction": "no"}), 30),
            event("review_rejected", "c2", serde_json::json!({"correction": "no", "from": ["f3.1"]}), 40),
        ];
        let marks = event_facts(&events);
        assert_eq!(marks.rejections["f1.1"], ("alice".to_string(), 10_000, "wrong year".to_string()));
        assert_eq!(marks.corrects["c1"], vec!["f1.2".to_string(), "f2.1".to_string()]);
        assert_eq!(marks.corrects["c2"], vec!["f3.1".to_string()]);
    }

    #[test]
    fn an_event_names_nodes_by_slug_and_keeps_the_persons_text_apart() {
        let slugs: HashMap<&str, &str> = [("f1.2", "fact-raptor-capacity"), ("i1.2", "intent-find-raptor")].into();
        let slug = |id: &str| slugs.get(id).map(|s| s.to_string()).unwrap_or_else(|| id.to_string());
        let concluded = summarise("explore_concluded", "i1.2", &serde_json::json!({"fact_id": "f1.2", "kind": "sourced"}), &slug, None);
        assert_eq!(concluded, ("intent-find-raptor concluded in fact-raptor-capacity (sourced).".to_string(), String::new()));
        let rejected = summarise("fact_rejected", "f1.2", &serde_json::json!({"reason": "wrong year"}), &slug, Some(4));
        assert_eq!(rejected, ("Rejected fact-raptor-capacity (budget +4 explores)".to_string(), "wrong year".to_string()));
        let hint = summarise("hint_added", "", &serde_json::json!({"text": "look at May"}), &slug, Some(0));
        assert_eq!(hint, ("Added a hint (budget unchanged, the board is at its explore limit)".to_string(), "look at May".to_string()));
        let goal = summarise("goal_added", "goal-2", &serde_json::json!({"text": "Find the auditor"}), &slug, None);
        assert_eq!(goal.1, "Find the auditor");
        let question = summarise("question_explored", "i0.7", &serde_json::json!({"fact_id": "f1.2", "question": "Who?"}), &slug, None);
        assert_eq!(question, ("Asked to explore a question of fact-raptor-capacity".to_string(), "Who?".to_string()));
        let own = summarise("question_explored", "i1.2", &serde_json::json!({"fact_id": "f1.2", "own": true, "question": "When?"}), &slug, None);
        assert_eq!(own, ("Asked a question about fact-raptor-capacity in intent-find-raptor".to_string(), "When?".to_string()));
        let accepted = summarise("goal_answer_accepted", "goal-2", &serde_json::json!({}), &slug, None);
        assert_eq!(accepted.0, "Accepted the answer of goal-2.");
        let rejected = summarise("goal_answer_rejected", "c1", &serde_json::json!({"goal": "goal-2", "correction": "no"}), &slug, None);
        assert_eq!(rejected, ("Rejected the answer of goal-2".to_string(), "no".to_string()));
        let started = summarise("reason_started", "3", &serde_json::json!({}), &slug, None);
        assert_eq!(started.0, "Assessment 3 started.");
        let correction = summarise("review_rejected", "c1", &serde_json::json!({"correction": "no"}), &slug, None);
        assert_eq!(correction.1, "no");
        let reopened = summarise("budget_extended", "", &serde_json::json!({"grant": 20}), &slug, Some(20));
        assert_eq!(reopened.0, "Reopened the board with 20 more explores.");
        let resumed = summarise("budget_extended", "", &serde_json::json!({"grant": 0}), &slug, Some(0));
        assert_eq!(resumed.0, "Reopened the board with the remaining budget.");
        let status = summarise("status_changed", "review", &serde_json::json!({"prior": "active", "status": "review"}), &slug, None);
        assert_eq!(status.0, "The board status changed from active to waits for review.");
        let budget = summarise("review_proposed", "budget", &serde_json::json!({"reason": "budget", "max_explores": 80}), &slug, None);
        assert_eq!(budget.0, "The board used its budget of 80 explores and waits for review.");
    }

    #[test]
    fn events_follow_the_fold_order_and_a_status_row_follows_its_cause() {
        let events = vec![
            event("board_created", "", serde_json::json!({}), 10),
            event("hint_added", "", serde_json::json!({"seq": 2, "request_id": "web:b"}), 20),
            event("status_changed", "paused", serde_json::json!({"causal_event_id": "e30", "ordinal": 0}), 30),
            event("pause_requested", "", serde_json::json!({"seq": 1, "request_id": "web:a"}), 30),
            event("status_changed", "active", serde_json::json!({"causal_event_id": "e99", "ordinal": 0}), 5),
        ];
        let order: Vec<String> = order_events(events.clone()).into_iter().map(|e| e.event_type).collect();
        assert_eq!(order, vec!["board_created", "pause_requested", "status_changed", "hint_added", "status_changed"]);
        let seen = published(&events);
        assert!(seen.contains("web:a") && seen.contains("web:b") && seen.len() == 2);
        let fact = |request: &str| FactRow {
            board_id: "b".into(), fact_id: "fact-x".into(), kind: "sourced".into(), text: String::new(),
            intent_id: String::new(), session_id: String::new(), answer_seq: 0, open_questions: vec![],
            problems: vec![], created_by: String::new(), created_at: OffsetDateTime::UNIX_EPOCH,
            request_id: request.into(),
        };
        assert!(is_visible(&fact(""), &seen) && is_visible(&fact("web:a"), &seen));
        assert!(!is_visible(&fact("explore_end:intent-x:1"), &seen), "a fact before its event is hidden");
    }

    #[test]
    fn a_page_request_id_gets_the_person_prefix_and_an_unsafe_one_is_refused() {
        assert_eq!(person_request("a1-b2_c3").unwrap(), "web:a1-b2_c3");
        assert!(person_request("").is_err());
        assert!(person_request("reason_started:1").is_err(), "a page cannot name a worker request");
        assert!(person_request(&"x".repeat(65)).is_err());
    }

    #[test]
    fn a_label_or_its_fallback_names_a_node() {
        let label = LabelRow { board_id: "b".into(), node_id: "f1.1".into(), slug: "fact-x".into(),
                               title: "X Title".into(), summary: "x summary".into() };
        assert_eq!(node_label("f1.1", "some text", Some(&label)), ("fact-x".into(), "X Title".into(), "x summary".into()));
        let created = LabelRow { title: String::new(), summary: String::new(), ..label.clone() };
        assert_eq!(node_label("f1.1", "one two three four five", Some(&created)),
                   ("fact-x".into(), "one two three four".into(), "one two three four five".into()));
        let empty = LabelRow { slug: String::new(), ..label };
        assert_eq!(node_label("f1.1", "one two three four five", Some(&empty)).0, "f1.1");
        assert_eq!(node_label("f1.1", "one two three four five", None).1, "one two three four");
    }

    #[test]
    fn an_assessment_shows_its_stored_prompt_or_the_reply_of_its_event() {
        let payload = serde_json::json!({"outcome": "intents", "raw": "short reply", "model": "m1",
                                         "latency_ms": 900, "problems": ["dropped i1.2"]});
        let old = assessment_of(3, 10, &payload, None);
        assert!(!old.stored && old.prompt.is_empty());
        assert_eq!((old.reply.as_str(), old.model.as_str(), old.latency_ms), ("short reply", "m1", 900));
        assert_eq!(old.problems, vec!["dropped i1.2".to_string()]);
        let row = AssessmentRow { prompt: "p".into(), reply: "whole reply".into(), error: String::new(), model: "m2".into() };
        let new = assessment_of(3, 10, &payload, Some(row));
        assert!(new.stored);
        assert_eq!((new.prompt.as_str(), new.reply.as_str(), new.model.as_str()), ("p", "whole reply", "m2"));
    }

    #[test]
    fn the_summary_gives_the_proposed_and_the_accepted_answers() {
        let summary = serde_json::json!({
            "answers_proposed": [{"goal": "goal-2", "from": ["f1.2"], "statement": "b", "reason_no": 4}],
            "answers_accepted": [{"goal": "goal", "from": ["f1.1"], "statement": "a", "reason_no": 3}],
        });
        assert_eq!(answers(&summary, "answers_proposed"), vec![BoardReviewGoal {
            goal: "goal-2".into(), from: vec!["f1.2".into()], statement: "b".into(), reason_no: 4,
            ..Default::default()
        }]);
        assert_eq!(answers(&summary, "answers_accepted")[0].goal, "goal");
        assert!(answers(&serde_json::json!({}), "answers_accepted").is_empty());
    }

    #[test]
    fn a_rejected_answer_corrects_its_facts_and_an_intent_names_its_question() {
        let events = vec![
            event("goal_answer_rejected", "c3", serde_json::json!({"goal": "goal-2", "from": ["f1.2"]}), 10),
            event("question_explored", "i0.1", serde_json::json!({"fact_id": "f1.2", "index": 1}), 20),
            event("question_explored", "i0.1", serde_json::json!({"fact_id": "f9.9", "index": 0}), 30),
            event("question_explored", "intent-when", serde_json::json!({"fact_id": "f1.2", "own": true}), 40),
        ];
        let marks = event_facts(&events);
        assert_eq!(marks.corrects["c3"], vec!["f1.2".to_string()]);
        assert_eq!(marks.asked["i0.1"], BoardQuestionRef { fact_id: "f1.2".into(), index: 1 });
        assert!(!marks.asked.contains_key("intent-when"), "an own question follows no open question");
    }
}
