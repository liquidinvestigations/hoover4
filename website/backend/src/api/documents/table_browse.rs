//! Browsing one tabular document's cells.
//!
//! # The authorisation rule, first, because everything else depends on it
//!
//! `table_cells` is keyed by **content hash alone**. It has no `collection_dataset`
//! column, because the same spreadsheet ingested into five datasets is one set of cells.
//! That makes a cell read by hash a read across every dataset in the collection. The
//! per-dataset manifest `table_documents` is therefore the *entire* authorisation, and
//! every function here does the same three things in the same order:
//!
//! 1. [`permissions::assert_can_read`] for the dataset,
//! 2. a `(collection_dataset, hash)` lookup in `table_documents` with `status = 'ok'`,
//! 3. and only then a query against `table_cells`.
//!
//! A hash with no manifest row for that dataset (or one whose row is still `parsing` or
//! is `failed`) is a 404 that never reaches step 3. There is no shortcut past this and
//! there must not be one: skipping the lookup lets a reader who may see dataset A read
//! the cells of a document that only exists in dataset B by pasting its hash.
//!
//! # Parameters are bound, not interpolated
//!
//! This is ClickHouse. `db_utils::manticore_match`'s escaping rules exist because
//! Manticore's SQL-ish surface takes a match expression as a *string literal* and there
//! is nothing to bind; none of that applies here and copying it would be wrong. Every
//! value a reader supplies (the search text, a filter's text, a range bound) is bound
//! through `Query::bind`. The only things spliced into the SQL text are integers this
//! module has already validated against the manifest's own extents, and the fixed
//! predicate and comparator fragments below.
//!
//! # The find text is resolved through the search engine
//!
//! The result list and the text viewers match with Manticore. Manticore splits text into
//! words at punctuation and whitespace. A literal substring test of the find text in one
//! cell can disagree with it. A search for Prudential Lighting Corp with a final dot
//! matches the document, and no cell holds the dot. [`table_find_terms`] asks
//! Manticore which words it marked in this document. It splits each marked run at cell and
//! row breaks and adds the find text without its double quotes. A cell matches when it
//! holds any of these terms. The grid, the sheet counts and the `Table` hit count use the
//! same terms.
//!
//! # Why the sort is two phases
//!
//! Phase 1 orders one contiguous primary-key range (the whole sort column of one sheet,
//! which `ORDER BY (file_hash, sheet_id, column_id, row_id)` makes a single scan), and
//! returns `row_id`s. Phase 2 fetches the window's cells by `row_id IN (…)`. The
//! comparator is not re-derived in phase 2: the window is re-ordered in Rust into phase
//! 1's order, so the two cannot disagree.
//!
//! Rows with **no cell in the sort column** are not in phase 1's range at all. They are
//! appended after the sorted rows, in `row_id` order, in both directions, which is the same
//! thing a spreadsheet's own sort does with blanks.
//!
//! # The header row is not a data row
//!
//! The reader stores the header row as ordinary cells (it is row `table_sheets.header_row`
//! of `table_cells`), and *also* writes its text into `table_columns.header`, and excludes
//! it from every column statistic. So the grid draws that row's text as its column labels,
//! and drawing it a second time as row 1 of the data shows it twice while making every
//! count disagree with the statistics the filter popovers and type marks come from.
//!
//! Everything reader-facing here therefore starts **after** the header row of the reading:
//! the row floor [`data_row_floor`] is spliced into every cell query, the totals subtract
//! it, and the unfiltered window's arithmetic is offset by it. A header row of `0` means
//! the reading has no header row and nothing is skipped. It is a `row_id` (dense within the
//! sheet) not a `source_row`, so it must never be compared against the file's own row
//! numbers.
//!
//! # One resolver chooses the reading of row 1
//!
//! `table_sheets.header_row` is the display choice of the website grid.
//! `header_state`, `header_basis` and `header_candidates` record every plausible reading.
//! [`resolve_read`] turns a [`TableRead`] into a
//! [`SheetInterpretation`] with the shared rules of `common::document_tables`, and every
//! read below takes its header row from that value. The website grid reads the display
//! choice. An agent route reads the reading that its request names, or the `auto`
//! reading. No query derives a header row of its own.

use common::current_user::CurrentUser;
use common::document_tables::{
    MAX_TABLE_COLUMN_VALUES, SheetInterpretation, TableCell, TableClamps, TableColumnClass,
    TableColumnFilter, TableColumnInfo, TableColumnValue, TableFilterKind, TableOverview,
    TablePage, TableRow, TableSheet, TableTruncation, TableViewQuery, clamp_table_page_rows,
    clamp_table_visible_columns, column_type_of, display_sheet_interpretation,
    resolve_sheet_interpretation, table_find_text,
};
use common::search_result::DocumentIdentifier;
use common::table_cell_preview::cell_preview;

use crate::api::documents::search_document_text::search_document_text_all_hits;
use crate::auth::guard::{InvalidInput, NOT_FOUND};
use crate::auth::permissions;
use crate::db_utils::clickhouse_utils::get_client_for_dataset;

/// Seconds a cell query may run before ClickHouse kills it.
///
/// A sort or a full-column filter reads one whole column, which is a column store's best
/// case and sub-second for anything in a normal corpus. A pathological document must fail
/// visibly rather than hold a connection open, for the same reason the search fan-out
/// carries a deadline.
pub(crate) const TABLE_QUERY_TIMEOUT_SECONDS: &str = "30";

/// Row shapes for the four reads below.
///
/// `clickhouse::Row` matches by COLUMN NAME, so every field here is named exactly as the
/// column it reads. Tuples would be shorter but the crate only implements `Row` for
/// tuples of primitives, and three of these rows carry an `Array` or a `Nullable`.
#[derive(Debug, clickhouse::Row, serde::Deserialize)]
struct ManifestRow {
    reader: String,
    table_format: String,
    sheet_count: u16,
    row_count: u64,
    column_count: u32,
    cell_count: u64,
    stored_bytes: u64,
    truncated_limits: Vec<String>,
    truncated_maximums: Vec<u64>,
    truncated_sheets: Vec<String>,
    truncated_reason: String,
    reader_version: u16,
    updated_at: u32,
}

#[derive(Debug, clickhouse::Row, serde::Deserialize)]
struct SheetRow {
    sheet_id: u16,
    name: String,
    row_count: u64,
    column_count: u32,
    header_row: u64,
    truncated: u8,
    header_state: String,
    header_basis: String,
    header_candidates: Vec<u64>,
}

impl SheetRow {
    /// The sheet as the website grid shows it: its data rows are the stored rows after the
    /// display choice of header row.
    fn into_sheet(self) -> TableSheet {
        TableSheet {
            sheet_id: self.sheet_id,
            name: self.name,
            row_count: self.row_count.saturating_sub(self.header_row),
            column_count: self.column_count,
            header_row: self.header_row,
            truncated: self.truncated == 1,
            header_state: self.header_state,
            header_basis: self.header_basis,
            header_candidates: self.header_candidates,
        }
    }
}

/// The columns of `table_sheets` that [`SheetRow`] reads, in its field order.
const SHEET_COLUMNS: &str = "sheet_id, name, row_count, column_count, header_row, truncated, \
                             header_state, header_basis, header_candidates";

/// Which reading of row 1 a table read takes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TableRead<'a> {
    /// The display choice of the website grid, `table_sheets.header_row`.
    Display,
    /// The reading that an agent request names: `auto` when `None`.
    Agent(Option<&'a str>),
}

