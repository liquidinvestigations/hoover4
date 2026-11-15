//! The group choice of a new chat or board.
//!
//! Every chat and board belongs to one group (`common::item_groups`). The list shows the
//! explicit groups of the person. A checkbox adds the implicit groups, which the identity
//! provider gives to every user. The first explicit group is selected at first. With no group
//! to select, the picker says why and what to do, and `selected` stays empty, so the form
//! does not submit.

use common::item_groups::{default_group, keep_or_first, listed_groups, GroupChoice};
use dioxus::prelude::*;
use dioxus_free_icons::icons::md_social_icons::MdGroup;
use dioxus_free_icons::Icon;

use crate::api::chat_api::chat_group_choices;
use crate::api::error_util::user_facing_message;
use crate::components::admin_components::{HELP_TEXT, LABEL, SELECT};
use crate::tr;

/// `selected` is the chosen group, empty when none can be chosen. `choices` holds every group
/// of the person once they load, so the form can read the collections of the chosen group.
/// `hint` says what the members of the group can do with the new item.
#[component]
pub fn GroupPicker(selected: Signal<String>, choices: Signal<Option<Vec<GroupChoice>>>, hint: String) -> Element {
    let groups_res = use_resource(chat_group_choices);
    let mut show_implicit = use_signal(|| false);

    use_effect(move || {
        if let Some(Ok(list)) = &*groups_res.read() {
            if choices.peek().is_none() {
                selected.set(default_group(list));
                choices.set(Some(list.clone()));
            }
        }
    });

    let all = match &*groups_res.read() {
        Some(Ok(list)) => list.clone(),
        Some(Err(e)) => {
            return rsx! {
                p { class: "x-group-picker-error", style: "margin: 0; color: var(--x-danger); font-size: var(--x-text-detail);",
                    "{user_facing_message(e)}"
                }
            };
        }
        None => return rsx! { span { style: HELP_TEXT, {tr!("group-picker-loading-groups-u")} } },
    };
    let listed = listed_groups(&all, show_implicit());
    let has_implicit = all.iter().any(|g| g.implicit);
    let current = selected.read().clone();

    rsx! {
        div { class: "x-group-picker", style: "display: flex; flex-direction: column; gap: 4px;",
            div { style: "display: flex; gap: 14px; flex-wrap: wrap; align-items: center;",
                if !listed.is_empty() {
                    label { style: LABEL,
                        {tr!("group-picker-group")}
                        select {
                            class: "x-group-picker-select",
                            style: SELECT,
                            onchange: move |e: FormEvent| selected.set(e.value()),
                            for g in listed.iter() {
                                option { key: "{g.name}", value: "{g.name}", selected: g.name == current, "{g.name}" }
                            }
                        }
                    }
                }
                if has_implicit {
                    label { style: LABEL,
                        input {
                            class: "x-group-picker-implicit",
                            r#type: "checkbox",
                            checked: show_implicit(),
                            onchange: {
                                let all = all.clone();
                                move |e: FormEvent| {
                                    show_implicit.set(e.checked());
                                    let next = keep_or_first(&listed_groups(&all, e.checked()), &selected.peek());
                                    selected.set(next);
                                }
                            },
                        }
                        {tr!("group-picker-show-groups-of-all-users")}
                    }
                }
            }
            if listed.is_empty() {
                p { class: "x-group-picker-empty", style: "margin: 0; color: var(--x-danger); font-size: var(--x-text-detail);",
                    if has_implicit {
                        {tr!("group-picker-you-have-no-group-of-your-own")}
                    } else {
                        {tr!("group-picker-you-are-not-in-a-group")}
                    }
                }
            } else {
                p { style: "margin: 0; {HELP_TEXT}", "{hint}" }
            }
        }
    }
}

/// The group of a chat or board on its card: a group icon and the name, with the word "Group"
/// as the title of both.
#[component]
pub fn GroupName(name: String) -> Element {
    if name.is_empty() {
        return rsx! {};
    }
    rsx! {
        span {
            class: "x-item-group",
            title: tr!("group-picker-group"),
            style: "display: inline-flex; align-items: center; gap: 3px; min-width: 0; max-width: 100%; \
                    font-size: var(--x-text-detail); color: var(--x-ink-muted);",
            Icon { icon: MdGroup, style: "width: 14px; height: 14px; flex-shrink: 0;" }
            span { style: "overflow: hidden; text-overflow: ellipsis; white-space: nowrap;", "{name}" }
        }
    }
}
