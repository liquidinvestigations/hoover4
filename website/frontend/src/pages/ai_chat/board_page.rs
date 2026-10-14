//! `/ai_chat/boards/:board_id`, one investigation board of the signed-in user: the graph of
//! board facts and intents on the left, the selected node or the board overview on the right.
//!
//! The page reads the board again every few seconds while work can change it. The graph
//! layout settles in one pass after each read that changes the board, and a node that was
//! already placed keeps its place (`components::board_graph`). Nothing moves between two
//! reads.
//!
//! The fact detail renders the fact as the chat renders an answer: Markdown, handles such as
//! `[D1]`, and a citation card for each handle. A card click opens the explore chat of the
//! fact in a new tab with that document selected, so the person can browse its cards there.
//!
//! `selected` is a fact id or an intent id in the address, so a selected node is a link.

use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;
use std::time::Duration;

use common::board_types::{BoardFact, BoardIntent, BoardSnapshot};
use common::chat_types::{ChatDocRef, card_find_phrase};
use common::search_result::{DocumentIdentifier, SearchResultDocuments, SearchResultHitCount};
use dioxus::prelude::*;

use crate::api::board_api::{
    board_add_hint, board_drop, board_reject_fact, board_review, board_set_internet_tools, board_set_paused,
    board_snapshot,
};
use crate::api::error_util::user_facing_message;
use crate::components::admin_components::{
    ErrorBar, BTN, BTN_PRIMARY, BTN_SMALL, BTN_SMALL_DANGER, HELP_TEXT, INPUT, LINK, SUBHEADING,
};
use crate::components::board_graph::{build_graph, kind_label, render_edge, render_node, settle, ArrowMarker, NodePosition};
use crate::components::chat_components::doc_ref_card::ChatDocOpen;
use crate::components::chat_components::markdown_text::MarkdownishText;
use crate::components::search_components::search_panel_left_view::SearchResultsState;
use crate::data_definitions::doc_viewer_state::DocViewerState;
use crate::pages::admin::llm_reports::format_utc_ms;
use crate::routes::Route;

/// Seconds between two reads while the board is active or an explore runs.
const LIVE_POLL_SECONDS: u64 = 3;
/// Seconds between two reads of a board that waits for a person.
const IDLE_POLL_SECONDS: u64 = 15;

const TEXTAREA: &str = "border: 1px solid; border-color: var(--x-border-strong); border-radius: 6px; padding: 6px 8px; font-size: var(--x-text-body); color: var(--x-ink-strong); background: white; width: 100%; box-sizing: border-box; font-family: inherit;";
const PANEL: &str = "border: 1px solid; border-color: var(--x-border); border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; background: white;";
const PRE: &str = "white-space: pre-wrap; font-size: var(--x-text-detail); background-color: var(--x-surface-muted); padding: 8px; border-radius: 6px; max-height: 260px; overflow: auto;";

#[component]
pub fn AiBoardPage(board_id: String, selected: String) -> Element {
    rsx! {
        Title { "Hoover Search - Board" }
        div {
            style: "width: 100%; height: 100%; background: #F5F6F8; box-sizing: border-box; padding: 15px 23px; overflow: auto;",
            BoardExplorer { board_id, selected }
        }
    }
}

/// The status of a board in words.
#[component]
pub fn StatusText(status: String) -> Element {
    let (label, colour) = match status.as_str() {
        "active" => ("Active", "var(--x-link)"),
        "paused" => ("Paused", "var(--x-ink-muted)"),
        "review" => ("Waits for review", "var(--x-danger)"),
        "completed" => ("Completed", "var(--x-ok)"),
        "dropped" => ("Dropped", "var(--x-ink-muted)"),
        _ => ("Unknown", "var(--x-ink-muted)"),
    };
    rsx! { span { style: "color: {colour}; font-weight: 500;", "{label}" } }
}

