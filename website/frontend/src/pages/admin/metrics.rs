//! Admin page: `/admin/metrics`, usage counters and per-function API stats
//! over the rolling last 24 h.

use common::metrics_types::{ApiFunctionStats, UsageMetrics, UsageTimePoint};
use dioxus::prelude::*;

use crate::api::admin_api::admin_get_metrics;
use crate::components::admin_components::{
    AdminGuard, AdminShell, LiveChatsPanel, HELP_TEXT, MODULE, MODULE_BODY, MODULE_CAPTION,
    TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
// Shadows the prelude's element table so `svg_title` exists. See its module docs. The
// bar tooltip is the only place the exact bucket timestamp and count are readable.
use crate::components::svg_title::dioxus_elements;

#[component]
pub fn AdminMetricsPage() -> Element {
    rsx! {
        Title { "Admin: metrics" }
        AdminGuard {
            AdminShell {
                title: "Metrics".to_string(),
                breadcrumb: "Metrics".to_string(),
                active: "metrics".to_string(),
                SuspendWrapper { MetricsContent {} }
            }
        }
    }
}

fn humanize_bytes(bytes: u64) -> String {
    match bytes {
        b if b < 1024 => format!("{b} B"),
        b if b < 1024 * 1024 => format!("{:.1} KiB", b as f64 / 1024.0),
        b if b < 1024 * 1024 * 1024 => format!("{:.1} MiB", b as f64 / 1024.0 / 1024.0),
        b => format!("{:.2} GiB", b as f64 / 1024.0 / 1024.0 / 1024.0),
    }
}

#[component]
fn MetricsContent() -> Element {
    let metrics_res = use_resource(admin_get_metrics);
    let metrics = metrics_res.read().as_ref().and_then(|r| r.as_ref().ok()).cloned();

    rsx! {
        // Live first: it is the only thing on this page that is actionable right now.
        LiveChatsPanel {}
        p { style: "{HELP_TEXT} margin: 0 0 16px;",
            "Rolling last 24 hours. Events record who, which route class or function name, and when. Never a URL or a query string."
        }
        match metrics {
            None => rsx! { "Loading\u{2026}" },
            Some(m) => rsx! {
                UsagePanel { usage: m.usage }
                ApiPanel { api: m.api }
            },
        }
    }
}

#[component]
fn UsagePanel(usage: UsageMetrics) -> Element {
    let max_series = usage.series.iter().map(|p| p.count).max().unwrap_or(1).max(1);
    rsx! {
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Usage (last 24 h)" }
            div { style: MODULE_BODY,
                h3 { style: "font-size: 13px; color: #333; margin: 0 0 8px;", "Events by type" }
                table { style: "{TABLE} margin-bottom: 20px;",
                    thead {
                        tr {
                            th { style: TH, "Event" }
                            th { style: TH, "Count" }
                        }
                    }
                    tbody {
                        for e in usage.per_event_type {
                            tr { key: "{e.event_type}",
                                td { style: TD, "{e.event_type}" }
                                td { style: TD, "{e.count}" }
                            }
                        }
                    }
                }

                h3 { style: "font-size: 13px; color: #333; margin: 0 0 8px;", "Events per hour" }
                if usage.series.is_empty() {
                    p { style: HELP_TEXT, "No events recorded yet." }
                } else {
                    HourlyEventsChart { series: usage.series, max_count: max_series }
                }

                h3 { style: "font-size: 13px; color: #333; margin: 0 0 8px;", "Busiest users" }
                table { style: TABLE,
                    thead {
                        tr {
                            th { style: TH, "User" }
                            th { style: TH, "Events" }
                        }
                    }
                    tbody {
                        for u in usage.per_user {
                            tr { key: "{u.username}",
                                td { style: TD, "{u.username}" }
                                td { style: TD, "{u.count}" }
                            }
                        }
                    }
                }
            }
        }
    }
}

/// `HH:MM` from an RFC 3339 bucket, for an axis tick. The date is redundant on a
/// 24-hour axis and doubles the label width, so it stays in the per-bar tooltip.
fn hour_of_day(bucket: &str) -> String {
    bucket
        .split('T')
        .nth(1)
        .and_then(|time| time.get(..5))
        .unwrap_or(bucket)
        .to_string()
}

