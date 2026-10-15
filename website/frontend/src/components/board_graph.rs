//! The graph of an investigation board, shared by the board page and the overview thumbnail.
//!
//! A fact or an intent is a node. **x is depth**: the origin is depth 0, an intent is one
//! more than the deepest fact it names, the fact of an intent one more than the intent, and a
//! correction one more than the deepest fact it corrects. The goals are the last column, so
//! the picture reads from the origin on the left to the goals on the right, as Cairn draws
//! its graph from `origin` to `goal`. An intent that names a goal gets no edge from it,
//! because that edge would run back across the whole picture. The intent detail lists it.
//!
//! The edges follow Cairn's encoding of the same events. An intent is an edge from the facts
//! it names to its fact. An accepted answer of a goal is an edge from each fact of the answer to
//! that goal (Cairn's `complete`), and a proposed answer that waits for the person is the same
//! edge dashed, in every status of the board. A rejected answer or review is an edge from each
//! of its facts to the correction that the person wrote (Cairn's `reopen`, whose
//! `external_feedback` intent leads to the correction fact).
//!
//! The layout is computed in one pass before it is shown, so no node moves on screen. x comes
//! from the depth. In each column, from left to right, a node asks for a y: its earlier y
//! when it was already placed, else the mean y of its placed neighbours. The column sorts by
//! that y and pushes its nodes apart to one row each. A node that was already placed keeps
//! its y unless a new node needs the room.
//!
//! **A node has one size.** The graph is laid out in pixels at 100 % zoom (`NODE_WIDTH`,
//! `NODE_HEIGHT`, `COLUMN_WIDTH`, `ROW_HEIGHT`), and the board page scales it only by the zoom
//! that the person chooses. A free band of half a row is above and below the nodes, and
//! `MARGIN_X` left and right of them.
//!
//! **Every edge is one straight line** from the middle of the right side of its source to the
//! middle of the left side of its target. The page draws all edges before all nodes, so an
//! edge that skips columns runs under the cards between. A dimmed card has an opaque white
//! card under it, so an edge does not show through it.

use std::collections::{HashMap, HashSet};

use common::board_types::{BoardFact, BoardGraphInput, BoardIntent, BoardReviewGoal};
use dioxus::prelude::*;

/// Pixels at 100 % zoom: one node, one depth column (a node and a gap of 80), one row (a node
/// and a gap of 30), and the free band left and right of the nodes.
pub const NODE_WIDTH: f64 = 300.0;
pub const NODE_HEIGHT: f64 = 150.0;
pub const COLUMN_WIDTH: f64 = 380.0;
pub const ROW_HEIGHT: f64 = 180.0;
pub const MARGIN_X: f64 = 40.0;
/// The free band above the top node and below the bottom node of every column.
pub const MARGIN_Y: f64 = ROW_HEIGHT / 2.0;

#[derive(Clone, Copy, PartialEq, Debug)]
pub struct NodePosition {
    pub x: f64,
    pub y: f64,
}

#[derive(Clone, PartialEq, Debug)]
pub enum NodeKind {
    /// A board fact and its kind.
    Fact(String),
    /// An intent and its state.
    Intent(String),
}

#[derive(Clone, PartialEq, Debug)]
pub struct GraphNode {
    pub id: String,
    pub kind: NodeKind,
    pub text: String,
    /// The display name of the node (`BoardFact::slug`, `BoardIntent::slug`).
    pub slug: String,
    /// 3 to 4 words. Empty for the origin and the goals.
    pub title: String,
    /// The body of the node card: the generated summary, or the full text of an origin or goal.
    pub summary: String,
    pub depth: u32,
    pub dimmed: bool,
    pub rejected: bool,
    /// For a goal: `answered`, `answer proposed`, or empty.
    pub answer: String,
}

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum EdgeKind {
    /// From a fact to an intent, or from an intent to its fact.
    Flow,
    /// From a fact to the goal that an accepted answer says it answers.
    Answers,
    /// From a fact to a goal, in an answer that waits for the person.
    Proposed,
    /// From a fact of a rejected answer or review to the correction.
    Corrects,
}

impl EdgeKind {
    pub fn name(self) -> &'static str {
        match self {
            EdgeKind::Flow => "flow",
            EdgeKind::Answers => "answers",
            EdgeKind::Proposed => "proposed",
            EdgeKind::Corrects => "corrects",
        }
    }
}

#[derive(Clone, PartialEq, Debug)]
pub struct GraphEdge {
    pub src: String,
    pub dst: String,
    pub kind: EdgeKind,
}

