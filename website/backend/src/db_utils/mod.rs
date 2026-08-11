//! Database utility module exports.

pub mod clickhouse_utils;
pub mod decompose_spans;
pub mod manticore_match;
pub mod manticore_utils;

/// The blob store's credentials, from the environment.
///
/// Never write them as a `StaticProvider::new("hoover4", "hoover4-secret", None)` literal.
/// A credential compiled into a binary cannot be rotated without a rebuild, and once it is
/// in the repository it is there for good. The names and the dev defaults match what every other container in the
/// stack already reads (`compose/agents.yaml`, `agent_common/minio_store.py`), so nothing
/// needs configuring for a local run and a real deployment sets two variables.
pub fn s3_credentials() -> (String, String) {
    (
        std::env::var("MINIO_ACCESS_KEY").unwrap_or_else(|_| "hoover4".to_string()),
        std::env::var("MINIO_SECRET_KEY").unwrap_or_else(|_| "hoover4-secret".to_string()),
    )
}
