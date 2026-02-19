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
            assert_eq!(tokio::runtime::RuntimeFlavor::MultiThread, rt_handle.runtime_flavor());

            use axum::{extract::Request, middleware::Next};
            use dioxus::server::axum;

            Ok(dioxus::server::router(App)
            .route("/_download_document/{collection_dataset}/{file_hash}", axum::routing::get(backend::server_extra::download_document::download_document))
                // we can apply a layer to the entire router using axum's `.layer` method
                .layer(axum::middleware::from_fn(
                    |request: Request, next: Next| async move {
                        // println!("Request: {} {}", request.method(), request.uri().path());
                        let res = next.run(request).await;
                        // println!("Response: {}", res.status());
                        res
                    },
                )))
        });

    }
    // backend::tokio::runtime::Runtime::new().unwrap().block_on(async move {

    // });
}