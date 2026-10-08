//! Types shared between the feedback control, the feedback upload route and the
//! administration feedback list.
//!
//! A person sends a report from the bug control in the left rail. The browser draws an
//! image of the tab from the DOM and copies the DOM as HTML. The upload route stores
//! both in the system bucket and one row in the global `feedback_reports` table.

/// The two report kinds a person can select.
pub const FEEDBACK_KINDS: [&str; 2] = ["bug", "feedback"];

/// The longest title the upload route accepts, in characters.
pub const TITLE_MAX_CHARS: usize = 200;

/// The longest description the upload route accepts, in characters.
pub const DESCRIPTION_MAX_CHARS: usize = 20_000;

/// The largest page image the upload route accepts, in bytes after decoding.
pub const SCREENSHOT_MAX_BYTES: usize = 16 * 1024 * 1024;

/// The largest DOM copy the upload route accepts, in bytes.
pub const DOM_MAX_BYTES: usize = 8 * 1024 * 1024;

/// The largest debug context the upload route accepts, in bytes.
pub const CONTEXT_MAX_BYTES: usize = 1024 * 1024;

/// The largest upload body. It holds the base64 image, the DOM copy and the context.
pub const UPLOAD_MAX_BYTES: usize = 32 * 1024 * 1024;

/// Reports on one page of the administration list.
pub const FEEDBACK_PAGE_SIZE: u32 = 50;

/// The JSON body of `POST /_feedback/submit`. The server takes the account from the
/// authenticated request, so the body names no user.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, Default)]
pub struct FeedbackSubmission {
    /// A UUID that the browser creates when the overlay opens. A retried send uses the
    /// same value, so it writes the same row and the same objects again.
    pub report_id: String,
    pub kind: String,
    pub title: String,
    pub description: String,
    pub page_url: String,
    /// Browser information, route state, notes about the capture and the log entries.
    pub context_json: String,
    /// The PNG image as base64, without a `data:` prefix. Empty when the drawing failed.
    pub screenshot_png_base64: String,
    /// The DOM as HTML. Empty when the copy failed.
    pub dom_html: String,
}

/// Which reports the administration list shows.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize, Default)]
pub enum FeedbackStatusFilter {
    /// Reports that are not archived.
    #[default]
    Open,
    /// Reports that are not archived and not read.
    Unread,
    /// Archived reports only.
    Archived,
    /// Every report.
    All,
}

impl FeedbackStatusFilter {
    pub const ALL: [Self; 4] = [Self::Open, Self::Unread, Self::Archived, Self::All];

    /// The value in the page address.
    pub fn as_param(self) -> &'static str {
        match self {
            Self::Open => "open",
            Self::Unread => "unread",
            Self::Archived => "archived",
            Self::All => "all",
        }
    }

    /// The value from the page address. An unknown value gives the default.
    pub fn from_param(value: &str) -> Self {
        Self::ALL
            .into_iter()
            .find(|s| s.as_param() == value)
            .unwrap_or_default()
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Open => "Not archived",
            Self::Unread => "Unread",
            Self::Archived => "Archived",
            Self::All => "All",
        }
    }
}

/// One row of the administration list.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, Default)]
pub struct FeedbackListRow {
    pub report_id: String,
    pub kind: String,
    pub title: String,
    pub description: String,
    pub username: String,
    pub page_url: String,
    pub context_json: String,
    pub screenshot_bytes: u64,
    pub dom_bytes: u64,
    /// RFC 3339, UTC.
    pub created_at: String,
    pub is_read: bool,
    pub is_archived: bool,
}

/// One page of the administration list, with the count of every matching report.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, Default)]
pub struct FeedbackPage {
    pub rows: Vec<FeedbackListRow>,
    pub total: u64,
}

/// Is `value` a lowercase hyphenated UUID? The upload route uses the report id in an
/// object key, so it accepts no other form.
pub fn is_report_id(value: &str) -> bool {
    let groups: Vec<&str> = value.split('-').collect();
    groups.len() == 5
        && groups
            .iter()
            .zip([8, 4, 4, 4, 12])
            .all(|(g, n)| g.len() == n && g.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn report_ids_are_lowercase_uuids() {
        assert!(is_report_id("6f1a3c2e-1b2c-4d5e-8f90-0123456789ab"));
        assert!(!is_report_id("6F1A3C2E-1B2C-4D5E-8F90-0123456789AB"));
        assert!(!is_report_id("../../etc/passwd"));
        assert!(!is_report_id("6f1a3c2e-1b2c-4d5e-8f90-0123456789ab-"));
        assert!(!is_report_id(""));
    }

    #[test]
    fn status_filter_reads_its_own_param() {
        for s in FeedbackStatusFilter::ALL {
            assert_eq!(FeedbackStatusFilter::from_param(s.as_param()), s);
        }
        assert_eq!(FeedbackStatusFilter::from_param(""), FeedbackStatusFilter::Open);
    }
}
