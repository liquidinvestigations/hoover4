//! What the viewer's Dates and Email sections show.
//!
//! These carry PROVENANCE, not just values. A date without its source answers "when" and
//! not "why the filter behaved that way", and the second question is the one that brings
//! people to this tab.

use serde::{Deserialize, Serialize};

/// One confirmed date and the metadata key it came from.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResolvedDate {
    /// Signed epoch seconds. Negative for documents predating 1970, which is why this is
    /// an `i64` everywhere rather than a `u32` timestamp.
    pub epoch_seconds: i64,
    /// `tika:dcterms:created`, `email:date`, `archive:mtime`, …
    pub source: String,
}

impl ResolvedDate {
    /// A short label for the source. `tika:dcterms:created` reads as `dcterms:created`
    /// with the provider shown separately, because the provider is the same for most
    /// rows and repeating it eight times is noise.
    pub fn source_key(&self) -> &str {
        self.source.split_once(':').map_or(self.source.as_str(), |(_, rest)| rest)
    }

    pub fn source_provider(&self) -> &str {
        self.source.split_once(':').map_or("", |(provider, _)| provider)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct DocumentDates {
    pub dates: Vec<ResolvedDate>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EmailParticipant {
    /// `from` / `to` / `cc` / `bcc`.
    pub role: String,
    /// Lower-cased `local@domain`.
    pub address: String,
    /// As written in the header; empty when the header had none.
    pub display_name: String,
}

impl EmailParticipant {
    /// `Terry Kafka <t.kafka@example.com>`, or just the address when there is no name.
    pub fn display(&self) -> String {
        if self.display_name.is_empty() {
            self.address.clone()
        } else {
            format!("{} <{}>", self.display_name, self.address)
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DocumentEmail {
    pub subject: String,
    /// `None` when the `Date:` header was absent or unparseable — NOT the epoch, which
    /// is both the fallback and a real instant.
    pub date_sent: Option<i64>,
    pub participants: Vec<EmailParticipant>,
    /// Files whose container is this email. Zero means no attachments.
    pub attachment_count: u64,
}

impl DocumentEmail {
    pub fn participants_with_role(&self, role: &str) -> Vec<&EmailParticipant> {
        self.participants.iter().filter(|p| p.role == role).collect()
    }
}

/// `YYYY-MM-DD HH:MM` UTC for a signed epoch-second value.
///
/// Written out rather than pulled from a date crate because it must be right for
/// negative values, and because this crate is compiled to wasm where every extra
/// dependency is bytes on the wire.
pub fn format_epoch_utc(epoch_seconds: i64) -> String {
    let days = epoch_seconds.div_euclid(86_400);
    let seconds_of_day = epoch_seconds.rem_euclid(86_400);
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    let (hour, minute) = (seconds_of_day / 3_600, (seconds_of_day % 3_600) / 60);
    format!("{y:04}-{m:02}-{d:02} {hour:02}:{minute:02} UTC")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn epochs_format_including_before_1970() {
        assert_eq!(format_epoch_utc(0), "1970-01-01 00:00 UTC");
        assert_eq!(format_epoch_utc(1_191_970_800), "2007-10-09 23:00 UTC");
        // The case a u32 timestamp cannot represent at all.
        assert_eq!(format_epoch_utc(-1_072_915_200), "1936-01-02 00:00 UTC");
        // rem_euclid, not %: a negative epoch with a non-zero time of day must not
        // produce a negative hour.
        assert_eq!(format_epoch_utc(-1), "1969-12-31 23:59 UTC");
    }

    #[test]
    fn a_source_splits_into_provider_and_key() {
        let date = ResolvedDate { epoch_seconds: 0, source: "tika:dcterms:created".to_string() };
        assert_eq!(date.source_provider(), "tika");
        assert_eq!(date.source_key(), "dcterms:created");

        let email = ResolvedDate { epoch_seconds: 0, source: "email:date".to_string() };
        assert_eq!(email.source_provider(), "email");
        assert_eq!(email.source_key(), "date");

        // A source with no colon degrades to the whole string rather than to empty.
        let bare = ResolvedDate { epoch_seconds: 0, source: "unknown".to_string() };
        assert_eq!(bare.source_key(), "unknown");
        assert_eq!(bare.source_provider(), "");
    }

    #[test]
    fn a_participant_without_a_display_name_shows_its_address() {
        let named = EmailParticipant {
            role: "from".to_string(),
            address: "a@b.com".to_string(),
            display_name: "A Person".to_string(),
        };
        assert_eq!(named.display(), "A Person <a@b.com>");
        let bare = EmailParticipant { display_name: String::new(), ..named };
        assert_eq!(bare.display(), "a@b.com");
    }

    #[test]
    fn participants_group_by_role() {
        let email = DocumentEmail {
            subject: "s".to_string(),
            date_sent: None,
            participants: vec![
                EmailParticipant { role: "from".to_string(), address: "a@b.com".to_string(), display_name: String::new() },
                EmailParticipant { role: "to".to_string(), address: "c@d.com".to_string(), display_name: String::new() },
                EmailParticipant { role: "to".to_string(), address: "e@f.com".to_string(), display_name: String::new() },
            ],
            attachment_count: 0,
        };
        assert_eq!(email.participants_with_role("from").len(), 1);
        assert_eq!(email.participants_with_role("to").len(), 2);
        assert!(email.participants_with_role("bcc").is_empty());
    }
}
