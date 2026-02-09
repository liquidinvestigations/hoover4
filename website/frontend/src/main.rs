//! Frontend application entry point.

use dioxus::prelude::server_only;
use frontend::app::App;

fn main() {
    dioxus::LaunchBuilder::new()
    .with_context(server_only! {
        // Enable out of order streaming during SSR
        // dioxus::server::ServeConfig::builder().enable_out_of_order_streaming()
    }).launch(App);
}
