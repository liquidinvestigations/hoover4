use dioxus::prelude::*;

use crate::components::error_boundary::ComponentErrorBoundary;

#[component]
pub fn SuspendWrapper(children: Element) -> Element {
    rsx! {
        SuspenseBoundary {
            // When any child components (like BreedGallery) are suspended, this closure will
            // be called and the loading view will be rendered instead of the children
            fallback: |_s: SuspenseContext| rsx! {
                div {
                    width: "100%",
                    height: "100%",
                    display: "flex",
                    align_items: "center",
                    justify_content: "center",
                    LoadingIndicator {}
                }
            },
            ComponentErrorBoundary {
                children
            }
        }
    }
}

#[component]
pub fn LoadingIndicator() -> Element {
    rsx! {
        div {
            style: "color:black; font-size: 26px; border: 1px solid black; padding: 10px; border-radius: 5px; margin: 15px;",
            "Loading..."
        }
    }
}