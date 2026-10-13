//! Verify PDF part reading and temporary assembly against local collection storage.

use backend::{db_utils::{clickhouse_utils::get_client_for_dataset,collection_bucket,s3_client},server_extra::pdf_parts::{source_parts,read_part_bytes,complete_response}};
use common::{current_user::CurrentUser,document_sources::DocumentPdfSourceItem,search_result::DocumentIdentifier};
use futures::StreamExt;

fn pdf(text:&str) -> Vec<u8> {
    let content=format!("BT /F1 12 Tf 50 100 Td ({text}) Tj ET");
    let objects=vec!["<< /Type /Catalog /Pages 2 0 R >>".into(),"<< /Type /Pages /Kids [3 0 R] /Count 1 >>".into(),
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>".into(),
        format!("<< /Length {} >>\nstream\n{content}\nendstream",content.len()),"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>".into()];
    let mut data=String::from("%PDF-1.4\n");let mut offsets=vec![0];
    for (index,object) in objects.iter().enumerate() {offsets.push(data.len());data.push_str(&format!("{} 0 obj\n{object}\nendobj\n",index+1));}
    let xref=data.len();data.push_str(&format!("xref\n0 {}\n0000000000 65535 f \n",objects.len()+1));
    for offset in offsets.iter().skip(1) {data.push_str(&format!("{offset:010} 00000 n \n"));}
    data.push_str(&format!("trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n",objects.len()+1));data.into_bytes()
}
fn user(admin:bool) -> CurrentUser {CurrentUser {username:"pdf-parts-integration".into(),fullname:String::new(),email:String::new(),is_admin:admin,groups:vec![]}}
fn temporary_count() -> usize {std::fs::read_dir(std::env::temp_dir()).unwrap().filter_map(Result::ok).filter(|p|p.file_name().to_string_lossy().starts_with("hoover4-pdf-")).count()}

