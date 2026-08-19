//! The email connection graph: a bounded neighbourhood of one message on the left, the
//! ordinary document preview on the right.
//!
//! Two parameters, and the split is what makes the page work as a place:
//!
//! * `centre` is the message the graph was opened on. It never changes while you browse,
//!   so the picture stays put and "back" means what it looks like it means.
//! * `selected` is what the right-hand pane shows. Clicking a node changes only this.
//!
//! The layout
//! ----------
//! **x is time, y is free.** Every node's send date is scaled to `-1..=1` across the
//! CURRENTLY RENDERED set and a spring pulls it to that x, so the picture reads
//! old-left / new-right without any node ever being placed by hand. A message whose
//! `Date:` header never parsed sits at x = 0 under a deliberately weak spring and renders
//! dimmed: "we do not know when" has to be visible, because the alternative is silently
//! drawing it in 1970 and letting someone read that as a fact.
//!
//! y comes from a plain force loop — pairwise repulsion, attraction along edges, damping.
//!
//! **Positions persist across navigations.** The map is keyed by `(dataset, hash)` and
//! survives a selection change; on a diff, surviving nodes keep their coordinates and new
//! nodes are seeded at the centroid of the neighbours they arrived with. The loop then
//! runs a BOUNDED number of further ticks and stops. A simulation that never settles is a
//! battery drain on a page people leave open, and this one is left open by design.

use std::collections::HashMap;

use common::email_graph::{EmailGraph, EmailGraphEdge, EmailGraphNode, MAX_GRAPH_DEPTH, MAX_GRAPH_NODES};
use common::search_query::SearchQuery;
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::components::document_view_components::doc_preview_for_search::DocumentPreviewForSearchRoot;
use crate::data_definitions::doc_viewer_state::DocViewerState;
use crate::data_definitions::url_param::UrlParam;
use crate::pages::search_page::DocViewerStateControl;
use crate::routes::Route;

/// Viewport the simulation runs in. The SVG scales to its pane through `viewBox`, so
/// these are simulation units, not pixels, and the physics does not change with the
/// window size.
const VIEW_WIDTH: f64 = 1000.0;
const VIEW_HEIGHT: f64 = 620.0;

/// Ticks per navigation, then the loop stops. See the module doc.
const MAX_TICKS: u32 = 120;
/// Milliseconds between ticks. 16 would be a frame; 25 is deliberately slower, because
/// this is a settling animation and not a game loop.
const TICK_MS: u64 = 25;

/// How hard the time axis pulls. Strong, because x is the one axis that carries meaning.
const TIME_SPRING: f64 = 0.08;
/// The same pull for a node with no known date. Weak on purpose: it drifts to the middle
/// rather than being pinned there, so it does not sit on top of a dated node.
const UNDATED_SPRING: f64 = 0.01;
/// Pairwise repulsion, in units² — the numerator of an inverse-square term.
const REPULSION: f64 = 42_000.0;
/// Attraction along an edge.
const EDGE_PULL: f64 = 0.012;
/// Velocity retained per tick.
const DAMPING: f64 = 0.82;
/// Vertical pull to the middle, so a component cannot drift off the top of the viewport.
const CENTRING: f64 = 0.004;

#[derive(Clone, Copy, PartialEq, Debug)]
struct NodePosition {
    x: f64,
    y: f64,
    vx: f64,
    vy: f64,
}

#[component]
pub fn EmailGraphPage(
    centre: UrlParam<DocumentIdentifier>,
    selected: UrlParam<Option<DocumentIdentifier>>,
    doc_viewer_state: UrlParam<Option<DocViewerState>>,
) -> Element {
    rsx! {
        Title { "Hoover Search - Connected Emails" }
        EmailGraphContent {
            centre: centre.0,
            selected: selected.0,
            doc_viewer_state: doc_viewer_state.0,
        }
    }
}

