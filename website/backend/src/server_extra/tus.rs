//! The tus 1.0 subset under `/_upload/files/`: creation, creation with upload,
//! expiration and termination. A creation request with a body writes it from offset 0,
//! so a file that fits one chunk needs one request.
//!
//! The upload id is `<batch_id>-<file_no>`, so the address names its manifest row. Every
//! request except `OPTIONS` must carry `Tus-Resumable: 1.0.0` (412 otherwise) and
//! `X-Hoover-Upload: 1` (403 otherwise). The custom header forces a CORS preflight for
//! another origin, and the site does not answer one. The protocol headers are checked
//! before any body byte is read.
//!
//! A `PATCH` body streams to a blocking writer thread through a bounded channel, so no
//! chunk is held in memory as a whole. The writer holds the batch and file locks until
//! the body ends. A body that gives no byte for [`uploads::PATCH_IDLE_TIMEOUT`] ends as
//! interrupted, so a client that lost its network without closing the connection does
//! not hold the locks without a limit.

use axum::{
    body::Body,
    extract::{Extension, Path},
    http::{HeaderMap, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
};
use base64::Engine;
use common::current_user::CurrentUser;
use futures::StreamExt;

use super::uploads::run_blocking;
use crate::uploads::transfer::{parse_upload_id, BodyEnd, TransferInfo};
use crate::uploads::{self, http_date, upload_url, UploadError};

pub const TUS_VERSION: &str = "1.0.0";
pub const TUS_EXTENSIONS: &str = "creation,creation-with-upload,expiration,termination";
pub const OFFSET_CONTENT_TYPE: &str = "application/offset+octet-stream";

fn header<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    headers.get(name).and_then(|v| v.to_str().ok())
}

fn tus_response(status: StatusCode, headers: &[(&str, String)], body: String) -> Response {
    let mut response = (status, body).into_response();
    let map = response.headers_mut();
    map.insert("tus-resumable", HeaderValue::from_static(TUS_VERSION));
    for (name, value) in headers {
        if let (Ok(name), Ok(value)) = (
            axum::http::HeaderName::from_bytes(name.as_bytes()),
            HeaderValue::from_str(value),
        ) {
            map.insert(name, value);
        }
    }
    response
}

