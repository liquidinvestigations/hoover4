//! Resolve PDF manifests after dataset access verification.

use axum::{body::Body, extract::{Extension, Path}, response::{IntoResponse, Response}};
use common::{current_user::CurrentUser, document_sources::{DocumentPdfPart, DocumentPdfSourceItem}, search_result::DocumentIdentifier};
use futures::TryStreamExt;
use crate::{auth::{guard, permissions}, db_utils::clickhouse_utils::get_client_for_dataset};

#[derive(Clone, Debug)]
pub struct ResolvedPdfPart {
    pub range: DocumentPdfPart,
    pub s3_path: String,
}

pub async fn source_parts(user: &CurrentUser, id: &DocumentIdentifier, source: &DocumentPdfSourceItem) -> anyhow::Result<Vec<ResolvedPdfPart>> {
    permissions::assert_can_read(user, &id.collection_dataset).await?;
    anyhow::ensure!(["original", "preview", "image"].contains(&source.kind()), "invalid PDF source kind");
    let client = get_client_for_dataset(&id.collection_dataset).await?;
    let source_rows = client.query("SELECT part_index, first_page, last_page, size_bytes, s3_path FROM pdf_parts FINAL WHERE collection_dataset = ? AND hash = ? AND source_kind = ? AND segmentation = 1 ORDER BY part_index")
        .bind(&id.collection_dataset).bind(&id.file_hash).bind(source.kind()).fetch_all::<(u16,u32,u32,u64,String)>().await?;
    let native: Vec<_> = source_rows.into_iter().map(|(part_index,first_page,last_page,size_bytes,s3_path)| ResolvedPdfPart { range: DocumentPdfPart { part_index,first_page,last_page,size_bytes }, s3_path }).collect();
    let original_pages = client.query("SELECT page_count FROM pdfs WHERE collection_dataset = ? AND pdf_hash = ? LIMIT 1")
        .bind(&id.collection_dataset).bind(&id.file_hash).fetch_all::<u32>().await?.into_iter().next();
    let preview = if source.kind() == "preview" {
        client.query("SELECT s3_path,page_count,size_bytes FROM pdf_previews FINAL WHERE collection_dataset = ? AND hash = ? LIMIT 1")
            .bind(&id.collection_dataset).bind(&id.file_hash).fetch_all::<(String,u32,u64)>().await?.into_iter().next()
    } else { None };
    if !source.is_ocr() {
        let pages = if source.kind() == "original" {original_pages} else {preview.as_ref().map(|p|p.1)}
            .ok_or_else(||anyhow::anyhow!("PDF source not found"))?;
        if !native.is_empty() && verify_ranges(&native,pages).is_ok() { return Ok(native); }
        let (path,size) = preview.map(|p|(p.0,p.2)).unwrap_or_default();
        return Ok(vec![ResolvedPdfPart {range:DocumentPdfPart {part_index:0,first_page:1,last_page:pages,size_bytes:size},s3_path:path}]);
    }
    let result = client.query("SELECT blob_key,size_bytes,page_count,source_kind,text_complete,form FROM pdf_ocr_results FINAL WHERE collection_dataset = ? AND pdf_hash = ? AND engine = ? AND languages = ? AND is_deleted = 0 LIMIT 1")
        .bind(&id.collection_dataset).bind(&id.file_hash).bind(&source.engine).bind(&source.languages).fetch_all::<(String,u64,u32,String,u8,String)>().await?;
    let (key,size,pages,kind,complete,_form) = result.into_iter().next().ok_or_else(||anyhow::anyhow!("PDF source not found"))?;
    anyhow::ensure!(kind == source.kind(), "PDF source not found");
    let rows = if complete == 1 { client.query("SELECT part_index,first_page,last_page,size_bytes,blob_key,borrows_source FROM pdf_ocr_parts FINAL WHERE collection_dataset = ? AND hash = ? AND source_kind = ? AND engine = ? AND languages = ? AND segmentation = 1 AND is_deleted = 0 ORDER BY part_index")
        .bind(&id.collection_dataset).bind(&id.file_hash).bind(source.kind()).bind(&source.engine).bind(&source.languages).fetch_all::<(u16,u32,u32,u64,String,u8)>().await? } else { vec![] };
    let bucket = crate::db_utils::collection_bucket(&crate::db_utils::collectionname_of_dataset(&id.collection_dataset).await?);
    let mut parts = Vec::new();
    for (part_index,first_page,last_page,size_bytes,key,borrowed) in rows {
        let path = if borrowed == 1 {
            let part = native.iter().find(|p| p.range.part_index == part_index && p.range.first_page == first_page && p.range.last_page == last_page)
                .ok_or_else(||anyhow::anyhow!("borrowed PDF source part not found"))?;
            part.s3_path.clone()
        } else { derived_path(&bucket,&key)? };
        parts.push(ResolvedPdfPart { range: DocumentPdfPart { part_index,first_page,last_page,size_bytes },s3_path:path });
    }
    if parts.is_empty() {
        anyhow::ensure!(!key.is_empty(), "PDF source manifest not found");
        parts.push(ResolvedPdfPart { range: DocumentPdfPart { part_index:0,first_page:1,last_page:pages,size_bytes:size },s3_path:derived_path(&bucket,&key)? });
    }
    verify_ranges(&parts,pages)?;
    Ok(parts)
}