#[component]
fn EmailGraphContent(
    centre: ReadSignal<DocumentIdentifier>,
    selected: ReadSignal<Option<DocumentIdentifier>>,
    doc_viewer_state: ReadSignal<Option<DocViewerState>>,
) -> Element {
    // Reading the value outside the async block is what subscribes the resource to the
    // route signal, so an in-app navigation to another centre refetches.
    let centre_value = centre();
    let graph = use_resource(use_reactive!(|centre_value| {
        async move { get_email_graph(centre_value, MAX_GRAPH_NODES, MAX_GRAPH_DEPTH).await }
    }));

    use_context_provider(move || DocViewerStateControl {
        doc_viewer_state: doc_viewer_state.into(),
        set_doc_viewer_state: Callback::new(move |state: DocViewerState| {
            navigator().replace(Route::EmailGraphPage {
                centre: centre.read().clone().into(),
                selected: selected.read().clone().into(),
                doc_viewer_state: Some(state).into(),
            });
        }),
    });

    // The persisted layout. It is a signal on THIS component, so it survives every
    // selection change (which only replaces the URL) and is rebuilt only when the page
    // itself is remounted.
    let positions = use_signal(HashMap::<(String, String), NodePosition>::new);
    let ticks = use_signal(|| 0_u32);

    let selected_value = selected.read().clone().or_else(|| Some(centre_value.clone()));

    let on_node_click = Callback::new(move |identifier: DocumentIdentifier| {
        // `push`, not `replace`: clicking a node is a navigation, and the prompt asks for
        // back and forward to keep the layout — which they do, because the layout lives
        // in the signal above and not in the URL.
        navigator().push(Route::EmailGraphPage {
            centre: centre.read().clone().into(),
            selected: Some(identifier).into(),
            doc_viewer_state: None.into(),
        });
    });

    let graph_pane = match graph() {
        None => rsx! { div { style: "padding: 20px; color: rgba(0,0,0,0.6);", "Loading the connection graph..." } },
        Some(Err(error)) => rsx! {
            div { class: "x-error-display", style: "padding: 20px;", "Could not load the graph: {error}" }
        },
        Some(Ok(value)) if value.nodes.is_empty() => rsx! {
            div { style: "padding: 20px; color: rgba(0,0,0,0.6);", "This message has no connections." }
        },
        Some(Ok(value)) => rsx! {
            EmailGraphCanvas {
                graph: value,
                selected: selected_value.clone(),
                positions,
                ticks,
                on_node_click,
            }
        },
    };

    rsx! {
        div {
            style: "display: flex; flex-direction: row; height: 100%; width: 100%; overflow: hidden; background: #FFFFFF;",
            div {
                class: "x-email-graph-pane",
                style: "flex: 1 1 55%; min-width: 0; display: flex; flex-direction: column; border-right: 1px solid rgba(0,0,0,0.12);",
                {graph_pane}
            }
            div {
                style: "flex: 1 1 45%; min-width: 0; overflow: hidden;",
                DocumentPreviewForSearchRoot {
                    query: SearchQuery::default(),
                    selected_result_hash: selected_value,
                    show_finder: false,
                }
            }
        }
    }
}