/// Read the board into `snapshot`, or the error into `error`.
async fn reload(board_id: String, mut snapshot: Signal<Option<BoardSnapshot>>, mut error: Signal<Option<String>>) {
    match board_snapshot(board_id).await {
        Ok(value) => {
            error.set(None);
            if snapshot.peek().as_ref() != Some(&value) {
                snapshot.set(Some(value));
            }
        }
        Err(e) => error.set(Some(user_facing_message(&e))),
    }
}

/// Whether the board can change soon: it is active, an explore runs, or the newest event is
/// a person action that the worker has not answered yet. A completed or dropped board waits
/// for nothing.
fn is_live(snapshot: &Option<BoardSnapshot>) -> bool {
    match snapshot {
        None => true,
        Some(s) if s.status == "completed" || s.status == "dropped" => false,
        Some(s) => {
            s.status == "active"
                || s.intents.iter().any(|i| i.state == "running")
                || s.events.last().is_some_and(|e| !matches!(e.actor.as_str(), "dispatcher" | "reason" | "explore"))
        }
    }
}

/// Open `route` in a new browser tab.
fn open_in_new_tab(route: Route) {
    if let Some(window) = web_sys::window() {
        let _ = window.open_with_url_and_target(&route.to_string(), "_blank");
    }
}

#[component]
fn BoardExplorer(board_id: ReadSignal<String>, selected: ReadSignal<String>) -> Element {
    let snapshot = use_signal(|| None::<BoardSnapshot>);
    let error = use_signal(|| None::<String>);
    let mut show_settings = use_signal(|| false);

    // The citation cards of a fact read the selection fields of a search page. This page
    // has no search, so the fields hold nothing and a card click goes to `ChatDocOpen`.
    let hit_count = use_signal(|| None::<Result<SearchResultHitCount, ServerFnError>>);
    let search_result = use_signal(|| None::<Result<SearchResultDocuments, ServerFnError>>);
    let current_page = use_signal(|| 0_u64);
    let search_query = use_signal(common::search_query::SearchQuery::default);
    let no_selection = use_signal(|| None::<DocumentIdentifier>);
    use_context_provider(move || SearchResultsState {
        query: search_query.into(),
        hit_count: hit_count.into(),
        search_result: search_result.into(),
        current_search_result_page: current_page.into(),
        set_current_page: Callback::new(|_| {}),
        selected_result_hash: no_selection.into(),
        set_selected_result_hash: Callback::new(|_| {}),
        set_selected_result_hash_and_page: Callback::new(|_| {}),
    });

    // The read loop. It reads the id each time, so a navigation to another board shows that
    // board on the next read.
    use_future(move || async move {
        let mut shown = String::new();
        loop {
            let id = board_id.peek().clone();
            if id != shown {
                let mut snapshot = snapshot;
                snapshot.set(None);
                shown = id.clone();
            }
            reload(id, snapshot, error).await;
            let seconds = if is_live(&snapshot.peek()) { LIVE_POLL_SECONDS } else { IDLE_POLL_SECONDS };
            n0_future::time::sleep(Duration::from_secs(seconds)).await;
        }
    });

    // The settled layout. It is computed again only when a read changes the board, and the
    // layout before it pins every node that stays.
    let placed = use_hook(|| Rc::new(RefCell::new(HashMap::<String, NodePosition>::new())));
    let layout = use_memo(move || {
        let graph = snapshot.read().as_ref().map(|s| build_graph(&s.graph_input())).unwrap_or_default();
        let next = settle(&graph, &placed.borrow());
        *placed.borrow_mut() = next.clone();
        (graph, next)
    });

    let current = snapshot.read().clone();
    let Some(snap) = current else {
        return rsx! {
            if let Some(err) = error.read().clone() {
                ErrorBar { message: err }
            } else {
                p { style: HELP_TEXT, "Loading the board\u{2026}" }
            }
        };
    };

    let selected_id = selected.read().clone();
    let (graph, positions) = layout.read().clone();
    let board_key = snap.board.board_id.clone();
    let on_select = Callback::new(move |id: String| {
        navigator().push(Route::AiBoardPage { board_id: board_key.clone(), selected: id });
    });

    let detail = if let Some(fact) = snap.facts.iter().find(|f| f.fact_id == selected_id) {
        rsx! { FactDetail { key: "{fact.fact_id}", board_id: snap.board.board_id.clone(), fact: fact.clone(), snapshot, error } }
    } else if let Some(intent) = snap.intents.iter().find(|i| i.intent_id == selected_id) {
        rsx! { IntentDetail { intent: intent.clone() } }
    } else {
        rsx! { BoardOverview { snap: snap.clone(), snapshot, error } }
    };

    rsx! {
        if let Some(err) = error.read().clone() {
            ErrorBar { message: err }
        }
        BoardHeader { snap: snap.clone(), on_settings: move |_| show_settings.set(true) }
        if show_settings() {
            BoardSettings { snap: snap.clone(), snapshot, error, on_close: move |_| show_settings.set(false) }
        }
        div {
            style: "display: flex; gap: 12px; height: calc(100vh - 150px); min-height: 480px;",
            div {
                class: "x-board-graph-pane",
                style: "flex: 1 1 62%; min-width: 0; border: 1px solid; border-color: var(--x-border); border-radius: 8px; overflow: auto; background: white;",
                svg {
                    class: "x-board-graph-svg",
                    width: "100%",
                    height: "100%",
                    view_box: "0 0 {graph.width} {graph.height}",
                    preserve_aspect_ratio: "xMidYMid meet",
                    ArrowMarker { id: "x-board-arrow" }
                    // A review edge can cross the correction column on its way to a goal, so
                    // it is drawn over the nodes. The other edges join neighbouring columns.
                    for edge in graph.edges.iter().filter(|e| !e.kind.is_review()) {
                        {render_edge(edge, &positions, "x-board-arrow")}
                    }
                    for node in graph.nodes.iter() {
                        {render_node(node, &positions, &selected_id, on_select)}
                    }
                    for edge in graph.edges.iter().filter(|e| e.kind.is_review()) {
                        {render_edge(edge, &positions, "x-board-arrow")}
                    }
                }
            }
            div {
                style: "flex: 1 1 38%; min-width: 340px; overflow: auto;",
                if !selected_id.is_empty() {
                    div { style: "margin-bottom: 8px;",
                        button { style: BTN_SMALL, onclick: move |_| on_select.call(String::new()), "Show the board overview" }
                    }
                }
                {detail}
            }
        }
    }
}