/// The reading of one read of `sheet`. A request for a reading that the sheet does not
/// have is an [`InvalidInput`], which the agent routes answer with 400.
pub fn resolve_read(sheet: &TableSheet, reader: &str, read: TableRead<'_>) -> anyhow::Result<SheetInterpretation> {
    match read {
        TableRead::Display => Ok(display_sheet_interpretation(sheet, reader)),
        TableRead::Agent(requested) => resolve_sheet_interpretation(sheet, reader, requested)
            .map_err(|message| anyhow::Error::new(InvalidInput(message))),
    }
}

/// The sheets of one document for one dataset, in sheet order. The caller holds the
/// manifest of the document.
async fn sheets_of(client: &clickhouse::Client, document_identifier: &DocumentIdentifier) -> anyhow::Result<Vec<TableSheet>> {
    let rows: Vec<SheetRow> = client
        .query(&format!(
            "SELECT {SHEET_COLUMNS} FROM table_sheets FINAL \
             WHERE collection_dataset = ? AND hash = ? ORDER BY sheet_id"
        ))
        .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_all()
        .await?;
    Ok(rows.into_iter().map(SheetRow::into_sheet).collect())
}

/// The data rows of each sheet in its reading, as one predicate over the `table_cells`
/// alias `alias` (with its dot). `extents` also bounds each sheet by its stored rows and
/// columns. `None` when no sheet has a data row.
fn sheet_bounds(alias: &str, sheets: &[(TableSheet, SheetInterpretation)], extents: bool) -> Option<String> {
    let parts: Vec<String> = sheets
        .iter()
        .filter(|(_, interpretation)| interpretation.selected_rows() > 0)
        .map(|(sheet, interpretation)| {
            let extent = if extents {
                format!(" AND {alias}row_id <= {} AND {alias}column_id <= {}", interpretation.stored_rows, sheet.column_count)
            } else {
                String::new()
            };
            format!("({alias}sheet_id = {} AND {alias}row_id > {}{extent})", sheet.sheet_id, interpretation.selected)
        })
        .collect();
    (!parts.is_empty()).then(|| format!("({})", parts.join(" OR ")))
}

/// Every sheet of a document with the display reading of the website grid.
async fn display_sheets(
    client: &clickhouse::Client,
    document_identifier: &DocumentIdentifier,
    manifest: &TableManifest,
) -> anyhow::Result<Vec<(TableSheet, SheetInterpretation)>> {
    Ok(sheets_of(client, document_identifier)
        .await?
        .into_iter()
        .map(|sheet| {
            let interpretation = display_sheet_interpretation(&sheet, &manifest.reader);
            (sheet, interpretation)
        })
        .collect())
}

#[derive(Debug, clickhouse::Row, serde::Deserialize)]
struct ColumnRow {
    sheet_id: u16,
    column_id: u32,
    letter: String,
    header: String,
    column_type: String,
    non_empty: u64,
    distinct_count: u64,
    min_value: String,
    max_value: String,
    samples: Vec<String>,
}

#[derive(Debug, clickhouse::Row, serde::Deserialize)]
struct CellRow {
    column_id: u32,
    row_id: u64,
    source_row: u64,
    cell_kind: String,
    cell_text: String,
    cell_link: String,
    cell_formula: String,
    cell_int: Option<i64>,
}

/// What the manifest says about one document, for one dataset.
///
/// Holding this value is the proof that step 2 happened. Nothing below queries
/// `table_cells` without one in scope.
#[derive(Debug, Clone)]
pub struct TableManifest {
    pub reader: String,
    pub table_format: String,
    pub sheet_count: u16,
    pub row_count: u64,
    pub column_count: u32,
    pub cell_count: u64,
    pub stored_bytes: u64,
    pub truncations: Vec<TableTruncation>,
    pub truncated_reason: String,
    /// The reader version and the write time of the manifest row. The agent table
    /// routes build their source fingerprint from these two values and read no cell.
    pub reader_version: u16,
    pub updated_at: u32,
}

/// The `(collection_dataset, hash)` lookup, with the read permission checked first.
///
/// `Ok(None)` means "this document is not a browsable table in this dataset", which is
/// the ordinary answer for the overwhelming majority of documents, and is why the source
/// list and the metadata section can call this on every document they render.
pub async fn load_table_manifest(
    user: &CurrentUser,
    document_identifier: &DocumentIdentifier,
) -> anyhow::Result<Option<TableManifest>> {
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
    let rows: Vec<ManifestRow> = client
        .query(
            // `status = 'ok'` is part of the lookup, not a later check: a `parsing` row is
            // a claim staked before the cells were written and a `failed` row describes a
            // document that has none, and opening a grid on either shows a reader an empty
            // spreadsheet where the answer is "this is not ready" or "this did not read".
            "SELECT reader, table_format, sheet_count, row_count, column_count, cell_count, \
                    stored_bytes, truncated_limits, truncated_maximums, truncated_sheets, \
                    truncated_reason, reader_version, toUnixTimestamp(updated_at) AS updated_at \
             FROM table_documents FINAL \
             WHERE collection_dataset = ? AND hash = ? AND status = 'ok' \
             LIMIT 1",
        )
        .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        // A collection whose database has no `table_documents` yet is "no table here",
        // not a failure that should cost the reader every other source of the document.
        .fetch_all()
        .await
        .unwrap_or_default();

    let Some(row) = rows.into_iter().next() else {
        return Ok(None);
    };

    // Three parallel arrays, one cap event per index. `truncated_sheets[i]` is empty both
    // for a document-wide cap and for a delimited file's single unnamed sheet, so the two
    // are told apart by the limit NAME, never by the sheet string.
    let truncations = row
        .truncated_limits
        .iter()
        .enumerate()
        .map(|(i, limit)| TableTruncation {
            limit: limit.clone(),
            maximum: row.truncated_maximums.get(i).copied().unwrap_or(0),
            sheet: row.truncated_sheets.get(i).cloned().unwrap_or_default(),
        })
        .collect();

    Ok(Some(TableManifest {
        reader: row.reader,
        table_format: row.table_format,
        sheet_count: row.sheet_count,
        row_count: row.row_count,
        column_count: row.column_count,
        cell_count: row.cell_count,
        stored_bytes: row.stored_bytes,
        truncations,
        truncated_reason: row.truncated_reason,
        reader_version: row.reader_version,
        updated_at: row.updated_at,
    }))
}

/// The same lookup, as a hard gate: absence is the 404 that keeps a cell query from ever
/// running for a dataset the reader may not read.
async fn require_table_manifest(
    user: &CurrentUser,
    document_identifier: &DocumentIdentifier,
) -> anyhow::Result<TableManifest> {
    match load_table_manifest(user, document_identifier).await? {
        Some(manifest) => Ok(manifest),
        // Deliberately the same message whether the document is in another dataset, is
        // not a table, or does not exist: a refusal that distinguishes them is an
        // existence oracle over every collection on the server.
        None => anyhow::bail!("{NOT_FOUND}: no browsable table for this document"),
    }
}