/// The SVG and the loop that moves it.
#[component]
fn EmailGraphCanvas(
    graph: ReadSignal<EmailGraph>,
    selected: ReadSignal<Option<DocumentIdentifier>>,
    positions: Signal<HashMap<(String, String), NodePosition>>,
    ticks: Signal<u32>,
    on_node_click: Callback<DocumentIdentifier>,
) -> Element {
    let value = graph.read().clone();

    // The diff, once per graph change: surviving nodes keep their coordinates, departed
    // nodes are dropped, and new ones are seeded. Seeding at the centroid of the
    // neighbours a node arrived with is what stops a new node from flying in from the
    // corner across the whole picture.
    let node_keys: Vec<(String, String)> = value
        .nodes
        .iter()
        .map(|n| (n.document_identifier.collection_dataset.clone(), n.document_identifier.file_hash.clone()))
        .collect();
    use_effect({
        let value = value.clone();
        let node_keys = node_keys.clone();
        let mut positions = positions;
        let mut ticks = ticks;
        move || {
            let seeded = seed_positions(&value, &node_keys, &positions.peek().clone());
            if seeded != *positions.peek() {
                positions.set(seeded);
                // The diff is done, so the loop gets its budget back — that is exactly
                // what "iterate the positions after the add/remove diff" means.
                ticks.set(0);
            }
        }
    });

    // The loop. It is a single future that ends: no timer survives it, and it restarts
    // only because `ticks` was reset by a diff above.
    use_future({
        let edges = value.edges.clone();
        let nodes = value.nodes.clone();
        let mut positions = positions;
        let mut ticks = ticks;
        move || {
            let edges = edges.clone();
            let nodes = nodes.clone();
            async move {
                loop {
                    if *ticks.peek() >= MAX_TICKS {
                        // `n0_future::time::sleep`, never `gloo_timers`: gloo is
                        // wasm-only and this file is compiled into the server-side render
                        // build as well.
                        n0_future::time::sleep(std::time::Duration::from_millis(200)).await;
                        continue;
                    }
                    let mut next = positions.peek().clone();
                    simulate_tick(&nodes, &edges, &mut next);
                    positions.set(next);
                    ticks += 1;
                    n0_future::time::sleep(std::time::Duration::from_millis(TICK_MS)).await;
                }
            }
        }
    });

    let layout = positions.read().clone();
    let selected_key = selected
        .read()
        .clone()
        .map(|d| (d.collection_dataset, d.file_hash));

    rsx! {
        div {
            style: "padding: 10px 14px; border-bottom: 1px solid rgba(0,0,0,0.10); display: flex; align-items: center; gap: 16px; flex-wrap: wrap;",
            div { style: "font-weight: 600;", "Connected emails" }
            div {
                style: "font-size: 13px; color: rgba(0,0,0,0.6);",
                "{value.nodes.len()} of {value.cluster_size} shown"
                if value.truncated {
                    " \u{00b7} the cluster continues beyond this view"
                }
            }
            GraphLegend {}
        }
        div {
            style: "flex: 1 1 auto; min-height: 0; overflow: auto;",
            svg {
                class: "x-email-graph-svg",
                width: "100%",
                height: "100%",
                view_box: "0 0 {VIEW_WIDTH} {VIEW_HEIGHT}",
                preserve_aspect_ratio: "xMidYMid meet",
                defs {
                    marker {
                        id: "x-email-arrow",
                        view_box: "0 0 10 10",
                        ref_x: "9",
                        ref_y: "5",
                        marker_width: "7",
                        marker_height: "7",
                        orient: "auto-start-reverse",
                        path { d: "M 0 0 L 10 5 L 0 10 z", fill: "rgba(0,0,0,0.45)" }
                    }
                }
                // The time axis, drawn first so it sits behind everything.
                line {
                    x1: "0", y1: "{VIEW_HEIGHT - 18.0}", x2: "{VIEW_WIDTH}", y2: "{VIEW_HEIGHT - 18.0}",
                    stroke: "rgba(0,0,0,0.12)", stroke_width: "1",
                }
                text {
                    x: "8", y: "{VIEW_HEIGHT - 4.0}", font_size: "13", fill: "rgba(0,0,0,0.45)",
                    "older"
                }
                text {
                    x: "{VIEW_WIDTH - 8.0}", y: "{VIEW_HEIGHT - 4.0}", font_size: "13",
                    text_anchor: "end", fill: "rgba(0,0,0,0.45)",
                    "newer"
                }

                for edge in value.edges.iter() {
                    {render_edge(edge, &layout)}
                }
                for node in value.nodes.iter() {
                    {render_node(node, &layout, &selected_key, on_node_click)}
                }
            }
        }
    }
}

#[component]
fn GraphLegend() -> Element {
    rsx! {
        div {
            style: "display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px; color: rgba(0,0,0,0.65);",
            for (label, dashed) in [
                ("identity", false), ("reply", false), ("forward", false),
                ("attachment", false), ("reference", false), ("inferred", true),
            ] {
                div {
                    key: "{label}",
                    style: "display: flex; align-items: center; gap: 5px;",
                    svg {
                        width: "26", height: "8", view_box: "0 0 26 8",
                        line {
                            x1: "0", y1: "4", x2: "26", y2: "4",
                            stroke: "rgba(0,0,0,0.5)", stroke_width: "2",
                            stroke_dasharray: if dashed { "5 4" } else { "" },
                        }
                    }
                    span { "{label}" }
                }
            }
        }
    }
}

fn node_key(node: &EmailGraphNode) -> (String, String) {
    (
        node.document_identifier.collection_dataset.clone(),
        node.document_identifier.file_hash.clone(),
    )
}

fn edge_key(identifier: &DocumentIdentifier) -> (String, String) {
    (identifier.collection_dataset.clone(), identifier.file_hash.clone())
}

