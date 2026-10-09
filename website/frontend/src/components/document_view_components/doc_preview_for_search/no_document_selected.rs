//! Placeholder view when no document is selected.

use dioxus::prelude::*;
use dioxus_free_icons::Icon;
use dioxus_free_icons::icons::md_action_icons::MdSearchOff;

#[component]
pub fn NoDocumentSelected() -> Element {
    rsx! {
        div {
            style: "
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                height: 100%;
                width: 100%;

            ",
            div {
                style: "
                    width: 310px;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    text-align: center;
                    gap: 11px;
                ",
                Icon {
                    icon: MdSearchOff,
                    style: "width: 96px; height: 96px; color:rgba(0, 0, 0, 0.5);",
                }
                div {
                    style: "font-size: var(--x-text-page); line-height: var(--x-line-page); font-weight: 500; color:rgb(0, 0, 0);",
                    "No document selected"
                }
                div {
                    style: "font-size: var(--x-text-body); line-height: var(--x-line-body); font-weight: 400; color:rgba(0, 0, 0, 0.5);",
                    "Please select a document from the list to display its preview here."
                }
            }
        }
    }
}