fn derived_path(bucket: &str,key: &str) -> anyhow::Result<String> {
    anyhow::ensure!(key.starts_with("derived/"), "invalid derived PDF key");
    Ok(format!("s3://{bucket}/{key}"))
}
fn verify_ranges(parts: &[ResolvedPdfPart], pages: u32) -> anyhow::Result<()> {
    let mut first = 1;
    for part in parts {
        anyhow::ensure!(part.range.first_page == first && part.range.last_page >= first, "invalid PDF part ranges");
        first = part.range.last_page + 1;
    }
    anyhow::ensure!(pages == 0 || first == pages + 1, "incomplete PDF part ranges");
    Ok(())
}

pub async fn part_reader(id: &DocumentIdentifier, part: &ResolvedPdfPart) -> anyhow::Result<Box<dyn tokio::io::AsyncRead + Send + Unpin>> {
    if part.s3_path.is_empty() {
        let blob = crate::api::documents::download_document::get_blob_info(id).await?;
        if blob.stored_in_clickhouse {
            let value = crate::api::documents::download_document::get_blob_value_from_clickhouse(id).await?;
            return Ok(Box::new(std::io::Cursor::new(value.blob_value)));
        }
        return object_reader(&blob.s3_path).await;
    }
    object_reader(&part.s3_path).await
}
async fn object_reader(path: &str) -> anyhow::Result<Box<dyn tokio::io::AsyncRead + Send + Unpin>> {
    let (bucket,key) = crate::db_utils::split_s3_path(path).ok_or_else(||anyhow::anyhow!("invalid PDF object path"))?;
    let object = crate::db_utils::s3_client().await?.get_object().bucket(bucket).key(key).send().await?;
    Ok(Box::new(object.body.into_async_read()))
}

pub async fn read_part_bytes(id: &DocumentIdentifier, part: &ResolvedPdfPart) -> anyhow::Result<Vec<u8>> {
    use tokio::io::AsyncReadExt;
    let mut bytes = Vec::new();
    part_reader(id,part).await?.read_to_end(&mut bytes).await?;
    Ok(bytes)
}

pub fn error_response(error: anyhow::Error) -> Response {
    let code = if guard::is_forbidden(&error) { axum::http::StatusCode::FORBIDDEN }
        else if guard::is_not_found(&error) { axum::http::StatusCode::NOT_FOUND }
        else { axum::http::StatusCode::INTERNAL_SERVER_ERROR };
    (code,error.to_string()).into_response()
}

pub async fn download_part(Extension(user): Extension<CurrentUser>, Path((dataset,hash,kind,engine,languages,index)): Path<(String,String,String,String,String,u16)>) -> Response {
    let id = DocumentIdentifier {collection_dataset:dataset,file_hash:hash};
    let source = DocumentPdfSourceItem {source_kind:kind,engine:if engine=="-" {String::new()} else {engine},languages:if languages=="-" {String::new()} else {languages},..Default::default()};
    let result: anyhow::Result<Response> = async {
        let parts = source_parts(&user,&id,&source).await?;
        let part = parts.iter().find(|p|p.range.part_index==index).ok_or_else(||anyhow::anyhow!("PDF part not found"))?;
        let stream = tokio_util::io::ReaderStream::new(part_reader(&id,part).await?).map_err(anyhow::Error::from);
        Ok(([("Content-Type","application/pdf")],Body::from_stream(stream)).into_response())
    }.await;
    result.unwrap_or_else(error_response)
}

static ASSEMBLY_LIMIT: std::sync::LazyLock<std::sync::Arc<tokio::sync::Semaphore>> = std::sync::LazyLock::new(||std::sync::Arc::new(tokio::sync::Semaphore::new(2)));
struct TemporaryPdf { path: std::path::PathBuf }
impl Drop for TemporaryPdf { fn drop(&mut self) { let _ = std::fs::remove_dir_all(&self.path); } }

