//! Create a dataset from a subfolder of a dataset mount, with its OCR options.
//!
//! The admin picks a mount and then a folder directly beneath it. The admin can also name a
//! new folder in a writable mount, and the server creates it when the form is sent. The
//! panel shows no mount select when only one mount is configured. "Accept uploads" shows
//! only for a writable mount, and it is disabled while another dataset of the collection
//! accepts uploads. The server checks both rules again.
//!
//! Datasets were CLI-only until this panel: `main.py add-disk-dataset`. The reason it is
//! a *picker* rather than a path box is the same reason the backend re-validates the name
//! against the listing. A free-text path in a browser form is a way to point the ingest
//! walker at any directory the container can see, and the walker copies what it finds.
//!
//! The OCR languages are chosen here rather than after the fact because the first pass is
//! the expensive one. A dataset ingested in the wrong languages costs a full re-OCR to
//! correct, and the apply job exists to change a decision, not to make up for never having
//! taken one.

use dioxus::prelude::*;

use common::admin_types::{DatasetFolderOption, DatasetMountOption};
use common::storage_tree::normalize_identifier;

use crate::api::admin_api::{
    admin_create_dataset, admin_get_collection_ocr_defaults, admin_list_collection_upload_datasets,
    admin_list_dataset_folders, admin_list_dataset_mounts, admin_set_collection_ocr_defaults,
};

/// The value of the folder option that asks for a new folder. It holds a `/`, so no
/// folder name can be equal to it.
const NEW_FOLDER: &str = "/new";
use crate::components::admin_components::{
    ErrorBar, SuccessBar, BTN, HELP_TEXT, INPUT, LABEL, MODULE, MODULE_BODY, MODULE_CAPTION, SELECT,
};

/// Turn a folder name into the pipeline's dataset-name shape: lowercase, `_` separators.
/// The backend applies the same rule and refuses what does not match, so this is a
/// suggestion the admin can override, not a sanitiser to rely on.
fn suggest_dataset_name(folder: &str) -> String {
    folder
        .to_lowercase()
        .chars()
        .map(|c| {
            if c.is_ascii_lowercase() || c.is_ascii_digit() {
                c
            } else {
                '_'
            }
        })
        .collect()
}

