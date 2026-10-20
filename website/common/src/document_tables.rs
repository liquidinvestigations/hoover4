//! Shared types for browsing a tabular document's cells.
//!
//! A spreadsheet or delimited-text file is stored one cell per row in ClickHouse:
//! `table_cells` holds the cells, keyed by content hash alone, and `table_documents`,
//! `table_sheets` and `table_columns` hold the per-dataset manifest, the per-sheet
//! extents and the per-column statistics. This module is the wire vocabulary between the
//! backend that queries those tables and the grid that draws them, and it owns the two
//! server-side caps so both halves quote the same number.
//!
//! Three facts about the storage shape the types below:
//!
//! * `row_id` is 1-based, dense, and restarts at 1 in every sheet. It is pagination
//!   arithmetic. `source_row` is the row number the file itself gives and is what the
//!   grid's `#` column draws, because someone comparing the browser against the same file
//!   open in a spreadsheet application is the normal case.
//! * `column_id` is 1-based as the file gives it, so gaps survive, and only non-empty
//!   cells exist: an absent `(column_id, row_id)` is empty by construction.
//! * `sheet_id` values are the workbook's own sheet ordinals and are **not contiguous**,
//!   a sheet that produced no cells is absent. Sheet pickers are built from
//!   [`TableOverview::sheets`], never from a range.

use serde::{Deserialize, Serialize};

/// The find text without its double-quote phrase delimiters.
///
/// The backend adds this text to the words that the search engine matched in the document.
/// The cells are searched for each of these terms. When a response has no excerpt, the grid
/// builds its own excerpt with this text as the one term.
pub fn table_find_text(query: &str) -> String {
    query.replace(['"', '“', '”'], "").trim().to_string()
}

/// Most rows one page request may return, however large a limit is asked for.
///
/// Reported back in [`TableClamps`] rather than applied silently: a grid that quietly
/// returns 200 of the 5 000 rows it was asked for looks exactly like a grid whose
/// document ends at row 200.
pub const MAX_TABLE_PAGE_ROWS: u32 = 200;

/// Most columns one page request may draw at once.
pub const MAX_TABLE_VISIBLE_COLUMNS: usize = 60;

/// Rows per page the explorer asks for by default.
pub const DEFAULT_TABLE_PAGE_ROWS: u32 = 50;

/// Most distinct values the filter popover's value list offers.
pub const MAX_TABLE_COLUMN_VALUES: u32 = 200;

/// One sheet of a workbook, as `table_sheets` records it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct TableSheet {
    /// The workbook's own sheet ordinal. Not an index into [`TableOverview::sheets`].
    pub sheet_id: u16,
    /// Sheet name as the file gives it. Empty for a delimited file's single sheet.
    pub name: String,
    /// Rows a reader can page through: the sheet's stored rows **less its header row**.
    /// The header row is stored as ordinary cells but is drawn as the column labels, so
    /// counting it again as a data row would show every reader one row too many.
    pub row_count: u64,
    pub column_count: u32,
    /// `row_id` the column headers came from, `0` when the sheet has no usable header.
    /// It is the display choice of the website grid. [`Self::header_candidates`] gives
    /// every reading of the first row that the reader found plausible.
    pub header_row: u64,
    /// A cap fired while reading this sheet.
    pub truncated: bool,
    /// [`HEADER_ESTABLISHED`], [`HEADER_AMBIGUOUS`] or [`HEADER_LEGACY`]. Empty in a value
    /// from before the field existed, which reads as legacy.
    #[serde(default)]
    pub header_state: String,
    /// [`HEADER_BASIS_FORMAT`], [`HEADER_BASIS_HEURISTIC`] or [`HEADER_BASIS_MISSING`].
    #[serde(default)]
    pub header_basis: String,
    /// The header `row_id` of each plausible reading, `0` for the reading with no header.
    /// Empty for a legacy sheet. [`resolve_sheet_interpretation`] derives the legacy
    /// candidates.
    #[serde(default)]
    pub header_candidates: Vec<u64>,
}

impl TableSheet {
    /// The `row_id` of the last stored row of the sheet. Stored rows count from `row_id` 1
    /// and include the header row and any rows above it. [`Self::row_count`] counts only
    /// the data rows after the header, so a query that bounds `row_id` by `row_count`
    /// drops the last data rows. The value is correct when `header_row` is at or below the
    /// stored row count, which the overview reader gives.
    pub fn last_row_id(&self) -> u64 {
        self.row_count + self.header_row
    }

    /// What the sheet picker shows. A delimited file's sheet has no name of its own, and
    /// an empty entry in a dropdown is unclickable in practice.
    pub fn label(&self) -> String {
        if self.name.is_empty() {
            "(the file)".to_string()
        } else {
            self.name.clone()
        }
    }
}

