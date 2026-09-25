//! The table routes: `tables/overview`, `tables/page`, `tables/column_values` and
//! `tables/search_cells`.

use super::*;

// ===================================================================================
// tables: the shared reads
// ===================================================================================

impl Deadline {
    /// A collection client for a table read. Its queries stop at the time that remains,
    /// and never later than the table reads' own `TABLE_QUERY_TIMEOUT_SECONDS`.
    fn table_client(&self, collectionname: &str) -> clickhouse::Client {
        let table_limit: u64 = table_browse::TABLE_QUERY_TIMEOUT_SECONDS.parse().unwrap_or(AGENT_ROUTE_DEADLINE_SECONDS);
        get_collection_client(collectionname)
            .with_option("max_execution_time", self.remaining_seconds().min(table_limit).to_string())
    }
}

/// One table document that the caller can read, with its overview and its source.
struct TableContext {
    identifier: DocumentIdentifier,
    overview: common::document_tables::TableOverview,
    source: String,
}

/// Resolves the dataset, checks the permission and reads the manifest. The source is the
/// file hash, the reader version and the latest manifest write time over every dataset
/// of the collection that holds the hash, because `table_cells` is keyed by the hash
/// alone. No cell is read.
async fn table_context(
    user: &CurrentUser,
    headers: &HeaderMap,
    collectionname: &str,
    file_hash: &str,
    expected_source: Option<&str>,
    deadline: Deadline,
) -> Result<TableContext, AgentError> {
    let header = requested_collections_header(headers);
    let permitted = permitted_collectionnames(user, &header).await?;
    let collection_dataset = resolve_document_dataset(user, &permitted, collectionname, file_hash, DatasetRow::Table).await?;
    let identifier = DocumentIdentifier { collection_dataset, file_hash: file_hash.to_string() };
    let manifest = table_browse::load_table_manifest(user, &identifier)
        .await
        .map_err(AgentError::from_anyhow)?
        .ok_or_else(|| AgentError::not_found("this document has no browsable table"))?;
    let (updated_at, reader_version): (u32, u16) = deadline
        .table_client(collectionname)
        .query("SELECT toUnixTimestamp(max(updated_at)), max(reader_version) FROM table_documents FINAL WHERE hash = ? AND status = 'ok'")
        .bind(file_hash)
        .fetch_one()
        .await
        .map_err(AgentError::from_clickhouse)?;
    let source = format!(
        "{file_hash}:table:{}:{}",
        reader_version.max(manifest.reader_version),
        updated_at.max(manifest.updated_at)
    );
    verify_expected_source(expected_source, &source)?;
    let overview = table_browse::get_table_overview(user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?
        .ok_or_else(|| AgentError::not_found("this document has no browsable table"))?;
    Ok(TableContext { identifier, overview, source })
}

/// Cuts a cell text over [`MAX_TABLE_CELL_CHARS`] characters with the marker. `field`
/// names the cut unit field, as a JSON pointer.
fn cell_text(text: String, field: &str) -> AgentCellText {
    if text.chars().count() <= MAX_TABLE_CELL_CHARS {
        return AgentCellText::Whole(text);
    }
    let kept: String = text.chars().take(MAX_TABLE_CELL_CHARS).collect();
    let cut = AgentCut { field: field.to_string(), returned_bytes: kept.len() as u64, total_bytes: text.len() as u64 };
    AgentCellText::Cut { text: kept, cut }
}

fn require_sheet(context: &TableContext, sheet: u16) -> Result<&common::document_tables::TableSheet, AgentError> {
    context
        .overview
        .sheets
        .iter()
        .find(|candidate| candidate.sheet_id == sheet)
        .ok_or_else(|| AgentError::not_found(format!("this document has no sheet {sheet}")))
}

fn column_label(context: &TableContext, sheet: u16, column: u32) -> Result<String, AgentError> {
    context
        .overview
        .columns_of(sheet)
        .into_iter()
        .find(|candidate| candidate.column_id == column)
        .map(|candidate| candidate.label())
        .ok_or_else(|| AgentError::not_found(format!("this sheet has no column {column}")))
}

/// Refuses a column id that the sheet does not have with 400 `invalid_argument`. The
/// message gives the lowest and highest column id of the sheet.
fn require_column_id(sheet_column_ids: &[u32], sheet: u16, column: u32) -> Result<(), AgentError> {
    if sheet_column_ids.contains(&column) {
        return Ok(());
    }
    let range = match (sheet_column_ids.iter().min(), sheet_column_ids.iter().max()) {
        (Some(low), Some(high)) => format!("Its column ids are {low} to {high}."),
        _ => "It has no columns.".to_string(),
    };
    Err(AgentError::invalid_argument(format!("sheet {sheet} has no column id {column}. {range}")))
}

fn column_info(column: &common::document_tables::TableColumnInfo) -> AgentTableColumnInfo {
    AgentTableColumnInfo { column_id: column.column_id, name: column.label(), column_type: column.column_type.clone() }
}

// ===================================================================================
// tables/overview
// ===================================================================================

pub async fn tables_overview(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<TablesOverviewRequest>,
) -> AgentResult<TablesOverviewResponse> {
    let deadline = Deadline::start();
    deadline.run(tables_overview_body(&user, &headers, body, deadline)).await.map(Json)
}

async fn tables_overview_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: TablesOverviewRequest,
    deadline: Deadline,
) -> Result<TablesOverviewResponse, AgentError> {
    let offset = match &body.position {
        None => 0,
        Some(AgentPosition::Offset { offset }) => *offset,
        Some(other) => return Err(wrong_position_kind("tables/overview", other, "Offset")),
    };
    let context =
        table_context(user, headers, &body.collectionname, &body.file_hash, body.expected_source.as_deref(), deadline).await?;
    let total = context.overview.sheets.len() as u64;
    if offset > 0 && offset >= total {
        return Err(AgentError::invalid_argument("position is past the last sheet"));
    }
    let sheets: Vec<AgentTableSheet> = context
        .overview
        .sheets
        .iter()
        .skip(offset as usize)
        .take(TABLE_OVERVIEW_SHEETS_PAGE_SIZE)
        .map(|sheet| AgentTableSheet {
            sheet: sheet.sheet_id,
            name: sheet.label(),
            row_count: sheet.row_count,
            column_count: sheet.column_count,
            columns: context.overview.columns_of(sheet.sheet_id).into_iter().map(column_info).collect(),
        })
        .collect();
    let end = offset + sheets.len() as u64;
    let next_position = (end < total).then_some(AgentPosition::Offset { offset: end });
    Ok(TablesOverviewResponse {
        sheets,
        page_info: AgentPageInfo { source: context.source, next_position, total: Some(total), partial: false },
    })
}

