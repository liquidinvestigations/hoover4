//! Error boundary component for rendering failures.
//!
//! Anything that puts an error in front of a user carries the class `x-error-display`.
//! It has no stylesheet rule: it exists so `website/tools/capture_screenshots.py` can find
//! surfaced errors structurally instead of guessing from the words on screen.

use dioxus::prelude::*;

#[component]
pub fn GlobalErrorBoundary(boundary_name: ReadSignal<String>, children: Element) -> Element {
    rsx! {
        ErrorBoundary {
            handle_error: move |_err: ErrorContext| {
                rsx! {
                    h1 {
                        class: "x-error-display",
                        style: "color:red; font-size: 54px; border: 1px solid red; padding: 10px; border-radius: 5px; margin: 15px;",
                        "Error",
                    }
                    p {
                        style: "color:darkred; font-size: 26px; border: 1px solid red; padding: 10px; border-radius: 5px; margin: 15px;",
                        "Boundary: {boundary_name}"
                    }
                    a {
                        href: "/",
                        style: "color:blue; font-size: 26px; border: 1px solid blue; padding: 10px; border-radius: 5px; margin: 15px;",
                        "Return to Home Page"
                    }
                    pre {
                        style: "color:black; border: 1px solid red; padding: 10px; border-radius: 5px; margin: 15px; text-wrap: auto;",
                        "{_err:#?}"
                    }
                }
            },
            children
        }
    }
}

#[component]
pub fn ComponentErrorBoundary(children: Element) -> Element {
    rsx! {
        ErrorBoundary {
            handle_error: |_err: ErrorContext| {
                let error = _err.error();
                let error_txt = if let Some(err) = error {
                    format!("{:#?}", err.0)
                } else {
                    "Unknown error".to_string()
                };
                rsx! {
                    ComponentErrorDisplay {
                        error_txt,
                        button {
                            style: "color:blue; font-size: 26px; border: 1px solid blue; padding: 10px; border-radius: 5px; margin: 15px;",
                            onclick: move |_| {
                                _err.clear_errors();
                            },
                            "Try Again"
                        }
                    }
                }
            },
            div {
                width: "100%",
                height: "100%",
                {children}
            }
        }
    }
}

/// The red box for a failure that is ours.
///
/// `error_txt` is a plain `String` and must stay one. A `ReadSignal<T>` prop is built by
/// a conversion that **runs a hook in the caller's scope**, so instantiating this
/// component inside an `if` — which is the natural way to write an error branch — changes
/// the caller's hook count between renders and panics with *"Unable to retrieve the hook
/// that was initialized at this index"* the first time the branch flips.
#[component]
pub fn ComponentErrorDisplay(error_txt: String, children: Element) -> Element {
    rsx! {
        div {
            class: "x-error-display",
            width: "100%",
            height: "100%",
            display: "flex",
            flex_direction: "column",
            align_items: "center",
            justify_content: "center",

            h1 {
                style: "color:red; font-size: 34px; border: 1px solid red; padding: 10px; border-radius: 5px; margin: 5px;",
                "Component Error",
            }

            pre {
                style: "color:darkred; border: 1px solid red; padding: 10px; border-radius: 5px; margin: 5px; text-wrap: auto; max-width: 500px; max-height: 400px; overflow-y: auto;",
                "{error_txt}"
            }

            {children}
        }
    }
}

/// The single way a failed **server call** is shown to a reader.
///
/// Two things it exists to stop, both of which a `format!("{e:#?}")` at the call site
/// produces every time: a Rust struct on the page, and a query the server declined
/// reading as a crash. The status is what separates the two — a 4xx is advice for the
/// person who typed it, everything else is a failure of ours.
///
/// It takes the error **by value**, not as a `ReadSignal`, for the reason spelled out on
/// [`ComponentErrorDisplay`]: every call site instantiates it inside an error branch, and
/// a signal prop would put a hook in each of those branches.
///
/// **One template and one `return`, and no child component.** The two presentations differ
/// only in the strings and styles they interpolate. A version of this that branched — an
/// early `return` for one case, a different child component for the other — panicked the
/// render with *"Unable to retrieve the hook that was initialized at this index"* as soon
/// as an error changed status between renders, which is exactly what a document viewer
/// does while its panels resolve. Structure that varies per branch is the hazard; values
/// that vary are not.
#[component]
pub fn ServerErrorDisplay(error: ServerFnError) -> Element {
    let message = crate::api::error_util::user_facing_message(&error);
    let user_input = crate::api::error_util::is_user_input_error(&error);

    let heading = if user_input {
        "This search cannot run"
    } else {
        "Component Error"
    };
    let heading_style = if user_input {
        "font-size: 20px; font-weight: 600; color: rgba(0, 0, 0, 0.8);"
    } else {
        "color:red; font-size: 34px; border: 1px solid red; padding: 10px; border-radius: 5px; margin: 5px;"
    };
    let message_style = if user_input {
        "font-size: 15px; color: rgba(0, 0, 0, 0.7); max-width: 560px; text-align: center;"
    } else {
        "color:darkred; border: 1px solid red; padding: 10px; border-radius: 5px; margin: 5px; text-wrap: auto; max-width: 500px; max-height: 400px; overflow-y: auto;"
    };

    rsx! {
        div {
            class: "x-error-display",
            style: "
                width: 100%;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 24px 16px;
                gap: 8px;
            ",
            div { style: "{heading_style}", "{heading}" }
            div { style: "{message_style}", "{message}" }
        }
    }
}
