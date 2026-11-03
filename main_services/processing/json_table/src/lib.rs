//! Flatten JSON and JSON Lines into table sheets with a frozen column schema.
//!
//! The program reads a file twice. Pass 1 discovers the sheets and the column paths of
//! each sheet. The schema is then frozen: the column identities stay the same for every
//! row of pass 2, which writes the cells. See `Readme.md` beside this crate for the
//! output protocol and every limit.

use std::cell::Cell;
use std::collections::HashMap;
use std::fmt;
use std::io::{self, BufRead, Read};
use std::rc::Rc;

use serde::de::{DeserializeSeed, IgnoredAny, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Value};

/// Columns of one sheet. The Python collector stores at most this many.
pub const MAX_COLUMNS: usize = 1000;
/// Schema nodes that discovery keeps for one sheet before it collapses subtrees.
pub const MAX_SCHEMA_NODES: usize = 50_000;
/// Object levels that become dot paths. A deeper object is one JSON text cell.
pub const MAX_FLATTEN_DEPTH: usize = 16;
/// Object keys between the root and an array that becomes a sheet.
pub const MAX_SHEET_DEPTH: usize = 3;
/// Sheets of one document.
pub const MAX_SHEETS: usize = 100;
/// Source bytes of one row: one JSON Lines line or one array element.
pub const MAX_VALUE_BYTES: u64 = 64 * 1024 * 1024;
/// Bytes of cell text that the program writes. The collector truncates at 64 KiB and
/// records the truncation, so the program writes a few bytes more than that limit.
pub const MAX_CELL_OUTPUT_BYTES: usize = 64 * 1024 + 4;
/// The most bytes of an indented JSON cell. A nested value whose indented text is longer
/// is written compact and cut at [`MAX_CELL_OUTPUT_BYTES`].
pub const MAX_PRETTY_BYTES: usize = 64 * 1024;
/// Bytes that the format check reads.
pub const SAMPLE_BYTES: usize = 64 * 1024;

/// The grammar of a file.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Json,
    JsonLines,
}

impl Mode {
    pub fn name(self) -> &'static str {
        match self {
            Mode::Json => "json",
            Mode::JsonLines => "jsonl",
        }
    }
}

/// Why a file gives no table. The caller treats it as valid output without a table.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NoTable(pub String);

/// Choose the grammar from the start of a file, or say why it is not JSON.
///
/// The file is JSON Lines when its first two nonblank lines are each one complete JSON
/// object or array. A later line that does not parse fails the read with its line number.
/// Every other file that starts with `{` or `[` is one JSON value.
pub fn detect_mode(sample: &[u8], whole_file: bool) -> Result<Mode, NoTable> {
    if sample.starts_with(&[0xFE, 0xFF]) || sample.starts_with(&[0xFF, 0xFE]) {
        return Err(NoTable("unsupported encoding: UTF-16 or UTF-32".into()));
    }
    let body = strip_bom(sample);
    match body.iter().find(|b| !b.is_ascii_whitespace()) {
        Some(b'{') | Some(b'[') => {}
        _ => return Err(NoTable("the file does not start with a JSON object or array".into())),
    }
    let mut lines: Vec<&[u8]> = body.split(|b| *b == b'\n').collect();
    if !whole_file && !lines.is_empty() {
        lines.pop();
    }
    let lines: Vec<&[u8]> = lines
        .into_iter()
        .map(trim_ascii)
        .filter(|line| !line.is_empty())
        .collect();
    let complete = |line: &&[u8]| {
        matches!(line.first(), Some(b'{') | Some(b'['))
            && serde_json::from_slice::<IgnoredAny>(line).is_ok()
    };
    if lines.len() >= 2 && lines.iter().take(2).all(complete) {
        Ok(Mode::JsonLines)
    } else {
        Ok(Mode::Json)
    }
}

pub fn strip_bom(data: &[u8]) -> &[u8] {
    data.strip_prefix(&[0xEF, 0xBB, 0xBF]).unwrap_or(data)
}

