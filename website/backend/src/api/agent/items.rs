//! The routes `chats/list`, `chats/read`, `boards/list` and `boards/read`: the chats and the
//! boards that the caller reads under the group rule (`auth::item_access`).
//!
//! A run reads only the items of the group of its chat (`item_access::run_group`), so a
//! member who sends a turn in a chat of another creator gets no item of another group.
//! The lists hold only the items of the groups of the caller. A read of an item of another
//! group is 403 `permission_denied`, and a read of an item that does not exist is 404. The
//! lists leave out the explore chats of the boards.
//!
//! The texts of a read item can hold the citation handles of that item, such as `[D1]`.
//! They name sources of that item only, so the routes write them as labels, `(D1)`
//! (`common::chat_items::handles_as_labels`), and list each one in `citations`.

use common::chat_items::{board_path, chat_path, extract_item_refs, handles_as_labels, text_handles, KIND_BOARD};
use common::chat_pages::extract_page_refs;
use common::chat_types::{ChatDocRef, ChatMessageItem, ChatRole, WorkspaceVersion};
use common::links::RichText;

use super::*;
use crate::auth::item_access::{self, ItemLookup};
use crate::db_chat;

/// Items on one page of a list.
const LIST_PAGE_SIZE: usize = 20;
/// The most chats that a list reads before its text filter.
const LIST_SCAN_LIMIT: u32 = 1000;
/// Turns on one page of a read chat.
const TURN_PAGE_SIZE: usize = 5;
/// The longest answer of a read chat, in characters.
const MAX_ANSWER_CHARS: usize = 8000;
/// The most findings that a read board returns.
const MAX_FINDINGS: usize = 60;

/// The refusal of an item outside the group of the run.
fn other_group(what: &str) -> AgentError {
    AgentError::permission_denied(format!("the {what} belongs to another group than the chat of this run"))
}

fn refusal<T>(lookup: ItemLookup<T>, what: &str) -> Result<T, AgentError> {
    match lookup {
        ItemLookup::Readable(item) => Ok(item),
        ItemLookup::Missing => Err(AgentError::not_found(format!("no {what} has this id"))),
        ItemLookup::Unreadable => Err(AgentError::permission_denied(format!(
            "the {what} belongs to a group of which the user is not a member"
        ))),
    }
}

/// The words of a list filter, in lower case.
fn filter_words(query: &str) -> Vec<String> {
    query.to_lowercase().split_whitespace().map(str::to_string).collect()
}

/// True when `text` holds every word of `words`, in any case.
fn holds_words(text: &str, words: &[String]) -> bool {
    let text = text.to_lowercase();
    words.iter().all(|word| text.contains(word.as_str()))
}

/// One page of `items` and the number of the next page.
fn page_of<T>(items: Vec<T>, page: u32, size: usize) -> (Vec<T>, Option<u32>) {
    let start = (page as usize).saturating_mul(size);
    let next = (items.len() > start + size).then_some(page + 1);
    (items.into_iter().skip(start).take(size).collect(), next)
}

fn validate_request(query: &str, ids: &[String]) -> Result<(), AgentError> {
    validate_plain_text(query)?;
    for id in ids {
        validate_plain_text(id)?;
    }
    if ids.len() > 50 {
        return Err(AgentError::invalid_argument("give at most 50 ids"));
    }
    Ok(())
}

fn rfc3339_ms(ms: i64) -> String {
    time::OffsetDateTime::from_unix_timestamp_nanos(i128::from(ms) * 1_000_000)
        .ok()
        .and_then(|t| t.format(&time::format_description::well_known::Rfc3339).ok())
        .unwrap_or_default()
}

// ===================================================================================
// chats/list, chats/read
// ===================================================================================

pub async fn chats_list(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<ItemsListRequest>,
) -> AgentResult<ChatsListResponse> {
    let group = item_access::run_group(&user, &headers).await.map_err(AgentError::from_anyhow)?;
    Deadline::start().run(chats_list_body(&user, &group, body)).await.map(Json)
}

