//! The storage identity of this installation: database, table and bucket names, and the
//! store users.
//!
//! This module copies `main_services/processing/tasks/storage_identity.json`. The tests
//! below compare the copy with the file. Each setting reads its environment variable, and an absent
//! variable gives the Compose default. A Compose deployment that sets none of them keeps
//! `Hoover4_Processing`, `Hoover4_Collection_<name>`, the unprefixed Manticore tables and
//! the `hoover4-system` and `hoover4-c-<name>` buckets.

/// One setting: its environment variable and its Compose default.
pub struct Setting {
    pub variable: &'static str,
    pub default: &'static str,
}

pub const CLICKHOUSE_DATABASE_PREFIX: Setting = Setting { variable: "HOOVER4_CLICKHOUSE_DB_PREFIX", default: "Hoover4" };
pub const MANTICORE_TABLE_PREFIX: Setting = Setting { variable: "HOOVER4_MANTICORE_TABLE_PREFIX", default: "" };
pub const SYSTEM_BUCKET: Setting = Setting { variable: "S3_SYSTEM_BUCKET", default: "hoover4-system" };
pub const COLLECTION_BUCKET_PREFIX: Setting = Setting { variable: "S3_COLLECTION_BUCKET_PREFIX", default: "hoover4-c-" };
pub const CLICKHOUSE_USER: Setting = Setting { variable: "CLICKHOUSE_USER", default: "hoover4" };
pub const CLICKHOUSE_PASSWORD: Setting = Setting { variable: "CLICKHOUSE_PASSWORD", default: "hoover4" };
pub const MANTICORE_USER: Setting = Setting { variable: "MANTICORE_USER", default: "manticore" };
pub const MANTICORE_PASSWORD: Setting = Setting { variable: "MANTICORE_PASSWORD", default: "manticore" };
pub const S3_ACCESS_KEY: Setting = Setting { variable: "S3_ACCESS_KEY", default: "hoover4-blobs-rw" };
pub const S3_SECRET_KEY: Setting = Setting { variable: "S3_SECRET_KEY", default: "hoover4-garage-blob-secret-key-0" };

/// The value of a setting, from the process environment.
pub fn value(setting: &Setting) -> String {
    value_in(setting, |name| std::env::var(name).ok())
}

fn value_in(setting: &Setting, lookup: impl Fn(&str) -> Option<String>) -> String {
    lookup(setting.variable).unwrap_or_else(|| setting.default.to_string())
}

fn clickhouse_prefix_valid(prefix: &str) -> bool {
    prefix.starts_with(|c: char| c.is_ascii_alphabetic() || c == '_')
        && prefix.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
}

fn manticore_prefix_valid(prefix: &str) -> bool {
    prefix.is_empty()
        || (prefix.starts_with(|c: char| c.is_ascii_lowercase())
            && prefix.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_'))
}

/// Refuse a name prefix outside its allowed form. The website start calls it, so a wrong
/// value stops the start and never reaches a query. The error names the variable only.
pub fn check() -> anyhow::Result<()> {
    check_in(|name| std::env::var(name).ok())
}

fn check_in(lookup: impl Fn(&str) -> Option<String>) -> anyhow::Result<()> {
    if !clickhouse_prefix_valid(&value_in(&CLICKHOUSE_DATABASE_PREFIX, &lookup)) {
        anyhow::bail!("{} is invalid.", CLICKHOUSE_DATABASE_PREFIX.variable);
    }
    if !manticore_prefix_valid(&value_in(&MANTICORE_TABLE_PREFIX, &lookup)) {
        anyhow::bail!("{} is invalid.", MANTICORE_TABLE_PREFIX.variable);
    }
    Ok(())
}

/// Return the global ClickHouse database. Its default name is `Hoover4_Processing`.
pub fn global_database() -> String {
    format!("{}_Processing", value(&CLICKHOUSE_DATABASE_PREFIX))
}

/// The ClickHouse database of a collection, without validation of the name.
pub fn collection_database(collectionname: &str) -> String {
    format!("{}_Collection_{collectionname}", value(&CLICKHOUSE_DATABASE_PREFIX))
}

/// The physical Manticore table of a logical table name. The shard ledger keeps the
/// logical names.
pub fn manticore_table(logical: &str) -> String {
    format!("{}{logical}", value(&MANTICORE_TABLE_PREFIX))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn definition() -> serde_json::Value {
        let text = crate::db_utils::processing_tasks_file("storage_identity.json")
            .expect("storage_identity.json is not reachable from this test");
        serde_json::from_str(&text).unwrap()
    }

    const ALL: [(&str, &Setting); 10] = [
        ("clickhouse_database_prefix", &CLICKHOUSE_DATABASE_PREFIX),
        ("manticore_table_prefix", &MANTICORE_TABLE_PREFIX),
        ("system_bucket", &SYSTEM_BUCKET),
        ("collection_bucket_prefix", &COLLECTION_BUCKET_PREFIX),
        ("clickhouse_user", &CLICKHOUSE_USER),
        ("clickhouse_password", &CLICKHOUSE_PASSWORD),
        ("manticore_user", &MANTICORE_USER),
        ("manticore_password", &MANTICORE_PASSWORD),
        ("s3_access_key", &S3_ACCESS_KEY),
        ("s3_secret_key", &S3_SECRET_KEY),
    ];

    #[test]
    fn every_setting_matches_the_pipeline_definition() {
        let definition = definition();
        let settings = definition["settings"].as_object().unwrap();
        assert_eq!(settings.len(), ALL.len());
        for (name, setting) in ALL {
            let expected = &settings[name];
            assert_eq!(expected["variable"], setting.variable, "{name}");
            assert_eq!(expected["default"], setting.default, "{name}");
        }
    }

    #[test]
    fn names_match_the_pipeline_cases() {
        let definition = definition();
        for case in definition["cases"].as_array().unwrap() {
            let environment = case["environment"].as_object().unwrap().clone();
            let lookup = |name: &str| environment.get(name).map(|v| v.as_str().unwrap().to_string());
            let collection = case["collectionname"].as_str().unwrap();
            let prefix = value_in(&CLICKHOUSE_DATABASE_PREFIX, &lookup);
            assert_eq!(format!("{prefix}_Processing"), case["global_database"]);
            assert_eq!(format!("{prefix}_Collection_{collection}"), case["collection_database"]);
            assert_eq!(
                format!("{}{collection}_vfs", value_in(&MANTICORE_TABLE_PREFIX, &lookup)),
                case["manticore_table"]
            );
            assert_eq!(
                format!("{}{}", value_in(&COLLECTION_BUCKET_PREFIX, &lookup), collection.replace('_', "-")),
                case["collection_bucket"]
            );
            assert!(check_in(&lookup).is_ok());
        }
    }

    #[test]
    fn invalid_prefixes_are_refused_by_variable_name() {
        for case in definition()["invalid"].as_array().unwrap() {
            let environment = case.as_object().unwrap().clone();
            let lookup = |name: &str| environment.get(name).map(|v| v.as_str().unwrap().to_string());
            let error = check_in(&lookup).unwrap_err().to_string();
            let variable = environment.keys().next().unwrap();
            assert_eq!(error, format!("{variable} is invalid."));
        }
    }
}
