use anyhow::Context;

const PID_FILE: &str = "/tmp/pdf-search-server.pid";

async fn write_pid_file(pid: u32) -> anyhow::Result<()> {
    use tokio::io::AsyncWriteExt;
    let mut file =  tokio::fs::File::create(PID_FILE).await?;
    file.write_all(pid.to_string().as_bytes()).await?;
    Ok(())
}

async fn read_pid_file() -> anyhow::Result<u32> {
    let content = std::fs::read_to_string(PID_FILE)?;
    let pid = content.trim().parse::<u32>()?;
    Ok(pid)
}

async fn kill_process(pid: u32) -> anyhow::Result<()> {
    // kill -s 0 <pid> -- return success if pid is running
    let _x = tokio::process::Command::new("kill")
        .arg("-s")
        .arg("0")
        .arg(pid.to_string())
        .spawn()?.wait().await?;
    if !_x.success() {
        tracing::info!("PID {} is not running", pid);
        return Ok(());
    }

    // kill -9 <pid>
    tracing::info!("Killing PID {} with signal 9", pid);
    let _x = tokio::process::Command::new("kill")
        .arg("-9")
        .arg(pid.to_string())
        .spawn()?.wait().await?;
    Ok(())
}

pub async fn run_pdf_search_server() -> anyhow::Result<i32> {
    let old_pid = read_pid_file().await;
    if let Ok(old_pid) = old_pid {
        tracing::info!("Killing old PDF search server with PID: {}", old_pid);
        kill_process(old_pid).await?;
    }
    tracing::info!("Starting PDF search server");
    let mut child = tokio::process::Command::new("node")
        .arg("server-search.js")
        .current_dir("backend/pdf-viewer/_server")
        .stdout(std::process::Stdio::inherit())
        .stderr(std::process::Stdio::inherit())
        .process_group(0)
        .spawn()?;
    let child_pid = child.id().context("Failed to get child PID")?;
    write_pid_file(child_pid).await?;

    let result = child.wait().await?;
    println!("PDF search server result: {:?}", result);
    let result = result.code().context("no result code")?;
    // std::process::exit(result.code().context("no result code")?);
    anyhow::Ok(result)
}
