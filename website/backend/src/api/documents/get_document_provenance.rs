//! The two curated sections at the top of the Metadata tab: **Dates** and **Email**.
//!
//! The rest of that tab is a dump of every ClickHouse row that mentions the document,
//! which is exhaustive and unreadable. These two are the questions people actually
//! arrive with:
//!
//! * "Why did my date filter miss this?". The Dates section shows every date the
//!   indexer confirmed AND where each one came from. A document with no dates says so
//!   explicitly, because "no Dates section" and "no dates" look identical otherwise, and
//!   only one of them is an answer.
//! * "Who was on this email?". The raw `addresses` column is a flat
//!   `"from: A; to: B, C"` string. The structured rows are what the filters use, so
//!   showing the same rows is also showing why a sender filter did or did not match.

use common::current_user::CurrentUser;
use common::document_provenance::{DocumentDates, DocumentEmail, EmailParticipant, ResolvedDate};
use common::search_result::DocumentIdentifier;

use crate::auth::permissions;
use crate::db_utils::clickhouse_utils::get_client_for_dataset;

/// Every confirmed date of one document, ascending, deduplicated, with provenance.
pub async fn get_document_dates(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<DocumentDates> {
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
    // FINAL: `document_dates` is a ReplacingMergeTree and a re-parse leaves two rows for
    // the same (hash, date, source) until the merge runs. Without it the viewer shows
    // the same date twice and looks broken.
    let rows: Vec<(i64, String)> = client
        .query(
            "SELECT date, source FROM document_dates FINAL
             WHERE collection_dataset = ? AND hash = ?
             ORDER BY date ASC, source ASC",
        )
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_all()
        .await?;

    let mut dates: Vec<ResolvedDate> = Vec::new();
    for (epoch_seconds, source) in rows {
        // Deduplicate on the pair, not on the date: two different keys agreeing on an
        // instant is information (it is the same date, confirmed twice), and collapsing
        // them would hide the corroboration.
        if dates
            .last()
            .is_some_and(|last| last.epoch_seconds == epoch_seconds && last.source == source)
        {
            continue;
        }
        dates.push(ResolvedDate { epoch_seconds, source });
    }
    Ok(DocumentDates { dates })
}

/// The email header of one document, or `None` when it is not an email.
pub async fn get_document_email(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Option<DocumentEmail>> {
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;

    let headers: Vec<(String, i64, u8)> = client
        .query(
            "SELECT subject, toInt64(date_sent), date_sent_known FROM email_headers FINAL
             WHERE collection_dataset = ? AND email_hash = ? LIMIT 1",
        )
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_all()
        .await?;
    let Some((subject, date_sent, date_sent_known)) = headers.into_iter().next() else {
        return Ok(None);
    };

    let participants: Vec<(String, String, String)> = client
        .query(
            "SELECT toString(role), address, display_name FROM email_addresses FINAL
             WHERE collection_dataset = ? AND email_hash = ?
             ORDER BY role, address",
        )
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_all()
        .await?;

    // Whether this email is also a container, i.e. whether it has attachments. The same
    // question `struct_flags` bit 0 answers for search; asked directly here so the
    // viewer does not depend on the search index being current.
    let attachments: Vec<u64> = client
        .query(
            "SELECT count() FROM vfs_files FINAL
             WHERE collection_dataset = ? AND container_hash = ?",
        )
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_all()
        .await?;

    Ok(Some(DocumentEmail {
        subject,
        // The epoch is the "no Date: header" fallback as well as a real instant, so the
        // flag decides whether there is a date to show at all.
        date_sent: (date_sent_known == 1).then_some(date_sent),
        participants: participants
            .into_iter()
            .map(|(role, address, display_name)| EmailParticipant {
                role,
                address,
                display_name,
            })
            .collect(),
        attachment_count: attachments.into_iter().next().unwrap_or(0),
    }))
}