#[derive(Clone, PartialEq, Debug, Default)]
pub struct Graph {
    pub nodes: Vec<GraphNode>,
    pub edges: Vec<GraphEdge>,
    pub width: f64,
    pub height: f64,
}

/// The nodes, edges and viewport of a board. Pure, so it is tested without a runtime.
pub fn build_graph(input: &BoardGraphInput) -> Graph {
    let mut depth: HashMap<String, u32> = HashMap::new();
    let mut nodes = Vec::new();
    let mut edges = Vec::new();
    let fact_of_intent: HashMap<&str, &BoardFact> =
        input.facts.iter().filter(|f| !f.intent_id.is_empty()).map(|f| (f.intent_id.as_str(), f)).collect();
    let mut goals: Vec<&BoardFact> = input.facts.iter().filter(|f| f.kind == "goal").collect();
    goals.sort_by_key(|f| (f.fact_id != "goal", f.fact_id.len(), f.fact_id.clone()));
    let goal_ids: HashSet<&str> = goals.iter().map(|g| g.fact_id.as_str()).collect();
    // An intent that names a goal starts from depth 0, as one that names the origin.
    for goal in &goals {
        depth.insert(goal.fact_id.clone(), 0);
    }
    for fact in input.facts.iter().filter(|f| f.kind == "origin") {
        depth.insert(fact.fact_id.clone(), 0);
        nodes.push(fact_node(fact, 0));
    }

    // Intents and corrections in the order they were written, so a correction is placed
    // before the intents that start from it.
    enum Item<'a> {
        Intent(&'a BoardIntent),
        Correction(&'a BoardFact),
    }
    let mut items: Vec<(i64, (u32, u32), Item)> = input
        .intents
        .iter()
        .map(|i| (i.created_ms, intent_order(&i.intent_id), Item::Intent(i)))
        .chain(
            input
                .facts
                .iter()
                .filter(|f| f.kind == "correction")
                .map(|f| (f.created_ms, (0, 0), Item::Correction(f))),
        )
        .collect();
    items.sort_by_key(|(ms, order, _)| (*ms, *order));
    for (_, _, item) in items {
        match item {
            Item::Intent(intent) => {
                let d = intent.from_facts.iter().filter_map(|f| depth.get(f)).max().copied().unwrap_or(0) + 1;
                depth.insert(intent.intent_id.clone(), d);
                nodes.push(GraphNode {
                    id: intent.intent_id.clone(),
                    kind: NodeKind::Intent(intent.state.clone()),
                    text: intent.objective.clone(),
                    slug: intent.slug.clone(),
                    title: intent.title.clone(),
                    summary: intent.summary.clone(),
                    depth: d,
                    dimmed: intent.state == "cancelled",
                    rejected: false,
                    answer: String::new(),
                });
                for from in &intent.from_facts {
                    if depth.contains_key(from) && !goal_ids.contains(from.as_str()) {
                        edges.push(GraphEdge { src: from.clone(), dst: intent.intent_id.clone(), kind: EdgeKind::Flow });
                    }
                }
                if let Some(fact) = fact_of_intent.get(intent.intent_id.as_str()) {
                    depth.insert(fact.fact_id.clone(), d + 1);
                    nodes.push(fact_node(fact, d + 1));
                    edges.push(GraphEdge { src: intent.intent_id.clone(), dst: fact.fact_id.clone(), kind: EdgeKind::Flow });
                }
            }
            Item::Correction(fact) => {
                let corrected: Vec<&String> = fact.corrects.iter().filter(|f| depth.contains_key(*f)).collect();
                let d = corrected.iter().filter_map(|f| depth.get(*f)).max().map(|d| d + 1).unwrap_or(1);
                depth.insert(fact.fact_id.clone(), d);
                nodes.push(fact_node(fact, d));
                for from in corrected {
                    edges.push(GraphEdge { src: from.clone(), dst: fact.fact_id.clone(), kind: EdgeKind::Corrects });
                }
            }
        }
    }

    let last = nodes.iter().map(|n| n.depth).max().unwrap_or(0) + 1;
    for goal in &goals {
        let mut node = fact_node(goal, last);
        let has = |list: &[BoardReviewGoal]| list.iter().any(|a| a.goal == goal.fact_id);
        if has(&input.answers_accepted) {
            node.answer = "answered".to_string();
        } else if has(&input.answers_proposed) {
            node.answer = "answer proposed".to_string();
        }
        nodes.push(node);
    }
    // Every accepted answer and every answer that waits for the person, in any status.
    let placed: HashSet<&str> = nodes.iter().map(|n| n.id.as_str()).collect();
    let answers = input.answers_accepted.iter().map(|a| (a, EdgeKind::Answers))
        .chain(input.answers_proposed.iter().map(|a| (a, EdgeKind::Proposed)));
    for (answer, kind) in answers {
        if !placed.contains(answer.goal.as_str()) {
            continue;
        }
        for from in &answer.from {
            if placed.contains(from.as_str()) && !goal_ids.contains(from.as_str()) {
                edges.push(GraphEdge { src: from.clone(), dst: answer.goal.clone(), kind });
            }
        }
    }

    let mut per_column: HashMap<u32, u32> = HashMap::new();
    for node in &nodes {
        *per_column.entry(node.depth).or_default() += 1;
    }
    let tallest = per_column.values().copied().max().unwrap_or(1) as f64;
    let columns = (last + 1) as f64;
    Graph {
        width: 2.0 * MARGIN_X + columns * NODE_WIDTH + (columns - 1.0) * (COLUMN_WIDTH - NODE_WIDTH),
        height: 2.0 * MARGIN_Y + tallest * NODE_HEIGHT + (tallest - 1.0) * (ROW_HEIGHT - NODE_HEIGHT),
        nodes,
        edges,
    }
}

fn fact_node(fact: &BoardFact, depth: u32) -> GraphNode {
    GraphNode {
        id: fact.fact_id.clone(),
        kind: NodeKind::Fact(fact.kind.clone()),
        text: fact.text.clone(),
        slug: fact.slug.clone(),
        title: fact.title.clone(),
        summary: fact.summary.clone(),
        depth,
        dimmed: fact.rejected,
        rejected: fact.rejected,
        answer: String::new(),
    }
}

/// `i3.2` sorts as (3, 2), so `i10.1` comes after `i9.1`.
fn intent_order(id: &str) -> (u32, u32) {
    let mut parts = id.trim_start_matches('i').split('.').map(|p| p.parse().unwrap_or(0));
    (parts.next().unwrap_or(0), parts.next().unwrap_or(0))
}

pub fn target_x(depth: u32) -> f64 {
    MARGIN_X + NODE_WIDTH / 2.0 + depth as f64 * COLUMN_WIDTH
}

/// The settled layout of `graph`, after `previous`. See the module doc.
pub fn settle(graph: &Graph, previous: &HashMap<String, NodePosition>) -> HashMap<String, NodePosition> {
    let mut neighbours: HashMap<&str, Vec<&str>> = HashMap::new();
    for edge in &graph.edges {
        neighbours.entry(edge.src.as_str()).or_default().push(edge.dst.as_str());
        neighbours.entry(edge.dst.as_str()).or_default().push(edge.src.as_str());
    }
    let mut columns: Vec<(u32, Vec<usize>)> = Vec::new();
    for (index, node) in graph.nodes.iter().enumerate() {
        match columns.iter_mut().find(|(depth, _)| *depth == node.depth) {
            Some((_, list)) => list.push(index),
            None => columns.push((node.depth, vec![index])),
        }
    }
    columns.sort_by_key(|(depth, _)| *depth);
    let (top, bottom) = (MARGIN_Y + NODE_HEIGHT / 2.0, graph.height - MARGIN_Y - NODE_HEIGHT / 2.0);
    let middle = graph.height / 2.0;
    let mut positions: HashMap<String, NodePosition> = HashMap::with_capacity(graph.nodes.len());
    for (depth, members) in columns {
        let mut wanted: Vec<(f64, usize)> = members
            .iter()
            .map(|&index| {
                let node = &graph.nodes[index];
                let y = previous.get(&node.id).map(|p| p.y).unwrap_or_else(|| {
                    let placed: Vec<f64> = neighbours
                        .get(node.id.as_str())
                        .map(|list| list.iter().filter_map(|n| positions.get(*n)).map(|p| p.y).collect())
                        .unwrap_or_default();
                    if placed.is_empty() { middle } else { placed.iter().sum::<f64>() / placed.len() as f64 }
                });
                (y, index)
            })
            .collect();
        wanted.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)));
        let ys = spread(&wanted.iter().map(|w| w.0).collect::<Vec<_>>(), top, bottom);
        for ((_, index), y) in wanted.into_iter().zip(ys) {
            positions.insert(graph.nodes[index].id.clone(), NodePosition { x: target_x(depth), y });
        }
    }
    positions
}

