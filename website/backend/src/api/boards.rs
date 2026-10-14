//! Investigation boards: the server functions of the board pages under AI Chat.
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
//! Every user can own boards. Only the owner of a board can read it or act on it. This
//! applies to administrators too. Anyone else gets not-found, which is the convention of
//! `auth::guard::NOT_FOUND`. A board starts only while AI chat is open
//! (`chat::gate::evaluate_live_chat_gate`), because its explores are chat turns.
//!
//! The explore model and the budgets are not inputs. The website writes the base values in
//! the board row, and the worker computes the budget from the events
//! (`tasks/P_board/fold.py`, `Folded.max_explores`). A board can have several goals: each
//! is a fact of kind `goal`, with the ids of `common::board_types::goal_id`.
//!
//! The worker writes a generated slug, title and summary for each intent, fact and correction
//! in `board_labels` (`tasks/P_board/labels.py`), and one summary row for each board. The
//! reads here attach them to the nodes. A node without a label yet shows its storage id and
//! the first words of its text (`common::board_types::fallback_label`). The storage ids stay
//! the keys of every write.

use std::collections::HashMap;

use common::board_types::{
    fallback_label, fixed_slug, goal_id, BoardCitation, BoardCreateRequest, BoardDefinition,
    BoardEvent, BoardFact, BoardGraphInput, BoardIntent, BoardListItem, BoardReviewGoal,
    BoardSnapshot, BOARD_SESSION_PREFIX, MAX_GOALS,
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
/// `BASE_EXPLORE_STEPS`).
const BASE_EXPLORES: u16 = 12;
const BASE_EXPLORE_STEPS: u16 = 60;
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

fn node_label(id: &str, text: &str, label: Option<&LabelRow>) -> (String, String, String) {
    match label.filter(|l| !l.slug.is_empty()) {
        Some(l) => (l.slug.clone(), l.title.clone(), l.summary.clone()),
        None => fallback_label(id, text),
    }
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

/// The rejection of each rejected fact (who, when, why), and the facts that each correction
/// corrects. A correction comes from a rejected review. It corrects the facts that the review
/// named: the `from` of its event, or for an event written before that field, the facts of the
/// newest review that reason proposed before it.
#[derive(Default)]
struct EventFacts {
    rejections: HashMap<String, (String, i64, String)>,
    corrects: HashMap<String, Vec<String>>,
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
            "reason_result" if payload["outcome"] == "review" => {
                last_review = strings(&payload["review"]["from"]);
            }
            "review_rejected" => {
                let from = strings(&payload["from"]);
                out.corrects.insert(event.subject.clone(), if from.is_empty() { last_review.clone() } else { from });
            }
            _ => {}
        }
    }
    out
}

fn strings(value: &serde_json::Value) -> Vec<String> {
    value.as_array().map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect()).unwrap_or_default()
}

/// The review of each goal from the state summary. A summary written before goal reviews
/// existed has one review, of the first goal.
fn review_goals(summary: &serde_json::Value) -> Vec<BoardReviewGoal> {
    let goals: Vec<BoardReviewGoal> = summary["review_goals"]
        .as_array()
        .map(|list| {
            list.iter()
                .map(|g| BoardReviewGoal {
                    goal: g["goal"].as_str().unwrap_or("").to_string(),
                    from: strings(&g["from"]),
                    statement: g["statement"].as_str().unwrap_or("").to_string(),
                })
                .filter(|g| !g.goal.is_empty())
                .collect()
        })
        .unwrap_or_default();
    let from = strings(&summary["review_from"]);
    if goals.is_empty() && !from.is_empty() {
        return vec![BoardReviewGoal {
            goal: goal_id(1),
            from,
            statement: summary["review_statement"].as_str().unwrap_or("").to_string(),
        }];
    }
    goals
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

fn board_intent(i: IntentRow) -> BoardIntent {
    BoardIntent {
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
                            let mut intent = board_intent(i);
                            let id = intent.intent_id.clone();
                            label_intent(&mut intent, label(&b.board_id, &id));
                            intent
                        })
                        .collect(),
                    facts: board_facts,
                    review_goals: review_goals(&summary),
                },
                status,
                board_id: b.board_id,
                title: b.title,
            }
        })
        .collect())
}

