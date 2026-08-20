//! Browsing one tabular document's cells.
//!
//! # The authorisation rule, first, because everything else depends on it
//!
//! `table_cells` is keyed by **content hash alone** — it has no `collection_dataset`
//! column, because the same spreadsheet ingested into five datasets is one set of cells.
//! That makes a cell read by hash a read across every dataset in the collection. The
//! per-dataset manifest `table_documents` is therefore the *entire* authorisation, and
//! every function here does the same three things in the same order:
//!
//! 1. [`permissions::assert_can_read`] for the dataset,
//! 2. a `(collection_dataset, hash)` lookup in `table_documents` with `status = 'ok'`,
//! 3. and only then a query against `table_cells`.
//!
//! A hash with no manifest row for that dataset — or one whose row is still `parsing` or
//! is `failed` — is a 404 that never reaches step 3. There is no shortcut past this and
//! there must not be one: skipping the lookup lets a reader who may see dataset A read
//! the cells of a document that only exists in dataset B by pasting its hash.
//!
//! # Parameters are bound, not interpolated
//!
//! This is ClickHouse. `db_utils::manticore_match`'s escaping rules exist because
//! Manticore's SQL-ish surface takes a match expression as a *string literal* and there
//! is nothing to bind; none of that applies here and copying it would be wrong. Every
//! value a reader supplies — the search text, a filter's text, a range bound — is bound
//! through `Query::bind`. The only things spliced into the SQL text are integers this
//! module has already validated against the manifest's own extents, and the fixed
//! predicate and comparator fragments below.
//!
//! # Why the sort is two phases
//!
//! Phase 1 orders one contiguous primary-key range — the whole sort column of one sheet,
//! which `ORDER BY (file_hash, sheet_id, column_id, row_id)` makes a single scan — and
//! returns `row_id`s. Phase 2 fetches the window's cells by `row_id IN (…)`. The
//! comparator is not re-derived in phase 2: the window is re-ordered in Rust into phase
//! 1's order, so the two cannot disagree.
//!
//! Rows with **no cell in the sort column** are not in phase 1's range at all. They are
//! appended after the sorted rows, in `row_id` order, in both directions — the same thing
//! a spreadsheet's own sort does with blanks.
//!
//! # The header row is not a data row
//!
//! The reader stores the header row as ordinary cells — it is row `table_sheets.header_row`
//! of `table_cells` — and *also* writes its text into `table_columns.header`, and excludes
//! it from every column statistic. So the grid draws that row's text as its column labels,
//! and drawing it a second time as row 1 of the data shows it twice while making every
//! count disagree with the statistics the filter popovers and type marks come from.
//!
//! Everything reader-facing here therefore starts **after** `header_row`: the row floor
//! [`data_row_floor`] is spliced into every cell query, the totals subtract it, and the
//! unfiltered window's arithmetic is offset by it. `header_row = 0` means the sheet has no
//! header row and nothing is skipped. It is a `row_id` — dense within the sheet — not a
//! `source_row`, so it must never be compared against the file's own row numbers.

use common::current_user::CurrentUser;
use common::document_tables::{
    MAX_TABLE_COLUMN_VALUES, TableCell, TableClamps, TableColumnClass, TableColumnFilter,
    TableColumnInfo, TableColumnValue, TableFilterKind, TableOverview, TablePage, TableRow,
    TableSheet, TableTruncation, TableViewQuery, clamp_table_page_rows,
    clamp_table_visible_columns,
};
use common::search_result::DocumentIdentifier;

use crate::auth::guard::NOT_FOUND;
use crate::auth::permissions;
use crate::db_utils::clickhouse_utils::get_client_for_dataset;

/// Seconds a cell query may run before ClickHouse kills it.
///
/// A sort or a full-column filter reads one whole column, which is a column store's best
/// case and sub-second for anything in a normal corpus. A pathological document must fail
/// visibly rather than hold a connection open, for the same reason the search fan-out
/// carries a deadline.
const TABLE_QUERY_TIMEOUT_SECONDS: &str = "30";

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
}

#[derive(Debug, clickhouse::Row, serde::Deserialize)]
struct SheetRow {
    sheet_id: u16,
    name: String,
    row_count: u64,
    column_count: u32,
    header_row: u64,
    truncated: u8,
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
}