fn trim_ascii(line: &[u8]) -> &[u8] {
    let start = line.iter().position(|b| !b.is_ascii_whitespace()).unwrap_or(line.len());
    let end = line.iter().rposition(|b| !b.is_ascii_whitespace()).map_or(start, |i| i + 1);
    &line[start..end]
}

// ---- display labels -------------------------------------------------------------------

/// The label of the column that holds a row that is not an object.
pub const ROOT_LABEL: &str = "$";
/// The label of the column that holds the root keys beyond the column limit.
pub const REST_LABEL: &str = "*";

/// One key component as a label part. The escaping is reversible: a backslash and a dot
/// get a backslash, an empty key is `\e`, and the reserved labels `$` and `*` get a
/// backslash.
pub fn escape_component(key: &str) -> String {
    if key.is_empty() {
        return "\\e".into();
    }
    if key == ROOT_LABEL || key == REST_LABEL {
        return format!("\\{key}");
    }
    let mut out = String::with_capacity(key.len());
    for ch in key.chars() {
        if ch == '\\' || ch == '.' {
            out.push('\\');
        }
        out.push(ch);
    }
    out
}

/// The display label of a key path.
pub fn label_of(path: &[String]) -> String {
    if path.is_empty() {
        return ROOT_LABEL.into();
    }
    path.iter().map(|k| escape_component(k)).collect::<Vec<_>>().join(".")
}

/// The key path of a display label. The inverse of [`label_of`] for a key column.
pub fn path_of(label: &str) -> Vec<String> {
    if label == ROOT_LABEL {
        return Vec::new();
    }
    let mut parts = Vec::new();
    let mut current = String::new();
    let mut chars = label.chars();
    while let Some(ch) = chars.next() {
        match ch {
            '\\' => match chars.next() {
                Some('e') => {}
                Some(next) => current.push(next),
                None => current.push('\\'),
            },
            '.' => parts.push(std::mem::take(&mut current)),
            other => current.push(other),
        }
    }
    parts.push(current);
    parts
}

/// The name of a sheet at a key path. The root array is `$`.
pub fn sheet_name(path: &[String]) -> String {
    if path.is_empty() {
        "$".into()
    } else {
        format!("$.{}", label_of(path))
    }
}

// ---- the schema of one sheet ----------------------------------------------------------

#[derive(Debug, Default)]
struct Node {
    key: String,
    children: Vec<usize>,
    index: HashMap<String, usize>,
    /// A scalar, an array, an empty object or an object beyond the depth limit was here.
    scalar: bool,
    /// The subtree is one JSON text column.
    collapsed: bool,
    /// The node left the schema. A dropped root key goes to the rest column.
    dropped: bool,
    seq: u64,
}

/// One column of a frozen schema.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Column {
    pub id: u32,
    pub path: Vec<String>,
    pub label: String,
    /// The column holds JSON text of a collapsed subtree.
    pub json: bool,
    /// The column holds the root keys beyond the limit, as one JSON object.
    pub rest: bool,
}

/// The column paths of one sheet. `observe` grows it in pass 1, `freeze` fixes it.
#[derive(Debug)]
pub struct Schema {
    nodes: Vec<Node>,
    live: usize,
    next_seq: u64,
    /// No new root key enters the schema.
    root_full: bool,
    rest: bool,
    pub collapsed_subtrees: u32,
}

impl Default for Schema {
    fn default() -> Self {
        Schema {
            nodes: vec![Node::default()],
            live: 1,
            next_seq: 1,
            root_full: false,
            rest: false,
            collapsed_subtrees: 0,
        }
    }
}

impl Schema {
    pub fn observe(&mut self, value: &Value) {
        self.observe_at(0, value, 0);
        if self.live > MAX_SCHEMA_NODES {
            self.shrink(MAX_SCHEMA_NODES / 2);
        }
    }

