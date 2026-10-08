//! Admin feedback page: the reports that people sent with the bug control.
//!
//! The search text, the status filter and the page number are in the page address.

use common::feedback_types::{FeedbackListRow, FeedbackStatusFilter, FEEDBACK_PAGE_SIZE};
use dioxus::prelude::*;

use crate::api::admin_api::{admin_get_feedback, admin_list_feedback, admin_set_feedback_flags};
use crate::api::error_util::user_facing_message;
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, BTN, BTN_SMALL, HELP_TEXT, INPUT, LINK, SELECT, SUBHEADING,
    TABLE, TD, TH,
};
use crate::components::feedback_control::kb;
use crate::components::suspend_boundary::SuspendWrapper;
use crate::pages::admin::collections_list::short_date;
use crate::routes::Route;

#[component]
pub fn AdminFeedbackPage(search: String, status: String, page: u32) -> Element {
    rsx! {
        Title { "Admin: feedback" }
        AdminGuard {
            AdminShell {
                title: "Feedback".to_string(),
                breadcrumb: String::new(),
                active: "feedback".to_string(),
                SuspendWrapper { FeedbackContent { search, status, page } }
            }
        }
    }
}

fn route(search: &str, status: FeedbackStatusFilter, page: u32) -> Route {
    Route::AdminFeedbackPage {
        search: search.to_string(),
        status: status.as_param().to_string(),
        page: page.max(1),
    }
}

