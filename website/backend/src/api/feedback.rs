//! Bug reports and feedback: the global `feedback_reports` table and its objects.
//!
//! A person sends a report through `POST /_feedback/submit`
//! ([`crate::server_extra::feedback`]). The route stores the page image and the DOM copy
//! in the system bucket, then writes one row. Only an administrator lists the reports,
//! reads their objects or changes their read and archived flags.
//!
//! The browser creates `report_id` when the overlay opens, so a retried send writes the
//! same objects and the same row key again. A report id that another account already
//! used is refused, because the id names objects.

use common::current_user::CurrentUser;
use common::feedback_types::{
    is_report_id, FeedbackListRow, FeedbackPage, FeedbackStatusFilter, FeedbackSubmission,
    CONTEXT_MAX_BYTES, DESCRIPTION_MAX_CHARS, DOM_MAX_BYTES, FEEDBACK_KINDS, FEEDBACK_PAGE_SIZE,
    SCREENSHOT_MAX_BYTES, TITLE_MAX_CHARS,
};
use time::format_description::well_known::Rfc3339;
use time::OffsetDateTime;

use crate::auth::guard::{self, InvalidInput};
use crate::db_utils::clickhouse_utils::get_global_client;

const TABLE: &str = "feedback_reports";

/// The longest page address the upload route accepts, in bytes.
const PAGE_URL_MAX_BYTES: usize = 8192;

const PNG_MAGIC: &[u8] = b"\x89PNG\r\n\x1a\n";

/// One complete row. A flag change writes the whole row again with a higher version.
#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
struct FeedbackDbRow {
    report_id: String,
    kind: String,
    title: String,
    description: String,
    username: String,
    page_url: String,
    context_json: String,
    screenshot_s3_path: String,
    screenshot_bytes: u64,
    dom_s3_path: String,
    dom_bytes: u64,
    #[serde(with = "clickhouse::serde::time::datetime64::millis")]
    created_at: OffsetDateTime,
    is_read: u8,
    is_archived: u8,
    row_version: u64,
}

/// Which stored object of a report a request wants.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FeedbackAsset {
    Screenshot,
    Dom,
}

impl FeedbackAsset {
    pub fn parse(name: &str) -> Option<Self> {
        match name {
            "screenshot.png" => Some(Self::Screenshot),
            "dom.html" => Some(Self::Dom),
            _ => None,
        }
    }

    pub fn file_name(self) -> &'static str {
        match self {
            Self::Screenshot => "screenshot.png",
            Self::Dom => "dom.html",
        }
    }

    pub fn content_type(self) -> &'static str {
        match self {
            Self::Screenshot => "image/png",
            Self::Dom => "text/html; charset=utf-8",
        }
    }
}

fn row_version() -> u64 {
    u64::try_from(OffsetDateTime::now_utc().unix_timestamp_nanos() / 1_000_000).unwrap_or(0)
}

fn invalid(message: &str) -> anyhow::Error {
    anyhow::Error::new(InvalidInput(message.to_string()))
}

/// The submission with its title and kind cleaned, or the rule it breaks.
pub fn validate(mut sub: FeedbackSubmission) -> anyhow::Result<FeedbackSubmission> {
    if !is_report_id(&sub.report_id) {
        return Err(invalid("The report id must be a lowercase UUID."));
    }
    sub.kind = sub.kind.trim().to_ascii_lowercase();
    if !FEEDBACK_KINDS.contains(&sub.kind.as_str()) {
        return Err(invalid("Select Bug or Feedback."));
    }
    sub.title = sub.title.trim().to_string();
    if sub.title.is_empty() {
        return Err(invalid("Write a title."));
    }
    if sub.title.chars().count() > TITLE_MAX_CHARS {
        return Err(invalid(&format!("Write a title of at most {TITLE_MAX_CHARS} characters.")));
    }
    if sub.description.chars().count() > DESCRIPTION_MAX_CHARS {
        return Err(invalid(&format!(
            "Write a description of at most {DESCRIPTION_MAX_CHARS} characters."
        )));
    }
    if sub.page_url.len() > PAGE_URL_MAX_BYTES {
        return Err(invalid("The page address is too long."));
    }
    if sub.context_json.len() > CONTEXT_MAX_BYTES {
        return Err(invalid("The debug context is too large."));
    }
    if sub.dom_html.len() > DOM_MAX_BYTES {
        return Err(invalid("The DOM copy is too large."));
    }
    Ok(sub)
}

