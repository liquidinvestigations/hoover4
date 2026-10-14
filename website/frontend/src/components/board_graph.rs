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
//! it names to its fact. An accepted review is an edge from each fact that answers a goal to
//! that goal (Cairn's `complete`), drawn dashed while the review waits for the person. A
//! rejected review is an edge from each fact of that review to the correction that the person
//! wrote (Cairn's `reopen`, whose `external_feedback` intent leads to the correction fact).
//!
//! The layout is computed in one pass before it is shown, so no node moves on screen. x comes
//! from the depth. In each column, from left to right, a node asks for a y: its earlier y
//! when it was already placed, else the mean y of its placed neighbours. The column sorts by
//! that y and pushes its nodes apart to one row each. A node that was already placed keeps
//! its y unless a new node needs the room.

use std::collections::{HashMap, HashSet};

use common::board_types::{BoardFact, BoardGraphInput, BoardIntent};
use dioxus::prelude::*;

/// Simulation units of one depth column, and the smallest viewport.
pub const COLUMN_WIDTH: f64 = 310.0;
pub const MIN_WIDTH: f64 = 1000.0;
pub const MIN_HEIGHT: f64 = 620.0;
/// Vertical room of one node in the tallest column.
pub const ROW_HEIGHT: f64 = 132.0;
pub const NODE_WIDTH: f64 = 260.0;
pub const NODE_HEIGHT: f64 = 112.0;

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
    pub depth: u32,
    pub dimmed: bool,
    pub rejected: bool,
}

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum EdgeKind {
    /// From a fact to an intent, or from an intent to its fact.
    Flow,
    /// From a fact to the goal that an accepted review says it answers.
    Answers,
    /// From a fact to a goal, in a review that waits for the person.
    Proposed,
    /// From a fact of a rejected review to the correction.
    Corrects,
}

impl EdgeKind {
    /// An edge from a fact to a goal.
    pub fn is_review(self) -> bool {
        matches!(self, EdgeKind::Answers | EdgeKind::Proposed)
    }

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
                    depth: d,
                    dimmed: intent.state == "cancelled",
                    rejected: false,
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
        nodes.push(fact_node(goal, last));
    }
    let review_kind = match input.status.as_str() {
        "completed" => Some(EdgeKind::Answers),
        "review" => Some(EdgeKind::Proposed),
        _ => None,
    };
    if let Some(kind) = review_kind {
        let placed: HashSet<&str> = nodes.iter().map(|n| n.id.as_str()).collect();
        for review in &input.review_goals {
            if !placed.contains(review.goal.as_str()) {
                continue;
            }
            for from in &review.from {
                if placed.contains(from.as_str()) && !goal_ids.contains(from.as_str()) {
                    edges.push(GraphEdge { src: from.clone(), dst: review.goal.clone(), kind });
                }
            }
        }
    }

    let mut per_column: HashMap<u32, u32> = HashMap::new();
    for node in &nodes {
        *per_column.entry(node.depth).or_default() += 1;
    }
    let tallest = per_column.values().copied().max().unwrap_or(1);
    Graph {
        width: MIN_WIDTH.max((last + 1) as f64 * COLUMN_WIDTH + 40.0),
        height: MIN_HEIGHT.max(tallest as f64 * ROW_HEIGHT + 60.0),
        nodes,
        edges,
    }
}

fn fact_node(fact: &BoardFact, depth: u32) -> GraphNode {
    GraphNode {
        id: fact.fact_id.clone(),
        kind: NodeKind::Fact(fact.kind.clone()),
        text: fact.text.clone(),
        depth,
        dimmed: fact.rejected,
        rejected: fact.rejected,
    }
}

/// `i3.2` sorts as (3, 2), so `i10.1` comes after `i9.1`.
fn intent_order(id: &str) -> (u32, u32) {
    let mut parts = id.trim_start_matches('i').split('.').map(|p| p.parse().unwrap_or(0));
    (parts.next().unwrap_or(0), parts.next().unwrap_or(0))
}