pub async fn complete_response(user: &CurrentUser,id: &DocumentIdentifier,source: &DocumentPdfSourceItem) -> anyhow::Result<Response> {
    permissions::assert_can_read(user,&id.collection_dataset).await?;
    if source.is_ocr() {
        let client = get_client_for_dataset(&id.collection_dataset).await?;
        let direct = client.query("SELECT blob_key FROM pdf_ocr_results FINAL WHERE collection_dataset = ? AND pdf_hash = ? AND source_kind = ? AND engine = ? AND languages = ? AND is_deleted = 0 LIMIT 1")
            .bind(&id.collection_dataset).bind(&id.file_hash).bind(source.kind()).bind(&source.engine).bind(&source.languages).fetch_all::<String>().await?;
        if let Some(key) = direct.into_iter().find(|key|!key.is_empty()) {
            let bucket = crate::db_utils::collection_bucket(&crate::db_utils::collectionname_of_dataset(&id.collection_dataset).await?);
            let reader = object_reader(&derived_path(&bucket,&key)?).await?;
            let stream = tokio_util::io::ReaderStream::new(reader).map_err(anyhow::Error::from);
            return Ok(([("Content-Type","application/pdf")],Body::from_stream(stream)).into_response());
        }
    }
    let parts = source_parts(user,id,source).await?;
    if parts.len() == 1 {
        let stream = tokio_util::io::ReaderStream::new(part_reader(id,&parts[0]).await?).map_err(anyhow::Error::from);
        return Ok(([("Content-Type","application/pdf")],Body::from_stream(stream)).into_response());
    }
    let permit = ASSEMBLY_LIMIT.clone().acquire_owned().await?;
    let temp = TemporaryPdf {path: std::env::temp_dir().join(format!("hoover4-pdf-{:032x}",rand::random::<u128>()))};
    tokio::fs::create_dir(&temp.path).await?;
    let mut paths = Vec::new();
    for part in &parts {
        let path = temp.path.join(format!("{:05}.pdf",part.range.part_index));
        let mut file = tokio::fs::File::create(&path).await?;
        tokio::io::copy(&mut part_reader(id,part).await?,&mut file).await?;
        paths.push(path);
    }
    let output = temp.path.join("complete.pdf");
    let mut command = tokio::process::Command::new("qpdf");
    command.arg("--empty").arg("--pages");
    for path in paths {command.arg(path).arg("1-z");}
    let result = tokio::time::timeout(std::time::Duration::from_secs(300),command.arg("--").arg(&output).kill_on_drop(true).output()).await??;
    anyhow::ensure!(result.status.success() || result.status.code() == Some(3), "PDF assembly failed: {}",String::from_utf8_lossy(&result.stderr));
    let file = tokio::fs::File::open(output).await?;
    let stream = tokio_util::io::ReaderStream::new(file).map_err(anyhow::Error::from).map_ok(move |bytes| {let _ = (&temp,&permit);bytes});
    Ok(([("Content-Type","application/pdf")],Body::from_stream(stream)).into_response())
}

pub async fn download_pdf(Extension(user): Extension<CurrentUser>,Path((dataset,hash,kind)):Path<(String,String,String)>) -> Response {
    let id = DocumentIdentifier {collection_dataset:dataset,file_hash:hash};
    complete_response(&user,&id,&DocumentPdfSourceItem {source_kind:kind,..Default::default()}).await.unwrap_or_else(error_response)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn part(index:u16,first:u32,last:u32) -> ResolvedPdfPart {
        ResolvedPdfPart {range:DocumentPdfPart {part_index:index,first_page:first,last_page:last,size_bytes:30_000_000},s3_path:String::new()}
    }
    #[test]
    fn manifests_require_consecutive_complete_document_ranges() {
        assert!(verify_ranges(&[part(1,1,100),part(2,101,140)],140).is_ok());
        assert!(verify_ranges(&[part(1,1,100)],140).is_err());
        assert!(verify_ranges(&[part(1,1,100),part(2,100,140)],140).is_err());
        assert!(verify_ranges(&[part(1,1,100),part(2,102,140)],140).is_err());
    }
    #[tokio::test]
    async fn temporary_directory_is_removed_on_task_cancellation() {
        let path=std::env::temp_dir().join(format!("hoover4-pdf-test-{:032x}",rand::random::<u128>()));
        tokio::fs::create_dir(&path).await.unwrap();
        let owned=path.clone();
        let (ready,started)=tokio::sync::oneshot::channel();
        let task=tokio::spawn(async move {
            let _temp=TemporaryPdf {path:owned};
            ready.send(()).unwrap();
            std::future::pending::<()>().await;
        });
        started.await.unwrap();
        task.abort();
        assert!(task.await.unwrap_err().is_cancelled());
        assert!(!path.exists());
    }
}