    fn observe_at(&mut self, node: usize, value: &Value, depth: usize) {
        if self.nodes[node].collapsed {
            return;
        }
        match value {
            Value::Object(map) if !map.is_empty() && depth < MAX_FLATTEN_DEPTH => {
                for (key, child_value) in map {
                    let child = match self.nodes[node].index.get(key) {
                        Some(&child) => child,
                        None => {
                            if node == 0 && self.root_full {
                                self.rest = true;
                                continue;
                            }
                            self.add_child(node, key)
                        }
                    };
                    if self.nodes[child].dropped {
                        self.rest = true;
                        continue;
                    }
                    self.observe_at(child, child_value, depth + 1);
                }
            }
            _ => self.nodes[node].scalar = true,
        }
    }

    fn add_child(&mut self, parent: usize, key: &str) -> usize {
        let id = self.nodes.len();
        self.nodes.push(Node { key: key.to_string(), seq: self.next_seq, ..Node::default() });
        self.next_seq += 1;
        self.nodes[parent].children.push(id);
        self.nodes[parent].index.insert(key.to_string(), id);
        self.live += 1;
        id
    }

    /// Columns of a subtree.
    fn columns_of(&self, node: usize) -> usize {
        let n = &self.nodes[node];
        if n.dropped {
            return 0;
        }
        if n.collapsed {
            return 1;
        }
        usize::from(n.scalar)
            + n.children.iter().map(|&c| self.columns_of(c)).sum::<usize>()
    }

    fn total_columns(&self) -> usize {
        self.columns_of(0) + usize::from(self.rest)
    }

    fn nodes_of(&self, node: usize) -> usize {
        let n = &self.nodes[node];
        if n.dropped || n.collapsed {
            return 0;
        }
        n.children.iter().map(|&c| 1 + self.nodes_of(c)).sum()
    }

    /// The non-root object with the most columns, the earliest one on a tie. Only an
    /// object with two or more columns makes the sheet narrower when it collapses.
    fn widest_object(&self) -> Option<usize> {
        let mut best: Option<(usize, u64, usize)> = None;
        let mut stack: Vec<usize> = self.nodes[0].children.clone();
        while let Some(node) = stack.pop() {
            let n = &self.nodes[node];
            if n.dropped || n.collapsed || n.children.is_empty() {
                continue;
            }
            let columns = self.columns_of(node);
            if columns >= 2 && best.map_or(true, |(c, s, _)| columns > c || (columns == c && n.seq < s)) {
                best = Some((columns, n.seq, node));
            }
            stack.extend(n.children.iter().copied());
        }
        best.map(|(_, _, node)| node)
    }

    fn collapse(&mut self, node: usize) {
        let removed = self.nodes_of(node);
        self.nodes[node].collapsed = true;
        self.live -= removed;
        self.collapsed_subtrees += 1;
    }

    /// Collapse the widest objects until the schema keeps at most `target` nodes. When
    /// the root keys alone exceed it, later root keys go to the rest column.
    fn shrink(&mut self, target: usize) {
        while self.live > target {
            match self.widest_object() {
                Some(node) => self.collapse(node),
                None => break,
            }
        }
        if self.live > target {
            self.root_full = true;
            let keep = target.saturating_sub(1);
            let children = self.nodes[0].children.clone();
            for &child in children.iter().skip(keep) {
                if !self.nodes[child].dropped {
                    self.nodes[child].dropped = true;
                    self.live -= 1;
                }
            }
            self.rest = true;
        }
    }

    /// Collapse objects until the sheet has at most [`MAX_COLUMNS`] columns, then assign
    /// the column identities in first-appearance order.
    pub fn freeze(mut self) -> FrozenSchema {
        while self.total_columns() > MAX_COLUMNS {
            match self.widest_object() {
                Some(node) => self.collapse(node),
                None => {
                    // A flat record: keep the earliest root keys and put the others
                    // into the rest column.
                    let room = MAX_COLUMNS - 1 - usize::from(self.nodes[0].scalar);
                    let mut used = 0;
                    let children = self.nodes[0].children.clone();
                    for child in children {
                        if self.nodes[child].dropped {
                            continue;
                        }
                        let columns = self.columns_of(child);
                        if used + columns <= room {
                            used += columns;
                        } else {
                            self.nodes[child].dropped = true;
                        }
                    }
                    self.rest = true;
                    self.root_full = true;
                }
            }
        }
        let mut frozen = FrozenSchema {
            columns: Vec::new(),
            scalar_column: HashMap::new(),
            rest_column: None,
            collapsed_subtrees: self.collapsed_subtrees,
            schema: self,
        };
        let mut path = Vec::new();
        frozen.assign(0, &mut path);
        if frozen.schema.rest {
            let id = frozen.columns.len() as u32 + 1;
            frozen.columns.push(Column { id, path: Vec::new(), label: REST_LABEL.into(), json: true, rest: true });
            frozen.rest_column = Some(id);
        }
        frozen
    }
}