// ===================================================================================
// tables/page
// ===================================================================================

fn table_filter_kind(filter: &AgentTableFilter) -> Option<TableFilterKind> {
    if let Some(v) = &filter.contains {
        return Some(TableFilterKind::Contains(v.clone()));
    }
    if let Some(v) = &filter.equals {
        return Some(TableFilterKind::Equals(v.clone()));
    }
    if let Some(v) = &filter.starts_with {
        return Some(TableFilterKind::StartsWith(v.clone()));
    }
    if filter.is_empty == Some(true) {
        return Some(TableFilterKind::IsEmpty);
    }
    if filter.number_min.is_some() || filter.number_max.is_some() {
        return Some(TableFilterKind::NumberRange { min: filter.number_min, max: filter.number_max });
    }
    if filter.date_min.is_some() || filter.date_max.is_some() {
        return Some(TableFilterKind::DateRange { min: filter.date_min.clone(), max: filter.date_max.clone() });
    }
    None
}

fn validate_table_filters(body: &TablesPageRequest) -> Result<(), AgentError> {
    validate_plain_text(&body.search)?;
    if body.sort.as_ref().is_some_and(|sort| sort.direction != "asc" && sort.direction != "desc") {
        return Err(AgentError::invalid_argument("sort direction is invalid"));
    }
    for filter in &body.filters {
        for value in [&filter.contains, &filter.equals, &filter.starts_with] {
            if let Some(value) = value { validate_plain_text(value)?; }
        }
        for date in [&filter.date_min, &filter.date_max] {
            if let Some(date) = date { validate_calendar_date(date)?; }
        }
        if filter.number_min.is_some_and(|value| !value.is_finite())
            || filter.number_max.is_some_and(|value| !value.is_finite())
            || filter.number_min.zip(filter.number_max).is_some_and(|(min, max)| min > max)
            || filter.date_min.as_ref().zip(filter.date_max.as_ref()).is_some_and(|(min, max)| min > max)
        {
            return Err(AgentError::invalid_argument("table filter range is invalid"));
        }
        if table_filter_kind(filter).is_none() {
            return Err(AgentError::invalid_argument("table filter is invalid"));
        }
    }
    Ok(())
}