/// The `(collection_dataset, hash)` lookup, with the read permission checked first.
///
/// `Ok(None)` means "this document is not a browsable table in this dataset" — which is
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
                    truncated_reason \
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
    // are told apart by the limit NAME — never by the sheet string.
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
/// `Ok(None)` for a document that is not a browsable table — the ordinary answer.
pub async fn get_table_overview(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Option<TableOverview>> {
    let Some(manifest) = load_table_manifest(user, &document_identifier).await? else {
        return Ok(None);
    };
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;

    let sheet_rows: Vec<SheetRow> = client
        .query(
            "SELECT sheet_id, name, row_count, column_count, header_row, truncated \
             FROM table_sheets FINAL \
             WHERE collection_dataset = ? AND hash = ? \
             ORDER BY sheet_id",
        )
        .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_all()
        .await?;

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

    // Every row count a reader sees is a DATA row count, so the header rows come off it
    // here — once per sheet, and only where a sheet has one. The stored figures are still
    // in the raw dumps of `table_documents` and `table_sheets` for anyone who wants them.
    let header_rows: u64 = sheet_rows.iter().map(|row| row.header_row).sum();

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
        sheets: sheet_rows
            .into_iter()
            .map(|row| TableSheet {
                sheet_id: row.sheet_id,
                name: row.name,
                row_count: row.row_count.saturating_sub(row.header_row),
                column_count: row.column_count,
                header_row: row.header_row,
                truncated: row.truncated == 1,
            })
            .collect(),
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
}

fn apply_binds(
    mut query: clickhouse::query::Query,
    binds: Vec<Bind>,
) -> clickhouse::query::Query {
    for bind in binds {
        query = match bind {
            Bind::Str(value) => query.bind(value),
            Bind::F64(value) => query.bind(value),
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

/// One window of one sheet: the rows, the total after filtering, and what was clamped.
pub async fn get_table_page(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    query: TableViewQuery,
) -> anyhow::Result<TablePage> {
    let _manifest = require_table_manifest(user, &document_identifier).await?;
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
    let hash = document_identifier.file_hash.clone();
    let dataset = document_identifier.collection_dataset.clone();

    // The sheet and its extents, from the manifest's own tables. A request naming a sheet
    // that does not exist is a 404 rather than an empty grid: sheet ordinals are the
    // workbook's, not indices, so "sheet 1" of a two-sheet workbook is often absent and
    // an empty grid would read as "this sheet is empty".
    let sheets: Vec<(u16, u64, u32, u64)> = client
        .query(
            "SELECT sheet_id, row_count, column_count, header_row FROM table_sheets FINAL \
             WHERE collection_dataset = ? AND hash = ? ORDER BY sheet_id",
        )
        .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS)
        .bind(&dataset)
        .bind(&hash)
        .fetch_all()
        .await?;
    let Some(&(sheet_id, stored_rows, _sheet_columns, header_row)) =
        sheets.iter().find(|(id, _, _, _)| *id == query.sheet_id)
    else {
        anyhow::bail!("{NOT_FOUND}: this document has no sheet {}", query.sheet_id);
    };
    // The header row is drawn as the column labels, so the data begins after it and every
    // count below is a count of data rows. See the module docstring.
    let floor = data_row_floor(header_row);
    let sheet_rows = stored_rows.saturating_sub(header_row);

    // Column types, so the comparator and every filter predicate are chosen from what the
    // pipeline recorded rather than from what the caller claims.
    let column_rows: Vec<(u32, String)> = client
        .query(
            "SELECT column_id, column_type FROM table_columns FINAL \
             WHERE collection_dataset = ? AND hash = ? AND sheet_id = ? ORDER BY column_id",
        )
        .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS)
        .bind(&dataset)
        .bind(&hash)
        .bind(sheet_id)
        .fetch_all()
        .await?;
    let known_columns: Vec<u32> = column_rows.iter().map(|(id, _)| *id).collect();
    let class_of = |column_id: u32| -> TableColumnClass {
        column_rows
            .iter()
            .find(|(id, _)| *id == column_id)
            .map(|(_, t)| TableColumnClass::of(t))
            .unwrap_or(TableColumnClass::Text)
    };

    // Validation against the manifest's extents, before anything reaches SQL. These are
    // integers, so this is not an injection question — it is a "a request for column
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
    let search = query.search.clone();

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
        return Ok(TablePage {
            rows: Vec::new(),
            total_rows,
            columns: visible_columns,
            offset,
            limit,
            clamps,
        });
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

    // Pivot into rows. The order is phase 1's, index by index — NOT re-derived from the
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

    Ok(TablePage {
        rows,
        total_rows,
        columns: visible_columns,
        offset,
        limit,
        clamps,
    })
}

/// Build the `AND row_id IN (…)` clauses and push their binds, in textual order.
///
/// Split out because the page needs the identical fragment in up to four queries and the
/// bind order must match the SQL text exactly in each of them.
fn build_constraints(
    filters: &[TableColumnFilter],
    search: &str,
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
        binds.push(Bind::Str(search.to_string()));
        clauses.push(format!(
            "row_id IN (SELECT row_id FROM table_cells FINAL \
             WHERE file_hash = ? AND sheet_id = {sheet_id} \
             AND positionCaseInsensitiveUTF8(cell_text, ?) > 0)"
        ));
    }
    if clauses.is_empty() {
        String::new()
    } else {
        format!(" AND {}", clauses.join(" AND "))
    }
}

/// The distinct values of one column, most frequent first — the filter popover's list.
pub async fn get_table_column_values(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    sheet_id: u16,
    column_id: u32,
    search: String,
) -> anyhow::Result<Vec<TableColumnValue>> {
    let _manifest = require_table_manifest(user, &document_identifier).await?;
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
    let header_row: u64 = client
        .query(
            "SELECT header_row FROM table_sheets FINAL \
             WHERE collection_dataset = ? AND hash = ? AND sheet_id = ? LIMIT 1",
        )
        .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .bind(sheet_id)
        .fetch_all::<u64>()
        .await?
        .into_iter()
        .next()
        .unwrap_or(0);
    let floor = data_row_floor(header_row);

    // The search string is BOUND. See the module docstring: the Manticore escaping next
    // door exists because Manticore has nothing to bind, and copying it here would be a
    // second, worse escaping layer over a parameter that is already safe.
    let rows: Vec<(String, u64)> = client
        .query(&format!(
            "SELECT cell_text, count() AS n FROM table_cells FINAL \
             WHERE file_hash = ? AND sheet_id = ? AND column_id = ?{floor} \
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

/// How many cells of this document match the viewer's find box.
///
/// Feeds the `Table` entry's number in the source selector, the way page hits feed the
/// text sources'.
pub async fn count_table_cell_matches(
    user: &CurrentUser,
    document_identifier: &DocumentIdentifier,
    find_query: &str,
) -> anyhow::Result<u64> {
    if find_query.is_empty() {
        return Ok(0);
    }
    let _manifest = require_table_manifest(user, document_identifier).await?;
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
    // Header rows are excluded, so this number counts the same cells the grid can show a
    // reader. A term that only appears in a header would otherwise promise matches that
    // no row of the grid contains — the header is drawn once, as the column label.
    let count: u64 = client
        .query(
            "SELECT count() FROM table_cells FINAL \
             WHERE file_hash = ? AND positionCaseInsensitiveUTF8(cell_text, ?) > 0 \
               AND (sheet_id, row_id) NOT IN ( \
                 SELECT sheet_id, header_row FROM table_sheets FINAL \
                 WHERE collection_dataset = ? AND hash = ? AND header_row > 0)",
        )
        .with_option("max_execution_time", TABLE_QUERY_TIMEOUT_SECONDS)
        .bind(&document_identifier.file_hash)
        .bind(find_query)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_one()
        .await?;
    Ok(count)
}

#[cfg(test)]
mod tests {
    use super::*;

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
    /// feeds the grid may see it — and a sheet without one must lose nothing.
    #[test]
    fn the_header_row_is_floored_out_and_only_when_there_is_one() {
        assert_eq!(data_row_floor(0), "");
        assert_eq!(data_row_floor(1), " AND row_id > 1");
        assert_eq!(data_row_floor(4), " AND row_id > 4");
    }

    #[test]
    fn the_comparator_matches_the_column_class() {
        assert!(sort_expression(TableColumnClass::Number, false).starts_with("cell_float"));
        assert!(sort_expression(TableColumnClass::Temporal, false).starts_with("cell_time"));
        assert!(sort_expression(TableColumnClass::Text, false).starts_with("cell_text"));
    }

    /// Every reader-supplied value is a `?`, and the count of `?` in a fragment must
    /// equal the count of binds it pushed — a mismatch is a query that binds the search
    /// text into the hash position, which would silently return nothing.
    #[test]
    fn every_constraint_binds_exactly_as_many_values_as_it_marks() {
        let cases: Vec<(Vec<TableColumnFilter>, &str)> = vec![
            (vec![], ""),
            (vec![], "needle"),
            (
                vec![TableColumnFilter {
                    column_id: 3,
                    kind: TableFilterKind::Contains("acme".into()),
                }],
                "",
            ),
            (
                vec![TableColumnFilter {
                    column_id: 3,
                    kind: TableFilterKind::NumberRange { min: Some(1.0), max: Some(9.0) },
                }],
                "needle",
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
                "needle",
            ),
        ];
        for (filters, search) in cases {
            let mut binds = Vec::new();
            let sql = build_constraints(&filters, search, 0, "deadbeef", &mut binds);
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
        assert!(build_constraints(&[], "", 0, "deadbeef", &mut binds).is_empty());
        assert!(binds.is_empty());
    }

    /// "Is empty" is the absence of a row, so it is the one predicate that has to be a
    /// NOT IN rather than a condition on a cell.
    #[test]
    fn is_empty_is_a_negative() {
        let mut binds = Vec::new();
        let sql = build_constraints(
            &[TableColumnFilter { column_id: 7, kind: TableFilterKind::IsEmpty }],
            "",
            2,
            "deadbeef",
            &mut binds,
        );
        assert!(sql.contains("row_id NOT IN"), "{sql}");
        assert!(sql.contains("column_id = 7"), "{sql}");
        assert!(sql.contains("sheet_id = 2"), "{sql}");
    }

    /// The search text never appears in the SQL text — only a placeholder does.
    #[test]
    fn reader_supplied_text_is_never_spliced_into_the_sql() {
        let mut binds = Vec::new();
        let sql = build_constraints(
            &[TableColumnFilter {
                column_id: 1,
                kind: TableFilterKind::Equals("'; DROP TABLE table_cells --".into()),
            }],
            "'; SELECT 1 --",
            0,
            "deadbeef",
            &mut binds,
        );
        assert!(!sql.contains("DROP"), "{sql}");
        assert!(!sql.contains("SELECT 1"), "{sql}");
    }
}
