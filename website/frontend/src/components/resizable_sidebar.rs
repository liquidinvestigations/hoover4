//! A left pane the user can drag wider, whose width outlives the session.
//!
//! **The unit is CSS pixels**, stored as a plain integer. The alternatives were considered
//! and are worse here: a percentage or `vw` re-scales the pane every time the window
//! changes size, so a width chosen to fit a folder name stops fitting it on a laptop and
//! swallows the page on a monitor; `rem` tracks the root font size, which nothing in this
//! tree reads — its rows are sized in pixels. A pixel is what the drag produces, what the
//! layout consumes, and what the content actually needs.
//!
//! Those pixels are the app's LAYOUT pixels, before the scale `#x-nav-container` applies
//! (`assets/main.css` lays the app out at a 1920 px design width and `zoom`s it down to
//! the window). A pointer event's `clientX` is in the unscaled viewport instead, so the
//! drag divides by the measured scale — without that the pane grows more slowly than the
//! cursor moves and the handle visibly lags behind it.
//!
//! **A remembered width can never make the pane unusable, and never off-screen.** Three
//! independent guards, because a stored value is user data that outlives every assumption
//! made when it was written:
//!
//! * anything that is not a positive integer is not a width, and falls back to the default
//!   rather than to zero;
//! * every value is clamped to [`MIN_SIDEBAR_PX`]..=[`MAX_SIDEBAR_PX`] on the way in AND on
//!   the way out, so a hand-edited or stale entry cannot widen the pane past the clamp.
//!   That clamp is also what keeps the pane on screen at every window size: the app scales
//!   a ~1920 px design width to fit, so [`MAX_SIDEBAR_PX`] is a fixed 37 % of the window
//!   whatever the window is, and no resize can change that;
//! * `max-width: 50%` in the style is the backstop for the day the layout stops
//!   normalising to a design width, and costs nothing until then. It is a percentage of
//!   the page rather than of the viewport on purpose: `vw` is measured before the app's
//!   scale, so it would cap at the wrong place.

use dioxus::prelude::*;

/// Where the width is remembered. The unit is part of the key: a value written under a
/// different unit must not be readable as this one.
const WIDTH_KEY: &str = "hoover4.sidebar-width-css-px";

/// The element carrying the app's layout scale. See the module docs.
const SCALED_ROOT_ID: &str = "x-nav-container";

/// Default pane width: 40 % wider than the 240 px the tree's row budget is drawn against,
/// because a deep row spends most of a 240 px pane on indent, chevron, icon and depth
/// badge and leaves the name with nothing.
pub const DEFAULT_SIDEBAR_PX: u32 = 336;

/// The narrowest the pane may be dragged. 240 px is the width every row in the tree is
/// sized against, so the floor is "no worse than the layout was designed for" rather than
/// an arbitrary small number.
pub const MIN_SIDEBAR_PX: u32 = 240;

/// The widest. Past this the pane is no longer a sidebar, and `max-width: 50%` is the
/// guard that matters on a small window anyway.
pub const MAX_SIDEBAR_PX: u32 = 720;

/// A width made safe to use, whatever it came from.
pub fn clamp_sidebar_px(px: u32) -> u32 {
    px.clamp(MIN_SIDEBAR_PX, MAX_SIDEBAR_PX)
}

/// A remembered width, or `None` when what was stored is not one.
///
/// `"336px"`, `"NaN"`, `"-40"`, `""` and `"1e3"` are all things a bug or a hand edit can
/// leave in local storage, and none of them is a number of pixels. They fall back to the
/// default; only a plain positive integer is honoured, and even that is clamped.
pub fn parse_sidebar_px(raw: &str) -> Option<u32> {
    raw.trim()
        .parse::<u32>()
        .ok()
        .filter(|px| *px > 0)
        .map(clamp_sidebar_px)
}