/// Create a board: its definition, its origin and goal facts, and its first events.
pub async fn create_board(user: &CurrentUser, request: BoardCreateRequest) -> anyhow::Result<String> {
    if !crate::api::chat::gate::evaluate_live_chat_gate().await.is_open() {
        anyhow::bail!("AI chat is closed, so a board cannot start");
    }
    let title = clip(&request.title);
    let goals: Vec<String> = request.goals.iter().map(|g| clip(g)).filter(|g| !g.is_empty()).collect();
    if title.is_empty() || goals.is_empty() {
        anyhow::bail!("a board needs a title and a goal");
    }
    if goals.len() > MAX_GOALS {
        anyhow::bail!("a board has at most {MAX_GOALS} goals");
    }
    let permitted = crate::db_auth::collections::permitted_collections(&user.username).await?;
    let collections: Vec<String> = request
        .collections
        .iter()
        .filter(|c| permitted.contains(c))
        .cloned()
        .collect();
    if collections.is_empty() {
        anyhow::bail!("choose at least one collection that you can read");
    }
    let board_id = new_id();
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
        internet_tools: u8::from(request.internet_tools),
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
    for (index, goal) in goals.iter().enumerate() {
        write_fact(&board_id, &goal_id(index + 1), "goal", goal, &user.username).await?;
    }
    write_event(&board_id, "board_created", &user.username, "", serde_json::json!({})).await?;
    for hint in request.hints.iter().map(|h| clip(h)).filter(|h| !h.is_empty()) {
        write_event(&board_id, "hint_added", &user.username, "", serde_json::json!({"text": hint})).await?;
    }
    Ok(board_id)
}

/// Turn the internet tools of a board's later explores on or off. The board row gets a new
/// version, and an event records the change for the timeline.
pub async fn board_set_internet_tools(user: &CurrentUser, board_id: String, on: bool) -> anyhow::Result<()> {
    let mut board = owned_board(user, &board_id).await?;
    if (board.internet_tools != 0) == on {
        return Ok(());
    }
    board.internet_tools = u8::from(on);
    board.updated_at = now();
    insert_row("boards", &board).await?;
    write_event(&board_id, "settings_changed", &user.username, "", serde_json::json!({"internet_tools": on})).await
}

/// The fixed text of one event and the text that a person wrote in it, from its type and
/// payload. `slug` gives the display name of a node id. The person's text (a hint, a
/// rejection reason, a correction) is the second value, so the page can set it apart.
fn summarise(event_type: &str, subject: &str, payload: &serde_json::Value,
             slug: &dyn Fn(&str) -> String) -> (String, String) {
    let text = |key: &str| payload[key].as_str().unwrap_or("").to_string();
    let fixed = |summary: String| (summary, String::new());
    match event_type {
        "board_created" => fixed("The board was created.".to_string()),
        "hint_added" => ("Added a hint".to_string(), text("text")),
        "fact_rejected" => (format!("Rejected {}", slug(subject)), text("reason")),
        "pause_requested" => fixed("A pause was requested.".to_string()),
        "resume_requested" => fixed("A resume was requested.".to_string()),
        "review_accepted" => fixed("The review was accepted. The board is complete.".to_string()),
        "review_rejected" => ("Rejected the review".to_string(), text("correction")),
        "drop_requested" => fixed("The board was dropped.".to_string()),
        "settings_changed" => fixed(if payload["internet_tools"].as_bool().unwrap_or(false) {
            "The internet tools were turned on for later explores.".to_string()
        } else {
            "The internet tools were turned off for later explores.".to_string()
        }),
        "reason_started" => fixed(format!("Reason {subject} started.")),
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
            fixed(format!("Reason {subject}: {detail}{checks}."))
        }
        "explore_started" => fixed(format!("Explore of {} started, attempt {}.", slug(subject), payload["attempt"])),
        "explore_concluded" => fixed(format!("{} concluded in {} ({}).", slug(subject), slug(&text("fact_id")), text("kind"))),
        "explore_failed" => fixed(format!("{} failed: {}", slug(subject), text("error"))),
        "explore_cancelled" => fixed(format!("{} was cancelled: {}", slug(subject), text("error"))),
        "explore_question" => fixed(format!("{} asked a question: {}", slug(subject), text("question"))),
        "review_proposed" => fixed(format!("The board went to review: {}", text("statement"))),
        other => fixed(other.replace('_', " ")),
    }
}