async fn chats_list_body(user: &CurrentUser, run_group: &str, body: ItemsListRequest) -> Result<ChatsListResponse, AgentError> {
    validate_request(&body.query, &body.ids)?;
    let groups = item_access::member_groups(user).await.map_err(AgentError::from_anyhow)?;
    let sessions = if body.ids.is_empty() {
        db_chat::list_sessions_of_groups(&groups, LIST_SCAN_LIMIT, false).await
    } else {
        db_chat::sessions_of_groups_by_ids(&groups, &body.ids).await
    }
    .map_err(AgentError::from_anyhow)?;
    let words = filter_words(&body.query);
    let chats: Vec<AgentChatItem> = sessions
        .into_iter()
        .filter(|s| !s.session_id.starts_with(common::board_types::BOARD_SESSION_PREFIX))
        .filter(|s| item_access::in_run_group(run_group, &s.owner_group))
        .filter(|s| holds_words(&format!("{} {}", s.title, s.summary), &words))
        .map(|s| AgentChatItem {
            link: chat_path(&s.session_id),
            session_id: s.session_id,
            title: s.title,
            summary: s.summary,
            group: s.owner_group,
            creator: s.owner,
            updated_at: s.updated_at,
            message_count: s.message_count,
        })
        .collect();
    let total = chats.len() as u32;
    let (chats, next_page) = page_of(chats, body.page, LIST_PAGE_SIZE);
    Ok(ChatsListResponse { chats, total, page: body.page, next_page })
}

pub async fn chats_read(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<ChatsReadRequest>,
) -> AgentResult<ChatsReadResponse> {
    let group = item_access::run_group(&user, &headers).await.map_err(AgentError::from_anyhow)?;
    Deadline::start().run(chats_read_body(&user, &group, body)).await.map(Json)
}

/// A chat by id, with the group rule of the agent routes.
async fn chat_lookup(user: &CurrentUser, session_id: &str) -> anyhow::Result<ItemLookup<db_chat::ChatSessionRow>> {
    let Some(row) = db_chat::get_session_by_id(session_id).await? else {
        return Ok(ItemLookup::Missing);
    };
    Ok(if item_access::access(user, &row.owner_group, &row.username).await?.read {
        ItemLookup::Readable(row)
    } else {
        ItemLookup::Unreadable
    })
}

async fn chats_read_body(user: &CurrentUser, run_group: &str, body: ChatsReadRequest) -> Result<ChatsReadResponse, AgentError> {
    validate_plain_text(&body.session_id)?;
    let row = refusal(chat_lookup(user, body.session_id.trim()).await.map_err(AgentError::from_anyhow)?, "chat")?;
    if !item_access::in_run_group(run_group, &row.owner_group) {
        return Err(other_group("chat"));
    }
    let owner = row.username.as_str();
    let messages = db_chat::list_messages(owner, &row.session_id).await.map_err(AgentError::from_anyhow)?;
    let outputs = db_chat::session_citation_outputs(owner, &row.session_id).await.map_err(AgentError::from_anyhow)?;
    let mut documents = common::chat_types::citation_refs(outputs.iter().map(String::as_str));
    for message in messages.iter().filter(|m| m.tool_name == "cite_documents") {
        for doc in message.parsed_doc_refs() {
            if !doc.handle.is_empty() && !documents.iter().any(|d| d.handle == doc.handle) {
                documents.push(doc);
            }
        }
    }
    let mut report_refs = Vec::new();
    for report in messages.iter().filter_map(ChatMessageItem::report_ref) {
        if !report_refs.contains(&report) {
            report_refs.push(report);
        }
    }
    let reports = db_chat::workspace::versions(owner, &row.session_id, &report_refs)
        .await
        .map_err(AgentError::from_anyhow)?;
    let turns = chat_turns(&messages, &reports, &documents);
    let turn_count = turns.len() as u32;
    let (turns, next_page) = page_of(turns, body.page, TURN_PAGE_SIZE);
    Ok(ChatsReadResponse {
        link: chat_path(&row.session_id),
        session_id: row.session_id,
        title: row.title,
        summary: row.summary,
        group: row.owner_group,
        turn_count,
        turns,
        page: body.page,
        next_page,
    })
}