#[tokio::test]
#[ignore="requires the migrated local testdata collection and qpdf"]
async fn source_kinds_borrowing_acl_assembly_order_and_disconnect_cleanup() {
    let dataset="testdata_p40large";
    let id=DocumentIdentifier {collection_dataset:dataset.into(),file_hash:format!("reader-test-{:032x}",rand::random::<u128>())};
    let client=get_client_for_dataset(dataset).await.unwrap();
    let s3=s3_client().await.unwrap();let bucket=collection_bucket("testdata");
    let keys=[format!("derived/reader-tests/{}/first.pdf",id.file_hash),format!("derived/reader-tests/{}/second.pdf",id.file_hash)];
    for (key,text) in keys.iter().zip(["FirstMarker","LaterMarker"]) {s3.put_object().bucket(&bucket).key(key).body(pdf(text).into()).send().await.unwrap();}
    client.query("INSERT INTO pdfs (collection_dataset,pdf_hash,page_count) VALUES (?,?,2)").bind(dataset).bind(&id.file_hash).execute().await.unwrap();
    for kind in ["original","preview"] {
        for (i,key) in keys.iter().enumerate() {client.query("INSERT INTO pdf_parts (collection_dataset,hash,source_kind,segmentation,part_index,first_page,last_page,s3_path,size_bytes) VALUES (?,?,?,1,?,?,?,?,1)")
            .bind(dataset).bind(&id.file_hash).bind(kind).bind(i as u16+1).bind(i as u32+1).bind(i as u32+1).bind(format!("s3://{bucket}/{key}")).execute().await.unwrap();}
    }
    client.query("INSERT INTO pdf_previews (collection_dataset,hash,s3_path,page_count,size_bytes) VALUES (?,?,?,2,1)").bind(dataset).bind(&id.file_hash).bind(format!("s3://{bucket}/{}",keys[0])).execute().await.unwrap();
    let mut source=DocumentPdfSourceItem {page_count:999,engine:"tesseract".into(),languages:"eng".into(),..Default::default()};
    client.query("INSERT INTO pdf_ocr_results (collection_dataset,pdf_hash,engine,languages,blob_key,page_count,part_count,text_complete,form) VALUES (?,?,\'tesseract\',\'eng\',\'\',2,2,1,\'overlay\')").bind(dataset).bind(&id.file_hash).execute().await.unwrap();
    for i in 1..=2_u16 {client.query("INSERT INTO pdf_ocr_parts (collection_dataset,hash,source_kind,engine,languages,segmentation,part_index,first_page,last_page,blob_key,size_bytes,borrows_source) VALUES (?,?,\'original\',\'tesseract\',\'eng\',1,?,?,?,\'\',1,1)")
        .bind(dataset).bind(&id.file_hash).bind(i).bind(i as u32).bind(i as u32).execute().await.unwrap();}
    let parts=source_parts(&user(true),&id,&source).await.unwrap();assert_eq!(parts.len(),2);
    assert!(String::from_utf8(read_part_bytes(&id,&parts[1]).await.unwrap()).unwrap().contains("LaterMarker"));
    for kind in ["original","preview"] {source.source_kind=kind.into();source.engine.clear();let parts=source_parts(&user(true),&id,&source).await.unwrap();assert_eq!(parts.len(),2);assert_eq!(parts[1].range.first_page,2);}
    client.query("INSERT INTO pdf_ocr_results (collection_dataset,pdf_hash,engine,languages,blob_key,page_count,part_count,text_complete,source_kind,form) VALUES (?,?,\'tesseract\',\'ron\',\'\',2,2,1,\'preview\',\'overlay\')").bind(dataset).bind(&id.file_hash).execute().await.unwrap();
    for i in 1..=2_u16 {client.query("INSERT INTO pdf_ocr_parts (collection_dataset,hash,source_kind,engine,languages,segmentation,part_index,first_page,last_page,blob_key,size_bytes,borrows_source) VALUES (?,?,\'preview\',\'tesseract\',\'ron\',1,?,?,?, ?,1,?)")
        .bind(dataset).bind(&id.file_hash).bind(i).bind(i as u32).bind(i as u32).bind(if i==1 {keys[0].clone()} else {String::new()}).bind(if i==1 {0_u8} else {1_u8}).execute().await.unwrap();}
    let preview_ocr=DocumentPdfSourceItem {source_kind:"preview".into(),engine:"tesseract".into(),languages:"ron".into(),..Default::default()};
    let preview_parts=source_parts(&user(true),&id,&preview_ocr).await.unwrap();assert_eq!(preview_parts.len(),2);
    assert!(String::from_utf8(read_part_bytes(&id,&preview_parts[1]).await.unwrap()).unwrap().contains("LaterMarker"));
    client.query("INSERT INTO pdf_ocr_results (collection_dataset,pdf_hash,engine,languages,blob_key,page_count,part_count,text_complete,source_kind,form) VALUES (?,?,\'easyocr\',\'en\',?,1,1,1,\'image\',\'overlay\')")
        .bind(dataset).bind(&id.file_hash).bind(&keys[0]).execute().await.unwrap();
    client.query("INSERT INTO pdf_ocr_parts (collection_dataset,hash,source_kind,engine,languages,segmentation,part_index,first_page,last_page,blob_key,size_bytes) VALUES (?,?,\'image\',\'easyocr\',\'en\',1,1,1,1,?,1)")
        .bind(dataset).bind(&id.file_hash).bind(&keys[0]).execute().await.unwrap();
    let image=DocumentPdfSourceItem {source_kind:"image".into(),engine:"easyocr".into(),languages:"en".into(),..Default::default()};
    let image_parts=source_parts(&user(true),&id,&image).await.unwrap();assert_eq!(image_parts.len(),1);
    assert!(String::from_utf8(read_part_bytes(&id,&image_parts[0]).await.unwrap()).unwrap().contains("FirstMarker"));
    let inline_id=DocumentIdentifier {file_hash:format!("{}-inline",id.file_hash),..id.clone()};
    let inline=pdf("InlineMarker");let hex=inline.iter().map(|b|format!("{b:02x}")).collect::<String>();
    client.query("INSERT INTO pdfs (collection_dataset,pdf_hash,page_count) VALUES (?,?,1)").bind(dataset).bind(&inline_id.file_hash).execute().await.unwrap();
    client.query("INSERT INTO blobs (collection_dataset,blob_hash,blob_size_bytes,s3_path,stored_in_clickhouse) VALUES (?,?,?,\'\',1)").bind(dataset).bind(&inline_id.file_hash).bind(inline.len() as u64).execute().await.unwrap();
    client.query("INSERT INTO blob_values (collection_dataset,blob_hash,blob_value,blob_length) VALUES (?,?,unhex(?),?)").bind(dataset).bind(&inline_id.file_hash).bind(hex).bind(inline.len() as u64).execute().await.unwrap();
    client.query("INSERT INTO pdf_parts (collection_dataset,hash,source_kind,segmentation,part_index,first_page,last_page,s3_path,size_bytes) VALUES (?,?,\'original\',1,1,1,1,\'\',1)").bind(dataset).bind(&inline_id.file_hash).execute().await.unwrap();
    client.query("INSERT INTO pdf_ocr_results (collection_dataset,pdf_hash,engine,languages,blob_key,page_count,part_count,text_complete,form) VALUES (?,?,\'tesseract\',\'eng\',\'\',1,1,1,\'overlay\')").bind(dataset).bind(&inline_id.file_hash).execute().await.unwrap();
    client.query("INSERT INTO pdf_ocr_parts (collection_dataset,hash,source_kind,engine,languages,segmentation,part_index,first_page,last_page,blob_key,size_bytes,borrows_source) VALUES (?,?,\'original\',\'tesseract\',\'eng\',1,1,1,1,\'\',1,1)").bind(dataset).bind(&inline_id.file_hash).execute().await.unwrap();
    let inline_source=DocumentPdfSourceItem {engine:"tesseract".into(),languages:"eng".into(),..Default::default()};
    let inline_parts=source_parts(&user(true),&inline_id,&inline_source).await.unwrap();
    assert_eq!(read_part_bytes(&inline_id,&inline_parts[0]).await.unwrap(),inline);
    for table in ["pdfs","pdf_parts","pdf_ocr_parts","pdf_ocr_results","blobs","blob_values"] {
        let column=if ["pdfs","pdf_ocr_results"].contains(&table) {"pdf_hash"} else if ["blobs","blob_values"].contains(&table) {"blob_hash"} else {"hash"};
        client.query(&format!("ALTER TABLE {table} DELETE WHERE collection_dataset = ? AND {column} = ? SETTINGS mutations_sync=2")).bind(dataset).bind(&inline_id.file_hash).execute().await.unwrap();
    }
    let denied_id=DocumentIdentifier {collection_dataset:"pdf-parts-ungranted_dataset".into(),..id.clone()};
    let error=source_parts(&user(false),&denied_id,&source).await.unwrap_err();assert!(backend::auth::guard::is_forbidden(&error));
    source.source_kind="original".into();source.engine="tesseract".into();
    let before=temporary_count();
    let response=complete_response(&user(true),&id,&source).await.unwrap();assert_eq!(temporary_count(),before+1);
    let mut stream=response.into_body().into_data_stream();let bytes=stream.next().await.unwrap().unwrap();assert!(bytes.starts_with(b"%PDF"));
    drop(stream);assert_eq!(temporary_count(),before);
    let response=complete_response(&user(true),&id,&source).await.unwrap();
    let mut stream=response.into_body().into_data_stream();let mut assembled=Vec::new();while let Some(bytes)=stream.next().await {assembled.extend(bytes.unwrap());}drop(stream);
    assert_eq!(temporary_count(),before);
    let path=std::env::temp_dir().join(format!("reader-test-{}.pdf",id.file_hash));tokio::fs::write(&path,assembled).await.unwrap();
    let output=tokio::process::Command::new("qpdf").arg("--show-npages").arg(&path).output().await.unwrap();assert_eq!(String::from_utf8(output.stdout).unwrap().trim(),"2");
    let raw=path.with_extension("qdf");let status=tokio::process::Command::new("qpdf").args(["--qdf","--object-streams=disable"]).arg(&path).arg(&raw).status().await.unwrap();assert!(status.success());
    let data=String::from_utf8_lossy(&tokio::fs::read(&raw).await.unwrap()).to_string();assert!(data.find("FirstMarker").unwrap()<data.find("LaterMarker").unwrap());
    let complete_key=format!("derived/reader-tests/{}/complete.pdf",id.file_hash);
    let complete_bytes=tokio::fs::read(&path).await.unwrap();
    s3.put_object().bucket(&bucket).key(&complete_key).body(complete_bytes.clone().into()).send().await.unwrap();
    client.query("INSERT INTO blobs (collection_dataset,blob_hash,blob_size_bytes,s3_path,stored_in_clickhouse) VALUES (?,?,?,?,0)")
        .bind(dataset).bind(&id.file_hash).bind(complete_bytes.len() as u64).bind(format!("s3://{bucket}/{complete_key}")).execute().await.unwrap();
    client.query("ALTER TABLE pdf_parts DELETE WHERE collection_dataset = ? AND hash = ? AND part_index = 2 SETTINGS mutations_sync=2")
        .bind(dataset).bind(&id.file_hash).execute().await.unwrap();
    let native=DocumentPdfSourceItem::default();
    let fallback=source_parts(&user(true),&id,&native).await.unwrap();assert_eq!(fallback.len(),1);assert_eq!(fallback[0].range.last_page,2);
    assert_eq!(read_part_bytes(&id,&fallback[0]).await.unwrap(),complete_bytes);
    let available=backend::api::documents::get_document_sources::get_document_sources_status(&user(true),id.clone()).await.unwrap();
    assert!(available.sources.iter().any(|item|matches!(item,common::document_sources::DocumentSourceItem::Pdf(item) if !item.is_ocr() && item.kind()=="original")));
    assert!(!available.errors.is_empty());
    for kind in ["original","preview"] {client.query("INSERT INTO pdf_parts (collection_dataset,hash,source_kind,segmentation,part_index,first_page,last_page,s3_path,size_bytes) VALUES (?,?,?,1,2,2,2,?,1)")
        .bind(dataset).bind(&id.file_hash).bind(kind).bind(format!("s3://{bucket}/{}",keys[1])).execute().await.unwrap();}
    client.query("ALTER TABLE blobs DELETE WHERE collection_dataset = ? AND blob_hash = ? SETTINGS mutations_sync=2").bind(dataset).bind(&id.file_hash).execute().await.unwrap();
    s3.delete_object().bucket(&bucket).key(complete_key).send().await.unwrap();
    tokio::fs::remove_file(path).await.unwrap();tokio::fs::remove_file(raw).await.unwrap();
    s3.put_object().bucket(&bucket).key(&keys[1]).body(b"invalid PDF".to_vec().into()).send().await.unwrap();
    for _ in 0..3 {
        let result=tokio::time::timeout(std::time::Duration::from_secs(10),complete_response(&user(true),&id,&source)).await.unwrap();
        assert!(result.is_err());assert_eq!(temporary_count(),before);
    }
    for table in ["pdfs","pdf_previews","pdf_parts","pdf_ocr_parts","pdf_ocr_results"] {let column=if ["pdfs","pdf_ocr_results"].contains(&table) {"pdf_hash"} else {"hash"};client.query(&format!("ALTER TABLE {table} DELETE WHERE collection_dataset = ? AND {column} = ? SETTINGS mutations_sync=2")).bind(dataset).bind(&id.file_hash).execute().await.unwrap();}
    for key in keys {s3.delete_object().bucket(&bucket).key(key).send().await.unwrap();}
}