/// Everything the explorer needs before it asks for a single cell: the sheets, the
/// columns and their statistics, and the caps that fired.
///
/// `Ok(None)` for a document that is not a browsable table. The ordinary answer.
pub async fn get_table_overview(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Option<TableOverview>> {
    let Some(manifest) = load_table_manifest(user, &document_identifier).await? else {
        return Ok(None);
    };
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;

    let sheets = sheets_of(&client, &document_identifier).await?;

    let column_rows: Vec<ColumnRow> = client
        .query(
            "SELECT sheet_id, column_id, letter, header, column_type, non_empty, \
                    distinct_count, min_value, max_value, samples \
             FROM table_columns FINAL \
             WHERE collection_dataset = ? AND hash = ? \
             ORDER BY sheet_id, column_id",
        )
        .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_all()
        .await?;

    // Every row count a reader sees is a DATA row count, so the header rows of the display
    // choice come off it here, once per sheet, and only where a sheet has one. The stored
    // figures are still in the raw dumps of `table_documents` and `table_sheets` for
    // anyone who wants them.
    let header_rows: u64 = sheets.iter().map(|sheet| sheet.header_row).sum();

    Ok(Some(TableOverview {
        reader: manifest.reader,
        table_format: manifest.table_format,
        sheet_count: manifest.sheet_count,
        row_count: manifest.row_count.saturating_sub(header_rows),
        column_count: manifest.column_count,
        cell_count: manifest.cell_count,
        stored_bytes: manifest.stored_bytes,
        // Sheet ordinals are the workbook's own and are not contiguous; the picker is
        // built from these rows and never from a range.
        sheets,
        columns: column_rows
            .into_iter()
            .map(|row| TableColumnInfo {
                sheet_id: row.sheet_id,
                column_id: row.column_id,
                letter: row.letter,
                header: row.header,
                column_type: row.column_type,
                non_empty: row.non_empty,
                distinct_count: row.distinct_count,
                min_value: row.min_value,
                max_value: row.max_value,
                samples: row.samples,
            })
            .collect(),
        truncations: manifest.truncations,
        truncated_reason: manifest.truncated_reason,
    }))
}

/// The `AND row_id > N` fragment that keeps a sheet's header row out of its data.
///
/// Empty when `header_row` is `0`, which is a sheet with no header row: there is nothing
/// to skip and splicing `row_id > 0` would only cost a comparison. Spliced rather than
/// bound because it is an integer read from the manifest, like `sheet_id` beside it.
fn data_row_floor(header_row: u64) -> String {
    if header_row == 0 {
        String::new()
    } else {
        format!(" AND row_id > {header_row}")
    }
}

/// A value bound into the query, in the order the SQL text mentions it.
///
/// Every reader-supplied value goes through here. Integers do not: they are validated
/// against the manifest before the SQL is built and are spliced as digits, which is what
/// lets one fragment be reused inside several subqueries without the bind order becoming
/// impossible to follow.
enum Bind {
    Str(String),
    F64(f64),
    Strs(Vec<String>),
}

fn apply_binds(
    mut query: clickhouse::query::Query,
    binds: Vec<Bind>,
) -> clickhouse::query::Query {
    for bind in binds {
        query = match bind {
            Bind::Str(value) => query.bind(value),
            Bind::F64(value) => query.bind(value),
            Bind::Strs(values) => query.bind(values),
        };
    }
    query
}

/// One filter, as a SQL predicate over a single cell row plus the values it binds.
fn filter_predicate(kind: &TableFilterKind, binds: &mut Vec<Bind>) -> String {
    match kind {
        TableFilterKind::Contains(text) => {
            binds.push(Bind::Str(text.clone()));
            "positionCaseInsensitiveUTF8(cell_text, ?) > 0".to_string()
        }
        TableFilterKind::Equals(text) => {
            binds.push(Bind::Str(text.clone()));
            "cell_text = ?".to_string()
        }
        TableFilterKind::StartsWith(text) => {
            binds.push(Bind::Str(text.clone()));
            "startsWith(lowerUTF8(cell_text), lowerUTF8(?))".to_string()
        }
        TableFilterKind::NumberRange { min, max } => {
            let mut parts = vec!["cell_float IS NOT NULL".to_string()];
            if let Some(min) = min {
                binds.push(Bind::F64(*min));
                parts.push("cell_float >= ?".to_string());
            }
            if let Some(max) = max {
                binds.push(Bind::F64(*max));
                parts.push("cell_float <= ?".to_string());
            }
            parts.join(" AND ")
        }
        TableFilterKind::DateRange { min, max } => {
            let mut parts = vec!["cell_time IS NOT NULL".to_string()];
            // `…OrNull` rather than the throwing form: a half-typed date in a filter box
            // must narrow to nothing, not turn the whole grid into an error card.
            if let Some(min) = min {
                binds.push(Bind::Str(min.clone()));
                parts.push("cell_time >= parseDateTime64BestEffortOrNull(?, 3, 'UTC')".to_string());
            }
            if let Some(max) = max {
                binds.push(Bind::Str(max.clone()));
                parts.push("cell_time <= parseDateTime64BestEffortOrNull(?, 3, 'UTC')".to_string());
            }
            parts.join(" AND ")
        }
        // Handled by the caller as a NOT IN, since "no cell here" is the absence of a row
        // rather than a property of one.
        TableFilterKind::IsEmpty => "1".to_string(),
    }
}

/// The comparator for one column class, as an `ORDER BY` fragment.
///
/// `cell_text` is the tie-break in every class, so two rows whose typed value is equal
/// (or absent) still have a stable, meaningful order rather than storage order.
fn sort_expression(class: TableColumnClass, desc: bool) -> String {
    let direction = if desc { "DESC" } else { "ASC" };
    let typed = match class {
        TableColumnClass::Number => "cell_float",
        TableColumnClass::Temporal => "cell_time",
        TableColumnClass::Text => "cell_text",
    };
    // NULLS LAST in BOTH directions: a numeric column with one unparsable cell should not
    // put that cell at the top of a descending sort, where it reads as the largest value.
    format!("{typed} {direction} NULLS LAST, cell_text {direction}, row_id ASC")
}

/// One column of a sheet in one reading of row 1.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct ViewColumn {
    pub column_id: u32,
    pub letter: String,
    /// The header text of the reading, empty in the reading with no header row.
    pub header: String,
    /// The type that the column sorts and filters as in the reading.
    pub column_type: String,
    /// The cell count of each kind in the data rows of the reading, most frequent first.
    pub kinds: Vec<(String, u64)>,
}

impl ViewColumn {
    /// The name of the column: its header text, else `Column <letter>`, as
    /// [`TableColumnInfo::label`] gives it.
    pub fn label(&self) -> String {
        if self.header.trim().is_empty() { format!("Column {}", self.letter) } else { self.header.clone() }
    }
}

#[derive(Debug, clickhouse::Row, serde::Deserialize)]
struct ViewColumnRow {
    column_id: u32,
    letter: String,
    header: String,
    column_type: String,
    kind_names: Vec<String>,
    kind_counts: Vec<u64>,
}

#[derive(Debug, clickhouse::Row, serde::Deserialize)]
struct BoundaryCellRow {
    column_id: u32,
    row_id: u64,
    cell_kind: String,
    cell_text: String,
}