/// Where the time axis wants each node.
///
/// Scaled across the CURRENTLY RENDERED set, per the prompt: a cluster spanning three
/// days and one spanning three years both use the full width, because the question the
/// axis answers is "which of these came first", not "what year is it".
fn target_x(nodes: &[EmailGraphNode]) -> HashMap<(String, String), f64> {
    let dated: Vec<i64> =
        nodes.iter().filter(|n| n.date_sent_known).map(|n| n.date_sent).collect();
    let (min, max) = (
        dated.iter().copied().min().unwrap_or(0),
        dated.iter().copied().max().unwrap_or(0),
    );
    let span = (max - min).max(1) as f64;
    let margin = VIEW_WIDTH * 0.10;
    nodes
        .iter()
        .map(|node| {
            let normalised = if node.date_sent_known {
                // -1..=1, then mapped into the viewport with a margin so a node at either
                // extreme is not half off the edge.
                ((node.date_sent - min) as f64 / span) * 2.0 - 1.0
            } else {
                0.0
            };
            (node_key(node), VIEW_WIDTH / 2.0 + normalised * (VIEW_WIDTH / 2.0 - margin))
        })
        .collect()
}

/// The add/remove diff. Pure so it can be tested without a runtime.
fn seed_positions(
    graph: &EmailGraph,
    node_keys: &[(String, String)],
    previous: &HashMap<(String, String), NodePosition>,
) -> HashMap<(String, String), NodePosition> {
    let targets = target_x(&graph.nodes);
    let mut neighbours: HashMap<(String, String), Vec<(String, String)>> = HashMap::new();
    for edge in &graph.edges {
        neighbours.entry(edge_key(&edge.src)).or_default().push(edge_key(&edge.dst));
        neighbours.entry(edge_key(&edge.dst)).or_default().push(edge_key(&edge.src));
    }

    let mut next = HashMap::with_capacity(node_keys.len());
    for (index, key) in node_keys.iter().enumerate() {
        if let Some(existing) = previous.get(key) {
            next.insert(key.clone(), *existing);
            continue;
        }
        let seeded_y = neighbours
            .get(key)
            .map(|list| {
                let known: Vec<f64> =
                    list.iter().filter_map(|n| previous.get(n)).map(|p| p.y).collect();
                if known.is_empty() {
                    None
                } else {
                    Some(known.iter().sum::<f64>() / known.len() as f64)
                }
            })
            .flatten()
            // No placed neighbour: spread down the middle band deterministically rather
            // than randomly, so the same graph always settles the same way.
            .unwrap_or_else(|| {
                VIEW_HEIGHT / 2.0 + ((index % 7) as f64 - 3.0) * (VIEW_HEIGHT / 18.0)
            });
        next.insert(
            key.clone(),
            NodePosition {
                x: targets.get(key).copied().unwrap_or(VIEW_WIDTH / 2.0),
                y: seeded_y,
                vx: 0.0,
                vy: 0.0,
            },
        );
    }
    next
}

/// One step of the simulation. Pure, in place, and deliberately O(n²): the node budget is
/// 50, so the pairwise loop is 2 500 operations per tick and a quadtree would be more
/// code than the thing it optimises.
fn simulate_tick(
    nodes: &[EmailGraphNode],
    edges: &[EmailGraphEdge],
    positions: &mut HashMap<(String, String), NodePosition>,
) {
    let targets = target_x(nodes);
    let keys: Vec<(String, String)> = nodes.iter().map(node_key).collect();
    let mut forces: HashMap<(String, String), (f64, f64)> =
        keys.iter().map(|k| (k.clone(), (0.0, 0.0))).collect();

    for (index, a_key) in keys.iter().enumerate() {
        let Some(a) = positions.get(a_key).copied() else { continue };
        for b_key in keys.iter().skip(index + 1) {
            let Some(b) = positions.get(b_key).copied() else { continue };
            let (dx, dy) = (a.x - b.x, a.y - b.y);
            // The floor keeps two coincident nodes from producing an infinite force,
            // which is how a force layout ends up with every node at NaN.
            let distance_squared = (dx * dx + dy * dy).max(25.0);
            let distance = distance_squared.sqrt();
            let magnitude = REPULSION / distance_squared;
            let (fx, fy) = (dx / distance * magnitude, dy / distance * magnitude);
            if let Some(force) = forces.get_mut(a_key) {
                force.0 += fx;
                force.1 += fy;
            }
            if let Some(force) = forces.get_mut(b_key) {
                force.0 -= fx;
                force.1 -= fy;
            }
        }
    }

    for edge in edges {
        let (src, dst) = (edge_key(&edge.src), edge_key(&edge.dst));
        let (Some(a), Some(b)) = (positions.get(&src).copied(), positions.get(&dst).copied())
        else {
            continue;
        };
        let (dx, dy) = (b.x - a.x, b.y - a.y);
        if let Some(force) = forces.get_mut(&src) {
            force.0 += dx * EDGE_PULL;
            force.1 += dy * EDGE_PULL;
        }
        if let Some(force) = forces.get_mut(&dst) {
            force.0 -= dx * EDGE_PULL;
            force.1 -= dy * EDGE_PULL;
        }
    }

    for (index, key) in keys.iter().enumerate() {
        let Some(position) = positions.get_mut(key) else { continue };
        let (mut fx, mut fy) = forces.get(key).copied().unwrap_or((0.0, 0.0));
        let dated = nodes.get(index).is_some_and(|n| n.date_sent_known);
        let spring = if dated { TIME_SPRING } else { UNDATED_SPRING };
        fx += (targets.get(key).copied().unwrap_or(VIEW_WIDTH / 2.0) - position.x) * spring;
        fy += (VIEW_HEIGHT / 2.0 - position.y) * CENTRING;

        position.vx = (position.vx + fx) * DAMPING;
        position.vy = (position.vy + fy) * DAMPING;
        position.x = (position.x + position.vx).clamp(40.0, VIEW_WIDTH - 40.0);
        position.y = (position.y + position.vy).clamp(30.0, VIEW_HEIGHT - 46.0);
    }
}