pub async fn tables_page(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<TablesPageRequest>,
) -> AgentResult<TablesPageResponse> {
    let deadline = Deadline::start();
    deadline.run(tables_page_body(&user, &headers, body, deadline)).await.map(Json)
}

async fn tables_page_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: TablesPageRequest,
    deadline: Deadline,
) -> Result<TablesPageResponse, AgentError> {
    validate_table_filters(&body)?;
    // An unsorted, unfiltered window is arithmetic over the dense `row_id`, so it
    // continues with `Rows`. A sorted, filtered or searched window is the website's
    // `LIMIT … OFFSET` read, so it continues with `Offset`.
    let windowed = body.sort.is_none() && body.filters.is_empty() && body.search.is_empty();
    let row_start = match (&body.position, windowed) {
        (None, _) => body.row_start.unwrap_or(0),
        (Some(AgentPosition::Rows { row_start }), true) => *row_start,
        (Some(AgentPosition::Offset { offset }), false) => *offset,
        (Some(other), true) => return Err(wrong_position_kind("tables/page", other, "Rows")),
        (Some(other), false) => return Err(wrong_position_kind("tables/page", other, "Offset")),
    };
    let context =
        table_context(user, headers, &body.collectionname, &body.file_hash, body.expected_source.as_deref(), deadline).await?;
    let sheet = require_sheet(&context, body.sheet)?;
    let sheet_column_ids: Vec<u32> = context.overview.columns_of(body.sheet).iter().map(|c| c.column_id).collect();
    let requested_columns = body
        .columns
        .iter()
        .copied()
        .chain(body.sort.as_ref().map(|s| s.column))
        .chain(body.filters.iter().map(|f| f.column));
    for column in requested_columns {
        require_column_id(&sheet_column_ids, body.sheet, column)?;
    }
    if row_start > 0 && row_start >= sheet.row_count && windowed {
        return Err(AgentError::invalid_argument("row_start is past the last row of the sheet"));
    }
    let limit = common::document_tables::DEFAULT_TABLE_PAGE_ROWS;
    let view_query = TableViewQuery {
        sheet_id: body.sheet,
        visible_columns: body.columns.clone(),
        sort: body.sort.as_ref().map(|s| CoreTableSort { column_id: s.column, desc: s.direction == "desc" }),
        filters: body
            .filters
            .iter()
            .filter_map(|f| table_filter_kind(f).map(|kind| TableColumnFilter { column_id: f.column, kind }))
            .collect(),
        search: body.search.clone(),
        offset: row_start,
        limit,
    };
    let page = table_browse::get_table_page(user, context.identifier.clone(), view_query)
        .await
        .map_err(AgentError::from_anyhow)?;

    let sheet_columns = context.overview.columns_of(body.sheet);
    let columns: Vec<AgentTableColumnInfo> = page
        .columns
        .iter()
        .filter_map(|id| sheet_columns.iter().find(|c| c.column_id == *id).map(|c| column_info(c)))
        .collect();
    let column_names: HashMap<u32, String> = sheet_columns.iter().map(|c| (c.column_id, c.label())).collect();
    let rows: Vec<AgentTableRow> = page
        .rows
        .into_iter()
        .enumerate()
        .map(|(index, row)| AgentTableRow {
            row_number: row.source_row,
            row_id: row.row_id,
            cells: row
                .cells
                .into_iter()
                .map(|c| {
                    let name = column_names.get(&c.column_id).cloned().unwrap_or_default();
                    let pointer = format!("/rows/{index}/cells/{}", name.replace('~', "~0").replace('/', "~1"));
                    (name, cell_text(c.text, &pointer))
                })
                .collect(),
        })
        .collect();
    let end = row_start + u64::from(page.limit);
    let next_position = (end < page.total_rows).then(|| {
        if windowed { AgentPosition::Rows { row_start: end } } else { AgentPosition::Offset { offset: end } }
    });

    Ok(TablesPageResponse {
        columns,
        rows,
        row_start,
        total_rows: page.total_rows,
        clamps: AgentTableClamps {
            rows_requested: page.clamps.rows_requested,
            rows_applied: page.clamps.rows_applied,
            columns_requested: page.clamps.columns_requested,
            columns_applied: page.clamps.columns_applied,
        },
        page_info: AgentPageInfo { source: context.source, next_position, total: Some(page.total_rows), partial: false },
    })
}

// ===================================================================================
// tables/cell
// ===================================================================================

pub async fn tables_cell(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<TablesCellRequest>,
) -> AgentResult<TablesCellResponse> {
    let deadline = Deadline::start();
    deadline.run(tables_cell_body(&user, &headers, body, deadline)).await.map(Json)
}