/// A schema whose column identities no longer change.
#[derive(Debug)]
pub struct FrozenSchema {
    pub columns: Vec<Column>,
    scalar_column: HashMap<usize, u32>,
    rest_column: Option<u32>,
    pub collapsed_subtrees: u32,
    schema: Schema,
}

/// The kind of one cell in the output protocol.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CellKind {
    Text,
    Number,
    Bool,
    Json,
}

impl CellKind {
    pub fn code(self) -> &'static str {
        match self {
            CellKind::Text => "s",
            CellKind::Number => "n",
            CellKind::Bool => "b",
            CellKind::Json => "j",
        }
    }
}

/// One cell of a row: the column, its kind and its text.
pub type OutCell = (u32, CellKind, String);

impl FrozenSchema {
    fn assign(&mut self, node: usize, path: &mut Vec<String>) {
        let (dropped, collapsed, scalar, children) = {
            let n = &self.schema.nodes[node];
            (n.dropped, n.collapsed, n.scalar, n.children.clone())
        };
        if dropped {
            return;
        }
        if collapsed || scalar {
            let id = self.columns.len() as u32 + 1;
            self.columns.push(Column { id, path: path.clone(), label: label_of(path), json: collapsed, rest: false });
            self.scalar_column.insert(node, id);
        }
        if collapsed {
            return;
        }
        for child in children {
            path.push(self.schema.nodes[child].key.clone());
            self.assign(child, path);
            path.pop();
        }
    }

    /// The cells of one row, in column order. A key that discovery did not keep goes to
    /// the rest column, and a duplicate key keeps its last value.
    pub fn cells(&self, value: &Value) -> Vec<OutCell> {
        let mut out = Vec::new();
        let mut rest = Map::new();
        self.emit(0, value, 0, &mut out, &mut rest);
        if !rest.is_empty() {
            if let Some(id) = self.rest_column {
                out.push((id, CellKind::Json, json_text(&Value::Object(rest))));
            }
        }
        out.sort_by_key(|cell| cell.0);
        out
    }

    fn emit(&self, node: usize, value: &Value, depth: usize, out: &mut Vec<OutCell>, rest: &mut Map<String, Value>) {
        let n = &self.schema.nodes[node];
        if n.collapsed {
            if let Some(&id) = self.scalar_column.get(&node) {
                out.extend(cell_of(id, value));
            }
            return;
        }
        match value {
            Value::Object(map) if !map.is_empty() && depth < MAX_FLATTEN_DEPTH => {
                for (key, child_value) in map {
                    match n.index.get(key) {
                        Some(&child) if !self.schema.nodes[child].dropped => {
                            self.emit(child, child_value, depth + 1, out, rest)
                        }
                        _ if node == 0 => {
                            rest.insert(key.clone(), child_value.clone());
                        }
                        _ => {}
                    }
                }
            }
            _ => {
                if let Some(&id) = self.scalar_column.get(&node) {
                    out.extend(cell_of(id, value));
                }
            }
        }
    }
}

/// The cell of one value. A JSON `null` is an empty cell, so the program writes none.
fn cell_of(id: u32, value: &Value) -> Option<OutCell> {
    Some(match value {
        Value::String(text) => (id, CellKind::Text, cap_text(text.clone())),
        Value::Number(number) => (id, CellKind::Number, number.to_string()),
        Value::Bool(flag) => (id, CellKind::Bool, flag.to_string()),
        Value::Null => return None,
        other => (id, CellKind::Json, json_text(other)),
    })
}

