//! File browser page layout and integration.

use dioxus::prelude::*;


/// File browser page
#[component]
pub fn FileBrowserPage() -> Element {
    rsx! {
        Title { "Hoover Search - File Browser" }
        h1 {
            "FileBrowserPage"
        }
    }
}