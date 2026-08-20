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
            // Dioxus server functions do not run on this runtime and cannot call a
            // library that blocks internally. Nothing in this binary does: the S3 client
            // is async end to end.
            assert_eq!(
                tokio::runtime::RuntimeFlavor::MultiThread,
                tokio::runtime::Handle::current().runtime_flavor()
            );

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
                // The derived searchable PDF for one (document, engine, languages). It
                // has no `blobs` row by design — `pdf_ocr_results` is its only index —
                // so it cannot go through the document route, but it is ACL'd on the
                // source document's dataset exactly like one.
                .route(
                    "/_download_ocr_pdf/{collection_dataset}/{pdf_hash}/{engine}/{languages}",
                    axum::routing::get(backend::server_extra::download_ocr_pdf::download_ocr_pdf),
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
                ))
                // Outermost, so it runs last on the response path: the framework's own
                // router answers everything with `access-control-allow-origin: *`, and
                // the two routes above serve bytes behind an owner-or-admin check.
                .layer(axum::middleware::from_fn(
                    backend::server_extra::private_routes::strip_cors_on_private_routes,
                )))
        });
    }
    // backend::tokio::runtime::Runtime::new().unwrap().block_on(async move {

    // });
}