/// The pane width in layout pixels for a drag that started at `start_px`.
///
/// `delta_client_px` is the cursor's movement in viewport pixels and `scale` is the app's
/// layout scale, so the division is what makes the edge follow the cursor exactly.
pub fn dragged_sidebar_px(start_px: u32, delta_client_px: f64, scale: f64) -> u32 {
    let scale = if scale.is_finite() && scale > 0.05 { scale } else { 1.0 };
    let next = f64::from(start_px) + delta_client_px / scale;
    if !next.is_finite() {
        return clamp_sidebar_px(start_px);
    }
    clamp_sidebar_px(next.round().max(0.0).min(f64::from(u32::MAX)) as u32)
}

/// The app's layout scale, measured rather than assumed.
///
/// `assets/main.css` picks a `zoom` per window-width breakpoint, so the factor is not a
/// constant and duplicating that ladder here would be a second copy to keep in step.
/// `clientWidth` is in the element's own (unscaled) pixels and the client rect is in
/// viewport pixels, so their ratio is the scale in force. Anything unmeasurable — no
/// window, no such element, a zero width — is 1.0, which degrades the drag to layout
/// pixels rather than breaking it.
fn layout_scale() -> f64 {
    let Some(element) = web_sys::window()
        .and_then(|window| window.document())
        .and_then(|document| document.get_element_by_id(SCALED_ROOT_ID))
    else {
        return 1.0;
    };
    let unscaled = element.client_width();
    if unscaled <= 0 {
        return 1.0;
    }
    let scale = element.get_bounding_client_rect().width() / f64::from(unscaled);
    if scale.is_finite() && scale > 0.05 { scale } else { 1.0 }
}

fn read_stored_px() -> Option<u32> {
    let storage = web_sys::window()?.local_storage().ok()??;
    parse_sidebar_px(&storage.get_item(WIDTH_KEY).ok()??)
}

fn write_stored_px(px: u32) {
    if let Some(storage) = web_sys::window().and_then(|w| w.local_storage().ok().flatten()) {
        let _ = storage.set_item(WIDTH_KEY, &px.to_string());
    }
}

/// A drag in progress: where the cursor started, how wide the pane was, and the scale that
/// was in force. All three are captured at `mousedown` — re-measuring the scale per move
/// would let a mid-drag breakpoint change turn the cursor's motion into a jump.
#[derive(Clone, Copy)]
struct Drag {
    client_x: f64,
    start_px: u32,
    scale: f64,
}

