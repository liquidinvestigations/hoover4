//! Error boundary component for rendering failures.

use dioxus::prelude::*;

#[component]
pub fn GlobalErrorBoundary(boundary_name: ReadSignal<String>, children: Element) -> Element {
    rsx! {
        ErrorBoundary {
            handle_error: move |_err: ErrorContext| {
                rsx! {
                    h1 {
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

#[component]
pub fn ComponentErrorDisplay(error_txt: ReadSignal<String>, children: Element) -> Element {
    rsx! {
        div {
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