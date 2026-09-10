use std::{cell::Cell, rc::Rc, sync::Arc};

use _js::*;
use common::{document_sources::DocumentPdfSourceItem, pdf_search_results::PdfSearchResults, search_result::DocumentIdentifier};
use dioxus::prelude::*;
use serde::{Deserialize, Serialize};
use wasm_bindgen::{JsValue, prelude::Closure};

/// The vendored EmbedPDF bundle, declared so `dx` ships the whole folder.
///
/// `#[used]` because nothing reads the binding: the viewer loads its entry point by
/// literal URL from a `<script>` tag, and without the attribute the constant is dropped
/// and the folder never reaches the bundle. `with_hash_suffix(false)` is what keeps the
/// served path `/assets/_viewer/…`, which [`PdfViewerJsScriptTag`] hardcodes, the two
/// have to be changed together.
#[used]
static EMBED_PDF_FOLDER: Asset = asset!(
    "/assets/embed-pdf/_viewer/",
    AssetOptions::folder().with_hash_suffix(false)
);

#[derive(Clone)]
pub struct PdfViewerControllerJs {
    inner: Arc<PdfViewerControllerInnerJs>,
}
impl PartialEq for PdfViewerControllerJs {
    fn eq(&self, other: &Self) -> bool {
        self.inner.pdf_url == other.inner.pdf_url
            && self.inner.loaded_event == other.inner.loaded_event
    }
}

struct PdfViewerControllerInnerJs {
    pdf_url: String,
    document_identifier: DocumentIdentifier,
    source: DocumentPdfSourceItem,
    loaded_event: PdfLoadedEvent,
    source_generation: u64,
    source_lifetime: Rc<Cell<u64>>,
    scroll_api: PdfScrollApi,
    search_api: PdfSearchApi,
    zoom_api: PdfZoomApi,
}

impl PdfViewerControllerJs {
    pub fn pdf_url(&self) -> String {
        self.inner.pdf_url.clone()
    }
    pub fn total_pages(&self) -> i32 {
        self.inner.loaded_event.totalPages
    }
    pub fn initial_page(&self) -> i32 {
        self.inner.loaded_event.pageNumber
    }
    fn document_id(&self) -> String {
        self.inner.loaded_event.documentId.clone()
    }
    fn is_active(&self) -> bool {
        self.inner.source_generation == self.inner.source_lifetime.get()
    }
}

#[derive(Clone, Copy, PartialEq)]
pub struct PdfViewerControllerDx {
    _controller: Signal<PdfViewerControllerJs>,
    pub current_page: ReadSignal<i32>,
    pub total_pages: ReadSignal<i32>,
    pub set_page: Callback<i32>,

    pub search_query: ReadSignal<String>,
    pub set_search_query: Callback<String>,
    pub search_hit_index: ReadSignal<i32>,
    pub search_hit_count: ReadSignal<i32>,
    pub set_search_idx: Callback<i32>,

    pub zoom_in: Callback<()>,
    pub zoom_out: Callback<()>,
    pub zoom_state: ReadSignal<String>,
}

fn scroll_to_page_options(page: i32, coord_x: f64, coord_y: f64, align_y: f64) -> JsValue {
    #[derive(Serialize)]
    struct PdfScrollToPageOptions {
        pageNumber: i32,
        behavior: String,
        pageCoordinates: PdfScrollToPageOptionsPoint,
        alignY: f64,
    }
    #[derive(Serialize)]
    struct PdfScrollToPageOptionsPoint {
        x: f64,
        y: f64,
    }
    let options = PdfScrollToPageOptions {
        pageNumber: page,
        behavior: "smooth".to_string(),
        pageCoordinates: PdfScrollToPageOptionsPoint {
            x: coord_x,
            y: coord_y,
        },
        alignY: align_y,
    };
    serde_wasm_bindgen::to_value(&options).expect("Failed to serialize scroll to page options")
}