#[component]
fn BoardHeader(snap: BoardSnapshot, on_settings: EventHandler<()>) -> Element {
    let running = snap.intents.iter().filter(|i| i.state == "running").count();
    let open = snap.intents.iter().filter(|i| i.state == "open").count();
    rsx! {
        div { style: "display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 10px;",
            Link { to: Route::AiChatPage {}, style: LINK, "\u{2190} AI Chat" }
            span { style: "font-size: var(--x-text-section); font-weight: 600; color: var(--x-ink-strong);", "{snap.board.title}" }
            StatusText { status: snap.status.clone() }
            span { style: HELP_TEXT,
                "{snap.explores_used} of {snap.max_explores} explores, {snap.explore_steps} model steps per explore, {snap.reasons_done} reasons, {running} running, {open} open"
            }
            button { class: "x-board-settings-open", style: BTN, onclick: move |_| on_settings.call(()), "Settings" }
        }
    }
}

/// The settings popup: internet tools, the collections (fixed at creation), pause and drop.
#[component]
fn BoardSettings(
    snap: BoardSnapshot,
    snapshot: Signal<Option<BoardSnapshot>>,
    error: Signal<Option<String>>,
    on_close: EventHandler<()>,
) -> Element {
    let mut confirm_drop = use_signal(|| false);
    let mut error = error;
    let board_id = snap.board.board_id.clone();
    let finished = snap.status == "completed" || snap.status == "dropped";
    let pause_label = match snap.status.as_str() {
        "active" => Some(("Pause the board", true)),
        "paused" => Some(("Resume the board", false)),
        _ => None,
    };
    rsx! {
        div {
            style: "position: fixed; inset: 0; background-color: rgba(0,0,0,0.3); z-index: 50; display: flex; align-items: center; justify-content: center;",
            onclick: move |_| on_close.call(()),
            div {
                class: "x-board-settings",
                style: "background: white; border-radius: 10px; padding: 18px 20px; width: 460px; max-width: 92vw; box-shadow: 0 8px 30px rgba(0,0,0,0.2);",
                onclick: move |e| e.stop_propagation(),
                div { style: "font-size: var(--x-text-section); font-weight: 600; margin-bottom: 10px;", "Board settings" }
                label { style: "display: flex; gap: 8px; align-items: center; font-size: var(--x-text-body);",
                    input {
                        class: "x-board-internet-tools",
                        r#type: "checkbox",
                        checked: snap.board.internet_tools,
                        disabled: finished,
                        onchange: {
                            let id = board_id.clone();
                            move |e: FormEvent| {
                                let id = id.clone();
                                let on = e.checked();
                                spawn(async move {
                                    if let Err(e) = board_set_internet_tools(id.clone(), on).await {
                                        error.set(Some(user_facing_message(&e)));
                                    }
                                    reload(id, snapshot, error).await;
                                });
                            }
                        },
                    }
                    "Internet tools"
                }
                p { style: HELP_TEXT, "The next explores of the board can search the web and read web pages. Running explores keep the setting they started with." }
                div { style: SUBHEADING, "Collections" }
                p { style: "margin: 4px 0;", "{snap.board.collections.join(\", \")}" }
                p { style: HELP_TEXT, "The collections are fixed when the board is created." }
                div { style: "display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 14px;",
                    if let Some((label, paused)) = pause_label {
                        button {
                            style: BTN,
                            onclick: {
                                let id = board_id.clone();
                                move |_| {
                                    let id = id.clone();
                                    spawn(async move {
                                        if let Err(e) = board_set_paused(id.clone(), paused).await {
                                            error.set(Some(user_facing_message(&e)));
                                        }
                                        reload(id, snapshot, error).await;
                                    });
                                }
                            },
                            "{label}"
                        }
                    }
                    if confirm_drop() {
                        button {
                            style: BTN_SMALL_DANGER,
                            onclick: {
                                let id = board_id.clone();
                                move |_| {
                                    let id = id.clone();
                                    spawn(async move {
                                        match board_drop(id).await {
                                            Ok(()) => { navigator().push(Route::AiChatPage {}); }
                                            Err(e) => error.set(Some(user_facing_message(&e))),
                                        }
                                    });
                                }
                            },
                            "Confirm drop"
                        }
                    } else if snap.status != "dropped" {
                        button { style: BTN_SMALL_DANGER, onclick: move |_| confirm_drop.set(true), "Drop the board" }
                    }
                    span { style: "flex: 1;" }
                    button { style: BTN_PRIMARY, onclick: move |_| on_close.call(()), "Close" }
                }
            }
        }
    }
}