#[tokio::test]
#[ignore="requires the prepared and indexed local multipart PDF fixture"]
async fn multipart_search_returns_document_pages_and_complete_count() {
    let id=DocumentIdentifier {collection_dataset:"testdata_p40large".into(),file_hash:"9eacd2f06fe0a705f8ac66142572f3f1b1da1b4bfb52c4f3612a59ae62de54fa".into()};
    let results=backend::api::documents::search_document_pdf::search_document_pdf(&user(true),id.clone(),"MIT".into(),None).await.unwrap();
    assert!(results.total>0);
    assert_eq!(results.total as usize,results.results.len());
    assert!(results.results.iter().any(|hit|hit.page_index>=1000));
    assert!(results.results.iter().all(|hit|hit.page_index<1020));
    let bytes=backend::api::documents::download_document::read_blob_bytes(&user(true),&id,128*1024*1024).await.unwrap();
    let whole:serde_json::Value=reqwest::Client::new().post(backend::api::documents::search_document_pdf::pdf_search_endpoint())
        .query(&[("keywords","[\"mit\"]")]).header("Content-Type","application/pdf").body(bytes).send().await.unwrap().json().await.unwrap();
    let expected:common::pdf_search_results::PdfSearchResults=serde_json::from_value(whole[0]["result_set"].clone()).unwrap();
    assert_eq!(results.total,expected.total);
    assert_eq!(serde_json::to_value(&results.results).unwrap(),serde_json::to_value(&expected.results).unwrap());
    eprintln!("multipart_document_hits={}",results.total);
}
