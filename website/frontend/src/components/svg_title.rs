//! An SVG `<title>` element that rsx can actually build.
//!
//! `<title>` is the only tooltip an SVG shape has, and it only works when the node is in
//! the SVG namespace. `dioxus-html` declares `title` in the HTML namespace alone — its
//! SVG twin is commented out in that crate because the two would collide on the Rust
//! identifier — so `title { … }` written inside an `svg { … }` is created with
//! `createElement` and lands in the document as an `HTMLTitleElement`. Inside `<svg>` that
//! is a foreign element: it is not rendered, and it is not a tooltip. Nothing warns, on
//! any build; the markup looks right in the inspector and the hover does nothing.
//!
//! rsx resolves an element to `dioxus_elements::elements::<name>::TAG_NAME` and
//! `dioxus_elements::<name>::NAME_SPACE`, so a module named `dioxus_elements` that
//! re-exports the real one and adds a name of its own is all it takes to declare the
//! element that crate is missing. Import it and `svgtitle { "…" }` builds a real
//! `SVGTitleElement`:
//!
//! ```ignore
//! use crate::components::svg_title::dioxus_elements;
//!
//! rsx! { svg { rect { svgtitle { "42 events" } } } }
//! ```
//!
//! The import shadows the prelude's glob, which is why it has to be the whole
//! `dioxus_elements` module rather than one element out of it.

/// The element namespace rsx resolves against, with an SVG `<title>` added to it.
pub mod dioxus_elements {
    pub use dioxus::prelude::dioxus_elements::*;

    /// SVG `<title>`: the native tooltip of the shape it is a child of.
    ///
    /// The Rust name differs from the tag name on purpose — `title` is taken by the HTML
    /// element of the same name, and having both under one identifier is what stopped
    /// `dioxus-html` from shipping this one.
    #[allow(non_camel_case_types)]
    pub mod svgtitle {
        pub const TAG_NAME: &str = "title";
        pub const NAME_SPACE: Option<&str> = Some("http://www.w3.org/2000/svg");
    }

    /// The element table rsx reads tag names from. Shadows the re-exported one above,
    /// which is why it repeats its glob.
    pub mod elements {
        pub use dioxus::prelude::dioxus_elements::elements::*;

        pub use super::svgtitle;
    }
}
