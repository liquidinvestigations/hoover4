use std::collections::BTreeMap;
use std::cell::RefCell;
use html5ever::tendril::TendrilSink;
use html5ever::tokenizer::{Token, TokenSink, TokenSinkResult, Tokenizer, TokenizerOpts, BufferQueue, TagToken, StartTag, EndTag, CharacterTokens};

use common::search_result::DocumentIdentifier;

use crate::api::documents::get_pdf_to_html_conversion::get_pdf_to_html_conversion;

pub async fn search_html_preview_hit_counts(document_identifier: DocumentIdentifier ,query: String) -> anyhow::Result<BTreeMap<u32, u32>> {
    let doc = get_pdf_to_html_conversion(document_identifier).await?;

    let counts = doc.pages.iter().enumerate().map(|(page_index, page)| {
        let page_index = page_index as u32;
        let page_hits = match _count_html_page_hits(page, &query) {
            Ok(hits) => hits,
            Err(e) => {
                tracing::error!("Error counting page hits: {}", e);
                0_u32
            },
        };
        (page_index, page_hits)
    }).collect::<BTreeMap<u32, u32>>();
    Ok(counts)
}

struct TextExtractor {
    text: RefCell<String>,
    in_skip_tag: RefCell<u32>,
}

impl TokenSink for TextExtractor {
    type Handle = ();

    fn process_token(&self, token: Token, _line_number: u64) -> TokenSinkResult<()> {
        match token {
            TagToken(tag) => {
                let tag_name = tag.name.as_ref();
                if tag_name == "script" || tag_name == "style" {
                    match tag.kind {
                        StartTag => *self.in_skip_tag.borrow_mut() += 1,
                        EndTag => *self.in_skip_tag.borrow_mut() = self.in_skip_tag.borrow().saturating_sub(1),
                    }
                }
            }
            CharacterTokens(tendril) => {
                if *self.in_skip_tag.borrow() == 0 {
                    let mut text = self.text.borrow_mut();
                    text.push_str(&tendril);
                    text.push(' ');
                }
            }
            _ => {}
        }
        TokenSinkResult::Continue
    }
}

fn _count_html_page_hits(page: &str, query: &str) -> anyhow::Result<u32> {
    let sink = TextExtractor {
        text: RefCell::new(String::new()),
        in_skip_tag: RefCell::new(0),
    };

    let mut input = BufferQueue::default();
    input.push_back(page.to_string().into());

    let tokenizer = Tokenizer::new(
        sink,
        TokenizerOpts::default(),
    );
    let _ = tokenizer.feed(&input);
    tokenizer.end();

    let query = query.to_lowercase();
    let text_content = tokenizer.sink.text.borrow().to_lowercase();

    let count = text_content.matches(&query).count() as u32;
    Ok(count)
}
