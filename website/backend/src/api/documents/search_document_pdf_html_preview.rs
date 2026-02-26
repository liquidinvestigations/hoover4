use std::collections::BTreeMap;
use std::cell::RefCell;
use html5ever::tendril::TendrilSink;
use html5ever::tokenizer::{Token, TokenSink, TokenSinkResult, Tokenizer, TokenizerOpts, BufferQueue, TagToken, StartTag, EndTag, CharacterTokens};

use common::search_result::DocumentIdentifier;

use crate::api::documents::get_pdf_to_html_conversion::get_pdf_to_html_conversion;

// pub async fn search_html_preview_hit_counts(document_identifier: DocumentIdentifier ,query: String) -> anyhow::Result<BTreeMap<u32, u32>> {
//     let doc = get_pdf_to_html_conversion(document_identifier).await?;

//     let counts = doc.pages.iter().enumerate().map(|(page_index, page)| {
//         let page_index = page_index as u32;
//         let page_hits = match _count_html_page_hits(page, &query) {
//             Ok(hits) => hits,
//             Err(e) => {
//                 tracing::error!("Error counting page hits: {}", e);
//                 0_u32
//             },
//         };
//         (page_index, page_hits)
//     }).collect::<BTreeMap<u32, u32>>();
//     Ok(counts)
// }
