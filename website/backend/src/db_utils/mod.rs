//! Database utility module exports.

pub mod clickhouse_utils;
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
/// Garage enforces minimum lengths — an access key id under 8 characters and a secret
/// under 16 are refused — so short placeholders that pass against other S3
/// implementations do not work here.
pub fn s3_credentials() -> (String, String) {
    (
        std::env::var("S3_ACCESS_KEY").unwrap_or_else(|_| "hoover4-blobs-rw".to_string()),
        std::env::var("S3_SECRET_KEY")
            .unwrap_or_else(|_| "hoover4-garage-blob-secret-key-0".to_string()),
    )
}

/// The blobs bucket. One bucket holds ingested blobs and everything derived; the
/// `derived/` prefix is what separates them.
pub fn s3_bucket() -> String {
    std::env::var("S3_BUCKET").unwrap_or_else(|_| "hoover4-blobs".to_string())
}

/// An S3 client for the blob store, configured from the environment.
///
/// Path-style addressing is mandatory: virtual-host addressing would put the bucket in
/// the hostname, and `garage` is a container name with no wildcard DNS under it.
///
/// The region is whatever the server declares (`s3_region` in `garage.toml`) — SigV4
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