/// The reader established how the first row of the sheet reads.
pub const HEADER_ESTABLISHED: &str = "established";
/// The first row of the sheet can be a header or data. Both readings are candidates.
pub const HEADER_AMBIGUOUS: &str = "ambiguous";
/// A sheet stored before the reader recorded its reading. It is the column default.
pub const HEADER_LEGACY: &str = "legacy";

/// The reading follows the convention of the file format, as for a workbook sheet.
pub const HEADER_BASIS_FORMAT: &str = "format";
/// The reading follows the cell kinds of the rows, as for a delimited file.
pub const HEADER_BASIS_HEURISTIC: &str = "heuristic";
/// No reader recorded a basis. It is the column default.
pub const HEADER_BASIS_MISSING: &str = "missing";

/// The reading with no header row: row 1 is data.
pub const VIEW_ALL_ROWS: &str = "all_rows";
/// The reading with row 1 as the column names.
pub const VIEW_FIRST_ROW_HEADER: &str = "first_row_header";
/// The request value that selects the reading for the caller.
pub const VIEW_AUTO: &str = "auto";

/// The reader of a delimited file, as `table_documents.reader` stores it.
pub const READER_DELIMITED: &str = "csv";

/// The name of the reading whose header is `header_row`.
pub fn table_view_name(header_row: u64) -> String {
    match header_row {
        0 => VIEW_ALL_ROWS.to_string(),
        1 => VIEW_FIRST_ROW_HEADER.to_string(),
        n => format!("header_row_{n}"),
    }
}

/// How one read of a sheet takes its first row: the reading that its counts describe,
/// with every plausible reading beside it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct SheetInterpretation {
    pub state: String,
    pub basis: String,
    /// The header `row_id` of each plausible reading, ascending.
    pub candidates: Vec<u64>,
    /// The header `row_id` of the selected reading. Rows after it are the data rows.
    pub selected: u64,
    /// True when the caller named the reading, false when `auto` or the display chose it.
    pub requested: bool,
    /// The stored rows of the sheet, which bound every read. The header row is one of them.
    pub stored_rows: u64,
}

impl SheetInterpretation {
    /// The data rows of the reading whose header is `header_row`.
    pub fn rows_of(&self, header_row: u64) -> u64 {
        self.stored_rows.saturating_sub(header_row)
    }

    /// The data rows of the selected reading.
    pub fn selected_rows(&self) -> u64 {
        self.rows_of(self.selected)
    }

    /// True when the reader established the reading of the first row.
    pub fn is_established(&self) -> bool {
        self.state == HEADER_ESTABLISHED
    }
}

/// The plausible readings of a sheet, as `(state, basis, candidates)`.
///
/// A stored reading keeps its state and its candidates. A legacy sheet of a delimited file
/// has the reading with no header and the reading with row 1 as header, because the
/// legacy reader decided between them from cell kinds alone. A legacy sheet of another
/// reader keeps its display choice as its one reading.
pub fn sheet_candidates(sheet: &TableSheet, reader: &str) -> (String, String, Vec<u64>) {
    let stored_rows = sheet.last_row_id();
    let legacy = sheet.header_state.is_empty() || sheet.header_state == HEADER_LEGACY;
    let mut candidates: Vec<u64> = if legacy {
        if reader == READER_DELIMITED && stored_rows >= 2 {
            vec![0, 1]
        } else {
            vec![sheet.header_row]
        }
    } else {
        sheet.header_candidates.clone()
    };
    candidates.retain(|row| *row <= stored_rows);
    candidates.sort_unstable();
    candidates.dedup();
    if candidates.is_empty() {
        candidates.push(sheet.header_row.min(stored_rows));
    }
    let (state, basis) = if legacy {
        (HEADER_LEGACY.to_string(), HEADER_BASIS_MISSING.to_string())
    } else {
        let basis = if sheet.header_basis.is_empty() { HEADER_BASIS_MISSING.to_string() } else { sheet.header_basis.clone() };
        (sheet.header_state.clone(), basis)
    };
    (state, basis, candidates)
}