/// The turns of a chat: each question of the person with the final answer of its turn, and
/// the sources of the handles of the answer. An answer that shows a report has the text of
/// that report version.
pub fn chat_turns(messages: &[ChatMessageItem], reports: &[WorkspaceVersion], documents: &[ChatDocRef]) -> Vec<AgentChatTurn> {
    let pages = common::chat_pages::merge_page_refs(
        messages.iter().flat_map(|message| match message.tool_name.as_str() {
            "cite_pages" => extract_page_refs(&message.tool_output),
            "execute" => common::chat_types::code_citation_outputs(&message.tool_output, "cite_pages")
                .iter().flat_map(|output| extract_page_refs(output)).collect(),
            _ => Vec::new(),
        }).collect(),
    );
    let items = common::chat_items::merge_item_refs(
        messages
            .iter()
            .filter(|m| m.tool_name == "cite_chats_and_boards")
            .flat_map(|m| extract_item_refs(&m.tool_output))
            .collect(),
    );
    let users: Vec<usize> = messages.iter().enumerate().filter(|(_, m)| m.role == ChatRole::User).map(|(i, _)| i).collect();
    let mut turns = Vec::new();
    for (n, &start) in users.iter().enumerate() {
        let end = users.get(n + 1).copied().unwrap_or(messages.len());
        let question = &messages[start];
        let answer = messages[start + 1..end]
            .iter()
            .rev()
            .find(|m| m.role == ChatRole::Assistant && !m.content.trim().is_empty());
        let text = answer
            .map(|m| {
                m.report_ref()
                    .and_then(|r| reports.iter().find(|v| v.name == r.name && v.version == r.version))
                    .map(|v| v.content.clone())
                    .unwrap_or_else(|| m.content.clone())
            })
            .unwrap_or_default();
        let citations = text_handles(&text)
            .into_iter()
            .filter_map(|handle| {
                let label = handle.trim_start_matches('[').trim_end_matches(']').to_string();
                if let Some(doc) = documents.iter().find(|d| d.handle == handle) {
                    return Some(AgentItemCitation {
                        label,
                        kind: "document".into(),
                        title: doc.path.clone(),
                        collection: doc.collectionname.clone(),
                        file_hash: doc.file_hash.clone(),
                        quote: doc.quote.clone(),
                        link: String::new(),
                    });
                }
                if let Some(page) = pages.iter().find(|p| p.handle == handle) {
                    return Some(AgentItemCitation {
                        label,
                        kind: "web".into(),
                        title: page.title.clone(),
                        quote: page.quotes.first().cloned().unwrap_or_default(),
                        link: page.url.clone(),
                        ..Default::default()
                    });
                }
                items.iter().find(|i| i.handle == handle).map(|item| AgentItemCitation {
                    label,
                    kind: item.kind.clone(),
                    title: item.title.clone(),
                    link: item.path(),
                    ..Default::default()
                })
            })
            .collect();
        let labelled = handles_as_labels(&text);
        let truncated = labelled.chars().count() > MAX_ANSWER_CHARS;
        turns.push(AgentChatTurn {
            seq: question.seq,
            created_at: question.created_at.clone(),
            question: RichText { text: question.content.clone(), references: question.references.clone() }.display_text(),
            answer: if truncated { labelled.chars().take(MAX_ANSWER_CHARS).collect() } else { labelled },
            citations,
            truncated,
        });
    }
    turns
}

// ===================================================================================
// boards/list, boards/read
// ===================================================================================

pub async fn boards_list(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<ItemsListRequest>,
) -> AgentResult<BoardsListResponse> {
    let group = item_access::run_group(&user, &headers).await.map_err(AgentError::from_anyhow)?;
    Deadline::start().run(boards_list_body(&user, &group, body)).await.map(Json)
}