pub fn use_pdf_controller(controller: PdfViewerControllerJs) -> PdfViewerControllerDx {
    let controller = use_signal(move || controller);

    // =========== PAGE NAVIGATION ============
    let mut current_page = use_signal(move || controller().initial_page());
    let total_pages = use_signal(move || controller().total_pages());
    let set_page = Callback::new(move |new_page: i32| {
        if !controller().is_active() {
            info!(
                "pdf-lifecycle skip-stale-scroll generation={} current={}",
                controller().inner.source_generation,
                controller().inner.source_lifetime.get()
            );
            return;
        }
        let new_page = new_page.clamp(1, total_pages());
        info!(
            "pdf-lifecycle rust-scroll-page generation={} document_id={} page={}",
            controller().inner.source_generation,
            controller().document_id(),
            new_page
        );
        controller().inner.scroll_api.scrollToPage(
            scroll_to_page_options(new_page, 0., 0., 0.),
            controller().document_id(),
        );
    });

    let controller_for_page_change = controller();
    let on_page_change = move |obj| {
        if !controller_for_page_change.is_active() {
            return;
        }
        #[derive(Debug, Deserialize)]
        struct PdfPageChangeEvent {
            pub pageNumber: i32,
        }
        let Ok(obj) = serde_wasm_bindgen::from_value::<PdfPageChangeEvent>(obj) else {
            error!("Failed to deserialize page change event");
            return;
        };
        current_page.set(obj.pageNumber);
    };
    let on_page_change = Closure::new(Box::new(on_page_change) as Box<dyn FnMut(JsValue)>);
    let on_page_change = on_page_change.into_js_value();
    controller().inner.scroll_api.onPageChange(on_page_change);

    // =========== SEARCH & HIT NAVIGATION ============
    let mut search_query = use_signal(move || "".to_string());
    let mut search_hit_index = use_signal(move || 0);
    let mut _sig_search_task: Signal<Option<dioxus_core::Task>> = use_signal(move || None);
    let mut search_generation = use_signal(move || 0_u64);
    let mut search_results = use_signal(move || PdfSearchResults {
        results: vec![],
        total: 0,
    });
    let search_hit_count = use_memo(move || search_results.read().results.len() as i32);

    let set_search_idx = Callback::new(move |new_idx: i32| {
        if !controller().is_active() {
            info!(
                "pdf-lifecycle skip-stale-search-hit generation={} current={}",
                controller().inner.source_generation,
                controller().inner.source_lifetime.get()
            );
            return;
        }
        if search_hit_count() == 0 {
            return;
        }
        let new_idx = new_idx.clamp(0, search_hit_count() - 1);
        search_hit_index.set(new_idx);

        let results = search_results.read();
        controller()
            .inner
            .search_api
            .goToResult(new_idx, controller().document_id());
        let scroll_opt = scroll_to_page_options(
            results.results[new_idx as usize].page_index + 1,
            results.results[new_idx as usize].rects[0].origin.x,
            results.results[new_idx as usize].rects[0].origin.y,
            40.,
        );
        controller()
            .inner
            .scroll_api
            .scrollToPage(scroll_opt, controller().document_id());
    });

    let set_search_query = Callback::new(move |new_query: String| {
        if !controller().is_active() {
            return;
        }
        let next_search_generation = *search_generation.peek() + 1;
        search_generation.set(next_search_generation);
        search_hit_index.set(0);
        search_results.set(PdfSearchResults {
            results: vec![],
            total: 0,
        });
        {
            if let Some(old_task) = _sig_search_task.write().take() {
                old_task.cancel();
            }
        }

        search_query.set(new_query.clone());
        let new_query = new_query.clone();
        let document_identifier = controller().inner.document_identifier.clone();
        let search_controller = controller();
        let _c = spawn(async move {
            let results = match search_document_pdf(document_identifier, new_query, Some(search_controller.inner.source.clone())).await {
                Ok(result) => result,
                Err(e) => {
                    error!("Failed to get search results: {e:?}");
                    return;
                }
            };
            if !search_controller.is_active()
                || search_generation() != next_search_generation
            {
                return;
            }
            _sig_search_task.set(None);
            search_results.set(results.clone());
            search_hit_index.set(0);
            search_controller
                .inner
                .search_api
                .startSearch(search_controller.document_id());
            if !search_controller.is_active()
                || search_generation() != next_search_generation
            {
                return;
            }
            search_controller.inner.search_api.setExternalSearchResults(
                search_controller.document_id(),
                serde_wasm_bindgen::to_value(&results).unwrap(),
            );
            if !search_controller.is_active()
                || search_generation() != next_search_generation
            {
                return;
            }
            set_search_idx.call(0);
        });
        _sig_search_task.set(Some(_c));
    });

    // =========== ZOOM ============
    let mut zoom_state_jsvalue = use_signal(move || controller().inner.zoom_api.getState());
    let zoom_in = Callback::new(move |_| {
        if !controller().is_active() {
            return;
        }
        controller().inner.zoom_api.zoomIn();
        zoom_state_jsvalue.set(controller().inner.zoom_api.getState());
    });
    let zoom_out = Callback::new(move |_| {
        if !controller().is_active() {
            return;
        }
        controller().inner.zoom_api.zoomOut();
        zoom_state_jsvalue.set(controller().inner.zoom_api.getState());
    });
    let zoom_state_str = use_memo(move || {
        #[derive(Debug, Serialize, Deserialize, Default)]
        struct PdfZoomState {
            pub currentZoomLevel: f32,
        }
        let obj = serde_wasm_bindgen::from_value::<PdfZoomState>(zoom_state_jsvalue.read().clone())
            .unwrap_or_default();
        let zoom = (obj.currentZoomLevel * 100.0) as i32;
        format!("{}%", zoom)
    });
    let controller_for_zoom_change = controller();
    let on_zoom_change = move |_obj| {
        if !controller_for_zoom_change.is_active() {
            return;
        }
        zoom_state_jsvalue.set(controller().inner.zoom_api.getState());
    };
    let on_zoom_change = Closure::new(Box::new(on_zoom_change) as Box<dyn FnMut(JsValue)>);
    let on_zoom_change = on_zoom_change.into_js_value();
    controller().inner.zoom_api.onZoomChange(on_zoom_change);

    PdfViewerControllerDx {
        _controller: controller,
        current_page: current_page.into(),
        total_pages: total_pages.into(),
        set_page,
        search_query: search_query.into(),
        set_search_query,
        search_hit_index: search_hit_index.into(),
        search_hit_count: search_hit_count.into(),
        set_search_idx,
        zoom_in,
        zoom_out,
        zoom_state: zoom_state_str.into(),
    }
}