/// The whole board.
pub async fn board_snapshot(user: &CurrentUser, board_id: String) -> anyhow::Result<BoardSnapshot> {
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
            let mut intent = board_intent(i);
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
    Ok(BoardSnapshot {
        summary: label("").map(|l| l.summary.clone()).unwrap_or_default(),
        status: state.as_ref().map(|s| s.status.clone()).unwrap_or_else(|| "active".to_string()),
        explores_used: state.as_ref().map(|s| s.explores_used).unwrap_or(0),
        reasons_done: state.as_ref().map(|s| s.reasons_done).unwrap_or(0),
        stall_count: state.as_ref().map(|s| u32::from(s.stall_count)).unwrap_or(0),
        review_statement: summary["review_statement"].as_str().unwrap_or("").to_string(),
        review_from: strings(&summary["review_from"]),
        review_goals: review_goals(&summary),
        max_explores: summary["max_explores"].as_u64().unwrap_or(u64::from(BASE_EXPLORES)) as u32,
        explore_steps: summary["explore_steps"].as_u64().unwrap_or(u64::from(BASE_EXPLORE_STEPS)) as u32,
        facts,
        intents,
        events: events
            .into_iter()
            .map(|e| {
                let payload: serde_json::Value = serde_json::from_str(&e.payload_json).unwrap_or_default();
                let (summary, quote) = summarise(&e.event_type, &e.subject, &payload, &slug);
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
            internet_tools: board.internet_tools != 0,
        },
    })
}

pub async fn board_add_hint(user: &CurrentUser, board_id: String, text: String) -> anyhow::Result<()> {
    owned_board(user, &board_id).await?;
    let text = clip(&text);
    if text.is_empty() {
        anyhow::bail!("the hint is empty");
    }
    write_event(&board_id, "hint_added", &user.username, "", serde_json::json!({"text": text})).await
}

pub async fn board_reject_fact(user: &CurrentUser, board_id: String, fact_id: String,
                                     reason: String) -> anyhow::Result<()> {
    owned_board(user, &board_id).await?;
    if fact_id == "origin" || fact_id == "goal" {
        anyhow::bail!("the origin and the goal cannot be rejected");
    }
    write_event(&board_id, "fact_rejected", &user.username, &fact_id,
                serde_json::json!({"reason": clip(&reason)})).await
}

pub async fn board_set_paused(user: &CurrentUser, board_id: String, paused: bool) -> anyhow::Result<()> {
    owned_board(user, &board_id).await?;
    let kind = if paused { "pause_requested" } else { "resume_requested" };
    write_event(&board_id, kind, &user.username, "", serde_json::json!({})).await
}

/// Accept the proposed review, or reject it with a correction that becomes a fact.
pub async fn board_review(user: &CurrentUser, board_id: String, accept: bool,
                                correction: String) -> anyhow::Result<()> {
    owned_board(user, &board_id).await?;
    if accept {
        return write_event(&board_id, "review_accepted", &user.username, "", serde_json::json!({})).await;
    }
    let correction = clip(&correction);
    if correction.is_empty() {
        anyhow::bail!("a rejected review needs a correction");
    }
    // The correction names the facts of the rejected review, so the graph links it to them.
    let summary: serde_json::Value = get_global_client()
        .query("SELECT ?fields FROM board_state FINAL WHERE board_id = ?")
        .bind(&board_id)
        .fetch_all::<StateRow>()
        .await?
        .into_iter()
        .next()
        .and_then(|s| serde_json::from_str(&s.summary_json).ok())
        .unwrap_or_default();
    let fact_id = format!("c{}", &new_id()[..8]);
    write_fact(&board_id, &fact_id, "correction", &correction, &user.username).await?;
    write_event(&board_id, "review_rejected", &user.username, &fact_id,
                serde_json::json!({"correction": correction, "from": strings(&summary["review_from"])})).await
}

/// Drop a board: cancel its running explores, delete its explore sessions through the chat
/// deletion path, delete the rows of its six tables, and keep the tombstone of the definition.
pub async fn board_drop(user: &CurrentUser, board_id: String) -> anyhow::Result<()> {
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
    for table in ["board_events", "board_state", "board_intents", "board_facts", "board_fact_citations", "board_labels"] {
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
        let concluded = summarise("explore_concluded", "i1.2", &serde_json::json!({"fact_id": "f1.2", "kind": "sourced"}), &slug);
        assert_eq!(concluded, ("intent-find-raptor concluded in fact-raptor-capacity (sourced).".to_string(), String::new()));
        let rejected = summarise("fact_rejected", "f1.2", &serde_json::json!({"reason": "wrong year"}), &slug);
        assert_eq!(rejected, ("Rejected fact-raptor-capacity".to_string(), "wrong year".to_string()));
        let hint = summarise("hint_added", "", &serde_json::json!({"text": "look at May"}), &slug);
        assert_eq!(hint, ("Added a hint".to_string(), "look at May".to_string()));
        let correction = summarise("review_rejected", "c1", &serde_json::json!({"correction": "no"}), &slug);
        assert_eq!(correction.1, "no");
    }

    #[test]
    fn a_label_or_its_fallback_names_a_node() {
        let label = LabelRow { board_id: "b".into(), node_id: "f1.1".into(), slug: "fact-x".into(),
                               title: "X Title".into(), summary: "x summary".into() };
        assert_eq!(node_label("f1.1", "some text", Some(&label)), ("fact-x".into(), "X Title".into(), "x summary".into()));
        let empty = LabelRow { slug: String::new(), ..label };
        assert_eq!(node_label("f1.1", "one two three four five", Some(&empty)).0, "f1.1");
        assert_eq!(node_label("f1.1", "one two three four five", None).1, "one two three four");
    }

    #[test]
    fn a_summary_without_goal_reviews_reviews_the_first_goal() {
        let old = serde_json::json!({"review_from": ["f1.1"], "review_statement": "done"});
        assert_eq!(review_goals(&old), vec![BoardReviewGoal { goal: "goal".into(), from: vec!["f1.1".into()], statement: "done".into() }]);
        let new = serde_json::json!({"review_from": ["f1.1", "f1.2"], "review_goals": [
            {"goal": "goal", "from": ["f1.1"], "statement": "a"},
            {"goal": "goal-2", "from": ["f1.2"], "statement": "b"},
        ]});
        assert_eq!(review_goals(&new).iter().map(|g| g.goal.as_str()).collect::<Vec<_>>(), vec!["goal", "goal-2"]);
    }
}
