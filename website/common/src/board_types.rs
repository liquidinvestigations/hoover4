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

/// The most goals of one board.
pub const MAX_GOALS: usize = 6;

/// The fact id of the `index`-th goal (1-based) of a board.
///
/// **Mirrored in `main_services/processing/tasks/P_board/model.py`** (`goal_id_for`).
pub fn goal_id(index: usize) -> String {
    if index <= 1 { "goal".to_string() } else { format!("goal-{index}") }
}

/// One card of the board overview.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BoardListItem {
    pub board_id: String,
    pub title: String,
    pub status: String,
    pub goals: u32,
    pub facts_sourced: u32,
    pub facts_inferred: u32,
    pub facts_not_found: u32,
    pub running: u32,
    pub open: u32,
    pub explores_used: u32,
    pub max_explores: u32,
    /// Milliseconds since the epoch of the newest event.
    pub updated_ms: i64,
    /// The graph of the card's thumbnail: the facts with short texts and no citations, and
    /// the intents.
    pub graph: BoardGraphInput,
}

/// The create form. The explore model and the budgets are not inputs: the worker starts
/// every board at the same budget and grows it with the person's corrections and hints.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct BoardCreateRequest {
    pub title: String,
    /// One or more goals, at most `MAX_GOALS`. Empty entries are dropped.
    pub goals: Vec<String>,
    pub context: String,
    pub collections: Vec<String>,
    /// Whether the explores may use the internet tools. The owner can change it later.
    pub internet_tools: bool,
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
    pub max_parallel: u8,
    pub internet_tools: bool,
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
    /// Who rejected the fact, when, and why. Empty and 0 for a fact that stands.
    #[serde(default)]
    pub rejected_by: String,
    #[serde(default)]
    pub rejected_ms: i64,
    #[serde(default)]
    pub rejected_reason: String,
    /// For a correction: the facts of the rejected review that it corrects.
    #[serde(default)]
    pub corrects: Vec<String>,
    /// Who wrote the fact: `explore`, or the person for origin, goals and corrections.
    #[serde(default)]
    pub created_by: String,
    pub created_ms: i64,
    pub citations: Vec<BoardCitation>,
}

/// The proposed or accepted answer of one goal.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct BoardReviewGoal {
    pub goal: String,
    pub from: Vec<String>,
    pub statement: String,
}

/// What the graph of a board is drawn from. The explorer and the overview thumbnail build
/// the same graph from it.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct BoardGraphInput {
    pub status: String,
    pub facts: Vec<BoardFact>,
    pub intents: Vec<BoardIntent>,
    pub review_goals: Vec<BoardReviewGoal>,
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
    /// The review of each goal, proposed while the board waits for review and accepted
    /// when it is complete.
    pub review_goals: Vec<BoardReviewGoal>,
    /// The explore budget and the model steps of one explore, as the worker computes them.
    pub max_explores: u32,
    pub explore_steps: u32,
    pub facts: Vec<BoardFact>,
    pub intents: Vec<BoardIntent>,
    pub events: Vec<BoardEvent>,
}

impl BoardSnapshot {
    /// The goal facts, first goal first.
    pub fn goals(&self) -> Vec<&BoardFact> {
        let mut goals: Vec<&BoardFact> = self.facts.iter().filter(|f| f.kind == "goal").collect();
        goals.sort_by_key(|f| (f.fact_id != "goal", f.fact_id.len(), f.fact_id.clone()));
        goals
    }

    pub fn graph_input(&self) -> BoardGraphInput {
        BoardGraphInput {
            status: self.status.clone(),
            facts: self.facts.clone(),
            intents: self.intents.clone(),
            review_goals: self.review_goals.clone(),
        }
    }
}