#[server]
async fn search_document_pdf(
    document_identifier: DocumentIdentifier,
    query: String,
    source: Option<DocumentPdfSourceItem>,
) -> anyhow::Result<PdfSearchResults> {
    let user = crate::api::server_auth::extract_user().await?;
    let results = backend::api::documents::search_document_pdf::search_document_pdf(
        &user,
        document_identifier,
        query,
        source,
    )
    .await?;
    Ok(results)
}
#[component]
pub fn PdfViewer(
    pdf_url: ReadSignal<String>,
    source: ReadSignal<DocumentPdfSourceItem>,
    document_identifier: ReadSignal<DocumentIdentifier>,
    on_document_loaded: Callback<PdfViewerControllerJs>,
) -> Element {
    let mut is_mounted = use_signal(move || false);
    let source_lifetime = use_hook(|| Rc::new(Cell::new(0_u64)));
    let source_lifetime_for_drop = source_lifetime.clone();
    use_drop(move || {
        source_lifetime_for_drop.set(source_lifetime_for_drop.get() + 1);
        info!(
            "pdf-lifecycle rust-drop generation={}",
            source_lifetime_for_drop.get()
        );
        let promise = x_dispose_pdf_viewer();
        wasm_bindgen_futures::spawn_local(async move {
            if let Err(error) = wasm_bindgen_futures::JsFuture::from(promise).await {
                error!("PDF viewer disposal failed: {:?}", error);
            }
        });
    });

    let proxy_cb = Callback::new(move |e: PdfViewerControllerJs| {
        let current_url = pdf_url.peek().clone();
        if &current_url == &e.pdf_url() {
            on_document_loaded.call(e);
        } else {
            info!(
                "PDF URL MISMATCH: {:#?} != {:#?}",
                pdf_url.peek(),
                e.pdf_url()
            );
        }
    });

    use_effect(move || {
        let pdf_url = pdf_url();
        if !is_mounted() {
            return;
        }
        let source_generation = source_lifetime.get() + 1;
        source_lifetime.set(source_generation);
        info!(
            "pdf-lifecycle rust-open generation={} url={}",
            source_generation, pdf_url
        );
        let source_lifetime_for_callback = source_lifetime.clone();

        let cb = move |pdf_url: String,
                       event: JsValue,
                       scroll: PdfScrollApi,
                       search: PdfSearchApi,
                       zoom: PdfZoomApi| {
            if source_lifetime_for_callback.get() != source_generation {
                return;
            }
            let loaded_event: PdfLoadedEvent =
                serde_wasm_bindgen::from_value(event).expect("Failed to deserialize loaded event");
            info!(
                "pdf-lifecycle rust-loaded generation={} document_id={}",
                source_generation, loaded_event.documentId
            );
            proxy_cb.call(PdfViewerControllerJs {
                inner: Arc::new(PdfViewerControllerInnerJs {
                    pdf_url: pdf_url,
                    document_identifier: document_identifier(),
                    source: source(),
                    loaded_event,
                    source_generation,
                    source_lifetime: source_lifetime_for_callback.clone(),
                    scroll_api: scroll,
                    search_api: search,
                    zoom_api: zoom,
                }),
            });
        };
        let cb =
            Closure::new(Box::new(cb)
                as Box<
                    dyn FnMut(String, JsValue, PdfScrollApi, PdfSearchApi, PdfZoomApi),
                >);
        let cb = cb.into_js_value();

        let promise = x_open_pdf_viewer(pdf_url.clone(), cb);
        wasm_bindgen_futures::spawn_local(async move {
            // The browser task remains active after the component scope is removed.
            if let Err(error) = wasm_bindgen_futures::JsFuture::from(promise).await {
                error!("PDF viewer initialization failed: {:?}", error);
            }
        });
    });

    rsx! {
        div {
            id: "x-pdf-viewer",
            style: "width:100%;height:100%;",
            onmounted: move |_| {
                is_mounted.set(true);
            },
        }
    }
}

