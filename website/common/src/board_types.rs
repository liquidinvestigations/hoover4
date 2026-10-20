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
/// `None` for another session. A board id is hex, so the first `-` after the prefix ends it,
/// and the hyphens of a slug intent id stay in the intent id.
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

/// The most goals of one board.
pub const MAX_GOALS: usize = 6;

/// The most explores of one board, whatever its budget.
/// **Mirrored in `main_services/processing/tasks/P_board/model.py`** (`EXPLORE_LIMIT`).
pub const EXPLORE_LIMIT: u32 = 300;

/// The `answer_kind` of a proposed answer that a sourced fact of its own supports.
pub const SUPPORTED: &str = "supported";
/// The `answer_kind` of a proposed answer whose facts are all not-found facts.
pub const NOT_ESTABLISHED: &str = "not_established";
/// The fixed statement of a `not_established` answer.
/// **Mirrored in `main_services/processing/tasks/P_board/model.py`** (`NOT_ESTABLISHED_STATEMENT`).
pub const NOT_ESTABLISHED_STATEMENT: &str = "The cited records do not establish an answer to this goal.";

/// The open question that an intent follows: its fact and its 0-based position there.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct BoardQuestionRef {
    pub fact_id: String,
    pub index: u32,
}

/// The 1-based slot of a goal id in either form: `goal` is 1, `goal-2` and `goal-02` are 2.
/// 0 for another id.
///
/// **Mirrored in `main_services/processing/tasks/P_board/model.py`** (`goal_slot`).
pub fn goal_slot(fact_id: &str) -> u32 {
    if fact_id == "goal" {
        return 1;
    }
    fact_id
        .strip_prefix("goal-")
        .filter(|n| !n.is_empty() && n.bytes().all(|b| b.is_ascii_digit()))
        .and_then(|n| n.parse::<u32>().ok())
        .unwrap_or(0)
}

/// The key of open question `index` (0-based) of a fact: `<fact_id>#<1-based index>`. The
/// fact id is opaque, so a hyphen or a dot in it is part of the id.
///
/// **Mirrored in `main_services/processing/tasks/P_board/model.py`** (`question_key`).
pub fn question_key(fact_id: &str, index: u32) -> String {
    format!("{fact_id}#{}", index + 1)
}