#[component]
fn FeedbackContent(search: String, status: String, page: u32) -> Element {
    let status = FeedbackStatusFilter::from_param(&status);
    let page = page.max(1);
    // Props are not reactive, so the resource reads signals that follow the props.
    let mut query = use_signal(|| (search.clone(), status, page));
    if *query.peek() != (search.clone(), status, page) {
        query.set((search.clone(), status, page));
    }
    let mut list_res = use_resource(move || {
        let (search, status, page) = query();
        async move { admin_list_feedback(search, status, page).await }
    });
    let mut draft = use_signal(|| search.clone());
    let mut action_error = use_signal(|| None::<String>);
    let nav = navigator();

    let submit_search = {
        let search_status = status;
        move |_| {
            nav.push(route(&draft(), search_status, 1));
        }
    };

    rsx! {
        div { style: "display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 14px;",
            input {
                id: "x-feedback-search",
                style: "{INPUT} width: 320px;",
                placeholder: "Search titles, descriptions, accounts and addresses",
                value: "{draft}",
                oninput: move |e| draft.set(e.value()),
                onkeydown: move |e: KeyboardEvent| {
                    if e.key() == Key::Enter {
                        nav.push(route(&draft(), status, 1));
                    }
                },
            }
            button { style: BTN, onclick: submit_search, "Search" }
            select {
                id: "x-feedback-status",
                style: SELECT,
                "aria-label": "Status",
                onchange: {
                    let search = search.clone();
                    move |e: Event<FormData>| {
                        nav.push(route(&search, FeedbackStatusFilter::from_param(&e.value()), 1));
                    }
                },
                for s in FeedbackStatusFilter::ALL {
                    option { value: s.as_param(), selected: s == status, "{s.label()}" }
                }
            }
        }
        if let Some(message) = action_error() {
            ErrorBar { message }
        }
        match &*list_res.read() {
            None => rsx! { p { style: HELP_TEXT, "Loading reports\u{2026}" } },
            Some(Err(e)) => rsx! { ErrorBar { message: user_facing_message(e) } },
            Some(Ok(data)) => {
                let pages = data.total.div_ceil(u64::from(FEEDBACK_PAGE_SIZE)).max(1);
                rsx! {
                    p { id: "x-feedback-count", style: HELP_TEXT,
                        if data.total == 1 { "1 report matches." } else { "{data.total} reports match." }
                    }
                    if !data.rows.is_empty() {
                        table { style: TABLE,
                            thead {
                                tr {
                                    th { style: TH, "Received" }
                                    th { style: TH, "Type" }
                                    th { style: TH, "Title" }
                                    th { style: TH, "From" }
                                    th { style: TH, "Captures" }
                                    th { style: TH, "State" }
                                    th { style: TH, "" }
                                }
                            }
                            tbody {
                                for row in data.rows.iter().cloned() {
                                    FeedbackRow {
                                        key: "{row.report_id}",
                                        row,
                                        on_change: move |result: Result<(), String>| {
                                            match result {
                                                Ok(()) => {
                                                    action_error.set(None);
                                                    list_res.restart();
                                                }
                                                Err(message) => action_error.set(Some(message)),
                                            }
                                        },
                                    }
                                }
                            }
                        }
                    }
                    if pages > 1 {
                        div { style: "display: flex; gap: 12px; align-items: center; margin-top: 12px;",
                            if page > 1 {
                                Link { to: route(&search, status, page - 1), style: LINK, "Previous page" }
                            }
                            span { style: HELP_TEXT, "Page {page} of {pages}" }
                            if u64::from(page) < pages {
                                Link { id: "x-feedback-next-page", to: route(&search, status, page + 1), style: LINK, "Next page" }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn FeedbackRow(row: FeedbackListRow, on_change: EventHandler<Result<(), String>>) -> Element {
    let mut expanded = use_signal(|| false);
    let weight = if row.is_read { "400" } else { "600" };
    let kind_label = if row.kind == "bug" { "Bug" } else { "Feedback" };
    let set_flags = {
        let report_id = row.report_id.clone();
        move |is_read: bool, is_archived: bool| {
            let report_id = report_id.clone();
            spawn(async move {
                let result = admin_set_feedback_flags(report_id, is_read, is_archived)
                    .await
                    .map_err(|e| user_facing_message(&e));
                on_change.call(result);
            });
        }
    };
    let mut toggle_read = set_flags.clone();
    let mut toggle_archive = set_flags;
    let (is_read, is_archived) = (row.is_read, row.is_archived);
    rsx! {
        tr { class: "x-feedback-row",
            td { style: "{TD} white-space: nowrap;", title: "{row.created_at}", "{short_time(&row.created_at)}" }
            td { style: TD, "{kind_label}" }
            td { style: TD,
                button {
                    class: "x-feedback-title",
                    style: "background: none; border: none; padding: 0; cursor: pointer; text-align: left; font: inherit; color: var(--x-link); font-weight: {weight};",
                    "aria-expanded": "{expanded()}",
                    onclick: move |_| expanded.toggle(),
                    "{row.title}"
                }
            }
            td { style: TD, "{row.username}" }
            td { style: "{TD} white-space: nowrap;",
                "Image {kb(row.screenshot_bytes)}"
                div { style: HELP_TEXT, "DOM {kb(row.dom_bytes)}" }
            }
            td { style: TD,
                if is_read { "Read" } else { "Unread" }
                if is_archived { div { style: HELP_TEXT, "Archived" } }
            }
            td { style: "{TD} white-space: nowrap;",
                button { class: "x-feedback-read", style: BTN_SMALL, onclick: move |_| toggle_read(!is_read, is_archived),
                    if is_read { "Mark unread" } else { "Mark read" }
                }
                " "
                button { class: "x-feedback-archive", style: BTN_SMALL, onclick: move |_| toggle_archive(is_read, !is_archived),
                    if is_archived { "Restore" } else { "Archive" }
                }
            }
        }
        if expanded() {
            tr {
                td { style: TD, colspan: 7,
                    FeedbackDetail { row: row.clone() }
                }
            }
        }
    }
}

#[component]
fn FeedbackDetail(row: FeedbackListRow) -> Element {
    let report_id = row.report_id.clone();
    let detail_res = use_resource(move || {
        let id = report_id.clone();
        async move { admin_get_feedback(id).await }
    });
    let image_url = format!("/_feedback/{}/screenshot.png", row.report_id);
    let dom_url = format!("/_feedback/{}/dom.html", row.report_id);
    rsx! {
        div { class: "x-feedback-detail", style: "padding: 4px 0 8px;",
            p { style: HELP_TEXT,
                "Page: "
                if is_safe_link(&row.page_url) {
                    a { href: "{row.page_url}", style: LINK, target: "_blank", rel: "noopener", "{row.page_url}" }
                } else {
                    "{row.page_url}"
                }
            }
            if row.description.is_empty() {
                p { style: HELP_TEXT, "The report has no description." }
            } else {
                p { style: "white-space: pre-wrap; margin: 8px 0;", "{row.description}" }
            }
            div { style: "display: flex; gap: 16px; margin: 8px 0;",
                if row.screenshot_bytes > 0 {
                    a { href: "{image_url}", style: LINK, target: "_blank", rel: "noopener", "Open the page image" }
                }
                if row.dom_bytes > 0 {
                    a { href: "{dom_url}", style: LINK, target: "_blank", rel: "noopener", "Open the DOM copy" }
                }
            }
            if row.screenshot_bytes > 0 {
                img {
                    src: "{image_url}",
                    alt: "Page image of the report",
                    style: "display: block; max-width: 100%; max-height: 480px; border: 1px solid var(--x-border);",
                }
            }
            h3 { style: SUBHEADING, "Debug context and browser log" }
            match &*detail_res.read() {
                None => rsx! { p { style: HELP_TEXT, "Loading\u{2026}" } },
                Some(Err(e)) => rsx! { ErrorBar { message: user_facing_message(e) } },
                Some(Ok(detail)) => rsx! {
                    pre { style: "font-size: var(--x-text-xs); max-height: 360px; overflow: auto; background: var(--x-surface-muted); padding: 8px; border-radius: 6px; white-space: pre-wrap; word-break: break-word;",
                        "{pretty_json(&detail.context_json)}"
                    }
                },
            }
        }
    }
}

/// The sender's browser wrote the page address, so only a web or site address becomes a
/// link. A `javascript:` address would otherwise run in the session of the administrator.
fn is_safe_link(url: &str) -> bool {
    let lower = url.trim_start().to_ascii_lowercase();
    lower.starts_with("https://") || lower.starts_with("http://") || (lower.starts_with('/') && !lower.starts_with("//"))
}

fn pretty_json(text: &str) -> String {
    serde_json::from_str::<serde_json::Value>(text)
        .ok()
        .and_then(|v| serde_json::to_string_pretty(&v).ok())
        .unwrap_or_else(|| text.to_string())
}

/// `YYYY-MM-DD HH:MM` of an RFC 3339 timestamp.
fn short_time(rfc3339: &str) -> String {
    let date = short_date(rfc3339);
    let time = rfc3339.split('T').nth(1).map(|t| t.get(..5).unwrap_or(t)).unwrap_or("");
    format!("{date} {time}").trim().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_web_and_site_addresses_become_links() {
        assert!(is_safe_link("https://demo.example/search"));
        assert!(is_safe_link("/admin/feedback"));
        assert!(!is_safe_link("javascript:alert(1)"));
        assert!(!is_safe_link(" JavaScript:alert(1)"));
        assert!(!is_safe_link("//other.example/x"));
    }

    #[test]
    fn short_time_keeps_minutes() {
        assert_eq!(short_time("2026-10-08T17:42:10.123Z"), "2026-10-08 17:42");
    }
}