fn tus_error(err: UploadError) -> Response {
    let status = StatusCode::from_u16(err.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    if status.is_server_error() {
        tracing::error!("tus request failed: {}", err.message);
    }
    tus_response(status, &[("content-type", "text/plain; charset=utf-8".to_string())], err.message)
}

/// Check `Tus-Resumable` and `X-Hoover-Upload`.
fn check_protocol(headers: &HeaderMap) -> Result<(), Response> {
    if header(headers, "tus-resumable") != Some(TUS_VERSION) {
        return Err(tus_response(
            StatusCode::PRECONDITION_FAILED,
            &[("tus-version", TUS_VERSION.to_string())],
            "This server supports tus version 1.0.0 only.".to_string(),
        ));
    }
    if header(headers, "x-hoover-upload") != Some("1") {
        return Err(tus_error(UploadError::new(403, "The request needs the header X-Hoover-Upload: 1.")));
    }
    Ok(())
}

fn transfer_headers(info: &TransferInfo) -> Vec<(&'static str, String)> {
    vec![
        ("upload-offset", info.offset.to_string()),
        ("upload-length", info.length.to_string()),
        ("upload-expires", http_date(info.expires_ms)),
        ("cache-control", "no-store".to_string()),
    ]
}

/// Start placement of a file whose last byte arrived. The sweep repeats it after a
/// failure.
fn place_in_background(service: std::sync::Arc<uploads::Service>, batch_id: String, file_no: u32) {
    tokio::task::spawn_blocking(move || {
        if let Err(e) = service.place_after_transfer(&batch_id, file_no) {
            tracing::error!("upload batch {batch_id} file {file_no}: placement waits for the sweep: {e:#}");
        }
    });
}

/// Parse `Upload-Metadata`: comma-separated pairs of a key and a base64 value.
pub fn parse_metadata(value: &str) -> Option<Vec<(String, String)>> {
    let mut out = Vec::new();
    for pair in value.split(',') {
        let pair = pair.trim();
        if pair.is_empty() {
            return None;
        }
        let mut parts = pair.splitn(2, ' ');
        let key = parts.next()?.to_string();
        let raw = parts.next().unwrap_or("");
        let decoded = base64::engine::general_purpose::STANDARD.decode(raw.trim()).ok()?;
        out.push((key, String::from_utf8(decoded).ok()?));
    }
    Some(out)
}

/// `OPTIONS /_upload/files/`: the supported version, extensions and maximum size.
pub async fn options() -> Response {
    let max = uploads::service().map(|s| s.limits.max_file_bytes).unwrap_or(0);
    let mut response = StatusCode::NO_CONTENT.into_response();
    let map = response.headers_mut();
    map.insert("tus-version", HeaderValue::from_static(TUS_VERSION));
    map.insert("tus-extension", HeaderValue::from_static(TUS_EXTENSIONS));
    if let Ok(value) = HeaderValue::from_str(&max.to_string()) {
        map.insert("tus-max-size", value);
    }
    response
}

/// The `Content-Length` of a request, `None` for a chunked body.
fn content_length(headers: &HeaderMap) -> Result<Option<u64>, Response> {
    match header(headers, "content-length") {
        Some(v) => match v.parse::<u64>() {
            Ok(n) => Ok(Some(n)),
            Err(_) => Err(tus_error(UploadError::new(400, "Content-Length must be a whole number."))),
        },
        None => Ok(None),
    }
}

/// True when the request names the tus body type.
fn has_offset_body(headers: &HeaderMap) -> bool {
    header(headers, "content-type").and_then(|v| v.split(';').next()).map(str::trim) == Some(OFFSET_CONTENT_TYPE)
}

/// Write a request body at `offset` and start placement when the file is complete. The
/// body streams to a blocking writer thread through a bounded channel.
async fn write_body(
    service: std::sync::Arc<uploads::Service>,
    username: String,
    batch_id: String,
    file_no: u32,
    offset: u64,
    content_length: Option<u64>,
    body: Body,
) -> Result<TransferInfo, UploadError> {
    let worker = service.clone();
    let id = batch_id.clone();
    let session = run_blocking(move || worker.tus_patch_open(&username, &id, file_no, offset, content_length)).await?;
    let (sender, mut receiver) = tokio::sync::mpsc::channel::<Piece>(4);
    let writer = tokio::task::spawn_blocking(move || {
        let mut session = session;
        while let Some(piece) = receiver.blocking_recv() {
            match piece {
                Piece::Bytes(bytes) => match session.write(&bytes) {
                    Ok(true) => {}
                    Ok(false) => return session.finish(BodyEnd::Overflow),
                    Err(e) => {
                        tracing::warn!("upload batch write failed, the received prefix is kept: {e:#}");
                        return session.finish(BodyEnd::Interrupted);
                    }
                },
                Piece::End(end) => return session.finish(end),
            }
        }
        session.finish(BodyEnd::Interrupted)
    });
    let end = pump_body(body.into_data_stream(), &sender, uploads::PATCH_IDLE_TIMEOUT).await;
    let _ = sender.send(Piece::End(end)).await;
    drop(sender);
    let info = match writer.await {
        Ok(result) => result?,
        Err(e) => return Err(UploadError::new(500, format!("the upload writer failed: {e}"))),
    };
    if info.complete {
        place_in_background(service, batch_id, file_no);
    }
    Ok(info)
}

/// `POST /_upload/files/`: create the transfer of one manifest file. With the tus body
/// type and a body, the body is written from offset 0 when the transfer has no
/// acknowledged byte. The answer carries the offset either way.
pub async fn create(Extension(user): Extension<CurrentUser>, headers: HeaderMap, body: Body) -> Response {
    if let Err(refused) = check_protocol(&headers) {
        return refused;
    }
    if headers.contains_key("upload-defer-length") {
        return tus_error(UploadError::new(400, "Upload-Defer-Length is not supported."));
    }
    let Some(length) = header(&headers, "upload-length").and_then(|v| v.parse::<u64>().ok()) else {
        return tus_error(UploadError::new(400, "Upload-Length must be a whole number."));
    };
    let metadata = header(&headers, "upload-metadata").and_then(parse_metadata);
    let named = metadata.as_ref().and_then(|pairs| {
        let get = |k: &str| pairs.iter().find(|(key, _)| key == k).map(|(_, v)| v.clone());
        Some((get("batch")?, get("file")?.parse::<u32>().ok()?))
    });
    let Some((batch_id, file_no)) = named else {
        return tus_error(UploadError::new(400, "Upload-Metadata must name the batch and the file."));
    };
    let service = match uploads::service() {
        Ok(service) => service,
        Err(e) => return tus_error(e),
    };
    let body_length = match content_length(&headers) {
        Ok(n) => n,
        Err(refused) => return refused,
    };
    let with_body = has_offset_body(&headers) && body_length != Some(0);
    let worker = service.clone();
    let id = batch_id.clone();
    let username = user.username.clone();
    let mut info = match run_blocking(move || worker.tus_create(&username, &id, file_no, length)).await {
        Ok(info) => info,
        Err(e) => return tus_error(e),
    };
    if info.complete {
        place_in_background(service.clone(), batch_id.clone(), file_no);
    } else if with_body && info.offset == 0 {
        match write_body(service, user.username.clone(), batch_id.clone(), file_no, 0, body_length, body).await {
            Ok(written) => info = written,
            Err(e) => return tus_error(e),
        }
    }
    let mut extra = transfer_headers(&info);
    extra.push(("location", upload_url(&batch_id, file_no)));
    tus_response(StatusCode::CREATED, &extra, String::new())
}

/// `HEAD /_upload/files/<id>`: the acknowledged offset.
pub async fn head(Extension(user): Extension<CurrentUser>, Path(upload_id): Path<String>, headers: HeaderMap) -> Response {
    if let Err(refused) = check_protocol(&headers) {
        return refused;
    }
    let Some((batch_id, file_no)) = parse_upload_id(&upload_id) else {
        return tus_error(UploadError::not_found());
    };
    let service = match uploads::service() {
        Ok(service) => service,
        Err(e) => return tus_error(e),
    };
    match run_blocking(move || service.tus_head(&user.username, &batch_id, file_no)).await {
        Ok(info) => tus_response(StatusCode::OK, &transfer_headers(&info), String::new()),
        Err(e) => tus_error(e),
    }
}

/// One message from the body reader to the writer thread.
enum Piece {
    Bytes(bytes::Bytes),
    End(BodyEnd),
}

/// Pass the body to the writer until it ends, fails, or gives no frame for `idle`.
async fn pump_body<S, E>(mut stream: S, sender: &tokio::sync::mpsc::Sender<Piece>, idle: std::time::Duration) -> BodyEnd
where
    S: futures::Stream<Item = Result<bytes::Bytes, E>> + Unpin,
{
    loop {
        match tokio::time::timeout(idle, stream.next()).await {
            Ok(Some(Ok(bytes))) => {
                if sender.send(Piece::Bytes(bytes)).await.is_err() {
                    return BodyEnd::Complete;
                }
            }
            Ok(Some(Err(_))) => return BodyEnd::Interrupted,
            Ok(None) => return BodyEnd::Complete,
            Err(_) => {
                tracing::warn!("an upload PATCH sent no byte for {} s and ends, the received prefix is kept", idle.as_secs());
                return BodyEnd::Interrupted;
            }
        }
    }
}

/// `PATCH /_upload/files/<id>`: append bytes at the acknowledged offset.
pub async fn patch(
    Extension(user): Extension<CurrentUser>,
    Path(upload_id): Path<String>,
    headers: HeaderMap,
    body: Body,
) -> Response {
    if let Err(refused) = check_protocol(&headers) {
        return refused;
    }
    if !has_offset_body(&headers) {
        return tus_error(UploadError::new(415, "The request must have Content-Type: application/offset+octet-stream."));
    }
    let Some(offset) = header(&headers, "upload-offset").and_then(|v| v.parse::<u64>().ok()) else {
        return tus_error(UploadError::new(400, "Upload-Offset must be a whole number."));
    };
    let content_length = match content_length(&headers) {
        Ok(n) => n,
        Err(refused) => return refused,
    };
    let Some((batch_id, file_no)) = parse_upload_id(&upload_id) else {
        return tus_error(UploadError::not_found());
    };
    let service = match uploads::service() {
        Ok(service) => service,
        Err(e) => return tus_error(e),
    };
    match write_body(service, user.username, batch_id, file_no, offset, content_length, body).await {
        Ok(info) => {
            let extra = vec![("upload-offset", info.offset.to_string()), ("upload-expires", http_date(info.expires_ms))];
            tus_response(StatusCode::NO_CONTENT, &extra, String::new())
        }
        Err(e) => tus_error(e),
    }
}

/// `DELETE /_upload/files/<id>`: end an incomplete transfer.
pub async fn terminate(Extension(user): Extension<CurrentUser>, Path(upload_id): Path<String>, headers: HeaderMap) -> Response {
    if let Err(refused) = check_protocol(&headers) {
        return refused;
    }
    let Some((batch_id, file_no)) = parse_upload_id(&upload_id) else {
        return tus_error(UploadError::not_found());
    };
    let service = match uploads::service() {
        Ok(service) => service,
        Err(e) => return tus_error(e),
    };
    match run_blocking(move || service.tus_terminate(&user.username, &batch_id, file_no)).await {
        Ok(()) => tus_response(StatusCode::NO_CONTENT, &[], String::new()),
        Err(e) => tus_error(e),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn metadata_pairs_decode_and_malformed_values_are_refused() {
        let b64 = |s: &str| base64::engine::general_purpose::STANDARD.encode(s);
        let parsed = parse_metadata(&format!("batch {},file {}", b64("abc"), b64("7"))).unwrap();
        assert_eq!(parsed, vec![("batch".to_string(), "abc".to_string()), ("file".to_string(), "7".to_string())]);
        assert!(parse_metadata("batch !!!").is_none());
        assert!(parse_metadata("batch YWJj,,file Nw==").is_none());
        // A key without a value is legal in tus.
        assert_eq!(parse_metadata("flag").unwrap(), vec![("flag".to_string(), String::new())]);
    }

    #[tokio::test]
    async fn a_body_that_stops_sending_ends_as_interrupted_after_the_idle_limit() {
        let first: Result<bytes::Bytes, std::io::Error> = Ok(bytes::Bytes::from_static(b"abc"));
        // One frame, then a stream that never gives another frame and never ends.
        let stream = futures::stream::iter([first]).chain(futures::stream::pending());
        let (sender, mut receiver) = tokio::sync::mpsc::channel::<Piece>(4);
        let started = std::time::Instant::now();
        let end = tokio::time::timeout(
            std::time::Duration::from_secs(5),
            pump_body(stream, &sender, std::time::Duration::from_millis(200)),
        )
        .await
        .expect("the body pump ends by its idle limit");
        assert_eq!(end, BodyEnd::Interrupted);
        assert!(started.elapsed() >= std::time::Duration::from_millis(200));
        assert!(matches!(receiver.try_recv(), Ok(Piece::Bytes(b)) if &b[..] == b"abc"));
    }

    #[tokio::test]
    async fn a_body_that_ends_or_fails_gives_its_end() {
        let (sender, _receiver) = tokio::sync::mpsc::channel::<Piece>(4);
        let done = futures::stream::iter([Ok::<_, std::io::Error>(bytes::Bytes::from_static(b"x"))]);
        assert_eq!(pump_body(done, &sender, std::time::Duration::from_secs(5)).await, BodyEnd::Complete);
        let failed = futures::stream::iter([Err::<bytes::Bytes, _>(std::io::Error::other("cut"))]);
        assert_eq!(pump_body(failed, &sender, std::time::Duration::from_secs(5)).await, BodyEnd::Interrupted);
    }

    #[test]
    fn the_protocol_check_refuses_a_missing_version_and_a_missing_marker() {
        let mut headers = HeaderMap::new();
        assert_eq!(check_protocol(&headers).unwrap_err().status(), StatusCode::PRECONDITION_FAILED);
        headers.insert("tus-resumable", HeaderValue::from_static("0.2.2"));
        let refused = check_protocol(&headers).unwrap_err();
        assert_eq!(refused.status(), StatusCode::PRECONDITION_FAILED);
        assert_eq!(refused.headers().get("tus-version").unwrap(), TUS_VERSION);
        headers.insert("tus-resumable", HeaderValue::from_static(TUS_VERSION));
        assert_eq!(check_protocol(&headers).unwrap_err().status(), StatusCode::FORBIDDEN);
        headers.insert("x-hoover-upload", HeaderValue::from_static("1"));
        assert!(check_protocol(&headers).is_ok());
    }
}
