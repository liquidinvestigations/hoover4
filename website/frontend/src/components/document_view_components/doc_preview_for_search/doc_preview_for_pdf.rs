use common::document_text_sources::{DocumentTextSourceHit, DocumentTextSourceHitCount, DocumentTextSourceItem};
use common::pdf_to_html_conversion::PDFToHtmlConversionResponse;
use dioxus::logger::tracing;
use dioxus::prelude::*;
use common::search_query::SearchQuery;
use common::search_result::DocumentIdentifier;

use crate::components::document_view_components::doc_title_bar::DocTitleBar;
use crate::components::document_view_components::raw_metadata_collector::RawMetadataCollector;
use crate::components::suspend_boundary::LoadingIndicator;
use crate::pages::search_page::DocViewerStateControl;



#[server]
pub async fn get_document_type_is_pdf(document_identifier: DocumentIdentifier) -> Result<(bool, u32), ServerFnError> {
    let (is_pdf, page_count) = backend::api::documents::get_pdf_to_html_conversion::get_document_type_is_pdf(document_identifier).await.map_err(|e| ServerFnError::from(e))?;
    Ok((is_pdf, page_count))
}


#[component]
pub fn DocumentPreviewForPdf(
    document_identifier: ReadSignal<DocumentIdentifier>,
    page_count: ReadSignal<u32>,
) -> Element {
    let current_page_index = use_signal(move || 0_u32);
    let pdf_to_html_conversion = use_resource(move || {
        let document_identifier = document_identifier.read().clone();
        let current_page_index = current_page_index.read().clone();
        async move {
            let pdf_to_html_conversion = get_pdf_to_html_single_page(document_identifier, current_page_index).await;
            pdf_to_html_conversion
        }
    });
    let data_viewer = match pdf_to_html_conversion.read().clone() {
        Some(Ok(pdf_to_html_conversion)) => {
            rsx! {
                PDFDataViewer { pdf_to_html_conversion }
            }
        }
        Some(Err(e)) => {
            return rsx! {
                pre {
                    style: "color:red; font-size: 26px; border: 1px solid red; padding: 10px; border-radius: 5px; margin: 15px;",
                    "{e:#?}"
                }
            }
        }
        None => {
            return rsx! {
                div {
                    style: "width: 90%; height: 60px;",
                    LoadingIndicator {  }
                }
            }
        }
    };
    rsx! {
        {data_viewer}
        PdfControllerOverlay { page_count, current_page_index }
    }
}

#[component]
fn PdfControllerOverlay(page_count: ReadSignal<u32>, current_page_index: Signal<u32>) -> Element {
    let mut current_page = current_page_index;
    let page_count = page_count();

    rsx! {
        div {
            style: "position: relative; width: 0; height: 0; bottom: 0; right: 0; float: right; z-index: 100;",
            div {
                style: "position: absolute; bottom: 20px; right: 20px; background: white; border: 1px solid #ccc; border-radius: 8px; display: flex; flex-direction: column; align-items: center; padding: 4px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); width: 40px;",

                div {
                    style: "font-size: 14px; font-weight: bold; margin-bottom: 4px; padding: 4px; border-bottom: 1px solid #eee; width: 100%; text-align: center;",
                    "{current_page() + 1}"
                }

                div {
                    style: "font-size: 14px; color: #666; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid #eee; width: 100%; text-align: center;",
                    "{page_count}"
                }

                button {
                    style: "background: none; border: none; cursor: pointer; font-size: 20px; padding: 4px; margin: 2px 0;",
                    onclick: move |_| {
                        if current_page() > 0 {
                            current_page -= 1;
                        }
                    },
                    "🔼"
                }

                button {
                    style: "background: none; border: none; cursor: pointer; font-size: 20px; padding: 4px; margin: 2px 0;",
                    onclick: move |_| {
                        if current_page() < page_count - 1 {
                            current_page += 1;
                        }
                    },
                    "🔽"
                }

                button {
                    style: "background: none; border: none; cursor: default; font-size: 20px; padding: 4px; margin: 2px 0; opacity: 0.3;",
                    disabled: true,
                    "➕"
                }

                button {
                    style: "background: none; border: none; cursor: default; font-size: 20px; padding: 4px; margin: 2px 0; opacity: 0.3;",
                    disabled: true,
                    "➖"
                }
            }
        }
    }
}
#[component]
fn PDFDataViewer(pdf_to_html_conversion: ReadSignal<PDFToHtmlConversionResponse>) -> Element {
    let page_width_px = use_memo(move || {
        pdf_to_html_conversion.read().page_width_px
    });
    let page_height_px = use_memo(move || {
        pdf_to_html_conversion.read().page_height_px
    });
    let aspect_ratio = use_memo(move || {
        page_width_px() / page_height_px()
    });

    let html_content = use_memo(move || {

        let styles = pdf_to_html_conversion.read().clone().styles.join("\n");
        let page_idx = 0;
        let page_content = pdf_to_html_conversion.read().clone().pages[page_idx].clone();
        let page_content = format!("{styles}\n{page_content}");

        let page_content = parse_html::search_snippet(&page_content, "Adobe");



        let text_content = parse_html::extract_text_from_html(&page_content).unwrap_or_default();
        info!("Text content: {text_content}");
        rsx! {
            iframe {
                srcdoc: "{page_content}",
                style: "width: {page_width_px+60.0}px; height: {page_height_px+60.0}px;  aspect-ratio: {aspect_ratio};",
            }
        }
    });

    let mut resize_info = use_signal(move || (page_width_px(), page_height_px()));
    let mut scale_factor = use_memo(move || {
        let rx = resize_info.read().0 / (page_width_px() + 60.0);
        let ry = resize_info.read().1 / (page_height_px() + 60.0);
        let min_scale_factor = rx.min(ry);
        min_scale_factor
    });



    rsx! {
        div {
            style: "height: 50px; font-size: 40px;",
            "TODO HEADER"
        }
        div {
            style: "aspect-ratio: {aspect_ratio};width: 100%;height: calc(100% - 50px);",
            onresize: move |e| {
                let Ok(size) = e.data().clone().get_border_box_size() else {
                    tracing::error!("Failed to get border box size: {:#?}", e.data());
                    return;
                };
                // tracing::info!("Border box size: {:#?}", size);

                resize_info.set((size.width as f32, size.height as f32));
            },

            div {
                style: "transform: scale({scale_factor}); transform-origin: top left;",
                {html_content()}
            }
        }
    }
}