/// The text of a nested value: indented when it fits [`MAX_PRETTY_BYTES`], otherwise
/// compact and cut at [`MAX_CELL_OUTPUT_BYTES`].
pub fn json_text(value: &Value) -> String {
    let compact = value.to_string();
    if compact.len() <= MAX_PRETTY_BYTES {
        if let Ok(pretty) = serde_json::to_string_pretty(value) {
            if pretty.len() <= MAX_PRETTY_BYTES {
                return pretty;
            }
        }
    }
    cap_text(compact)
}

/// Text cut at [`MAX_CELL_OUTPUT_BYTES`] on a character boundary.
pub fn cap_text(mut text: String) -> String {
    if text.len() > MAX_CELL_OUTPUT_BYTES {
        let mut end = MAX_CELL_OUTPUT_BYTES;
        while !text.is_char_boundary(end) {
            end -= 1;
        }
        text.truncate(end);
    }
    text
}

// ---- bounded reading ------------------------------------------------------------------

/// A reader that counts its bytes and refuses a row that grows beyond the value limit.
pub struct Counted<R> {
    inner: R,
    pos: Rc<Cell<u64>>,
    row_start: Rc<Cell<Option<u64>>>,
}

impl<R: Read> Counted<R> {
    pub fn new(inner: R) -> (Self, Rc<Cell<u64>>, Rc<Cell<Option<u64>>>) {
        let pos = Rc::new(Cell::new(0));
        let row_start = Rc::new(Cell::new(None));
        (Counted { inner, pos: pos.clone(), row_start: row_start.clone() }, pos, row_start)
    }
}

impl<R: Read> Read for Counted<R> {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        if let Some(start) = self.row_start.get() {
            if self.pos.get().saturating_sub(start) > MAX_VALUE_BYTES {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!("a row is larger than {MAX_VALUE_BYTES} bytes"),
                ));
            }
        }
        let n = self.inner.read(buf)?;
        self.pos.set(self.pos.get() + n as u64);
        Ok(n)
    }
}

/// Receives each row of each candidate sheet in file order.
pub trait RowSink {
    fn row(&mut self, sheet_path: &[String], value: Value) -> Result<(), String>;
}

struct Walk<'a, S: RowSink> {
    path: Vec<String>,
    sink: &'a mut S,
    row_start: Rc<Cell<Option<u64>>>,
    pos: Rc<Cell<u64>>,
}

impl<'de, S: RowSink> DeserializeSeed<'de> for Walk<'_, S> {
    type Value = ();
    fn deserialize<D: serde::Deserializer<'de>>(self, deserializer: D) -> Result<(), D::Error> {
        deserializer.deserialize_any(self)
    }
}

impl<'de, S: RowSink> Visitor<'de> for Walk<'_, S> {
    type Value = ();

    fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str("a JSON value")
    }

    fn visit_bool<E>(self, _: bool) -> Result<(), E> { Ok(()) }
    fn visit_i64<E>(self, _: i64) -> Result<(), E> { Ok(()) }
    fn visit_u64<E>(self, _: u64) -> Result<(), E> { Ok(()) }
    fn visit_f64<E>(self, _: f64) -> Result<(), E> { Ok(()) }
    fn visit_str<E>(self, _: &str) -> Result<(), E> { Ok(()) }
    fn visit_unit<E>(self) -> Result<(), E> { Ok(()) }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<(), A::Error> {
        let Walk { mut path, sink, row_start, pos } = self;
        // `arbitrary_precision` reads a number through a map with one private key.
        while let Some(key) = map.next_key::<String>()? {
            if path.len() >= MAX_SHEET_DEPTH {
                map.next_value::<IgnoredAny>()?;
                continue;
            }
            path.push(key);
            map.next_value_seed(Walk { path: path.clone(), sink: &mut *sink, row_start: row_start.clone(), pos: pos.clone() })?;
            path.pop();
        }
        Ok(())
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<(), A::Error> {
        loop {
            self.row_start.set(Some(self.pos.get()));
            let element = seq.next_element::<Value>();
            self.row_start.set(None);
            match element? {
                Some(value) => self
                    .sink
                    .row(&self.path, value)
                    .map_err(serde::de::Error::custom)?,
                None => return Ok(()),
            }
        }
    }
}

