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
//! corner control sets the zoom, which is the `zoom` value of the address. When the selected
//! node is not wholly in the pane, at the first load or after a link in a detail pane selects
//! it, the pane scrolls it to the middle. A click on a node does not scroll.
//!
//! `selected` is the slug of a node in the address, so a selected node is a link. The page
//! resolves it by slug first and then by storage id, so a link written before the slugs keeps
//! working. The address, the event lines and the link column name a node by its slug. The
//! cards and the detail panes show its type and statuses (`board_graph::corners`).
//!
//! `assessment` in the address opens the details popup of that assessment: its prompt and
//! its response, read from `board_assessments` when the popup opens.

use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;
use std::time::Duration;

use common::board_types::{
    BoardAssessment, BoardEvent, BoardFact, BoardIntent, BoardReviewGoal, BoardSnapshot, MAX_GOALS,
};
use common::chat_types::{ChatDocRef, card_find_phrase};
use common::search_result::{DocumentIdentifier, SearchResultDocuments, SearchResultHitCount};
use dioxus::prelude::*;

use crate::api::board_api::{
    board_add_goal, board_add_hint, board_answer, board_assessment, board_drop, board_explore_question,
    board_reject_fact, board_review, board_set_internet_tools, board_set_paused, board_snapshot,
};
use crate::api::error_util::user_facing_message;
use dioxus_free_icons::icons::md_content_icons::{MdAdd, MdRemove};
use dioxus_free_icons::icons::md_navigation_icons::MdArrowDownward;
use dioxus_free_icons::Icon;

use crate::components::admin_components::{
    ErrorBar, BTN, BTN_PRIMARY, BTN_SMALL, BTN_SMALL_DANGER, HELP_TEXT, INPUT, LINK, SUBHEADING, TABLE, TD, TH,
};
use crate::components::board_graph::{
    build_graph, corners, render_edge, render_node, settle, ArrowMarker, NodeKind, NodePosition,
};
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
pub fn AiBoardPage(board_id: String, selected: String, zoom: String, assessment: String) -> Element {
    // No top padding: the header row has the height of the logo box of the left bar, so the
    // two share one middle line (`HEADER_HEIGHT`).
    rsx! {
        Title { "Hoover Search - Board" }
        div {
            style: "width: 100%; height: 100%; background: #F5F6F8; box-sizing: border-box; padding: 0 23px 15px; overflow: auto; font-family: var(--x-font); font-size: var(--x-text-body); line-height: var(--x-line-body); color: var(--x-ink);",
            BoardExplorer { board_id, selected, zoom, assessment }
        }
    }
}

/// The height of the board page header row. The logo box of the left bar spans 4 to 41 px
/// from the top of the window, so a row of this height from the top of the page has its middle
/// on the middle of the logo.
const HEADER_HEIGHT: &str = "45px";

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