/// The fixed slug of a background or goal fact, or `None` for a node with a generated label.
///
/// The background context of the board is `background`, whether its id is the legacy
/// `origin` or `background`. An address with the id `origin` still resolves. A goal is
/// `goal-` followed by its slot with at least two digits: `goal` is `goal-01`, `goal-2` and
/// `goal-02` are `goal-02`. The background and the goals keep their own text as their label.
pub fn fixed_slug(fact_id: &str, kind: &str) -> Option<String> {
    match kind {
        "origin" => Some("background".to_string()),
        "goal" => Some(format!("goal-{:02}", goal_slot(fact_id).max(1))),
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
    /// The assessment that proposed the answer, for display and for an answer without a
    /// proposal id.
    #[serde(default)]
    pub reason_no: u32,
    /// The identity of the proposal. A decision names it, so a decision on an answer that a
    /// newer assessment replaced does nothing. Empty for an answer proposed before it existed.
    #[serde(default)]
    pub proposal_id: String,
    /// `supported` or `not_established`. Empty for an older answer.
    #[serde(default)]
    pub answer_kind: String,
    /// The model's text of a `not_established` answer. The statement stays the fixed text.
    #[serde(default)]
    pub commentary: String,
    /// Milliseconds since the epoch of the assessment that proposed the answer. 0 when the
    /// state summary was written before this field.
    #[serde(default)]
    pub proposed_ms: i64,
    /// The numbers of the later assessments that dropped an answer for this goal while this
    /// proposal waited. Empty for an accepted answer.
    #[serde(default)]
    pub later_drops: Vec<u32>,
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
    /// The goals that the person finished without an answer.
    #[serde(default)]
    pub not_answered: Vec<String>,
    /// The findings that arrived after the board entered review or completion, which no
    /// acceptance covered. They change no accepted answer.
    #[serde(default)]
    pub unreviewed: Vec<String>,
}

impl BoardGraphInput {
    /// The nodes that a label of this board can name (`board_text::name_nodes`).
    pub fn link_nodes(&self) -> Vec<crate::board_text::LinkNode> {
        node_list(&self.facts, &self.intents)
    }
}

fn node_list(facts: &[BoardFact], intents: &[BoardIntent]) -> Vec<crate::board_text::LinkNode> {
    let fact = facts.iter().map(|f| (&f.fact_id, &f.slug, &f.title));
    let intent = intents.iter().map(|i| (&i.intent_id, &i.slug, &i.title));
    fact.chain(intent)
        .map(|(id, slug, title)| crate::board_text::LinkNode { id: id.clone(), slug: slug.clone(), title: title.clone() })
        .collect()
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
    /// The question keys (`question_key`) that this intent explores.
    #[serde(default)]
    pub questions: Vec<String>,
    /// `assessment` or `person_question`. Empty for an intent of an older board summary.
    #[serde(default)]
    pub origin: String,
    /// A question that the person wrote, with no open question of a fact behind it.
    #[serde(default)]
    pub own: bool,
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
    /// The identity of the current review or completion: the event that caused it. A review
    /// decision and a reopening name it. Empty on an active or paused board.
    #[serde(default)]
    pub review_id: String,
    /// Why the board is in review: `answers`, `budget`, `stalled_no_direction`,
    /// `stalled_invalid` or `model_unavailable`. An older review has `stalled` for every cause
    /// without progress. Empty otherwise. Mirrors `STALL_REVIEW_REASONS` in
    /// `main_services/processing/tasks/P_board/model.py`.
    #[serde(default)]
    pub review_reason: String,
    /// Whether the board used `EXPLORE_LIMIT` explores. Such a board starts no more work.
    #[serde(default)]
    pub limit_reached: bool,
    /// The explores that a reopening adds now, when the board can reopen: it is in review or
    /// complete, a goal has no accepted answer, the limit is not reached, and this review
    /// has not reopened. 0 reopens with the remaining budget. `None` when it cannot reopen.
    #[serde(default)]
    pub reopen_grant: Option<u32>,
    /// A final assessment of the used budget runs.
    #[serde(default)]
    pub final_running: bool,
    /// The goals that the person finished without an answer. A hint or a reopening opens
    /// them again.
    #[serde(default)]
    pub not_answered: Vec<String>,
    /// The findings concluded after the board entered review or completion, which no later
    /// acceptance covered (`fold.Folded.unreviewed` in the worker). They change no accepted
    /// answer, and the board does not reopen for them.
    #[serde(default)]
    pub unreviewed: Vec<String>,
    /// The last event sequence number of the fold that gave the proposals, the review and
    /// [`Self::unreviewed`]. A decision names it as `seen_seq`. 0 for a state summary that
    /// was written before this field.
    #[serde(default)]
    pub snapshot_seq: u64,
}

impl BoardSnapshot {
    /// The goal facts, in slot order.
    pub fn goals(&self) -> Vec<&BoardFact> {
        let mut goals: Vec<&BoardFact> = self.facts.iter().filter(|f| f.kind == "goal").collect();
        goals.sort_by_key(|f| (goal_slot(&f.fact_id), f.fact_id.clone()));
        goals
    }

    /// The intent that explores open question `index` of fact `fact_id`. The intent that
    /// binds its key and did not fail comes first, newest first, then a failed one, then an
    /// intent of an older person action that names the question.
    pub fn follower_of(&self, fact_id: &str, index: u32) -> Option<&BoardIntent> {
        let key = question_key(fact_id, index);
        let bound: Vec<&BoardIntent> = self.intents.iter().filter(|i| i.questions.contains(&key)).collect();
        bound
            .iter()
            .rev()
            .find(|i| i.state != "failed")
            .or_else(|| bound.last())
            .copied()
            .or_else(|| {
                self.intents
                    .iter()
                    .find(|i| i.asked.as_ref().is_some_and(|a| a.fact_id == fact_id && a.index == index))
            })
    }

    /// The questions that the person wrote about fact `fact_id`, as intents.
    pub fn own_questions_of(&self, fact_id: &str) -> Vec<&BoardIntent> {
        self.intents.iter().filter(|i| i.own && i.from_facts.first().is_some_and(|f| f == fact_id)).collect()
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

    /// The nodes that a text of this board can name (`board_text::link_nodes`).
    pub fn link_nodes(&self) -> Vec<crate::board_text::LinkNode> {
        node_list(&self.facts, &self.intents)
    }

    pub fn graph_input(&self) -> BoardGraphInput {
        BoardGraphInput {
            status: self.status.clone(),
            facts: self.facts.clone(),
            intents: self.intents.clone(),
            answers_proposed: self.answers_proposed.clone(),
            answers_accepted: self.answers_accepted.clone(),
            not_answered: self.not_answered.clone(),
            unreviewed: self.unreviewed.clone(),
        }
    }
}

/// One action of a person on a board. Each is one command of the board's command writer
/// (`main_services/processing/tasks/P_board/commands.py`). The website maps each to its
/// command kind, so no action can name a command of the worker.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum BoardAction {
    AddHint { text: String },
    RejectFact { fact_id: String, reason: String },
    SetPaused { paused: bool },
    SetInternetTools { on: bool },
    /// Finish the review `review_id`, or continue it with a correction. `seen_seq` and
    /// `seen_unreviewed` are the [`BoardSnapshot::snapshot_seq`] and the unreviewed findings
    /// of the shown snapshot. An acceptance covers only those findings, and an acceptance
    /// without `seen_seq` covers none.
    Review {
        review_id: String,
        accept: bool,
        correction: String,
        #[serde(default)]
        seen_seq: Option<u64>,
        #[serde(default)]
        seen_unreviewed: Vec<String>,
    },
    /// Accept or reject the proposed answer `proposal_id` of goal `goal`. The coverage
    /// fields are those of [`BoardAction::Review`], for the findings of this goal.
    Answer {
        goal: String,
        proposal_id: String,
        accept: bool,
        correction: String,
        #[serde(default)]
        seen_seq: Option<u64>,
        #[serde(default)]
        seen_unreviewed: Vec<String>,
    },
    AddGoal { text: String },
    /// Explore open question `index` of a fact, or the person's own `question` about it.
    /// Exactly one of the two is set.
    ExploreQuestion { fact_id: String, index: Option<u32>, question: String },
    /// Reopen the board in review or completion `expected_id`.
    Reopen { expected_id: String },
}

/// The state of one submitted command.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct BoardCommandReceipt {
    pub request_id: String,
    /// `pending`, `committed` or `rejected`.
    pub state: String,
    /// Why a rejected command was refused.
    #[serde(default)]
    pub error: String,
    /// The intent that a question opened.
    #[serde(default)]
    pub intent_id: String,
    /// The explores that a reopening added.
    #[serde(default)]
    pub grant: Option<u32>,
}