async fn tables_cell_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: TablesCellRequest,
    deadline: Deadline,
) -> Result<TablesCellResponse, AgentError> {
    let offset = match &body.position {
        None => 0,
        Some(AgentPosition::Offset { offset }) => *offset,
        Some(other) => return Err(wrong_position_kind("tables/cell", other, "Offset")),
    };
    let context =
        table_context(user, headers, &body.collectionname, &body.file_hash, body.expected_source.as_deref(), deadline).await?;
    require_sheet(&context, body.sheet)?;
    let column = column_label(&context, body.sheet, body.column)?;
    // A full primary-key read of one cell.
    let cells: Vec<(u64, String)> = deadline
        .table_client(&body.collectionname)
        .query("SELECT source_row, cell_text FROM table_cells FINAL WHERE file_hash = ? AND sheet_id = ? AND column_id = ? AND row_id = ? LIMIT 1")
        .bind(&body.file_hash)
        .bind(body.sheet)
        .bind(body.column)
        .bind(body.row)
        .fetch_all()
        .await
        .map_err(AgentError::from_clickhouse)?;
    let Some((row_number, text)) = cells.into_iter().next() else {
        return Err(AgentError::not_found(format!("row {} has no cell in column {}", body.row, body.column)));
    };
    let total = text.chars().count() as u64;
    if offset > 0 && offset >= total {
        return Err(AgentError::invalid_argument("position is past the end of the cell"));
    }
    let slice: String = text.chars().skip(offset as usize).take(TABLE_CELL_PAGE_CHARS).collect();
    let end = offset + slice.chars().count() as u64;
    let next_position = (end < total).then_some(AgentPosition::Offset { offset: end });
    Ok(TablesCellResponse {
        row_number,
        column,
        offset,
        text: slice,
        page_info: AgentPageInfo { source: context.source, next_position, total: Some(total), partial: false },
    })
}

// ===================================================================================
// tables/column_values
// ===================================================================================

pub async fn tables_column_values(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<TablesColumnValuesRequest>,
) -> AgentResult<TablesColumnValuesResponse> {
    let deadline = Deadline::start();
    deadline.run(tables_column_values_body(&user, &headers, body, deadline)).await.map(Json)
}

async fn tables_column_values_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: TablesColumnValuesRequest,
    deadline: Deadline,
) -> Result<TablesColumnValuesResponse, AgentError> {
    validate_plain_text(&body.search)?;
    let after = match &body.position {
        None => None,
        Some(AgentPosition::ValueKey { count, value }) => Some((*count, value.clone())),
        Some(other) => return Err(wrong_position_kind("tables/column_values", other, "ValueKey")),
    };
    let context =
        table_context(user, headers, &body.collectionname, &body.file_hash, body.expected_source.as_deref(), deadline).await?;
    let header_row = require_sheet(&context, body.sheet)?.header_row;
    column_label(&context, body.sheet, body.column)?;
    let floor = if header_row > 0 { format!(" AND row_id > {header_row}") } else { String::new() };
    // The website's order, `n DESC, cell_text ASC`, is total, so the `HAVING` key
    // continues after the last value of the previous page with no `OFFSET`.
    let having = if after.is_some() { " HAVING n < ? OR (n = ? AND cell_text > ?)" } else { "" };
    let limit = common::document_tables::MAX_TABLE_COLUMN_VALUES;
    let mut query = deadline
        .table_client(&body.collectionname)
        .query(&format!(
            "SELECT cell_text, count() AS n FROM table_cells FINAL \
             WHERE file_hash = ? AND sheet_id = ? AND column_id = ?{floor} \
               AND (? = '' OR positionCaseInsensitiveUTF8(cell_text, ?) > 0) \
             GROUP BY cell_text{having} ORDER BY n DESC, cell_text ASC LIMIT {limit}"
        ))
        .bind(&body.file_hash)
        .bind(body.sheet)
        .bind(body.column)
        .bind(&body.search)
        .bind(&body.search);
    if let Some((count, value)) = &after {
        query = query.bind(*count).bind(*count).bind(value);
    }
    let rows: Vec<(String, u64)> = query.fetch_all().await.map_err(AgentError::from_clickhouse)?;
    let next_position = (rows.len() as u32 == limit)
        .then(|| rows.last().map(|(value, count)| AgentPosition::ValueKey { count: *count, value: value.clone() }))
        .flatten();
    let values = rows
        .into_iter()
        .enumerate()
        .map(|(index, (value, count))| AgentColumnValue { value: cell_text(value, &format!("/values/{index}/value")), count })
        .collect();
    Ok(TablesColumnValuesResponse {
        values,
        page_info: AgentPageInfo { source: context.source, next_position, total: None, partial: false },
    })
}