/// The PNG bytes of a submission, or none when the drawing failed in the browser.
pub fn decode_screenshot(base64_png: &str) -> anyhow::Result<Option<Vec<u8>>> {
    use base64::Engine;

    if base64_png.is_empty() {
        return Ok(None);
    }
    // Four base64 characters hold three bytes, so a longer string cannot fit the limit.
    if base64_png.len() / 4 * 3 > SCREENSHOT_MAX_BYTES + 3 {
        return Err(invalid("The page image is too large."));
    }
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(base64_png)
        .map_err(|_| invalid("The page image is not valid base64."))?;
    if bytes.len() > SCREENSHOT_MAX_BYTES {
        return Err(invalid("The page image is too large."));
    }
    if !bytes.starts_with(PNG_MAGIC) {
        return Err(invalid("The page image is not a PNG file."));
    }
    Ok(Some(bytes))
}

async fn get_row(report_id: &str) -> anyhow::Result<Option<FeedbackDbRow>> {
    Ok(get_global_client()
        .query("SELECT ?fields FROM feedback_reports FINAL WHERE report_id = ? LIMIT 1")
        .bind(report_id)
        .fetch_optional::<FeedbackDbRow>()
        .await?)
}

async fn put_object(key: &str, bytes: Vec<u8>, content_type: &str) -> anyhow::Result<String> {
    let bucket = crate::db_utils::system_bucket();
    let client = crate::db_utils::s3_client().await?;
    client
        .put_object()
        .bucket(&bucket)
        .key(key)
        .content_type(content_type)
        .body(bytes.into())
        .send()
        .await?;
    Ok(format!("s3://{bucket}/{key}"))
}

fn object_key(report_id: &str, asset: FeedbackAsset) -> String {
    format!("feedback/{report_id}/{}", asset.file_name())
}

/// Store a validated submission for `user`. Returns the report id.
pub async fn store_submission(user: &CurrentUser, sub: FeedbackSubmission) -> anyhow::Result<String> {
    let sub = validate(sub)?;
    let screenshot = decode_screenshot(&sub.screenshot_png_base64)?;
    let existing = get_row(&sub.report_id).await?;
    if let Some(row) = &existing {
        if row.username != user.username {
            anyhow::bail!("forbidden: another account sent a report with this id");
        }
    }

    let (screenshot_s3_path, screenshot_bytes) = match screenshot {
        Some(bytes) => {
            let len = bytes.len() as u64;
            let key = object_key(&sub.report_id, FeedbackAsset::Screenshot);
            (put_object(&key, bytes, FeedbackAsset::Screenshot.content_type()).await?, len)
        }
        None => (String::new(), 0),
    };
    let (dom_s3_path, dom_bytes) = if sub.dom_html.is_empty() {
        (String::new(), 0)
    } else {
        let len = sub.dom_html.len() as u64;
        let key = object_key(&sub.report_id, FeedbackAsset::Dom);
        (put_object(&key, sub.dom_html.into_bytes(), FeedbackAsset::Dom.content_type()).await?, len)
    };

    let row = FeedbackDbRow {
        report_id: sub.report_id.clone(),
        kind: sub.kind,
        title: sub.title,
        description: sub.description,
        username: user.username.clone(),
        page_url: sub.page_url,
        context_json: sub.context_json,
        screenshot_s3_path,
        screenshot_bytes,
        dom_s3_path,
        dom_bytes,
        // A retried send keeps the time of the first one.
        created_at: existing.as_ref().map_or_else(OffsetDateTime::now_utc, |r| r.created_at),
        is_read: 0,
        is_archived: 0,
        row_version: row_version(),
    };
    crate::db_auth::insert_row(TABLE, &row).await?;
    Ok(row.report_id)
}

