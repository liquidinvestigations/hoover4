use common::{document_metadata::DocumentMetadataTableInfo, search_result::DocumentIdentifier};

use crate::api::documents::get_raw_metadata::get_raw_metadata;

pub async fn get_document_type_is_pdf(
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<(bool, u32)> {
    let meta = get_raw_metadata(
        document_identifier,
        DocumentMetadataTableInfo::new("pdfs", "pdf_hash"),
    )
    .await?;
    let Some(obj) = meta.first() else {
        return Ok((false, 0));
    };
    let Some(page_count) = obj.get("page_count").and_then(|v| v.as_u64()) else {
        return Ok((false, 0));
    };
    Ok((true, page_count as u32))
}
