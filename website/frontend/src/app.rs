use dioxus::prelude::*;

use crate::components::error_boundary::GlobalErrorBoundary;
use crate::routes::Route;
const FAVICON: Asset = asset!("/assets/favicon.ico");
const MAIN_CSS: Asset = asset!("/assets/main.css");

#[component]
pub fn App() -> Element {
    rsx! {
        // TODO: replace google fonts with local fonts
        document::Link { rel: "preconnect", href: "https://fonts.googleapis.com" }
        document::Link { rel: "preconnect", href: "https://fonts.gstatic.com" }
        document::Link { rel: "stylesheet", href: "https://fonts.googleapis.com/css2?family=Roboto:ital,wght@0,100..900;1,100..900&display=swap" }


        document::Link { rel: "icon", href: FAVICON }
        document::Link { rel: "stylesheet", href: MAIN_CSS }
        GlobalErrorBoundary {
            boundary_name: "App".to_string(),
            Router::<Route> {}
        }
    }
}