/// The bytes of one stored object of a report. Administrators only.
pub async fn read_asset(user: &CurrentUser, report_id: &str, asset: FeedbackAsset) -> anyhow::Result<Vec<u8>> {
    guard::require_admin(user)?;
    let row = get_row(report_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("report {}", guard::NOT_FOUND))?;
    let path = match asset {
        FeedbackAsset::Screenshot => &row.screenshot_s3_path,
        FeedbackAsset::Dom => &row.dom_s3_path,
    };
    // The bucket comes from the stored path, never from this process's configuration.
    let (bucket, key) = crate::db_utils::split_s3_path(path)
        .ok_or_else(|| anyhow::anyhow!("report object {}", guard::NOT_FOUND))?;
    let client = crate::db_utils::s3_client().await?;
    let object = client.get_object().bucket(&bucket).key(&key).send().await?;
    Ok(object.body.collect().await?.to_vec())
}

fn status_clause(status: FeedbackStatusFilter) -> &'static str {
    match status {
        FeedbackStatusFilter::Open => "is_archived = 0",
        FeedbackStatusFilter::Unread => "is_archived = 0 AND is_read = 0",
        FeedbackStatusFilter::Archived => "is_archived = 1",
        FeedbackStatusFilter::All => "1",
    }
}

const SEARCH_CLAUSE: &str = "(? = '' OR positionCaseInsensitiveUTF8(title, ?) > 0 \
    OR positionCaseInsensitiveUTF8(description, ?) > 0 \
    OR positionCaseInsensitiveUTF8(username, ?) > 0 \
    OR positionCaseInsensitiveUTF8(page_url, ?) > 0)";

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct ListDbRow {
    report_id: String,
    kind: String,
    title: String,
    description: String,
    username: String,
    page_url: String,
    screenshot_bytes: u64,
    dom_bytes: u64,
    created_ms: i64,
    is_read: u8,
    is_archived: u8,
}

fn rfc3339_of_millis(ms: i64) -> String {
    OffsetDateTime::from_unix_timestamp_nanos(i128::from(ms) * 1_000_000)
        .ok()
        .and_then(|t| t.format(&Rfc3339).ok())
        .unwrap_or_default()
}

fn list_row(row: &FeedbackDbRow) -> FeedbackListRow {
    FeedbackListRow {
        report_id: row.report_id.clone(),
        kind: row.kind.clone(),
        title: row.title.clone(),
        description: row.description.clone(),
        username: row.username.clone(),
        page_url: row.page_url.clone(),
        context_json: row.context_json.clone(),
        screenshot_bytes: row.screenshot_bytes,
        dom_bytes: row.dom_bytes,
        created_at: row.created_at.format(&Rfc3339).unwrap_or_default(),
        is_read: row.is_read != 0,
        is_archived: row.is_archived != 0,
    }
}