fn render_edge(edge: &EmailGraphEdge, layout: &HashMap<(String, String), NodePosition>) -> Element {
    let (Some(src), Some(dst)) = (layout.get(&edge_key(&edge.src)), layout.get(&edge_key(&edge.dst)))
    else {
        return rsx! {};
    };
    // Dashed for inferred. This is the difference the confidence column exists for.
    let dash = if edge.is_inferred() { "6 5" } else { "" };
    let colour = if edge.is_inferred() { "rgba(0,0,0,0.32)" } else { "rgba(0,0,0,0.45)" };
    rsx! {
        line {
            key: "{edge.src.file_hash}-{edge.dst.file_hash}-{edge.kind}",
            x1: "{src.x}", y1: "{src.y}", x2: "{dst.x}", y2: "{dst.y}",
            stroke: "{colour}",
            stroke_width: "1.6",
            stroke_dasharray: "{dash}",
            marker_end: "url(#x-email-arrow)",
            title { "{edge.kind} \u{00b7} confidence {edge.confidence} \u{00b7} {edge.evidence}" }
        }
    }
}

fn render_node(
    node: &EmailGraphNode,
    layout: &HashMap<(String, String), NodePosition>,
    selected_key: &Option<(String, String)>,
    on_node_click: Callback<DocumentIdentifier>,
) -> Element {
    let key = node_key(node);
    let Some(position) = layout.get(&key) else { return rsx! {} };
    let is_selected = selected_key.as_ref() == Some(&key);
    let fill = if node.is_centre {
        "#1a73e8"
    } else if is_selected {
        "#c7dcff"
    } else {
        "#FFFFFF"
    };
    let text_colour = if node.is_centre { "#FFFFFF" } else { "#111827" };
    // An undated node is drawn dimmed, so its position on the time axis cannot be read
    // as information.
    let opacity = if node.date_sent_known { "1" } else { "0.55" };
    let label: String = node.subject.chars().take(28).collect();
    let sub: String = node.from_display.chars().take(30).collect();
    let identifier = node.document_identifier.clone();

    rsx! {
        g {
            key: "{key.0}-{key.1}",
            class: "x-email-graph-node",
            opacity: "{opacity}",
            transform: "translate({position.x - 84.0}, {position.y - 20.0})",
            onclick: move |_| on_node_click.call(identifier.clone()),
            rect {
                class: "x-email-graph-node-body",
                width: "168", height: "40", rx: "8",
                fill: "{fill}",
                stroke: if node.is_centre { "#0b57d0" } else { "rgba(0,0,0,0.30)" },
                stroke_width: if is_selected { "2" } else { "1" },
            }
            text {
                x: "10", y: "17", font_size: "12", fill: "{text_colour}",
                if label.is_empty() { "(no subject)" } else { "{label}" }
            }
            text {
                x: "10", y: "31", font_size: "11",
                fill: if node.is_centre { "rgba(255,255,255,0.85)" } else { "rgba(0,0,0,0.55)" },
                "{sub}"
            }
            if node.truncated {
                // Says the graph stops here rather than that the cluster does.
                text { x: "156", y: "31", font_size: "13", fill: "rgba(0,0,0,0.45)", "\u{2026}" }
            }
            title {
                "{node.subject}"
            }
        }
    }
}

