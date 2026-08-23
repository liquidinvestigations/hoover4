//! Database utility module exports.

pub mod clickhouse_utils;
pub use clickhouse_utils::collectionname_of_dataset;
pub mod decompose_spans;
pub mod manticore_match;
pub mod manticore_utils;

/// The blob store's credentials, from the environment.
///
/// Never write them as a literal in a client constructor. A credential compiled into a
/// binary cannot be rotated without a rebuild, and once it is in the repository it is
/// there for good. The names and the dev defaults match what every other container in
/// the stack already reads (`compose/agents.yaml`, `agent_common/s3_store.py`), so
/// nothing needs configuring for a local run and a real deployment sets two variables.
///
/// Garage enforces minimum lengths (an access key id under 8 characters and a secret
/// under 16 are refused), so short placeholders that pass against other S3
/// implementations do not work here.
pub fn s3_credentials() -> (String, String) {
    (
        std::env::var("S3_ACCESS_KEY").unwrap_or_else(|_| "hoover4-blobs-rw".to_string()),
        std::env::var("S3_SECRET_KEY")
            .unwrap_or_else(|_| "hoover4-garage-blob-secret-key-0".to_string()),
    )
}

/// The bucket for everything that belongs to no collection, such as chat artifacts and
/// the like. A collection's own objects are in [`collection_bucket`].
pub fn system_bucket() -> String {
    std::env::var("S3_SYSTEM_BUCKET").unwrap_or_else(|_| "hoover4-system".to_string())
}

/// One collection's bucket: its ingested blobs and everything derived from them.
///
/// There is a bucket per collection rather than one shared bucket with prefixes, so a
/// collection's objects are enumerable without prefix filtering and deletable in one
/// call, and so a read scoped to a collection cannot reach another one's bytes. Garage
/// dedups blocks globally, so the split costs no storage.
pub fn collection_bucket(collectionname: &str) -> String {
    let prefix = std::env::var("S3_COLLECTION_BUCKET_PREFIX")
        .unwrap_or_else(|_| "hoover4-c-".to_string());
    format!("{prefix}{collectionname}")
}

/// Split a stored `s3://bucket/key` into its two halves.
///
/// The bucket is read out of the path rather than reconstructed from configuration: the
/// path is what the writer recorded, and a reader that rebuilds the bucket from its own
/// environment fetches from wherever it happens to be pointed instead of from where the
/// object actually is.
pub fn split_s3_path(s3_path: &str) -> Option<(String, String)> {
    let without_scheme = s3_path.strip_prefix("s3://")?;
    let (bucket, key) = without_scheme.split_once('/')?;
    if bucket.is_empty() || key.is_empty() {
        return None;
    }
    Some((bucket.to_string(), key.to_string()))
}

/// An S3 client for the blob store, configured from the environment.
///
/// Path-style addressing is mandatory: virtual-host addressing would put the bucket in
/// the hostname, and `garage` is a container name with no wildcard DNS under it.
///
/// The region is whatever the server declares (`s3_region` in `garage.toml`). SigV4
/// signs it into the credential scope, and a mismatch fails as
/// `AuthorizationHeaderMalformed`, which names authorization and not the region.
pub async fn s3_client() -> anyhow::Result<aws_sdk_s3::Client> {
    use anyhow::Context;

    let endpoint = std::env::var("S3_ENDPOINT").context("S3_ENDPOINT is not set")?;
    let (access, secret) = s3_credentials();
    let region = std::env::var("S3_REGION").unwrap_or_else(|_| "us-east-1".to_string());
    let config = aws_sdk_s3::Config::builder()
        .region(aws_sdk_s3::config::Region::new(region))
        .endpoint_url(endpoint)
        .credentials_provider(aws_sdk_s3::config::Credentials::new(
            access, secret, None, None, "hoover4-env",
        ))
        .force_path_style(true)
        .behavior_version(aws_sdk_s3::config::BehaviorVersion::latest())
        .build();
    Ok(aws_sdk_s3::Client::from_conf(config))
}
