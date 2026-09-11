//! Per-operation failure tree at `/admin/failures/:op_id`.
//!
//! The page shows every stored node for that `op_id`. `parent_index` of `-1` is a root
//! of that capture. Several roots are shown. A non-zero `nodes_dropped` on any node is
//! stated as a truncated tree. The stored record is raw; the copy control scrubs it.

use common::failure_types::FailureNode;
use dioxus::prelude::*;
use wasm_bindgen::JsCast;

use crate::api::admin_api::admin_get_failure_tree;
use crate::api::error_util::user_facing_message;
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN, HELP_TEXT, LINK, MODULE, MODULE_BODY,
    MODULE_CAPTION,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;

#[component]
pub fn AdminFailureDetailPage(op_id: String) -> Element {
    rsx! {
        Title { "Admin: failure {op_id}" }
        AdminGuard {
            AdminShell {
                title: "Failure tree".to_string(),
                breadcrumb: format!("Failures / {op_id}"),
                active: "failures".to_string(),
                SuspendWrapper { FailureDetailContent { op_id } }
            }
        }
    }
}

#[component]
fn FailureDetailContent(op_id: String) -> Element {
    let mut scope = use_signal(|| op_id.clone());
    if *scope.read() != op_id {
        scope.set(op_id.clone());
    }
    let tree_res = use_resource(move || {
        let id = scope();
        async move { admin_get_failure_tree(id).await }
    });
    let mut copied = use_signal(|| false);

    let data = tree_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned();
    let load_error = tree_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().err().map(user_facing_message));

    let Some(tree) = data else {
        return rsx! {
            if let Some(e) = load_error {
                ErrorBar { message: e }
            } else {
                p { style: HELP_TEXT, "Loading tree…" }
            }
        };
    };

    let root_count = tree.nodes.iter().filter(|n| n.parent_index == -1).count();
    let scrubbed = tree.scrubbed_copy.clone();

    rsx! {
        p { style: HELP_TEXT,
            Link { to: Route::AdminFailuresPage {}, style: LINK, "Back to failures" }
            " · "
            Link { to: Route::AdminOperationsPage {}, style: LINK, "Operations" }
        }
        if copied() {
            SuccessBar { message: "Scrubbed copy written to the clipboard.".to_string() }
        }
        if tree.truncated {
            ErrorBar { message: "This tree is truncated. At least one capture dropped nodes.".to_string() }
        }
        if tree.capture_expired {
            ErrorBar { message: "The captured tree has expired. The operations row is still present.".to_string() }
        }
        if tree.nodes.is_empty() && !tree.capture_expired {
            p { style: HELP_TEXT, "No captured nodes for this operation." }
        }

        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Operation" }
            div { style: MODULE_BODY,
                p { id: "x-failures-detail-op",
                    code { "{tree.op_id}" }
                }
                p { style: HELP_TEXT,
                    "{tree.operation_kind} · {tree.operation_state} · {root_count} root(s) · {tree.nodes.len()} node(s)"
                }
                if !tree.operation_error.is_empty() {
                    p { "{tree.operation_error}" }
                }
                p {
                    a {
                        id: "x-failures-temporal",
                        href: "{tree.temporal_url}",
                        target: "_blank",
                        style: LINK,
                        "Open in Temporal"
                    }
                }
            }
        }

        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Scrubbed copy" }
            div { style: MODULE_BODY,
                p { style: HELP_TEXT,
                    "The scrubbed copy is for handing a failure to a language model that must not read the corpus. Dataset-mount paths become a basename hash. Any value over 512 characters is replaced with its length. The stored record stays raw."
                }
                button {
                    id: "x-failures-copy-scrubbed",
                    style: BTN,
                    onclick: move |_| {
                        copy_text(&scrubbed);
                        copied.set(true);
                    },
                    "Copy scrubbed record"
                }
                pre {
                    id: "x-failures-scrubbed-copy",
                    style: "margin-top: 12px; max-height: 240px; overflow: auto; background: #f6f6f6; padding: 8px; font-size: 11px; white-space: pre-wrap;",
                    "{tree.scrubbed_copy}"
                }
            }
        }

        div { id: "x-failures-tree", style: MODULE,
            h2 { style: MODULE_CAPTION, "Tree" }
            div { style: MODULE_BODY,
                for node in tree.nodes.iter() {
                    TreeNode { key: "{node.node_index}", node: node.clone() }
                }
            }
        }
    }
}

#[component]
fn TreeNode(node: FailureNode) -> Element {
    let is_root = node.parent_index == -1;
    let indent = (node.depth as u32).saturating_mul(16);
    let stack_note = if node.stack_trace.chars().count() < node.stack_trace_original_len as usize {
        format!(
            "showing {} of {} characters",
            node.stack_trace.chars().count(),
            node.stack_trace_original_len
        )
    } else {
        String::new()
    };
    rsx! {
        div {
            id: "x-failures-node-{node.node_index}",
            style: "margin-left: {indent}px; margin-bottom: 16px; padding: 8px; border-left: 3px solid #79aec8;",
            p { style: "margin: 0 0 4px; font-weight: 600;",
                if is_root { "Root · " }
                "{node.error_class}"
                if !node.error_type.is_empty() { " / {node.error_type}" }
            }
            p { style: HELP_TEXT,
                "node {node.node_index} · parent {node.parent_index} · depth {node.depth} · source {node.source} · stage {node.stage} · {node.task_name}"
            }
            p { "{node.message}" }
            p { style: HELP_TEXT,
                "workflow {node.workflow_id} · run {node.run_id} · activity {node.activity_id} · attempt {node.attempt}"
            }
            if node.nodes_dropped > 0 {
                p { style: "color: #ba2121; font-size: 12px;",
                    "{node.nodes_dropped} node(s) dropped at this capture"
                }
            }
            if !node.details_json.is_empty() {
                pre { style: "font-size: 11px; background: #f6f6f6; padding: 8px; overflow: auto; max-height: 160px;",
                    "{node.details_json}"
                }
            }
            if !node.stack_trace.is_empty() {
                if !stack_note.is_empty() {
                    p { style: HELP_TEXT, "{stack_note}" }
                }
                pre {
                    class: "x-failures-stack",
                    style: "font-size: 11px; background: #f6f6f6; padding: 8px; overflow: auto; max-height: 240px; white-space: pre-wrap;",
                    "{node.stack_trace}"
                }
            }
        }
    }
}

fn copy_text(text: &str) {
    let secure = web_sys::window()
        .map(|window| window.is_secure_context())
        .unwrap_or(false);
    if secure {
        if let Some(window) = web_sys::window() {
            let promise = window.navigator().clipboard().write_text(text);
            wasm_bindgen_futures::spawn_local(async move {
                let _ = wasm_bindgen_futures::JsFuture::from(promise).await;
            });
        }
    } else {
        copy_via_exec_command(text);
    }
}

fn copy_via_exec_command(text: &str) {
    let Some(window) = web_sys::window() else {
        return;
    };
    let Some(document) = window.document() else {
        return;
    };
    let Ok(element) = document.create_element("textarea") else {
        return;
    };
    let _ = element.set_attribute("style", "position: fixed; top: -1000px; opacity: 0;");
    element.set_text_content(Some(text));
    if let Some(body) = document.body() {
        let _ = body.append_child(&element);
        if let Some(area) = element.dyn_ref::<web_sys::HtmlTextAreaElement>() {
            area.select();
        }
        if let Some(html_document) = document.dyn_ref::<web_sys::HtmlDocument>() {
            let _ = html_document.exec_command("copy");
        }
        let _ = body.remove_child(&element);
    }
}