/// Sorted wanted ys moved apart to at least `ROW_HEIGHT` and into `top..=bottom`. A run of
/// nodes that is too close moves as a block centred on its wanted ys, so a node that was
/// placed moves only when another node needs its room.
fn spread(wanted: &[f64], top: f64, bottom: f64) -> Vec<f64> {
    // Blocks of consecutive nodes: (first index, count, mean wanted y). A block that touches
    // the block before it joins it, and the joined block centres on the mean of its nodes.
    let mut blocks: Vec<(usize, usize, f64)> = Vec::new();
    for (index, &y) in wanted.iter().enumerate() {
        blocks.push((index, 1, y));
        while blocks.len() > 1 {
            let (a, b) = (blocks[blocks.len() - 2], blocks[blocks.len() - 1]);
            let a_end = start_of(a) + (a.1 as f64 - 1.0) * ROW_HEIGHT;
            if start_of(b) - a_end >= ROW_HEIGHT {
                break;
            }
            let count = a.1 + b.1;
            let mean = (a.2 * a.1 as f64 + b.2 * b.1 as f64) / count as f64;
            blocks.pop();
            blocks.pop();
            blocks.push((a.0, count, mean));
        }
    }
    let mut out: Vec<f64> = Vec::with_capacity(wanted.len());
    for block in blocks {
        for k in 0..block.1 {
            out.push(start_of(block) + k as f64 * ROW_HEIGHT);
        }
    }
    // Into the viewport: the column fits, because the viewport height counts the tallest
    // column. The two passes keep the gaps.
    let n = out.len();
    for i in (0..n).rev() {
        let limit = bottom - (n - 1 - i) as f64 * ROW_HEIGHT;
        out[i] = out[i].min(limit);
        if i + 1 < n {
            out[i] = out[i].min(out[i + 1] - ROW_HEIGHT);
        }
    }
    for i in 0..n {
        let limit = top + i as f64 * ROW_HEIGHT;
        out[i] = out[i].max(limit);
        if i > 0 {
            out[i] = out[i].max(out[i - 1] + ROW_HEIGHT);
        }
    }
    out
}