#[component]
fn BoardOverview(snap: BoardSnapshot, snapshot: Signal<Option<BoardSnapshot>>, error: Signal<Option<String>>) -> Element {
    let mut hint = use_signal(String::new);
    let mut correction = use_signal(String::new);
    let mut error = error;
    let board_id = snap.board.board_id.clone();
    let goals: Vec<BoardFact> = snap.goals().into_iter().cloned().collect();
    let statement_of = |goal: &str| snap.review_goals.iter().find(|r| r.goal == goal).cloned();
    rsx! {
        if snap.status == "review" {
            div { class: "x-board-review", style: "{PANEL} border-color: var(--x-danger);",
                div { style: SUBHEADING, "The board waits for your review" }
                if snap.review_goals.is_empty() && snap.review_statement.is_empty() {
                    p { style: HELP_TEXT, "The board stopped without a statement: the explore budget is used or the work stalled." }
                }
                if snap.review_goals.is_empty() && !snap.review_statement.is_empty() {
                    p { "{snap.review_statement}" }
                    p { style: HELP_TEXT, "From the facts {snap.review_from.join(\", \")}." }
                }
                for goal in goals.iter() {
                    if let Some(review) = statement_of(&goal.fact_id) {
                        div { key: "{goal.fact_id}", class: "x-board-review-goal", style: "margin: 8px 0;",
                            div { style: "font-weight: 600; font-size: var(--x-text-detail);", "{goal.fact_id}: {goal.text}" }
                            p { style: "margin: 4px 0;", "{review.statement}" }
                            if !review.from.is_empty() {
                                p { style: HELP_TEXT, "From the facts {review.from.join(\", \")}." }
                            }
                        }
                    }
                }
                div { style: "display: flex; gap: 8px; align-items: center; flex-wrap: wrap;",
                    button {
                        style: BTN_PRIMARY,
                        onclick: {
                            let id = board_id.clone();
                            move |_| {
                                let id = id.clone();
                                spawn(async move {
                                    if let Err(e) = board_review(id.clone(), true, String::new()).await {
                                        error.set(Some(user_facing_message(&e)));
                                    }
                                    reload(id, snapshot, error).await;
                                });
                            }
                        },
                        "Accept"
                    }
                }
                textarea {
                    style: "{TEXTAREA} margin-top: 8px;", rows: "2",
                    placeholder: "Correction: what is wrong or missing. The board continues with it.",
                    value: "{correction}", oninput: move |e| correction.set(e.value()),
                }
                button {
                    style: "{BTN} margin-top: 6px;",
                    onclick: {
                        let id = board_id.clone();
                        move |_| {
                            let id = id.clone();
                            let text = correction.read().clone();
                            spawn(async move {
                                match board_review(id.clone(), false, text).await {
                                    Ok(()) => correction.set(String::new()),
                                    Err(e) => error.set(Some(user_facing_message(&e))),
                                }
                                reload(id, snapshot, error).await;
                            });
                        }
                    },
                    "Reject with correction"
                }
            }
        }
        div { style: PANEL,
            div { style: SUBHEADING, if goals.len() == 1 { "Goal" } else { "Goals" } }
            for goal in goals.iter() {
                div { key: "{goal.fact_id}", style: "margin: 4px 0;",
                    if goals.len() > 1 { span { style: "color: var(--x-ink-muted); margin-right: 6px;", "{goal.fact_id}" } }
                    "{goal.text}"
                    if snap.status == "completed" {
                        if let Some(review) = statement_of(&goal.fact_id) {
                            div { style: "margin: 4px 0 0 12px; color: var(--x-ok);", "Answer: {review.statement}" }
                        }
                    }
                }
            }
            if !snap.board.context.is_empty() {
                div { style: SUBHEADING, "Context" }
                p { style: "margin: 4px 0;", "{snap.board.context}" }
            }
            p { style: HELP_TEXT,
                "Collections: {snap.board.collections.join(\", \")}. Internet tools: "
                if snap.board.internet_tools { "on." } else { "off." }
                " A rejected fact or review adds explores and model steps, and a hint adds a few."
            }
        }
        if snap.status == "active" || snap.status == "paused" {
            div { style: PANEL,
                div { style: SUBHEADING, "Add a hint" }
                p { style: HELP_TEXT, "The next reason reads every hint. A hint also answers an explore that asked a question." }
                textarea {
                    class: "x-board-hint",
                    style: TEXTAREA, rows: "2",
                    value: "{hint}", oninput: move |e| hint.set(e.value()),
                }
                button {
                    style: "{BTN} margin-top: 6px;",
                    onclick: {
                        let id = board_id.clone();
                        move |_| {
                            let id = id.clone();
                            let text = hint.read().clone();
                            spawn(async move {
                                match board_add_hint(id.clone(), text).await {
                                    Ok(()) => hint.set(String::new()),
                                    Err(e) => error.set(Some(user_facing_message(&e))),
                                }
                                reload(id, snapshot, error).await;
                            });
                        }
                    },
                    "Add hint"
                }
            }
        }
        div { class: "x-board-timeline", style: PANEL,
            div { style: SUBHEADING, "Events, newest first" }
            for event in snap.events.iter().rev().take(200) {
                div { key: "{event.event_id}", style: "padding: 4px 0; border-bottom: 1px solid; border-bottom-color: var(--x-border); font-size: var(--x-text-detail);",
                    span { style: "color: var(--x-ink-muted); margin-right: 8px;", "{format_utc_ms(event.created_ms)}" }
                    span { style: "color: var(--x-ink-muted); margin-right: 8px;", "{event.actor}" }
                    "{event.summary}"
                }
            }
        }
    }
}

