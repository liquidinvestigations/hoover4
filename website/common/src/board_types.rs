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

/// The board and the intent of a board explore session `board-<board_id>-<intent_id>`, or
/// `None` for another session. A board id is hex, so the first `-` after the prefix ends it.
///
/// **Mirrored in `main_services/processing/tasks/P_board/model.py`** (`session_id_for`).
pub fn board_of_session(session_id: &str) -> Option<(String, String)> {
    let rest = session_id.strip_prefix(BOARD_SESSION_PREFIX)?;
    let (board, intent) = rest.split_once('-')?;
    if board.is_empty() || intent.is_empty() || !board.chars().all(|c| c.is_ascii_hexdigit()) {
        return None;
    }
    Some((board.to_string(), intent.to_string()))
}

/// The fact id of the fact that the intent `intent_id` concludes in: `i3.2` gives `f3.2`.
///
/// **Mirrored in `main_services/processing/tasks/P_board/model.py`** (`fact_id_for`).
pub fn fact_id_for(intent_id: &str) -> String {
    format!("f{}", intent_id.strip_prefix('i').unwrap_or(intent_id))
}

/// The most goals of one board.
pub const MAX_GOALS: usize = 6;

/// The prefix of the intents that a person starts from an open question: `i0.N` for the
/// N-th question that the board explores. Reasons start at 1, so reason number 0 is free.
///
/// **Mirrored in `main_services/processing/tasks/P_board/model.py`** (`QUESTION_INTENT_PREFIX`).
pub const QUESTION_INTENT_PREFIX: &str = "i0.";

/// The open question that an intent follows: its fact and its 0-based position there.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct BoardQuestionRef {
    pub fact_id: String,
    pub index: u32,
}

/// The fact id of the `index`-th goal (1-based) of a board.
///
/// **Mirrored in `main_services/processing/tasks/P_board/model.py`** (`goal_id_for`).
pub fn goal_id(index: usize) -> String {
    if index <= 1 { "goal".to_string() } else { format!("goal-{index}") }
}

/// The fixed slug of an origin or goal fact, or `None` for a node with a generated label.
///
/// The origin (the background context of the board) is `background`. An address with its
/// storage id `origin` still resolves. The goal with the id `goal` is `goal-01`, and `goal-N` is `goal-`
/// followed by `N` with at least two digits. The slugs are computed here and not stored,
/// because the origin and the goals keep their own text as their label.
pub fn fixed_slug(fact_id: &str, kind: &str) -> Option<String> {
    match kind {
        "origin" => Some("background".to_string()),
        "goal" => {
            let number = if fact_id == "goal" {
                1
            } else {
                fact_id.strip_prefix("goal-").and_then(|n| n.parse::<u32>().ok()).unwrap_or(1)
            };
            Some(format!("goal-{number:02}"))
        }
        _ => None,
    }
}

/// The label that the website shows for a node that has no generated label yet: the storage
/// id as its slug, the first 4 words of its text as its title and the first 20 words as its
/// summary.
pub fn fallback_label(id: &str, text: &str) -> (String, String, String) {
    let words: Vec<&str> = text.split_whitespace().collect();
    let take = |n: usize| words.iter().take(n).copied().collect::<Vec<_>>().join(" ");
    (id.to_string(), take(4), take(20))
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
    /// The generated summary of the board, 10 to 15 words. Empty before its first label pass.
    #[serde(default)]
    pub summary: String,
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
    /// The display name and address key of the node. `fixed_slug` for the origin and the
    /// goals, the generated slug for a labelled node, else the storage id.
    #[serde(default)]
    pub slug: String,
    /// 3 to 4 words. Empty for the origin and the goals.
    #[serde(default)]
    pub title: String,
    /// 15 to 20 words. The full text for the origin and the goals.
    #[serde(default)]
    pub summary: String,
}

/// The proposed or accepted answer of one goal.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct BoardReviewGoal {
    pub goal: String,
    pub from: Vec<String>,
    pub statement: String,
    /// The assessment that proposed the answer. A decision names it, so a decision on an
    /// answer that a newer assessment replaced does nothing.
    #[serde(default)]
    pub reason_no: u32,
}

