//! The folder tree of the upload page: the folders of the upload dataset, from the
//! structure index without a cache (`vfs_tree_children` with `folders_only`). Archives and
//! email containers are not destinations, so the tree shows folders only.

use common::vfs::{make_node_key, VfsNodeKind};
use dioxus::prelude::*;
use dioxus_free_icons::icons::md_file_icons::MdFolder;
use dioxus_free_icons::icons::md_navigation_icons::{MdChevronRight, MdExpandMore};
use dioxus_free_icons::Icon;

use crate::api::error_util::user_facing_message;
use crate::api::vfs_api::vfs_tree_children;

/// Children listed for one folder. A folder with more subfolders shows the first ones.
const CHILD_LIMIT: u64 = 500;

/// True when `path` is `folder` or a folder above it.
fn holds(path: &str, folder: &str) -> bool {
    path == "/" || folder == path || folder.starts_with(&format!("{path}/"))
}

#[component]
pub fn FolderTree(dataset: String, selected: String, on_select: Callback<String>) -> Element {
    rsx! {
        div {
            class: "x-upload-folders",
            style: "border: 1px solid; border-color: var(--x-border); border-radius: 6px; padding: 4px 0; max-height: 280px; overflow: auto; font-size: var(--x-text-body);",
            FolderRow {
                key: "{dataset}",
                dataset: dataset.clone(),
                path: "/".to_string(),
                name: dataset.clone(),
                depth: 0,
                selected,
                on_select,
            }
        }
    }
}

#[component]
fn FolderRow(
    dataset: String,
    path: String,
    name: String,
    depth: usize,
    selected: String,
    on_select: Callback<String>,
) -> Element {
    let initially_open = holds(&path, &selected);
    let mut open = use_signal(move || initially_open);
    let location = use_memo(use_reactive!(|dataset, path| (dataset, path)));
    let children = use_resource(move || {
        let (dataset, path) = location();
        let node_key = make_node_key(&dataset, "", &path);
        let wanted = open();
        async move {
            if !wanted {
                return Ok(Vec::new());
            }
            let page = vfs_tree_children(dataset, node_key, CHILD_LIMIT, 0, true).await?;
            Ok::<_, ServerFnError>(
                page.nodes.into_iter().filter(|n| n.kind == VfsNodeKind::Dir).collect::<Vec<_>>(),
            )
        }
    });
    let is_selected = selected == path;
    let row_style = if is_selected {
        "display: flex; align-items: center; gap: 4px; padding: 2px 8px; cursor: pointer; background-color: var(--x-selected);"
    } else {
        "display: flex; align-items: center; gap: 4px; padding: 2px 8px; cursor: pointer; background-color: transparent;"
    };
    let indent = format!("padding-left: {}px; display: inline-flex; align-items: center;", depth * 16);
    let select_path = path.clone();
    rsx! {
        div {
            class: "x-upload-folder",
            "data-path": "{path}",
            "aria-selected": "{is_selected}",
            style: row_style,
            onclick: move |_| on_select.call(select_path.clone()),
            span { style: "{indent}",
                button {
                    style: "border: none; background: none; padding: 0; cursor: pointer; display: inline-flex; color: var(--x-ink-muted);",
                    onclick: move |e| {
                        e.stop_propagation();
                        let now = open();
                        open.set(!now);
                    },
                    if open() {
                        Icon { icon: MdExpandMore, width: 18, height: 18 }
                    } else {
                        Icon { icon: MdChevronRight, width: 18, height: 18 }
                    }
                }
            }
            Icon { icon: MdFolder, width: 16, height: 16 }
            span { style: "overflow: hidden; text-overflow: ellipsis; white-space: nowrap;", "{name}" }
        }
        if open() {
            match &*children.read() {
                Some(Ok(nodes)) => rsx! {
                    for node in nodes.iter() {
                        FolderRow {
                            key: "{node.node_key}",
                            dataset: dataset.clone(),
                            path: node.path.clone(),
                            name: node.display_name().to_string(),
                            depth: depth + 1,
                            selected: selected.clone(),
                            on_select,
                        }
                    }
                },
                Some(Err(e)) => rsx! {
                    div { style: "color: var(--x-danger); padding: 2px 8px;", "{user_facing_message(e)}" }
                },
                None => rsx! {},
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::holds;

    #[test]
    fn a_folder_row_opens_when_it_holds_the_selected_folder() {
        assert!(holds("/", "/a/b"));
        assert!(holds("/a", "/a/b"));
        assert!(holds("/a/b", "/a/b"));
        assert!(!holds("/a/b", "/a"));
        assert!(!holds("/ab", "/a/b"));
    }
}
