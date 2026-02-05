pub fn get_clickhouse_client() -> clickhouse::Client {
    clickhouse::Client::default()
        .with_url(std::env::var("CLICKHOUSE_URL").unwrap_or("http://localhost:8123".to_string()))
        .with_user("hoover4")
        .with_password("hoover4")
        .with_database("Hoover4_Processing")
}
