//! Per-dataset OCR settings, the `change_ocr_languages` apply job, and dataset creation.
//!
//! Three things the admin UI could not do before this module: see what OCR variants a
//! dataset actually holds, change the languages that produce them, and create a dataset
//! at all (that was a CLI-only operation).
//!
//! Two rules run through all of it:
//!
//! * **One language change per dataset, refused by the operations lock.** The disabled
//!   button on the form is courtesy. Two admins in two browsers are stopped by the
//!   non-terminal `operations` row, which is the same row the status strip polls, so
//!   what refuses the second admin is exactly what the first one can see.
//! * **The creation form never takes a path.** It takes a folder *name*, which is
//!   validated against the listing of `DATASETS_MOUNT_PATH` and joined server-side. A
//!   free-text path in a browser form is a way to point the ingest walker at any
//!   directory the container can see.

use std::time::Duration;

use common::admin_types::{
    DatasetFolderOption, DatasetOcrPanel, DatasetOperationStatus, DatasetPdfVariant,
    DatasetTextVariant,
};
use common::current_user::CurrentUser;
use time::format_description::well_known::Rfc3339;

use crate::api::admin::operations;
use crate::auth::guard;
use crate::db_utils::clickhouse_utils::{
    collection_db_name, get_collection_client, get_global_client,
};

/// Setting keys, mirroring `tasks/dataset_config.py`. The duplication is the same
/// deliberate one as `extracted_by`: a key that is simultaneously a storage key and a
/// form field must not be spelled by only one runtime.
const KEY_TESSERACT_LANGUAGES: &str = "ocr.tesseract.languages";
const KEY_EASYOCR_LANGUAGES: &str = "ocr.easyocr.languages";
/// Collection-level defaults a newly created dataset inherits. A dataset's own row always
/// wins; these only fill in what was never set.
const KEY_DEFAULT_TESSERACT_LANGUAGES: &str = "ocr.default.tesseract.languages";
const KEY_DEFAULT_EASYOCR_LANGUAGES: &str = "ocr.default.easyocr.languages";

/// The operation kind this module dispatches. Registered in `operations.rs` beside every
/// other kind, which is what makes the lock and the destructive flag one rule.
const OPERATION_KIND_OCR_LANGUAGES: &str = "change_ocr_languages";

fn format_ts(unix_seconds: i64) -> String {
    if unix_seconds <= 0 {
        return String::new();
    }
    time::OffsetDateTime::from_unix_timestamp(unix_seconds)
        .ok()
        .and_then(|dt| dt.format(&Rfc3339).ok())
        .unwrap_or_else(|| unix_seconds.to_string())
}

fn env_url(name: &str) -> String {
    std::env::var(name).unwrap_or_default().trim().to_string()
}

/// The dataset's `collectionname`, or an error naming the dataset rather than the query.
async fn collection_of(collection_dataset: &str) -> anyhow::Result<String> {
    crate::db_utils::collectionname_of_dataset(collection_dataset).await
}

#[derive(Debug, clickhouse::Row, serde::Deserialize)]
struct OperationSummaryRow {
    op_id: String,
    kind: String,
    state: String,
    detail: String,
    error: String,
    started_at: i64,
    finished_at: i64,
    /// Aliased rather than selected as `updated_at`: `clickhouse::Row` binds by column
    /// name, and an alias carrying the column's own name shadows the column it derives
    /// from.
    last_update: i64,
}

