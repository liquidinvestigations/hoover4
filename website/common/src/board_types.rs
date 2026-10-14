//! Types of the investigation board pages and their server functions.
//!
//! A board is a long-running investigation: a goal, board facts, intents that agents
//! explore, and the events of every action. The worker folds the events into the state that
//! these types show. `docs/architecture/Boards.md` describes the whole system.

use serde::{Deserialize, Serialize};

/// The chat session id prefix of every explore turn.
///
/// **Mirrored in `main_services/processing/tasks/P_board/model.py`** (`SESSION_PREFIX`). The
/// chat history leaves these sessions out, and a person cannot post into one.
pub const BOARD_SESSION_PREFIX: &str = "board-";

/// Whether a chat session belongs to a board.
pub fn is_board_session(session_id: &str) -> bool {
    session_id.starts_with(BOARD_SESSION_PREFIX)
}

/// One row of the board list.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BoardListItem {
    pub board_id: String,
    pub title: String,
    pub status: String,
    pub facts_sourced: u32,
    pub facts_inferred: u32,
    pub facts_not_found: u32,
    pub running: u32,
    pub open: u32,
    pub explores_used: u32,
    pub max_explores: u32,
    /// Milliseconds since the epoch of the newest event.
    pub updated_ms: i64,
}

/// The create form.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct BoardCreateRequest {
    pub title: String,
    pub goal: String,
    pub context: String,
    pub collections: Vec<String>,
    /// The model of the explore turns. Empty for the model of the internal search chat
    /// profile. Reasons always use the summarisation model.
    pub llm_model: String,
    pub max_explores: u16,
    pub max_parallel: u8,
    pub explore_step_budget: u16,
    /// First hints, one per entry. Empty entries are dropped.
    pub hints: Vec<String>,
}

/// The definition of a board, as created.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BoardDefinition {
    pub board_id: String,
    pub owner: String,
    pub title: String,
    pub goal: String,
    pub context: String,
    pub collections: Vec<String>,
    pub llm_model: String,
    pub max_explores: u16,
    pub max_parallel: u8,
    pub explore_step_budget: u16,
    pub created_ms: i64,
}

/// One resolved citation of a board fact.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BoardCitation {
    /// The session handle without brackets, for example `D1`.
    pub label: String,
    pub collection_dataset: String,
    pub collectionname: String,
    pub file_hash: String,
    pub path: String,
    pub page_id: u32,
    pub quote: String,
    pub quote_verified: bool,
}

/// One board fact.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BoardFact {
    pub fact_id: String,
    /// `origin`, `goal`, `sourced`, `inferred`, `not_found` or `correction`.
    pub kind: String,
    pub text: String,
    pub intent_id: String,
    /// The explore chat session, empty for origin, goal and corrections.
    pub session_id: String,
    pub open_questions: Vec<String>,
    pub problems: Vec<String>,
    pub rejected: bool,
    pub created_ms: i64,
    pub citations: Vec<BoardCitation>,
}

/// One intent.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BoardIntent {
    pub intent_id: String,
    pub from_facts: Vec<String>,
    pub objective: String,
    pub brief: String,
    /// `open`, `running`, `concluded`, `failed`, `question` or `cancelled`.
    pub state: String,
    pub attempts: u32,
    pub session_id: String,
    pub fact_id: String,
    pub question: String,
    pub last_error: String,
    pub created_ms: i64,
}

/// One event, with a sentence a person can read.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BoardEvent {
    pub event_id: String,
    pub event_type: String,
    pub actor: String,
    pub subject: String,
    pub summary: String,
    pub created_ms: i64,
}

/// The whole board, as the explorer shows it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BoardSnapshot {
    pub board: BoardDefinition,
    /// The status that the worker last wrote. `active` before its first pass.
    pub status: String,
    pub explores_used: u32,
    pub reasons_done: u32,
    pub stall_count: u32,
    pub review_statement: String,
    pub review_from: Vec<String>,
    pub facts: Vec<BoardFact>,
    pub intents: Vec<BoardIntent>,
    pub events: Vec<BoardEvent>,
}
