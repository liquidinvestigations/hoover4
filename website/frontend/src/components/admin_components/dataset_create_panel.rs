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
    admin_create_dataset, admin_get_collection_ocr_defaults, admin_get_dataset,
    admin_list_dataset_folders, admin_list_dataset_mounts, admin_set_collection_ocr_defaults,
};
use crate::components::admin_components::dataset_ocr_panel::{split_languages, tesseract_choices, LanguageChecklist};
use crate::routes::Route;
use crate::tr;

/// The value of the folder option that asks for a new folder. It holds a `/`, so no
/// folder name can be equal to it.
const NEW_FOLDER: &str = "/new";
use crate::components::admin_components::{
    action_state, ErrorBar, SuccessBar, BTN, BTN_PRIMARY, HELP_TEXT, INPUT, LABEL, MODULE, MODULE_BODY,
    MODULE_CAPTION, SELECT, SUBHEADING,
};

/// How many times the panel reads the new dataset before it opens the dataset page, and
/// the wait between two reads.
const OPEN_ATTEMPTS: u32 = 20;
const OPEN_WAIT_MS: u64 = 500;

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
    let mut accept_uploads = use_signal(|| false);

    let mut folder = use_signal(String::new);
    let mut new_folder_name = use_signal(String::new);
    let mut dataset_name = use_signal(String::new);
    let mut tesseract = use_signal(|| vec!["eng".to_string()]);
    let mut easyocr = use_signal(|| vec!["en".to_string()]);
    let mut easyocr_on = use_signal(|| true);
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
        if let Some(Ok(defaults)) = defaults {
            if !*seeded.peek() {
                tesseract.set(split_languages(&defaults.tesseract_languages));
                easyocr.set(split_languages(&defaults.easyocr_languages));
                easyocr_on.set(!defaults.easyocr_languages.is_empty());
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

    let accept_value = *accept_uploads.read() && mount_writable;

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
    let ocr = defaults_res.read().as_ref().and_then(|r| r.as_ref().ok()).cloned().unwrap_or_default();
    let tesseract_value = tesseract.read().join("+");
    let easyocr_value = if *easyocr_on.read() { easyocr.read().join("+") } else { String::new() };
    let languages_ok = !tesseract.read().is_empty() && (!*easyocr_on.read() || !easyocr.read().is_empty());
    // A service that lists nothing leaves the stored codes selectable.
    let tesseract_offer = if ocr.tesseract_available.is_empty() {
        split_languages(&ocr.tesseract_languages)
    } else {
        tesseract_choices(&ocr.tesseract_available)
    };
    let easyocr_offer = if ocr.easyocr_supported.is_empty() {
        split_languages(&ocr.easyocr_languages)
    } else {
        ocr.easyocr_supported.clone()
    };
    let not_preloaded: Vec<String> = easyocr
        .read()
        .iter()
        .filter(|code| !ocr.easyocr_preloaded.is_empty() && !ocr.easyocr_preloaded.contains(code))
        .cloned()
        .collect();
    let can_create = !target_folder.is_empty()
        && !mount_name.is_empty()
        && !*submitting.read()
        && !name_taken
        && languages_ok;
    let create_style = action_state(can_create);
    let can_save_defaults = !*saving_defaults.read() && languages_ok;
    let save_style = action_state(can_save_defaults);

    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("dataset-create-panel-add-a-dataset")} }
            div { style: "{MODULE_BODY} display: flex; flex-direction: column; gap: 12px; max-width: 640px;",
                if let Some(m) = msg.read().clone() { SuccessBar { message: m } }
                if let Some(e) = error_msg.read().clone() { ErrorBar { message: e } }

                if let Some(err) = mounts_error {
                    p { style: "{HELP_TEXT} margin: 0;",
                        {tr!("dataset-create-panel-the-dataset-mounts-could-not", err: err.to_string())}
                    }
                } else if mounts_loading {
                    p { style: "{HELP_TEXT} margin: 0;", {tr!("dataset-create-panel-loading-the-dataset-mounts")} }
                } else if mounts.is_empty() {
                    p { style: "{HELP_TEXT} margin: 0;", {tr!("dataset-create-panel-no-dataset-mount-is-configured")} }
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
                            {tr!("dataset-create-panel-the-mount-folder-could-not", err: err.to_string())}
                        }
                    } else if folders.is_empty() && !mount_writable {
                        p { style: "{HELP_TEXT} margin: 0;",
                            {tr!("dataset-create-panel-no-subfolders-were-found-in")}
                            {tr!("dataset-create-panel-put-the-documents-in-a")}
                        }
                    } else {
                    label { style: LABEL,
                        span { style: "width: 130px; color: var(--x-ink-muted);", {tr!("dataset-create-panel-folder")} }
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
                            option { value: "", {tr!("dataset-create-panel-select-a-folder")} }
                            if mount_writable {
                                option { value: NEW_FOLDER, {tr!("dataset-create-panel-new-folder")} }
                            }
                            for option in folders.iter() {
                                option {
                                    key: "{option.name}",
                                    value: "{option.name}",
                                    disabled: option.already_used,
                                    if option.already_used {
                                        {tr!("dataset-create-panel-entries-already-a-dataset", option_name: option.name.to_string(), option_entry_count: option.entry_count)}
                                    } else {
                                        {tr!("dataset-create-panel-entries", option_name: option.name.to_string(), option_entry_count: option.entry_count)}
                                    }
                                }
                            }
                        }
                    }
                    if creating_folder {
                        label { style: LABEL,
                            span { style: "width: 130px; color: var(--x-ink-muted);", {tr!("dataset-create-panel-new-folder")} }
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
                            {tr!("dataset-create-panel-the-server-creates-this-folder")}
                            {tr!("dataset-create-panel-the-name-cannot-start-with")}
                        }
                    } else {
                        p { style: "{HELP_TEXT} margin: 0;",
                            {tr!("dataset-create-panel-the-list-shows-the-direct")}
                        }
                    }

                    label { style: LABEL,
                        span { style: "width: 130px; color: var(--x-ink-muted);", {tr!("dataset-create-panel-dataset-name")} }
                        input {
                            style: "{INPUT} flex: 1;",
                            value: "{dataset_name}",
                            oninput: move |e| dataset_name.set(e.value()),
                        }
                    }
                    p { style: "{HELP_TEXT} margin: 0;",
                        {tr!("dataset-create-panel-a-name-has-lowercase-letters")}
                        {tr!("dataset-create-panel-and-a-dash-a-space")}
                    }
                    if !saved_name.is_empty() {
                        p { class: "x-name-preview", style: "{HELP_TEXT} margin: 0;", {tr!("dataset-create-panel-the-dataset-is-saved-as", saved_name: saved_name.to_string())} }
                    }
                    if name_taken {
                        p { class: "x-name-collision", style: "margin: 0; color: var(--x-danger);", {tr!("dataset-create-panel-this-collection-has-a-dataset", saved_name: saved_name.to_string())} }
                    }

                    if mount_writable {
                        label { style: LABEL,
                            input {
                                r#type: "checkbox",
                                checked: accept_value,
                                onchange: move |e| accept_uploads.set(e.checked()),
                            }
                            {tr!("dataset-create-panel-accept-uploads")}
                        }
                    }

                    div {
                        h3 { style: SUBHEADING, {tr!("dataset-create-panel-tesseract")} }
                        if ocr.tesseract_available.is_empty() {
                            p { style: "{HELP_TEXT} margin: 0 0 6px;",
                                {tr!("dataset-ocr-panel-the-tesseract-service-did-not")}
                                {tr!("dataset-ocr-panel-the-list-comes-from-the")}
                            }
                        }
                        LanguageChecklist { available: tesseract_offer.clone(), selected: tesseract, disabled: false }
                        p { style: "{HELP_TEXT} margin: 6px 0 0;",
                            {tr!("dataset-ocr-panel-the-first-language-is-the")}
                            strong { "{tesseract_value}" }
                        }
                    }
                    div {
                        h3 { style: SUBHEADING, {tr!("dataset-create-panel-easyocr")} }
                        if !ocr.easyocr_configured {
                            p { style: "{HELP_TEXT} margin: 0 0 6px;", {tr!("dataset-ocr-panel-easyocr-is-off-on-this")} }
                        }
                        label { style: "display: flex; align-items: center; gap: 6px; font-size: var(--x-text-sm); margin-bottom: 8px;",
                            input {
                                r#type: "checkbox",
                                checked: *easyocr_on.read(),
                                onchange: move |e| easyocr_on.set(e.checked()),
                            }
                            {tr!("dataset-ocr-panel-enabled")}
                        }
                        if *easyocr_on.read() {
                            if ocr.easyocr_supported.is_empty() {
                                p { style: "{HELP_TEXT} margin: 0 0 6px;", {tr!("dataset-ocr-panel-the-easyocr-service-did-not")} }
                            }
                            LanguageChecklist { available: easyocr_offer.clone(), selected: easyocr, disabled: false }
                            if !not_preloaded.is_empty() {
                                p { style: "{HELP_TEXT} margin: 6px 0 0;",
                                    {tr!("admin-dataset-ocr-panel-models-not-in-image", languages: not_preloaded.join(", "))}
                                }
                            }
                        }
                    }
                    p { style: "{HELP_TEXT} margin: 0;",
                        {tr!("dataset-create-panel-the-form-starts-with-the")}
                        {tr!("dataset-create-panel-and-a-dataset-created-with")}
                    }

                    div {
                        button {
                            style: "{BTN} {save_style}",
                            disabled: !can_save_defaults,
                            onclick: {
                                let collectionname = collectionname.clone();
                                let tess = tesseract_value.clone();
                                let easy = easyocr_value.clone();
                                move |_| {
                                    let collectionname = collectionname.clone();
                                    let tess = tess.clone();
                                    let easy = easy.clone();
                                    if *saving_defaults.peek() { return; }
                                    saving_defaults.set(true);
                                    spawn(async move {
                                        msg.set(None);
                                        error_msg.set(None);
                                        match admin_set_collection_ocr_defaults(collectionname, tess, easy).await {
                                            Ok(changed) => {
                                                msg.set(Some(if changed.is_empty() {
                                                    {tr!("dataset-create-panel-saved-as-this-collection-s")}.to_string()
                                                } else {
                                                    tr!("dataset-create-panel-saved-as-this-collection-s-2", changed_join: (changed.join(", ")).to_string())
                                                }));
                                                defaults_res.restart();
                                            }
                                            Err(e) => error_msg.set(Some(e.to_string())),
                                        }
                                        saving_defaults.set(false);
                                    });
                                }
                            },
                            if *saving_defaults.read() { {tr!("dataset-create-panel-saving-u")} } else { {tr!("dataset-create-panel-save-as-collection-defaults")} }
                        }
                    }

                    div {
                        button {
                            style: "{BTN_PRIMARY} {create_style}",
                            disabled: !can_create,
                            onclick: {
                                let collectionname = collectionname.clone();
                                let tess = tesseract_value.clone();
                                let easy = easyocr_value.clone();
                                move |_| {
                                    let collectionname = collectionname.clone();
                                    let mount_name = mount_name.clone();
                                    let folder_value = target_folder.clone();
                                    let name = normalize_identifier(&dataset_name.read());
                                    let tess = tess.clone();
                                    let easy = easy.clone();
                                    let accept = accept_value;
                                    if *submitting.peek() { return; }
                                    submitting.set(true);
                                    let collectionname_for_route = collectionname.clone();
                                    spawn(async move {
                                        msg.set(None);
                                        error_msg.set(None);
                                        match admin_create_dataset(collectionname, mount_name, folder_value, creating_folder, name, tess, easy, accept).await {
                                            Ok(collection_dataset) => {
                                                // The dataset page is the confirmation. It opens once
                                                // the page can read the new dataset.
                                                for _ in 0..OPEN_ATTEMPTS {
                                                    if admin_get_dataset(collection_dataset.clone()).await.is_ok() {
                                                        break;
                                                    }
                                                    n0_future::time::sleep(std::time::Duration::from_millis(OPEN_WAIT_MS)).await;
                                                }
                                                on_created.call(collection_dataset.clone());
                                                navigator().push(Route::AdminDatasetPage {
                                                    collection_id: collectionname_for_route.clone(),
                                                    dataset_id: collection_dataset,
                                                });
                                            }
                                            Err(e) => error_msg.set(Some(e.to_string())),
                                        }
                                        submitting.set(false);
                                    });
                                }
                            },
                            if *submitting.read() { {tr!("dataset-create-panel-creating-u")} } else { {tr!("dataset-create-panel-create-and-ingest")} }
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
            span { style: "width: 130px; color: var(--x-ink-muted);", {tr!("dataset-create-panel-mount")} }
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
                            {tr!("dataset-create-panel-read-only", option_name: option.name.to_string())}
                        }
                    }
                }
            }
        }
    }
}