/// The newest operation touching a dataset, whatever its kind or state.
///
/// One progress mechanism, not two: this is the same `operations` row the admin
/// operations log renders, read here so the dataset page shows the run a person started
/// from it without a per-dataset job table of its own.
pub async fn latest_operation(
    collection_dataset: &str,
) -> anyhow::Result<Option<DatasetOperationStatus>> {
    let client = get_global_client();
    let rows = client
        .query(
            "SELECT op_id, \
                    kind, \
                    state, \
                    detail, \
                    error, \
                    toInt64(toUnixTimestamp(started_at)) AS started_at, \
                    toInt64(toUnixTimestamp(finished_at)) AS finished_at, \
                    toInt64(toUnixTimestamp(updated_at)) AS last_update \
             FROM operations FINAL \
             WHERE collection_dataset = ? \
             ORDER BY started_at DESC, op_id DESC LIMIT 1",
        )
        .bind(collection_dataset)
        .fetch_all::<OperationSummaryRow>()
        .await?;

    let Some(row) = rows.into_iter().next() else {
        return Ok(None);
    };
    let now = time::OffsetDateTime::now_utc().unix_timestamp();
    let running = matches!(row.state.as_str(), "pending" | "running");
    Ok(Some(DatasetOperationStatus {
        op_id: row.op_id,
        kind: row.kind,
        stale_seconds: if running {
            (now - row.last_update).max(0) as u64
        } else {
            0
        },
        state: row.state,
        detail: row.detail,
        error: row.error,
        started_at: format_ts(row.started_at),
        finished_at: format_ts(row.finished_at),
    }))
}

async fn read_setting(collection_dataset: &str, key: &str) -> anyhow::Result<Option<String>> {
    let client = get_global_client();
    let rows = client
        .query(
            "SELECT argMax(value, updated_at) FROM dataset_settings \
             WHERE collection_dataset = ? AND key = ? \
             GROUP BY key HAVING argMax(is_deleted, updated_at) = 0",
        )
        .bind(collection_dataset)
        .bind(key)
        .fetch_all::<String>()
        .await?;
    Ok(rows.into_iter().next())
}

async fn write_setting(collection_dataset: &str, key: &str, value: &str) -> anyhow::Result<()> {
    #[derive(clickhouse::Row, serde::Serialize)]
    struct SettingRow<'a> {
        collection_dataset: &'a str,
        key: &'a str,
        value: &'a str,
        #[serde(with = "clickhouse::serde::time::datetime")]
        updated_at: time::OffsetDateTime,
        is_deleted: u8,
    }
    let client = get_global_client();
    let mut insert = client.insert::<SettingRow>("dataset_settings").await?;
    insert
        .write(&SettingRow {
            collection_dataset,
            key,
            value,
            updated_at: time::OffsetDateTime::now_utc(),
            is_deleted: 0,
        })
        .await?;
    insert.end().await?;
    Ok(())
}

/// The languages the Tesseract image can actually serve.
///
/// Read from the tier's `/health`, never from configuration: `languages_available` comes
/// from `tesseract --list-langs`, and a dataset configured for a language whose
/// traineddata is not installed fails per file, hours after the form was submitted. An
/// unreachable tier returns an empty list, and the form says so rather than offering one
/// it cannot stand behind.
async fn tesseract_languages_available() -> Vec<String> {
    let url = env_url("OCR_TESSERACT_URL");
    if url.is_empty() {
        return Vec::new();
    }
    let health = format!("{}/health", url.trim_end_matches("/ocr"));
    let Ok(client) = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(2))
        .timeout(Duration::from_secs(5))
        .build()
    else {
        return Vec::new();
    };
    let Ok(response) = client.get(&health).send().await else {
        return Vec::new();
    };
    let Ok(body) = response.json::<serde_json::Value>().await else {
        return Vec::new();
    };
    body.get("languages_available")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

