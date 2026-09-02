//! Shared model picker for the chat composer.
//!
//! Grouped by provider, with context / vision / tools badges and median latency from
//! `llm_call_events`. The parent hides it while no model choices have loaded yet.

use common::llm_types::ChatModelChoice;
use dioxus::prelude::*;

fn option_label(m: &ChatModelChoice) -> String {
    let mut label = m.display_name.clone();
    if m.is_default {
        label.push_str(" (default)");
    }
    let mut badges = Vec::new();
    if m.supports_tools {
        badges.push("tools".to_string());
    }
    if m.supports_vision {
        badges.push("vision".to_string());
    }
    if m.is_reasoning {
        badges.push("reasoning".to_string());
    }
    if m.context_window > 0 {
        badges.push(format!("{}k ctx", m.context_window / 1000));
    }
    if m.median_latency_ms > 0 {
        badges.push(format!("p50 {}ms", m.median_latency_ms));
    }
    if !badges.is_empty() {
        label.push_str(" · ");
        label.push_str(&badges.join(", "));
    }
    label
}

#[component]
pub fn ModelSelector(
    choices: Vec<ChatModelChoice>,
    selected: Signal<String>,
    disabled: bool,
) -> Element {
    if choices.is_empty() {
        return rsx! { span {} };
    }
    let mut by_provider: Vec<(String, Vec<ChatModelChoice>)> = Vec::new();
    for c in choices {
        if let Some((_, list)) = by_provider.iter_mut().find(|(p, _)| p == &c.provider) {
            list.push(c);
        } else {
            by_provider.push((c.provider.clone(), vec![c]));
        }
    }
    let current = selected.read().clone();
    rsx! {
        label {
            style: "display: flex; align-items: center; gap: 6px; font-size: 13px; color: #475569;",
            span { "Model" }
            select {
                style: "border: 1px solid #CBD5E1; border-radius: 8px; padding: 4px 8px; \
                        font-size: 13px; color: #0F172A; background: white; max-width: 320px;",
                disabled: disabled,
                value: "{current}",
                onchange: move |e| selected.set(e.value()),
                for (provider, models) in by_provider {
                    optgroup {
                        key: "{provider}",
                        label: "{provider}",
                        for m in models {
                            option {
                                key: "{m.model_id}",
                                value: "{m.model_id}",
                                selected: m.model_id == current,
                                "{option_label(&m)}"
                            }
                        }
                    }
                }
            }
        }
    }
}