#[component]
pub fn DatasetCreatePanel(
    collectionname: String,
    /// The dataset names that the collection has, for the collision message.
    #[props(default)]
    existing_datasets: Vec<String>,
    on_created: EventHandler<String>,
) -> Element {
    let mounts_res = use_resource(admin_list_dataset_mounts);
    // Empty until the admin picks a mount. The first mount applies until then.
    let mut mount = use_signal(String::new);
    let for_res = collectionname.clone();
    let mut folders_res = use_resource(move || {
        let collectionname = for_res.clone();
        let picked = mount.read().clone();
        let first = mounts_res
            .read()
            .as_ref()
            .and_then(|r| r.as_ref().ok())
            .and_then(|m| m.first().map(|m| m.name.clone()));
        async move {
            let name = if picked.is_empty() { first } else { Some(picked) };
            match name {
                Some(name) => admin_list_dataset_folders(collectionname, name).await,
                None => Ok(Vec::new()),
            }
        }
    });
    let for_defaults = collectionname.clone();
    let mut defaults_res = use_resource(move || admin_get_collection_ocr_defaults(for_defaults.clone()));
    let for_uploads = collectionname.clone();
    let mut upload_datasets_res =
        use_resource(move || admin_list_collection_upload_datasets(for_uploads.clone()));
    let mut accept_uploads = use_signal(|| false);

    let mut folder = use_signal(String::new);
    let mut new_folder_name = use_signal(String::new);
    let mut dataset_name = use_signal(String::new);
    let mut tesseract = use_signal(|| "eng".to_string());
    let mut easyocr = use_signal(|| "en".to_string());
    let mut seeded = use_signal(|| false);
    let mut saving_defaults = use_signal(|| false);

    // Seed the language boxes from the collection's defaults, once. After that the admin
    // owns them: a re-render must not undo what they typed.
    //
    // The hook runs on every render and the resource's state is tested *inside* it. A
    // `use_effect` that only exists once a resource has resolved shifts every hook index
    // after it on the render that adds it, which traps the WebAssembly runtime and leaves
    // the whole page painted but dead.
    use_effect(move || {
        let defaults = defaults_res.read().as_ref().cloned();
        if let Some(Ok((tess, easy))) = defaults {
            if !*seeded.peek() {
                tesseract.set(tess);
                easyocr.set(easy);
                seeded.set(true);
            }
        }
    });
    let mut msg = use_signal(|| None::<String>);
    let mut error_msg = use_signal(|| None::<String>);
    let mut submitting = use_signal(|| false);

    let mounts: Vec<DatasetMountOption> = mounts_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned()
        .unwrap_or_default();
    let mounts_error = mounts_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().err().map(|e| e.to_string()));
    let mounts_loading = mounts_res.read().is_none();
    let picked_mount = mount.read().clone();
    let current_mount: Option<DatasetMountOption> = if picked_mount.is_empty() {
        mounts.first().cloned()
    } else {
        mounts.iter().find(|m| m.name == picked_mount).cloned()
    };
    let mount_name = current_mount.as_ref().map(|m| m.name.clone()).unwrap_or_default();
    let mount_writable = current_mount.as_ref().is_some_and(|m| m.writable);

    let folders: Vec<DatasetFolderOption> = folders_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned()
        .unwrap_or_default();
    let listing_error = folders_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().err().map(|e| e.to_string()));

    let upload_datasets: Vec<String> = upload_datasets_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned()
        .unwrap_or_default();
    let upload_datasets_error = upload_datasets_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().err().map(|e| e.to_string()));
    let uploads_taken = !upload_datasets.is_empty();
    let accept_value = *accept_uploads.read() && mount_writable && !uploads_taken;
    let uploads_taken_note = match upload_datasets.as_slice() {
        [one] => format!("{one} already accepts uploads."),
        many => format!("{} already accept uploads.", many.join(", ")),
    };

    let chosen = folder.read().clone();
    let creating_folder = chosen == NEW_FOLDER;
    let target_folder = if creating_folder {
        new_folder_name.read().trim().to_string()
    } else {
        chosen.clone()
    };
    // The name the server derives when the field is empty, and saves otherwise.
    let saved_name = if dataset_name.read().trim().is_empty() {
        normalize_identifier(&target_folder)
    } else {
        normalize_identifier(&dataset_name.read())
    };
    let name_taken = !saved_name.is_empty() && existing_datasets.iter().any(|d| d == &saved_name);
    let can_create = !target_folder.is_empty() && !mount_name.is_empty() && !*submitting.read() && !name_taken;
    let create_style = if can_create {
        ""
    } else {
        "opacity: 0.5; cursor: not-allowed;"
    };

    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, "Add a dataset" }
            div { style: "{MODULE_BODY} display: flex; flex-direction: column; gap: 12px; max-width: 640px;",
                if let Some(m) = msg.read().clone() { SuccessBar { message: m } }
                if let Some(e) = error_msg.read().clone() { ErrorBar { message: e } }

                if let Some(err) = mounts_error {
                    p { style: "{HELP_TEXT} margin: 0;",
                        "The dataset mounts could not be read, so there is nothing to pick from: {err}"
                    }
                } else if mounts_loading {
                    p { style: "{HELP_TEXT} margin: 0;", "Loading the dataset mounts." }
                } else if mounts.is_empty() {
                    p { style: "{HELP_TEXT} margin: 0;", "No dataset mount is configured." }
                } else {
                    if mounts.len() > 1 {
                        MountSelect { mounts: mounts.clone(), value: mount_name.clone(), on_change: move |value: String| {
                            mount.set(value);
                            folder.set(String::new());
                            new_folder_name.set(String::new());
                        } }
                    }
                    if let Some(err) = listing_error {
                        p { style: "{HELP_TEXT} margin: 0;",
                            "The mount folder could not be read, so there is nothing to pick from: {err}"
                        }
                    } else if folders.is_empty() && !mount_writable {
                        p { style: "{HELP_TEXT} margin: 0;",
                            "No subfolders were found in this mount. "
                            "Put the documents in a folder there and reload this page."
                        }
                    } else {
                    label { style: LABEL,
                        span { style: "width: 130px; color: var(--x-ink-muted);", "Folder" }
                        select {
                            style: "{SELECT} flex: 1;",
                            value: "{folder}",
                            onchange: move |e| {
                                let value = e.value();
                                let suggestion_from = if *folder.peek() == NEW_FOLDER {
                                    new_folder_name.peek().clone()
                                } else {
                                    folder.peek().clone()
                                };
                                let suggestion_to = if value == NEW_FOLDER {
                                    new_folder_name.peek().clone()
                                } else {
                                    value.clone()
                                };
                                if dataset_name.read().is_empty() || dataset_name.read().as_str() == suggest_dataset_name(&suggestion_from) {
                                    dataset_name.set(suggest_dataset_name(&suggestion_to));
                                }
                                folder.set(value);
                            },
                            option { value: "", "Select a folder" }
                            if mount_writable {
                                option { value: NEW_FOLDER, "New folder" }
                            }
                            for option in folders.iter() {
                                option {
                                    key: "{option.name}",
                                    value: "{option.name}",
                                    disabled: option.already_used,
                                    if option.already_used {
                                        "{option.name} ({option.entry_count} entries), already a dataset"
                                    } else {
                                        "{option.name} ({option.entry_count} entries)"
                                    }
                                }
                            }
                        }
                    }
                    if creating_folder {
                        label { style: LABEL,
                            span { style: "width: 130px; color: var(--x-ink-muted);", "New folder" }
                            input {
                                style: "{INPUT} flex: 1;",
                                value: "{new_folder_name}",
                                oninput: move |e| {
                                    let value = e.value();
                                    if dataset_name.read().is_empty() || dataset_name.read().as_str() == suggest_dataset_name(&new_folder_name.peek()) {
                                        dataset_name.set(suggest_dataset_name(&value));
                                    }
                                    new_folder_name.set(value);
                                },
                            }
                        }
                        p { style: "{HELP_TEXT} margin: 0;",
                            "The server creates this folder in the mount when you create the dataset. "
                            "The name cannot start with a full stop or contain a slash."
                        }
                    } else {
                        p { style: "{HELP_TEXT} margin: 0;",
                            "The list shows the direct subfolders of the mount."
                        }
                    }

                    label { style: LABEL,
                        span { style: "width: 130px; color: var(--x-ink-muted);", "Dataset name" }
                        input {
                            style: "{INPUT} flex: 1;",
                            value: "{dataset_name}",
                            oninput: move |e| dataset_name.set(e.value()),
                        }
                    }
                    p { style: "{HELP_TEXT} margin: 0;",
                        "A name has lowercase letters, digits and underscores. Capital letters become lowercase, "
                        "and a dash, a space or a full stop becomes an underscore. The name cannot change later."
                    }
                    if !saved_name.is_empty() {
                        p { class: "x-name-preview", style: "{HELP_TEXT} margin: 0;", "The dataset is saved as: {saved_name}" }
                    }
                    if name_taken {
                        p { class: "x-name-collision", style: "margin: 0; color: var(--x-danger);", "This collection has a dataset with the name {saved_name}." }
                    }

                    if mount_writable {
                        label { style: LABEL,
                            input {
                                r#type: "checkbox",
                                checked: accept_value,
                                disabled: uploads_taken || upload_datasets_error.is_some(),
                                onchange: move |e| accept_uploads.set(e.checked()),
                            }
                            "Accept uploads"
                        }
                        if let Some(err) = upload_datasets_error.clone() {
                            p { style: "{HELP_TEXT} margin: 0;", "The upload datasets of this collection could not be read: {err}" }
                        } else if uploads_taken {
                            p { style: "{HELP_TEXT} margin: 0;", "{uploads_taken_note}" }
                        }
                    }

                    label { style: LABEL,
                        span { style: "width: 130px; color: var(--x-ink-muted);", "Tesseract" }
                        input {
                            style: "{INPUT} flex: 1;",
                            value: "{tesseract}",
                            oninput: move |e| tesseract.set(e.value()),
                        }
                    }
                    label { style: LABEL,
                        span { style: "width: 130px; color: var(--x-ink-muted);", "EasyOCR" }
                        input {
                            style: "{INPUT} flex: 1;",
                            value: "{easyocr}",
                            oninput: move |e| easyocr.set(e.value()),
                        }
                    }
                    p { style: "{HELP_TEXT} margin: 0;",
                        "`+`-joined language codes, for example eng+ron. An empty EasyOCR value turns EasyOCR off. "
                        "The form starts with the collection defaults. A dataset created with the defaults follows later changes of them, "
                        "and a dataset created with other values keeps its own. A change on the dataset page runs OCR again."
                    }

                    div {
                        button {
                            style: "{BTN} background: #999;",
                            disabled: *saving_defaults.read(),
                            onclick: {
                                let collectionname = collectionname.clone();
                                move |_| {
                                    let collectionname = collectionname.clone();
                                    let tess = tesseract.read().clone();
                                    let easy = easyocr.read().clone();
                                    if *saving_defaults.peek() { return; }
                                    saving_defaults.set(true);
                                    spawn(async move {
                                        msg.set(None);
                                        error_msg.set(None);
                                        match admin_set_collection_ocr_defaults(collectionname, tess, easy).await {
                                            Ok(changed) => {
                                                msg.set(Some(if changed.is_empty() {
                                                    "Saved as this collection's defaults. No dataset changes its languages.".to_string()
                                                } else {
                                                    format!(
                                                        "Saved as this collection's defaults. These datasets inherit them, and their OCR updates start one at a time: {}. Datasets with their own languages keep them.",
                                                        changed.join(", ")
                                                    )
                                                }));
                                                defaults_res.restart();
                                            }
                                            Err(e) => error_msg.set(Some(e.to_string())),
                                        }
                                        saving_defaults.set(false);
                                    });
                                }
                            },
                            if *saving_defaults.read() { "Saving\u{2026}" } else { "Save as collection defaults" }
                        }
                    }

                    div {
                        button {
                            style: "{BTN} {create_style}",
                            disabled: !can_create,
                            onclick: {
                                let collectionname = collectionname.clone();
                                move |_| {
                                    let collectionname = collectionname.clone();
                                    let mount_name = mount_name.clone();
                                    let folder_value = target_folder.clone();
                                    let name = normalize_identifier(&dataset_name.read());
                                    let tess = tesseract.read().clone();
                                    let easy = easyocr.read().clone();
                                    let accept = accept_value;
                                    if *submitting.peek() { return; }
                                    submitting.set(true);
                                    spawn(async move {
                                        msg.set(None);
                                        error_msg.set(None);
                                        match admin_create_dataset(collectionname, mount_name, folder_value, creating_folder, name, tess, easy, accept).await {
                                            Ok(collection_dataset) => {
                                                msg.set(Some(format!(
                                                    "Created {collection_dataset}. Ingestion has started. \
                                                     Follow it on the collection's processing page."
                                                )));
                                                folder.set(String::new());
                                                new_folder_name.set(String::new());
                                                dataset_name.set(String::new());
                                                accept_uploads.set(false);
                                                folders_res.restart();
                                                upload_datasets_res.restart();
                                                on_created.call(collection_dataset);
                                            }
                                            Err(e) => error_msg.set(Some(e.to_string())),
                                        }
                                        submitting.set(false);
                                    });
                                }
                            },
                            if *submitting.read() { "Creating\u{2026}" } else { "Create and ingest" }
                        }
                    }
                    }
                }
            }
        }
    }
}

/// Renders the mount select, with "(read-only)" after the name of each read-only mount.
#[component]
fn MountSelect(mounts: Vec<DatasetMountOption>, value: String, on_change: EventHandler<String>) -> Element {
    rsx! {
        label { style: LABEL,
            span { style: "width: 130px; color: var(--x-ink-muted);", "Mount" }
            select {
                style: "{SELECT} flex: 1;",
                value: "{value}",
                onchange: move |e| on_change.call(e.value()),
                for option in mounts.iter() {
                    option {
                        key: "{option.name}",
                        value: "{option.name}",
                        selected: option.name == value,
                        if option.writable {
                            "{option.name}"
                        } else {
                            "{option.name} (read-only)"
                        }
                    }
                }
            }
        }
    }
}