pub async fn admin_get_dataset_ocr(
    user: &CurrentUser,
    collection_dataset: String,
) -> anyhow::Result<DatasetOcrPanel> {
    guard::require_admin(user)?;
    let collectionname = collection_of(&collection_dataset).await?;
    let client = get_collection_client(&collectionname);

    let text_variants: Vec<DatasetTextVariant> = client
        .query(
            "SELECT extracted_by, count() FROM text_content FINAL \
             WHERE collection_dataset = ? GROUP BY extracted_by ORDER BY extracted_by",
        )
        .bind(&collection_dataset)
        .fetch_all::<(String, u64)>()
        .await?
        .into_iter()
        .map(|(extracted_by, page_count)| DatasetTextVariant {
            extracted_by,
            page_count,
        })
        .collect();

    let pdf_variants: Vec<DatasetPdfVariant> = client
        .query(
            "SELECT engine, languages, count(), sum(size) FROM ( \
                 SELECT engine, languages, pdf_hash, \
                        argMax(size_bytes, updated_at) AS size \
                 FROM pdf_ocr_results \
                 WHERE collection_dataset = ? \
                 GROUP BY engine, languages, pdf_hash \
                 HAVING argMax(is_deleted, updated_at) = 0 \
             ) GROUP BY engine, languages ORDER BY engine, languages",
        )
        .bind(&collection_dataset)
        .fetch_all::<(String, String, u64, u64)>()
        .await?
        .into_iter()
        .map(
            |(engine, languages, pdf_count, total_bytes)| DatasetPdfVariant {
                engine,
                languages,
                pdf_count,
                total_bytes,
            },
        )
        .collect();

    // A dataset with no row of its own inherits the collection default, and a collection
    // with no default falls back to the stack-wide one the worker was deployed with. The
    // form shows the value that is actually in force, never an empty box that reads as
    // "no OCR at all".
    let tesseract_languages = match read_setting(&collection_dataset, KEY_TESSERACT_LANGUAGES).await? {
        Some(v) => v,
        None => read_setting(&collectionname, KEY_DEFAULT_TESSERACT_LANGUAGES)
            .await?
            .unwrap_or_else(|| "eng".to_string()),
    };
    let easyocr_languages = match read_setting(&collection_dataset, KEY_EASYOCR_LANGUAGES).await? {
        Some(v) => v,
        None => read_setting(&collectionname, KEY_DEFAULT_EASYOCR_LANGUAGES)
            .await?
            .unwrap_or_else(|| "en".to_string()),
    };

    Ok(DatasetOcrPanel {
        collection_dataset: collection_dataset.clone(),
        collectionname,
        tesseract_languages,
        easyocr_languages,
        tesseract_available: tesseract_languages_available().await,
        easyocr_configured: !env_url("OCR_EASYOCR_URL").is_empty(),
        ocr_pdf_configured: !env_url("OCR_PDF_URL").is_empty(),
        text_variants,
        pdf_variants,
        operation: latest_operation(&collection_dataset).await?,
    })
}

/// Polled by the operation strip on both the dataset page and the collection processing
/// page.
pub async fn admin_get_dataset_operation(
    user: &CurrentUser,
    collection_dataset: String,
) -> anyhow::Result<Option<DatasetOperationStatus>> {
    guard::require_admin(user)?;
    latest_operation(&collection_dataset).await
}

/// A language string as the pipeline stores it: `+`-joined, deduplicated, order kept.
///
/// Order is preserved rather than sorted because Tesseract treats the first language as
/// the primary one: `eng+ron` and `ron+eng` are genuinely different requests and
/// therefore genuinely different variants. Mirrors `join_languages` in
/// `tasks/text_sources.py`.
pub fn normalise_languages(raw: &str) -> String {
    let mut seen: Vec<&str> = Vec::new();
    for code in raw.split('+') {
        let code = code.trim();
        if !code.is_empty() && !seen.contains(&code) {
            seen.push(code);
        }
    }
    seen.join("+")
}

/// Reject anything that is not a plain language code before it reaches a storage key.
///
/// `extracted_by` is built from this string and becomes a ClickHouse value, a Manticore
/// value and part of a blob-store object key. Restricting it to `[a-z_]` costs nothing
/// (Tesseract's own codes are `eng`, `ron`, `chi_sim`), and removes a whole class of
/// question about where the value ends up.
fn validate_languages(raw: &str, field: &str) -> anyhow::Result<String> {
    let joined = normalise_languages(raw);
    if joined.is_empty() {
        anyhow::bail!("{field} must list at least one language");
    }
    if joined.len() > 200 {
        anyhow::bail!("{field} is too long");
    }
    for code in joined.split('+') {
        if !code
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
        {
            anyhow::bail!("{field}: {code:?} is not a language code (lowercase letters, digits and underscore only)");
        }
    }
    Ok(joined)
}