async fn boards_list_body(user: &CurrentUser, run_group: &str, body: ItemsListRequest) -> Result<BoardsListResponse, AgentError> {
    validate_request(&body.query, &body.ids)?;
    let ids = (!body.ids.is_empty()).then_some(body.ids.as_slice());
    let boards = crate::api::boards::list_boards_with(user, ids).await.map_err(AgentError::from_anyhow)?;
    let words = filter_words(&body.query);
    let mut boards: Vec<AgentBoardItem> = boards
        .into_iter()
        .map(|b| {
            let goals: Vec<String> = b.graph.facts.iter().filter(|f| f.kind == "goal").map(|f| f.text.clone()).collect();
            AgentBoardItem {
                link: board_path(&b.board_id, ""),
                updated_at: rfc3339_ms(b.updated_ms),
                board_id: b.board_id,
                title: b.title,
                status: b.status,
                summary: b.summary,
                goals,
                group: b.owner_group,
            }
        })
        .filter(|b| item_access::in_run_group(run_group, &b.group))
        .filter(|b| holds_words(&format!("{} {} {}", b.title, b.summary, b.goals.join(" ")), &words))
        .collect();
    boards.sort_by(|a, b| b.updated_at.cmp(&a.updated_at));
    let total = boards.len() as u32;
    let (boards, next_page) = page_of(boards, body.page, LIST_PAGE_SIZE);
    Ok(BoardsListResponse { boards, total, page: body.page, next_page })
}

pub async fn boards_read(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<BoardsReadRequest>,
) -> AgentResult<BoardsReadResponse> {
    let group = item_access::run_group(&user, &headers).await.map_err(AgentError::from_anyhow)?;
    Deadline::start().run(boards_read_body(&user, &group, body)).await.map(Json)
}

async fn boards_read_body(user: &CurrentUser, run_group: &str, body: BoardsReadRequest) -> Result<BoardsReadResponse, AgentError> {
    validate_plain_text(&body.board_id)?;
    validate_plain_text(&body.node)?;
    let lookup = crate::api::boards::board_for_agent(user, body.board_id.trim()).await.map_err(AgentError::from_anyhow)?;
    let snapshot = refusal(lookup, KIND_BOARD)?;
    if !item_access::in_run_group(run_group, &snapshot.board.owner_group) {
        return Err(other_group(KIND_BOARD));
    }
    board_read(&snapshot, body.node.trim())
}

fn fact_node(board_id: &str, fact: &common::board_types::BoardFact, with_citations: bool) -> AgentBoardNode {
    let node = if fact.slug.is_empty() { fact.fact_id.clone() } else { fact.slug.clone() };
    AgentBoardNode {
        link: board_path(board_id, &node),
        node,
        kind: fact.kind.clone(),
        title: if fact.title.is_empty() { fact.summary.clone() } else { fact.title.clone() },
        text: handles_as_labels(&fact.text),
        open_questions: if with_citations { fact.open_questions.clone() } else { Vec::new() },
        citations: if with_citations {
            fact.citations
                .iter()
                .map(|c| AgentItemCitation {
                    label: c.label.clone(),
                    kind: "document".into(),
                    title: c.path.clone(),
                    collection: c.collectionname.clone(),
                    file_hash: c.file_hash.clone(),
                    quote: c.quote.clone(),
                    link: String::new(),
                })
                .collect()
        } else {
            Vec::new()
        },
    }
}