/// The pane, its remembered width, and the handle that changes it.
///
/// The moving half of the drag lives on a full-screen overlay that only exists while the
/// button is down. That is not decoration: a `mousemove` handler on the 6 px handle stops
/// firing the moment the cursor outruns it, which is most of a fast drag, and the overlay
/// also stops the pointer selecting text or hovering rows underneath while the edge moves.
#[component]
pub fn ResizableSidebar(children: Element) -> Element {
    let mut width = use_signal(|| DEFAULT_SIDEBAR_PX);
    let mut drag = use_signal(|| None::<Drag>);

    // Reads nothing reactive, so it runs once, on the client. The server render has no
    // local storage and shows the default.
    use_effect(move || {
        if let Some(px) = read_stored_px() {
            width.set(px);
        }
    });

    let current = width();
    let dragging = drag.read().is_some();
    // A dragged pane must not animate towards the cursor; a clicked one may.
    let transition = if dragging { "none" } else { "width 120ms ease-out" };
    let handle_background = if dragging { "#9CA3AF" } else { "#E5E7EB" };

    let end_drag = Callback::new(move |_: ()| {
        let was_dragging = drag.write().take().is_some();
        if was_dragging {
            write_stored_px(*width.peek());
        }
    });

    rsx! {
        div {
            style: "
                width: {current}px;
                max-width: 50%;
                flex: 0 0 auto;
                display: flex;
                flex-direction: row;
                min-width: 0;
                overflow: hidden;
                transition: {transition};
            ",
            div {
                style: "flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; overflow: hidden;",
                {children}
            }
            div {
                // Named so a script can drive exactly this, and so the pane's width is
                // reachable without guessing at a layout.
                id: "x-sidebar-resize",
                style: "
                    flex: 0 0 6px;
                    cursor: col-resize;
                    background: {handle_background};
                    border-left: 1px solid #E5E7EB;
                    border-right: 1px solid #E5E7EB;
                    box-sizing: border-box;
                ",
                title: "Drag to resize the sidebar, double-click to reset it",
                onmousedown: move |event: Event<MouseData>| {
                    event.prevent_default();
                    drag.set(Some(Drag {
                        client_x: event.client_coordinates().x,
                        start_px: *width.peek(),
                        scale: layout_scale(),
                    }));
                },
                ondoubleclick: move |_| {
                    drag.set(None);
                    width.set(DEFAULT_SIDEBAR_PX);
                    write_stored_px(DEFAULT_SIDEBAR_PX);
                },
            }
        }
        if dragging {
            div {
                style: "position: fixed; inset: 0; z-index: 3000; cursor: col-resize; user-select: none;",
                onmousemove: move |event: Event<MouseData>| {
                    let Some(origin) = *drag.peek() else { return };
                    let delta = event.client_coordinates().x - origin.client_x;
                    width.set(dragged_sidebar_px(origin.start_px, delta, origin.scale));
                },
                onmouseup: move |_| end_drag.call(()),
                // The cursor leaving the overlay means it left the window: without this
                // the drag survives a release the page never saw and the pane keeps
                // following the mouse on the way back in.
                onmouseleave: move |_| end_drag.call(()),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_default_is_forty_percent_wider_than_the_floor() {
        // The floor is the width the tree's rows are drawn against; the default is the
        // decided step up from it.
        assert_eq!(DEFAULT_SIDEBAR_PX, MIN_SIDEBAR_PX * 14 / 10);
        assert_eq!(clamp_sidebar_px(DEFAULT_SIDEBAR_PX), DEFAULT_SIDEBAR_PX);
    }

    #[test]
    fn a_remembered_width_can_never_leave_the_pane_unusable() {
        assert_eq!(clamp_sidebar_px(0), MIN_SIDEBAR_PX);
        assert_eq!(clamp_sidebar_px(1), MIN_SIDEBAR_PX);
        assert_eq!(clamp_sidebar_px(u32::MAX), MAX_SIDEBAR_PX);
        assert_eq!(clamp_sidebar_px(400), 400);
    }

    #[test]
    fn only_a_plain_integer_is_a_remembered_width() {
        assert_eq!(parse_sidebar_px("400"), Some(400));
        assert_eq!(parse_sidebar_px("  400 "), Some(400));
        // Clamped on the way in as well as on the way out: a stale entry from a build
        // with different limits may not widen the pane past this one's.
        assert_eq!(parse_sidebar_px("5000"), Some(MAX_SIDEBAR_PX));
        assert_eq!(parse_sidebar_px("10"), Some(MIN_SIDEBAR_PX));
        for junk in ["", "   ", "336px", "NaN", "-40", "1e3", "336.5", "null"] {
            assert_eq!(parse_sidebar_px(junk), None, "{junk:?} is not a width");
        }
    }

    #[test]
    fn the_drag_follows_the_cursor_through_the_layout_scale() {
        // At the app's 1200 px breakpoint the layout is scaled to 0.62, so 62 viewport
        // pixels of cursor travel is 100 layout pixels of pane.
        assert_eq!(dragged_sidebar_px(300, 62.0, 0.62), 400);
        assert_eq!(dragged_sidebar_px(400, -62.0, 0.62), 300);
        // Unscaled and unmeasurable both mean "one for one" rather than "no drag".
        assert_eq!(dragged_sidebar_px(300, 100.0, 1.0), 400);
        assert_eq!(dragged_sidebar_px(300, 100.0, 0.0), 400);
        assert_eq!(dragged_sidebar_px(300, 100.0, f64::NAN), 400);
    }

    #[test]
    fn dragging_past_either_limit_stops_at_it() {
        assert_eq!(dragged_sidebar_px(MIN_SIDEBAR_PX, -10_000.0, 1.0), MIN_SIDEBAR_PX);
        assert_eq!(dragged_sidebar_px(MAX_SIDEBAR_PX, 10_000.0, 1.0), MAX_SIDEBAR_PX);
        // A delta that is not a finite number is not a gesture: the pane stays where it
        // was rather than snapping to a limit.
        for delta in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
            assert_eq!(dragged_sidebar_px(400, delta, 1.0), 400);
        }
    }
}
