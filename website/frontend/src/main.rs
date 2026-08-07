//! Frontend application entry point.

// use dioxus::prelude::server_only;
use frontend::app::App;

fn main() {
    #[cfg(not(feature = "server"))]
    dioxus::launch(App);

    #[cfg(feature = "server")]
    {
        // let rt = backend::tokio::runtime::Builder::new_multi_thread()
        // .enable_all()
        // .build()
        // .unwrap();

        dioxus::serve(|| async move {
            let rt_handle = tokio::runtime::Handle::current();
            assert_eq!(
                tokio::runtime::RuntimeFlavor::MultiThread,
                rt_handle.runtime_flavor()
            );
            // Server functions do NOT run on this runtime, and a library that blocks
            // internally panics when they call it. Anything in that position hands its
            // work back here through `startup::on_multi_thread_runtime`.
            backend::startup::set_multi_thread_runtime(rt_handle.clone());

            // Fail loudly if the database is unreachable rather than serving a
            // site where every DB-backed route silently fails.
            if let Err(e) = backend::startup::ensure_clickhouse_reachable().await {
                dioxus::logger::tracing::error!("FATAL: {e}");
                std::process::exit(1);
            }
            let _pdf_search_server = tokio::spawn(async move {
                let res =
                    backend::server_extra::run_pdf_search_server::run_pdf_search_server().await;
                match res {
                    Ok(code) => {
                        dioxus::logger::tracing::info!(
                            "PDF search server exited with code: {}",
                            code
                        );
                        // std::process::exit(code);
                    }
                    Err(e) => {
                        dioxus::logger::tracing::error!("PDF search server error: {:?}", e);
                        // std::process::exit(1);
                    }
                }
            });


            use dioxus::server::axum;

            Ok(dioxus::server::router(App)
                .route(
                    "/_download_document/{collection_dataset}/{file_hash}",
                    axum::routing::get(backend::server_extra::download_document::download_document),
                )
                // Chat tool artifacts: thumb.webp, page.html, detail.json. The handler
                // resolves the id to its owner and enforces owner-or-admin — the id
                // itself comes from an LLM-driven tool payload and is only a lookup key.
                .route(
                    "/_chat_artifact/{artifact_id}/{asset}",
                    axum::routing::get(backend::server_extra::chat_artifact::chat_artifact),
                )
                // we can apply a layer to the entire router using axum's `.layer` method
                .layer(axum::middleware::from_fn(
                    backend::auth::session_middleware::session_middleware,
                )))
        });
    }
    // backend::tokio::runtime::Runtime::new().unwrap().block_on(async move {

    // });
}
