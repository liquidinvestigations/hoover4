//! Root application component.

use dioxus::prelude::*;

use crate::components::error_boundary::GlobalErrorBoundary;
use crate::components::pdf_viewer::PdfViewerJsScriptTag;
use crate::components::session_context::SessionProvider;
use crate::components::toast::ToastProvider;
use crate::routes::Route;
const FAVICON: Asset = asset!("/assets/favicon.ico");
const MAIN_CSS: Asset = asset!("/assets/main.css");
const THEME_CSS: Asset = asset!("/assets/dx-components-theme.css");
/// html-to-image 1.11.13, MIT licence, vendored with its licence file. The feedback
/// script draws the page image with it.
const HTML_TO_IMAGE_JS: Asset = asset!("/assets/feedback/html-to-image.js");
/// The feedback log collector and capture. It loads with the application, so the log
/// holds the entries since the application loaded.
const FEEDBACK_JS: Asset = asset!("/assets/feedback/feedback.js");

/// The vendored Roboto and Inter font files and their stylesheet, declared so `dx`
/// ships the whole folder.
///
/// `#[used]` because nothing reads the binding: the stylesheet link below names the
/// served path by a literal string, and without the attribute the constant is dropped
/// and the folder never reaches the bundle. `with_hash_suffix(false)` is what keeps
/// the served path `/assets/fonts/…`, which the literal string below and
/// `dx-components-theme.css` both depend on, so all three change together.
#[used]
static FONTS_FOLDER: Asset = asset!("/assets/fonts/", AssetOptions::folder().with_hash_suffix(false));

#[component]
pub fn App() -> Element {
    rsx! {
        document::Meta { name: "color-scheme", content: "light" }
        document::Link { rel: "stylesheet", href: "/assets/fonts/fonts.css" }

        document::Link { rel: "icon", href: FAVICON }
        document::Link { rel: "stylesheet", href: MAIN_CSS }
        document::Link { rel: "stylesheet", href: THEME_CSS }

        PdfViewerJsScriptTag {  }
        document::Script { src: HTML_TO_IMAGE_JS }
        document::Script { src: FEEDBACK_JS }

        GlobalErrorBoundary {
            boundary_name: "App".to_string(),

            ToastProvider {
                children: rsx! {
                    // Outside the router and inside the boundaries: every route is
                    // behind it, so the identity below is always resolved.
                    SessionProvider {
                        children: rsx! {
                            Router::<Route> {}
                        }
                    }
                }
            }
        }
    }
}