/// The citation cards of a fact, as the chat builds them from its `cite_documents` results.
fn fact_sources(fact: &BoardFact) -> Vec<ChatDocRef> {
    fact.citations
        .iter()
        .map(|c| ChatDocRef {
            collection_dataset: c.collection_dataset.clone(),
            file_hash: c.file_hash.clone(),
            collectionname: c.collectionname.clone(),
            path: c.path.clone(),
            page_id: (c.page_id > 0).then_some(c.page_id),
            score: None,
            snippet: String::new(),
            also_in: Vec::new(),
            handle: format!("[{}]", c.label),
            quote: c.quote.clone(),
            why: String::new(),
            quote_verified: c.quote_verified,
            quote_reason: String::new(),
            // The words of the quote as one phrase. The raw quote would find each of its
            // words anywhere in the document.
            find_query: card_find_phrase(&format!("\"{}\"", c.quote.replace('"', " "))),
            term: String::new(),
            search_snippet: String::new(),
            search_route: String::new(),
        })
        .collect()
}

#[component]
fn FactDetail(board_id: String, fact: BoardFact, snapshot: Signal<Option<BoardSnapshot>>, error: Signal<Option<String>>) -> Element {
    let mut reason = use_signal(String::new);
    let mut error = error;
    let can_reject = !fact.rejected && fact.kind != "origin" && fact.kind != "goal";
    // A citation card opens the explore chat of this fact in a new tab, with its document
    // selected. The component is keyed by the fact, so the provider names this fact.
    let session_id = fact.session_id.clone();
    use_context_provider(move || ChatDocOpen {
        open: Callback::new(move |(id, find_query): (DocumentIdentifier, String)| {
            if !session_id.is_empty() {
                open_in_new_tab(Route::ai_chat_session(
                    session_id.clone(),
                    Some(id),
                    Some(DocViewerState::from_find_query(find_query)),
                ));
            }
        }),
    });
    let sources = fact_sources(&fact);
    let handles: Vec<String> = sources.iter().map(|s| s.handle.clone()).collect();
    let rejected_by = if fact.rejected_by.is_empty() { "A person".to_string() } else { fact.rejected_by.clone() };
    rsx! {
        div { class: "x-board-fact-detail", style: PANEL,
            div { style: SUBHEADING, "Fact {fact.fact_id} ({kind_label(&fact.kind)})" }
            if fact.rejected {
                div { class: "x-board-fact-rejection", style: "border-left: 3px solid; border-left-color: var(--x-danger); padding: 4px 10px; margin: 6px 0;",
                    div { style: "color: var(--x-danger); font-weight: 500;",
                        if fact.rejected_ms > 0 {
                            "{rejected_by} rejected this fact on {format_utc_ms(fact.rejected_ms)}. The board no longer uses it."
                        } else {
                            "{rejected_by} rejected this fact. The board no longer uses it."
                        }
                    }
                    if fact.rejected_reason.is_empty() {
                        div { style: HELP_TEXT, "No reason was given." }
                    } else {
                        div { style: "white-space: pre-wrap;", "Reason: {fact.rejected_reason}" }
                    }
                }
            }
            if !fact.corrects.is_empty() {
                p { style: HELP_TEXT, "This correction applies to the facts {fact.corrects.join(\", \")}." }
            }
            div { class: "x-board-fact-text", style: "margin: 6px 0;",
                MarkdownishText { text: fact.text.clone(), cited_handles: Some(handles), sources }
            }
            if !fact.open_questions.is_empty() {
                div { style: SUBHEADING, "Open questions" }
                for (i, q) in fact.open_questions.iter().enumerate() {
                    div { key: "{i}", style: "font-size: var(--x-text-detail);", "{q}" }
                }
            }
            if !fact.problems.is_empty() {
                div { style: SUBHEADING, "Checks that changed this fact" }
                for (i, p) in fact.problems.iter().enumerate() {
                    div { key: "{i}", style: "font-size: var(--x-text-detail); color: var(--x-danger);", "{p}" }
                }
            }
            p { style: HELP_TEXT,
                if fact.created_by.is_empty() || fact.created_by == "explore" {
                    "Written {format_utc_ms(fact.created_ms)}."
                } else {
                    "Written by {fact.created_by} on {format_utc_ms(fact.created_ms)}."
                }
            }
            if !fact.session_id.is_empty() {
                Link { to: Route::ai_chat_session(fact.session_id.clone(), None, None), style: LINK, "Open the explore chat" }
            }
            if can_reject {
                div { style: "margin-top: 10px; display: flex; gap: 8px; align-items: center;",
                    input {
                        class: "x-board-reject-reason",
                        style: "{INPUT} flex: 1;", placeholder: "Why the fact is wrong",
                        value: "{reason}", oninput: move |e| reason.set(e.value()),
                    }
                    button {
                        style: BTN_SMALL_DANGER,
                        onclick: {
                            let board_id = board_id.clone();
                            let fact_id = fact.fact_id.clone();
                            move |_| {
                                let (board_id, fact_id) = (board_id.clone(), fact_id.clone());
                                let text = reason.read().clone();
                                spawn(async move {
                                    match board_reject_fact(board_id.clone(), fact_id, text).await {
                                        Ok(()) => reason.set(String::new()),
                                        Err(e) => error.set(Some(user_facing_message(&e))),
                                    }
                                    reload(board_id, snapshot, error).await;
                                });
                            }
                        },
                        "Reject fact"
                    }
                }
            }
        }
    }
}

