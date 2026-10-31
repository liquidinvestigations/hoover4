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
//! * **One upload dataset per collection.** `uploads_enabled` is refused for a dataset whose
//!   folder is not beneath a writable mount, and while another live dataset of the
//!   collection has it. The check and the write hold the upload setting lock of the
//!   collection (`db_auth::uploads::lock_upload_setting`), at creation and at each change.
//! * **The creation form never takes a path.** It takes a mount name and a folder *name*.
//!   The folder is validated against the listing of that mount and joined server-side. A
//!   free-text path in a browser form is a way to point the ingest walker at any
//!   directory the container can see. A new folder is created only in a writable mount.

use std::time::Duration;

use common::admin_types::{
    DatasetFolderOption, DatasetMountOption, DatasetOcrPanel, DatasetOperationStatus, DatasetPdfVariant,
    DatasetTextVariant, DatasetUploadsSetting,
};
use common::current_user::CurrentUser;
use common::storage_tree::{compose_collection_dataset, normalize_identifier};
use time::format_description::well_known::Rfc3339;

use crate::api::admin::operations;
use crate::dataset_mounts::{self, is_safe_folder_name, DatasetMount};
use crate::auth::guard;
use crate::db_auth::uploads::{self, KEY_UPLOADS_ENABLED};
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
    progress_done: u64,
    progress_total: u64,
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
                    toInt64(toUnixTimestamp(updated_at)) AS last_update, progress_done, progress_total \
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
    let running = matches!(row.state.as_str(), "pending" | "queued" | "running");
    Ok(Some(DatasetOperationStatus {
        progress_done: row.progress_done,
        progress_total: row.progress_total,
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

/// The latest stored row of one setting key, as `tasks/dataset_config.py` reads it. The
/// value, the deletion flag and the version come from one write, chosen by
/// `setting_version_us`.
#[derive(clickhouse::Row, serde::Deserialize)]
struct LatestSetting {
    value: String,
    is_deleted: u8,
    setting_version_us: u64,
}

async fn latest_setting(collection_dataset: &str, key: &str) -> anyhow::Result<Option<LatestSetting>> {
    let client = get_global_client();
    let rows = client
        .query(
            "SELECT latest.1 AS value, latest.2 AS is_deleted, latest.3 AS setting_version_us \
             FROM (SELECT argMax((value, is_deleted, setting_version_us), setting_version_us) \
                   AS latest FROM dataset_settings \
                   WHERE collection_dataset = ? AND key = ? GROUP BY key)",
        )
        .bind(collection_dataset)
        .bind(key)
        .fetch_all::<LatestSetting>()
        .await?;
    Ok(rows.into_iter().next())
}

async fn read_setting(collection_dataset: &str, key: &str) -> anyhow::Result<Option<String>> {
    Ok(latest_setting(collection_dataset, key)
        .await?
        .filter(|row| row.is_deleted == 0)
        .map(|row| row.value))
}

/// The version of a new or changed setting value: the current time in microseconds, and
/// above the version of the row it replaces.
fn next_setting_version(now_us: u64, latest_version_us: Option<u64>) -> u64 {
    latest_version_us.map_or(now_us, |latest| now_us.max(latest + 1))
}

/// Write one setting. An unchanged live value writes nothing, so the setting keeps its
/// version, as `set_dataset_setting` in `tasks/dataset_config.py` does. The client waits
/// for the insert to reach storage.
async fn write_setting(collection_dataset: &str, key: &str, value: &str) -> anyhow::Result<()> {
    #[derive(clickhouse::Row, serde::Serialize)]
    struct SettingRow<'a> {
        collection_dataset: &'a str,
        key: &'a str,
        value: &'a str,
        #[serde(with = "clickhouse::serde::time::datetime")]
        updated_at: time::OffsetDateTime,
        is_deleted: u8,
        setting_version_us: u64,
        version_is_precise: u8,
    }
    let latest = latest_setting(collection_dataset, key).await?;
    if latest
        .as_ref()
        .is_some_and(|row| row.is_deleted == 0 && row.value == value)
    {
        return Ok(());
    }
    let now = time::OffsetDateTime::now_utc();
    let now_us = u64::try_from(now.unix_timestamp_nanos() / 1_000)?;
    let client = get_global_client();
    let mut insert = client.insert::<SettingRow>("dataset_settings").await?;
    insert
        .write(&SettingRow {
            collection_dataset,
            key,
            value,
            updated_at: now,
            is_deleted: 0,
            setting_version_us: next_setting_version(
                now_us,
                latest.map(|row| row.setting_version_us),
            ),
            version_is_precise: 1,
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
            "SELECT extracted_by, uniqExact((file_hash, page_id)) FROM text_content \
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
                 HAVING argMax(is_deleted, updated_at) = 0 AND argMax(source_kind, updated_at) != 'image' \
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

    // No second check here: the operations lock refuses a dispatch while a live operation
    // holds the dataset or its collection, and it names the row in the way. A separate
    // guard would be a second rule that can disagree with it.
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
// The upload dataset setting
// ---------------------------------------------------------------------------

/// The refusal of `uploads_enabled = true` for a dataset, or `None` when the setting may
/// be written. `others` lists the other live datasets of the collection that have it.
fn upload_refusal(
    collection_dataset: &str,
    dataset_type: &str,
    writable_mount: bool,
    others: &[String],
) -> Option<String> {
    if dataset_type != "disk" {
        return Some(format!(
            "{collection_dataset} is not a disk dataset, so it cannot accept uploads."
        ));
    }
    if !writable_mount {
        return Some(format!(
            "The folder of {collection_dataset} is not in a writable dataset mount, so it cannot accept uploads."
        ));
    }
    match others {
        [] => None,
        [other] => Some(format!(
            "{other} already accepts uploads. A collection can have one upload dataset."
        )),
        many => Some(format!(
            "The datasets {} already accept uploads. A collection can have one upload dataset. \
             Turn off Accept uploads on all of them but one.",
            many.join(", ")
        )),
    }
}

/// True when the dataset folder opens beneath a writable mount of `mounts`.
async fn opens_in_writable_mount(
    mounts: &[DatasetMount],
    dataset_path: &str,
) -> anyhow::Result<bool> {
    let mounts = mounts.to_vec();
    let path = dataset_path.to_string();
    dataset_mounts::blocking(move || Ok(uploads::open_dataset_folder(&mounts, &path).is_ok())).await
}

/// Write `uploads_enabled` for a dataset, with the mounts in `mounts`. Turning it off is
/// always accepted, so an administrator can clear a conflict. Turning it on holds the
/// upload setting lock of the collection from the check to the write.
pub async fn set_uploads_enabled(
    collection_dataset: &str,
    on: bool,
    mounts: &[DatasetMount],
) -> anyhow::Result<()> {
    let facts = uploads::dataset_upload_facts(collection_dataset)
        .await?
        .ok_or_else(|| anyhow::anyhow!("dataset not found"))?;
    let _guard = uploads::lock_upload_setting(&facts.collectionname).await;
    if on {
        let writable = facts.dataset_type == "disk"
            && opens_in_writable_mount(mounts, &facts.dataset_path).await?;
        let others: Vec<String> = uploads::upload_datasets_of_collection(&facts.collectionname)
            .await?
            .into_iter()
            .filter(|d| d != collection_dataset)
            .collect();
        if let Some(refusal) = upload_refusal(collection_dataset, &facts.dataset_type, writable, &others) {
            return Err(guard::InvalidInput(refusal).into());
        }
    }
    write_setting(collection_dataset, KEY_UPLOADS_ENABLED, if on { "true" } else { "false" }).await
}

/// Turn "Accept uploads" on or off for a dataset.
pub async fn admin_set_dataset_uploads(
    user: &CurrentUser,
    collection_dataset: String,
    on: bool,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    set_uploads_enabled(&collection_dataset, on, &dataset_mounts::dataset_mounts()?).await
}

/// The upload setting of a dataset, for the dataset page.
pub async fn admin_get_dataset_uploads(
    user: &CurrentUser,
    collection_dataset: String,
) -> anyhow::Result<DatasetUploadsSetting> {
    guard::require_admin(user)?;
    let facts = uploads::dataset_upload_facts(&collection_dataset)
        .await?
        .ok_or_else(|| anyhow::anyhow!("dataset not found"))?;
    let writable_mount = facts.dataset_type == "disk"
        && opens_in_writable_mount(&dataset_mounts::dataset_mounts()?, &facts.dataset_path).await?;
    let enabled = read_setting(&collection_dataset, KEY_UPLOADS_ENABLED).await?.as_deref() == Some("true");
    let other_upload_datasets = uploads::upload_datasets_of_collection(&facts.collectionname)
        .await?
        .into_iter()
        .filter(|d| d != &collection_dataset)
        .collect();
    Ok(DatasetUploadsSetting {
        writable_mount,
        enabled,
        other_upload_datasets,
    })
}

/// The live datasets of a collection that accept uploads, for the creation form.
pub async fn admin_list_collection_upload_datasets(
    user: &CurrentUser,
    collectionname: String,
) -> anyhow::Result<Vec<String>> {
    guard::require_admin(user)?;
    collection_db_name(&collectionname)?;
    uploads::upload_datasets_of_collection(&collectionname).await
}

// ---------------------------------------------------------------------------
// Dataset creation
// ---------------------------------------------------------------------------

/// The pipeline's dataset-name rule, duplicated here so the form can refuse before the
/// CLI-side check does. Lowercase alphanumerics and the underscore character.
fn is_valid_dataset_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && name
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
}

/// The dataset path of a folder: the mount's container path and the folder name.
fn dataset_path(mount: &DatasetMount, folder_name: &str) -> String {
    format!("{}/{}", mount.path.trim_end_matches('/'), folder_name)
}

/// The configured dataset mounts, in the order of `HOOVER4_DATASET_MOUNTS`.
pub async fn admin_list_dataset_mounts(
    user: &CurrentUser,
) -> anyhow::Result<Vec<DatasetMountOption>> {
    guard::require_admin(user)?;
    Ok(dataset_mounts::dataset_mounts()?
        .into_iter()
        .map(|m| DatasetMountOption {
            name: m.name,
            path: m.path,
            writable: m.writable,
        })
        .collect())
}

pub async fn admin_list_dataset_folders(
    user: &CurrentUser,
    collectionname: String,
    mount_name: String,
) -> anyhow::Result<Vec<DatasetFolderOption>> {
    guard::require_admin(user)?;
    collection_db_name(&collectionname)?;
    let mount = dataset_mounts::mount_named(&mount_name)?;

    // One level only, and only the immediate child count: walking the tree to report a
    // total would make listing a large corpus a multi-second page load.
    let listed_mount = mount.clone();
    let folders = dataset_mounts::blocking(move || dataset_mounts::list_folders(&listed_mount))
        .await
        .map_err(|e| anyhow::anyhow!("cannot read {}: {e}", mount.path))?;

    let client = get_global_client();
    let existing: Vec<String> = client
        .query("SELECT dataset_path FROM dataset FINAL WHERE collectionname = ? AND is_deleted = 0")
        .bind(&collectionname)
        .fetch_all::<String>()
        .await?;

    Ok(folders
        .into_iter()
        .map(|(name, entry_count)| {
            let path = dataset_path(&mount, &name);
            DatasetFolderOption {
                already_used: existing.iter().any(|p| p == &path),
                name,
                entry_count,
            }
        })
        .collect())
}

/// Create an empty folder directly beneath a writable dataset mount. Refuses a read-only
/// mount, including the inferred one.
pub async fn admin_create_dataset_folder(
    user: &CurrentUser,
    mount_name: String,
    folder_name: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    let mount = dataset_mounts::mount_named(&mount_name)?;
    dataset_mounts::blocking(move || dataset_mounts::create_folder(&mount, &folder_name)).await
}

/// Create a disk dataset from a subfolder of the datasets mount and start ingestion.
///
/// The OCR settings are written **before** the ingest workflow starts, so the very first
/// OCR activity reads them rather than the stack-wide defaults, there is no apply job to
/// fix it up afterwards, and a first pass in the wrong languages costs a full re-OCR.
///
/// With `new_folder` the server creates the folder in a writable mount after every other
/// field is valid. Without it the folder must be in the listing of the mount.
///
/// With `accept_uploads` the dataset becomes the upload dataset of the collection. The
/// mount must be writable, and no other live dataset of the collection may accept uploads.
/// The upload setting lock of the collection is held from that check until the setting
/// is written. Without it, a stored `true` of an earlier dataset with the same id is
/// written `false`.
#[allow(clippy::too_many_arguments)]
pub async fn admin_create_dataset(
    user: &CurrentUser,
    collectionname: String,
    mount_name: String,
    folder_name: String,
    new_folder: bool,
    dataset_name: String,
    tesseract_languages: String,
    easyocr_languages: String,
    accept_uploads: bool,
) -> anyhow::Result<String> {
    guard::require_admin(user)?;
    collection_db_name(&collectionname)?;
    let mount = dataset_mounts::mount_named(&mount_name)?;
    if new_folder {
        dataset_mounts::require_writable(&mount)?;
    }
    if accept_uploads && !mount.writable {
        return Err(guard::InvalidInput(format!(
            "The dataset mount {} is read-only, so a dataset in it cannot accept uploads.",
            mount.name
        ))
        .into());
    }

    if !is_safe_folder_name(&folder_name) {
        anyhow::bail!("{folder_name:?} is not a folder name");
    }
    // The form shows the same normalized name before it sends the request.
    let dataset_name = if dataset_name.trim().is_empty() {
        normalize_identifier(&folder_name)
    } else {
        normalize_identifier(&dataset_name)
    };
    if !is_valid_dataset_name(&dataset_name) {
        anyhow::bail!(
            "dataset name must be lowercase letters, digits and underscores: got {dataset_name:?}"
        );
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

    let upload_guard = uploads::lock_upload_setting(&collectionname).await;
    if accept_uploads {
        let others = uploads::upload_datasets_of_collection(&collectionname).await?;
        if let Some(refusal) = upload_refusal(&collection_dataset, "disk", true, &others) {
            return Err(guard::InvalidInput(refusal).into());
        }
    }

    if new_folder {
        admin_create_dataset_folder(user, mount_name.clone(), folder_name.clone()).await?;
    }
    // The name has to be in the listing, not merely well-formed: the listing opens each
    // folder through the mount's descriptor and drops symbolic links, so the joined path is
    // a real folder directly beneath the mount.
    let folders = admin_list_dataset_folders(user, collectionname.clone(), mount_name).await?;
    if !folders.iter().any(|f| f.name == folder_name) {
        anyhow::bail!("{folder_name:?} is not a folder under {}", mount.path);
    }
    let path = dataset_path(&mount, &folder_name);

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
    if accept_uploads {
        write_setting(&collection_dataset, KEY_UPLOADS_ENABLED, "true").await?;
    } else if read_setting(&collection_dataset, KEY_UPLOADS_ENABLED).await?.as_deref() == Some("true") {
        write_setting(&collection_dataset, KEY_UPLOADS_ENABLED, "false").await?;
    }
    drop(upload_guard);

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
    fn a_setting_version_is_above_the_row_it_replaces() {
        assert_eq!(next_setting_version(1_000_000, None), 1_000_000);
        assert_eq!(next_setting_version(1_000_000, Some(999_999)), 1_000_000);
        // A row written later in the same second by another clock, or copied from a
        // whole-second time that rounds up past the writer's clock.
        assert_eq!(next_setting_version(1_000_000, Some(1_000_000)), 1_000_001);
        assert_eq!(next_setting_version(1_000_000, Some(2_000_000)), 2_000_001);
    }

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
    fn a_dataset_path_is_the_mount_path_and_the_folder() {
        let mount = DatasetMount {
            name: "uploads".to_string(),
            path: "/uploads".to_string(),
            writable: true,
        };
        assert_eq!(dataset_path(&mount, "case 7"), "/uploads/case 7");
    }

    #[test]
    fn uploads_need_a_disk_dataset_in_a_writable_mount_and_no_other_upload_dataset() {
        assert_eq!(upload_refusal("c_a", "disk", true, &[]), None);
        let read_only = upload_refusal("c_a", "disk", false, &[]).unwrap();
        assert!(read_only.contains("not in a writable dataset mount"), "{read_only}");
        let not_disk = upload_refusal("c_a", "s3", true, &[]).unwrap();
        assert!(not_disk.contains("not a disk dataset"), "{not_disk}");
        let second = upload_refusal("c_b", "disk", true, &["c_a".to_string()]).unwrap();
        assert!(second.starts_with("c_a already accepts uploads"), "{second}");
        let conflict = upload_refusal("c_c", "disk", true, &["c_a".to_string(), "c_b".to_string()]).unwrap();
        assert!(conflict.contains("c_a, c_b"), "{conflict}");
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