/// Dispatch the `change_ocr_languages` operation for one dataset.
///
/// Returns the operation id, which the form uses to start polling immediately rather
/// than waiting for the first refresh to notice the row. The languages travel in the
/// operation's `detail`, so the log records what was asked for and a re-run of that row
/// asks for the same thing.
pub async fn admin_apply_ocr_languages(
    user: &CurrentUser,
    collection_dataset: String,
    tesseract_languages: String,
    easyocr_languages: String,
) -> anyhow::Result<String> {
    guard::require_admin(user)?;
    let collectionname = collection_of(&collection_dataset).await?;

    let tesseract = validate_languages(&tesseract_languages, "Tesseract languages")?;
    let easyocr = validate_languages(&easyocr_languages, "EasyOCR languages")?;

    // A language the image cannot serve fails per file, hours later and out of sight.
    // Refusing here is the only place it is cheap. An unreachable tier reports no
    // languages, and then this check stands down rather than blocking every change.
    let available = tesseract_languages_available().await;
    if !available.is_empty() {
        let missing: Vec<&str> = tesseract
            .split('+')
            .filter(|code| !available.iter().any(|a| a == code))
            .collect();
        if !missing.is_empty() {
            anyhow::bail!(
                "the OCR image does not have traineddata for {missing:?}. Available: {}",
                available.join(", ")
            );
        }
    }

    // No second check here: the operations lock refuses a second dispatch while a
    // non-terminal `change_ocr_languages` row holds the dataset, and it names the row in
    // the way. A separate guard would be a second rule that can disagree with it.
    let detail = serde_json::json!({
        "tesseract_languages": tesseract,
        "easyocr_languages": easyocr,
    })
    .to_string();
    operations::dispatch_operation(
        OPERATION_KIND_OCR_LANGUAGES,
        &collectionname,
        &collection_dataset,
        &user.username,
        "",
        &detail,
    )
    .await
}

/// The collection's default languages, as `(tesseract, easyocr)`.
///
/// Falls back to the same values `tasks/dataset_config.py` falls back to, so the form
/// shows what a new dataset would actually get rather than an empty box.
pub async fn admin_get_collection_ocr_defaults(
    user: &CurrentUser,
    collectionname: String,
) -> anyhow::Result<(String, String)> {
    guard::require_admin(user)?;
    collection_db_name(&collectionname)?;
    Ok((
        read_setting(&collectionname, KEY_DEFAULT_TESSERACT_LANGUAGES)
            .await?
            .unwrap_or_else(|| "eng".to_string()),
        read_setting(&collectionname, KEY_DEFAULT_EASYOCR_LANGUAGES)
            .await?
            .unwrap_or_else(|| "en".to_string()),
    ))
}

/// Collection-level defaults new datasets inherit. No "apply to all" button: changing a
/// default must not silently re-OCR every dataset that was using it.
pub async fn admin_set_collection_ocr_defaults(
    user: &CurrentUser,
    collectionname: String,
    tesseract_languages: String,
    easyocr_languages: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    collection_db_name(&collectionname)?;
    let tesseract = validate_languages(&tesseract_languages, "Tesseract languages")?;
    let easyocr = validate_languages(&easyocr_languages, "EasyOCR languages")?;
    write_setting(&collectionname, KEY_DEFAULT_TESSERACT_LANGUAGES, &tesseract).await?;
    write_setting(&collectionname, KEY_DEFAULT_EASYOCR_LANGUAGES, &easyocr).await?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Dataset creation
// ---------------------------------------------------------------------------

fn datasets_mount_path() -> String {
    std::env::var("DATASETS_MOUNT_PATH").unwrap_or_else(|_| "/testdata".to_string())
}

/// A folder name that is safe to join onto the mount path.
///
/// Names come back to us through a browser, so this is the boundary: no separators, no
/// traversal, no hidden entries. Together with "the name must be in the listing" it means
/// the joined path is always a direct child of the mount.
fn is_safe_folder_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 128
        && !name.starts_with('.')
        && !name.contains('/')
        && !name.contains('\\')
        && name != ".."
}

