//! Chatbot page layout and integration.

use dioxus::prelude::*;


/// Chatbot page
#[component]
pub fn ChatbotPage() -> Element {
    rsx! {
        Title { "Hoover Search - Chatbot" }
        h1 {
            "ChatbotPage"
        }
    }
}