/// The columns of `sheet` in `interpretation`, in ordinal order.
///
/// `table_columns` describes the data rows of the display choice. A reading with that
/// header row uses the stored header, type and kind counts. Another reading moves the rows
/// between the two header rows into or out of its data rows: it adds or removes the kinds
/// of their cells, takes its header text from its own header row, and computes the type
/// from the kinds that result. One query reads those cells, at most one row of each column
/// for the readings that the reader records.
pub async fn view_columns(
    client: &clickhouse::Client,
    document_identifier: &DocumentIdentifier,
    sheet: &TableSheet,
    interpretation: &SheetInterpretation,
) -> anyhow::Result<Vec<ViewColumn>> {
    let rows: Vec<ViewColumnRow> = client
        .query(
            "SELECT column_id, letter, header, column_type, kind_names, kind_counts FROM table_columns FINAL \
             WHERE collection_dataset = ? AND hash = ? AND sheet_id = ? ORDER BY column_id",
        )
        .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .bind(sheet.sheet_id)
        .fetch_all()
        .await?;
    let mut columns: Vec<ViewColumn> = rows
        .into_iter()
        .map(|row| ViewColumn {
            column_id: row.column_id,
            letter: row.letter,
            header: row.header,
            column_type: row.column_type,
            kinds: row.kind_names.into_iter().zip(row.kind_counts).collect(),
        })
        .collect();
    let (display, selected) = (sheet.header_row, interpretation.selected);
    if selected == display {
        return Ok(columns);
    }
    let (low, high) = (display.min(selected), display.max(selected));
    let cells: Vec<BoundaryCellRow> = client
        .query(&format!(
            "SELECT column_id, row_id, cell_kind, cell_text FROM table_cells FINAL \
             WHERE file_hash = ? AND sheet_id = {} AND column_id <= {} \
             AND ((row_id > {low} AND row_id <= {high}) OR row_id = {selected})",
            sheet.sheet_id, sheet.column_count
        ))
        .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS)
        .bind(&document_identifier.file_hash)
        .fetch_all()
        .await?;
    apply_reading(&mut columns, &cells, display, selected);
    Ok(columns)
}

/// Moves the rows between the display header row and the selected header row into or out
/// of the data rows of `columns`, as [`view_columns`] describes.
fn apply_reading(columns: &mut [ViewColumn], cells: &[BoundaryCellRow], display: u64, selected: u64) {
    let (low, high) = (display.min(selected), display.max(selected));
    for column in columns.iter_mut() {
        column.header = String::new();
        let mut kinds: std::collections::BTreeMap<String, i64> =
            column.kinds.iter().map(|(kind, count)| (kind.clone(), *count as i64)).collect();
        for cell in cells.iter().filter(|cell| cell.column_id == column.column_id) {
            if cell.row_id == selected && selected > 0 {
                column.header = cell.cell_text.clone();
            }
            if cell.row_id > low && cell.row_id <= high {
                // A smaller header row gives more data rows.
                let change = if selected < display { 1 } else { -1 };
                *kinds.entry(cell.cell_kind.clone()).or_insert(0) += change;
            }
        }
        let mut counted: Vec<(String, u64)> =
            kinds.into_iter().filter(|(_, count)| *count > 0).map(|(kind, count)| (kind, count as u64)).collect();
        counted.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
        column.column_type = column_type_of(&counted);
        column.kinds = counted;
    }
}

/// One window of one sheet: the rows, the total after filtering, and what was clamped.
/// The website grid reads the display choice of row 1.
pub async fn get_table_page(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    query: TableViewQuery,
) -> anyhow::Result<TablePage> {
    Ok(read_table_page(user, document_identifier, query, TableRead::Display).await?.page)
}

/// A window of one sheet in one reading of row 1, with that reading and its columns.
#[derive(Debug, Clone)]
pub struct TablePageRead {
    pub page: TablePage,
    pub sheet: TableSheet,
    pub interpretation: SheetInterpretation,
    pub columns: Vec<ViewColumn>,
}

