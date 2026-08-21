//! The service shell: load the vendored data, compile the rules, serve.

use std::sync::Arc;

use anyhow::{Context, Result};
use regex_entity_scanner::data::VendoredData;
use regex_entity_scanner::scan::Scanner;
use regex_entity_scanner::service::{self, Admission, AppState};

/// Ten mebibytes. Large enough for any fragment a windowing caller should be sending, small enough
/// that a request cannot be used to make the process allocate without bound.
const DEFAULT_MAX_BODY_BYTES: usize = 10_485_760;

/// Async workers. The async half of this process parses JSON and moves bytes; the work is on the
/// blocking pool. Deriving this from the core count hands a busy box a thread per core to do
/// nothing with, and competes with the scanning that is the actual load.
const DEFAULT_WORKER_THREADS: usize = 4;

/// Concurrent scans, and the queue in front of them. Scanning measures at about 0.85 MB/s per core,
/// so ten is roughly 8.5 MB/s of throughput; the queue absorbs a burst without either refusing a
/// caller that would have been served in a second or accepting a backlog nobody is still waiting
/// on.
const DEFAULT_SCAN_THREADS: usize = 10;
const DEFAULT_QUEUE_DEPTH: usize = 32;

fn main() -> Result<()> {
    // `--health-check` probes the port this process would bind and exits non-zero if the answer is
    // not a healthy one. It lives in the binary because the release image carries no shell tooling
    // — no curl, no Python — and a health check that needs a package installed to run is a health
    // check that stops being run.
    if std::env::args().any(|arg| arg == "--health-check") {
        return health_check();
    }
    let worker_threads = usize_from_env("RES_WORKER_THREADS", DEFAULT_WORKER_THREADS)?;
    let scan_threads = usize_from_env("RES_SCAN_THREADS", DEFAULT_SCAN_THREADS)?;
    let queue_depth = usize_from_env("RES_QUEUE_DEPTH", DEFAULT_QUEUE_DEPTH)?;
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(worker_threads)
        .max_blocking_threads(scan_threads)
        .enable_all()
        .build()
        .context("building the runtime")?
        .block_on(serve(scan_threads, queue_depth))
}

async fn serve(scan_threads: usize, queue_depth: usize) -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_env("RES_LOG")
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    let data = VendoredData::load_from_env()?;
    let scanner = Arc::new(Scanner::new(data)?);
    tracing::info!(
        rules = scanner.rule_ids().len(),
        tlds = scanner.data().tld_count(),
        "rules compiled"
    );

    let max_body_bytes = max_body_bytes()?;
    let state = Arc::new(AppState {
        scanner,
        max_body_bytes,
        admission: Admission::new(scan_threads, queue_depth),
    });

    let bind = std::env::var("RES_BIND").unwrap_or_else(|_| "0.0.0.0:19705".to_string());
    let listener = tokio::net::TcpListener::bind(&bind)
        .await
        .with_context(|| format!("binding {bind}"))?;
    tracing::info!(%bind, "listening");

    axum::serve(listener, service::router(state))
        .with_graceful_shutdown(shutdown())
        .await
        .context("serving")?;
    Ok(())
}

/// The request and fragment size limit. An operational parameter that is silently wrong is worse
/// than one that refuses to boot, so an unparseable value fails startup instead of falling back.
fn max_body_bytes() -> Result<usize> {
    usize_from_env("RES_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)
}

/// Every numeric knob reads the same way, for the same reason: a value the operator meant and the
/// process could not parse must stop the process, not be quietly replaced by a default that then
/// looks like the operator's choice. Zero is refused too — a bound of zero is a service that
/// accepts nothing and reports itself healthy.
fn usize_from_env(name: &str, default: usize) -> Result<usize> {
    let Ok(raw) = std::env::var(name) else {
        return Ok(default);
    };
    let parsed: usize = raw
        .trim()
        .parse()
        .with_context(|| format!("{name} is {raw:?}, which is not a positive whole number"))?;
    if parsed == 0 {
        anyhow::bail!("{name} is 0, which would leave the service unable to do anything");
    }
    Ok(parsed)
}

/// A one-shot HTTP/1.0 GET against `/health` on the address this process serves.
///
/// Hand-rolled rather than pulled from a client crate: the release binary otherwise needs no HTTP
/// client at all, and a health probe that drags in TLS, connection pooling and redirects to read
/// one status line is a dependency taken for nothing.
fn health_check() -> Result<()> {
    use std::io::{Read, Write};

    let bind = std::env::var("RES_BIND").unwrap_or_else(|_| "0.0.0.0:19705".to_string());
    // The bind address may be a wildcard, which is not a routable destination. The port is the
    // part that matters; the probe always connects to the loopback interface.
    let port = bind
        .rsplit(':')
        .next()
        .and_then(|port| port.parse::<u16>().ok())
        .with_context(|| format!("RES_BIND is {bind:?}, which names no port"))?;

    let timeout = std::time::Duration::from_secs(5);
    let address = std::net::SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = std::net::TcpStream::connect_timeout(&address, timeout)
        .with_context(|| format!("connecting to {address}"))?;
    stream.set_read_timeout(Some(timeout))?;
    stream.set_write_timeout(Some(timeout))?;
    stream.write_all(b"GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n")?;
    let mut response = String::new();
    stream.read_to_string(&mut response)?;

    // A degraded scanner answers 503 with a body naming the tables that loaded short, so the
    // status line alone is the whole verdict.
    let status = response.lines().next().unwrap_or_default();
    if status.contains(" 200 ") {
        Ok(())
    } else {
        anyhow::bail!("/health answered {status:?}")
    }
}

/// Ctrl-C and SIGTERM both end the process cleanly, so `docker stop` does not have to escalate.
async fn shutdown() {
    let ctrl_c = async {
        tokio::signal::ctrl_c().await.ok();
    };
    let terminate = async {
        if let Ok(mut signal) =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        {
            signal.recv().await;
        }
    };
    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }
}
