mod no_document_selected;
mod preview_subtitle_bar;
mod text_data_viewer;

use common::document_text_sources::{DocumentTextSourceHit, DocumentTextSourceHitCount, DocumentTextSourceItem};
use dioxus::prelude::*;
use common::search_query::SearchQuery;
use common::search_result::DocumentIdentifier;

use crate::components::document_view_components::doc_title_bar::DocTitleBar;
use crate::components::document_view_components::raw_metadata_collector::RawMetadataCollector;
use crate::pages::search_page::DocViewerStateControl;

#[component]
pub fn DocumentPreviewForSearchRoot(
    query: ReadSignal<SearchQuery>,
    selected_result_hash: ReadSignal<Option<DocumentIdentifier>>,
) -> Element {
    let Some(document_identifier) = selected_result_hash.read().clone() else {
        return rsx! {
            no_document_selected::NoDocumentSelected {}
        }
    };

    rsx! {
        DocumentPreviewForSearch { document_identifier }
    }
}

#[derive(Debug, Clone, PartialEq, Copy)]
pub struct DocumentViewerResultStore {
    pub hit_counts: ReadSignal<Option<Vec<DocumentTextSourceHitCount>>>,
    pub all_sources: ReadSignal<Vec<DocumentTextSourceItem>>,
    pub current_text_data: ReadSignal<Option<Result<Vec<DocumentTextSourceHit>, ServerFnError>>>,
    pub max_highlighted_word_index: ReadSignal<u32>,
    pub current_highlighted_word_index: Signal<u32>,
}


#[component]
fn DocumentPreviewForSearch(
    document_identifier: ReadSignal<DocumentIdentifier>,
) -> Element {


    // ============== ALL COUNTS: ==============
    let mut _all_counts_res = use_resource(move || {
        let _doc_id = document_identifier.read().clone();
        get_text_sources(_doc_id)
    });
    use_effect(move || {
        let _doc_id = document_identifier.read().clone();
        _all_counts_res.clear();
        _all_counts_res.restart();
    });
    let _all_counts_memo = use_memo(move || {
        let _all_counts_res = _all_counts_res.read().cloned();
        let Some(Ok(all_counts)) = _all_counts_res else { return vec![] };
        all_counts
    });

    // ============== HIT COUNTS: ==============
    let _control_state = use_context::<DocViewerStateControl>().doc_viewer_state;
    let _find_query = use_memo(move || {
        let _control_state = _control_state.read().clone();
        let Some(state) = &_control_state else { return "".to_string() };
        state.find_query.clone()
    });
    let mut _hit_counts_res = use_resource(move || {
        let _doc_id = document_identifier.read().clone();
        let _find_query = _find_query.read().clone();
        search_document_text_for_hit_count(_doc_id, _find_query)
    });
    use_effect(move || {
        let _doc_id = document_identifier.read().clone();
        let _find_query = _find_query.read().clone();
        _hit_counts_res.clear();
        _hit_counts_res.restart();
    });
    let _hit_counts_memo = use_memo(move || {
        let _hit_counts_res = _hit_counts_res.read().cloned();
        let Some(Ok(hit_counts)) = _hit_counts_res else { return None };
        dioxus::logger::tracing::info!("hit_counts: {:#?}", hit_counts);
        Some(hit_counts)
    });

    // ================ CURRENT SELECTION: ================
    let _current_text_selection: Memo<Option<(String, u32)>> = use_memo(move || {
        let hit_counts = _hit_counts_memo.read().clone();
        let _all_counts = _all_counts_memo.read().clone();

        let Some(mut hit_counts) = hit_counts else { return None };
        if hit_counts.is_empty() { return _all_counts.first().cloned().map(|item| (item.extracted_by, item.min_page)); }
        hit_counts.sort_by_key(|h| h.hit_count as i64 * -1);

        return Some((hit_counts[0].extracted_by.clone(), hit_counts[0].page_id));

    });

    // ================ CURRENT TEXT DATA: ================
    let _current_text_data: Resource<std::result::Result<Vec<DocumentTextSourceHit>, ServerFnError>> = use_resource(move || {
        let _current_text_selection = _current_text_selection.read().clone();
        let document_identifier = document_identifier.read().clone();
        let find_query = _find_query.read().clone();
        async move {
            let Some((extracted_by, page_id)) = _current_text_selection else {
                return Err(ServerFnError::from(anyhow::anyhow!("No current text selection"))) };
            let item = search_document_text_for_hits(
                document_identifier, find_query, extracted_by, page_id).await;
            item
        }
    });

    // ================ HIGHLIGHTED WORD INDEX: ================
    let mut max_highlighted_word_index = use_signal(move || 0);
    use_effect(move || {
        let _selection = _current_text_selection.read().clone();
        let _hits = _hit_counts_memo.read().clone();
        let (Some(selection), Some(hits))= (&_selection, &_hits) else {
            max_highlighted_word_index.set(0);
            return;
        };
        let Some(selected_item) = hits.iter().find(|h| h.extracted_by == selection.0 && h.page_id == selection.1).cloned() else {
            max_highlighted_word_index.set(0);
            return;
        };
        max_highlighted_word_index.set(selected_item.hit_count as u32);
    });
    let mut current_highlighted_word_index = use_signal(move || 0);
    use_effect(move || {
        let _max = *max_highlighted_word_index.read();
        current_highlighted_word_index.set(0);
    });


    use_context_provider(move || DocumentViewerResultStore {
        hit_counts: _hit_counts_memo.into(),
        all_sources: _all_counts_memo.into(),
        current_text_data: _current_text_data.into(),
        max_highlighted_word_index: max_highlighted_word_index.into(),
        current_highlighted_word_index: current_highlighted_word_index,
    });

    rsx! {
        div {
            style: "
                display: flex;
                flex-direction: column;
                height: 100%;
                width: 100%;
            ",
            DocTitleBar { document_identifier }
            preview_subtitle_bar::PreviewSubtitleBar { document_identifier }
            div {
                style: "
                    width: 100%;
                    height: calc(100% - 54px - 48px);
                    flex-grow: 0;
                    flex-shrink: 0;
                    border-left: 1px solid rgba(0,0,0,.3);
                ",
                // RawMetadataCollector { document_identifier }
                text_data_viewer::TextDataViewer {}
            }
        }
    }
}

#[server]
async fn get_text_sources(document_identifier: DocumentIdentifier) -> Result<Vec<DocumentTextSourceItem>, ServerFnError> {
    let text_sources = backend::api::documents::get_text_sources::get_text_sources(document_identifier).await.map_err(|e| ServerFnError::from(e));
    text_sources
}
#[server]
async fn search_document_text_for_hit_count(document_identifier: DocumentIdentifier, find_query: String) -> Result<Vec<DocumentTextSourceHitCount>, ServerFnError> {
    let hit_counts = backend::api::documents::search_document_text::search_document_text_for_hit_count(document_identifier, find_query).await.map_err(|e| ServerFnError::from(e));
    hit_counts
}

#[server]
async fn search_document_text_for_hits(document_identifier: DocumentIdentifier, find_query: String, extracted_by: String, page_id: u32) -> Result<Vec<DocumentTextSourceHit>, ServerFnError> {
    let hits = backend::api::documents::search_document_text::search_document_text_for_hits(document_identifier, find_query, extracted_by, page_id).await.map_err(|e| ServerFnError::from(e));
    hits
}