/// [`get_table_page`] in the reading that `read` selects.
pub async fn read_table_page(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    query: TableViewQuery,
    read: TableRead<'_>,
) -> anyhow::Result<TablePageRead> {
    let manifest = require_table_manifest(user, &document_identifier).await?;
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
    let hash = document_identifier.file_hash.clone();

    // The sheet and its extents, from the manifest's own tables. A request naming a sheet
    // that does not exist is a 404 rather than an empty grid: sheet ordinals are the
    // workbook's, not indices, so "sheet 1" of a two-sheet workbook is often absent and
    // an empty grid would read as "this sheet is empty".
    let sheets = sheets_of(&client, &document_identifier).await?;
    let Some(sheet) = sheets.into_iter().find(|sheet| sheet.sheet_id == query.sheet_id) else {
        anyhow::bail!("{NOT_FOUND}: this document has no sheet {}", query.sheet_id);
    };
    let interpretation = resolve_read(&sheet, &manifest.reader, read)?;
    let sheet_id = sheet.sheet_id;
    let stored_rows = interpretation.stored_rows;
    // The header row of the reading is not a data row, so the data begins after it and
    // every count below is a count of data rows. See the module docstring.
    let header_row = interpretation.selected;
    let floor = data_row_floor(header_row);
    let sheet_rows = interpretation.selected_rows();

    // Column types of the reading, so the comparator and every filter predicate are chosen
    // from what the pipeline recorded rather than from what the caller claims.
    let columns = view_columns(&client, &document_identifier, &sheet, &interpretation).await?;
    let known_columns: Vec<u32> = columns.iter().map(|column| column.column_id).collect();
    let class_of = |column_id: u32| -> TableColumnClass {
        columns
            .iter()
            .find(|column| column.column_id == column_id)
            .map(|column| TableColumnClass::of(&column.column_type))
            .unwrap_or(TableColumnClass::Text)
    };

    // Validation against the manifest's extents, before anything reaches SQL. These are
    // integers, so this is not an injection question. It is a "a request for column
    // 4 000 000 must not become a query that scans nothing for a second" question.
    let requested_columns: Vec<u32> = if query.visible_columns.is_empty() {
        known_columns.clone()
    } else {
        query
            .visible_columns
            .iter()
            .copied()
            .filter(|c| known_columns.contains(c))
            .collect()
    };
    let columns_requested = requested_columns.len() as u32;
    let visible_columns = clamp_table_visible_columns(&requested_columns);
    let columns_applied = visible_columns.len() as u32;

    let rows_requested = query.limit;
    let limit = clamp_table_page_rows(query.limit);
    let clamps = TableClamps {
        rows_requested: if rows_requested == 0 { limit } else { rows_requested },
        rows_applied: limit,
        columns_requested,
        columns_applied,
    };

    // A filter naming a column this sheet does not have is dropped rather than refused:
    // a shared URL outlives a re-ingest that renumbered a sheet's columns, and losing one
    // filter is a better answer than losing the page.
    let filters: Vec<TableColumnFilter> = query
        .filters
        .iter()
        .filter(|f| known_columns.contains(&f.column_id) && !f.kind.is_noop())
        .cloned()
        .collect();
    let sort = query
        .sort
        .filter(|sort| known_columns.contains(&sort.column_id));
    let search = table_find_terms(user, &document_identifier, &query.search).await;

    let constrained = !filters.is_empty() || !search.is_empty();
    let offset = query.offset;

    // ---- how many rows match at all -------------------------------------------------
    let total_rows = if constrained {
        let mut binds = vec![Bind::Str(hash.clone())];
        let constraints = build_constraints(&filters, &search, sheet_id, &hash, &mut binds);
        let sql = format!(
            "SELECT count() FROM (SELECT DISTINCT row_id FROM table_cells FINAL \
             WHERE file_hash = ? AND sheet_id = {sheet_id}{floor}{constraints})"
        );
        let query = client
            .query(&sql)
            .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS);
        apply_binds(query, binds).fetch_one::<u64>().await?
    } else {
        // `row_id` is dense within a sheet, so the sheet's own row count IS the total.
        sheet_rows
    };

    // ---- phase 1: the row ids of this window, in order ------------------------------
    let window_rows: Vec<u64> = if let Some(sort) = sort {
        let class = class_of(sort.column_id);
        let column_id = sort.column_id;
        let order = sort_expression(class, sort.desc);

        // How many matching rows even have a cell in the sort column. The rest sort last,
        // in both directions, and are appended from a second query.
        let mut binds = vec![Bind::Str(hash.clone())];
        let constraints = build_constraints(&filters, &search, sheet_id, &hash, &mut binds);
        let sorted_total: u64 = apply_binds(
            client
                .query(&format!(
                    "SELECT count() FROM (SELECT DISTINCT row_id FROM table_cells FINAL \
                     WHERE file_hash = ? AND sheet_id = {sheet_id} AND column_id = {column_id}\
                     {floor}{constraints})"
                ))
                .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS),
            binds,
        )
        .fetch_one()
        .await?;

        let mut ids: Vec<u64> = Vec::new();
        if offset < sorted_total {
            let take = limit as u64;
            let mut binds = vec![Bind::Str(hash.clone())];
            let constraints = build_constraints(&filters, &search, sheet_id, &hash, &mut binds);
            ids = apply_binds(
                client
                    .query(&format!(
                        "SELECT row_id FROM table_cells FINAL \
                         WHERE file_hash = ? AND sheet_id = {sheet_id} AND column_id = {column_id}\
                         {floor}{constraints} \
                         ORDER BY {order} LIMIT {take} OFFSET {offset}"
                    ))
                    .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS),
                binds,
            )
            .fetch_all()
            .await?;
        }
        if (ids.len() as u32) < limit && total_rows > sorted_total {
            let tail_offset = offset.saturating_sub(sorted_total.min(offset));
            let tail_take = limit as u64 - ids.len() as u64;
            let mut binds = vec![Bind::Str(hash.clone())];
            let constraints = build_constraints(&filters, &search, sheet_id, &hash, &mut binds);
            binds.push(Bind::Str(hash.clone()));
            let tail: Vec<u64> = apply_binds(
                client
                    .query(&format!(
                        "SELECT DISTINCT row_id FROM table_cells FINAL \
                         WHERE file_hash = ? AND sheet_id = {sheet_id}{floor}{constraints} \
                         AND row_id NOT IN (SELECT row_id FROM table_cells FINAL \
                           WHERE file_hash = ? AND sheet_id = {sheet_id} AND column_id = {column_id}) \
                         ORDER BY row_id ASC LIMIT {tail_take} OFFSET {tail_offset}"
                    ))
                    .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS),
                binds,
            )
            .fetch_all()
            .await?;
            ids.extend(tail);
        }
        ids
    } else if constrained {
        let take = limit as u64;
        let mut binds = vec![Bind::Str(hash.clone())];
        let constraints = build_constraints(&filters, &search, sheet_id, &hash, &mut binds);
        apply_binds(
            client
                .query(&format!(
                    "SELECT DISTINCT row_id FROM table_cells FINAL \
                     WHERE file_hash = ? AND sheet_id = {sheet_id}{floor}{constraints} \
                     ORDER BY row_id ASC LIMIT {take} OFFSET {offset}"
                ))
                .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS),
            binds,
        )
        .fetch_all()
        .await?
    } else {
        // Unsorted and unfiltered: `row_id` is 1-based and dense, so the window is
        // arithmetic and needs no query at all. Data row 1 is `row_id = header_row + 1`.
        let first = header_row + offset + 1;
        let last = (header_row + offset + limit as u64).min(stored_rows);
        (first..=last).collect()
    };

    if window_rows.is_empty() || visible_columns.is_empty() {
        let page = TablePage { rows: Vec::new(), total_rows, columns: visible_columns, offset, limit, clamps, find_terms: search };
        return Ok(TablePageRead { page, sheet, interpretation, columns });
    }

    // ---- phase 2: the cells of exactly those rows -----------------------------------
    let cells: Vec<CellRow> = client
        .query(
            "SELECT column_id, row_id, source_row, cell_kind, cell_text, cell_link, \
                    cell_formula, cell_int \
             FROM table_cells FINAL \
             WHERE file_hash = ? AND sheet_id = ? AND column_id IN ? AND row_id IN ?",
        )
        .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS)
        .bind(&hash)
        .bind(sheet_id)
        .bind(&visible_columns)
        .bind(&window_rows)
        .fetch_all()
        .await?;

    // Pivot into rows. The order is phase 1's, index by index, NOT re-derived from the
    // comparator, which is what keeps the two phases from ever disagreeing.
    let mut by_row: std::collections::HashMap<u64, TableRow> = std::collections::HashMap::new();
    for cell in cells {
        let row_id = cell.row_id;
        let source_row = cell.source_row;
        let row = by_row.entry(row_id).or_insert_with(|| TableRow {
            row_id,
            source_row,
            cells: Vec::new(),
        });
        row.cells.push(TableCell {
            column_id: cell.column_id,
            text: cell.cell_text,
            kind: cell.cell_kind,
            link: cell.cell_link,
            formula: cell.cell_formula,
            int_value: cell.cell_int,
            preview: None,
        });
    }
    let rows: Vec<TableRow> = window_rows
        .into_iter()
        .map(|row_id| {
            let mut row = by_row.remove(&row_id).unwrap_or(TableRow {
                row_id,
                // A row whose every visible cell is empty still exists and still has a
                // number; drawing it blank is the truth, skipping it is not.
                source_row: row_id,
                cells: Vec::new(),
            });
            row.cells.sort_by_key(|c| {
                visible_columns
                    .iter()
                    .position(|v| *v == c.column_id)
                    .unwrap_or(usize::MAX)
            });
            row
        })
        .collect();

    let page = TablePage { rows, total_rows, columns: visible_columns, offset, limit, clamps, find_terms: search };
    Ok(TablePageRead { page, sheet, interpretation, columns })
}

/// Fill the inline excerpt of every cell of a page for the website grid. The excerpt marks
/// the page's own find terms, the terms that selected its rows.
///
/// The website route calls this after [`get_table_page`]. The agent route does not, so it
/// keeps reading the raw `text` and pays nothing for an excerpt it does not show.
pub fn fill_cell_previews(page: &mut TablePage) {
    let terms = page.find_terms.clone();
    for row in &mut page.rows {
        for cell in &mut row.cells {
            cell.preview = Some(cell_preview(&cell.text, &terms));
        }
    }
}

/// Most find terms of one table read. The in-PDF search sends at most the same number of
/// keywords to its sidecar.
const MAX_TABLE_FIND_TERMS: usize = 50;

/// The cell text that the find terms are compared with. The extractors write a tab between
/// cells and a line break between rows. So a term from a cell with a line break holds a
/// space in its place.
const FIND_CELL_TEXT: &str = "translate(cell_text, '\\t\\r\\n', '   ')";