/// One page of reports, newest first. `page` starts at 1. The rows leave out the debug
/// context, which [`admin_get_feedback`] returns for one report.
pub async fn admin_list_feedback(
    user: &CurrentUser,
    search: String,
    status: FeedbackStatusFilter,
    page: u32,
) -> anyhow::Result<FeedbackPage> {
    guard::require_admin(user)?;
    let search = search.trim().to_string();
    let where_clause = format!("{} AND {SEARCH_CLAUSE}", status_clause(status));
    let client = get_global_client();
    let total = client
        .query(&format!("SELECT count() FROM feedback_reports FINAL WHERE {where_clause}"))
        .bind(&search).bind(&search).bind(&search).bind(&search).bind(&search)
        .fetch_one::<u64>()
        .await?;
    let offset = page.max(1).saturating_sub(1).saturating_mul(FEEDBACK_PAGE_SIZE);
    let rows = client
        .query(&format!(
            "SELECT report_id, kind, title, description, username, page_url, \
             screenshot_bytes, dom_bytes, \
             toInt64(toUnixTimestamp64Milli(created_at)) AS created_ms, is_read, is_archived \
             FROM feedback_reports FINAL WHERE {where_clause} \
             ORDER BY created_at DESC, report_id LIMIT ? OFFSET ?"
        ))
        .bind(&search).bind(&search).bind(&search).bind(&search).bind(&search)
        .bind(FEEDBACK_PAGE_SIZE)
        .bind(offset)
        .fetch_all::<ListDbRow>()
        .await?;
    Ok(FeedbackPage {
        rows: rows
            .into_iter()
            .map(|r| FeedbackListRow {
                report_id: r.report_id,
                kind: r.kind,
                title: r.title,
                description: r.description,
                username: r.username,
                page_url: r.page_url,
                context_json: String::new(),
                screenshot_bytes: r.screenshot_bytes,
                dom_bytes: r.dom_bytes,
                created_at: rfc3339_of_millis(r.created_ms),
                is_read: r.is_read != 0,
                is_archived: r.is_archived != 0,
            })
            .collect(),
        total,
    })
}

/// One report with its debug context.
pub async fn admin_get_feedback(user: &CurrentUser, report_id: String) -> anyhow::Result<FeedbackListRow> {
    guard::require_admin(user)?;
    let row = get_row(&report_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("report {}", guard::NOT_FOUND))?;
    Ok(list_row(&row))
}

/// Set the read and archived flags of one report. The two flags are separate, so an
/// archived report keeps its read state.
pub async fn admin_set_feedback_flags(
    user: &CurrentUser,
    report_id: String,
    is_read: bool,
    is_archived: bool,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    let mut row = get_row(&report_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("report {}", guard::NOT_FOUND))?;
    row.is_read = u8::from(is_read);
    row.is_archived = u8::from(is_archived);
    row.row_version = row_version().max(row.row_version + 1);
    crate::db_auth::insert_row(TABLE, &row).await
}

#[cfg(test)]
mod tests {
    use super::*;

    fn submission() -> FeedbackSubmission {
        FeedbackSubmission {
            report_id: "6f1a3c2e-1b2c-4d5e-8f90-0123456789ab".into(),
            kind: "Bug".into(),
            title: "  The table does not scroll  ".into(),
            ..Default::default()
        }
    }

    #[test]
    fn validation_cleans_the_kind_and_the_title() {
        let sub = validate(submission()).unwrap();
        assert_eq!(sub.kind, "bug");
        assert_eq!(sub.title, "The table does not scroll");
    }

    #[test]
    fn validation_refuses_what_the_route_cannot_store() {
        let mut bad_id = submission();
        bad_id.report_id = "../x".into();
        assert!(guard::is_bad_request(&validate(bad_id).unwrap_err()));
        let mut bad_kind = submission();
        bad_kind.kind = "praise".into();
        assert!(guard::is_bad_request(&validate(bad_kind).unwrap_err()));
        let mut no_title = submission();
        no_title.title = "   ".into();
        assert!(guard::is_bad_request(&validate(no_title).unwrap_err()));
    }

    #[test]
    fn the_screenshot_must_be_a_png() {
        use base64::Engine;
        let png = base64::engine::general_purpose::STANDARD.encode(b"\x89PNG\r\n\x1a\nrest");
        assert_eq!(decode_screenshot(&png).unwrap().unwrap().len(), 12);
        let gif = base64::engine::general_purpose::STANDARD.encode(b"GIF89a");
        assert!(decode_screenshot(&gif).is_err());
        assert!(decode_screenshot("").unwrap().is_none());
    }
}