pub fn target_x(depth: u32) -> f64 {
    20.0 + NODE_WIDTH / 2.0 + depth as f64 * COLUMN_WIDTH
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
    let (top, bottom) = (NODE_HEIGHT / 2.0 + 4.0, graph.height - NODE_HEIGHT / 2.0 - 4.0);
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
        "origin" => "origin",
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

/// Colour, width and dash pattern of an edge.
pub fn edge_style(kind: EdgeKind) -> (&'static str, &'static str, &'static str) {
    match kind {
        EdgeKind::Flow => ("rgba(0,0,0,0.35)", "1.4", ""),
        EdgeKind::Answers => ("#1e8e3e", "2.2", ""),
        EdgeKind::Proposed => ("#1e8e3e", "2", "6 4"),
        EdgeKind::Corrects => ("#9334e6", "1.8", "4 3"),
    }
}

pub fn render_edge(edge: &GraphEdge, layout: &HashMap<String, NodePosition>, marker: &str) -> Element {
    let (Some(src), Some(dst)) = (layout.get(&edge.src), layout.get(&edge.dst)) else {
        return rsx! {};
    };
    let (x1, x2) = if dst.x >= src.x {
        (src.x + NODE_WIDTH / 2.0, dst.x - NODE_WIDTH / 2.0)
    } else {
        (src.x - NODE_WIDTH / 2.0, dst.x + NODE_WIDTH / 2.0)
    };
    let (stroke, width, dash) = edge_style(edge.kind);
    rsx! {
        line {
            key: "{edge.src}-{edge.dst}",
            class: "x-board-edge",
            "data-edge-kind": edge.kind.name(),
            x1: "{x1}", y1: "{src.y}", x2: "{x2}", y2: "{dst.y}",
            stroke: "{stroke}",
            stroke_width: "{width}",
            stroke_dasharray: "{dash}",
            marker_end: "url(#{marker})",
        }
    }
}

/// One node: the title in the body font of the page, and the text of the card under it in
/// a small font, as many lines as the card holds.
pub fn render_node(
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
    let sub_colour = if anchor { "rgba(255,255,255,0.88)" } else { "rgba(0,0,0,0.62)" };
    let running = matches!(&node.kind, NodeKind::Intent(s) if s == "running");
    let stroke_width = if is_selected { "3" } else if running { "2.4" } else { "1.2" };
    let opacity = if node.dimmed { "0.5" } else { "1" };
    let title = if node.rejected {
        format!("{} \u{00b7} {tag} \u{00b7} rejected", node.id)
    } else {
        format!("{} \u{00b7} {tag}", node.id)
    };
    let title_decoration = if node.rejected { "line-through" } else { "none" };
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
            foreignObject {
                x: "0", y: "0", width: "{NODE_WIDTH}", height: "{NODE_HEIGHT}",
                div {
                    style: "box-sizing: border-box; height: 100%; padding: 6px 9px; overflow: hidden; display: flex; flex-direction: column; gap: 3px; pointer-events: none;",
                    div {
                        style: "font-size: 12px; font-weight: 600; color: {text_colour}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-decoration: {title_decoration};",
                        "{title}"
                    }
                    div {
                        class: "x-board-node-text",
                        style: "font-size: 10px; line-height: 1.3; color: {sub_colour}; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 6; -webkit-box-orient: vertical; word-break: break-word;",
                        "{node.text}"
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
                if let (Some(a), Some(b)) = (layout.get(&edge.src), layout.get(&edge.dst)) {
                    line {
                        key: "{edge.src}-{edge.dst}",
                        x1: "{a.x}", y1: "{a.y}", x2: "{b.x}", y2: "{b.y}",
                        stroke: "{edge_style(edge.kind).0}", stroke_width: "8",
                    }
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
    use common::board_types::BoardReviewGoal;

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

    fn input(facts: Vec<BoardFact>, intents: Vec<BoardIntent>) -> BoardGraphInput {
        BoardGraphInput { status: "active".into(), facts, intents, review_goals: vec![] }
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
    fn a_review_links_its_facts_to_each_goal_and_a_correction_to_the_facts_it_corrects() {
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
        data.review_goals = vec![
            BoardReviewGoal { goal: "goal".into(), from: vec!["f1.1".into()], statement: String::new() },
            BoardReviewGoal { goal: "goal-2".into(), from: vec!["f1.2".into()], statement: String::new() },
        ];
        let active = build_graph(&data);
        assert!(active.edges.iter().all(|e| e.kind != EdgeKind::Answers && e.kind != EdgeKind::Proposed));
        let corrects: Vec<_> = active.edges.iter().filter(|e| e.kind == EdgeKind::Corrects).collect();
        assert_eq!(corrects.len(), 1);
        assert_eq!((corrects[0].src.as_str(), corrects[0].dst.as_str()), ("f1.1", "c1"));
        data.status = "review".into();
        assert_eq!(build_graph(&data).edges.iter().filter(|e| e.kind == EdgeKind::Proposed).count(), 2);
        data.status = "completed".into();
        let done = build_graph(&data);
        assert!(done.edges.iter().any(|e| e.kind == EdgeKind::Answers && e.src == "f1.2" && e.dst == "goal-2"));
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
}
