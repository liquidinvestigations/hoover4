//! Shared setup for the integration tests.

use std::path::PathBuf;
use std::sync::{Arc, OnceLock};

use regex_entity_scanner::data::VendoredData;
use regex_entity_scanner::scan::Scanner;

/// The vendored tree next to the manifest, so tests do not depend on the environment the way the
/// binary does.
pub fn vendored_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("vendored")
}

/// One scanner per test binary. Compiling the whole pattern set and loading the vendored data once
/// per test is where the battery's time budget would otherwise go, and the scanner is immutable and
/// shared by every request in production anyway, so sharing it here is also the more faithful
/// fixture.
pub fn scanner() -> Arc<Scanner> {
    static SCANNER: OnceLock<Arc<Scanner>> = OnceLock::new();
    SCANNER
        .get_or_init(|| {
            let data = VendoredData::load(&vendored_dir()).expect(
                "the vendored data is missing; run `vendored/fetch-all.sh` inside the dev container",
            );
            Arc::new(Scanner::new(data).expect("compiling the rule set"))
        })
        .clone()
}
