//! The board explorer: the graph of board facts and intents on the left, the selected node
//! or the board overview on the right.
//!
//! The graph
//! ---------
//! A fact or an intent is a node. An edge goes from each fact that an intent names to the
//! intent, and from the intent to the fact that its explore wrote. **x is depth**: origin,
//! goal and corrections are depth 0, an intent is one more than the deepest fact it names,
//! and a fact is one more than its intent. A spring pulls each node to the column of its
//! depth, so the picture reads from the goal on the left to the newest facts on the right.
//! y comes from pairwise repulsion, attraction along edges and damping.
//!
//! The page reads the board again every few seconds while work can change it. Positions
//! persist across reads: surviving nodes keep their coordinates, and a new node starts at
//! the centroid of the neighbours it arrived with. After each change the loop runs a bounded
//! number of ticks and stops, as the email graph does.
//!
//! `selected` is a fact id or an intent id in the address, so a selected node is a link.

use std::collections::HashMap;
use std::time::Duration;

use common::board_types::{BoardFact, BoardIntent, BoardSnapshot};
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::api::admin_api::{
    admin_board_add_hint, admin_board_drop, admin_board_reject_fact, admin_board_review, admin_board_set_paused,
    admin_board_snapshot,
};
use crate::api::error_util::user_facing_message;
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, BTN, BTN_PRIMARY, BTN_SMALL, BTN_SMALL_DANGER, HELP_TEXT, INPUT, LINK,
    SUBHEADING,
};
use crate::pages::admin::boards_list::StatusText;
use crate::pages::admin::llm_reports::format_utc_ms;
use crate::routes::Route;

/// Seconds between two reads while the board is active or an explore runs.
const LIVE_POLL_SECONDS: u64 = 3;
/// Seconds between two reads of a board that waits for a person.
const IDLE_POLL_SECONDS: u64 = 15;

/// Ticks after each change of the node set, then the loop stops.
const MAX_TICKS: u32 = 120;
/// Milliseconds between ticks.
const TICK_MS: u64 = 25;

/// Simulation units of one depth column, and the smallest viewport.
const COLUMN_WIDTH: f64 = 240.0;
const MIN_WIDTH: f64 = 1000.0;
const MIN_HEIGHT: f64 = 620.0;
/// Vertical room of one node in the tallest column.
const ROW_HEIGHT: f64 = 76.0;
const NODE_WIDTH: f64 = 190.0;
const NODE_HEIGHT: f64 = 58.0;

const DEPTH_SPRING: f64 = 0.08;
const REPULSION: f64 = 30_000.0;
const EDGE_PULL: f64 = 0.01;
const DAMPING: f64 = 0.82;
const CENTRING: f64 = 0.004;

const TEXTAREA: &str = "border: 1px solid; border-color: var(--x-border-strong); border-radius: 6px; padding: 6px 8px; font-size: var(--x-text-body); color: var(--x-ink-strong); background: white; width: 100%; box-sizing: border-box; font-family: inherit;";
const PANEL: &str = "border: 1px solid; border-color: var(--x-border); border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; background: white;";
const PRE: &str = "white-space: pre-wrap; font-size: var(--x-text-detail); background-color: var(--x-surface-muted); padding: 8px; border-radius: 6px; max-height: 260px; overflow: auto;";

#[derive(Clone, Copy, PartialEq, Debug)]
struct NodePosition {
    x: f64,
    y: f64,
    vx: f64,
    vy: f64,
}

#[derive(Clone, PartialEq, Debug)]
enum NodeKind {
    /// A board fact and its kind.
    Fact(String),
    /// An intent and its state.
    Intent(String),
}

#[derive(Clone, PartialEq, Debug)]
struct GraphNode {
    id: String,
    kind: NodeKind,
    label: String,
    depth: u32,
    dimmed: bool,
}

#[derive(Clone, PartialEq, Debug)]
struct GraphEdge {
    src: String,
    dst: String,
}

#[derive(Clone, PartialEq, Debug, Default)]
struct Graph {
    nodes: Vec<GraphNode>,
    edges: Vec<GraphEdge>,
    width: f64,
    height: f64,
}