/// Selects the reading of one sheet read. `None` and [`VIEW_AUTO`] select the one reading
/// of a sheet with one candidate, and the reading with no header otherwise, so the first
/// row stays visible. [`VIEW_ALL_ROWS`] and [`VIEW_FIRST_ROW_HEADER`] select their reading
/// when the sheet has it. `Err` holds the message of a request for another reading.
pub fn resolve_sheet_interpretation(
    sheet: &TableSheet,
    reader: &str,
    requested: Option<&str>,
) -> Result<SheetInterpretation, String> {
    let (state, basis, candidates) = sheet_candidates(sheet, reader);
    let stored_rows = sheet.last_row_id();
    let wanted = match requested {
        None => None,
        Some(name) if name == VIEW_AUTO => None,
        Some(name) if name == VIEW_ALL_ROWS => Some(0),
        Some(name) if name == VIEW_FIRST_ROW_HEADER => Some(1),
        Some(other) => {
            return Err(format!(
                "interpretation {other:?} is not a reading: use {VIEW_AUTO}, {VIEW_ALL_ROWS} or {VIEW_FIRST_ROW_HEADER}"
            ));
        }
    };
    let selected = match wanted {
        Some(row) if candidates.contains(&row) => row,
        Some(row) => {
            let names: Vec<String> = candidates.iter().map(|row| table_view_name(*row)).collect();
            return Err(format!(
                "sheet {} has no {} reading. Its readings are {}.",
                sheet.sheet_id,
                table_view_name(row),
                names.join(", ")
            ));
        }
        None if candidates.len() == 1 => candidates[0],
        None if candidates.contains(&0) => 0,
        None => candidates[0],
    };
    Ok(SheetInterpretation { state, basis, candidates, selected, requested: wanted.is_some(), stored_rows })
}

/// The reading of the website grid: the stored display choice, with the stored candidates.
pub fn display_sheet_interpretation(sheet: &TableSheet, reader: &str) -> SheetInterpretation {
    let (state, basis, mut candidates) = sheet_candidates(sheet, reader);
    if !candidates.contains(&sheet.header_row) {
        candidates.push(sheet.header_row);
        candidates.sort_unstable();
    }
    SheetInterpretation {
        state,
        basis,
        candidates,
        selected: sheet.header_row,
        requested: false,
        stored_rows: sheet.last_row_id(),
    }
}

/// The type a column sorts and filters as, from the count of each cell kind: its most
/// common kind, and `text` on a tie or with no cell. The pipeline's
/// `parse_table._column_type` uses the same rule.
pub fn column_type_of(kinds: &[(String, u64)]) -> String {
    let mut ordered: Vec<&(String, u64)> = kinds.iter().filter(|(_, count)| *count > 0).collect();
    ordered.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
    match ordered.as_slice() {
        [] => "text".to_string(),
        [first, second, ..] if first.1 == second.1 => "text".to_string(),
        [first, ..] => first.0.clone(),
    }
}

/// One column of one sheet, as `table_columns` records it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct TableColumnInfo {
    pub sheet_id: u16,
    /// 1-based column ordinal as the file gives it.
    pub column_id: u32,
    /// Spreadsheet column label: `A`, `B`, `AA`.
    pub letter: String,
    /// Header text, empty when the sheet has no header row.
    pub header: String,
    /// The type this column sorts and filters as; one of [`TABLE_CELL_KINDS`].
    pub column_type: String,
    pub non_empty: u64,
    pub distinct_count: u64,
    pub min_value: String,
    pub max_value: String,
    pub samples: Vec<String>,
}

impl TableColumnInfo {
    /// What the header cell reads. A column with no header falls back to its letter
    /// rather than to nothing. An unlabelled header is a column nobody can name in a
    /// conversation about the file.
    pub fn label(&self) -> String {
        if self.header.trim().is_empty() {
            format!("Column {}", self.letter)
        } else {
            self.header.clone()
        }
    }

    pub fn class(&self) -> TableColumnClass {
        TableColumnClass::of(&self.column_type)
    }
}

/// The vocabulary `cell_kind` and `column_type` share.
pub const TABLE_CELL_KINDS: [&str; 9] = [
    "text", "int", "float", "bool", "date", "datetime", "time", "duration", "error",
];

/// How a column sorts, filters and aligns. Three classes, not nine kinds: the controls a
/// filter popover offers depend only on which typed ClickHouse column carries the value.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum TableColumnClass {
    /// `int` / `float`, sorts and ranges on `cell_float`.
    Number,
    /// `date` / `datetime` / `time`, sorts and ranges on `cell_time`.
    Temporal,
    /// Everything else, sorts and matches on `cell_text`.
    Text,
}

impl TableColumnClass {
    pub fn of(column_type: &str) -> Self {
        match column_type {
            "int" | "float" => TableColumnClass::Number,
            "date" | "datetime" | "time" => TableColumnClass::Temporal,
            _ => TableColumnClass::Text,
        }
    }
}