/// `MM-DD HH:MM`, for the ends of an axis whose two ends print the same clock time.
///
/// The window is `now() - INTERVAL 24 HOUR` grouped by hour, which spans **25** buckets
/// as soon as the partial first hour holds an event, so the first and last bars are the
/// same hour of two different days, and `HH:MM` alone labels them identically.
fn day_and_hour(bucket: &str) -> String {
    let Some((date, time)) = bucket.split_once('T') else {
        return bucket.to_string();
    };
    let day = date.get(5..).unwrap_or(date);
    let clock = time.get(..5).unwrap_or(time);
    format!("{day} {clock}")
}

/// The top of the count axis for a series whose largest bar is `max_count`.
///
/// Even, and never zero: the axis draws a tick at half height, and a half that rounds is
/// a rule drawn in one place and labelled with the value of another, at `max_count = 3`
/// the rule sits at 1.5 and says `2`. Rounding the top up instead moves the rule, which
/// is free, rather than the label, which is wrong. It also keeps the three tick values
/// distinct, so they can never collide into one repeated label.
fn count_axis_max(max_count: u64) -> u64 {
    let at_least_one = max_count.max(1);
    at_least_one + (at_least_one % 2)
}

/// One bar per hour over the rolling 24 h, with the axes that make it readable.
///
/// Bare bars answer "was there a spike" and nothing else. The count axis says how big,
/// the time axis says when, and the gridlines let a bar be read against them instead of
/// against its neighbours. Everything structural is recessive: grey rules behind grey
/// text, one accent for the data.
#[component]
fn HourlyEventsChart(series: Vec<UsageTimePoint>, max_count: u64) -> Element {
    // A fixed coordinate system scaled by the viewBox, so the geometry below is written
    // in one unit and the chart still fits whatever width the panel gives it.
    const W: f64 = 720.0;
    const H: f64 = 160.0;
    const LEFT: f64 = 46.0;
    const RIGHT: f64 = 8.0;
    const TOP: f64 = 10.0;
    const BOTTOM: f64 = 22.0;

    let plot_w = W - LEFT - RIGHT;
    let plot_h = H - TOP - BOTTOM;
    let baseline = TOP + plot_h;
    let count = series.len().max(1) as f64;
    let slot = plot_w / count;
    // A 2 px surface gap between bars, and never a bar so thin it vanishes.
    let bar_w = (slot - 2.0).max(1.0);

    // Three ticks: zero, half, full. More than three on a 150 px plot is noise. The top
    // is [`count_axis_max`] rather than the largest bar, so the middle rule sits exactly
    // on the value it is labelled with and the bars scale against the axis they are read
    // against.
    let axis_max = count_axis_max(max_count);
    let ticks: Vec<(f64, u64)> = (0..=2)
        .map(|i| {
            let fraction = i as f64 / 2.0;
            (baseline - fraction * plot_h, (axis_max as f64 * fraction) as u64)
        })
        .collect();

    // First, middle and last hour. The middle one is dropped when the series is short
    // enough that it would sit on top of one of the ends. Whenever the two ends fall in
    // the same hour of two different days (the 25-bucket window does this) every tick
    // carries its date, because labelling one end differently from the other is what
    // makes a reader think the axis is broken rather than long.
    let ends_share_a_clock_time = match (series.first(), series.last()) {
        (Some(first), Some(last)) => {
            series.len() > 1 && hour_of_day(&first.bucket) == hour_of_day(&last.bucket)
        }
        _ => false,
    };
    let time_ticks: Vec<(f64, String)> = {
        let mut out = Vec::new();
        let mut push = |index: usize| {
            if let Some(point) = series.get(index) {
                let label = if ends_share_a_clock_time {
                    day_and_hour(&point.bucket)
                } else {
                    hour_of_day(&point.bucket)
                };
                out.push((LEFT + (index as f64 + 0.5) * slot, label));
            }
        };
        push(0);
        if series.len() >= 5 {
            push(series.len() / 2);
        }
        if series.len() > 1 {
            push(series.len() - 1);
        }
        out
    };

    rsx! {
        svg {
            width: "100%",
            height: "{H}",
            "viewBox": "0 0 {W} {H}",
            style: "max-width: 720px; display: block; margin-bottom: 20px;",

            // Keyed by position on the axis, never by the label: two ticks can carry the
            // same text, and duplicate keys among siblings are a dioxus-core assertion on
            // a debug build and an undefined re-association on a release one.
            for (tick, (y, value)) in ticks.into_iter().enumerate() {
                g {
                    key: "y-{tick}",
                    line {
                        x1: "{LEFT}", y1: "{y}", x2: "{W - RIGHT}", y2: "{y}",
                        "stroke": "#e5e5e5", "stroke-width": "1",
                    }
                    text {
                        x: "{LEFT - 6.0}", y: "{y + 3.5}",
                        "text-anchor": "end",
                        style: "font-size: 10px; fill: #666;",
                        "{value}"
                    }
                }
            }

            for (index, point) in series.iter().enumerate() {
                {
                    // An hour with no events keeps a hairline, so a gap in the series
                    // reads as a gap rather than as the axis running out.
                    let height = (point.count as f64 / axis_max as f64 * plot_h).max(1.0);
                    let x = LEFT + index as f64 * slot + (slot - bar_w) / 2.0;
                    rsx! {
                        rect {
                            key: "{point.bucket}",
                            x: "{x}", y: "{baseline - height}",
                            width: "{bar_w}", height: "{height}",
                            rx: "2",
                            fill: "#79aec8",
                            svgtitle { "{point.bucket}: {point.count} events" }
                        }
                    }
                }
            }

            line {
                x1: "{LEFT}", y1: "{baseline}", x2: "{W - RIGHT}", y2: "{baseline}",
                "stroke": "#bbb", "stroke-width": "1",
            }
            for (tick, (x, label)) in time_ticks.into_iter().enumerate() {
                text {
                    key: "x-{tick}",
                    x: "{x}", y: "{H - 7.0}",
                    "text-anchor": "middle",
                    style: "font-size: 10px; fill: #666;",
                    "{label}"
                }
            }
            text {
                x: "{LEFT - 6.0}", y: "{H - 7.0}",
                "text-anchor": "end",
                style: "font-size: 10px; fill: #999;",
                "UTC"
            }
        }
    }
}

