//! Supervisor for the in-PDF search sidecar.
//!
//! The sidecar is a node process serving `backend/pdf-viewer/_server/server-search.js` on
//! loopback inside this container; `api::documents::search_document_pdf` is its only
//! caller. It is started from here rather than from compose because it is useless without
//! this server — it fetches the PDF back over the server's own HTTP port.

use anyhow::Context;

const PID_FILE: &str = "/tmp/pdf-search-server.pid";

/// Path of the sidecar's directory, relative to whatever root holds the source tree.
const SERVER_SUBDIR: &str = "backend/pdf-viewer/_server";

/// Locate the sidecar's directory without depending on the process's working directory.
///
/// The working directory is **not** the source root in every deployment: the release
/// container serves the built binary from `target/dx/<pkg>/release/web/`, so a relative
/// `backend/pdf-viewer/_server` resolves under the build output, the spawn fails with
/// `No such file or directory`, and in-PDF search is dead for the whole deployment while
/// everything else looks healthy. Walk up from the working directory instead, and let
/// `PDF_SEARCH_SERVER_DIR` override it outright.
fn find_server_dir() -> anyhow::Result<std::path::PathBuf> {
    if let Ok(dir) = std::env::var("PDF_SEARCH_SERVER_DIR") {
        let dir = std::path::PathBuf::from(dir);
        anyhow::ensure!(
            dir.join("server-search.js").is_file(),
            "PDF_SEARCH_SERVER_DIR={} holds no server-search.js",
            dir.display()
        );
        return Ok(dir);
    }
    find_server_dir_from(&std::env::current_dir()?)
}

