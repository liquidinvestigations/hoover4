use std::sync::Arc;

use _js::*;
use dioxus::prelude::*;
use serde::{Deserialize, Serialize};
use wasm_bindgen::{JsValue, prelude::Closure};
use wasm_bindgen_futures::JsFuture;

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
    loaded_event: PdfLoadedEvent,
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

#[derive(Debug, Deserialize, Clone)]
struct PdfSearchResults {
    pub results: Vec<PdfSearchResult>,
    pub total: i32,
}

#[derive(Debug, Deserialize, Clone)]
struct PdfSearchResult {
    #[serde(rename = "pageIndex")]
    pub page_index: i32,
    #[serde(rename = "charIndex")]
    pub char_index: i32,
    #[serde(rename = "charCount")]
    pub char_count: i32,
    pub rects: Vec<PdfSearchResultRect>,
    pub context: PdfSearchResultContext,
}

#[derive(Debug, Deserialize, Clone)]
struct PdfSearchResultRect {
    pub origin: RectPoint,
    pub size: RectSize,
}

#[derive(Debug, Deserialize, Clone)]
struct RectPoint {
    pub x: f64,
    pub y: f64,
}

#[derive(Debug, Deserialize, Clone)]
struct RectSize {
    pub width: f64,
    pub height: f64,
}

#[derive(Debug, Deserialize, Clone)]
struct PdfSearchResultContext {
    pub before: String,
    #[serde(rename = "match")]
    pub _match: String,
    pub after: String,
    #[serde(rename = "truncatedLeft")]
    pub truncated_left: bool,
    #[serde(rename = "truncatedRight")]
    pub truncated_right: bool,
}

async fn desearialize_search_results(
    search_task: SearchAllPagesTask,
) -> anyhow::Result<PdfSearchResults> {
    let search_task = search_task.toPromise();
    let search_task = JsFuture::from(search_task);
    let result = search_task
        .await
        .map_err(|e| anyhow::anyhow!("Failed to get search results: {e:?}"))?;
    let result = serde_wasm_bindgen::from_value::<PdfSearchResults>(result)
        .map_err(|e| anyhow::anyhow!("Failed to deserialize search results: {e:?}"))?;
    Ok(result)
}

pub fn use_pdf_controller(controller: PdfViewerControllerJs) -> PdfViewerControllerDx {
    let controller = use_signal(move || controller);

    // =========== PAGE NAVIGATION ============
    let mut current_page = use_signal(move || controller().initial_page());
    let total_pages = use_signal(move || controller().total_pages());
    let set_page = Callback::new(move |new_page: i32| {
        let new_page = new_page.clamp(1, total_pages());
        controller().inner.scroll_api.scrollToPage(
            scroll_to_page_options(new_page, 0., 0., 0.),
            controller().document_id(),
        );
    });

    let on_page_change = move |obj| {
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
    let mut search_results = use_signal(move || PdfSearchResults {
        results: vec![],
        total: 0,
    });
    let search_hit_count = use_memo(move || search_results.read().results.len() as i32);

    let set_search_idx = Callback::new(move |new_idx: i32| {
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
        let search_task = controller()
            .inner
            .search_api
            .searchAllPages(new_query.clone(), controller().document_id());
        let _c = spawn(async move {
            let results = match desearialize_search_results(search_task).await {
                Ok(result) => result,
                Err(e) => {
                    error!("Failed to get search results: {e:?}");
                    return;
                }
            };
            _sig_search_task.set(None);
            search_results.set(results.clone());
            set_search_idx.call(0);
        });
        _sig_search_task.set(Some(_c));
    });

    // =========== ZOOM ============
    let mut zoom_state_jsvalue = use_signal(move || controller().inner.zoom_api.getState());
    let zoom_in = Callback::new(move |_| {
        controller().inner.zoom_api.zoomIn();
        zoom_state_jsvalue.set(controller().inner.zoom_api.getState());
    });
    let zoom_out = Callback::new(move |_| {
        controller().inner.zoom_api.zoomOut();
        zoom_state_jsvalue.set(controller().inner.zoom_api.getState());
    });
    let zoom_state_str = use_memo(move || {
        #[derive(Debug, Serialize, Deserialize, Default)]
        struct PdfZoomState {
            pub currentZoomLevel: f32,
        }
        let obj = serde_wasm_bindgen::from_value::<PdfZoomState>(zoom_state_jsvalue.read().clone()).unwrap_or_default();
        let zoom = (obj.currentZoomLevel * 100.0) as i32;
        format!("{}%", zoom)
    });
    let on_zoom_change = move |_obj| {
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

#[component]
pub fn PdfViewer(
    pdf_url: ReadSignal<String>,
    on_document_loaded: Callback<PdfViewerControllerJs>,
) -> Element {
    let mut is_mounted = use_signal(move || false);

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

        let cb =
            move |pdf_url: String, event: JsValue, scroll: PdfScrollApi, search: PdfSearchApi, zoom: PdfZoomApi| {
                let loaded_event = serde_wasm_bindgen::from_value(event)
                    .expect("Failed to deserialize loaded event");
                proxy_cb.call(PdfViewerControllerJs {
                    inner: Arc::new(PdfViewerControllerInnerJs {
                        pdf_url: pdf_url,
                        loaded_event,
                        scroll_api: scroll,
                        search_api: search,
                        zoom_api: zoom,
                    }),
                });
            };
        let cb = Closure::new(
            Box::new(cb) as Box<dyn FnMut(String, JsValue, PdfScrollApi, PdfSearchApi, PdfZoomApi)>
        );
        let cb = cb.into_js_value();

        let promise = x_open_pdf_viewer(pdf_url.clone(), cb);
        spawn(async move {
            let result = promise.await;
            info!("_js::x_open_pdf_viewer: {:#?}", result);
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
        pub async fn x_open_pdf_viewer(
            pdf_url: String,
            callback_fn: JsValue,
        ) -> web_sys::js_sys::Boolean;
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
            src:asset!("/assets/embed-pdf/embed-pdf.js"),
            r#type: "module",
        }
    }
}
