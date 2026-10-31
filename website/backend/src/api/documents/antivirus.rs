//! Antivirus verdicts and the download policy for infected documents.
//!
//! Every byte route checks the read permission first, then this policy.
//!
//! | Route | Infected document |
//! |---|---|
//! | `/_download_document` (original) | 403 without `view=1`. With `view=1` the bytes are served inline for the viewer. |
//! | `/_download_ocr_pdf` (searchable PDF) | 403 without `view=1`. |
//! | `/_download_pdf/{kind}` (complete original, preview or searchable PDF) | 403 without `view=1`. |
//! | `/_download_pdf_part` (one part of a large PDF) | Served. The viewer alone reads it. |
//! | `/_image_preview` (JPEG preview) | Served. It is a rendered JPEG image of the file. |
//!
//! Bytes that the viewer may read stay retrievable by any reader of the dataset. The
//! policy refuses the ordinary downloads and does not prevent saving the viewer bytes.

use common::antivirus::{refused_download_message, VirusScanStatus};

use crate::db_utils::clickhouse_utils::get_client_for_dataset;

#[derive(Debug, clickhouse::Row, serde::Deserialize)]
struct AttemptRow {
    attempt_status: String,
    verdict: String,
    signature: String,
    engine_version: String,
    database_version: String,
    scanned_at: String,
}

/// The antivirus state of one document. The caller has checked the read permission.
/// A document without an attempt row answers `not_scanned`. A failed query is an error.
pub async fn scan_status(collection_dataset: &str, file_hash: &str) -> anyhow::Result<VirusScanStatus> {
    let client = get_client_for_dataset(collection_dataset).await?;
    let rows: Vec<AttemptRow> = client
        .query(
            "SELECT attempt_status, verdict, signature, engine_version, database_version, \
                    formatDateTime(scanned_at, '%Y-%m-%d %H:%i:%S') AS scanned_at \
             FROM virus_scan_results WHERE hash = ? \
             ORDER BY (attempt_status = 'completed') DESC, result_seq DESC LIMIT 1",
        )
        .bind(file_hash)
        .fetch_all()
        .await?;
    Ok(match rows.into_iter().next() {
        None => VirusScanStatus { state: "not_scanned".into(), ..Default::default() },
        Some(row) => VirusScanStatus {
            state: if row.attempt_status == "completed" { row.verdict } else { row.attempt_status },
            signature: row.signature,
            engine_version: row.engine_version,
            database_version: row.database_version,
            scanned_at: row.scanned_at,
        },
    })
}

/// Refuse an ordinary download of an infected document. `view` is the viewer exception.
/// The error message holds the `forbidden` marker, which the routes answer with 403.
pub async fn refuse_infected_download(collection_dataset: &str, file_hash: &str, view: bool) -> anyhow::Result<()> {
    if view {
        return Ok(());
    }
    let status = scan_status(collection_dataset, file_hash).await?;
    if status.is_infected() {
        anyhow::bail!(refused_download_message(&status.signature));
    }
    Ok(())
}

/// The query of a byte route. `view=1` is the request of the in-browser viewer.
#[derive(Debug, Default, serde::Deserialize)]
pub struct ViewQuery {
    #[serde(default)]
    pub view: Option<String>,
}

impl ViewQuery {
    pub fn is_view(&self) -> bool {
        self.view.as_deref() == Some("1")
    }
}
