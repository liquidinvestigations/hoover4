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
/// The popover, hover-card and toast stylesheets. They are linked here, once, so the
/// server-rendered head carries them before the first paint. A link inside a component
/// reaches the head only when that component first renders, and its markup then paints
/// without styles until the file arrives.
const POPOVER_CSS: Asset = asset!("/src/components/popover/style.css");
const HOVER_CARD_CSS: Asset = asset!("/src/components/hover_card/style.css");
const TOAST_CSS: Asset = asset!("/src/components/toast/style.css");
/// The Latin file of the normal Roboto face, which every first view uses through
/// `--x-font`. The search, document and storage pages load no other face before the
/// first paint. Inter is not preloaded: the theme sets it on `body`, but `#main` sets
/// Roboto, so no view renders Inter text. The URL is the one that `fonts.css` resolves
/// to, and `crossorigin` matches the anonymous request mode of a font load, so the
/// browser reuses the preloaded response.
const PRELOADED_FONTS: [&str; 1] = [
    "/assets/fonts/roboto/KFO7CnqEu92Fr1ME7kSn66aGLdTylUAMa3yUBA.woff2",
];
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
        for font in PRELOADED_FONTS {
            document::Link { rel: "preload", href: font, r#as: "font", r#type: "font/woff2", crossorigin: "anonymous" }
        }
        document::Link { rel: "stylesheet", href: "/assets/fonts/fonts.css" }

        document::Link { rel: "icon", href: FAVICON }
        document::Link { rel: "stylesheet", href: MAIN_CSS }
        document::Link { rel: "stylesheet", href: THEME_CSS }
        document::Link { rel: "stylesheet", href: POPOVER_CSS }
        document::Link { rel: "stylesheet", href: HOVER_CARD_CSS }
        document::Link { rel: "stylesheet", href: TOAST_CSS }

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
                            crate::i18n::LanguageProvider {
                                Router::<Route> {}
                            }
                        }
                    }
                }
            }
        }
    }
}