/// The terms that the table find searches cells for, for one find text.
///
/// An empty find text gives no terms. The other terms are the find text without its double
/// quotes and the runs that Manticore marked in this document for the same query. The
/// module docstring gives the reason. When the Manticore read fails, the find text is the
/// only term and the grid matches as a literal substring.
pub async fn table_find_terms(
    user: &CurrentUser,
    document_identifier: &DocumentIdentifier,
    query: &str,
) -> Vec<String> {
    let literal = table_find_text(query);
    if literal.is_empty() {
        return Vec::new();
    }
    match search_document_text_all_hits(user, document_identifier.clone(), query.to_string()).await {
        Ok(hits) => terms_from_marks(
            &literal,
            hits.iter()
                .flat_map(|hit| hit.highlight_text_spans.iter())
                .filter(|span| span.is_highlighted)
                .map(|span| span.text.as_str()),
        ),
        Err(error) => {
            tracing::warn!(%error, "table find: the search engine read failed, the find text is the only term");
            vec![literal]
        }
    }
}

/// The find text and each marked run split at tabs and line breaks, trimmed, without empty
/// parts and without case-insensitive duplicates, at most [`MAX_TABLE_FIND_TERMS`]. The find
/// text is first, so the limit never removes it.
fn terms_from_marks<'a>(literal: &str, marks: impl Iterator<Item = &'a str>) -> Vec<String> {
    let mut seen = std::collections::HashSet::new();
    let mut terms = Vec::new();
    let parts = marks.flat_map(|mark| mark.split(['\t', '\n', '\r']));
    for part in std::iter::once(literal).chain(parts) {
        let part = part.trim();
        if part.is_empty() || !seen.insert(part.to_lowercase()) {
            continue;
        }
        terms.push(part.to_string());
        if terms.len() == MAX_TABLE_FIND_TERMS {
            break;
        }
    }
    terms
}

/// Build the `AND row_id IN (…)` clauses and push their binds, in textual order.
///
/// Split out because the page needs the identical fragment in up to four queries and the
/// bind order must match the SQL text exactly in each of them.
fn build_constraints(
    filters: &[TableColumnFilter],
    search: &[String],
    sheet_id: u16,
    hash: &str,
    binds: &mut Vec<Bind>,
) -> String {
    let mut clauses = Vec::new();
    for filter in filters {
        let column_id = filter.column_id;
        match &filter.kind {
            TableFilterKind::IsEmpty => {
                binds.push(Bind::Str(hash.to_string()));
                clauses.push(format!(
                    "row_id NOT IN (SELECT row_id FROM table_cells FINAL \
                     WHERE file_hash = ? AND sheet_id = {sheet_id} AND column_id = {column_id})"
                ));
            }
            kind => {
                binds.push(Bind::Str(hash.to_string()));
                let predicate = filter_predicate(kind, binds);
                clauses.push(format!(
                    "row_id IN (SELECT row_id FROM table_cells FINAL \
                     WHERE file_hash = ? AND sheet_id = {sheet_id} AND column_id = {column_id} \
                     AND ({predicate}))"
                ));
            }
        }
    }
    if !search.is_empty() {
        binds.push(Bind::Str(hash.to_string()));
        binds.push(Bind::Strs(search.to_vec()));
        clauses.push(format!(
            "row_id IN (SELECT row_id FROM table_cells FINAL \
             WHERE file_hash = ? AND sheet_id = {sheet_id} \
             AND multiSearchAnyCaseInsensitiveUTF8({FIND_CELL_TEXT}, ?))"
        ));
    }
    if clauses.is_empty() {
        String::new()
    } else {
        format!(" AND {}", clauses.join(" AND "))
    }
}

/// How many data rows of each sheet hold a find term of `search` ([`table_find_terms`]),
/// as `(sheet_id, rows)`, for the sheet chooser. A sheet with no match is absent. The count
/// is the one the grid shows for the same search on that sheet, so it excludes the header
/// row.
pub async fn get_table_sheet_hits(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    search: String,
) -> anyhow::Result<Vec<(u16, u64)>> {
    if table_find_text(&search).is_empty() {
        return Ok(Vec::new());
    }
    let manifest = require_table_manifest(user, &document_identifier).await?;
    let search = table_find_terms(user, &document_identifier, &search).await;
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
    // The grid's own search count bounds a sheet by its header row only, so this does too.
    let Some(bounds) = sheet_bounds("c.", &display_sheets(&client, &document_identifier, &manifest).await?, false) else {
        return Ok(Vec::new());
    };
    Ok(client
        .query(&format!(
            "SELECT c.sheet_id, uniqExact(c.row_id) FROM table_cells AS c FINAL \
             WHERE c.file_hash = ? AND {bounds} \
             AND multiSearchAnyCaseInsensitiveUTF8(translate(c.cell_text, '\\t\\r\\n', '   '), ?) \
             GROUP BY c.sheet_id ORDER BY c.sheet_id"
        ))
        .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS)
        .bind(&document_identifier.file_hash)
        .bind(search)
        .fetch_all()
        .await?)
}

/// The distinct values of one column, most frequent first, for the filter popover's list.
pub async fn get_table_column_values(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    sheet_id: u16,
    column_id: u32,
    search: String,
) -> anyhow::Result<Vec<TableColumnValue>> {
    let search = table_find_text(&search);
    let manifest = require_table_manifest(user, &document_identifier).await?;
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;

    // The column has to exist on that sheet before a cell query runs, for the same reason
    // the page validates its visible set.
    let known: Vec<u32> = client
        .query(
            "SELECT column_id FROM table_columns FINAL \
             WHERE collection_dataset = ? AND hash = ? AND sheet_id = ? AND column_id = ? LIMIT 1",
        )
        .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .bind(sheet_id)
        .bind(column_id)
        .fetch_all()
        .await?;
    if known.is_empty() {
        anyhow::bail!("{NOT_FOUND}: this sheet has no column {column_id}");
    }

    // The header row's text is this column's LABEL, not one of its values, and the column
    // statistics beside this list already exclude it. Offering it as a filterable value
    // would let a reader pick a value that matches no data row.
    let (header_row, row_count, column_count) = match display_sheets(&client, &document_identifier, &manifest)
        .await?
        .into_iter()
        .find(|(sheet, _)| sheet.sheet_id == sheet_id)
    {
        Some((sheet, interpretation)) => (interpretation.selected, interpretation.stored_rows, sheet.column_count),
        None => (0, 0, 0),
    };
    let floor = data_row_floor(header_row);

    // The search string is BOUND. See the module docstring: the Manticore escaping next
    // door exists because Manticore has nothing to bind, and copying it here would be a
    // second, worse escaping layer over a parameter that is already safe.
    let rows: Vec<(String, u64)> = client
        .query(&format!(
            "SELECT cell_text, count() AS n FROM table_cells FINAL \
             WHERE file_hash = ? AND sheet_id = ? AND column_id = ?{floor} AND row_id <= {row_count} AND column_id <= {column_count} \
               AND (? = '' OR positionCaseInsensitiveUTF8(cell_text, ?) > 0) \
             GROUP BY cell_text ORDER BY n DESC, cell_text ASC LIMIT {MAX_TABLE_COLUMN_VALUES}"
        ))
        .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS)
        .bind(&document_identifier.file_hash)
        .bind(sheet_id)
        .bind(column_id)
        .bind(&search)
        .bind(&search)
        .fetch_all()
        .await?;

    Ok(rows
        .into_iter()
        .map(|(value, count)| TableColumnValue { value, count })
        .collect())
}