#[component]
fn IntentDetail(intent: BoardIntent) -> Element {
    let from = intent.from_facts.join(", ");
    rsx! {
        div { class: "x-board-intent-detail", style: PANEL,
            div { style: SUBHEADING, "Intent {intent.intent_id} ({intent.state})" }
            p { style: "margin: 4px 0;", "{intent.objective}" }
            p { style: HELP_TEXT, "From the facts {from}. Attempts: {intent.attempts}. Declared {format_utc_ms(intent.created_ms)}." }
            if !intent.question.is_empty() {
                div { style: SUBHEADING, "The explore asked" }
                p { style: "margin: 4px 0;", "{intent.question}" }
                p { style: HELP_TEXT, "Add a hint in the board overview to answer it." }
            }
            if !intent.last_error.is_empty() {
                div { style: SUBHEADING, "Last error" }
                p { style: "margin: 4px 0; color: var(--x-danger);", "{intent.last_error}" }
            }
            if !intent.session_id.is_empty() {
                Link { to: Route::ai_chat_session(intent.session_id.clone(), None, None), style: LINK, "Open the explore chat" }
            }
            if !intent.brief.is_empty() {
                div { style: SUBHEADING, "Brief sent to the explore" }
                pre { style: PRE, "{intent.brief}" }
            }
        }
    }
}