impl BoardCommandReceipt {
    pub fn is_done(&self) -> bool {
        self.state == "committed" || self.state == "rejected"
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
        assert_eq!(fixed_slug("goal-03", "goal").as_deref(), Some("goal-03"));
        assert_eq!(fixed_slug("background", "origin").as_deref(), Some("background"));
        assert_eq!(fixed_slug("f1.1", "sourced"), None);
    }

    #[test]
    fn a_goal_slot_reads_both_forms_and_a_question_key_keeps_the_fact_id() {
        assert_eq!((goal_slot("goal"), goal_slot("goal-2"), goal_slot("goal-02"), goal_slot("goal-x")), (1, 2, 2, 0));
        assert_eq!(goal_slot("fact-goal-2"), 0);
        assert_eq!(question_key("f1.2", 0), "f1.2#1");
        assert_eq!(question_key("fact-contract-payment-2", 2), "fact-contract-payment-2#3");
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
            intents: vec![], events: vec![], summary: String::new(), review_id: String::new(),
            review_reason: String::new(), limit_reached: false, reopen_grant: None, final_running: false,
            not_answered: vec![], unreviewed: vec![], snapshot_seq: 0,
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
        let intent = |id: &str, asked: Option<BoardQuestionRef>, questions: &[&str], state: &str| BoardIntent {
            intent_id: id.into(), from_facts: vec!["f1.1".into()], objective: String::new(),
            brief: String::new(), state: state.into(), attempts: 0, session_id: String::new(),
            fact_id: String::new(), question: String::new(), last_error: String::new(), created_ms: 0,
            slug: String::new(), title: String::new(), summary: String::new(), asked,
            questions: questions.iter().map(|q| q.to_string()).collect(), origin: String::new(), own: false,
        };
        snap.intents = vec![
            intent("i1.1", None, &[], "open"),
            intent("i0.1", Some(BoardQuestionRef { fact_id: "f1.1".into(), index: 1 }), &[], "open"),
        ];
        assert_eq!(snap.follower_of("f1.1", 1).map(|i| i.intent_id.as_str()), Some("i0.1"));
        assert!(snap.follower_of("f1.1", 0).is_none());
        assert!(snap.follower_of("f1.2", 1).is_none());
        // A binding names the intent, and a replacement comes before the failed intent.
        snap.intents.push(intent("intent-who-signed", None, &["f1.1#1"], "failed"));
        assert_eq!(snap.follower_of("f1.1", 0).map(|i| i.intent_id.as_str()), Some("intent-who-signed"));
        snap.intents.push(intent("intent-who-signed-2", None, &["f1.1#1"], "open"));
        assert_eq!(snap.follower_of("f1.1", 0).map(|i| i.intent_id.as_str()), Some("intent-who-signed-2"));
    }

    #[test]
    fn goals_are_in_slot_order_in_both_forms() {
        let mut snap = snapshot();
        let base = snap.facts[0].clone();
        let goal = |id: &str| BoardFact { fact_id: id.into(), kind: "goal".into(), ..base.clone() };
        snap.facts = vec![goal("goal-10"), goal("goal-02"), goal("goal")];
        let order: Vec<&str> = snap.goals().iter().map(|g| g.fact_id.as_str()).collect();
        assert_eq!(order, vec!["goal", "goal-02", "goal-10"]);
    }

    #[test]
    fn a_board_session_names_its_board_and_intent() {
        assert_eq!(
            board_of_session("board-0a1b2c-i1.2"),
            Some(("0a1b2c".to_string(), "i1.2".to_string()))
        );
        assert_eq!(
            board_of_session("board-0a1b2c-intent-check-contracts-2"),
            Some(("0a1b2c".to_string(), "intent-check-contracts-2".to_string()))
        );
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