/// One cap that fired while the document was read.
///
/// Stored as three parallel arrays on `table_documents` and zipped into this on the way
/// out. The banner names the maximum as well as the limit, because a reader needs to know that the
/// reader learns the ceiling, not merely that one exists.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct TableTruncation {
    /// `cells_per_document` | `rows_per_sheet` | `columns_per_sheet` | `sheets` |
    /// `cell_bytes`.
    pub limit: String,
    pub maximum: u64,
    /// The sheet the cap fired on. Empty for a document-wide cap **and** for a delimited
    /// file's single unnamed sheet, so the two are told apart by the limit name and never
    /// by this string.
    pub sheet: String,
}

impl TableTruncation {
    /// Whether this cap applies to the document as a whole rather than to one sheet.
    pub fn is_document_wide(&self) -> bool {
        matches!(self.limit.as_str(), "cells_per_document" | "sheets")
    }

    /// One sentence naming the limit, its maximum and, when it is a per-sheet cap that
    /// fired on a named sheet, which sheet.
    pub fn sentence(&self) -> String {
        let what = match self.limit.as_str() {
            "cells_per_document" => format!("only the first {} cells of this document were stored", self.maximum),
            "rows_per_sheet" => format!("only the first {} rows of a sheet were stored", self.maximum),
            "columns_per_sheet" => format!("only the first {} columns of a sheet were stored", self.maximum),
            "sheets" => format!("only the first {} sheets were read", self.maximum),
            "cell_bytes" => format!("cells longer than {} bytes were cut", self.maximum),
            other => format!("the {other} limit of {} was reached", self.maximum),
        };
        if self.is_document_wide() || self.sheet.is_empty() {
            what
        } else {
            format!("{what} (sheet \u{201c}{}\u{201d})", self.sheet)
        }
    }
}

/// Everything the explorer needs before it asks for a single cell.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct TableOverview {
    /// `csv` | `xlsx_stream` | `ods_stream` | `calamine`.
    pub reader: String,
    /// `csv` | `tsv` | `xlsx` | `xls` | `ods` | …
    pub table_format: String,
    pub sheet_count: u16,
    /// Data rows summed across every sheet, header rows excluded. The per-sheet counts
    /// in [`Self::sheets`] are the ones that bound a read.
    pub row_count: u64,
    /// Widest column ordinal across every sheet.
    pub column_count: u32,
    pub cell_count: u64,
    pub stored_bytes: u64,
    pub sheets: Vec<TableSheet>,
    pub columns: Vec<TableColumnInfo>,
    /// Empty when nothing was capped.
    pub truncations: Vec<TableTruncation>,
    /// The reader's own English sentence, kept as a fallback for a limit name this build
    /// does not know.
    pub truncated_reason: String,
}

impl TableOverview {
    pub fn sheet(&self, sheet_id: u16) -> Option<&TableSheet> {
        self.sheets.iter().find(|s| s.sheet_id == sheet_id)
    }

    /// The sheet the explorer opens on: the first one the manifest lists. Sheet ordinals
    /// are not contiguous, so "sheet 0" is not a safe default.
    pub fn first_sheet_id(&self) -> u16 {
        self.sheets.first().map(|s| s.sheet_id).unwrap_or(0)
    }

    /// Columns of one sheet, in ordinal order.
    pub fn columns_of(&self, sheet_id: u16) -> Vec<&TableColumnInfo> {
        let mut cols: Vec<&TableColumnInfo> =
            self.columns.iter().filter(|c| c.sheet_id == sheet_id).collect();
        cols.sort_by_key(|c| c.column_id);
        cols
    }

    /// The banner text, or `None` when nothing was capped.
    pub fn truncation_banner(&self) -> Option<String> {
        if self.truncations.is_empty() {
            if self.truncated_reason.is_empty() {
                return None;
            }
            return Some(self.truncated_reason.clone());
        }
        let sentences: Vec<String> = self.truncations.iter().map(|t| t.sentence()).collect();
        Some(format!(
            "This document is larger than the browser stores: {}.",
            sentences.join("; ")
        ))
    }
}

/// What one column filter asks for. The variant follows the column's class, which is why
/// the popover offers different controls per column.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum TableFilterKind {
    Contains(String),
    Equals(String),
    StartsWith(String),
    /// Open ends allowed on either side.
    NumberRange { min: Option<f64>, max: Option<f64> },
    /// ISO-8601 instants, open ends allowed on either side.
    DateRange { min: Option<String>, max: Option<String> },
    /// Rows with no cell at all in this column.
    IsEmpty,
}

