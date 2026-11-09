//! Read automatic OCR status, create datasets, and set the upload and vector switches.
//!
//! Manual OCR language mutations remain for stale clients and return a typed
//! retired-setting error. Dataset creation accepts empty compatibility fields and stores
//! no OCR override. Dataset mounts and upload settings retain their existing access checks.

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

    let automatic_status = automatic_status(&collectionname, &collection_dataset).await?;
    Ok(DatasetOcrPanel {
        automatic_status,
        collection_dataset: collection_dataset.clone(),
        collectionname,
        easyocr_configured: !env_url("OCR_EASYOCR_URL").is_empty(),
        ocr_pdf_configured: !env_url("OCR_PDF_URL").is_empty(),
        text_variants,
        pdf_variants,
        operation: latest_operation(&collection_dataset).await?,
    })
}

/// Summarize current automatic publications without returning document payloads. The model
/// of a page is its first OCR pass, or its first adopted earlier result when it has no pass.
async fn automatic_status(collectionname: &str, dataset: &str) -> anyhow::Result<common::admin_types::AutomaticOcrStatus> {
    let rows: Vec<(String, String, u64, u64)> = get_collection_client(collectionname)
        .query("SELECT current_state, current_reason, count(), sum(current_pages) FROM (SELECT hash, argMax(state, revision) AS current_state, argMax(reason, revision) AS current_reason, argMax(expected_pages, revision) AS current_pages FROM automatic_ocr_plans FINAL WHERE collection_dataset = ? AND state NOT IN ('candidate', 'superseded') GROUP BY hash) GROUP BY current_state, current_reason ORDER BY current_state, current_reason")
        .bind(dataset).fetch_all().await?;
    let mut digests: Vec<String> = get_collection_client(collectionname)
        .query("SELECT DISTINCT current_capability FROM (SELECT hash, argMax(capability_digest, revision) AS current_capability, argMax(state, revision) AS current_state FROM automatic_ocr_plans FINAL WHERE collection_dataset = ? AND state NOT IN ('candidate', 'superseded') GROUP BY hash) ORDER BY current_capability LIMIT 101")
        .bind(dataset).fetch_all().await?;
    let mut decisions: Vec<(String, String, String, String, String, String, u64)> = get_collection_client(collectionname)
        .query("SELECT JSONExtractString(page, 'script'), JSONExtractString(page, 'language'), JSONExtractString(page, 'status'), JSONExtractString(page, 'reason'), JSONExtractString(arrayElement(arrayConcat(JSONExtractArrayRaw(page, 'passes'), JSONExtractArrayRaw(page, 'adopted')), 1), 'engine'), JSONExtractString(arrayElement(arrayConcat(JSONExtractArrayRaw(page, 'passes'), JSONExtractArrayRaw(page, 'adopted')), 1), 'languages'), count() FROM (SELECT argMax(plan_json, revision) AS plan, argMax(state, revision) AS current_state FROM automatic_ocr_plans FINAL WHERE collection_dataset = ? AND state NOT IN ('candidate', 'superseded') GROUP BY hash) ARRAY JOIN JSONExtractArrayRaw(plan, 'pages') AS page GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY 1, 2, 3, 4, 5, 6 LIMIT 1025")
        .bind(dataset).fetch_all().await?;
    let page_decisions_truncated = decisions.len() > 1024;
    let capability_digests_truncated = digests.len() > 100;
    decisions.truncate(1024);
    digests.truncate(100);
    Ok(common::admin_types::AutomaticOcrStatus {
        page_decisions_truncated, capability_digests_truncated,
        automatic: true, policy_version: 1, capability_digests: digests,
        page_decisions: decisions.into_iter().map(|(script, language, status, reason, engine, languages, pages)|
            common::admin_types::AutomaticOcrPageCount { script, language, status, reason, engine, languages, pages }).collect(),
        states: rows.into_iter().map(|(state, reason, files, pages)| common::admin_types::AutomaticOcrStateCount { state, reason, files, pages }).collect(),
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

/// Return a typed retired-setting error to stale dataset clients.
pub async fn admin_apply_ocr_languages(
    user: &CurrentUser,
    collection_dataset: String,
    tesseract_languages: String,
    easyocr_languages: String,
    inherit_tesseract: bool,
    inherit_easyocr: bool,
) -> anyhow::Result<String> {
    guard::require_admin(user)?;
    let _ = (collection_dataset, tesseract_languages, easyocr_languages, inherit_tesseract, inherit_easyocr);
    Err(guard::RetiredOcrSetting.into())
}

/// Return a typed retired-setting error to stale collection clients.
pub async fn admin_set_collection_ocr_defaults(
    user: &CurrentUser,
    collectionname: String,
    tesseract_languages: String,
    easyocr_languages: String,
) -> anyhow::Result<Vec<String>> {
    guard::require_admin(user)?;
    let _ = (collectionname, tesseract_languages, easyocr_languages);
    Err(guard::RetiredOcrSetting.into())
}

// ---------------------------------------------------------------------------
// The upload dataset setting
// ---------------------------------------------------------------------------

/// The refusal of `uploads_enabled = true` for a dataset, or `None` when the setting may
/// be written. Other upload datasets of the collection do not matter.
fn upload_refusal(collection_dataset: &str, dataset_type: &str, writable_mount: bool) -> Option<String> {
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
    None
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
/// always accepted.
pub async fn set_uploads_enabled(
    collection_dataset: &str,
    on: bool,
    mounts: &[DatasetMount],
) -> anyhow::Result<()> {
    let facts = uploads::dataset_upload_facts(collection_dataset)
        .await?
        .ok_or_else(|| anyhow::anyhow!("dataset not found"))?;
    if on {
        let writable = facts.dataset_type == "disk"
            && opens_in_writable_mount(mounts, &facts.dataset_path).await?;
        if let Some(refusal) = upload_refusal(collection_dataset, &facts.dataset_type, writable) {
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
    Ok(DatasetUploadsSetting { writable_mount, enabled })
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
/// OCR activity reads them, and a first pass in the wrong languages costs no re-OCR.
///
/// With `new_folder` the server creates the folder in a writable mount after every other
/// field is valid. Without it the folder must be in the listing of the mount.
///
/// With `accept_uploads` the dataset becomes an upload dataset of the collection. The
/// mount must be writable. Other upload datasets of the collection do not matter. Without
/// it, a stored `true` of an earlier dataset with the same id is written `false`.
#[allow(clippy::too_many_arguments)]
pub async fn admin_create_dataset_automatic(
    user: &CurrentUser,
    collectionname: String,
    mount_name: String,
    folder_name: String,
    new_folder: bool,
    dataset_name: String,
    accept_uploads: bool,
) -> anyhow::Result<String> {
    admin_create_dataset(user, collectionname, mount_name, folder_name, new_folder,
                         dataset_name, String::new(), String::new(), accept_uploads).await
}

/// Retain the creation signature for stale clients and reject manual OCR values.
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

    if !tesseract_languages.trim().is_empty() || !easyocr_languages.trim().is_empty() {
        return Err(guard::RetiredOcrSetting.into());
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

    if accept_uploads {
        write_setting(&collection_dataset, KEY_UPLOADS_ENABLED, "true").await?;
    } else if read_setting(&collection_dataset, KEY_UPLOADS_ENABLED).await?.as_deref() == Some("true") {
        write_setting(&collection_dataset, KEY_UPLOADS_ENABLED, "false").await?;
    }

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

    #[tokio::test]
    async fn retired_mutations_return_before_storage_access() {
        let user = CurrentUser { username: "admin".into(), fullname: String::new(), email: String::new(), is_admin: true, groups: vec![] };
        let dataset_error = admin_apply_ocr_languages(&user, "dataset".into(), "eng".into(), "en".into(), false, false).await.unwrap_err();
        assert!(dataset_error.is::<guard::RetiredOcrSetting>());
        let collection_error = admin_set_collection_ocr_defaults(&user, "collection".into(), "eng".into(), "en".into()).await.unwrap_err();
        assert!(collection_error.is::<guard::RetiredOcrSetting>());
    }

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
    fn a_dataset_path_is_the_mount_path_and_the_folder() {
        let mount = DatasetMount {
            name: "uploads".to_string(),
            path: "/uploads".to_string(),
            writable: true,
        };
        assert_eq!(dataset_path(&mount, "case 7"), "/uploads/case 7");
    }

    #[test]
    fn uploads_need_a_disk_dataset_in_a_writable_mount() {
        assert_eq!(upload_refusal("c_a", "disk", true), None);
        let read_only = upload_refusal("c_a", "disk", false).unwrap();
        assert!(read_only.contains("not in a writable dataset mount"), "{read_only}");
        let not_disk = upload_refusal("c_a", "s3", true).unwrap();
        assert!(not_disk.contains("not a disk dataset"), "{not_disk}");
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

// ---------------------------------------------------------------------------
// Collection features
// ---------------------------------------------------------------------------

/// The collection switch for vectors, mirroring `KEY_FEATURE_VECTORS` in
/// `tasks/dataset_config.py`. Stored under the collection name.
const KEY_FEATURE_VECTORS: &str = "features.vectors";

/// The vectors switch of a collection: `(enabled, explicit, installation)`.
///
/// A collection without the row follows the installation, which uses vectors when an
/// embeddings endpoint is configured. `explicit` is true when the collection has a row.
pub async fn admin_get_collection_vectors(
    user: &CurrentUser,
    collectionname: String,
) -> anyhow::Result<(bool, bool, bool)> {
    guard::require_admin(user)?;
    collection_db_name(&collectionname)?;
    let installation = !env_url("EMBEDDINGS_URL").is_empty();
    let stored = read_setting(&collectionname, KEY_FEATURE_VECTORS).await?;
    let explicit = matches!(stored.as_deref(), Some("true") | Some("false"));
    let enabled = installation && stored.as_deref().map_or(true, |v| v != "false");
    Ok((enabled, explicit, installation))
}

/// Turn vectors on or off for a collection, then start the processing updates.
///
/// Off stops new vectors and stops search from using the stored ones, which stay. On
/// makes the Vectors step of each dataset wait for the files without vectors. A
/// collection cannot turn on a service that the installation does not run.
pub async fn admin_set_collection_vectors(
    user: &CurrentUser,
    collectionname: String,
    on: bool,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    collection_db_name(&collectionname)?;
    if on && env_url("EMBEDDINGS_URL").is_empty() {
        return Err(guard::InvalidInput(
            "This installation runs no embedding service, so a collection cannot use vectors.".to_string(),
        )
        .into());
    }
    write_setting(&collectionname, KEY_FEATURE_VECTORS, if on { "true" } else { "false" }).await?;
    crate::api::admin::processing_updates::signal_check("*").await
}
