//! Reads of the global `operation_failures` table for `/admin/failures`.
//!
//! Grouping is done in the query, by the stored `signature` column, so a count is over
//! the whole match and not over one page. Every filter value is bound. `node_index` is
//! decoded as UInt32. `captured_at` is selected with `toInt64(toUnixTimestamp(...))`
//! because RowBinary will otherwise eat four bytes too many.

use common::current_user::CurrentUser;
use common::failure_types::{
    FailureGroupRow, FailureInstanceRow, FailureListFilter, FailureListSort, FailureNode,
    FailureTree, FailuresPage,
};
use time::format_description::well_known::Rfc3339;

use crate::api::admin::operation_temporal_url;
use crate::auth::guard;
use crate::db_utils::clickhouse_utils::get_global_client;

/// Page responses cap each stack at this many characters. The stored row is unchanged.
const STACK_TRACE_PAGE_CAP: usize = 8192;

/// ClickHouse `toUnixTimestamp` is UInt32. An open upper bound has to fit that type.
const UNIX_TS_MAX: u32 = u32::MAX;

const FILTER_WHERE: &str = "\
    (? = '' OR collectionname = ?) \
    AND (? = '' OR collection_dataset = ?) \
    AND (? = '' OR task_name = ?) \
    AND (? = '' OR error_class = ?) \
    AND toUnixTimestamp(captured_at) >= ? \
    AND toUnixTimestamp(captured_at) <= ? \
    AND (? = '' OR op_id IN (SELECT op_id FROM operations FINAL WHERE kind = ?))";

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct GroupDbRow {
    signature: String,
    failure_count: u64,
    operation_count: u64,
    group_error_class: String,
    group_error_type: String,
    group_task_name: String,
    group_collectionname: String,
    group_collection_dataset: String,
    last_seen: i64,
    sample_message: String,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct InstanceDbRow {
    op_id: String,
    node_index: u32,
    message: String,
    task_name: String,
    collectionname: String,
    collection_dataset: String,
    captured_at: i64,
    error_class: String,
    error_type: String,
    source: String,
    stage: String,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct NodeDbRow {
    op_id: String,
    node_index: u32,
    depth: u16,
    parent_index: i32,
    error_class: String,
    error_type: String,
    message: String,
    stack_trace: String,
    signature: String,
    task_name: String,
    workflow_id: String,
    run_id: String,
    activity_id: String,
    attempt: u16,
    collectionname: String,
    collection_dataset: String,
    stage: String,
    details_json: String,
    source: String,
    nodes_dropped: u32,
    captured_at: i64,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct OperationMetaRow {
    kind: String,
    state: String,
    error: String,
}

fn format_ts(unix_seconds: i64) -> String {
    time::OffsetDateTime::from_unix_timestamp(unix_seconds)
        .ok()
        .and_then(|dt| dt.format(&Rfc3339).ok())
        .unwrap_or_else(|| unix_seconds.to_string())
}

fn parse_bound_ts(value: &str, empty: u32) -> u32 {
    if value.trim().is_empty() {
        return empty;
    }
    time::OffsetDateTime::parse(value, &Rfc3339)
        .ok()
        .map(|dt| dt.unix_timestamp().clamp(0, UNIX_TS_MAX as i64) as u32)
        .or_else(|| parse_date_only(value))
        .unwrap_or(empty)
}

fn parse_date_only(value: &str) -> Option<u32> {
    let date = time::Date::parse(
        value,
        &time::format_description::parse("[year]-[month]-[day]").ok()?,
    )
    .ok()?;
    let dt = date.with_time(time::Time::MIDNIGHT).assume_utc();
    Some(dt.unix_timestamp().clamp(0, UNIX_TS_MAX as i64) as u32)
}

fn captured_from_ts(filter: &FailureListFilter) -> u32 {
    parse_bound_ts(&filter.captured_from, 0)
}

fn captured_to_ts(filter: &FailureListFilter) -> u32 {
    let parsed = parse_bound_ts(&filter.captured_to, UNIX_TS_MAX);
    if filter.captured_to.trim().len() == 10 && parsed != UNIX_TS_MAX {
        parsed.saturating_add(86_399)
    } else {
        parsed
    }
}

fn sort_sql(sort: &FailureListSort) -> (&'static str, &'static str) {
    let column = match sort.column.as_str() {
        "failure_count" => "failure_count",
        "operation_count" => "operation_count",
        "signature" => "signature",
        "error_class" => "group_error_class",
        "task_name" => "group_task_name",
        "collectionname" => "group_collectionname",
        _ => "last_seen",
    };
    let direction = if sort.descending { "DESC" } else { "ASC" };
    (column, direction)
}

fn bind_filters(
    query: clickhouse::query::Query,
    filter: &FailureListFilter,
) -> clickhouse::query::Query {
    query
        .bind(&filter.collectionname)
        .bind(&filter.collectionname)
        .bind(&filter.collection_dataset)
        .bind(&filter.collection_dataset)
        .bind(&filter.task_name)
        .bind(&filter.task_name)
        .bind(&filter.error_class)
        .bind(&filter.error_class)
        .bind(captured_from_ts(filter))
        .bind(captured_to_ts(filter))
        .bind(&filter.operation_kind)
        .bind(&filter.operation_kind)
}

fn cap_stack(stack: &str) -> (String, u32) {
    let original_len = stack.chars().count() as u32;
    if stack.chars().count() <= STACK_TRACE_PAGE_CAP {
        (stack.to_string(), original_len)
    } else {
        (
            stack.chars().take(STACK_TRACE_PAGE_CAP).collect(),
            original_len,
        )
    }
}

fn datasets_mount_path() -> String {
    std::env::var("DATASETS_MOUNT_PATH").unwrap_or_else(|_| "/testdata".to_string())
}

fn hash_basename(path: &str) -> String {
    let base = path.rsplit('/').next().unwrap_or(path);
    let digest = sha256::digest(base.as_bytes());
    format!("dataset-file:{}", &digest[..16])
}

fn replace_mount_paths(text: &str, mount: &str) -> String {
    let mount = mount.trim_end_matches('/');
    if mount.is_empty() {
        return text.to_string();
    }
    let mut out = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(pos) = rest.find(mount) {
        out.push_str(&rest[..pos]);
        let after_mount = &rest[pos + mount.len()..];
        let is_path = after_mount.is_empty() || after_mount.starts_with('/');
        let ok_before = pos == 0
            || rest[..pos]
                .chars()
                .last()
                .is_some_and(|c| c.is_whitespace() || matches!(c, '"' | '\'' | '=' | ':' | '(' | '[' | '{'));
        if is_path && ok_before {
            let path_end = after_mount
                .find(|c: char| {
                    c.is_whitespace() || matches!(c, '"' | '\'' | ',' | ')' | ']' | '}' | ';')
                })
                .unwrap_or(after_mount.len());
            let path = format!("{}{}", mount, &after_mount[..path_end]);
            out.push_str(&hash_basename(&path));
            rest = &after_mount[path_end..];
        } else {
            out.push_str(mount);
            rest = after_mount;
        }
    }
    out.push_str(rest);
    out
}

fn elide_if_long(s: &str) -> String {
    let chars = s.chars().count();
    if chars > 512 {
        format!("[elided {chars} characters]")
    } else {
        s.to_string()
    }
}

fn scrub_value(s: &str, mount: &str) -> String {
    elide_if_long(&replace_mount_paths(s, mount))
}

fn scrub_json(value: &mut serde_json::Value, mount: &str) {
    match value {
        serde_json::Value::String(s) => *s = scrub_value(s, mount),
        serde_json::Value::Array(items) => {
            for item in items {
                scrub_json(item, mount);
            }
        }
        serde_json::Value::Object(map) => {
            for item in map.values_mut() {
                scrub_json(item, mount);
            }
        }
        _ => {}
    }
}

fn node_json(row: &NodeDbRow) -> serde_json::Value {
    serde_json::json!({
        "op_id": row.op_id,
        "node_index": row.node_index,
        "depth": row.depth,
        "parent_index": row.parent_index,
        "error_class": row.error_class,
        "error_type": row.error_type,
        "message": row.message,
        "stack_trace": row.stack_trace,
        "signature": row.signature,
        "task_name": row.task_name,
        "workflow_id": row.workflow_id,
        "run_id": row.run_id,
        "activity_id": row.activity_id,
        "attempt": row.attempt,
        "collectionname": row.collectionname,
        "collection_dataset": row.collection_dataset,
        "stage": row.stage,
        "details_json": row.details_json,
        "source": row.source,
        "nodes_dropped": row.nodes_dropped,
        "captured_at": format_ts(row.captured_at),
    })
}

fn scrubbed_copy(rows: &[NodeDbRow]) -> String {
    let mount = datasets_mount_path();
    let mut value = serde_json::Value::Array(rows.iter().map(node_json).collect());
    scrub_json(&mut value, &mount);
    serde_json::to_string_pretty(&value).unwrap_or_else(|_| "[]".to_string())
}

fn to_group(row: GroupDbRow) -> FailureGroupRow {
    FailureGroupRow {
        signature: row.signature,
        failure_count: row.failure_count,
        operation_count: row.operation_count,
        error_class: row.group_error_class,
        error_type: row.group_error_type,
        task_name: row.group_task_name,
        collectionname: row.group_collectionname,
        collection_dataset: row.group_collection_dataset,
        last_seen: format_ts(row.last_seen),
        sample_message: row.sample_message,
    }
}

fn to_instance(row: InstanceDbRow) -> FailureInstanceRow {
    FailureInstanceRow {
        op_id: row.op_id,
        node_index: row.node_index,
        message: row.message,
        task_name: row.task_name,
        collectionname: row.collectionname,
        collection_dataset: row.collection_dataset,
        captured_at: format_ts(row.captured_at),
        error_class: row.error_class,
        error_type: row.error_type,
        source: row.source,
        stage: row.stage,
    }
}

fn to_node(row: NodeDbRow) -> FailureNode {
    let (stack_trace, stack_trace_original_len) = cap_stack(&row.stack_trace);
    FailureNode {
        op_id: row.op_id,
        node_index: row.node_index,
        depth: row.depth,
        parent_index: row.parent_index,
        error_class: row.error_class,
        error_type: row.error_type,
        message: row.message,
        stack_trace,
        stack_trace_original_len,
        signature: row.signature,
        task_name: row.task_name,
        workflow_id: row.workflow_id,
        run_id: row.run_id,
        activity_id: row.activity_id,
        attempt: row.attempt,
        collectionname: row.collectionname,
        collection_dataset: row.collection_dataset,
        stage: row.stage,
        details_json: row.details_json,
        source: row.source,
        nodes_dropped: row.nodes_dropped,
        captured_at: format_ts(row.captured_at),
    }
}

async fn distinct_strings(sql: &str) -> anyhow::Result<Vec<String>> {
    Ok(get_global_client().query(sql).fetch_all::<String>().await?)
}

/// Grouped failure list, with filter, sort and `limit`/`offset` pagination.
pub async fn admin_list_operation_failures(
    user: &CurrentUser,
    filter: FailureListFilter,
    sort: FailureListSort,
    limit: u32,
    offset: u32,
) -> anyhow::Result<FailuresPage> {
    guard::require_admin(user)?;
    let limit = limit.clamp(1, 200);
    let (sort_col, sort_dir) = sort_sql(&sort);
    let sql = format!(
        "SELECT signature, \
                count() AS failure_count, \
                uniqExact(op_id) AS operation_count, \
                any(error_class) AS group_error_class, \
                any(error_type) AS group_error_type, \
                any(task_name) AS group_task_name, \
                any(collectionname) AS group_collectionname, \
                any(collection_dataset) AS group_collection_dataset, \
                toInt64(toUnixTimestamp(max(captured_at))) AS last_seen, \
                any(message) AS sample_message \
         FROM operation_failures \
         WHERE {FILTER_WHERE} \
         GROUP BY signature \
         ORDER BY {sort_col} {sort_dir}, signature ASC \
         LIMIT ? OFFSET ?"
    );
    let raw = bind_filters(get_global_client().query(&sql), &filter)
        .bind(limit + 1)
        .bind(offset)
        .fetch_all::<GroupDbRow>()
        .await?;
    let has_more = raw.len() as u32 > limit;
    let groups: Vec<FailureGroupRow> = raw
        .into_iter()
        .take(limit as usize)
        .map(to_group)
        .collect();

    let collections = distinct_strings(
        "SELECT DISTINCT collectionname FROM operation_failures \
         WHERE collectionname != '' ORDER BY collectionname",
    )
    .await?;
    let datasets = distinct_strings(
        "SELECT DISTINCT collection_dataset FROM operation_failures \
         WHERE collection_dataset != '' ORDER BY collection_dataset",
    )
    .await?;
    let task_names = distinct_strings(
        "SELECT DISTINCT task_name FROM operation_failures \
         WHERE task_name != '' ORDER BY task_name",
    )
    .await?;
    let error_classes = distinct_strings(
        "SELECT DISTINCT error_class FROM operation_failures \
         WHERE error_class != '' ORDER BY error_class",
    )
    .await?;
    let operation_kinds = distinct_strings(
        "SELECT DISTINCT kind FROM operations FINAL \
         WHERE op_id IN (SELECT op_id FROM operation_failures) AND kind != '' \
         ORDER BY kind",
    )
    .await?;

    Ok(FailuresPage {
        groups,
        has_more,
        collections,
        datasets,
        task_names,
        error_classes,
        operation_kinds,
    })
}

/// Individual nodes under one signature, same filters as the grouped list.
pub async fn admin_list_failure_instances(
    user: &CurrentUser,
    filter: FailureListFilter,
    signature: String,
    limit: u32,
    offset: u32,
) -> anyhow::Result<Vec<FailureInstanceRow>> {
    guard::require_admin(user)?;
    let limit = limit.clamp(1, 200);
    let sql = format!(
        "SELECT op_id, node_index, message, task_name, collectionname, collection_dataset, \
                toInt64(toUnixTimestamp(captured_at)) AS captured_at, \
                error_class, error_type, source, stage \
         FROM operation_failures \
         WHERE signature = ? AND {FILTER_WHERE} \
         ORDER BY captured_at DESC, op_id ASC, node_index ASC \
         LIMIT ? OFFSET ?"
    );
    let rows = bind_filters(
        get_global_client().query(&sql).bind(&signature),
        &filter,
    )
    .bind(limit)
    .bind(offset)
    .fetch_all::<InstanceDbRow>()
    .await?;
    Ok(rows.into_iter().map(to_instance).collect())
}

/// The whole tree for one `op_id`, every root included.
pub async fn admin_get_failure_tree(
    user: &CurrentUser,
    op_id: String,
) -> anyhow::Result<FailureTree> {
    guard::require_admin(user)?;
    let client = get_global_client();
    let raw = client
        .query(
            "SELECT op_id, node_index, depth, parent_index, error_class, error_type, message, \
                    stack_trace, signature, task_name, workflow_id, run_id, activity_id, attempt, \
                    collectionname, collection_dataset, stage, details_json, source, nodes_dropped, \
                    toInt64(toUnixTimestamp(captured_at)) AS captured_at \
             FROM operation_failures \
             WHERE op_id = ? \
             ORDER BY node_index",
        )
        .bind(&op_id)
        .fetch_all::<NodeDbRow>()
        .await?;

    let mut meta = client
        .query("SELECT kind, state, error FROM operations FINAL WHERE op_id = ? LIMIT 1")
        .bind(&op_id)
        .fetch_all::<OperationMetaRow>()
        .await?;
    let meta = meta.pop();
    let capture_expired = raw.is_empty() && meta.is_some();
    let truncated = raw.iter().any(|r| r.nodes_dropped > 0);
    let scrubbed = scrubbed_copy(&raw);
    let nodes = raw.into_iter().map(to_node).collect();
    Ok(FailureTree {
        op_id: op_id.clone(),
        nodes,
        truncated,
        capture_expired,
        temporal_url: operation_temporal_url(&op_id),
        operation_kind: meta.as_ref().map(|m| m.kind.clone()).unwrap_or_default(),
        operation_state: meta.as_ref().map(|m| m.state.clone()).unwrap_or_default(),
        operation_error: meta.as_ref().map(|m| m.error.clone()).unwrap_or_default(),
        scrubbed_copy: scrubbed,
    })
}

pub(crate) async fn op_ids_with_failure_trees(
    op_ids: &[String],
) -> anyhow::Result<std::collections::HashSet<String>> {
    if op_ids.is_empty() {
        return Ok(std::collections::HashSet::new());
    }
    let rows = get_global_client()
        .query("SELECT DISTINCT op_id FROM operation_failures WHERE has(?, op_id)")
        .bind(op_ids.to_vec())
        .fetch_all::<String>()
        .await?;
    Ok(rows.into_iter().collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scrub_replaces_dataset_mount_path_with_basename_hash() {
        let mount = "/testdata";
        let input = "failed on /testdata/failcap_tiny3/secret.doc during parse";
        let out = replace_mount_paths(input, mount);
        assert!(!out.contains("secret.doc"), "{out}");
        assert!(!out.contains("failcap_tiny3"), "{out}");
        let expected = &sha256::digest("secret.doc".as_bytes())[..16];
        assert!(
            out.contains(&format!("dataset-file:{expected}")),
            "{out}"
        );
        assert!(out.contains("failed on "), "{out}");
        assert!(out.contains(" during parse"), "{out}");
    }

    #[test]
    fn scrub_elides_a_value_over_512_characters() {
        let long = "a".repeat(513);
        assert_eq!(elide_if_long(&long), "[elided 513 characters]");
    }

    #[test]
    fn scrub_keeps_a_value_of_512_characters() {
        let s = "b".repeat(512);
        assert_eq!(elide_if_long(&s), s);
    }

    #[test]
    fn sort_sql_allowlists_columns() {
        let sort = FailureListSort {
            column: "failure_count".into(),
            descending: false,
        };
        assert_eq!(sort_sql(&sort), ("failure_count", "ASC"));
        let unknown = FailureListSort {
            column: "drop table".into(),
            descending: true,
        };
        assert_eq!(sort_sql(&unknown), ("last_seen", "DESC"));
    }
}
