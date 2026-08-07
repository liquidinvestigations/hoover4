//! Create a dataset from a subfolder of the datasets mount, with its OCR options.
//!
//! Datasets were CLI-only until this panel: `main.py add-disk-dataset`. The reason it is
//! a *picker* rather than a path box is the same reason the backend re-validates the name
//! against the listing — a free-text path in a browser form is a way to point the ingest
//! walker at any directory the container can see, and the walker copies what it finds.
//!
//! The OCR languages are chosen here rather than after the fact because the first pass is
//! the expensive one. A dataset ingested in the wrong languages costs a full re-OCR to
//! correct, and the apply job exists to change a decision, not to make up for never having
//! taken one.

use dioxus::prelude::*;

use common::admin_types::DatasetFolderOption;

use crate::api::admin_api::{
    admin_create_dataset, admin_get_collection_ocr_defaults, admin_list_dataset_folders,
    admin_set_collection_ocr_defaults,
};
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
pub fn DatasetCreatePanel(collectionname: String, on_created: EventHandler<String>) -> Element {
    let for_res = collectionname.clone();
    let mut folders_res = use_resource(move || admin_list_dataset_folders(for_res.clone()));
    let for_defaults = collectionname.clone();
    let mut defaults_res = use_resource(move || admin_get_collection_ocr_defaults(for_defaults.clone()));

    let mut folder = use_signal(String::new);
    let mut dataset_name = use_signal(String::new);
    let mut tesseract = use_signal(|| "eng".to_string());
    let mut easyocr = use_signal(|| "en".to_string());
    let mut seeded = use_signal(|| false);
    let mut saving_defaults = use_signal(|| false);

    // Seed the language boxes from the collection's defaults, once. After that the admin
    // owns them: a re-render must not undo what they typed.
    if let Some(Ok((tess, easy))) = defaults_res.read().as_ref().cloned() {
        use_effect(move || {
            if !*seeded.peek() {
                tesseract.set(tess.clone());
                easyocr.set(easy.clone());
                seeded.set(true);
            }
        });
    }
    let mut msg = use_signal(|| None::<String>);
    let mut error_msg = use_signal(|| None::<String>);
    let mut submitting = use_signal(|| false);

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

    let chosen = folder.read().clone();
    let can_create = !chosen.is_empty() && !*submitting.read();
    let create_style = if can_create {
        ""
    } else {
        "opacity: 0.5; cursor: not-allowed;"
    };

    rsx! {
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Add a dataset" }
            div { style: "{MODULE_BODY} display: flex; flex-direction: column; gap: 12px; max-width: 640px;",
                if let Some(m) = msg.read().clone() { SuccessBar { message: m } }
                if let Some(e) = error_msg.read().clone() { ErrorBar { message: e } }

                if let Some(err) = listing_error {
                    p { style: "{HELP_TEXT} margin: 0;",
                        "The datasets directory could not be read, so there is nothing to pick from: {err}"
                    }
                } else if folders.is_empty() {
                    p { style: "{HELP_TEXT} margin: 0;",
                        "No subfolders were found under the configured datasets path. "
                        "Put the documents in a folder there (datasets_mount_path in hoover4.ini) and reload."
                    }
                } else {
                    label { style: LABEL,
                        span { style: "width: 130px; color: #666;", "Folder" }
                        select {
                            style: "{SELECT} flex: 1;",
                            value: "{folder}",
                            onchange: move |e| {
                                let value = e.value();
                                if dataset_name.read().is_empty() || dataset_name.read().as_str() == suggest_dataset_name(&folder.peek()) {
                                    dataset_name.set(suggest_dataset_name(&value));
                                }
                                folder.set(value);
                            },
                            option { value: "", "\u{2014} pick a folder \u{2014}" }
                            for option in folders.iter() {
                                option {
                                    key: "{option.name}",
                                    value: "{option.name}",
                                    disabled: option.already_used,
                                    if option.already_used {
                                        "{option.name} ({option.entry_count} entries) \u{2014} already a dataset"
                                    } else {
                                        "{option.name} ({option.entry_count} entries)"
                                    }
                                }
                            }
                        }
                    }
                    p { style: "{HELP_TEXT} margin: 0;",
                        "Only direct subfolders of the configured datasets path are offered, and the path is composed on the server \u{2014} the form never carries one."
                    }

                    label { style: LABEL,
                        span { style: "width: 130px; color: #666;", "Dataset name" }
                        input {
                            style: "{INPUT} flex: 1;",
                            value: "{dataset_name}",
                            oninput: move |e| dataset_name.set(e.value()),
                        }
                    }
                    p { style: "{HELP_TEXT} margin: 0;",
                        "Lowercase letters, digits and underscores. It becomes part of the dataset id and cannot be changed afterwards."
                    }

                    label { style: LABEL,
                        span { style: "width: 130px; color: #666;", "Tesseract" }
                        input {
                            style: "{INPUT} flex: 1;",
                            value: "{tesseract}",
                            oninput: move |e| tesseract.set(e.value()),
                        }
                    }
                    label { style: LABEL,
                        span { style: "width: 130px; color: #666;", "EasyOCR" }
                        input {
                            style: "{INPUT} flex: 1;",
                            value: "{easyocr}",
                            oninput: move |e| easyocr.set(e.value()),
                        }
                    }
                    p { style: "{HELP_TEXT} margin: 0;",
                        "`+`-joined language codes, e.g. eng+ron. These are the languages the first pass runs with; "
                        "they can be changed later on the dataset page, but changing them re-runs OCR over the whole dataset. "
                        "New datasets start from the collection's defaults."
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
                                    saving_defaults.set(true);
                                    spawn(async move {
                                        msg.set(None);
                                        error_msg.set(None);
                                        match admin_set_collection_ocr_defaults(collectionname, tess, easy).await {
                                            Ok(()) => {
                                                msg.set(Some(
                                                    "Saved as this collection's defaults. Existing datasets keep their own settings \u{2014}                                                      there is deliberately no apply-to-all, because it would re-OCR every one of them."
                                                        .to_string(),
                                                ));
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
                                    let folder = folder.read().clone();
                                    let name = dataset_name.read().clone();
                                    let tess = tesseract.read().clone();
                                    let easy = easyocr.read().clone();
                                    submitting.set(true);
                                    spawn(async move {
                                        msg.set(None);
                                        error_msg.set(None);
                                        match admin_create_dataset(collectionname, folder, name, tess, easy).await {
                                            Ok(collection_dataset) => {
                                                msg.set(Some(format!(
                                                    "Created {collection_dataset}. Ingestion has started \u{2014} \
                                                     follow it on the collection's processing page."
                                                )));
                                                folders_res.restart();
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