/// Scroll the graph pane so the graph point under the press follows the pointer.
fn pan_to(start: PanStart, x: f64, y: f64) {
    if let Some(pane) = graph_pane() {
        pane.set_scroll_left(start.left - (x - start.x).round() as i32);
        pane.set_scroll_top(start.top - (y - start.y).round() as i32);
    }
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

/// Whether the board can change soon: it is active, an explore runs or waits to start for an
/// open question, or the newest event is a person action that the worker has not answered
/// yet. A dropped board waits for nothing. On a completed board only a new goal and a
/// question explore start work, so its other person events do not count.
fn is_live(snapshot: &Option<BoardSnapshot>) -> bool {
    match snapshot {
        None => true,
        Some(s) if s.status == "dropped" => false,
        Some(s) => {
            let working = s.intents.iter().any(|i| i.state == "running" || (i.state == "open" && i.asked.is_some()));
            let waiting = s.events.last().is_some_and(|e| {
                if s.status == "completed" {
                    matches!(e.event_type.as_str(), "goal_added" | "question_explored")
                } else {
                    !SYSTEM_ACTORS.contains(&e.actor.as_str())
                }
            });
            s.status == "active" || working || waiting
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
fn BoardExplorer(
    board_id: ReadSignal<String>,
    selected: ReadSignal<String>,
    zoom: ReadSignal<String>,
    assessment: ReadSignal<String>,
) -> Element {
    let snapshot = use_signal(|| None::<BoardSnapshot>);
    let error = use_signal(|| None::<String>);
    let mut show_settings = use_signal(|| false);
    // Pan and zoom of the graph pane. See `GraphPane`.
    let mut press = use_signal(|| None::<PanStart>);
    let mut dragging = use_signal(|| false);
    let mut suppress_click = use_signal(|| false);
    let mut zoom_from = use_signal(|| None::<(u32, f64, f64, f64, f64)>);
    // The node id that the scroll of `D29` last handled. A node click sets it before it
    // selects the node, so a click does not scroll.
    let mut scrolled_for = use_signal(String::new);

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
            // An idle board is read every `IDLE_POLL_SECONDS`. The wait is checked every
            // `LIVE_POLL_SECONDS`, so a person action that a control reloads at once (a goal, a
            // question) makes the board live and shortens the wait.
            let mut waited = 0;
            loop {
                n0_future::time::sleep(Duration::from_secs(LIVE_POLL_SECONDS)).await;
                waited += LIVE_POLL_SECONDS;
                if waited >= IDLE_POLL_SECONDS || is_live(&snapshot.peek()) || *board_id.peek() != shown {
                    break;
                }
            }
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

    // Scroll the selected node into the pane when it is not wholly visible. It runs after the
    // render that draws the node, and once for each selected node.
    use_effect(move || {
        let key = selected.read().clone();
        let _ = layout.read();
        let Some(id) = snapshot.peek().as_ref().and_then(|s| s.resolve_node(&key)) else { return };
        if *scrolled_for.peek() == id {
            return;
        }
        let Some(pane) = graph_pane() else { return };
        let Ok(Some(node)) = pane.query_selector(&format!("[data-node=\"{id}\"]")) else { return };
        scrolled_for.set(id);
        let (p, n) = (pane.get_bounding_client_rect(), node.get_bounding_client_rect());
        let inside = n.left() >= p.left() && n.right() <= p.right() && n.top() >= p.top() && n.bottom() <= p.bottom();
        if !inside {
            let dx = (n.left() + n.right()) / 2.0 - (p.left() + p.right()) / 2.0;
            let dy = (n.top() + n.bottom()) / 2.0 - (p.top() + p.bottom()) / 2.0;
            pane.set_scroll_left(pane.scroll_left() + dx.round() as i32);
            pane.set_scroll_top(pane.scroll_top() + dy.round() as i32);
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
        navigator().push(Route::AiBoardPage {
            board_id: board_key.clone(),
            selected,
            zoom: zoom.peek().clone(),
            assessment: String::new(),
        });
    });
    // A click that ends a pan does not select the node under the pointer. A click on a node
    // does not scroll the pane: the node is in view.
    let on_node = Callback::new(move |id: String| {
        if *suppress_click.peek() {
            suppress_click.set(false);
            return;
        }
        scrolled_for.set(id.clone());
        on_select.call(id);
    });
    let popup_board = snap.board.board_id.clone();
    let set_assessment = Callback::new(move |number: Option<u32>| {
        navigator().replace(Route::AiBoardPage {
            board_id: popup_board.clone(),
            selected: selected.peek().clone(),
            zoom: zoom.peek().clone(),
            assessment: number.map(|n| n.to_string()).unwrap_or_default(),
        });
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
            assessment: assessment.peek().clone(),
        });
    });
    let zoom_out = next_zoom(level, -1);
    let zoom_in = next_zoom(level, 1);

    let zoom_value = zoom.read().clone();
    let detail = if let Some(fact) = snap.facts.iter().find(|f| f.fact_id == selected_id) {
        rsx! { FactDetail { key: "{fact.fact_id}", snap: snap.clone(), fact: fact.clone(), zoom: zoom_value.clone(), snapshot, error } }
    } else if let Some(intent) = snap.intents.iter().find(|i| i.intent_id == selected_id) {
        rsx! { IntentDetail { intent: intent.clone(), from: slugs(&snap, &intent.from_facts) } }
    } else {
        rsx! { BoardOverview { snap: snap.clone(), zoom: zoom_value.clone(), on_details: set_assessment, snapshot, error } }
    };
    let open_assessment = assessment.read().trim().parse::<u32>().ok();

    rsx! {
        if let Some(err) = error.read().clone() {
            ErrorBar { message: err }
        }
        BoardHeader { snap: snap.clone(), on_settings: move |_| show_settings.set(true) }
        if show_settings() {
            BoardSettings { snap: snap.clone(), snapshot, error, on_close: move |_| show_settings.set(false) }
        }
        if let Some(number) = open_assessment {
            AssessmentDetails {
                key: "{number}",
                board_id: snap.board.board_id.clone(),
                reason_no: number,
                on_close: move |_| set_assessment.call(None),
            }
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
                    // The press blocks its default action. Firefox otherwise starts a text
                    // selection and sends every later move to this pane, also over the
                    // overlay below, so the pane's own handlers pan as well.
                    onmousedown: move |e: Event<MouseData>| {
                        if e.trigger_button() != Some(dioxus::html::input_data::MouseButton::Primary) {
                            return;
                        }
                        e.prevent_default();
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
                            dragging.set(false);
                            return;
                        }
                        let point = e.client_coordinates();
                        if *dragging.peek() {
                            pan_to(start, point.x, point.y);
                        } else if (point.x - start.x).hypot(point.y - start.y) > PAN_THRESHOLD {
                            dragging.set(true);
                            pan_to(start, point.x, point.y);
                        }
                    },
                    onmouseup: move |_| {
                        press.set(None);
                        if *dragging.peek() {
                            dragging.set(false);
                            suppress_click.set(true);
                        }
                    },
                    svg {
                        class: "x-board-graph-svg",
                        width: "{graph.width * scale}",
                        height: "{graph.height * scale}",
                        view_box: "0 0 {graph.width} {graph.height}",
                        ArrowMarker { id: "x-board-arrow" }
                        for edge in graph.edges.iter() {
                            {render_edge(edge, &positions, "x-board-arrow")}
                        }
                        for node in graph.nodes.iter() {
                            {render_node(node, &positions, &selected_id, on_node)}
                        }
                    }
                }
                if !selected_id.is_empty() {
                    button { class: "x-board-overview-open", onclick: move |_| on_select.call(String::new()), "Show the board overview" }
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
                    pan_to(start, point.x, point.y);
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
        div { class: "x-board-header", style: "height: {HEADER_HEIGHT}; margin-bottom: 4px;",
            Link { to: Route::AiChatPage {}, style: "color: var(--x-link); text-decoration: none;", "\u{2190} AI Chat" }
            h1 { "{snap.board.title}" }
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
fn BoardOverview(
    snap: BoardSnapshot,
    zoom: String,
    on_details: Callback<Option<u32>>,
    snapshot: Signal<Option<BoardSnapshot>>,
    error: Signal<Option<String>>,
) -> Element {
    let mut hint = use_signal(String::new);
    let mut correction = use_signal(String::new);
    let mut goal = use_signal(String::new);
    let mut adding_goal = use_signal(|| false);
    let mut error = error;
    let board_id = snap.board.board_id.clone();
    let goals: Vec<BoardFact> = snap.goals().into_iter().cloned().collect();
    let dropped = snap.status == "dropped";
    rsx! {
        if snap.status == "review" {
            div { class: "x-board-review", style: "{PANEL} border-color: var(--x-danger);",
                div { style: SECTION, "The board waits for your review" }
                if !snap.answers_proposed.is_empty() {
                    p { style: HELP_TEXT, "Accept or reject the proposed answer of each goal below. A rejected answer lets the board continue at once." }
                } else if snap.review_statement.is_empty() {
                    p { style: HELP_TEXT, "The board stopped without answers: the explore budget is used or the work stalled." }
                } else {
                    p { "{snap.review_statement}" }
                }
                p { style: HELP_TEXT, "Finish the board to accept every proposed answer and stop it, or continue it with a correction." }
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
                        "Finish the board"
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
                    "Continue with a correction"
                }
            }
        }
        div { style: PANEL,
            div { style: SECTION, if goals.len() == 1 { "Goal" } else { "Goals" } }
            for goal in goals.iter() {
                div { key: "{goal.fact_id}", style: "margin: 4px 0;",
                    if goals.len() > 1 { span { style: "font-family: monospace; color: var(--x-ink-muted); margin-right: 6px;", "{goal.slug}" } }
                    "{goal.text}"
                    {
                        let answer = goal_answer(&snap, &goal.fact_id);
                        let from: Vec<String> = answer.as_ref().map(|(a, _)| a.from.iter().map(|f| snap.slug_of(f)).collect()).unwrap_or_default();
                        rsx! {
                            GoalAnswer {
                                key: "{goal.fact_id}-{answer_key(&answer)}",
                                board_id: board_id.clone(),
                                answer,
                                from,
                                zoom: zoom.clone(),
                                dropped,
                                snapshot,
                                error,
                            }
                        }
                    }
                }
            }
            if snap.status != "dropped" && goals.len() < MAX_GOALS {
                div { class: "x-board-goal-form", style: "margin-top: 10px;",
                    textarea {
                        class: "x-board-goal",
                        style: TEXTAREA, rows: "2",
                        placeholder: "A new goal",
                        value: "{goal}", oninput: move |e| goal.set(e.value()),
                    }
                    p { style: HELP_TEXT, "The board works on the new goal next. A complete board starts again." }
                    button {
                        style: BTN,
                        disabled: adding_goal() || goal.read().trim().is_empty(),
                        onclick: {
                            let id = board_id.clone();
                            move |_| {
                                let id = id.clone();
                                let text = goal.read().clone();
                                adding_goal.set(true);
                                spawn(async move {
                                    match board_add_goal(id.clone(), text).await {
                                        Ok(()) => goal.set(String::new()),
                                        Err(e) => error.set(Some(user_facing_message(&e))),
                                    }
                                    adding_goal.set(false);
                                    reload(id, snapshot, error).await;
                                });
                            }
                        },
                        "Add goal"
                    }
                }
            }
            if !snap.board.context.is_empty() {
                div { style: SUBHEADING, "Background context" }
                p { style: "margin: 4px 0;", "{snap.board.context}" }
            }
        }
        if snap.status == "active" || snap.status == "paused" {
            div { style: PANEL,
                div { style: SECTION, "Add a hint" }
                p { style: HELP_TEXT, "The next assessment reads every hint. A hint also answers an explore that asked a question." }
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
                        th { style: TH, "aria-label": "Links" }
                    }
                }
                tbody {
                    for event in snap.events.iter().rev().take(200) {
                        tr { key: "{event.event_id}",
                            td { style: "{TD} white-space: nowrap;", "{format_utc_ms(event.created_ms)}" }
                            td { style: "{TD} {actor_style(&event.actor)}", class: "x-board-event-actor", "{actor_label(&event.actor)}" }
                            td { style: TD,
                                "{event.summary}"
                                if !event.quote.is_empty() {
                                    ": "
                                    em { class: "x-board-event-quote", "{event.quote}" }
                                }
                            }
                            td { style: "{TD} width: 1%;", class: "x-board-event-link",
                                match event_link(&snap, event) {
                                    EventLink::Assessment(number) => rsx! {
                                        button { style: "{BTN_SMALL} white-space: nowrap;", onclick: move |_| on_details.call(Some(number)), "Show details" }
                                    },
                                    EventLink::Chat(session_id) => {
                                        let href = Route::ai_chat_session(session_id, None, None).to_string();
                                        rsx! {
                                        a {
                                            href: "{href}",
                                            target: "_blank", rel: "noopener", style: LINK,
                                            "Open"
                                        }
                                        }
                                    }
                                    EventLink::Node(id) => rsx! {
                                        Link {
                                            to: Route::AiBoardPage {
                                                board_id: snap.board.board_id.clone(),
                                                selected: snap.slug_of(&id),
                                                zoom: zoom.clone(),
                                                assessment: String::new(),
                                            },
                                            style: "{LINK} font-family: monospace; font-size: var(--x-text-detail); overflow-wrap: anywhere;",
                                            "{snap.slug_of(&id)}"
                                        }
                                    },
                                    EventLink::None => rsx! {},
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

/// The name of an actor on the page. The stored actor `reason` is the assessment step.
fn actor_label(actor: &str) -> &str {
    if actor == "reason" { "assessment" } else { actor }
}

/// What the last column of an event row links to.
#[derive(Debug, Clone, PartialEq)]
enum EventLink {
    /// The details popup of an assessment.
    Assessment(u32),
    /// The explore chat of the intent or the fact that the event names.
    Chat(String),
    /// The node that the event names, by its storage id.
    Node(String),
    None,
}

fn event_link(snap: &BoardSnapshot, event: &BoardEvent) -> EventLink {
    match event.event_type.as_str() {
        "reason_result" => return event.subject.trim().parse().map(EventLink::Assessment).unwrap_or(EventLink::None),
        _ => {}
    }
    if event.subject.is_empty() {
        return EventLink::None;
    }
    let chat = snap
        .intents
        .iter()
        .find(|i| i.intent_id == event.subject)
        .map(|i| i.session_id.clone())
        .or_else(|| snap.facts.iter().find(|f| f.fact_id == event.subject).map(|f| f.session_id.clone()))
        .filter(|session| !session.is_empty());
    match chat {
        Some(session_id) => EventLink::Chat(session_id),
        None if snap.resolve_node(&event.subject).is_some() => EventLink::Node(event.subject.clone()),
        None => EventLink::None,
    }
}

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
                dt { "Assessments" } dd { "{snap.reasons_done}" }
                dt { "Intents" } dd { "{intent_line}" }
                dt { "Facts" } dd { "{fact_line}" }
                dt { "Collections" } dd { "{snap.board.collections.join(\", \")}" }
                dt { "Internet tools" } dd { "{internet}" }
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

/// The title of a fact in its detail pane.
fn fact_title(fact: &BoardFact) -> String {
    match fact.kind.as_str() {
        "origin" => "Background context".to_string(),
        "goal" => {
            let number = fact.slug.strip_prefix("goal-").and_then(|n| n.parse::<u32>().ok()).unwrap_or(1);
            format!("Goal {number}")
        }
        _ if fact.title.is_empty() => "Fact".to_string(),
        _ => fact.title.clone(),
    }
}

/// The placeholder of the reject box and the label of its button, for a correction or a fact.
fn reject_words(kind: &str) -> (&'static str, &'static str) {
    if kind == "correction" {
        ("Why the correction is wrong", "Reject correction")
    } else {
        ("Why the fact is wrong", "Reject fact")
    }
}

#[component]
fn FactDetail(
    snap: BoardSnapshot,
    fact: BoardFact,
    zoom: String,
    snapshot: Signal<Option<BoardSnapshot>>,
    error: Signal<Option<String>>,
) -> Element {
    let mut reason = use_signal(String::new);
    let mut asking = use_signal(|| false);
    let mut error = error;
    let board_id = snap.board.board_id.clone();
    let dropped = snap.status == "dropped";
    let link = |selected: String| Route::AiBoardPage {
        board_id: board_id.clone(),
        selected,
        zoom: zoom.clone(),
        assessment: String::new(),
    };
    // The open questions of the fact, each with the slug of the intent that follows it.
    let questions: Vec<(u32, String, Option<String>)> = fact
        .open_questions
        .iter()
        .enumerate()
        .map(|(i, text)| {
            let follower = snap.follower_of(&fact.fact_id, i as u32).map(|f| snap.slug_of(&f.intent_id));
            (i as u32, text.clone(), follower)
        })
        .collect();
    let answer = goal_answer(&snap, &fact.fact_id);
    let can_reject = !fact.rejected && fact.kind != "origin" && fact.kind != "goal";
    let (placeholder, reject_label) = reject_words(&fact.kind);
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
                title: fact_title(&fact),
                kind: NodeKind::Fact(fact.kind.clone()),
                slug: fact.slug.clone(),
                rejected: fact.rejected,
                chat: fact.session_id.clone(),
                answer: answer_word(&answer),
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
            // The gray area behind the citation cards, as on the chat page, so the white cards
            // stand out.
            div { class: "x-board-fact-text", style: "margin: 6px 0; background: #ECEEF2; padding: 12px; border-radius: 8px;",
                MarkdownishText { text: fact.text.clone(), cited_handles: Some(handles), sources }
            }
            if fact.kind == "goal" {
                GoalAnswer {
                    key: "{fact.fact_id}-{answer_key(&answer)}",
                    board_id: board_id.clone(),
                    answer: answer.clone(),
                    from: answer.as_ref().map(|(a, _)| a.from.iter().map(|f| snap.slug_of(f)).collect()).unwrap_or_default(),
                    zoom: zoom.clone(),
                    dropped,
                    snapshot,
                    error,
                }
            }
            if !questions.is_empty() {
                div { style: SUBHEADING, "Open questions" }
                for (index, text, follower) in questions.into_iter() {
                    div { key: "{index}", class: "x-board-fact-question",
                        div { class: "x-board-fact-question-text", "{text}" }
                        if let Some(intent) = follower {
                            span { class: "x-board-question-corner x-board-question-followed",
                                "Explored in "
                                Link { to: link(intent.clone()), style: "{LINK} font-family: monospace;", "{intent}" }
                            }
                        } else if !fact.rejected && !dropped {
                            button {
                                class: "x-board-question-corner x-board-explore-question",
                                style: BTN_SMALL,
                                disabled: asking(),
                                onclick: {
                                    let board_id = board_id.clone();
                                    let fact_id = fact.fact_id.clone();
                                    move |_| {
                                        let (board_id, fact_id) = (board_id.clone(), fact_id.clone());
                                        asking.set(true);
                                        spawn(async move {
                                            if let Err(e) = board_explore_question(board_id.clone(), fact_id, index).await {
                                                error.set(Some(user_facing_message(&e)));
                                            }
                                            asking.set(false);
                                            reload(board_id, snapshot, error).await;
                                        });
                                    }
                                },
                                "Explore this question"
                            }
                        }
                    }
                }
            }
            if !fact.problems.is_empty() {
                div { style: SUBHEADING, "Checks that changed this fact" }
                for (i, p) in fact.problems.iter().enumerate() {
                    div { key: "{i}", style: "font-size: var(--x-text-detail); color: var(--x-danger);", "{p}" }
                }
            }
            if can_reject {
                div { style: "margin-top: 10px; display: flex; gap: 8px; align-items: center;",
                    input {
                        class: "x-board-reject-reason",
                        style: "{INPUT} flex: 1;", placeholder: "{placeholder}",
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
                        "{reject_label}"
                    }
                }
            }
        }
    }
}

/// The answer of a goal and whether the person accepted it, or none yet.
fn goal_answer(snap: &BoardSnapshot, goal: &str) -> Option<(BoardReviewGoal, bool)> {
    snap.answers_accepted.iter().find(|a| a.goal == goal).map(|a| (a.clone(), true))
        .or_else(|| snap.answers_proposed.iter().find(|a| a.goal == goal).map(|a| (a.clone(), false)))
}

/// The word of the goal card corner for an answer (`board_graph::GraphNode::answer`).
fn answer_word(answer: &Option<(BoardReviewGoal, bool)>) -> String {
    match answer {
        Some((_, true)) => "answered".to_string(),
        Some((_, false)) => "answer proposed".to_string(),
        None => String::new(),
    }
}

/// A key that changes when another assessment proposes the answer, so the correction box of
/// the earlier answer does not stay.
fn answer_key(answer: &Option<(BoardReviewGoal, bool)>) -> String {
    match answer {
        Some((a, accepted)) => format!("{}-{accepted}", a.reason_no),
        None => "none".to_string(),
    }
}

/// The answer of one goal: the accepted answer, the proposed answer with the person's
/// decision, or none yet. `from` holds the slugs of the answer's facts.
#[component]
fn GoalAnswer(
    board_id: String,
    answer: Option<(BoardReviewGoal, bool)>,
    from: Vec<String>,
    zoom: String,
    dropped: bool,
    snapshot: Signal<Option<BoardSnapshot>>,
    error: Signal<Option<String>>,
) -> Element {
    let mut correction = use_signal(String::new);
    let mut busy = use_signal(|| false);
    let mut error = error;
    let Some((answer, accepted)) = answer else {
        return rsx! { p { class: "x-board-goal-answer", style: HELP_TEXT, "No answer yet." } };
    };
    let link_board = board_id.clone();
    let (goal, reason_no) = (answer.goal.clone(), answer.reason_no);
    let decide = move |accept: bool| {
        let (board_id, goal) = (board_id.clone(), goal.clone());
        let text = correction.read().clone();
        busy.set(true);
        spawn(async move {
            match board_answer(board_id.clone(), goal, reason_no, accept, text).await {
                Ok(()) => correction.set(String::new()),
                Err(e) => error.set(Some(user_facing_message(&e))),
            }
            busy.set(false);
            reload(board_id, snapshot, error).await;
        });
    };
    let mut decide_accept = decide.clone();
    let mut decide_reject = decide;
    let (label, border) = if accepted { ("Answer", "solid") } else { ("Proposed answer", "dashed") };
    rsx! {
        div {
            class: "x-board-goal-answer",
            "data-answer": if accepted { "accepted" } else { "proposed" },
            style: "border-left: 3px {border}; border-left-color: var(--x-ok); padding: 2px 10px; margin: 8px 0;",
            div { style: "font-weight: 600; color: var(--x-ok);", "{label}" }
            p { style: "margin: 2px 0; white-space: pre-wrap;", "{answer.statement}" }
            if !from.is_empty() {
                p { style: HELP_TEXT,
                    "From the facts "
                    for (i, slug) in from.iter().enumerate() {
                        span { key: "{slug}",
                            if i > 0 { ", " }
                            Link {
                                to: Route::AiBoardPage {
                                    board_id: link_board.clone(),
                                    selected: slug.clone(),
                                    zoom: zoom.clone(),
                                    assessment: String::new(),
                                },
                                style: "{LINK} font-family: monospace;",
                                "{slug}"
                            }
                        }
                    }
                    "."
                }
            }
            if !accepted && !dropped {
                button {
                    class: "x-board-accept-answer",
                    style: "{BTN_PRIMARY} margin-top: 4px;",
                    disabled: busy(),
                    onclick: move |_| decide_accept(true),
                    "Accept answer"
                }
                div { style: "display: flex; gap: 8px; align-items: center; margin-top: 6px;",
                    input {
                        class: "x-board-answer-correction",
                        style: "{INPUT} flex: 1;",
                        placeholder: "Why the answer is wrong or incomplete",
                        value: "{correction}",
                        oninput: move |e| correction.set(e.value()),
                    }
                    button {
                        class: "x-board-reject-answer",
                        style: BTN_SMALL_DANGER,
                        disabled: busy(),
                        onclick: move |_| decide_reject(false),
                        "Reject answer"
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
                kind: NodeKind::Intent(intent.state.clone()),
                slug: intent.slug.clone(),
                rejected: false,
                chat: intent.session_id.clone(),
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
            if !intent.brief.is_empty() {
                div { style: SUBHEADING, "Brief sent to the explore" }
                pre { style: PRE, "{intent.brief}" }
            }
        }
    }
}

#[component]
fn DetailHeader(title: String, kind: NodeKind, slug: String, rejected: bool, chat: String,
                #[props(default)] answer: String) -> Element {
    let decoration = if rejected { "line-through" } else { "none" };
    let (left, status) = corners(&kind, &slug, rejected, &answer);
    rsx! {
        div { class: "x-board-detail-head",
            div { class: "x-board-detail-title", style: "{SECTION} margin: 0; text-decoration: {decoration};", "{title}" }
            if !chat.is_empty() {
                Link { to: Route::ai_chat_session(chat.clone(), None, None), style: "{LINK} white-space: nowrap;", "Open the explore chat" }
            }
        }
        div { class: "x-board-detail-meta",
            span { "{left}" }
            span { style: "display: flex; gap: 6px; flex-shrink: 0;",
                for (i, tag) in status.iter().enumerate() {
                    span { key: "{i}", "{tag}" }
                }
            }
        }
    }
}

/// The details popup of one assessment: its prompt and its response, read only.
#[component]
fn AssessmentDetails(board_id: String, reason_no: u32, on_close: EventHandler<()>) -> Element {
    let details = use_resource(move || board_assessment(board_id.clone(), reason_no));
    let body = match &*details.read() {
        None => rsx! { p { style: HELP_TEXT, "Loading the assessment\u{2026}" } },
        Some(Err(e)) => rsx! { ErrorBar { message: user_facing_message(e) } },
        Some(Ok(a)) => rsx! { AssessmentBody { assessment: a.clone() } },
    };
    rsx! {
        div {
            class: "x-board-assessment-overlay",
            style: "position: fixed; inset: 0; background-color: rgba(0,0,0,0.3); z-index: 50; display: flex; align-items: center; justify-content: center;",
            onclick: move |_| on_close.call(()),
            div {
                class: "x-board-assessment",
                style: "background: white; border-radius: 10px; padding: 18px 20px; width: min(1100px, 94vw); height: 90vh; box-sizing: border-box; display: flex; flex-direction: column; gap: 8px; box-shadow: 0 8px 30px rgba(0,0,0,0.2);",
                onclick: move |e| e.stop_propagation(),
                div { style: "display: flex; align-items: center; gap: 12px;",
                    div { style: "font-size: var(--x-text-section); font-weight: 600;", "Assessment {reason_no}" }
                    span { style: "flex: 1;" }
                    button { style: BTN_PRIMARY, onclick: move |_| on_close.call(()), "Close" }
                }
                div { style: "flex: 1; min-height: 0; overflow: auto;", {body} }
            }
        }
    }
}

#[component]
fn AssessmentBody(assessment: BoardAssessment) -> Element {
    let a = assessment;
    let tokens = format!("{} prompt and {} completion tokens", a.prompt_tokens, a.completion_tokens);
    rsx! {
        p { style: HELP_TEXT,
            "{format_utc_ms(a.created_ms)}. Model {a.model}. Outcome {a.outcome}. {a.latency_ms} ms, {tokens}."
        }
        if !a.error.is_empty() {
            p { style: "color: var(--x-danger);", "{a.error}" }
        }
        if !a.problems.is_empty() {
            div { style: SUBHEADING, "Checks that changed it" }
            for (i, p) in a.problems.iter().enumerate() {
                div { key: "{i}", style: "font-size: var(--x-text-detail); color: var(--x-danger);", "{p}" }
            }
        }
        div { style: SUBHEADING, "Prompt" }
        if a.stored {
            pre { class: "x-board-assessment-prompt", style: "{PRE} max-height: none;", "{a.prompt}" }
        } else {
            p { style: HELP_TEXT, "This assessment ran before the prompts were stored." }
        }
        div { style: SUBHEADING, "Response" }
        pre { class: "x-board-assessment-reply", style: "{PRE} max-height: none;", "{a.reply}" }
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
        assert_eq!(actor_label("reason"), "assessment");
    }

    #[test]
    fn a_correction_pane_rejects_a_correction() {
        assert_eq!(reject_words("correction"), ("Why the correction is wrong", "Reject correction"));
        assert_eq!(reject_words("sourced"), ("Why the fact is wrong", "Reject fact"));
    }

    fn event(event_type: &str, subject: &str) -> BoardEvent {
        BoardEvent {
            event_id: format!("{event_type}:{subject}"), event_type: event_type.into(), actor: "admin".into(),
            subject: subject.into(), summary: String::new(), quote: String::new(), created_ms: 0,
        }
    }

    #[test]
    fn an_event_links_its_assessment_its_chat_or_its_node() {
        let fact = |id: &str, kind: &str, session: &str| BoardFact {
            fact_id: id.into(), kind: kind.into(), text: String::new(), intent_id: String::new(),
            session_id: session.into(), open_questions: vec![], problems: vec![], rejected: false,
            rejected_by: String::new(), rejected_ms: 0, rejected_reason: String::new(), corrects: vec![],
            created_by: String::new(), created_ms: 0, citations: vec![], slug: format!("slug-{id}"),
            title: String::new(), summary: String::new(),
        };
        let snap = BoardSnapshot {
            board: common::board_types::BoardDefinition {
                board_id: "b".into(), owner: "o".into(), title: "t".into(), goal: "g".into(),
                context: String::new(), collections: vec![], llm_model: String::new(), max_parallel: 1,
                internet_tools: false, created_ms: 0,
            },
            status: "active".into(), explores_used: 0, reasons_done: 0, stall_count: 0,
            review_statement: String::new(), answers_proposed: vec![], answers_accepted: vec![],
            max_explores: 12, explore_steps: 60,
            facts: vec![fact("f1.1", "sourced", "board-b-i1.1"), fact("c1", "correction", "")],
            intents: vec![], events: vec![], summary: String::new(),
        };
        assert_eq!(event_link(&snap, &event("reason_result", "4")), EventLink::Assessment(4));
        assert_eq!(event_link(&snap, &event("fact_rejected", "f1.1")), EventLink::Chat("board-b-i1.1".into()));
        assert_eq!(event_link(&snap, &event("review_rejected", "c1")), EventLink::Node("c1".into()));
        assert_eq!(event_link(&snap, &event("reason_started", "4")), EventLink::None);
        assert_eq!(event_link(&snap, &event("hint_added", "")), EventLink::None);
    }
}