mod _js {
    use serde::{Deserialize, Serialize};
    use wasm_bindgen::prelude::*;
    use web_sys::js_sys::Promise;

    #[wasm_bindgen]
    extern "C" {
        #[wasm_bindgen(js_namespace = window)]
        pub fn x_open_pdf_viewer(
            pdf_url: String,
            callback_fn: JsValue,
        ) -> Promise;

        #[wasm_bindgen(js_namespace = window)]
        pub fn x_dispose_pdf_viewer() -> Promise;
    }

    #[wasm_bindgen]
    extern "C" {

        // ====== SCROLL API ======
        pub type PdfScrollApi;

        #[wasm_bindgen(method, structural)]
        pub fn scrollToPage(this: &PdfScrollApi, options: JsValue, doc_id: String) -> JsValue;

        #[wasm_bindgen(method, structural)]
        pub fn onPageChange(this: &PdfScrollApi, callback_fn: JsValue) -> JsValue;

        // ====== SEARCH API ======
        pub type PdfSearchApi;

        #[wasm_bindgen(method, structural)]
        pub fn searchAllPages(
            this: &PdfSearchApi,
            query: String,
            doc_id: String,
        ) -> SearchAllPagesTask;

        #[wasm_bindgen(method, structural)]
        pub fn goToResult(this: &PdfSearchApi, result_index: i32, doc_id: String) -> JsValue;

        #[wasm_bindgen(method, structural)]
        pub fn getState(this: &PdfSearchApi) -> JsValue;

        #[wasm_bindgen(method, structural)]
        pub fn setExternalSearchResults(
            this: &PdfSearchApi,
            doc_id: String,
            results: JsValue,
        ) -> JsValue;

        #[wasm_bindgen(method, structural)]
        pub fn startSearch(this: &PdfSearchApi, doc_id: String) -> JsValue;

        pub type SearchAllPagesTask;
        #[wasm_bindgen(method, structural)]
        pub fn toPromise(this: &SearchAllPagesTask) -> Promise;

        // ====== ZOOM API ======
        pub type PdfZoomApi;

        #[wasm_bindgen(method, structural)]
        pub fn zoomIn(this: &PdfZoomApi) -> JsValue;
        #[wasm_bindgen(method, structural)]
        pub fn zoomOut(this: &PdfZoomApi) -> JsValue;
        #[wasm_bindgen(method, structural)]
        pub fn getState(this: &PdfZoomApi) -> JsValue;
        #[wasm_bindgen(method, structural)]
        pub fn onZoomChange(this: &PdfZoomApi, callback_fn: JsValue) -> JsValue;
    }

    #[derive(Debug, Serialize, Deserialize, PartialEq, Clone)]
    pub struct PdfLoadedEvent {
        pub documentId: String,
        pub isInitial: bool,
        pub pageNumber: i32,
        pub totalPages: i32,
    }
}

#[component]
pub fn PdfViewerJsScriptTag() -> Element {
    rsx! {
        script {
            // src:asset!("/assets/embed-pdf/embed-pdf.js"),
            src: "/assets/_viewer/embed-pdf.js",
            r#type: "module",
        }
    }
}