// ===================================================================================
// tables/search_cells
// ===================================================================================

pub async fn tables_search_cells(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<TablesSearchCellsRequest>,
) -> AgentResult<TablesSearchCellsResponse> {
    let deadline = Deadline::start();
    deadline.run(tables_search_cells_body(&user, &headers, body, deadline)).await.map(Json)
}

async fn tables_search_cells_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: TablesSearchCellsRequest,
    deadline: Deadline,
) -> Result<TablesSearchCellsResponse, AgentError> {
    validate_plain_text(&body.query)?;
    if body.query.is_empty() {
        return Err(AgentError::invalid_argument("query is required"));
    }
    let offset = match &body.position {
        None => 0,
        Some(AgentPosition::Offset { offset }) => *offset,
        Some(other) => return Err(wrong_position_kind("tables/search_cells", other, "Offset")),
    };
    let context =
        table_context(user, headers, &body.collectionname, &body.file_hash, body.expected_source.as_deref(), deadline).await?;
    let column_names: HashMap<u32, String> =
        context.overview.columns_of(body.sheet).into_iter().map(|c| (c.column_id, c.label())).collect();
    let dataset = &context.identifier.collection_dataset;

    let hit_count: u64 = deadline
        .table_client(&body.collectionname)
        .query("SELECT count() FROM table_cells FINAL WHERE file_hash = ? AND sheet_id = ? AND positionCaseInsensitiveUTF8(cell_text, ?) > 0 AND row_id NOT IN (SELECT header_row FROM table_sheets FINAL WHERE collection_dataset = ? AND hash = ? AND sheet_id = ? AND header_row > 0)")
        .bind(&body.file_hash)
        .bind(body.sheet)
        .bind(&body.query)
        .bind(dataset)
        .bind(&body.file_hash)
        .bind(body.sheet)
        .fetch_one()
        .await
        .map_err(AgentError::from_clickhouse)?;
    if offset > 0 && offset >= hit_count {
        return Err(AgentError::invalid_argument("position is past the last hit"));
    }
    let rows: Vec<(u64, u64, u32, String)> = deadline
        .table_client(&body.collectionname)
        .query("SELECT source_row, row_id, column_id, cell_text FROM table_cells FINAL WHERE file_hash = ? AND sheet_id = ? AND positionCaseInsensitiveUTF8(cell_text, ?) > 0 AND row_id NOT IN (SELECT header_row FROM table_sheets FINAL WHERE collection_dataset = ? AND hash = ? AND sheet_id = ? AND header_row > 0) ORDER BY row_id, column_id LIMIT ? OFFSET ?")
        .bind(&body.file_hash)
        .bind(body.sheet)
        .bind(&body.query)
        .bind(dataset)
        .bind(&body.file_hash)
        .bind(body.sheet)
        .bind(common::document_tables::MAX_TABLE_PAGE_ROWS)
        .bind(offset)
        .fetch_all()
        .await
        .map_err(AgentError::from_clickhouse)?;
    let hits: Vec<AgentCellHit> = rows
        .into_iter()
        .enumerate()
        .map(|(index, (row_number, row_id, column_id, value))| AgentCellHit {
            row_number,
            row_id,
            column: column_names.get(&column_id).cloned().unwrap_or_default(),
            column_id,
            value: cell_text(value, &format!("/hits/{index}/value")),
        })
        .collect();
    let end = offset + hits.len() as u64;
    let next_position = (end < hit_count).then_some(AgentPosition::Offset { offset: end });

    Ok(TablesSearchCellsResponse {
        hit_count,
        hits,
        page_info: AgentPageInfo { source: context.source, next_position, total: Some(hit_count), partial: false },
    })
}

#[cfg(test)]
mod column_id_tests {
    use super::require_column_id;

    #[test]
    fn an_unknown_column_id_names_the_range() {
        assert!(require_column_id(&[1, 2, 3], 0, 2).is_ok());
        let refused = require_column_id(&[1, 2, 3], 0, 0).err().map(|e| (e.error, e.message));
        assert_eq!(
            refused,
            Some(("invalid_argument", "sheet 0 has no column id 0. Its column ids are 1 to 3.".to_string()))
        );
    }
}