#[server]
async fn get_pdf_to_html_single_page(document_identifier: DocumentIdentifier, page_index: u32) -> Result<PDFToHtmlConversionResponse, ServerFnError> {
    let pdf_to_html_conversion = backend::api::documents::get_pdf_to_html_conversion::
    get_pdf_to_html_single_page(document_identifier, page_index).await.map_err(|e| ServerFnError::from(e));
    pdf_to_html_conversion
}


mod parse_html {
    use std::cell::RefCell;

    use html5ever::tokenizer::{BufferQueue, TagKind::{EndTag, StartTag}, Token::{self, CharacterTokens, TagToken}, TokenSink, TokenSinkResult, Tokenizer, TokenizerOpts};

    #[derive(Debug, Clone)]
    struct Snippet {
        text: String,
        start: usize,
        end: usize,
    }

    struct TextExtractor {
        snippets: RefCell<Vec<Snippet>>,
        in_skip_tag: RefCell<u32>,
        current_pos: RefCell<usize>,
    }

    impl TokenSink for TextExtractor {
        type Handle = ();

        fn process_token(&self, token: Token, _line_number: u64) -> TokenSinkResult<()> {
            let mut in_skip_tag = self.in_skip_tag.borrow_mut();
            let mut snippets = self.snippets.borrow_mut();
            let mut current_pos = self.current_pos.borrow_mut();

            match token {
                TagToken(tag) => {
                    let tag_name = tag.name.as_ref();
                    if tag_name == "script" || tag_name == "style" {
                        match tag.kind {
                            StartTag => *in_skip_tag += 1,
                            EndTag => *in_skip_tag = in_skip_tag.saturating_sub(1),
                        }
                    }
                }
                CharacterTokens(tendril) => {
                    if *in_skip_tag == 0 {
                        let text = tendril.to_string();
                        let len = text.len();
                        snippets.push(Snippet {
                            text,
                            start: *current_pos,
                            end: *current_pos + len,
                        });
                    }
                }
                _ => {}
            }
            // Note: This tokenizer doesn't easily give us the byte offset in the original string
            // through the TokenSink interface directly for every token in a way that maps back to the input &str.
            // However, for the purpose of this task, we will assume the caller provides the positions
            // or we track them if we were feeding it differently.
            // Actually, html5ever's tokenizer doesn't expose byte offsets to process_token easily.
            // Let's rethink: if we want to "apply highlighting on each one... and return the completed html",
            // we need to know where these snippets are in the original `page` string.

            TokenSinkResult::Continue
        }
    }

