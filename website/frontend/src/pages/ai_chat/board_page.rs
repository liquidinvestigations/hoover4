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
//! The graph keeps its node size at every node count. The pane scrolls, a drag pans it, and a
//! corner control sets the zoom, which is the `zoom` value of the address.
//!
//! `selected` is the slug of a node in the address, so a selected node is a link. The page
//! resolves it by slug first and then by storage id, so a link written before the slugs keeps
//! working. Every place that shows a node names it by its slug.

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
use dioxus_free_icons::icons::md_content_icons::{MdAdd, MdRemove};
use dioxus_free_icons::icons::md_navigation_icons::MdArrowDownward;
use dioxus_free_icons::Icon;

use crate::components::admin_components::{
    ErrorBar, BTN, BTN_PRIMARY, BTN_SMALL, BTN_SMALL_DANGER, HELP_TEXT, INPUT, LINK, SUBHEADING, TABLE, TD, TH,
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
pub fn AiBoardPage(board_id: String, selected: String, zoom: String) -> Element {
    rsx! {
        Title { "Hoover Search - Board" }
        div {
            style: "width: 100%; height: 100%; background: #F5F6F8; box-sizing: border-box; padding: 15px 23px; overflow: auto; font-family: var(--x-font); font-size: var(--x-text-body); line-height: var(--x-line-body); color: var(--x-ink);",
            BoardExplorer { board_id, selected, zoom }
        }
    }
}

/// The zoom levels of the graph, in percent. An empty or unknown address value is 100.
pub const ZOOM_LEVELS: [u32; 4] = [50, 75, 100, 125];

pub fn parse_zoom(value: &str) -> u32 {
    value.trim().parse::<u32>().ok().filter(|z| ZOOM_LEVELS.contains(z)).unwrap_or(100)
}

/// The zoom level after `current` in the direction `step` (-1 or +1), or `None` at the end of
/// the range.
pub fn next_zoom(current: u32, step: i32) -> Option<u32> {
    let index = ZOOM_LEVELS.iter().position(|z| *z == current)? as i32 + step;
    ZOOM_LEVELS.get(usize::try_from(index).ok()?).copied()
}

/// The scroll offset that keeps the graph point at the middle of the pane after a zoom
/// change, for one axis.
pub fn zoom_scroll(old_scroll: f64, pane_size: f64, old_zoom: u32, new_zoom: u32) -> f64 {
    ((old_scroll + pane_size / 2.0) * new_zoom as f64 / old_zoom as f64 - pane_size / 2.0).max(0.0)
}

const GRAPH_PANE_ID: &str = "x-board-graph-pane";
/// Pixels that the pointer moves before a press on the graph becomes a pan.
const PAN_THRESHOLD: f64 = 4.0;

fn graph_pane() -> Option<web_sys::Element> {
    web_sys::window()?.document()?.get_element_by_id(GRAPH_PANE_ID)
}

/// A press on the graph pane: the client point and the scroll at the press.
#[derive(Clone, Copy, PartialEq)]
struct PanStart {
    x: f64,
    y: f64,
    left: i32,
    top: i32,
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

/// The slugs of node ids, joined for a sentence.
fn slugs(snap: &BoardSnapshot, ids: &[String]) -> String {
    ids.iter().map(|id| snap.slug_of(id)).collect::<Vec<_>>().join(", ")
}

/// Open `route` in a new browser tab.
fn open_in_new_tab(route: Route) {
    if let Some(window) = web_sys::window() {
        let _ = window.open_with_url_and_target(&route.to_string(), "_blank");
    }
}

#[component]
fn BoardExplorer(board_id: ReadSignal<String>, selected: ReadSignal<String>, zoom: ReadSignal<String>) -> Element {
    let snapshot = use_signal(|| None::<BoardSnapshot>);
    let error = use_signal(|| None::<String>);
    let mut show_settings = use_signal(|| false);
    // Pan and zoom of the graph pane. See `GraphPane`.
    let mut press = use_signal(|| None::<PanStart>);
    let mut dragging = use_signal(|| false);
    let mut suppress_click = use_signal(|| false);
    let mut zoom_from = use_signal(|| None::<(u32, f64, f64, f64, f64)>);

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

    // After a zoom change the graph renders at its new size first. Then the pane scrolls so
    // that the graph point that was in its middle is in its middle again.
    use_effect(move || {
        let level = parse_zoom(&zoom.read());
        let Some((old, left, top, width, height)) = *zoom_from.peek() else { return };
        zoom_from.set(None);
        if let Some(pane) = graph_pane() {
            pane.set_scroll_left(zoom_scroll(left, width, old, level).round() as i32);
            pane.set_scroll_top(zoom_scroll(top, height, old, level).round() as i32);
        }
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

    let selected_id = snap.resolve_node(&selected.read()).unwrap_or_default();
    let (graph, positions) = layout.read().clone();
    let level = parse_zoom(&zoom.read());
    let scale = f64::from(level) / 100.0;
    let board_key = snap.board.board_id.clone();
    // A node id goes into the address as its slug, with the zoom kept.
    let slug_snap = snap.clone();
    let on_select = Callback::new(move |id: String| {
        let selected = if id.is_empty() { id } else { slug_snap.slug_of(&id) };
        navigator().push(Route::AiBoardPage { board_id: board_key.clone(), selected, zoom: zoom.peek().clone() });
    });
    // A click that ends a pan does not select the node under the pointer.
    let on_node = Callback::new(move |id: String| {
        if *suppress_click.peek() {
            suppress_click.set(false);
            return;
        }
        on_select.call(id);
    });
    let zoom_board = snap.board.board_id.clone();
    let set_zoom = Callback::new(move |next: u32| {
        if let Some(pane) = graph_pane() {
            zoom_from.set(Some((level, f64::from(pane.scroll_left()), f64::from(pane.scroll_top()),
                                f64::from(pane.client_width()), f64::from(pane.client_height()))));
        }
        navigator().replace(Route::AiBoardPage {
            board_id: zoom_board.clone(),
            selected: selected.peek().clone(),
            zoom: if next == 100 { String::new() } else { next.to_string() },
        });
    });
    let zoom_out = next_zoom(level, -1);
    let zoom_in = next_zoom(level, 1);

    let detail = if let Some(fact) = snap.facts.iter().find(|f| f.fact_id == selected_id) {
        rsx! { FactDetail { key: "{fact.fact_id}", board_id: snap.board.board_id.clone(), fact: fact.clone(), corrects: slugs(&snap, &fact.corrects), snapshot, error } }
    } else if let Some(intent) = snap.intents.iter().find(|i| i.intent_id == selected_id) {
        rsx! { IntentDetail { intent: intent.clone(), from: slugs(&snap, &intent.from_facts) } }
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
                style: "flex: 1 1 62%; min-width: 0; position: relative; border: 1px solid; border-color: var(--x-border); border-radius: 8px; background: white; overflow: hidden;",
                div {
                    id: GRAPH_PANE_ID,
                    class: "x-board-graph-pane",
                    "data-dragging": "{dragging()}",
                    style: "width: 100%; height: 100%;",
                    onmousedown: move |e: Event<MouseData>| {
                        if e.trigger_button() != Some(dioxus::html::input_data::MouseButton::Primary) {
                            return;
                        }
                        let point = e.client_coordinates();
                        if let Some(pane) = graph_pane() {
                            suppress_click.set(false);
                            press.set(Some(PanStart { x: point.x, y: point.y, left: pane.scroll_left(), top: pane.scroll_top() }));
                        }
                    },
                    onmousemove: move |e: Event<MouseData>| {
                        let Some(start) = *press.peek() else { return };
                        if e.held_buttons().is_empty() {
                            press.set(None);
                            return;
                        }
                        let point = e.client_coordinates();
                        if (point.x - start.x).hypot(point.y - start.y) > PAN_THRESHOLD {
                            dragging.set(true);
                        }
                    },
                    onmouseup: move |_| press.set(None),
                    svg {
                        class: "x-board-graph-svg",
                        width: "{graph.width * scale}",
                        height: "{graph.height * scale}",
                        view_box: "0 0 {graph.width} {graph.height}",
                        ArrowMarker { id: "x-board-arrow" }
                        for edge in graph.edges.iter() {
                            {render_edge(edge, &positions, &graph, "x-board-arrow")}
                        }
                        for node in graph.nodes.iter() {
                            {render_node(node, &positions, &selected_id, on_node)}
                        }
                    }
                }
                div { class: "x-board-zoom",
                    button {
                        "aria-label": "Zoom out", title: "Zoom out",
                        disabled: zoom_out.is_none(),
                        onclick: move |_| if let Some(next) = zoom_out { set_zoom.call(next) },
                        Icon { icon: MdRemove, style: "width: 15px; height: 15px;" }
                    }
                    span { class: "x-board-zoom-level", "{level}%" }
                    button {
                        "aria-label": "Zoom in", title: "Zoom in",
                        disabled: zoom_in.is_none(),
                        onclick: move |_| if let Some(next) = zoom_in { set_zoom.call(next) },
                        Icon { icon: MdAdd, style: "width: 15px; height: 15px;" }
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
        // While a pan runs, this layer takes the mouse, so a release outside the pane ends it.
        // It shows only after the threshold: a press and release without a move stays a click
        // on the node under the pointer.
        if dragging() {
            div {
                style: "position: fixed; inset: 0; z-index: 3000; cursor: grabbing; user-select: none;",
                onmousemove: move |e: Event<MouseData>| {
                    let Some(start) = *press.peek() else { return };
                    let point = e.client_coordinates();
                    if let Some(pane) = graph_pane() {
                        pane.set_scroll_left(start.left - (point.x - start.x).round() as i32);
                        pane.set_scroll_top(start.top - (point.y - start.y).round() as i32);
                    }
                },
                onmouseup: move |_| {
                    press.set(None);
                    dragging.set(false);
                    suppress_click.set(true);
                },
                onmouseleave: move |_| {
                    press.set(None);
                    dragging.set(false);
                },
            }
        }
    }
}

/// A section heading of the board pages.
const SECTION: &str = "margin: 0 0 8px; font-size: var(--x-text-section); line-height: var(--x-line-section); font-weight: 600; color: var(--x-ink-strong);";

#[component]
fn BoardHeader(snap: BoardSnapshot, on_settings: EventHandler<()>) -> Element {
    rsx! {
        div { style: "display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 10px;",
            Link { to: Route::AiChatPage {}, style: LINK, "\u{2190} AI Chat" }
            h1 { style: "margin: 0; font-size: var(--x-text-page); line-height: var(--x-line-page); font-weight: 600; color: var(--x-ink-strong);", "{snap.board.title}" }
            StatusText { status: snap.status.clone() }
            span { style: "flex: 1;" }
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
                div { style: SECTION, "The board waits for your review" }
                if snap.review_goals.is_empty() && snap.review_statement.is_empty() {
                    p { style: HELP_TEXT, "The board stopped without a statement: the explore budget is used or the work stalled." }
                }
                if snap.review_goals.is_empty() && !snap.review_statement.is_empty() {
                    p { "{snap.review_statement}" }
                    p { style: HELP_TEXT, "From the facts {slugs(&snap, &snap.review_from)}." }
                }
                for goal in goals.iter() {
                    if let Some(review) = statement_of(&goal.fact_id) {
                        div { key: "{goal.fact_id}", class: "x-board-review-goal", style: "margin: 8px 0;",
                            div { style: "font-weight: 600;", span { style: "font-family: monospace; font-weight: 400; color: var(--x-ink-muted); margin-right: 6px;", "{goal.slug}" } "{goal.text}" }
                            p { style: "margin: 4px 0;", "{review.statement}" }
                            if !review.from.is_empty() {
                                p { style: HELP_TEXT, "From the facts {slugs(&snap, &review.from)}." }
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
            div { style: SECTION, if goals.len() == 1 { "Goal" } else { "Goals" } }
            for goal in goals.iter() {
                div { key: "{goal.fact_id}", style: "margin: 4px 0;",
                    if goals.len() > 1 { span { style: "font-family: monospace; color: var(--x-ink-muted); margin-right: 6px;", "{goal.slug}" } }
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
        }
        if snap.status == "active" || snap.status == "paused" {
            div { style: PANEL,
                div { style: SECTION, "Add a hint" }
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
            div { style: SECTION, "Events" }
            table { class: "x-board-events", style: TABLE,
                thead {
                    tr {
                        th { style: TH, title: "Newest first",
                            span { style: "display: inline-flex; align-items: center; gap: 4px;",
                                "Date"
                                Icon { icon: MdArrowDownward, style: "width: 15px; height: 15px; color: var(--x-ink-muted);" }
                            }
                        }
                        th { style: TH, "Actor" }
                        th { style: TH, "Event" }
                    }
                }
                tbody {
                    for event in snap.events.iter().rev().take(200) {
                        tr { key: "{event.event_id}",
                            td { style: "{TD} white-space: nowrap;", "{format_utc_ms(event.created_ms)}" }
                            td { style: "{TD} {actor_style(&event.actor)}", class: "x-board-event-actor", "{event.actor}" }
                            td { style: TD,
                                "{event.summary}"
                                if !event.quote.is_empty() {
                                    ": "
                                    em { class: "x-board-event-quote", "{event.quote}" }
                                }
                            }
                        }
                    }
                }
            }
        }
        BoardStatistics { snap: snap.clone() }
    }
}

/// The actors that are the system: their name shows in italic, and a person's in bold.
const SYSTEM_ACTORS: [&str; 4] = ["dispatcher", "reason", "explore", "worker"];

fn actor_style(actor: &str) -> &'static str {
    if SYSTEM_ACTORS.contains(&actor) {
        "font-style: italic; font-weight: 400; color: var(--x-ink-muted);"
    } else {
        "font-weight: 600; color: var(--x-ink-strong);"
    }
}

/// The counts of a board, with `noun` after each nonzero entry, joined. The first entries
/// always show.
fn count_line(entries: &[(usize, &str, bool)]) -> String {
    entries.iter().filter(|(n, _, always)| *always || *n > 0)
        .map(|(n, label, _)| format!("{n} {label}")).collect::<Vec<_>>().join(", ")
}

/// The numbers and settings of a board, under the events.
#[component]
fn BoardStatistics(snap: BoardSnapshot) -> Element {
    let intents = |state: &str| snap.intents.iter().filter(|i| i.state == state).count();
    let facts = |kind: &str| snap.facts.iter().filter(|f| f.kind == kind && !f.rejected).count();
    let rejected = snap.facts.iter().filter(|f| f.rejected).count();
    let intent_line = count_line(&[
        (intents("concluded"), "concluded", true), (intents("running"), "running", true),
        (intents("open"), "open", true), (intents("question"), "with a question", false),
        (intents("failed"), "failed", false), (intents("cancelled"), "cancelled", false),
    ]);
    let fact_line = count_line(&[
        (facts("sourced"), "sourced", true), (facts("inferred"), "inferred", true),
        (facts("not_found"), "not found", true), (facts("correction"), "corrections", true),
        (rejected, "rejected", false),
    ]);
    let internet = if snap.board.internet_tools { "On" } else { "Off" };
    rsx! {
        div { class: "x-board-statistics", style: PANEL,
            div { style: SECTION, "Statistics" }
            dl { class: "x-board-stats",
                dt { "Explores" } dd { "{snap.explores_used} of {snap.max_explores}" }
                dt { "Model steps per explore" } dd { "{snap.explore_steps}" }
                dt { "Reasons" } dd { "{snap.reasons_done}" }
                dt { "Intents" } dd { "{intent_line}" }
                dt { "Facts" } dd { "{fact_line}" }
                dt { "Collections" } dd { "{snap.board.collections.join(\", \")}" }
                dt { "Internet tools" } dd { "{internet}" }
                dt { "Budget" } dd { "A rejected fact or review adds explores and model steps. A hint adds a few." }
                dt { "Created" } dd { "{format_utc_ms(snap.board.created_ms)}" }
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
fn FactDetail(board_id: String, fact: BoardFact, corrects: String, snapshot: Signal<Option<BoardSnapshot>>, error: Signal<Option<String>>) -> Element {
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
            DetailHeader {
                title: if fact.title.is_empty() { kind_label(&fact.kind).to_string() } else { fact.title.clone() },
                slug: fact.slug.clone(),
                tags: fact_tags(&fact),
                rejected: fact.rejected,
            }
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
                p { style: HELP_TEXT, "This correction applies to the facts {corrects}." }
            }
            // The gray area behind the citation cards, as on the chat page, so the white cards
            // stand out.
            div { class: "x-board-fact-text", style: "margin: 6px 0; background: #ECEEF2; padding: 12px; border-radius: 8px;",
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
fn IntentDetail(intent: BoardIntent, from: String) -> Element {
    rsx! {
        div { class: "x-board-intent-detail", style: PANEL,
            DetailHeader {
                title: if intent.title.is_empty() { "Intent".to_string() } else { intent.title.clone() },
                slug: intent.slug.clone(),
                tags: vec!["intent".to_string(), intent.state.clone()],
                rejected: false,
            }
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

/// The tags of a fact in its detail pane, as on its node.
fn fact_tags(fact: &BoardFact) -> Vec<String> {
    let mut tags = vec![kind_label(&fact.kind).to_string()];
    if fact.rejected {
        tags.push("rejected".to_string());
    }
    tags
}

/// The head of a detail pane: the title in bold, then the slug and the tags in the meta style
/// of a node.
#[component]
fn DetailHeader(title: String, slug: String, tags: Vec<String>, rejected: bool) -> Element {
    let decoration = if rejected { "line-through" } else { "none" };
    rsx! {
        div { class: "x-board-detail-title", style: "{SECTION} margin: 0; text-decoration: {decoration};", "{title}" }
        div { class: "x-board-detail-meta",
            span { title: "{slug}", "{slug}" }
            span { style: "display: flex; gap: 6px; flex-shrink: 0;",
                for (i, tag) in tags.iter().enumerate() {
                    span { key: "{i}", "{tag}" }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_unknown_zoom_is_100_and_the_buttons_stop_at_the_ends() {
        assert_eq!(parse_zoom(""), 100);
        assert_eq!(parse_zoom("75"), 75);
        assert_eq!(parse_zoom("80"), 100);
        assert_eq!(next_zoom(50, -1), None);
        assert_eq!(next_zoom(50, 1), Some(75));
        assert_eq!(next_zoom(125, 1), None);
        assert_eq!(next_zoom(100, -1), Some(75));
    }

    #[test]
    fn a_zoom_change_keeps_the_middle_of_the_pane() {
        // At 100 % the pane of 800 px shows graph x 400 to 1200, middle 800.
        let left = zoom_scroll(400.0, 800.0, 100, 50);
        assert_eq!((left + 400.0) * 2.0, 800.0);
        assert_eq!(zoom_scroll(0.0, 800.0, 100, 50), 0.0);
    }

    #[test]
    fn a_system_actor_is_italic_and_a_person_bold() {
        assert!(actor_style("dispatcher").contains("italic"));
        assert!(actor_style("admin").contains("600"));
    }
}