/// Walk one JSON document and send each element of each candidate array to `sink`.
pub fn walk_json<R: Read, S: RowSink>(reader: R, sink: &mut S) -> Result<(), String> {
    let (counted, pos, row_start) = Counted::new(reader);
    let mut deserializer = serde_json::Deserializer::from_reader(io::BufReader::new(counted));
    Walk { path: Vec::new(), sink, row_start, pos }
        .deserialize(&mut deserializer)
        .map_err(|e| e.to_string())?;
    deserializer.end().map_err(|e| e.to_string())
}

/// Send each nonblank line of a JSON Lines file to `sink` as a row of one sheet.
pub fn walk_json_lines<R: BufRead, S: RowSink>(mut reader: R, sink: &mut S) -> Result<(), String> {
    let mut line = Vec::new();
    let mut number = 0u64;
    loop {
        line.clear();
        number += 1;
        let read = (&mut reader)
            .take(MAX_VALUE_BYTES + 1)
            .read_until(b'\n', &mut line)
            .map_err(|e| e.to_string())?;
        if read == 0 {
            return Ok(());
        }
        if line.len() as u64 > MAX_VALUE_BYTES {
            return Err(format!("line {number} is larger than {MAX_VALUE_BYTES} bytes"));
        }
        let text = trim_ascii(if number == 1 { strip_bom(&line) } else { &line });
        if text.is_empty() {
            continue;
        }
        let value: Value = serde_json::from_slice(text).map_err(|e| format!("line {number}: {e}"))?;
        sink.row(&[], value)?;
    }
}

// ---- sheets ---------------------------------------------------------------------------

/// What pass 1 learns about one candidate sheet.
#[derive(Debug, Default)]
pub struct Candidate {
    pub path: Vec<String>,
    pub schema: Schema,
    pub rows: u64,
    pub objects: u64,
}

/// Pass 1: the candidate sheets in file order.
#[derive(Debug, Default)]
pub struct Discovery {
    pub candidates: Vec<Candidate>,
    index: HashMap<Vec<String>, usize>,
    pub sheets_truncated: bool,
}

impl RowSink for Discovery {
    fn row(&mut self, sheet_path: &[String], value: Value) -> Result<(), String> {
        let index = match self.index.get(sheet_path) {
            Some(&index) => index,
            None => {
                if self.candidates.iter().filter(|c| c.objects > 0).count() >= MAX_SHEETS {
                    self.sheets_truncated = true;
                    return Ok(());
                }
                self.candidates.push(Candidate { path: sheet_path.to_vec(), ..Candidate::default() });
                self.index.insert(sheet_path.to_vec(), self.candidates.len() - 1);
                self.candidates.len() - 1
            }
        };
        let candidate = &mut self.candidates[index];
        candidate.rows += 1;
        if value.is_object() {
            candidate.objects += 1;
        }
        candidate.schema.observe(&value);
        Ok(())
    }
}

/// One sheet with its frozen schema.
#[derive(Debug)]
pub struct Sheet {
    pub id: u16,
    pub path: Vec<String>,
    pub name: String,
    pub rows: u64,
    pub schema: FrozenSchema,
}

impl Discovery {
    /// The sheets: each candidate array with at least one object, at most [`MAX_SHEETS`].
    pub fn sheets(self, mode: Mode) -> Vec<Sheet> {
        self.candidates
            .into_iter()
            .filter(|c| c.objects > 0)
            .take(MAX_SHEETS)
            .enumerate()
            .map(|(id, c)| Sheet {
                id: id as u16,
                name: if mode == Mode::JsonLines { String::new() } else { sheet_name(&c.path) },
                path: c.path,
                rows: c.rows,
                schema: c.schema.freeze(),
            })
            .collect()
    }
}

#[cfg(test)]
mod tests;