/// What the graph of a board is drawn from. The explorer and the overview thumbnail build
/// the same graph from it.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct BoardGraphInput {
    pub status: String,
    pub facts: Vec<BoardFact>,
    pub intents: Vec<BoardIntent>,
    /// The answers that wait for the person, and the answers that the person accepted.
    pub answers_proposed: Vec<BoardReviewGoal>,
    pub answers_accepted: Vec<BoardReviewGoal>,
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
    /// The display name and address key of the intent, else its storage id.
    #[serde(default)]
    pub slug: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub summary: String,
    /// The open question that a person asked to explore with this intent.
    #[serde(default)]
    pub asked: Option<BoardQuestionRef>,
}

/// One assessment of a board, for its details popup.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct BoardAssessment {
    pub reason_no: u32,
    pub created_ms: i64,
    /// `intents`, `review`, `noop` or `invalid`.
    pub outcome: String,
    pub model: String,
    pub latency_ms: u64,
    pub prompt_tokens: u64,
    pub completion_tokens: u64,
    /// The checks that changed the reply.
    pub problems: Vec<String>,
    /// The whole prompt. Empty when the assessment ran before the prompts were stored.
    pub prompt: String,
    /// The whole reply, or the first 6000 characters that the event holds for an older one.
    pub reply: String,
    pub error: String,
    /// The prompt and the whole reply are stored.
    pub stored: bool,
}

/// One event, with a sentence a person can read.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BoardEvent {
    pub event_id: String,
    pub event_type: String,
    pub actor: String,
    pub subject: String,
    /// The fixed text of the event, with node slugs in place of storage ids.
    pub summary: String,
    /// The text that a person wrote: a hint, a rejection reason or a correction. Empty for
    /// other events.
    #[serde(default)]
    pub quote: String,
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
    /// The statement of a stop without answers: the explore budget is used, or the work
    /// stalled.
    pub review_statement: String,
    /// The answers that wait for the person's decision, one for each goal at most.
    pub answers_proposed: Vec<BoardReviewGoal>,
    /// The answers that the person accepted. No later activity removes them.
    pub answers_accepted: Vec<BoardReviewGoal>,
    /// The explore budget and the model steps of one explore, as the worker computes them.
    pub max_explores: u32,
    pub explore_steps: u32,
    pub facts: Vec<BoardFact>,
    pub intents: Vec<BoardIntent>,
    pub events: Vec<BoardEvent>,
    /// The generated summary of the board. Empty before its first label pass.
    #[serde(default)]
    pub summary: String,
}

impl BoardSnapshot {
    /// The goal facts, first goal first.
    pub fn goals(&self) -> Vec<&BoardFact> {
        let mut goals: Vec<&BoardFact> = self.facts.iter().filter(|f| f.kind == "goal").collect();
        goals.sort_by_key(|f| (f.fact_id != "goal", f.fact_id.len(), f.fact_id.clone()));
        goals
    }

    /// The intent that follows open question `index` of fact `fact_id`, when a person asked
    /// to explore it.
    pub fn follower_of(&self, fact_id: &str, index: u32) -> Option<&BoardIntent> {
        self.intents
            .iter()
            .find(|i| i.asked.as_ref().is_some_and(|a| a.fact_id == fact_id && a.index == index))
    }

    /// The slug of a fact or intent id, or the id itself when the board has no such node.
    pub fn slug_of(&self, id: &str) -> String {
        self.facts
            .iter()
            .find(|f| f.fact_id == id)
            .map(|f| f.slug.clone())
            .or_else(|| self.intents.iter().find(|i| i.intent_id == id).map(|i| i.slug.clone()))
            .filter(|slug| !slug.is_empty())
            .unwrap_or_else(|| id.to_string())
    }

    /// The storage id of the node that an address names: by slug first, then by storage id,
    /// so a link written before the slugs keeps working.
    pub fn resolve_node(&self, key: &str) -> Option<String> {
        if key.is_empty() {
            return None;
        }
        let by_slug = self.facts.iter().find(|f| f.slug == key).map(|f| f.fact_id.clone())
            .or_else(|| self.intents.iter().find(|i| i.slug == key).map(|i| i.intent_id.clone()));
        by_slug.or_else(|| {
            self.facts.iter().find(|f| f.fact_id == key).map(|f| f.fact_id.clone())
                .or_else(|| self.intents.iter().find(|i| i.intent_id == key).map(|i| i.intent_id.clone()))
        })
    }