/// The dataset id the pipeline composes: `<collectionname>_<dataset_name>`.
///
/// Mirrors `compose_collection_dataset` in `tasks/P0_scan_disk/submit_job.py`. Never split
/// it to recover the collection. A dataset name may contain `_`; resolve through the
/// `dataset` table instead.
fn compose_collection_dataset(collectionname: &str, dataset_name: &str) -> String {
    format!("{collectionname}_{dataset_name}")
}

/// The pipeline's dataset-name rule, duplicated here so the form can refuse before the
/// CLI-side check does. Lowercase alphanumerics and the underscore character.
fn is_valid_dataset_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && name
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
}

pub async fn admin_list_dataset_folders(
    user: &CurrentUser,
    collectionname: String,
) -> anyhow::Result<Vec<DatasetFolderOption>> {
    guard::require_admin(user)?;
    collection_db_name(&collectionname)?;
    let root = datasets_mount_path();

    let mut entries = match std::fs::read_dir(&root) {
        Ok(entries) => entries,
        Err(err) => anyhow::bail!("cannot read {root}: {err}"),
    }
    .filter_map(Result::ok)
    .filter(|e| e.file_type().map(|t| t.is_dir()).unwrap_or(false))
    .filter_map(|e| e.file_name().into_string().ok())
    .filter(|name| is_safe_folder_name(name))
    .collect::<Vec<_>>();
    entries.sort();

    // One level only, and only the immediate child count: walking the tree to report a
    // total would make listing a large corpus a multi-second page load.
    let client = get_global_client();
    let existing: Vec<String> = client
        .query("SELECT dataset_path FROM dataset FINAL WHERE collectionname = ? AND is_deleted = 0")
        .bind(&collectionname)
        .fetch_all::<String>()
        .await?;

    Ok(entries
        .into_iter()
        .map(|name| {
            let path = format!("{}/{}", root.trim_end_matches('/'), name);
            let entry_count = std::fs::read_dir(&path)
                .map(|d| d.filter_map(Result::ok).count() as u64)
                .unwrap_or(0);
            DatasetFolderOption {
                already_used: existing.iter().any(|p| p == &path),
                name,
                entry_count,
            }
        })
        .collect())
}