/// How many cells of this document hold a find term of the viewer's find box
/// ([`table_find_terms`]).
///
/// Feeds the `Table` entry's number in the source selector, the way page hits feed the
/// text sources'.
pub async fn count_table_cell_matches(
    user: &CurrentUser,
    document_identifier: &DocumentIdentifier,
    find_query: &str,
) -> anyhow::Result<u64> {
    if table_find_text(find_query).is_empty() {
        return Ok(0);
    }
    let manifest = require_table_manifest(user, document_identifier).await?;
    let find_terms = table_find_terms(user, document_identifier, find_query).await;
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
    // Header rows are excluded, so this number counts the same cells the grid can show a
    // reader. A term that only appears in a header would otherwise promise matches that
    // no row of the grid contains. The header is drawn once, as the column label.
    let Some(bounds) = sheet_bounds("c.", &display_sheets(&client, document_identifier, &manifest).await?, true) else {
        return Ok(0);
    };
    let count: u64 = client
        .query(&format!(
            "SELECT count() FROM table_cells AS c FINAL \
             WHERE c.file_hash = ? AND {bounds} \
               AND multiSearchAnyCaseInsensitiveUTF8(translate(c.cell_text, '\\t\\r\\n', '   '), ?)"
        ))
        .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS)
        .bind(&document_identifier.file_hash)
        .bind(find_terms)
        .fetch_one()
        .await?;
    Ok(count)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The excerpt is added beside the raw value. Text, row order and totals stay as the
    /// reader returned them, because sorting, filters and the full-cell view read those.
    #[test]
    fn previews_leave_the_raw_page_unchanged() {
        let raw = format!("{} \"Jenalynn Weed\" {}", "a ".repeat(200), "b ".repeat(200));
        let cell = |column_id, text: &str| TableCell { column_id, text: text.to_string(), ..Default::default() };
        let mut page = TablePage {
            rows: vec![
                TableRow { row_id: 9, source_row: 10, cells: vec![cell(1, &raw), cell(2, "short")] },
                TableRow { row_id: 3, source_row: 4, cells: vec![cell(1, "weed")] },
            ],
            total_rows: 2,
            ..Default::default()
        };
        page.find_terms = vec!["weed".to_string()];
        let before = page.clone();
        fill_cell_previews(&mut page);
        assert_eq!(page.total_rows, before.total_rows);
        let ids: Vec<u64> = page.rows.iter().map(|r| r.row_id).collect();
        assert_eq!(ids, vec![9, 3]);
        for (row, old) in page.rows.iter().zip(&before.rows) {
            for (cell, old_cell) in row.cells.iter().zip(&old.cells) {
                assert_eq!(cell.text, old_cell.text);
                assert!(cell.preview.is_some());
            }
        }
        let long = page.rows[0].cells[0].preview.as_ref().unwrap();
        assert!(long.lines.iter().flatten().any(|(t, m)| *m && t == "Weed"));
    }

    #[test]
    fn every_column_class_sorts_its_blanks_last_in_both_directions() {
        for class in [
            TableColumnClass::Number,
            TableColumnClass::Temporal,
            TableColumnClass::Text,
        ] {
            for desc in [false, true] {
                let expression = sort_expression(class, desc);
                assert!(expression.contains("NULLS LAST"), "{expression}");
                assert!(expression.ends_with("row_id ASC"), "{expression}");
            }
        }
    }

    /// The header row is stored as cells and drawn as the column labels, so no read that
    /// feeds the grid may see it, and a sheet without one must lose nothing.
    #[test]
    fn the_header_row_is_floored_out_and_only_when_there_is_one() {
        assert_eq!(data_row_floor(0), "");
        assert_eq!(data_row_floor(1), " AND row_id > 1");
        assert_eq!(data_row_floor(4), " AND row_id > 4");
    }

    fn column(id: u32, header: &str, kinds: &[(&str, u64)]) -> ViewColumn {
        let kinds: Vec<(String, u64)> = kinds.iter().map(|(k, n)| (k.to_string(), *n)).collect();
        ViewColumn {
            column_id: id,
            letter: ["A", "B", "C"][id as usize - 1].into(),
            header: header.into(),
            column_type: column_type_of(&kinds),
            kinds,
        }
    }

    fn cell(id: u32, row: u64, kind: &str, text: &str) -> BoundaryCellRow {
        BoundaryCellRow { column_id: id, row_id: row, cell_kind: kind.into(), cell_text: text.into() }
    }

    /// The display choice took row 1 as the header. The reading with every row adds row 1
    /// to the data: its text cell shows in the kinds of a numeric column, and the columns
    /// lose their header text.
    #[test]
    fn every_row_adds_the_header_cells_to_the_kinds() {
        let mut columns = vec![column(1, "office", &[("text", 18)]), column(2, "amount", &[("int", 18)])];
        apply_reading(&mut columns, &[cell(1, 1, "text", "office"), cell(2, 1, "text", "amount")], 1, 0);
        assert_eq!(columns[0].kinds, vec![("text".to_string(), 19)]);
        assert_eq!(columns[1].kinds, vec![("int".to_string(), 18), ("text".to_string(), 1)]);
        assert_eq!(columns[1].column_type, "int");
        assert!(columns.iter().all(|c| c.header.is_empty()));
        assert_eq!(columns[1].label(), "Column B");
    }

    /// The display choice read row 1 as data. The reading with row 1 as header takes its
    /// names from row 1 and removes its cells from the kinds, so a year header leaves a
    /// numeric column with the data rows only.
    #[test]
    fn a_first_row_header_takes_its_names_and_removes_its_kinds() {
        let mut columns = vec![column(1, "", &[("text", 4)]), column(2, "", &[("int", 4)]), column(3, "", &[("int", 3)])];
        let cells = [cell(1, 1, "text", "region"), cell(2, 1, "int", "2018"), cell(3, 1, "int", "2020")];
        apply_reading(&mut columns, &cells, 0, 1);
        assert_eq!(columns.iter().map(ViewColumn::label).collect::<Vec<_>>(), vec!["region", "2018", "2020"]);
        assert_eq!(columns[1].kinds, vec![("int".to_string(), 3)]);
        assert_eq!(columns[2].kinds, vec![("int".to_string(), 2)]);
        assert_eq!(columns[0].column_type, "text");
    }

    /// A column whose only stored cells are in row 1 has no data cell in the reading with
    /// row 1 as header, and reads as text.
    #[test]
    fn a_column_without_a_data_cell_reads_as_text() {
        let mut columns = vec![column(1, "", &[("int", 1)])];
        apply_reading(&mut columns, &[cell(1, 1, "int", "7")], 0, 1);
        assert!(columns[0].kinds.is_empty());
        assert_eq!((columns[0].column_type.as_str(), columns[0].header.as_str()), ("text", "7"));
    }

    #[test]
    fn the_sheet_bounds_follow_each_reading() {
        let interpretation = |selected, stored_rows| SheetInterpretation { selected, stored_rows, ..Default::default() };
        let sheets = vec![
            (TableSheet { sheet_id: 0, column_count: 3, ..Default::default() }, interpretation(1, 39)),
            (TableSheet { sheet_id: 2, column_count: 5, ..Default::default() }, interpretation(0, 7)),
            (TableSheet { sheet_id: 4, column_count: 1, ..Default::default() }, interpretation(1, 1)),
        ];
        assert_eq!(
            sheet_bounds("c.", &sheets, true).unwrap(),
            "((c.sheet_id = 0 AND c.row_id > 1 AND c.row_id <= 39 AND c.column_id <= 3) OR \
             (c.sheet_id = 2 AND c.row_id > 0 AND c.row_id <= 7 AND c.column_id <= 5))"
        );
        assert_eq!(
            sheet_bounds("", &sheets, false).unwrap(),
            "((sheet_id = 0 AND row_id > 1) OR (sheet_id = 2 AND row_id > 0))"
        );
        assert_eq!(sheet_bounds("c.", &sheets[2..], true), None, "a sheet with no data row matches nothing");
    }

    #[test]
    fn a_request_for_a_reading_the_sheet_lacks_is_invalid_input() {
        let sheet = TableSheet {
            row_count: 38,
            header_row: 1,
            header_state: common::document_tables::HEADER_ESTABLISHED.into(),
            header_candidates: vec![1],
            ..Default::default()
        };
        let error = resolve_read(&sheet, "csv", TableRead::Agent(Some("all_rows"))).unwrap_err();
        assert!(crate::auth::guard::is_bad_request(&error), "{error}");
        assert_eq!(resolve_read(&sheet, "csv", TableRead::Display).unwrap().selected, 1);
    }

    #[test]
    fn the_comparator_matches_the_column_class() {
        assert!(sort_expression(TableColumnClass::Number, false).starts_with("cell_float"));
        assert!(sort_expression(TableColumnClass::Temporal, false).starts_with("cell_time"));
        assert!(sort_expression(TableColumnClass::Text, false).starts_with("cell_text"));
    }

    /// Every reader-supplied value is a `?`, and the count of `?` in a fragment must
    /// equal the count of binds it pushed. A mismatch is a query that binds the search
    /// text into the hash position, which would silently return nothing.
    #[test]
    fn every_constraint_binds_exactly_as_many_values_as_it_marks() {
        let cases: Vec<(Vec<TableColumnFilter>, Vec<String>)> = vec![
            (vec![], vec![]),
            (vec![], vec!["needle".to_string(), "pin".to_string()]),
            (
                vec![TableColumnFilter {
                    column_id: 3,
                    kind: TableFilterKind::Contains("acme".into()),
                }],
                vec![],
            ),
            (
                vec![TableColumnFilter {
                    column_id: 3,
                    kind: TableFilterKind::NumberRange { min: Some(1.0), max: Some(9.0) },
                }],
                vec!["needle".to_string()],
            ),
            (
                vec![
                    TableColumnFilter { column_id: 1, kind: TableFilterKind::IsEmpty },
                    TableColumnFilter {
                        column_id: 2,
                        kind: TableFilterKind::DateRange { min: Some("2019-01-01".into()), max: None },
                    },
                    TableColumnFilter {
                        column_id: 4,
                        kind: TableFilterKind::StartsWith("A".into()),
                    },
                ],
                vec!["needle".to_string(), "Prudential Lighting".to_string()],
            ),
        ];
        for (filters, search) in cases {
            let mut binds = Vec::new();
            let sql = build_constraints(&filters, &search, 0, "deadbeef", &mut binds);
            assert_eq!(
                sql.matches('?').count(),
                binds.len(),
                "placeholders and binds disagree for {sql}"
            );
        }
    }

    #[test]
    fn nothing_filtered_and_nothing_searched_is_no_constraint_at_all() {
        let mut binds = Vec::new();
        assert!(build_constraints(&[], &[], 0, "deadbeef", &mut binds).is_empty());
        assert!(binds.is_empty());
    }

    /// "Is empty" is the absence of a row, so it is the one predicate that has to be a
    /// NOT IN rather than a condition on a cell.
    #[test]
    fn is_empty_is_a_negative() {
        let mut binds = Vec::new();
        let sql = build_constraints(
            &[TableColumnFilter { column_id: 7, kind: TableFilterKind::IsEmpty }],
            &[],
            2,
            "deadbeef",
            &mut binds,
        );
        assert!(sql.contains("row_id NOT IN"), "{sql}");
        assert!(sql.contains("column_id = 7"), "{sql}");
        assert!(sql.contains("sheet_id = 2"), "{sql}");
    }

    /// The search text never appears in the SQL text, only a placeholder does.
    #[test]
    fn reader_supplied_text_is_never_spliced_into_the_sql() {
        let mut binds = Vec::new();
        let sql = build_constraints(
            &[TableColumnFilter {
                column_id: 1,
                kind: TableFilterKind::Equals("'; DROP TABLE table_cells --".into()),
            }],
            &["'; SELECT 1 --".to_string()],
            0,
            "deadbeef",
            &mut binds,
        );
        assert!(!sql.contains("DROP"), "{sql}");
        assert!(!sql.contains("SELECT 1"), "{sql}");
    }

    fn marks(values: &[&'static str]) -> std::vec::IntoIter<&'static str> {
        values.to_vec().into_iter()
    }

    /// A phrase that Manticore marks as one run gives one term, beside the find text.
    #[test]
    fn a_marked_phrase_is_one_term() {
        let terms = terms_from_marks("Prudential Lighting Corp.", marks(&["Prudential Lighting Corp"]));
        assert_eq!(terms, vec!["Prudential Lighting Corp.", "Prudential Lighting Corp"]);
    }

    /// Words that Manticore marks one by one give one term each.
    #[test]
    fn each_marked_word_is_a_term() {
        let terms = terms_from_marks("prudential corp", marks(&["Prudential", "Corp", "Corp"]));
        assert_eq!(terms, vec!["prudential corp", "Prudential", "Corp"]);
    }

    /// A phrase across two cells or two rows is marked as one run with a tab or a line
    /// break in it. No cell holds that run, so it splits into the text of each cell.
    #[test]
    fn a_marked_run_splits_at_cell_and_row_breaks() {
        let terms = terms_from_marks("Tarbor Prudential", marks(&["Tarbor\tPrudential", "Acme\r\n Wire \n"]));
        assert_eq!(terms, vec!["Tarbor Prudential", "Tarbor", "Prudential", "Acme", "Wire"]);
    }

    #[test]
    fn duplicates_are_removed_without_regard_to_case() {
        let terms = terms_from_marks("amic", marks(&["AMIC", "Amic Range", "amic range", "Range"]));
        assert_eq!(terms, vec!["amic", "Amic Range", "Range"]);
    }

    #[test]
    fn at_most_fifty_terms_and_the_find_text_stays() {
        let many: Vec<String> = (0..80).map(|i| format!("word{i}")).collect();
        let terms = terms_from_marks("query", many.iter().map(String::as_str));
        assert_eq!(terms.len(), MAX_TABLE_FIND_TERMS);
        assert_eq!(terms[0], "query");
    }

    #[test]
    fn an_empty_find_text_with_no_marks_has_no_terms() {
        assert!(terms_from_marks("", marks(&[" ", "\t"])).is_empty());
    }

    /// The constraint compares the terms with the cell text after the same tab and line
    /// break replacement, and binds the terms as one array.
    #[test]
    fn the_find_constraint_binds_the_terms_as_one_array() {
        let mut binds = Vec::new();
        let sql = build_constraints(&[], &["a".to_string(), "b".to_string()], 1, "deadbeef", &mut binds);
        assert!(sql.contains("multiSearchAnyCaseInsensitiveUTF8(translate(cell_text, '\\t\\r\\n', '   '), ?)"), "{sql}");
        assert!(matches!(binds.last(), Some(Bind::Strs(terms)) if terms.len() == 2));
    }
}
