pub async fn run_pdf_search_server() -> anyhow::Result<i32> {
    tracing::info!("Starting PDF search server");
    let mut child = tokio::process::Command::new("node")
        .arg("server-search.js")
        .current_dir("backend/pdf-viewer/_server")
        .stdout(std::process::Stdio::inherit())
        .stderr(std::process::Stdio::inherit())
        .kill_on_drop(true)
        .spawn()
        ?;
    let result = child.wait().await?;
    println!("PDF search server result: {:?}", result);
    let result = anyhow::Context::context(result.code(), "no result code")?;
    // std::process::exit(result.code().context("no result code")?);
    anyhow::Ok(result)
}