#[component]
pub fn AdminBoardPage(board_id: String, selected: String) -> Element {
    rsx! {
        Title { "Admin: board" }
        AdminGuard {
            AdminShell {
                title: "Investigation board".to_string(),
                breadcrumb: "Boards".to_string(),
                active: "boards".to_string(),
                BoardExplorer { board_id, selected }
            }
        }
    }
}

/// Read the board into `snapshot`, or the error into `error`.
async fn reload(board_id: String, mut snapshot: Signal<Option<BoardSnapshot>>, mut error: Signal<Option<String>>) {
    match admin_board_snapshot(board_id).await {
        Ok(value) => {
            error.set(None);
            if snapshot.peek().as_ref() != Some(&value) {
                snapshot.set(Some(value));
            }
        }
        Err(e) => error.set(Some(user_facing_message(&e))),
    }
}

fn is_live(snapshot: &Option<BoardSnapshot>) -> bool {
    match snapshot {
        None => true,
        Some(s) => s.status == "active" || s.intents.iter().any(|i| i.state == "running"),
    }
}

#[component]
fn BoardExplorer(board_id: ReadSignal<String>, selected: ReadSignal<String>) -> Element {
    let snapshot = use_signal(|| None::<BoardSnapshot>);
    let error = use_signal(|| None::<String>);
    let positions = use_signal(HashMap::<String, NodePosition>::new);
    let ticks = use_signal(|| 0_u32);

    // The read loop. It reads the id each time, so a navigation to another board shows that
    // board on the next read, and the layout of the earlier board is cleared.
    use_future(move || async move {
        let mut shown = String::new();
        loop {
            let id = board_id.peek().clone();
            if id != shown {
                let mut positions = positions;
                let mut snapshot = snapshot;
                positions.set(HashMap::new());
                snapshot.set(None);
                shown = id.clone();
            }
            reload(id, snapshot, error).await;
            let seconds = if is_live(&snapshot.peek()) { LIVE_POLL_SECONDS } else { IDLE_POLL_SECONDS };
            n0_future::time::sleep(Duration::from_secs(seconds)).await;
        }
    });

    let current = snapshot.read().clone();
    let graph = current.as_ref().map(build_graph).unwrap_or_default();

    // The add/remove diff. Reading `snapshot` subscribes the effect, so it runs after every
    // new read and seeds the nodes that the read added.
    use_effect({
        let mut positions = positions;
        let mut ticks = ticks;
        move || {
            let graph = snapshot.read().as_ref().map(build_graph).unwrap_or_default();
            let seeded = seed_positions(&graph, &positions.peek().clone());
            if seeded.len() != positions.peek().len() || seeded.keys().any(|k| !positions.peek().contains_key(k)) {
                positions.set(seeded);
                ticks.set(0);
            }
        }
    });

    // The layout loop: one future that idles after `MAX_TICKS` until a diff resets the count.
    use_future({
        let mut positions = positions;
        let mut ticks = ticks;
        move || async move {
            loop {
                if *ticks.peek() >= MAX_TICKS {
                    n0_future::time::sleep(Duration::from_millis(200)).await;
                    continue;
                }
                let graph = snapshot.peek().as_ref().map(build_graph).unwrap_or_default();
                let mut next = positions.peek().clone();
                simulate_tick(&graph, &mut next);
                positions.set(next);
                ticks += 1;
                n0_future::time::sleep(Duration::from_millis(TICK_MS)).await;
            }
        }
    });

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
    let layout = positions.read().clone();
    let board_key = snap.board.board_id.clone();
    let on_select = Callback::new(move |id: String| {
        navigator().push(Route::AdminBoardPage { board_id: board_key.clone(), selected: id });
    });

    let detail = if let Some(fact) = snap.facts.iter().find(|f| f.fact_id == selected_id) {
        rsx! { FactDetail { board_id: snap.board.board_id.clone(), fact: fact.clone(), snapshot, error } }
    } else if let Some(intent) = snap.intents.iter().find(|i| i.intent_id == selected_id) {
        rsx! { IntentDetail { intent: intent.clone() } }
    } else {
        rsx! { BoardOverview { snap: snap.clone(), snapshot, error } }
    };

    rsx! {
        if let Some(err) = error.read().clone() {
            ErrorBar { message: err }
        }
        BoardHeader { snap: snap.clone(), snapshot, error }
        div {
            style: "display: flex; gap: 12px; height: calc(100vh - 210px); min-height: 480px;",
            div {
                class: "x-board-graph-pane",
                style: "flex: 1 1 60%; min-width: 0; border: 1px solid; border-color: var(--x-border); border-radius: 8px; overflow: auto; background: white;",
                svg {
                    class: "x-board-graph-svg",
                    width: "100%",
                    height: "100%",
                    view_box: "0 0 {graph.width} {graph.height}",
                    preserve_aspect_ratio: "xMidYMid meet",
                    defs {
                        marker {
                            id: "x-board-arrow",
                            view_box: "0 0 10 10",
                            ref_x: "9",
                            ref_y: "5",
                            marker_width: "7",
                            marker_height: "7",
                            orient: "auto-start-reverse",
                            path { d: "M 0 0 L 10 5 L 0 10 z", fill: "rgba(0,0,0,0.40)" }
                        }
                    }
                    for edge in graph.edges.iter() {
                        {render_edge(edge, &layout)}
                    }
                    for node in graph.nodes.iter() {
                        {render_node(node, &layout, &selected_id, on_select)}
                    }
                }
            }
            div {
                style: "flex: 1 1 40%; min-width: 320px; overflow: auto;",
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
fn BoardHeader(snap: BoardSnapshot, snapshot: Signal<Option<BoardSnapshot>>, error: Signal<Option<String>>) -> Element {
    let mut confirm_drop = use_signal(|| false);
    let mut error = error;
    let board_id = snap.board.board_id.clone();
    let running = snap.intents.iter().filter(|i| i.state == "running").count();
    let open = snap.intents.iter().filter(|i| i.state == "open").count();
    let pause_label = match snap.status.as_str() {
        "active" => Some(("Pause", true)),
        "paused" => Some(("Resume", false)),
        _ => None,
    };
    rsx! {
        div { style: "display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 10px;",
            span { style: "font-size: var(--x-text-section); font-weight: 600; color: var(--x-ink-strong);", "{snap.board.title}" }
            StatusText { status: snap.status.clone() }
            span { style: HELP_TEXT,
                "{snap.explores_used} of {snap.board.max_explores} explores, {snap.reasons_done} reasons, {running} running, {open} open"
            }
            if let Some((label, paused)) = pause_label {
                button {
                    style: BTN,
                    onclick: {
                        let id = board_id.clone();
                        move |_| {
                            let id = id.clone();
                            spawn(async move {
                                if let Err(e) = admin_board_set_paused(id.clone(), paused).await {
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
                                match admin_board_drop(id).await {
                                    Ok(()) => { navigator().push(Route::AdminBoardsPage {}); }
                                    Err(e) => error.set(Some(user_facing_message(&e))),
                                }
                            });
                        }
                    },
                    "Confirm drop"
                }
            } else {
                button { style: BTN_SMALL_DANGER, onclick: move |_| confirm_drop.set(true), "Drop" }
            }
            Link { to: Route::AdminBoardsPage {}, style: LINK, "All boards" }
        }
    }
}

#[component]
fn BoardOverview(snap: BoardSnapshot, snapshot: Signal<Option<BoardSnapshot>>, error: Signal<Option<String>>) -> Element {
    let mut hint = use_signal(String::new);
    let mut correction = use_signal(String::new);
    let mut error = error;
    let board_id = snap.board.board_id.clone();
    let review_from = snap.review_from.join(", ");
    rsx! {
        if snap.status == "review" {
            div { class: "x-board-review", style: "{PANEL} border-color: var(--x-danger);",
                div { style: SUBHEADING, "The board waits for your review" }
                if snap.review_statement.is_empty() {
                    p { style: HELP_TEXT, "The board stopped without a statement: the explore budget is used or the work stalled." }
                } else {
                    p { "{snap.review_statement}" }
                    p { style: HELP_TEXT, "From the facts {review_from}." }
                }
                div { style: "display: flex; gap: 8px; align-items: center; flex-wrap: wrap;",
                    button {
                        style: BTN_PRIMARY,
                        onclick: {
                            let id = board_id.clone();
                            move |_| {
                                let id = id.clone();
                                spawn(async move {
                                    if let Err(e) = admin_board_review(id.clone(), true, String::new()).await {
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
                                match admin_board_review(id.clone(), false, text).await {
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
            div { style: SUBHEADING, "Goal" }
            p { style: "margin: 4px 0;", "{snap.board.goal}" }
            if !snap.board.context.is_empty() {
                div { style: SUBHEADING, "Context" }
                p { style: "margin: 4px 0;", "{snap.board.context}" }
            }
            p { style: HELP_TEXT,
                "Collections: {snap.board.collections.join(\", \")}. Model steps per explore: {snap.board.explore_step_budget}."
            }
        }
        if snap.status == "active" || snap.status == "paused" {
            div { style: PANEL,
                div { style: SUBHEADING, "Add a hint" }
                p { style: HELP_TEXT, "The next reason reads every hint. A hint also answers an explore that asked a question." }
                textarea {
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
                                match admin_board_add_hint(id.clone(), text).await {
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

#[component]
fn FactDetail(board_id: String, fact: BoardFact, snapshot: Signal<Option<BoardSnapshot>>, error: Signal<Option<String>>) -> Element {
    let mut reason = use_signal(String::new);
    let mut error = error;
    let can_reject = !fact.rejected && fact.kind != "origin" && fact.kind != "goal";
    rsx! {
        div { class: "x-board-fact-detail", style: PANEL,
            div { style: SUBHEADING, "Fact {fact.fact_id} ({kind_label(&fact.kind)})" }
            if fact.rejected {
                p { style: "color: var(--x-danger);", "A person rejected this fact. The board no longer uses it." }
            }
            p { style: "margin: 4px 0; white-space: pre-wrap;", "{fact.text}" }
            if !fact.citations.is_empty() {
                div { style: SUBHEADING, "Citations" }
                for citation in fact.citations.iter() {
                    div { key: "{citation.label}", style: "padding: 4px 0; font-size: var(--x-text-detail);",
                        Link {
                            to: Route::ViewDocumentPage {
                                document_identifier: DocumentIdentifier {
                                    collection_dataset: citation.collection_dataset.clone(),
                                    file_hash: citation.file_hash.clone(),
                                }.into(),
                                doc_viewer_state: None.into(),
                                viewer_right_tab_state: crate::data_definitions::doc_viewer_state::ViewerRightTabState::default().into(),
                            },
                            style: LINK,
                            "[{citation.label}] {citation.collectionname} {citation.path}"
                        }
                        if !citation.quote.is_empty() {
                            div { style: "color: var(--x-ink-muted); margin-left: 12px;",
                                "\u{201c}{citation.quote}\u{201d}"
                                if citation.quote_verified { " (quote found in the document)" } else { " (quote not found in the document)" }
                            }
                        }
                    }
                }
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
            p { style: HELP_TEXT, "Written {format_utc_ms(fact.created_ms)}." }
            if !fact.session_id.is_empty() {
                Link { to: Route::ai_chat_session(fact.session_id.clone(), None, None), style: LINK, "Open the explore chat" }
            }
            if can_reject {
                div { style: "margin-top: 10px; display: flex; gap: 8px; align-items: center;",
                    input {
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
                                    match admin_board_reject_fact(board_id.clone(), fact_id, text).await {
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

fn kind_label(kind: &str) -> &'static str {
    match kind {
        "origin" => "origin",
        "goal" => "goal",
        "sourced" => "sourced",
        "inferred" => "inferred",
        "not_found" => "not found",
        "correction" => "correction",
        _ => "unknown",
    }
}

/// The nodes, edges and viewport of a snapshot. Pure, so it is tested without a runtime.
fn build_graph(snap: &BoardSnapshot) -> Graph {
    let mut depth: HashMap<String, u32> = HashMap::new();
    let mut nodes = Vec::new();
    let mut edges = Vec::new();
    let fact_of_intent: HashMap<&str, &BoardFact> =
        snap.facts.iter().filter(|f| !f.intent_id.is_empty()).map(|f| (f.intent_id.as_str(), f)).collect();

    for fact in snap.facts.iter().filter(|f| f.intent_id.is_empty()) {
        depth.insert(fact.fact_id.clone(), 0);
        nodes.push(fact_node(fact, 0));
    }
    let mut intents: Vec<&BoardIntent> = snap.intents.iter().collect();
    intents.sort_by_key(|i| (i.created_ms, intent_order(&i.intent_id)));
    for intent in intents {
        let d = intent.from_facts.iter().filter_map(|f| depth.get(f)).max().copied().unwrap_or(0) + 1;
        depth.insert(intent.intent_id.clone(), d);
        nodes.push(GraphNode {
            id: intent.intent_id.clone(),
            kind: NodeKind::Intent(intent.state.clone()),
            label: intent.objective.clone(),
            depth: d,
            dimmed: intent.state == "cancelled",
        });
        for from in &intent.from_facts {
            if depth.contains_key(from) {
                edges.push(GraphEdge { src: from.clone(), dst: intent.intent_id.clone() });
            }
        }
        if let Some(fact) = fact_of_intent.get(intent.intent_id.as_str()) {
            depth.insert(fact.fact_id.clone(), d + 1);
            nodes.push(fact_node(fact, d + 1));
            edges.push(GraphEdge { src: intent.intent_id.clone(), dst: fact.fact_id.clone() });
        }
    }

    let columns = nodes.iter().map(|n| n.depth).max().unwrap_or(0) + 1;
    let mut per_column: HashMap<u32, u32> = HashMap::new();
    for node in &nodes {
        *per_column.entry(node.depth).or_default() += 1;
    }
    let tallest = per_column.values().copied().max().unwrap_or(1);
    Graph {
        width: MIN_WIDTH.max(columns as f64 * COLUMN_WIDTH + 80.0),
        height: MIN_HEIGHT.max(tallest as f64 * ROW_HEIGHT + 60.0),
        nodes,
        edges,
    }
}

fn fact_node(fact: &BoardFact, depth: u32) -> GraphNode {
    GraphNode {
        id: fact.fact_id.clone(),
        kind: NodeKind::Fact(fact.kind.clone()),
        label: fact.text.clone(),
        depth,
        dimmed: fact.rejected,
    }
}

/// `i3.2` sorts as (3, 2), so `i10.1` comes after `i9.1`.
fn intent_order(id: &str) -> (u32, u32) {
    let mut parts = id.trim_start_matches('i').split('.').map(|p| p.parse().unwrap_or(0));
    (parts.next().unwrap_or(0), parts.next().unwrap_or(0))
}

fn target_x(depth: u32) -> f64 {
    40.0 + NODE_WIDTH / 2.0 + depth as f64 * COLUMN_WIDTH
}

/// The add/remove diff. Surviving nodes keep their place, a new node starts at the centroid
/// of its placed neighbours, or in a fixed spread down the middle when it has none.
fn seed_positions(graph: &Graph, previous: &HashMap<String, NodePosition>) -> HashMap<String, NodePosition> {
    let mut neighbours: HashMap<&str, Vec<&str>> = HashMap::new();
    for edge in &graph.edges {
        neighbours.entry(edge.src.as_str()).or_default().push(edge.dst.as_str());
        neighbours.entry(edge.dst.as_str()).or_default().push(edge.src.as_str());
    }
    let mut next: HashMap<String, NodePosition> = HashMap::with_capacity(graph.nodes.len());
    for (index, node) in graph.nodes.iter().enumerate() {
        if let Some(existing) = previous.get(&node.id) {
            next.insert(node.id.clone(), *existing);
            continue;
        }
        let placed: Vec<f64> = neighbours
            .get(node.id.as_str())
            .map(|list| list.iter().filter_map(|n| next.get(*n).or_else(|| previous.get(*n))).map(|p| p.y).collect())
            .unwrap_or_default();
        let y = if placed.is_empty() {
            graph.height / 2.0 + ((index % 7) as f64 - 3.0) * (graph.height / 18.0)
        } else {
            placed.iter().sum::<f64>() / placed.len() as f64 + ((index % 3) as f64 - 1.0) * 12.0
        };
        // A new node enters one column to the left, so it is seen to move into place.
        let x = target_x(node.depth.saturating_sub(1));
        next.insert(node.id.clone(), NodePosition { x, y, vx: 0.0, vy: 0.0 });
    }
    next
}

/// One step of the simulation, in place. O(n²) in the node count, which the explore budget
/// bounds to a few hundred.
fn simulate_tick(graph: &Graph, positions: &mut HashMap<String, NodePosition>) {
    let mut forces: HashMap<&str, (f64, f64)> = graph.nodes.iter().map(|n| (n.id.as_str(), (0.0, 0.0))).collect();
    for (index, a_node) in graph.nodes.iter().enumerate() {
        let Some(a) = positions.get(&a_node.id).copied() else { continue };
        for b_node in graph.nodes.iter().skip(index + 1) {
            let Some(b) = positions.get(&b_node.id).copied() else { continue };
            // Two nodes on the same point feel no direction. A fixed vertical direction
            // separates them, or they stay on top of each other for ever.
            let (dx, dy) = if a.x == b.x && a.y == b.y { (0.0, 1.0) } else { (a.x - b.x, a.y - b.y) };
            let distance_squared = (dx * dx + dy * dy).max(25.0);
            let distance = distance_squared.sqrt();
            let magnitude = REPULSION / distance_squared;
            let (fx, fy) = (dx / distance * magnitude, dy / distance * magnitude);
            if let Some(force) = forces.get_mut(a_node.id.as_str()) {
                force.0 += fx;
                force.1 += fy;
            }
            if let Some(force) = forces.get_mut(b_node.id.as_str()) {
                force.0 -= fx;
                force.1 -= fy;
            }
        }
    }
    for edge in &graph.edges {
        let (Some(a), Some(b)) = (positions.get(&edge.src).copied(), positions.get(&edge.dst).copied()) else {
            continue;
        };
        let dy = b.y - a.y;
        if let Some(force) = forces.get_mut(edge.src.as_str()) {
            force.1 += dy * EDGE_PULL;
        }
        if let Some(force) = forces.get_mut(edge.dst.as_str()) {
            force.1 -= dy * EDGE_PULL;
        }
    }
    for node in &graph.nodes {
        let Some(position) = positions.get_mut(&node.id) else { continue };
        let (mut fx, mut fy) = forces.get(node.id.as_str()).copied().unwrap_or((0.0, 0.0));
        fx += (target_x(node.depth) - position.x) * DEPTH_SPRING;
        fy += (graph.height / 2.0 - position.y) * CENTRING;
        position.vx = (position.vx + fx) * DAMPING;
        position.vy = (position.vy + fy) * DAMPING;
        position.x = (position.x + position.vx).clamp(NODE_WIDTH / 2.0 + 4.0, graph.width - NODE_WIDTH / 2.0 - 4.0);
        position.y = (position.y + position.vy).clamp(NODE_HEIGHT / 2.0 + 4.0, graph.height - NODE_HEIGHT / 2.0 - 4.0);
    }
}

fn render_edge(edge: &GraphEdge, layout: &HashMap<String, NodePosition>) -> Element {
    let (Some(src), Some(dst)) = (layout.get(&edge.src), layout.get(&edge.dst)) else {
        return rsx! {};
    };
    let (x1, x2) = (src.x + NODE_WIDTH / 2.0, dst.x - NODE_WIDTH / 2.0);
    rsx! {
        line {
            key: "{edge.src}-{edge.dst}",
            x1: "{x1}", y1: "{src.y}", x2: "{x2}", y2: "{dst.y}",
            stroke: "rgba(0,0,0,0.35)",
            stroke_width: "1.4",
            marker_end: "url(#x-board-arrow)",
        }
    }
}

/// Fill, border colour, dash pattern and the short tag of a node.
fn node_style(kind: &NodeKind) -> (&'static str, &'static str, &'static str, String) {
    match kind {
        NodeKind::Fact(k) => {
            let (fill, stroke) = match k.as_str() {
                "origin" | "goal" => ("#1a73e8", "#0b57d0"),
                "sourced" => ("#e6f4ea", "#1e8e3e"),
                "inferred" => ("#fef7e0", "#e37400"),
                "not_found" => ("#f1f3f4", "#80868b"),
                "correction" => ("#f3e8fd", "#9334e6"),
                _ => ("#ffffff", "#80868b"),
            };
            (fill, stroke, "", kind_label(k).to_string())
        }
        NodeKind::Intent(state) => {
            let stroke = match state.as_str() {
                "running" => "#1a73e8",
                "concluded" => "#1e8e3e",
                "failed" => "#d93025",
                "question" => "#e37400",
                _ => "#80868b",
            };
            ("#ffffff", stroke, "5 4", format!("intent, {state}"))
        }
    }
}

fn render_node(
    node: &GraphNode,
    layout: &HashMap<String, NodePosition>,
    selected: &str,
    on_select: Callback<String>,
) -> Element {
    let Some(position) = layout.get(&node.id) else { return rsx! {} };
    let (fill, stroke, dash, tag) = node_style(&node.kind);
    let is_selected = node.id == selected;
    let anchor = matches!(&node.kind, NodeKind::Fact(k) if k == "origin" || k == "goal");
    let text_colour = if anchor { "#ffffff" } else { "#111827" };
    let sub_colour = if anchor { "rgba(255,255,255,0.85)" } else { "rgba(0,0,0,0.55)" };
    let running = matches!(&node.kind, NodeKind::Intent(s) if s == "running");
    let stroke_width = if is_selected { "3" } else if running { "2.4" } else { "1.2" };
    let opacity = if node.dimmed { "0.4" } else { "1" };
    let (first, second) = two_lines(&node.label, 29);
    let id = node.id.clone();
    rsx! {
        g {
            key: "{node.id}",
            class: "x-board-node",
            "data-node": "{node.id}",
            opacity: "{opacity}",
            style: "cursor: pointer;",
            transform: "translate({position.x - NODE_WIDTH / 2.0}, {position.y - NODE_HEIGHT / 2.0})",
            onclick: move |_| on_select.call(id.clone()),
            rect {
                width: "{NODE_WIDTH}", height: "{NODE_HEIGHT}", rx: "8",
                fill: "{fill}", stroke: "{stroke}", stroke_width: "{stroke_width}", stroke_dasharray: "{dash}",
            }
            text { x: "9", y: "17", font_size: "12", fill: "{text_colour}", "{first}" }
            text { x: "9", y: "32", font_size: "12", fill: "{text_colour}", "{second}" }
            text { x: "9", y: "49", font_size: "11", fill: "{sub_colour}", "{node.id} \u{00b7} {tag}" }
        }
    }
}

/// The first two lines of `text`, broken at spaces, each at most `width` characters. The
/// second line ends in an ellipsis when text remains.
fn two_lines(text: &str, width: usize) -> (String, String) {
    let mut lines = vec![String::new(), String::new()];
    let mut line = 0;
    let mut cut = false;
    for word in text.split_whitespace() {
        let needed = lines[line].chars().count() + word.chars().count() + usize::from(!lines[line].is_empty());
        if needed > width {
            if line == 1 || lines[line].is_empty() {
                cut = true;
                break;
            }
            line = 1;
        }
        if !lines[line].is_empty() {
            lines[line].push(' ');
        }
        lines[line].push_str(word);
    }
    if cut {
        let kept: String = lines[1].chars().take(width.saturating_sub(1)).collect();
        lines[1] = format!("{kept}\u{2026}");
    }
    (lines[0].clone(), lines[1].clone())
}

#[cfg(test)]
mod tests {
    use super::*;
    use common::board_types::BoardDefinition;

    fn fact(id: &str, kind: &str, intent: &str) -> BoardFact {
        BoardFact {
            fact_id: id.into(),
            kind: kind.into(),
            text: id.into(),
            intent_id: intent.into(),
            session_id: String::new(),
            open_questions: vec![],
            problems: vec![],
            rejected: false,
            created_ms: 0,
            citations: vec![],
        }
    }

    fn intent(id: &str, from: &[&str], created_ms: i64) -> BoardIntent {
        BoardIntent {
            intent_id: id.into(),
            from_facts: from.iter().map(|f| f.to_string()).collect(),
            objective: id.into(),
            brief: String::new(),
            state: "concluded".into(),
            attempts: 1,
            session_id: String::new(),
            fact_id: String::new(),
            question: String::new(),
            last_error: String::new(),
            created_ms,
        }
    }

    fn snapshot(facts: Vec<BoardFact>, intents: Vec<BoardIntent>) -> BoardSnapshot {
        BoardSnapshot {
            board: BoardDefinition {
                board_id: "b".into(),
                owner: "o".into(),
                title: "t".into(),
                goal: "g".into(),
                context: String::new(),
                collections: vec![],
                llm_model: String::new(),
                max_explores: 12,
                max_parallel: 1,
                explore_step_budget: 40,
                created_ms: 0,
            },
            status: "active".into(),
            explores_used: 0,
            reasons_done: 0,
            stall_count: 0,
            review_statement: String::new(),
            review_from: vec![],
            facts,
            intents,
            events: vec![],
        }
    }

    #[test]
    fn a_long_label_breaks_at_spaces_into_two_lines() {
        let (a, b) = two_lines("Identify concerns raised about LJM partnerships in 2001 by staff", 32);
        assert_eq!(a, "Identify concerns raised about");
        assert!(b.starts_with("LJM partnerships in 2001") && b.ends_with('\u{2026}'));
        assert_eq!(two_lines("short", 32), ("short".to_string(), String::new()));
    }

    #[test]
    fn depth_follows_the_facts_an_intent_names() {
        let snap = snapshot(
            vec![fact("origin", "origin", ""), fact("goal", "goal", ""), fact("f1.1", "sourced", "i1.1"),
                 fact("f2.1", "inferred", "i2.1")],
            vec![intent("i1.1", &["goal"], 1), intent("i2.1", &["f1.1"], 2)],
        );
        let graph = build_graph(&snap);
        let depth: HashMap<&str, u32> = graph.nodes.iter().map(|n| (n.id.as_str(), n.depth)).collect();
        assert_eq!(depth["goal"], 0);
        assert_eq!(depth["i1.1"], 1);
        assert_eq!(depth["f1.1"], 2);
        assert_eq!(depth["i2.1"], 3);
        assert_eq!(depth["f2.1"], 4);
        assert_eq!(graph.edges.len(), 4);
    }

    #[test]
    fn a_new_node_starts_near_its_placed_neighbour_and_survivors_keep_their_place() {
        let first = build_graph(&snapshot(vec![fact("goal", "goal", "")], vec![]));
        let placed = seed_positions(&first, &HashMap::new());
        let goal_y = placed["goal"].y;
        let second = build_graph(&snapshot(vec![fact("goal", "goal", "")], vec![intent("i1.1", &["goal"], 1)]));
        let seeded = seed_positions(&second, &placed);
        assert_eq!(seeded["goal"], placed["goal"]);
        assert!((seeded["i1.1"].y - goal_y).abs() <= 12.0);
    }

    #[test]
    fn two_nodes_seeded_on_one_point_separate() {
        let snap = snapshot(
            vec![fact("origin", "origin", "")],
            vec![intent("i1.1", &["origin"], 1), intent("i1.2", &["origin"], 1)],
        );
        let graph = build_graph(&snap);
        let mut positions = seed_positions(&graph, &HashMap::new());
        let same = positions["i1.1"];
        positions.insert("i1.2".to_string(), same);
        for _ in 0..MAX_TICKS {
            simulate_tick(&graph, &mut positions);
        }
        assert!((positions["i1.1"].y - positions["i1.2"].y).abs() > NODE_HEIGHT);
    }

    #[test]
    fn the_simulation_stays_finite_and_inside_the_viewport() {
        let snap = snapshot(
            vec![fact("origin", "origin", ""), fact("goal", "goal", "")],
            vec![intent("i1.1", &["goal"], 1), intent("i1.2", &["goal"], 1), intent("i1.3", &["origin"], 1)],
        );
        let graph = build_graph(&snap);
        let mut positions = seed_positions(&graph, &HashMap::new());
        for _ in 0..MAX_TICKS {
            simulate_tick(&graph, &mut positions);
        }
        for p in positions.values() {
            assert!(p.x.is_finite() && p.y.is_finite());
            assert!(p.x > 0.0 && p.x < graph.width && p.y > 0.0 && p.y < graph.height);
        }
    }
}