impl TableFilterKind {
    /// A filter that constrains nothing is dropped rather than sent: an empty `contains`
    /// would otherwise cost a full column scan to match every row.
    pub fn is_noop(&self) -> bool {
        match self {
            TableFilterKind::Contains(s)
            | TableFilterKind::Equals(s)
            | TableFilterKind::StartsWith(s) => s.is_empty(),
            TableFilterKind::NumberRange { min, max } => min.is_none() && max.is_none(),
            TableFilterKind::DateRange { min, max } => min.is_none() && max.is_none(),
            TableFilterKind::IsEmpty => false,
        }
    }

    /// The chip text in the controls bar.
    pub fn summary(&self) -> String {
        match self {
            TableFilterKind::Contains(s) => format!("contains \u{201c}{s}\u{201d}"),
            TableFilterKind::Equals(s) => format!("is \u{201c}{s}\u{201d}"),
            TableFilterKind::StartsWith(s) => format!("starts with \u{201c}{s}\u{201d}"),
            TableFilterKind::NumberRange { min, max } => match (min, max) {
                (Some(a), Some(b)) => format!("{a} \u{2013} {b}"),
                (Some(a), None) => format!("\u{2265} {a}"),
                (None, Some(b)) => format!("\u{2264} {b}"),
                (None, None) => "any number".to_string(),
            },
            TableFilterKind::DateRange { min, max } => match (min, max) {
                (Some(a), Some(b)) => format!("{a} \u{2013} {b}"),
                (Some(a), None) => format!("from {a}"),
                (None, Some(b)) => format!("until {b}"),
                (None, None) => "any date".to_string(),
            },
            TableFilterKind::IsEmpty => "is empty".to_string(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TableColumnFilter {
    pub column_id: u32,
    pub kind: TableFilterKind,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct TableSort {
    pub column_id: u32,
    pub desc: bool,
}

/// One request for a window of a sheet.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct TableViewQuery {
    pub sheet_id: u16,
    /// Empty means "the first [`MAX_TABLE_VISIBLE_COLUMNS`] by ordinal".
    pub visible_columns: Vec<u32>,
    pub sort: Option<TableSort>,
    pub filters: Vec<TableColumnFilter>,
    /// Substring matched across every column of the sheet. Bound as a query parameter,
    /// never interpolated.
    pub search: String,
    pub offset: u64,
    pub limit: u32,
}

/// What the server actually did with a request that asked for more than it may have.
///
/// Carried in every [`TablePage`] so the grid can say so. `requested == applied` on the
/// ordinary path and [`Self::message`] is then `None`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct TableClamps {
    pub rows_requested: u32,
    pub rows_applied: u32,
    pub columns_requested: u32,
    pub columns_applied: u32,
}

impl TableClamps {
    pub fn any(&self) -> bool {
        self.rows_requested > self.rows_applied || self.columns_requested > self.columns_applied
    }

    pub fn message(&self) -> Option<String> {
        if !self.any() {
            return None;
        }
        let mut parts = Vec::new();
        if self.rows_requested > self.rows_applied {
            parts.push(format!(
                "{} rows were asked for; this endpoint returns at most {}",
                self.rows_requested, MAX_TABLE_PAGE_ROWS
            ));
        }
        if self.columns_requested > self.columns_applied {
            parts.push(format!(
                "{} columns were asked for; this endpoint draws at most {}",
                self.columns_requested, MAX_TABLE_VISIBLE_COLUMNS
            ));
        }
        Some(parts.join(". "))
    }
}

/// Clamp a requested row limit. `0` means "the default page", not "no rows".
pub fn clamp_table_page_rows(requested: u32) -> u32 {
    if requested == 0 {
        DEFAULT_TABLE_PAGE_ROWS
    } else {
        requested.min(MAX_TABLE_PAGE_ROWS)
    }
}

/// Clamp a requested visible-column list, preserving the caller's order.
pub fn clamp_table_visible_columns(requested: &[u32]) -> Vec<u32> {
    requested.iter().copied().take(MAX_TABLE_VISIBLE_COLUMNS).collect()
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct TableCell {
    pub column_id: u32,
    /// The cell exactly as the reader stored it. Authoritative for display, always,
    /// never reconstructed from the typed columns.
    pub text: String,
    /// One of [`TABLE_CELL_KINDS`].
    pub kind: String,
    /// Hyperlink target, empty when the cell has none. Only ODS fills this today: OOXML
    /// puts hyperlinks in a block after the cells, which a streaming reader has already
    /// passed, so an absent link is the normal case and never an affordance.
    pub link: String,
    /// Formula without its leading `=`, empty when the cell has none.
    pub formula: String,
    /// The exact integer, when the cell holds one. The value to copy above 2^53, where
    /// the float is approximate.
    pub int_value: Option<i64>,
    /// The inline excerpt the grid draws. Only the website's page route fills it. The
    /// shared page reader and the agent routes leave it empty and read [`Self::text`].
    #[serde(default)]
    pub preview: Option<crate::table_cell_preview::TableCellPreview>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct TableRow {
    /// Dense ordinal within the sheet; the address the next page is asked for by.
    pub row_id: u64,
    /// The row number the file itself gives. What the `#` column draws.
    pub source_row: u64,
    /// Only the non-empty cells, in visible-column order. A visible column with no entry
    /// here is empty in this row.
    pub cells: Vec<TableCell>,
}

impl TableRow {
    pub fn cell(&self, column_id: u32) -> Option<&TableCell> {
        self.cells.iter().find(|c| c.column_id == column_id)
    }
}

/// One window of one sheet.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct TablePage {
    pub rows: Vec<TableRow>,
    /// Rows matching the filters and the search, before paging. The pager's denominator.
    pub total_rows: u64,
    /// The columns these cells are in, in draw order.
    pub columns: Vec<u32>,
    /// Where this window starts, after clamping.
    pub offset: u64,
    /// How many rows this window holds room for, after clamping.
    pub limit: u32,
    pub clamps: TableClamps,
    /// The terms that selected the rows and that the cell excerpts mark. They are the words
    /// that the search engine matched in this document, split at cell and row breaks, and
    /// the find text without its double quotes. Empty without a find text.
    #[serde(default)]
    pub find_terms: Vec<String>,
}

/// One entry of a filter popover's value list.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct TableColumnValue {
    pub value: String,
    pub count: u64,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sheet(row_count: u64, header_row: u64) -> TableSheet {
        TableSheet { row_count, header_row, column_count: 3, ..Default::default() }
    }

    #[test]
    fn the_last_stored_row_includes_the_header_and_the_rows_above_it() {
        // A header and 38 data rows: stored rows 1 to 39.
        assert_eq!(sheet(38, 1).last_row_id(), 39);
        // No header: the data rows are the stored rows.
        assert_eq!(sheet(38, 0).last_row_id(), 38);
        // Two title rows, then the header in row 3, then 10 data rows: stored rows 1 to 13.
        assert_eq!(sheet(10, 3).last_row_id(), 13);
        // A header without data rows, and an empty sheet.
        assert_eq!(sheet(0, 1).last_row_id(), 1);
        assert_eq!(sheet(0, 0).last_row_id(), 0);
    }

    fn stored(state: &str, candidates: &[u64], header_row: u64, stored_rows: u64) -> TableSheet {
        TableSheet {
            sheet_id: 0,
            row_count: stored_rows - header_row,
            header_row,
            header_state: state.into(),
            header_basis: if state.is_empty() { String::new() } else { HEADER_BASIS_HEURISTIC.into() },
            header_candidates: candidates.to_vec(),
            ..Default::default()
        }
    }

    #[test]
    fn an_ambiguous_sheet_reads_every_row_unless_a_reading_is_named() {
        let sheet = stored(HEADER_AMBIGUOUS, &[0, 1], 1, 19);
        let auto = resolve_sheet_interpretation(&sheet, READER_DELIMITED, None).unwrap();
        assert_eq!((auto.selected, auto.selected_rows(), auto.requested), (0, 19, false));
        assert_eq!(auto.candidates, vec![0, 1]);
        assert_eq!((auto.rows_of(0), auto.rows_of(1)), (19, 18));
        assert!(!auto.is_established());
        assert_eq!(resolve_sheet_interpretation(&sheet, READER_DELIMITED, Some(VIEW_AUTO)).unwrap(), auto);
        let header = resolve_sheet_interpretation(&sheet, READER_DELIMITED, Some(VIEW_FIRST_ROW_HEADER)).unwrap();
        assert_eq!((header.selected, header.selected_rows(), header.requested), (1, 18, true));
        let rows = resolve_sheet_interpretation(&sheet, READER_DELIMITED, Some(VIEW_ALL_ROWS)).unwrap();
        assert_eq!((rows.selected, rows.requested), (0, true));
    }

    #[test]
    fn an_established_sheet_has_one_reading_and_refuses_the_other() {
        let sheet = stored(HEADER_ESTABLISHED, &[1], 1, 39);
        let auto = resolve_sheet_interpretation(&sheet, READER_DELIMITED, None).unwrap();
        assert_eq!((auto.selected, auto.selected_rows()), (1, 38));
        assert!(auto.is_established());
        let refused = resolve_sheet_interpretation(&sheet, READER_DELIMITED, Some(VIEW_ALL_ROWS)).unwrap_err();
        assert_eq!(refused, "sheet 0 has no all_rows reading. Its readings are first_row_header.");
        let unknown = resolve_sheet_interpretation(&sheet, READER_DELIMITED, Some("header")).unwrap_err();
        assert!(unknown.contains("auto, all_rows or first_row_header"), "{unknown}");
    }

    #[test]
    fn a_legacy_delimited_sheet_has_both_readings_and_keeps_its_display_choice() {
        // Reader version 1 took the first row as the header.
        let header = stored("", &[], 1, 19);
        let auto = resolve_sheet_interpretation(&header, READER_DELIMITED, None).unwrap();
        assert_eq!((auto.state.as_str(), auto.basis.as_str()), (HEADER_LEGACY, HEADER_BASIS_MISSING));
        assert_eq!((auto.candidates.clone(), auto.selected), (vec![0, 1], 0));
        assert_eq!(display_sheet_interpretation(&header, READER_DELIMITED).selected, 1);
        // Reader version 2 read the first row as data. Row 1 can still be named the header.
        let data = stored(HEADER_LEGACY, &[], 0, 19);
        let named = resolve_sheet_interpretation(&data, READER_DELIMITED, Some(VIEW_FIRST_ROW_HEADER)).unwrap();
        assert_eq!((named.selected, named.selected_rows()), (1, 18));
        assert_eq!(display_sheet_interpretation(&data, READER_DELIMITED).selected, 0);
    }

    #[test]
    fn a_legacy_workbook_sheet_keeps_its_one_reading() {
        let sheet = stored("", &[], 1, 5);
        let auto = resolve_sheet_interpretation(&sheet, "xlsx_stream", None).unwrap();
        assert_eq!((auto.candidates.clone(), auto.selected, auto.selected_rows()), (vec![1], 1, 4));
        assert!(resolve_sheet_interpretation(&sheet, "xlsx_stream", Some(VIEW_ALL_ROWS)).is_err());
    }

    #[test]
    fn a_candidate_past_the_stored_rows_is_not_a_reading() {
        let sheet = stored(HEADER_AMBIGUOUS, &[0, 1, 7], 1, 3);
        assert_eq!(resolve_sheet_interpretation(&sheet, READER_DELIMITED, None).unwrap().candidates, vec![0, 1]);
    }

    #[test]
    fn the_column_type_is_the_most_common_kind_and_text_on_a_tie() {
        let kinds = |pairs: &[(&str, u64)]| pairs.iter().map(|(k, n)| (k.to_string(), *n)).collect::<Vec<_>>();
        assert_eq!(column_type_of(&kinds(&[("int", 18), ("text", 1)])), "int");
        assert_eq!(column_type_of(&kinds(&[("int", 1), ("text", 1)])), "text");
        assert_eq!(column_type_of(&kinds(&[("int", 0), ("float", 2)])), "float");
        assert_eq!(column_type_of(&[]), "text");
        assert_eq!(table_view_name(0), VIEW_ALL_ROWS);
        assert_eq!(table_view_name(1), VIEW_FIRST_ROW_HEADER);
    }

    #[test]
    fn a_zero_limit_is_the_default_page_not_an_empty_one() {
        assert_eq!(clamp_table_page_rows(0), DEFAULT_TABLE_PAGE_ROWS);
        assert_eq!(clamp_table_page_rows(10), 10);
        assert_eq!(clamp_table_page_rows(MAX_TABLE_PAGE_ROWS), MAX_TABLE_PAGE_ROWS);
        assert_eq!(clamp_table_page_rows(u32::MAX), MAX_TABLE_PAGE_ROWS);
    }

    #[test]
    fn the_column_clamp_keeps_the_callers_order() {
        let asked: Vec<u32> = (1..=100).rev().collect();
        let got = clamp_table_visible_columns(&asked);
        assert_eq!(got.len(), MAX_TABLE_VISIBLE_COLUMNS);
        assert_eq!(got[0], 100);
        assert_eq!(got[MAX_TABLE_VISIBLE_COLUMNS - 1], 100 - (MAX_TABLE_VISIBLE_COLUMNS as u32 - 1));
    }

    #[test]
    fn a_clamp_that_did_not_fire_says_nothing() {
        let quiet = TableClamps {
            rows_requested: 50,
            rows_applied: 50,
            columns_requested: 9,
            columns_applied: 9,
        };
        assert!(!quiet.any());
        assert!(quiet.message().is_none());

        let loud = TableClamps {
            rows_requested: 5000,
            rows_applied: MAX_TABLE_PAGE_ROWS,
            columns_requested: 300,
            columns_applied: MAX_TABLE_VISIBLE_COLUMNS as u32,
        };
        let message = loud.message().expect("a clamp that fired must be reported");
        assert!(message.contains("5000"), "{message}");
        assert!(message.contains(&MAX_TABLE_PAGE_ROWS.to_string()), "{message}");
        assert!(message.contains("300"), "{message}");
    }

    /// The three parallel arrays record a document-wide cap and a per-sheet cap with the
    /// same empty sheet string, so only the limit NAME separates them.
    #[test]
    fn a_document_wide_cap_is_told_from_a_sheet_cap_by_its_name() {
        let doc_wide = TableTruncation {
            limit: "cells_per_document".into(),
            maximum: 300_000_000,
            sheet: String::new(),
        };
        let unnamed_sheet = TableTruncation {
            limit: "columns_per_sheet".into(),
            maximum: 300,
            sheet: String::new(),
        };
        assert!(doc_wide.is_document_wide());
        assert!(!unnamed_sheet.is_document_wide());
        // Both name their maximum: the ceiling is the point of the banner.
        assert!(doc_wide.sentence().contains("300000000"));
        assert!(unnamed_sheet.sentence().contains("300"));
    }

    #[test]
    fn the_banner_names_every_cap_that_fired() {
        let overview = TableOverview {
            truncations: vec![
                TableTruncation { limit: "columns_per_sheet".into(), maximum: 300, sheet: "Orders".into() },
                TableTruncation { limit: "sheets".into(), maximum: 100, sheet: String::new() },
            ],
            ..Default::default()
        };
        let banner = overview.truncation_banner().expect("caps fired");
        assert!(banner.contains("300"), "{banner}");
        assert!(banner.contains("100"), "{banner}");
        assert!(banner.contains("Orders"), "{banner}");

        assert!(TableOverview::default().truncation_banner().is_none());
    }

    /// The reader's own sentence is the fallback when this build does not know a limit
    /// name, which is what a newer pipeline against an older website looks like.
    #[test]
    fn an_unknown_limit_still_names_its_maximum() {
        let unknown = TableTruncation { limit: "future_cap".into(), maximum: 7, sheet: String::new() };
        assert!(unknown.sentence().contains("future_cap"));
        assert!(unknown.sentence().contains('7'));
    }

    #[test]
    fn sheet_ordinals_are_not_indices() {
        // `Excel-sample-data-for-pivot-tables.xlsx` really does have sheets 0 and 2.
        let overview = TableOverview {
            sheets: vec![
                TableSheet { sheet_id: 0, name: "Source Data".into(), ..Default::default() },
                TableSheet { sheet_id: 2, name: "Sample PivotTable Report".into(), ..Default::default() },
            ],
            ..Default::default()
        };
        assert_eq!(overview.first_sheet_id(), 0);
        assert!(overview.sheet(1).is_none());
        assert_eq!(overview.sheet(2).map(|s| s.name.as_str()), Some("Sample PivotTable Report"));
    }

    #[test]
    fn a_delimited_files_unnamed_sheet_is_still_clickable() {
        assert_eq!(TableSheet::default().label(), "(the file)");
    }

    #[test]
    fn column_classes_follow_the_stored_kind() {
        assert_eq!(TableColumnClass::of("int"), TableColumnClass::Number);
        assert_eq!(TableColumnClass::of("float"), TableColumnClass::Number);
        assert_eq!(TableColumnClass::of("date"), TableColumnClass::Temporal);
        assert_eq!(TableColumnClass::of("datetime"), TableColumnClass::Temporal);
        assert_eq!(TableColumnClass::of("time"), TableColumnClass::Temporal);
        for text in ["text", "bool", "duration", "error", "something-new"] {
            assert_eq!(TableColumnClass::of(text), TableColumnClass::Text, "{text}");
        }
    }

    #[test]
    fn an_empty_filter_constrains_nothing_and_is_dropped() {
        assert!(TableFilterKind::Contains(String::new()).is_noop());
        assert!(TableFilterKind::NumberRange { min: None, max: None }.is_noop());
        assert!(!TableFilterKind::NumberRange { min: Some(1.0), max: None }.is_noop());
        assert!(!TableFilterKind::IsEmpty.is_noop());
    }

    #[test]
    fn an_unlabelled_column_falls_back_to_its_letter() {
        let column = TableColumnInfo { letter: "AB".into(), ..Default::default() };
        assert_eq!(column.label(), "Column AB");
    }
}

#[cfg(test)]
mod find_tests {
    use super::table_find_text;

    #[test]
    fn phrase_quotes_do_not_become_cell_content() {
        assert_eq!(table_find_text("\"Jenalynn Weed\""), "Jenalynn Weed");
        assert_eq!(table_find_text(" “María García” "), "María García");
        assert_eq!(table_find_text("D'Angelo"), "D'Angelo");
        assert_eq!(table_find_text("\"\""), "");
    }
}
