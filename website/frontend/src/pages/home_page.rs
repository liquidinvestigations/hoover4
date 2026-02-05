use dioxus::prelude::*;
use dioxus_free_icons::icons::md_action_icons::MdSearch;
use dioxus_free_icons::icons::md_communication_icons::MdChat;
use dioxus_free_icons::Icon;

use common::search_query::SearchQuery;
use crate::data_definitions::url_param::UrlParam;
use crate::routes::Route;


/// Home page
#[component]
pub fn HomePage() -> Element {
    rsx! {
        Title { "Hoover Search - Home" }
        div {
            id: "x-home-container",
            style: "
                display:flex;
                flex-direction: column;
                gap: 20px;
                width: 100%;
                height: 100%;
                padding: 36px 40px;
                background: #F5F6F8;
                box-sizing: border-box;
                overflow: auto;
            ",

            MainTitle {}
            SubText {}

            // Cards Row
            div {
                style: "
                    display:flex;
                    flex-direction: row;
                    gap: 20px;
                    flex-wrap: wrap;
                    align-items: stretch;
                    margin-top: 10px;
                ",
                TextSearchCard {}
                AiChatCard {}
            }

            // Feedback Row
            div {
                style: "
                    display:flex;
                    flex-direction: row;
                    gap: 20px;
                ",
                FeedbackCard {}
            }
        }
    }
}


#[component]
fn MainTitle() -> Element {
    rsx! {
        div {
            style: "
                display:flex;
                align-items: center;
                gap: 8px;
                color: #0F172A;
                font-size: 46px;
                font-weight: 500;
                letter-spacing: -0.02em;
            ",
            img {
                src: asset!("/assets/favicon-transparent.png"),
                alt: "Hoover Logo",
                style: "width: 46px; height: 46px;",
            },
            span { "Welcome to" }
            span { style: "color:#4F46E5;", "Hoover!" }
        }
    }
}

#[component]
fn SubText() -> Element {
    rsx! {
        div {
            style: "
                color: #111827;
                font-size: 30px;
                line-height: 1.6;
                max-width: 620px;
                font-weight: 500;
            ",
            "Investigate faster with AI-powered tools built for journalists search, analyze, and uncover insights across thousands of documents."
        }
    }
}

#[component]
fn TextSearchCard() -> Element {

    rsx! {
        div {
            id: "x-card-text-search",
            style: "
                display:flex;
                flex-direction: column;
                gap: 14px;
                width: 520px;
                min-height: 280px;
                border-radius: 22px;
                padding: 22px 22px 26px 22px;
                background: linear-gradient(135deg, #2D208A 0%, #5B3DF5 100%);
                color: white;
                box-shadow: 0 8px 24px rgba(0,0,0,0.12);
            ",

            // Title
            div {
                style: "
                    font-size: 30px;
                    font-weight: 500;
                ",
                "Text Search"
            }

            // Description
            div {
                style: "
                    font-size: 20px;
                    font-weight: 500;
                    line-height: 1.5;
                    color: rgba(255,255,255,0.92);
                ",
                "Instantly find keywords or phrases across all uploaded reports, articles and documents. Perfect for tracing facts or following leads fast."
            }

            // Divider spacing
            div { style: "height: 8px; padding-top: 7px; margin-top:7px; border-top: 1px solid white; width: 100%; " }

            div {
                style: "
                    font-size: 16px;
                    color: rgba(255,255,255,0.9);
                    width: 100%;
                ",
                "*Type search terms in the text box below and hit Enter to start."
            }
            SearchCardInput {}
        }
    }
}

#[component]
fn SearchCardInput() -> Element {
    let n2 = navigator();
    let mut search_q = use_signal(|| "".to_string());
    rsx! {
        div {
            style: "
                display:flex;
                align-items:center;
                gap: 10px;
                background-color: white;
                border-radius: 9999px;
                padding: 10px 14px;
                height: 42px;
                color: #111827;
            ",
            Icon { icon: MdSearch, style: "width: 20px; height: 20px; color:#6B7280;" }
            input {
                r#type: "text",
                placeholder: "Search in knowledgebase",
                style: "
                    flex:1;
                    border: none;
                    outline: none;
                    background: transparent;
                    color: #111827;
                    font-size: 14px;
                ",
                oninput: move |e| {
                    *search_q.write() = e.value();
                },
                onkeypress: move |e| {
                    if e.key() == Key::Enter {
                        e.prevent_default();
                        let search_q = SearchQuery { query_string: search_q.read().clone(), ..Default::default() };
                        n2.push( Route::search_page_from_query(search_q) );
                    }
                },
            }
        }
    }
}

#[component]
fn AiChatCard() -> Element {
    rsx! {
        div {
            id: "x-card-ai-chat",
            style: "
                display:flex;
                flex-direction: column;
                gap: 12px;
                width: 520px;
                min-height: 280px;
                border-radius: 22px;
                padding: 22px 22px 26px 22px;
                background: linear-gradient(135deg, #0B7A2B 0%, #23A340 60%, #178E35 100%);
                color: white;
                box-shadow: 0 8px 24px rgba(0,0,0,0.12);
            ",

            div {
                style: "
                    font-size: 26px;
                    font-weight: 500;
                ",
                "Coming soon: Try Liquid Labs"
            }

            div {
                style: "
                    font-size: 20px;
                    font-weight: 500;
                    line-height: 1.6;
                    color: rgba(255,255,255,0.96);
                    max-width: 510px;
                ",
                "An AI powered journalistic search which connects insights across multiple sources. It will provide a new way to search by asking questions about your data and get clear, contextual answers."
            }
        }
    }
}

#[component]
fn FeedbackCard() -> Element {
    rsx! {
        div {
            id: "x-card-feedback",
            style: "
                display:flex;
                flex-direction: row;
                align-items: flex-start;
                gap: 14px;
                width: 520px;
                min-height: 140px;
                border-radius: 16px;
                padding: 18px;
                background: white;
                color: #111827;
                border: 1px solid #E5E7EB;
                box-shadow: 0 6px 16px rgba(0,0,0,0.06);
            ",

            // Icon box
            div {
                style: "
                    display:flex;
                    align-items:center;
                    justify-content:center;
                    width: 36px;
                    height: 36px;
                    border-radius: 10px;
                    background: #EEF2FF;
                    border: 1px solid #C7D2FE;
                    color: #4F46E5;
                ",
                Icon { icon: MdChat, style: "width: 20px; height: 20px;" }
            }

            // Text and button
            div {
                style: "
                    display:flex;
                    flex-direction: column;
                    gap: 16px;
                ",
                div { style: "font-size: 20px; font-weight: 500;", "We'd love to hear from you. Share your ideas, suggestions, or issues to help us improve Hoover." }

                div {
                    style: "display:flex; flex-direction:row;",
                    button {
                        style: "
                            height: 34px;
                            padding: 0 12px;
                            font-size: 14px;
                            border-radius: 8px;
                            background: white;
                            color: #111827;
                            border: 1px solid #D1D5DB;
                            cursor: pointer;
                        ",
                        "Feedback Form",
                    }
                }
            }
        }
    }
}