/// Create a disk dataset from a subfolder of the datasets mount and start ingestion.
///
/// The OCR settings are written **before** the ingest workflow starts, so the very first
/// OCR activity reads them rather than the stack-wide defaults, there is no apply job to
/// fix it up afterwards, and a first pass in the wrong languages costs a full re-OCR.
pub async fn admin_create_dataset(
    user: &CurrentUser,
    collectionname: String,
    folder_name: String,
    dataset_name: String,
    tesseract_languages: String,
    easyocr_languages: String,
) -> anyhow::Result<String> {
    guard::require_admin(user)?;
    collection_db_name(&collectionname)?;

    if !is_safe_folder_name(&folder_name) {
        anyhow::bail!("{folder_name:?} is not a folder name");
    }
    let dataset_name = if dataset_name.trim().is_empty() {
        folder_name.to_lowercase().replace(['-', ' ', '.'], "_")
    } else {
        dataset_name.trim().to_string()
    };
    if !is_valid_dataset_name(&dataset_name) {
        anyhow::bail!(
            "dataset name must be lowercase letters, digits and underscores: got {dataset_name:?}"
        );
    }

    // The name has to be in the listing, not merely well-formed: that is what keeps the
    // joined path a child of the mount even if `is_safe_folder_name` is ever loosened.
    let folders = admin_list_dataset_folders(user, collectionname.clone()).await?;
    if !folders.iter().any(|f| f.name == folder_name) {
        anyhow::bail!("{folder_name:?} is not a folder under {}", datasets_mount_path());
    }

    let collection_dataset = compose_collection_dataset(&collectionname, &dataset_name);
    let client = get_global_client();
    let existing: u64 = client
        .query("SELECT count() FROM dataset FINAL WHERE collection_dataset = ? AND is_deleted = 0")
        .bind(&collection_dataset)
        .fetch_one()
        .await?;
    if existing > 0 {
        anyhow::bail!("dataset {collection_dataset} already exists");
    }

    let tesseract = validate_languages(&tesseract_languages, "Tesseract languages")?;
    let easyocr = validate_languages(&easyocr_languages, "EasyOCR languages")?;

    let path = format!(
        "{}/{}",
        datasets_mount_path().trim_end_matches('/'),
        folder_name
    );

    #[derive(clickhouse::Row, serde::Serialize)]
    struct NewDataset<'a> {
        collection_dataset: &'a str,
        collectionname: &'a str,
        dataset_name: &'a str,
        dataset_display_name: &'a str,
        dataset_type: &'a str,
        dataset_path: &'a str,
        dataset_access_json: Option<&'a str>,
        user_id: &'a str,
        #[serde(with = "clickhouse::serde::time::datetime")]
        date_created: time::OffsetDateTime,
        #[serde(with = "clickhouse::serde::time::datetime")]
        date_modified: time::OffsetDateTime,
        is_deleted: u8,
    }

    let now = time::OffsetDateTime::now_utc();
    let mut insert = client.insert::<NewDataset>("dataset").await?;
    insert
        .write(&NewDataset {
            collection_dataset: &collection_dataset,
            collectionname: &collectionname,
            dataset_name: &dataset_name,
            dataset_display_name: &dataset_name,
            dataset_type: "disk",
            dataset_path: &path,
            dataset_access_json: None,
            user_id: &user.username,
            date_created: now,
            date_modified: now,
            is_deleted: 0,
        })
        .await?;
    insert.end().await?;

    write_setting(&collection_dataset, KEY_TESSERACT_LANGUAGES, &tesseract).await?;
    write_setting(&collection_dataset, KEY_EASYOCR_LANGUAGES, &easyocr).await?;

    // Not a rescan: that only walks the disk and leaves the dataset scanned but
    // unprocessed, which reads as finished and is not. `add_dataset` sequences the three
    // stages server-side, and dispatching it as an operation is what gives the new
    // dataset a row on the collection's processing page from its first second.
    operations::dispatch_operation(
        "add_dataset",
        &collectionname,
        &collection_dataset,
        &user.username,
        "",
        "",
    )
    .await?;
    Ok(collection_dataset)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn languages_keep_their_order_and_lose_duplicates() {
        // `eng+ron` and `ron+eng` are different Tesseract requests and therefore
        // different variants, so neither may be sorted into the other.
        assert_eq!(normalise_languages(" eng + ron "), "eng+ron");
        assert_eq!(normalise_languages("ron+eng"), "ron+eng");
        assert_eq!(normalise_languages("eng+eng+ron"), "eng+ron");
        assert_eq!(normalise_languages("++"), "");
    }

    #[test]
    fn a_language_code_may_not_carry_anything_else_into_a_storage_key() {
        assert!(validate_languages("eng+ron", "x").is_ok());
        assert!(validate_languages("chi_sim", "x").is_ok());
        for bad in ["", "  ", "ENG", "eng ron", "eng/../x", "eng;drop"] {
            assert!(validate_languages(bad, "x").is_err(), "{bad:?} was accepted");
        }
    }

    #[test]
    fn folder_names_cannot_escape_the_mount() {
        assert!(is_safe_folder_name("emails"));
        for bad in ["", "..", ".hidden", "a/b", "a\\b", "/etc"] {
            assert!(!is_safe_folder_name(bad), "{bad:?} was accepted");
        }
    }

    #[test]
    fn dataset_names_match_the_pipelines_rule() {
        assert!(is_valid_dataset_name("test_files2"));
        for bad in ["", "Test", "test-files", "test files", "tést"] {
            assert!(!is_valid_dataset_name(bad), "{bad:?} was accepted");
        }
    }

    #[test]
    fn the_dataset_id_is_composed_the_way_the_pipeline_composes_it() {
        assert_eq!(
            compose_collection_dataset("testdata", "testfiles"),
            "testdata_testfiles"
        );
    }
}