/// The search half of [`find_server_dir`], separated so it can be exercised against a
/// working directory this process does not have to move into.
fn find_server_dir_from(start: &std::path::Path) -> anyhow::Result<std::path::PathBuf> {
    let mut tried = vec![];
    for root in start.ancestors() {
        let candidate = root.join(SERVER_SUBDIR);
        if candidate.join("server-search.js").is_file() {
            return Ok(candidate);
        }
        tried.push(candidate.display().to_string());
    }
    anyhow::bail!(
        "no {SERVER_SUBDIR}/server-search.js above {}; tried {tried:?}",
        start.display()
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A scratch tree that removes itself, so these tests need no dependency for it.
    struct Scratch(std::path::PathBuf);

    impl Scratch {
        fn new(name: &str) -> Self {
            let path = std::env::temp_dir().join(format!(
                "hoover4-pdf-search-{}-{name}",
                std::process::id()
            ));
            let _ = std::fs::remove_dir_all(&path);
            std::fs::create_dir_all(&path).unwrap();
            Scratch(path)
        }
    }

    impl Drop for Scratch {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    /// The layout the release container actually runs in: the built binary is served from
    /// `target/dx/<pkg>/release/web/`, which is where its working directory ends up, and
    /// the sidecar's source sits five levels above it. Resolving `SERVER_SUBDIR` against
    /// that directory finds nothing, which is how in-PDF search dies on a deployment
    /// while every other route stays healthy.
    #[test]
    fn the_sidecar_is_found_from_the_release_binarys_working_directory() {
        let root = Scratch::new("release-layout");
        let sidecar = root.0.join(SERVER_SUBDIR);
        std::fs::create_dir_all(&sidecar).unwrap();
        std::fs::write(sidecar.join("server-search.js"), "").unwrap();

        let serving_from = root.0.join("target/dx/frontend/release/web");
        std::fs::create_dir_all(&serving_from).unwrap();
        assert!(
            !serving_from.join(SERVER_SUBDIR).exists(),
            "the relative path this replaces must genuinely not resolve here"
        );

        assert_eq!(find_server_dir_from(&serving_from).unwrap(), sidecar);
        assert_eq!(find_server_dir_from(&root.0).unwrap(), sidecar);
    }

    /// The pid file outlives the process it names, and pids are recycled — so "the file
    /// says 537" is never evidence that 537 is the sidecar. Unchecked, the kill has taken
    /// out the website's own server binary seconds after start and left every route
    /// answering 500 across restarts, because the same low pid kept being handed out.
    #[test]
    fn a_recycled_pid_is_not_mistaken_for_the_sidecar() {
        // This test process is definitely alive and is definitely not the node sidecar,
        // which is exactly the situation that caused the self-kill.
        assert!(!pid_is_the_sidecar(std::process::id()));
        assert!(!pid_is_the_sidecar(1), "pid 1 here is the container's shell");
        // A pid that cannot exist has no cmdline to read, and that is not the sidecar
        // either — the old check treated "kill -s 0 succeeded" as proof enough.
        assert!(!pid_is_the_sidecar(u32::MAX));
    }

    #[test]
    fn a_tree_without_the_sidecar_names_what_it_looked_for() {
        let root = Scratch::new("no-sidecar");
        let error = find_server_dir_from(&root.0).unwrap_err().to_string();
        assert!(error.contains(SERVER_SUBDIR), "{error}");
    }
}

async fn write_pid_file(pid: u32) -> anyhow::Result<()> {
    use tokio::io::AsyncWriteExt;
    let mut file = tokio::fs::File::create(PID_FILE).await?;
    file.write_all(pid.to_string().as_bytes()).await?;
    Ok(())
}

async fn read_pid_file() -> anyhow::Result<u32> {
    let content = std::fs::read_to_string(PID_FILE)?;
    let pid = content.trim().parse::<u32>()?;
    Ok(pid)
}

/// Is this pid **our** sidecar, right now?
///
/// The pid file outlives the process that wrote it — it is on the container's filesystem
/// and a restart does not clear it — and pids are recycled from a small range at boot, so
/// the recorded number very often names a *different, live* process next time. Killing it
/// unchecked is not a stale-cleanup, it is a random `SIGKILL`: it has killed the website's
/// own server binary seconds after start, leaving `dx serve` believing the app was
/// running and every route answering 500 with nothing else in the log, across restarts,
/// because the same pid was handed out again.
///
/// `/proc/<pid>/cmdline` is the only thing that answers "is this the process I started".
fn pid_is_the_sidecar(pid: u32) -> bool {
    let Ok(cmdline) = std::fs::read(format!("/proc/{pid}/cmdline")) else {
        return false;
    };
    // NUL-separated argv; the script name is what identifies it.
    String::from_utf8_lossy(&cmdline).contains("server-search.js")
}

async fn kill_stale_sidecar(pid: u32) -> anyhow::Result<()> {
    if !pid_is_the_sidecar(pid) {
        tracing::debug!("recorded pid {pid} is not a running sidecar; leaving it alone");
        return Ok(());
    }
    tracing::info!("killing the previous PDF search server, pid {pid}");
    let _ = tokio::process::Command::new("kill")
        .arg("-9")
        .arg(pid.to_string())
        .spawn()?
        .wait()
        .await?;
    Ok(())
}

pub async fn run_pdf_search_server() -> anyhow::Result<i32> {
    if let Ok(old_pid) = read_pid_file().await {
        kill_stale_sidecar(old_pid).await?;
    }
    let server_dir = find_server_dir()?;
    tracing::info!("Starting PDF search server in {}", server_dir.display());
    let mut child = tokio::process::Command::new("node")
        .arg("server-search.js")
        .current_dir(&server_dir)
        .stdout(std::process::Stdio::inherit())
        .stderr(std::process::Stdio::inherit())
        .process_group(0)
        .spawn()?;
    let child_pid = child.id().context("Failed to get child PID")?;
    write_pid_file(child_pid).await?;

    let result = child.wait().await?;
    tracing::info!("PDF search server exited: {result:?}");
    let result = result.code().context("no result code")?;
    anyhow::Ok(result)
}
