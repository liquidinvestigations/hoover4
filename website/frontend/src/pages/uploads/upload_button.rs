//! The Upload button at the end of the breadcrumb bar of the file browser pages. It shows
//! only when the user has an upload target. On a folder of an upload dataset of the user,
//! the link names the collection and the folder.

use common::uploads::UploadTargetInfo;
use dioxus::prelude::*;
use dioxus_free_icons::icons::md_file_icons::MdFileUpload;
use dioxus_free_icons::Icon;

use crate::api::uploads_api::upload_page_info;
use crate::routes::Route;

const BUTTON_STYLE: &str = "margin-left: auto; display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; border: 1px solid rgba(0,0,0,0.35); border-radius: 100px; text-decoration: none; color: var(--x-ink-strong); font-size: var(--x-text-md); white-space: nowrap;";

/// The upload page for the browsed place. `folder` is empty outside a dataset folder.
pub fn upload_route(targets: &[UploadTargetInfo], dataset: &str, folder: &str) -> Route {
    match targets.iter().find(|t| t.dataset == dataset) {
        Some(t) if !folder.is_empty() => Route::UploadPage { collection: t.collection.clone(), folder: folder.to_string() },
        _ => Route::UploadPage { collection: String::new(), folder: String::new() },
    }
}

#[component]
pub fn UploadButton(dataset: String, folder: String) -> Element {
    let info = use_resource(upload_page_info);
    let targets = match &*info.read() {
        Some(Ok(info)) if !info.targets.is_empty() => info.targets.clone(),
        _ => return rsx! {},
    };
    rsx! {
        Link {
            to: upload_route(&targets, &dataset, &folder),
            class: "x-upload-button hoover4-hover-shadow-background",
            style: BUTTON_STYLE,
            Icon { icon: MdFileUpload, width: 16, height: 16 }
            "Upload"
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_link_names_the_folder_only_inside_an_upload_dataset() {
        let targets = vec![UploadTargetInfo { collection: "press".into(), dataset: "press_inbox".into() }];
        assert_eq!(
            upload_route(&targets, "press_inbox", "/2026"),
            Route::UploadPage { collection: "press".into(), folder: "/2026".into() }
        );
        let empty = Route::UploadPage { collection: String::new(), folder: String::new() };
        assert_eq!(upload_route(&targets, "press_other", "/2026"), empty);
        assert_eq!(upload_route(&targets, "press_inbox", ""), empty);
    }
}