    pub(crate) fn search_snippet(page: &str, query: &str) -> String {
        if query.is_empty() {
            return page.to_string();
        }

        // let mut snippets: Vec<_> = Vec::new();
        let mut current_pos = 0;

        // We need a way to track positions. Since html5ever doesn't give them easily,
        // we'll do a manual pass to find text nodes if we want exact offsets,
        // OR we can use a simpler approach if the HTML is predictable (like from pdf2html).
        // But let's try to stick to the requirement: "store extra information... for each tag snippet... entry/exit location".

        // To get offsets, we can use a custom tokenizer or just find the text in the original string.
        // Given pdf2html output is usually lots of <div>text</div>, we can try to find the text.

        let sink = TextExtractor {
            snippets: RefCell::new(Vec::new()),
            in_skip_tag: RefCell::new(0),
            current_pos: RefCell::new(0),
        };

        let mut input = BufferQueue::default();
        input.push_back(page.to_string().into());

        let tokenizer = Tokenizer::new(
            sink,
            TokenizerOpts::default(),
        );
        let _ = tokenizer.feed(&input);
        tokenizer.end();

        let extracted_snippets = tokenizer.sink.snippets.borrow().clone();

        // Now we need to find where these snippets actually are in the original `page` string
        // to be able to reconstruct it with highlights.
        let mut snippets_with_offsets = Vec::new();
        let mut last_search_pos = 0;
        for s in extracted_snippets {
            if let Some(pos) = page[last_search_pos..].find(&s.text) {
                let actual_start = last_search_pos + pos;
                let actual_end = actual_start + s.text.len();
                snippets_with_offsets.push(Snippet {
                    text: s.text,
                    start: actual_start,
                    end: actual_end,
                });
                last_search_pos = actual_end;
            }
        }

        if snippets_with_offsets.is_empty() {
            return page.to_string();
        }

        // Combine all snippet text to search across them
        let full_text: String = snippets_with_offsets.iter().map(|s| s.text.as_str()).collect();
        let query_lower = query.to_lowercase();
        let full_text_lower = full_text.to_lowercase();

        let mut highlights = Vec::new(); // (snippet_idx, start_in_snippet, end_in_snippet)
        let mut search_start = 0;

        while let Some(match_start) = full_text_lower[search_start..].find(&query_lower) {
            let match_start = search_start + match_start;
            let match_end = match_start + query.len();

            // Map match_start and match_end back to snippets
            let mut current_full_pos = 0;
            for (idx, s) in snippets_with_offsets.iter().enumerate() {
                let snippet_len = s.text.len();
                let snippet_full_start = current_full_pos;
                let snippet_full_end = current_full_pos + snippet_len;

                let overlap_start = match_start.max(snippet_full_start);
                let overlap_end = match_end.min(snippet_full_end);

                if overlap_start < overlap_end {
                    highlights.push((
                        idx,
                        overlap_start - snippet_full_start,
                        overlap_end - snippet_full_start,
                    ));
                }

                current_full_pos = snippet_full_end;
            }
            search_start = match_start + 1;
        }

        if highlights.is_empty() {
            return page.to_string();
        }

        // Sort highlights by snippet index and then by start position (descending to replace from back)
        highlights.sort_by(|a, b| b.0.cmp(&a.0).then(b.1.cmp(&a.1)));

        let mut result_page = page.to_string();

        for (s_idx, h_start, h_end) in highlights {
            let snippet = &snippets_with_offsets[s_idx];
            // We need to be careful here. Replacing in the middle of the page string
            // will shift offsets. It's better to rebuild the string or use a more robust replacement.
            // Since we sorted by snippet index and start pos descending, we can replace safely
            // IF we know the absolute position in the original `page`.

            let abs_start = snippet.start + h_start;
            let abs_end = snippet.start + h_end;

            let highlight_part = &result_page[abs_start..abs_end];
            let highlighted = format!("<b style=\"background:red\">{}</b>", highlight_part);
            result_page.replace_range(abs_start..abs_end, &highlighted);
        }

        result_page
    }

    pub(crate) fn extract_text_from_html(page: &str) -> anyhow::Result<String> {
        let sink = TextExtractor {
            snippets: RefCell::new(Vec::new()),
            in_skip_tag: RefCell::new(0),
            current_pos: RefCell::new(0),
        };

        let mut input = BufferQueue::default();
        input.push_back(page.to_string().into());

        let tokenizer = Tokenizer::new(
            sink,
            TokenizerOpts::default(),
        );
        let _ = tokenizer.feed(&input);
        tokenizer.end();

        let text_content: String = tokenizer.sink.snippets.borrow().iter().map(|s| s.text.as_str()).collect();
        Ok(text_content)
    }
}