/// The agent view of one board. `node` names a fact or an intent by its slug or id, empty
/// for none. An unknown node is 404.
pub fn board_read(snapshot: &common::board_types::BoardSnapshot, node: &str) -> Result<BoardsReadResponse, AgentError> {
    let board_id = snapshot.board.board_id.as_str();
    let standing: Vec<&common::board_types::BoardFact> = snapshot.facts.iter().filter(|f| !f.rejected).collect();
    let name_of = |id: &str| {
        snapshot
            .facts
            .iter()
            .find(|f| f.fact_id == id)
            .map(|f| if f.slug.is_empty() { f.fact_id.clone() } else { f.slug.clone() })
            .unwrap_or_else(|| id.to_string())
    };
    let background = standing
        .iter()
        .find(|f| f.kind == "origin")
        .map(|f| handles_as_labels(&f.text))
        .unwrap_or_else(|| snapshot.board.context.clone());
    let goals = standing.iter().filter(|f| f.kind == "goal").map(|f| fact_node(board_id, f, false)).collect();
    let answers = snapshot
        .answers_accepted
        .iter()
        .map(|a| AgentBoardAnswer {
            goal: name_of(&a.goal),
            statement: handles_as_labels(&a.statement),
            from: a.from.iter().map(|id| name_of(id)).collect(),
        })
        .collect();
    let all_findings: Vec<&&common::board_types::BoardFact> =
        standing.iter().filter(|f| !matches!(f.kind.as_str(), "origin" | "goal")).collect();
    let findings_left_out = all_findings.len().saturating_sub(MAX_FINDINGS) as u32;
    let findings = all_findings.into_iter().take(MAX_FINDINGS).map(|f| fact_node(board_id, f, false)).collect();
    let node = if node.is_empty() {
        None
    } else if let Some(fact) = snapshot.facts.iter().find(|f| f.slug == node || f.fact_id == node) {
        Some(fact_node(board_id, fact, true))
    } else if let Some(intent) = snapshot.intents.iter().find(|i| i.slug == node || i.intent_id == node) {
        let name = if intent.slug.is_empty() { intent.intent_id.clone() } else { intent.slug.clone() };
        Some(AgentBoardNode {
            link: board_path(board_id, &name),
            node: name,
            kind: "intent".into(),
            title: intent.title.clone(),
            text: [intent.objective.as_str(), intent.question.as_str()]
                .into_iter()
                .filter(|t| !t.is_empty())
                .collect::<Vec<_>>()
                .join("\n"),
            open_questions: Vec::new(),
            citations: Vec::new(),
        })
    } else {
        return Err(AgentError::not_found(format!(
            "the board has no node {node}. Read the board without a node to see the node names"
        )));
    };
    Ok(BoardsReadResponse {
        board_id: board_id.to_string(),
        title: snapshot.board.title.clone(),
        status: snapshot.status.clone(),
        summary: snapshot.summary.clone(),
        group: snapshot.board.owner_group.clone(),
        link: board_path(board_id, ""),
        background,
        goals,
        answers,
        findings,
        findings_left_out,
        node,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use common::board_types::{BoardFact, BoardReviewGoal, BoardSnapshot};

    fn message(seq: u32, role: ChatRole, content: &str, tool: &str, output: &str) -> ChatMessageItem {
        let mut item: ChatMessageItem = serde_json::from_value(serde_json::json!({
            "seq": seq, "role": "User", "content": content, "tool_name": tool, "tool_input": "",
            "tool_output": output, "doc_refs": "", "created_at": "", "created_ms": "",
            "agent_duration_ms": 0, "retry_errors": "", "reasoning": "",
        }))
        .unwrap();
        item.role = role;
        item
    }

    #[test]
    fn a_member_reads_and_a_non_member_is_refused() {
        // The group rule of the pages decides the lookup. A member reads.
        let person = CurrentUser { username: "ana".into(), fullname: String::new(), email: String::new(), is_admin: false, groups: vec![] };
        let groups = vec!["team".to_string()];
        let lookup = |owner_group: &str| {
            if item_access::item_access(&person, &groups, owner_group, "bo").read {
                ItemLookup::Readable(owner_group.to_string())
            } else {
                ItemLookup::Unreadable
            }
        };
        for what in ["chat", KIND_BOARD] {
            assert_eq!(refusal(lookup("team"), what).ok().as_deref(), Some("team"));
            // A person outside the group gets 403, administrators too.
            let denied = refusal(lookup("other"), what).err().unwrap();
            assert_eq!((denied.status, denied.error), (StatusCode::FORBIDDEN, "permission_denied"));
            let missing = refusal::<String>(ItemLookup::Missing, what).err().unwrap();
            assert_eq!(missing.status, StatusCode::NOT_FOUND);
        }
    }

    #[test]
    fn a_chat_reads_as_questions_and_final_answers_with_their_sources() {
        let documents: Vec<ChatDocRef> = serde_json::from_value(serde_json::json!([{
            "handle": "[D1]", "collection_dataset": "enron_mail", "collectionname": "enron",
            "file_hash": "ab".repeat(32), "path": "/mail/a.eml", "quote": "the deal closes friday",
        }]))
        .unwrap();
        let item = serde_json::json!({"success": true, "citations": [{"handle": "[B1]", "kind": "board", "id": "b9", "title": "Who paid"}]});
        let messages = vec![
            message(1, ChatRole::User, "Who paid?", "", ""),
            message(2, ChatRole::Tool, "", "search_collections", "{}"),
            message(3, ChatRole::Assistant, "Draft that a repair replaced.", "", ""),
            message(4, ChatRole::Tool, "", "cite_chats_and_boards", &item.to_string()),
            message(5, ChatRole::Assistant, "Enron paid [D1]. See the board [B1] and [D7].", "", ""),
            message(6, ChatRole::User, "And then?", "", ""),
        ];
        let turns = chat_turns(&messages, &[], &documents);
        assert_eq!(turns.len(), 2);
        assert_eq!(turns[0].question, "Who paid?");
        assert_eq!(turns[0].answer, "Enron paid (D1). See the board (B1) and (D7).");
        assert_eq!(turns[0].citations.iter().map(|c| (c.label.as_str(), c.kind.as_str())).collect::<Vec<_>>(),
                   vec![("D1", "document"), ("B1", "board")]);
        assert_eq!(turns[0].citations[1].link, "/ai_chat/boards/b9");
        assert_eq!(turns[1].answer, "");
        let (page, next) = page_of(turns, 0, 1);
        assert_eq!((page.len(), next), (1, Some(1)));
    }

    #[test]
    fn a_list_filter_needs_every_word() {
        let words = filter_words("Enron  PAYMENTS");
        assert!(holds_words("Payments of enron in 2001", &words));
        assert!(!holds_words("Enron board", &words));
        assert!(holds_words("anything", &filter_words("")));
    }

    fn fact(id: &str, kind: &str, slug: &str, text: &str) -> BoardFact {
        serde_json::from_value(serde_json::json!({
            "fact_id": id, "kind": kind, "text": text, "intent_id": "", "session_id": "",
            "open_questions": [], "problems": [], "rejected": false, "created_ms": 0,
            "citations": [{"label": "D1", "collection_dataset": "enron_mail", "collectionname": "enron",
                           "file_hash": "ff", "path": "/a.eml", "page_id": 0, "quote": "paid in cash", "quote_verified": true}],
            "slug": slug, "title": "", "summary": "",
        }))
        .unwrap()
    }

    #[test]
    fn a_board_reads_as_background_goals_answers_and_findings() {
        let mut snapshot: BoardSnapshot = serde_json::from_value(serde_json::json!({
            "board": {"board_id": "b1", "owner": "bo", "title": "Payments", "goal": "", "context": "ctx",
                      "collections": [], "llm_model": "", "max_parallel": 1, "internet_tools": false, "created_ms": 0},
            "status": "review", "explores_used": 0, "reasons_done": 0, "stall_count": 0, "review_statement": "",
            "answers_proposed": [], "answers_accepted": [], "max_explores": 0, "explore_steps": 0,
            "facts": [], "intents": [], "events": [],
        }))
        .unwrap();
        snapshot.facts = vec![
            fact("origin", "origin", "background", "Background text."),
            fact("goal-01", "goal", "goal-01", "Who paid?"),
            fact("f1", "sourced", "finding-cash", "Cash was paid [D1]."),
        ];
        let mut rejected = fact("f2", "sourced", "finding-old", "Old.");
        rejected.rejected = true;
        snapshot.facts.push(rejected);
        snapshot.answers_accepted = vec![BoardReviewGoal { goal: "goal-01".into(), from: vec!["f1".into()], statement: "Cash [D1].".into(), ..Default::default() }];
        let read = board_read(&snapshot, "").unwrap();
        assert_eq!(read.background, "Background text.");
        assert_eq!(read.goals[0].node, "goal-01");
        assert_eq!(read.answers[0].from, vec!["finding-cash"]);
        assert_eq!(read.answers[0].statement, "Cash (D1).");
        assert_eq!(read.findings.iter().map(|f| f.node.as_str()).collect::<Vec<_>>(), vec!["finding-cash"]);
        assert!(read.findings[0].citations.is_empty());
        let node = board_read(&snapshot, "finding-cash").unwrap().node.unwrap();
        assert_eq!(node.text, "Cash was paid (D1).");
        assert_eq!(node.citations[0].label, "D1");
        assert_eq!(node.link, "/ai_chat/boards/b1?selected=finding-cash");
        assert_eq!(board_read(&snapshot, "nothing").err().unwrap().status, StatusCode::NOT_FOUND);
    }
}