/// The y of the first node of a block: the block centred on its mean wanted y.
fn start_of(block: (usize, usize, f64)) -> f64 {
    block.2 - (block.1 as f64 - 1.0) * ROW_HEIGHT / 2.0
}

pub fn kind_label(kind: &str) -> &'static str {
    match kind {
        "origin" => "background",
        "goal" => "goal",
        "sourced" => "sourced",
        "inferred" => "inferred",
        "not_found" => "not found",
        "correction" => "correction",
        _ => "unknown",
    }
}

/// Fill, border colour, dash pattern and the short tag of a node.
pub fn node_style(kind: &NodeKind) -> (&'static str, &'static str, &'static str, String) {
    match kind {
        NodeKind::Fact(k) => {
            let (fill, stroke) = match k.as_str() {
                "origin" => ("#ffffff", "#000000"),
                "goal" => ("#1a73e8", "#0b57d0"),
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

/// Colour, width and dash pattern of an edge.
pub fn edge_style(kind: EdgeKind) -> (&'static str, &'static str, &'static str) {
    match kind {
        EdgeKind::Flow => ("rgba(0,0,0,0.35)", "1.4", ""),
        EdgeKind::Answers => ("#1e8e3e", "2.2", ""),
        EdgeKind::Proposed => ("#1e8e3e", "2", "6 4"),
        EdgeKind::Corrects => ("#9334e6", "1.8", "4 3"),
    }
}

/// The two ends of an edge: the middle of the right side of its source and the middle of the
/// left side of its target, or none when either node is not placed.
pub fn edge_points(edge: &GraphEdge, layout: &HashMap<String, NodePosition>) -> Vec<(f64, f64)> {
    match (layout.get(&edge.src), layout.get(&edge.dst)) {
        (Some(src), Some(dst)) => vec![(src.x + NODE_WIDTH / 2.0, src.y), (dst.x - NODE_WIDTH / 2.0, dst.y)],
        _ => Vec::new(),
    }
}

/// The `d` attribute of a path through `points`.
pub fn path_data(points: &[(f64, f64)]) -> String {
    points.iter().enumerate()
        .map(|(i, (x, y))| format!("{}{x:.1} {y:.1}", if i == 0 { "M" } else { " L" }))
        .collect()
}

pub fn render_edge(edge: &GraphEdge, layout: &HashMap<String, NodePosition>, marker: &str) -> Element {
    let points = edge_points(edge, layout);
    if points.is_empty() {
        return rsx! {};
    }
    let (stroke, width, dash) = edge_style(edge.kind);
    rsx! {
        path {
            key: "{edge.src}-{edge.dst}",
            class: "x-board-edge",
            "data-edge-kind": edge.kind.name(),
            d: "{path_data(&points)}",
            fill: "none",
            stroke: "{stroke}",
            stroke_width: "{width}",
            stroke_dasharray: "{dash}",
            stroke_linejoin: "round",
            marker_end: "url(#{marker})",
        }
    }
}

/// The bottom-left and bottom-right text of a card and of its detail pane: the type of the
/// node (a goal shows its slug in its place), and the statuses that the type does not say.
/// `answer` is the answer state of a goal (`GraphNode::answer`).
pub fn corners(kind: &NodeKind, slug: &str, rejected: bool, answer: &str) -> (String, Vec<String>) {
    let mut status: Vec<String> = Vec::new();
    if !answer.is_empty() {
        status.push(answer.to_string());
    }
    let left = match kind {
        NodeKind::Fact(k) => match k.as_str() {
            "origin" => "background".to_string(),
            "goal" => slug.to_string(),
            "correction" => "correction".to_string(),
            other => {
                status.push(kind_label(other).to_string());
                "finding".to_string()
            }
        },
        NodeKind::Intent(state) => {
            status.push(state.clone());
            "intent".to_string()
        }
    };
    if rejected {
        status.push("rejected".to_string());
    }
    (left, status)
}

/// One node: the title in bold, the summary under it, and a meta row with the type on the left
/// and the statuses on the right (`corners`). The origin and the goals have no title row. The classes in `assets/main.css` give the fonts. A dimmed node has an opaque
/// white card under its translucent card, so an edge under it does not show through.
pub fn render_node(
    node: &GraphNode,
    layout: &HashMap<String, NodePosition>,
    selected: &str,
    on_select: Callback<String>,
) -> Element {
    let Some(position) = layout.get(&node.id) else { return rsx! {} };
    let (fill, stroke, dash, _) = node_style(&node.kind);
    let is_selected = node.id == selected;
    let untitled = node.title.is_empty()
        || matches!(&node.kind, NodeKind::Fact(k) if k == "origin" || k == "goal");
    let running = matches!(&node.kind, NodeKind::Intent(s) if s == "running");
    let stroke_width = if is_selected { "3" } else if running { "2.4" } else { "1.2" };
    let opacity = if node.dimmed { "0.5" } else { "1" };
    let card_class = match &node.kind {
        NodeKind::Fact(k) if k == "goal" => "x-board-node-card x-board-node-untitled x-board-node-anchor",
        _ if untitled => "x-board-node-card x-board-node-untitled",
        _ => "x-board-node-card",
    };
    let title_class = if node.rejected { "x-board-node-title x-board-node-rejected" } else { "x-board-node-title" };
    let (left, status) = corners(&node.kind, &node.slug, node.rejected, &node.answer);
    let id = node.id.clone();
    rsx! {
        g {
            key: "{node.id}",
            class: "x-board-node",
            "data-node": "{node.id}",
            "data-slug": "{node.slug}",
            style: "cursor: pointer;",
            transform: "translate({position.x - NODE_WIDTH / 2.0}, {position.y - NODE_HEIGHT / 2.0})",
            onclick: move |_| on_select.call(id.clone()),
            if node.dimmed {
                rect { width: "{NODE_WIDTH}", height: "{NODE_HEIGHT}", rx: "8", fill: "#ffffff" }
            }
            g { opacity: "{opacity}",
                rect {
                    width: "{NODE_WIDTH}", height: "{NODE_HEIGHT}", rx: "8",
                    fill: "{fill}", stroke: "{stroke}", stroke_width: "{stroke_width}", stroke_dasharray: "{dash}",
                }
                foreignObject {
                    x: "0", y: "0", width: "{NODE_WIDTH}", height: "{NODE_HEIGHT}",
                    div { class: "{card_class}",
                        if !untitled {
                            div { class: "{title_class}", "{node.title}" }
                        }
                        div { class: "x-board-node-summary", "{node.summary}" }
                        div { class: "x-board-node-meta",
                            span { class: "x-board-node-type", title: "{left}", "{left}" }
                            span { class: "x-board-node-tags",
                                for (i, tag) in status.iter().enumerate() {
                                    span { key: "{i}", "{tag}" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/// The arrow head of the edges of one graph. `id` must be unique on the page.
#[component]
pub fn ArrowMarker(id: String) -> Element {
    rsx! {
        defs {
            marker {
                id: "{id}",
                view_box: "0 0 10 10",
                ref_x: "9",
                ref_y: "5",
                marker_width: "7",
                marker_height: "7",
                orient: "auto-start-reverse",
                path { d: "M 0 0 L 10 5 L 0 10 z", fill: "rgba(0,0,0,0.45)" }
            }
        }
    }
}

/// The small picture of a board on its overview card: the settled graph, without text.
#[component]
pub fn BoardThumbnail(input: BoardGraphInput) -> Element {
    let graph = build_graph(&input);
    let layout = settle(&graph, &HashMap::new());
    rsx! {
        svg {
            class: "x-board-thumbnail",
            width: "100%",
            height: "110",
            view_box: "0 0 {graph.width} {graph.height}",
            preserve_aspect_ratio: "xMidYMid meet",
            for edge in graph.edges.iter() {
                path {
                    key: "{edge.src}-{edge.dst}",
                    d: "{path_data(&edge_points(edge, &layout))}",
                    fill: "none",
                    stroke: "{edge_style(edge.kind).0}", stroke_width: "8", stroke_linejoin: "round",
                }
            }
            for node in graph.nodes.iter() {
                if let Some(p) = layout.get(&node.id) {
                    rect {
                        key: "{node.id}",
                        x: "{p.x - NODE_WIDTH / 2.0}", y: "{p.y - NODE_HEIGHT / 2.0}",
                        width: "{NODE_WIDTH}", height: "{NODE_HEIGHT}", rx: "14",
                        fill: "{node_style(&node.kind).0}", stroke: "{node_style(&node.kind).1}", stroke_width: "8",
                        opacity: if node.dimmed { "0.45" } else { "1" },
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
            rejected_by: String::new(),
            rejected_ms: 0,
            rejected_reason: String::new(),
            corrects: vec![],
            created_by: String::new(),
            created_ms: 0,
            citations: vec![],
            slug: id.into(),
            title: String::new(),
            summary: id.into(),
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
            questions: vec![],
            origin: String::new(),
            own: false,
            slug: id.into(),
            title: String::new(),
            summary: id.into(),
            asked: None,
        }
    }

    fn answer(goal: &str, from: &str) -> BoardReviewGoal {
        BoardReviewGoal { goal: goal.into(), from: vec![from.into()], statement: String::new(), reason_no: 1, ..Default::default() }
    }

    fn input(facts: Vec<BoardFact>, intents: Vec<BoardIntent>) -> BoardGraphInput {
        BoardGraphInput { status: "active".into(), facts, intents, answers_proposed: vec![], answers_accepted: vec![] }
    }

    #[test]
    fn depth_follows_the_facts_an_intent_names_and_the_goals_close_the_graph() {
        let graph = build_graph(&input(
            vec![
                fact("origin", "origin", ""),
                fact("goal", "goal", ""),
                fact("goal-2", "goal", ""),
                fact("f1.1", "sourced", "i1.1"),
                fact("f2.1", "inferred", "i2.1"),
            ],
            vec![intent("i1.1", &["origin", "goal"], 1), intent("i2.1", &["f1.1"], 2)],
        ));
        let depth: HashMap<&str, u32> = graph.nodes.iter().map(|n| (n.id.as_str(), n.depth)).collect();
        assert_eq!((depth["origin"], depth["i1.1"], depth["f1.1"], depth["i2.1"], depth["f2.1"]), (0, 1, 2, 3, 4));
        assert_eq!((depth["goal"], depth["goal-2"]), (5, 5));
        // origin to i1.1, i1.1 to f1.1, f1.1 to i2.1, i2.1 to f2.1. The goal gets no edge.
        assert_eq!(graph.edges.len(), 4);
    }

    #[test]
    fn the_answers_link_their_facts_to_each_goal_in_every_status_and_a_correction_to_its_facts() {
        let mut correction = fact("c1", "correction", "");
        correction.corrects = vec!["f1.1".into()];
        correction.created_ms = 5;
        let mut data = input(
            vec![
                fact("origin", "origin", ""),
                fact("goal", "goal", ""),
                fact("goal-2", "goal", ""),
                fact("f1.1", "sourced", "i1.1"),
                fact("f1.2", "not_found", "i1.2"),
                correction,
            ],
            vec![intent("i1.1", &["origin"], 1), intent("i1.2", &["origin"], 1)],
        );
        // An active board: goal is accepted, goal-2 waits for the person.
        data.answers_accepted = vec![answer("goal", "f1.1")];
        data.answers_proposed = vec![answer("goal-2", "f1.2")];
        let active = build_graph(&data);
        let kinds: Vec<(&str, &str, EdgeKind)> = active.edges.iter()
            .filter(|e| e.kind == EdgeKind::Answers || e.kind == EdgeKind::Proposed)
            .map(|e| (e.src.as_str(), e.dst.as_str(), e.kind)).collect();
        assert_eq!(kinds, vec![("f1.1", "goal", EdgeKind::Answers), ("f1.2", "goal-2", EdgeKind::Proposed)]);
        let answer_of = |id: &str| active.nodes.iter().find(|n| n.id == id).unwrap().answer.clone();
        assert_eq!((answer_of("goal"), answer_of("goal-2")), ("answered".to_string(), "answer proposed".to_string()));
        let corrects: Vec<_> = active.edges.iter().filter(|e| e.kind == EdgeKind::Corrects).collect();
        assert_eq!(corrects.len(), 1);
        assert_eq!((corrects[0].src.as_str(), corrects[0].dst.as_str()), ("f1.1", "c1"));
    }

    #[test]
    fn five_nodes_of_one_column_do_not_overlap() {
        let mut correction = fact("c1", "correction", "");
        correction.created_ms = 9;
        let graph = build_graph(&input(
            vec![
                fact("origin", "origin", ""),
                fact("goal", "goal", ""),
                fact("f1.1", "sourced", "i1.1"),
                fact("f1.2", "not_found", "i1.2"),
                fact("f2.1", "sourced", "i2.1"),
                fact("f2.2", "sourced", "i2.2"),
                correction,
            ],
            vec![
                intent("i1.1", &["origin"], 1),
                intent("i1.2", &["origin"], 1),
                intent("i2.1", &["origin"], 5),
                intent("i2.2", &["origin"], 5),
            ],
        ));
        let placed = settle(&graph, &HashMap::new());
        for a in &graph.nodes {
            for b in &graph.nodes {
                if a.id < b.id && a.depth == b.depth {
                    let gap = (placed[&a.id].y - placed[&b.id].y).abs();
                    assert!(gap >= NODE_HEIGHT, "{} and {} overlap: {:?} {:?}", a.id, b.id, placed[&a.id], placed[&b.id]);
                }
            }
        }
    }

    #[test]
    fn the_layout_settles_and_a_placed_node_keeps_its_place() {
        let first = build_graph(&input(
            vec![fact("origin", "origin", ""), fact("goal", "goal", "")],
            vec![intent("i1.1", &["origin"], 1), intent("i1.2", &["origin"], 1), intent("i1.3", &["origin"], 1)],
        ));
        let placed = settle(&first, &HashMap::new());
        let ids = ["i1.1", "i1.2", "i1.3"];
        for (a, b) in [(0, 1), (0, 2), (1, 2)] {
            assert!((placed[ids[a]].y - placed[ids[b]].y).abs() >= NODE_HEIGHT, "nodes of one column overlap");
        }
        // Settling the settled layout again moves nothing.
        assert_eq!(settle(&first, &placed), placed);
        let second = build_graph(&input(
            vec![fact("origin", "origin", ""), fact("goal", "goal", ""), fact("f1.1", "sourced", "i1.1")],
            vec![intent("i1.1", &["origin"], 1), intent("i1.2", &["origin"], 1), intent("i1.3", &["origin"], 1)],
        ));
        let next = settle(&second, &placed);
        for id in ids {
            assert_eq!(next[id].y, placed[id].y);
        }
        assert!(next["f1.1"].y.is_finite());
    }

    /// The shape of the local test board: origin, 2 goals, 3 intents with their facts, and
    /// 4 corrections, 2 of which correct `f1.1` and `f1.2`. The completed review links
    /// `f1.1` and `f1.2` to the goals across the correction column.
    fn test_board() -> BoardGraphInput {
        let mut facts = vec![
            fact("origin", "origin", ""),
            fact("goal", "goal", ""),
            fact("goal-2", "goal", ""),
            fact("f1.1", "sourced", "i1.1"),
            fact("f1.2", "sourced", "i1.2"),
            fact("f2.1", "not_found", "i2.1"),
        ];
        for (index, id) in ["c1", "c2", "c3", "c4"].into_iter().enumerate() {
            let mut correction = fact(id, "correction", "");
            correction.created_ms = 10 + index as i64;
            if index < 2 {
                correction.corrects = vec!["f1.1".into(), "f1.2".into()];
            }
            facts.push(correction);
        }
        let mut data = input(facts, vec![
            intent("i1.1", &["origin"], 1),
            intent("i1.2", &["origin"], 1),
            intent("i2.1", &["f1.2"], 5),
        ]);
        data.status = "completed".into();
        data.answers_accepted = vec![answer("goal", "f1.1"), answer("goal-2", "f1.2")];
        data
    }

    #[test]
    fn every_edge_is_one_line_from_the_right_side_of_its_source_to_the_left_side_of_its_target() {
        let graph = build_graph(&test_board());
        assert_eq!(graph.nodes.len(), 13);
        assert_eq!(graph.edges.iter().filter(|e| e.kind == EdgeKind::Answers).count(), 2);
        assert_eq!(graph.edges.iter().filter(|e| e.kind == EdgeKind::Corrects).count(), 4);
        let layout = settle(&graph, &HashMap::new());
        for edge in &graph.edges {
            let (src, dst) = (layout[&edge.src], layout[&edge.dst]);
            assert_eq!(
                edge_points(edge, &layout),
                vec![(src.x + NODE_WIDTH / 2.0, src.y), (dst.x - NODE_WIDTH / 2.0, dst.y)]
            );
        }
    }

    #[test]
    fn an_open_question_has_no_node_and_its_intent_follows_its_fact() {
        let mut asking = fact("f1.1", "sourced", "i1.1");
        asking.open_questions = vec!["Who signed?".into(), "When?".into()];
        let graph = build_graph(&input(
            vec![fact("origin", "origin", ""), fact("goal", "goal", ""), asking, fact("f0.1", "sourced", "i0.1")],
            vec![intent("i1.1", &["origin"], 1), intent("i0.1", &["f1.1"], 5)],
        ));
        assert_eq!(graph.nodes.len(), 6);
        let depth: HashMap<&str, u32> = graph.nodes.iter().map(|n| (n.id.as_str(), n.depth)).collect();
        assert_eq!((depth["f1.1"], depth["i0.1"], depth["f0.1"]), (2, 3, 4));
        assert!(graph.edges.iter().any(|e| e.src == "f1.1" && e.dst == "i0.1"));
    }

    #[test]
    fn a_card_shows_its_type_and_only_the_statuses_that_the_type_does_not_say() {
        let fact = |k: &str| NodeKind::Fact(k.to_string());
        let corner = |kind: NodeKind, slug: &str, rejected: bool| corners(&kind, slug, rejected, "");
        let words = |left: &str, right: &[&str]| (left.to_string(), right.iter().map(|w| w.to_string()).collect::<Vec<_>>());
        assert_eq!(corner(fact("origin"), "background", false), words("background", &[]));
        assert_eq!(corner(fact("goal"), "goal-01", false), words("goal-01", &[]));
        assert_eq!(corner(fact("sourced"), "fact-x", false), words("finding", &["sourced"]));
        assert_eq!(corner(fact("not_found"), "fact-x", true), words("finding", &["not found", "rejected"]));
        assert_eq!(corner(fact("correction"), "correction-x", false), words("correction", &[]));
        assert_eq!(corner(NodeKind::Intent("concluded".into()), "intent-x", false), words("intent", &["concluded"]));
        assert_eq!(corners(&fact("goal"), "goal-02", false, "answered"), words("goal-02", &["answered"]));
    }

    #[test]
    fn the_graph_has_fixed_node_sizes_and_bands_around_the_nodes() {
        let graph = build_graph(&test_board());
        let layout = settle(&graph, &HashMap::new());
        let top = layout.values().map(|p| p.y - NODE_HEIGHT / 2.0).fold(f64::INFINITY, f64::min);
        let bottom = layout.values().map(|p| p.y + NODE_HEIGHT / 2.0).fold(0.0, f64::max);
        let left = layout.values().map(|p| p.x - NODE_WIDTH / 2.0).fold(f64::INFINITY, f64::min);
        let right = layout.values().map(|p| p.x + NODE_WIDTH / 2.0).fold(0.0, f64::max);
        assert!(top >= MARGIN_Y - 0.1 && graph.height - bottom >= MARGIN_Y - 0.1, "{top} {bottom} {}", graph.height);
        assert_eq!((left, graph.width - right), (MARGIN_X, MARGIN_X));
    }
}
