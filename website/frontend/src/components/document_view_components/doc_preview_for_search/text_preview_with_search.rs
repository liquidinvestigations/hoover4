use common::document_sources::{
    DocumentTextSourceHit, DocumentTextSourceHitCount, DocumentTextSourceItem,
};
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use dioxus_free_icons::icons::md_navigation_icons::{MdArrowDownward, MdArrowUpward};

use crate::components::document_view_components::doc_preview_shared::PreviewWrapper;
use crate::components::{
    document_view_components::doc_preview_for_search::text_data_viewer,
    search_components::search_result_list_controls::NavigationButton,
};
use crate::pages::search_page::DocViewerStateControl;

#[derive(Debug, Clone, PartialEq, Copy)]
pub struct DocumentViewerResultStore {
    pub hit_counts: ReadSignal<Option<Vec<DocumentTextSourceHitCount>>>,
    pub current_text_data: ReadSignal<Option<Result<Vec<DocumentTextSourceHit>, ServerFnError>>>,
    pub max_highlighted_word_index: ReadSignal<u32>,
    pub current_highlighted_word_index: Signal<u32>,
}

#[component]
pub fn DocumentPreviewTextWithSearch(
    document_identifier: ReadSignal<DocumentIdentifier>,
    source: ReadSignal<DocumentTextSourceItem>,
    preamble: Element,
) -> Element {
    // ============== HIT COUNTS: ==============
    let control_state = use_context::<DocViewerStateControl>().doc_viewer_state;
    let find_query = use_memo(move || {
        let Some(state) = &control_state.read().clone() else {
            return "".to_string();
        };
        state.find_query.clone()
    });
    let mut hit_counts_res = use_resource(move || {
        let doc_id = document_identifier.read().clone();
        let find_query = find_query.read().clone();
        search_document_text_for_hit_count(doc_id, find_query)
    });
    use_effect(move || {
        let _doc_id = document_identifier.read().clone();
        let _find_query = find_query.read().clone();
        hit_counts_res.clear();
        hit_counts_res.restart();
    });
    let hit_counts_memo: Memo<Option<Vec<DocumentTextSourceHitCount>>> = use_memo(move || {
        let hit_counts_res = hit_counts_res.read().cloned();
        let Some(Ok(hit_counts)) = hit_counts_res else {
            return None;
        };
        Some(hit_counts)
    });

    // ================ CURRENT SELECTION: ================
    let current_text_selection: Memo<Option<(String, u32)>> = use_memo(move || {
        let hit_counts = hit_counts_memo.read().clone();
        let source = source.read().clone();

        let Some(hit_counts) = hit_counts else {
            return None;
        };
        let mut hit_counts = hit_counts
            .iter()
            .filter(|h| h.extracted_by == source.extracted_by)
            .collect::<Vec<_>>();
        if hit_counts.is_empty() {
            return Some((source.extracted_by, source.min_page));
        }
        hit_counts.sort_by_key(|h| h.hit_count as i64 * -1);
        Some((hit_counts[0].extracted_by.clone(), hit_counts[0].page_id))
    });

    // ================ CURRENT TEXT DATA: ================
    let current_text_data: Resource<Result<Vec<DocumentTextSourceHit>, ServerFnError>> =
        use_resource(move || {
            let current_text_selection = current_text_selection.read().clone();
            let document_identifier = document_identifier.read().clone();
            let find_query = find_query.read().clone();
            async move {
                let Some((extracted_by, page_id)) = current_text_selection else {
                    return Err(ServerFnError::from(anyhow::anyhow!(
                        "No current text selection"
                    )));
                };
                search_document_text_for_hits(
                    document_identifier,
                    find_query,
                    extracted_by,
                    page_id,
                )
                .await
            }
        });

    // ================ HIGHLIGHTED WORD INDEX: ================
    let mut max_highlighted_word_index = use_signal(move || 0);
    use_effect(move || {
        let selection = current_text_selection.read().clone();
        let hits = hit_counts_memo.read().clone();
        let (Some(selection), Some(hits)) = (&selection, &hits) else {
            max_highlighted_word_index.set(0);
            return;
        };
        let Some(selected_item) = hits
            .iter()
            .find(|h| h.extracted_by == selection.0 && h.page_id == selection.1)
            .cloned()
        else {
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
        hit_counts: hit_counts_memo.into(),
        current_text_data: current_text_data.into(),
        max_highlighted_word_index: max_highlighted_word_index.into(),
        current_highlighted_word_index,
    });

    rsx! {
        PreviewWrapper {
            controls: rsx! {
                SearchHitSelector {}
            },
            page: rsx! {
                div {
                    style: "
                        height: 100%;
                        width: 100%;
                        display: flex;
                        flex-direction: column;
                        overflow: hidden;
                    ",
                    {preamble}
                    div {
                        style: "flex: 1; min-height: 0;",
                        text_data_viewer::TextDataViewer {}
                    }
                }
            }
        }
    }
}

#[component]
fn SearchHitSelector() -> Element {
    let max_highlighted_word_index =
        use_context::<DocumentViewerResultStore>().max_highlighted_word_index;
    let mut current_highlighted_word_index =
        use_context::<DocumentViewerResultStore>().current_highlighted_word_index;
    let have_hits = use_memo(move || *max_highlighted_word_index.read() > 0);
    let hit_string = use_memo(move || {
        if have_hits() {
            let current = 1 + *current_highlighted_word_index.read();
            let max = *max_highlighted_word_index.read();
            format!("{current} / {max}")
        } else {
            "- / -".to_string()
        }
    });
    let disable_next = use_memo(move || {
        !have_hits()
            || *current_highlighted_word_index.read() + 1 >= *max_highlighted_word_index.read()
    });
    let disable_previous =
        use_memo(move || !have_hits() || *current_highlighted_word_index.read() == 0);

    rsx! {
        div {
            style: "
                flex-grow: 0;
                flex-shrink: 0;
                display: flex;
                flex-direction: row;
                align-items: center;
                justify-content: center;
                gap: 12px;
                padding: 12px;
            ",
            NavigationButton { icon: MdArrowUpward, label: "Previous Hit", disabled: disable_previous, onclick: move |_| {
                *current_highlighted_word_index.write() -= 1;
            } }
            div { style: "min-width: 60px; font-size: 20px; line-height: 28px;", "{hit_string()}" }
            NavigationButton { icon: MdArrowDownward, label: "Next Hit", disabled: disable_next, onclick: move |_| {
                *current_highlighted_word_index.write() += 1;
            } }
        }
    }
}

#[server]
async fn search_document_text_for_hit_count(
    document_identifier: DocumentIdentifier,
    find_query: String,
) -> Result<Vec<DocumentTextSourceHitCount>, ServerFnError> {
    backend::api::documents::search_document_text::search_document_text_for_hit_count(
        document_identifier,
        find_query,
    )
    .await
    .map_err(|e| ServerFnError::from(e))
}

#[server]
async fn search_document_text_for_hits(
    document_identifier: DocumentIdentifier,
    find_query: String,
    extracted_by: String,
    page_id: u32,
) -> Result<Vec<DocumentTextSourceHit>, ServerFnError> {
    backend::api::documents::search_document_text::search_document_text_for_hits(
        document_identifier,
        find_query,
        extracted_by,
        page_id,
    )
    .await
    .map_err(|e| ServerFnError::from(e))
}