#[component]
fn ApiPanel(api: Vec<ApiFunctionStats>) -> Element {
    rsx! {
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "API calls (last 24 h)" }
            div { style: MODULE_BODY,
                if api.is_empty() {
                    p { style: HELP_TEXT, "No API calls recorded yet." }
                } else {
                    table { style: TABLE,
                        thead {
                            tr {
                                th { style: TH, "Function" }
                                th { style: TH, "Calls" }
                                th { style: TH, "Errors" }
                                th { style: TH, "Error rate" }
                                th { style: TH, "p50" }
                                th { style: TH, "p95" }
                                th { style: TH, "max" }
                                th { style: TH, "Bytes in" }
                                th { style: TH, "Bytes out" }
                            }
                        }
                        tbody {
                            for f in api {
                                tr { key: "{f.function_name}",
                                    td { style: "{TD} font-family: monospace; font-size: 12px;", "{f.function_name}" }
                                    td { style: TD, "{f.calls}" }
                                    td {
                                        style: if f.errors > 0 { format!("{TD} color: #ba2121; font-weight: 700;") } else { TD.to_string() },
                                        "{f.errors}"
                                    }
                                    td { style: TD, "{f.error_rate * 100.0:.1}%" }
                                    td { style: TD, "{f.p50_ms} ms" }
                                    td { style: TD, "{f.p95_ms} ms" }
                                    td { style: TD, "{f.max_ms} ms" }
                                    td { style: TD, "{humanize_bytes(f.bytes_in)}" }
                                    td { style: TD, "{humanize_bytes(f.bytes_out)}" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::humanize_bytes;

    #[test]
    fn humanize_picks_a_unit() {
        assert_eq!(humanize_bytes(512), "512 B");
        assert_eq!(humanize_bytes(2048), "2.0 KiB");
        assert_eq!(humanize_bytes(5 * 1024 * 1024), "5.0 MiB");
        assert_eq!(humanize_bytes(3 * 1024 * 1024 * 1024), "3.00 GiB");
    }
}
