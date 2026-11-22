//! The workspace files of a conversation: the reports and other text files that the agent
//! writes. The worker is the only writer of versions (`tasks/P_workspace/workflows.py`), and
//! the table comment in migration `00048_chat_workspace.sql` gives the storage rules. This
//! module reads the files for the workspace view and the pinned report of an answer, and
//! writes the tombstones of a deleted conversation.
//!
//! Every function takes the owner, so a caller that checked the session owner reads that
//! owner's rows only. Every read uses FINAL and skips tombstones.

use common::chat_types::{ReportRef, WorkspaceFile, WorkspaceVersion};

use crate::db_utils::clickhouse_utils::get_global_client;

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct FileRow {
    name: String,
    version: u32,
    chars: u64,
    updated_at: String,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct VersionRow {
    name: String,
    version: u32,
    content: String,
    created_at: String,
}

impl From<VersionRow> for WorkspaceVersion {
    fn from(row: VersionRow) -> Self {
        WorkspaceVersion { name: row.name, version: row.version, content: row.content, created_at: row.created_at }
    }
}

/// The files of a conversation, by name, each at its current version.
pub async fn files(username: &str, session_id: &str) -> anyhow::Result<Vec<WorkspaceFile>> {
    let rows = get_global_client()
        .query(
            // The inner alias is `top`, because an alias named `version` would replace the
            // column inside `argMax`.
            "SELECT name, top AS version, chars, updated_at FROM ( \
                SELECT name, max(version) AS top, argMax(lengthUTF8(content), version) AS chars, \
                       toString(argMax(created_at, version)) AS updated_at \
                FROM chat_workspace_files FINAL \
                WHERE username = ? AND session_id = ? AND is_deleted = 0 \
                GROUP BY name) ORDER BY name",
        )
        .bind(username)
        .bind(session_id)
        .fetch_all::<FileRow>()
        .await?;
    Ok(rows
        .into_iter()
        .map(|row| WorkspaceFile {
            name: row.name,
            version: row.version,
            chars: u32::try_from(row.chars).unwrap_or(u32::MAX),
            updated_at: row.updated_at,
        })
        .collect())
}

/// One version of a file, or the current version when `version` is `None`.
pub async fn version(
    username: &str,
    session_id: &str,
    name: &str,
    version: Option<u32>,
) -> anyhow::Result<Option<WorkspaceVersion>> {
    let filter = if version.is_some() { " AND version = ?" } else { "" };
    let mut query = get_global_client()
        .query(&format!(
            "SELECT name, version, content, toString(created_at) AS created_at \
             FROM chat_workspace_files FINAL \
             WHERE username = ? AND session_id = ? AND name = ? AND is_deleted = 0{filter} \
             ORDER BY version DESC LIMIT 1"
        ))
        .bind(username)
        .bind(session_id)
        .bind(name);
    if let Some(version) = version {
        query = query.bind(version);
    }
    Ok(query.fetch_optional::<VersionRow>().await?.map(Into::into))
}

/// The named versions, for the pinned reports of the answer rows of a transcript.
pub async fn versions(
    username: &str,
    session_id: &str,
    refs: &[ReportRef],
) -> anyhow::Result<Vec<WorkspaceVersion>> {
    if refs.is_empty() {
        return Ok(Vec::new());
    }
    let keys: Vec<(String, u32)> = refs.iter().map(|r| (r.name.clone(), r.version)).collect();
    let rows = get_global_client()
        .query(
            "SELECT name, version, content, toString(created_at) AS created_at \
             FROM chat_workspace_files FINAL \
             WHERE username = ? AND session_id = ? AND is_deleted = 0 AND (name, version) IN ? \
             ORDER BY name, version",
        )
        .bind(username)
        .bind(session_id)
        .bind(keys)
        .fetch_all::<VersionRow>()
        .await?;
    Ok(rows.into_iter().map(Into::into).collect())
}

/// Write a tombstone for each version of a deleted conversation's files. A tombstone has
/// the key of its version, `is_deleted = 1` and a later time, so FINAL drops the version.
pub async fn tombstone(username: &str, session_id: &str) -> anyhow::Result<()> {
    get_global_client()
        .query(
            "INSERT INTO chat_workspace_files \
             (username, session_id, name, version, parent_version, run_id, operation_id, \
              operation, content, citations_json, patch_json, created_at, is_deleted) \
             SELECT username, session_id, name, version, parent_version, run_id, operation_id, \
                    operation, '', '', '', now64(3), 1 \
             FROM chat_workspace_files FINAL \
             WHERE username = ? AND session_id = ? AND is_deleted = 0",
        )
        .bind(username)
        .bind(session_id)
        .execute()
        .await?;
    Ok(())
}

#[derive(clickhouse::Row, serde::Deserialize)]
pub struct CaptureRow {
    pub artifact_id: String,
    pub kind: String,
    pub tool_name: String,
    pub title: String,
    pub detail: String,
}

pub fn capture_group(kind: &str, tool: &str) -> &'static str {
    match (kind, tool) {
        ("web_page_text", _) => "sources/web",
        ("workspace_result", "read_documents" | "doc_search_text" | "doc_metadata" | "doc_email"
            | "doc_diff_sources" | "pdf_search" | "list_document_entities") => "sources/collections",
        ("workspace_result", tool) if tool.starts_with("browser_") => "sources/browser",
        _ => "results",
    }
}

pub async fn captures(
    username: &str, session_id: &str, collections: &[String], after: &str, sources: bool,
) -> anyhow::Result<Vec<CaptureRow>> {
    let sources_filter = "kind = 'web_page_text' OR (kind = 'workspace_result' AND         (startsWith(tool_name, 'browser_') OR tool_name IN ('read_documents', 'doc_search_text',         'doc_metadata', 'doc_email', 'doc_diff_sources', 'pdf_search', 'list_document_entities')))";
    let filter = if sources { sources_filter.to_string() } else { format!("NOT ({sources_filter})") };
    Ok(get_global_client().query(&format!(
        "SELECT artifact_id, kind, tool_name, title, detail FROM chat_artifacts FINAL          WHERE username = ? AND session_id = ? AND artifact_id > ? AND is_deleted = 0          AND status = 'ok' AND kind IN ('workspace_result', 'web_page_text')          AND hasAll(?, JSONExtract(detail, 'collections', 'Array(String)'))          AND ({filter}) ORDER BY artifact_id LIMIT 26"
    ))
    .bind(username)
    .bind(session_id)
    .bind(after)
    .bind(collections)
    .fetch_all::<CaptureRow>().await?)
}