    pub fn graph_input(&self) -> BoardGraphInput {
        BoardGraphInput {
            status: self.status.clone(),
            facts: self.facts.clone(),
            intents: self.intents.clone(),
            answers_proposed: self.answers_proposed.clone(),
            answers_accepted: self.answers_accepted.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_origin_and_the_goals_have_fixed_slugs() {
        assert_eq!(fixed_slug("origin", "origin").as_deref(), Some("background"));
        assert_eq!(fixed_slug("goal", "goal").as_deref(), Some("goal-01"));
        assert_eq!(fixed_slug("goal-2", "goal").as_deref(), Some("goal-02"));
        assert_eq!(fixed_slug("goal-12", "goal").as_deref(), Some("goal-12"));
        assert_eq!(fixed_slug("f1.1", "sourced"), None);
    }

    fn snapshot() -> BoardSnapshot {
        let fact = |id: &str, slug: &str| BoardFact {
            fact_id: id.into(), kind: "sourced".into(), text: String::new(), intent_id: String::new(),
            session_id: String::new(), open_questions: vec![], problems: vec![], rejected: false,
            rejected_by: String::new(), rejected_ms: 0, rejected_reason: String::new(), corrects: vec![],
            created_by: String::new(), created_ms: 0, citations: vec![], slug: slug.into(),
            title: String::new(), summary: String::new(),
        };
        BoardSnapshot {
            board: BoardDefinition {
                board_id: "b".into(), owner: "o".into(), title: "t".into(), goal: "g".into(),
                context: String::new(), collections: vec![], llm_model: String::new(), max_parallel: 1,
                internet_tools: false, created_ms: 0,
            },
            status: "active".into(), explores_used: 0, reasons_done: 0, stall_count: 0,
            review_statement: String::new(), answers_proposed: vec![], answers_accepted: vec![],
            max_explores: 12, explore_steps: 60,
            // A slug that equals another node's storage id resolves to the node with the slug.
            facts: vec![fact("f1.1", "fact-raptor"), fact("f1.2", "f1.1")],
            intents: vec![], events: vec![], summary: String::new(),
        }
    }

    #[test]
    fn an_address_names_a_node_by_slug_first_and_then_by_storage_id() {
        let snap = snapshot();
        assert_eq!(snap.resolve_node("fact-raptor").as_deref(), Some("f1.1"));
        assert_eq!(snap.resolve_node("f1.1").as_deref(), Some("f1.2"));
        assert_eq!(snap.resolve_node("f1.2").as_deref(), Some("f1.2"));
        assert_eq!(snap.resolve_node("nothing"), None);
        assert_eq!(snap.resolve_node(""), None);
        assert_eq!(snap.slug_of("f1.1"), "fact-raptor");
        assert_eq!(snap.slug_of("i9.9"), "i9.9");
    }

    #[test]
    fn a_question_is_followed_by_the_intent_that_names_it() {
        let mut snap = snapshot();
        let intent = |id: &str, asked: Option<BoardQuestionRef>| BoardIntent {
            intent_id: id.into(), from_facts: vec!["f1.1".into()], objective: String::new(),
            brief: String::new(), state: "open".into(), attempts: 0, session_id: String::new(),
            fact_id: String::new(), question: String::new(), last_error: String::new(), created_ms: 0,
            slug: String::new(), title: String::new(), summary: String::new(), asked,
        };
        snap.intents = vec![
            intent("i1.1", None),
            intent("i0.1", Some(BoardQuestionRef { fact_id: "f1.1".into(), index: 1 })),
        ];
        assert_eq!(snap.follower_of("f1.1", 1).map(|i| i.intent_id.as_str()), Some("i0.1"));
        assert!(snap.follower_of("f1.1", 0).is_none());
        assert!(snap.follower_of("f1.2", 1).is_none());
    }

    #[test]
    fn a_board_session_names_its_board_and_intent() {
        assert_eq!(
            board_of_session("board-0a1b2c-i1.2"),
            Some(("0a1b2c".to_string(), "i1.2".to_string()))
        );
        assert_eq!(board_of_session("board-0a1b2c-i0.7").map(|(_, i)| fact_id_for(&i)).as_deref(), Some("f0.7"));
        assert_eq!(board_of_session("4f2a9e"), None);
        assert_eq!(board_of_session("board-0a1b2c"), None);
        assert_eq!(board_of_session("board-xyz-i1.1"), None);
    }

    #[test]
    fn a_node_without_a_label_shows_its_id_and_the_first_words() {
        let text = (1..=30).map(|i| format!("w{i}")).collect::<Vec<_>>().join(" ");
        let (slug, title, summary) = fallback_label("f1.1", &text);
        assert_eq!(slug, "f1.1");
        assert_eq!(title, "w1 w2 w3 w4");
        assert_eq!(summary.split(' ').count(), 20);
    }
}
