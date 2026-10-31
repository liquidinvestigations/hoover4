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
use crate::tr;

#[component]
pub fn AdminFailureDetailPage(op_id: String) -> Element {
    rsx! {
        Title { {tr!("admin-failure-detail-admin-failure", op_id: op_id.to_string())} }
        AdminGuard {
            AdminShell {
                title: tr!("admin-failure-detail-failure-tree-of", op_id: op_id.to_string()),
                breadcrumb: "Failures".to_string(),
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
                p { style: HELP_TEXT, {tr!("admin-failure-detail-loading-tree")} }
            }
        };
    };

    let root_count = tree.nodes.iter().filter(|n| n.parent_index == -1).count();
    let scrubbed = tree.scrubbed_copy.clone();

    rsx! {
        p { style: HELP_TEXT,
            Link { to: crate::pages::admin::failures::failures_route("", ""), style: LINK, {tr!("admin-failure-detail-back-to-errors-and-failures")} }
            " · "
            Link { to: Route::AdminOperationsPage {}, style: LINK, {tr!("admin-failure-detail-operations")} }
        }
        if copied() {
            SuccessBar { message: tr!("admin-failure-detail-scrubbed-copy-written-to-the").to_string() }
        }
        if tree.truncated {
            ErrorBar { message: tr!("admin-failure-detail-this-tree-is-truncated-at").to_string() }
        }
        if tree.capture_expired {
            ErrorBar { message: tr!("admin-failure-detail-the-captured-tree-has-expired").to_string() }
        }
        if tree.nodes.is_empty() && !tree.capture_expired {
            p { style: HELP_TEXT, {tr!("admin-failure-detail-no-captured-nodes-for-this")} }
        }

        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-failure-detail-operation")} }
            div { style: MODULE_BODY,
                p { id: "x-failures-detail-op",
                    code { "{tree.op_id}" }
                }
                p { style: HELP_TEXT,
                    {tr!("admin-failure-detail-root-s-node-s", tree_operation_kind: tree.operation_kind.to_string(), tree_operation_state: tree.operation_state.to_string(), root_count: root_count, tree_nodes_len: tree.nodes.len())}
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
                        {tr!("admin-failure-detail-open-in-temporal")}
                    }
                }
            }
        }

        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-failure-detail-scrubbed-copy")} }
            div { style: MODULE_BODY,
                p { style: HELP_TEXT,
                    {tr!("admin-failure-detail-the-scrubbed-copy-replaces-dataset")}
                }
                button {
                    id: "x-failures-copy-scrubbed",
                    style: BTN,
                    onclick: move |_| {
                        copy_text(&scrubbed);
                        copied.set(true);
                    },
                    {tr!("admin-failure-detail-copy-scrubbed-record")}
                }
                pre {
                    id: "x-failures-scrubbed-copy",
                    style: "margin-top: 12px; max-height: 240px; overflow: auto; background-color: var(--x-surface-muted); padding: 8px; font-size: var(--x-text-xs); white-space: pre-wrap;",
                    "{tree.scrubbed_copy}"
                }
            }
        }

        div { id: "x-failures-tree", class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-failure-detail-tree")} }
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
        tr!("admin-failure-detail-showing-of-characters", node_stack_trace_chars_count: (node.stack_trace.chars().count()).to_string(), node_stack_trace_original_len: node.stack_trace_original_len.to_string())
    } else {
        String::new()
    };
    rsx! {
        div {
            id: "x-failures-node-{node.node_index}",
            style: "margin-left: {indent}px; margin-bottom: 16px; padding: 8px; border-left: 3px solid; border-left-color: var(--x-link);",
            p { style: "margin: 0 0 4px; font-weight: 600;",
                if is_root { {tr!("admin-failure-detail-root")} }
                "{node.error_class}"
                if !node.error_type.is_empty() { " / {node.error_type}" }
            }
            p { style: HELP_TEXT,
                {tr!("admin-failure-detail-node-parent-depth-source-stage", node_node_index: node.node_index.to_string(), node_parent_index: node.parent_index.to_string(), node_depth: node.depth.to_string(), node_source: node.source.to_string(), node_stage: node.stage.to_string(), node_task_name: node.task_name.to_string())}
            }
            p { "{node.message}" }
            p { style: HELP_TEXT,
                {tr!("admin-failure-detail-workflow-run-activity-attempt", node_workflow_id: node.workflow_id.to_string(), node_run_id: node.run_id.to_string(), node_activity_id: node.activity_id.to_string(), node_attempt: node.attempt.to_string())}
            }
            if node.nodes_dropped > 0 {
                p { style: "color: var(--x-danger); font-size: var(--x-text-xs);",
                    {tr!("admin-failure-detail-node-s-dropped-at-this", node_nodes_dropped: node.nodes_dropped.to_string())}
                }
            }
            if !node.details_json.is_empty() {
                pre { style: "font-size: var(--x-text-xs); background-color: var(--x-surface-muted); padding: 8px; overflow: auto; max-height: 160px;",
                    "{node.details_json}"
                }
            }
            if !node.stack_trace.is_empty() {
                if !stack_note.is_empty() {
                    p { style: HELP_TEXT, "{stack_note}" }
                }
                pre {
                    class: "x-failures-stack",
                    style: "font-size: var(--x-text-xs); background-color: var(--x-surface-muted); padding: 8px; overflow: auto; max-height: 240px; white-space: pre-wrap;",
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