#[server]
async fn get_email_graph(
    centre: DocumentIdentifier,
    max_nodes: u32,
    max_depth: u32,
) -> Result<EmailGraph, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::get_email_graph::get_email_graph(&user, centre, max_nodes, max_depth)
        .await
        .map_err(crate::api::error_util::to_server_fn_error)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn node(hash: &str, date: i64, known: bool) -> EmailGraphNode {
        EmailGraphNode {
            document_identifier: DocumentIdentifier {
                collection_dataset: "ds".to_string(),
                file_hash: hash.to_string(),
            },
            subject: format!("subject {hash}"),
            from_display: "a@x.com".to_string(),
            date_sent: date,
            date_sent_known: known,
            truncated: false,
            is_centre: hash == "a",
        }
    }

    fn edge(src: &str, dst: &str, confidence: f32) -> EmailGraphEdge {
        EmailGraphEdge {
            src: DocumentIdentifier { collection_dataset: "ds".into(), file_hash: src.into() },
            dst: DocumentIdentifier { collection_dataset: "ds".into(), file_hash: dst.into() },
            kind: "reply".into(),
            confidence,
            evidence: String::new(),
        }
    }

    #[test]
    fn the_time_axis_puts_the_oldest_left_and_the_newest_right() {
        let nodes = vec![node("a", 1_000, true), node("b", 2_000, true), node("c", 3_000, true)];
        let targets = target_x(&nodes);
        let x = |h: &str| targets[&("ds".to_string(), h.to_string())];
        assert!(x("a") < x("b"), "older node must be left of newer");
        assert!(x("b") < x("c"));
        // An undated node sits in the middle rather than at 1970, which is where its
        // epoch date would otherwise put it: hard left, next to nothing.
        let with_unknown = vec![node("a", 1_000, true), node("z", 0, false)];
        let targets = target_x(&with_unknown);
        assert_eq!(targets[&("ds".to_string(), "z".to_string())], VIEW_WIDTH / 2.0);
    }

    #[test]
    fn a_diff_keeps_surviving_nodes_and_seeds_new_ones_near_their_neighbours() {
        let graph = EmailGraph {
            nodes: vec![node("a", 1_000, true), node("b", 2_000, true)],
            edges: vec![edge("a", "b", 1.0)],
            cluster_size: 2,
            truncated: false,
        };
        let keys: Vec<(String, String)> =
            graph.nodes.iter().map(node_key).collect();

        let first = seed_positions(&graph, &keys, &HashMap::new());
        assert_eq!(first.len(), 2);

        // `a` survives with its exact coordinates; `b` is new and lands at `a`'s height.
        let mut previous = HashMap::new();
        previous.insert(keys[0].clone(), NodePosition { x: 111.0, y: 222.0, vx: 3.0, vy: 4.0 });
        let second = seed_positions(&graph, &keys, &previous);
        assert_eq!(second[&keys[0]], NodePosition { x: 111.0, y: 222.0, vx: 3.0, vy: 4.0 });
        assert_eq!(second[&keys[1]].y, 222.0);

        // A node that left the graph leaves the map with it.
        let smaller_keys = vec![keys[0].clone()];
        let smaller = EmailGraph { nodes: vec![node("a", 1_000, true)], ..graph.clone() };
        let third = seed_positions(&smaller, &smaller_keys, &second);
        assert_eq!(third.len(), 1);
    }

    #[test]
    fn the_simulation_stays_finite_even_when_two_nodes_coincide() {
        let nodes = vec![node("a", 1_000, true), node("b", 1_000, true)];
        let edges = vec![edge("a", "b", 0.5)];
        let mut positions = HashMap::new();
        for n in &nodes {
            positions.insert(node_key(n), NodePosition { x: 500.0, y: 300.0, vx: 0.0, vy: 0.0 });
        }
        for _ in 0..MAX_TICKS {
            simulate_tick(&nodes, &edges, &mut positions);
        }
        for position in positions.values() {
            assert!(position.x.is_finite() && position.y.is_finite());
            assert!((40.0..=VIEW_WIDTH - 40.0).contains(&position.x));
            assert!((30.0..=VIEW_HEIGHT - 46.0).contains(&position.y));
        }
    }
}
