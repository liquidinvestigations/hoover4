//! Reader contracts against explicitly reserved disposable fixtures.

use backend::db_utils::clickhouse_utils::get_collection_client;
use common::{current_user::CurrentUser, search_result::DocumentIdentifier};

fn user(admin: bool) -> CurrentUser {
    CurrentUser { username: "release-reader-fixture".into(), fullname: String::new(), email: String::new(), is_admin: admin, groups: Vec::new() }
}

fn document(dataset: &str, hash: &str) -> DocumentIdentifier {
    DocumentIdentifier { collection_dataset: dataset.into(), file_hash: hash.into() }
}

async fn message(collection: &str, hash: &str) -> anyhow::Result<()> {
    let client = get_collection_client(collection);
    let dataset = format!("{collection}_documents");
    client.query("INSERT INTO email_headers (collection_dataset,email_hash,subject,date_sent,date_sent_known) VALUES (?, ?, 'shared fixture', toDateTime(1600000000), 1)")
        .bind(&dataset).bind(hash).execute().await?;
    client.query("INSERT INTO vfs_files (collection_dataset,container_hash,path,hash,updated_at) VALUES (?, '', ?, ?, toDateTime(1600000000))")
        .bind(&dataset).bind(format!("/{hash}.eml")).bind(hash).execute().await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires explicitly reserved release reader fixtures"]
async fn exact_hash_graph_aliases_respect_permissions_live_sources_and_logical_limits() -> anyhow::Result<()> {
    anyhow::ensure!(std::env::var("HOOVER4_RELEASE_READER_FIXTURES").as_deref() == Ok("1"), "Reserved fixtures are required.");
    let run = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?.as_nanos();
    let root = &format!("release-shared-email-{run}");
    let child = &format!("release-neighbor-email-{run}");
    for collection in ["release_api_a", "release_api_b", "release_api_hidden"] { message(collection, root).await?; }
    message("release_api_b", child).await?;
    let client = get_collection_client("release_api_b");
    client.query("INSERT INTO email_edges (collectionname,src_dataset,src_hash,dst_dataset,dst_hash,kind,confidence,evidence) VALUES ('release_api_b','release_api_b_documents',?,'release_api_b_documents',?,'reply',0.7,'fixture reply')")
        .bind(root).bind(child).execute().await?;
    let centre = document("release_api_a_documents", root);
    let graph = backend::api::documents::get_email_graph::get_email_graph(&user(false), centre.clone(), 2, 3).await?;
    assert_eq!(graph.nodes.len(), 2);
    let node = graph.nodes.iter().find(|node| node.is_centre).unwrap();
    assert_eq!(node.document_identifier, centre);
    assert_eq!(node.occurrences.len(), 2);
    assert!(node.occurrences.iter().all(|occurrence| occurrence.collectionname != "release_api_hidden"));
    assert_eq!(graph.edges.len(), 1);
    assert_eq!(graph.edges[0].src, centre);
    let scoped = backend::api::documents::get_email_graph::get_email_graph_scoped(
        &user(false), centre.clone(), 2, 3, Some(&["release_api_a".into()]),
    ).await?;
    assert_eq!(scoped.nodes.len(), 1);
    assert_eq!(scoped.nodes[0].occurrences.len(), 1);
    assert!(scoped.edges.is_empty());
    assert_eq!(scoped.cluster_size, 1);
    let limited = backend::api::documents::get_email_graph::get_email_graph(&user(false), centre.clone(), 1, 3).await?;
    assert_eq!(limited.nodes.len(), 1);
    assert_eq!(limited.nodes[0].occurrences.len(), 2);
    assert!(limited.truncated);
    let admin = backend::api::documents::get_email_graph::get_email_graph(&user(true), centre.clone(), 2, 3).await?;
    assert_eq!(admin.nodes.iter().find(|node| node.is_centre).unwrap().occurrences.len(), 3);
    client.query("INSERT INTO vfs_files (collection_dataset,container_hash,path,hash,updated_at,is_deleted) VALUES ('release_api_b_documents','',?, ?, toDateTime(1600000010),1)")
        .bind(format!("/{root}.eml")).bind(root).execute().await?;
    let after = backend::api::documents::get_email_graph::get_email_graph(&user(false), centre, 2, 3).await?;
    assert_eq!(after.nodes.len(), 1);
    assert_eq!(after.nodes[0].occurrences.len(), 1);
    assert!(after.edges.is_empty());
    assert!(backend::api::documents::get_email_graph::get_email_graph(&user(false), document("release_api_b_documents", root), 2, 3).await.is_err());
    Ok(())
}

#[tokio::test]
#[ignore = "requires explicitly reserved release reader fixtures"]
async fn projected_source_keeps_four_hits_across_rendering_counts_and_targets() -> anyhow::Result<()> {
    anyhow::ensure!(std::env::var("HOOVER4_RELEASE_READER_FIXTURES").as_deref() == Ok("1"), "Reserved fixtures are required.");
    let run = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?.as_nanos();
    let hash = sha256::digest(format!("projection-{run}"));
    let dataset = "release_api_a_documents";
    let identifier = document(dataset, &hash);
    let source = format!("  quokka café\r\n{}\r\nquokka harbor quokka forest quokka  ", "A".repeat(240));
    let (source, find_query) = match std::env::var("HOOVER4_RETAINED_TEXT_FIXTURE") {
        Ok(path) => {
            let fixture: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(path)?)?;
            (fixture["source"].as_str().unwrap().to_string(), fixture["find_query"].as_str().unwrap().to_string())
        }
        Err(_) => (source, "quokka".to_string()),
    };
    let indexed = common::text_projection::indexed_text(&source);
    let client = get_collection_client("release_api_a");
    client.query("INSERT INTO text_content (collection_dataset,file_hash,extracted_by,page_id,text,text_bytes,version) VALUES (?,?,'raw_text',1,?,?,1)")
        .bind(dataset).bind(&hash).bind(&source).bind(source.len() as u64).execute().await?;
    client.query("INSERT INTO manticore_shard_assignments (collection_dataset,file_hash,shard_name,text_bytes) VALUES (?,?,'release_api_a_1',?)")
        .bind(dataset).bind(&hash).bind(indexed.len() as u64).execute().await?;
    client.query("INSERT INTO manticore_shards (shard_name,shard_index,text_bytes,doc_count) VALUES ('release_api_a_1',1,1,1)").execute().await?;
    let quote = backend::db_utils::manticore_match::quoted_manticore_string;
    let sql = format!("INSERT INTO release_api_a_1_pages (id,page_text,file_hash,collection_dataset,extracted_by,page_id) VALUES ({},{},{},{},'raw_text',1)", (run % (i64::MAX as u128)) as u64, quote(&indexed), quote(&hash), quote(dataset));
    let response: serde_json::Value = reqwest::Client::new()
        .post(format!("{}/sql?mode=raw", std::env::var("MANTICORE_URL")?))
        .basic_auth("manticore", Some("manticore")).form(&[("query", sql)]).send().await?.json().await?;
    anyhow::ensure!(response[0]["error"].as_str().is_none_or(str::is_empty), "Manticore insert failed: {response}");
    let matches = backend::api::documents::document_matches::get_document_matches(&user(false), identifier.clone(), find_query.clone()).await?;
    assert_eq!(matches.completeness, common::document_matches::MatchCompleteness::Complete);
    assert_eq!(matches.targets.len(), 4);
    let counts = backend::api::documents::search_document_itemcount::search_document_item_count(
        &user(false), identifier.clone(), find_query.clone(), vec![common::document_sources::DocumentSourceItem::Text(common::document_sources::DocumentTextSourceItem {
            extracted_by: "raw_text".into(), min_page: 1, max_page: 1,
        })],
    ).await?;
    assert_eq!(counts.0[0].1, common::document_text_pages::HitCountState::Exact(4));
    let view = backend::api::documents::document_text::get_text_page_view(
        &user(false), identifier.clone(), "raw_text".into(), Some(1), find_query.clone(), None,
    ).await?;
    if let common::document_text_pages::TextPageBody::Text { spans, highlight_error, .. } = view.body {
        assert!(highlight_error.is_none());
        assert_eq!(spans.iter().map(|span| span.text.as_str()).collect::<String>(), source);
        assert_eq!(spans.iter().filter(|span| span.is_highlighted).count(), 4);
    } else { panic!("The stored source page is missing."); }
    client.query("INSERT INTO text_content (collection_dataset,file_hash,extracted_by,page_id,text,text_bytes,version) VALUES (?,?,'raw_text',1,'changed quokka',14,2)")
        .bind(dataset).bind(&hash).execute().await?;
    let stale = backend::api::documents::document_matches::get_document_matches(&user(false), identifier, find_query.clone()).await?;
    assert_eq!(stale.completeness, common::document_matches::MatchCompleteness::Unavailable);
    assert!(stale.targets.is_empty());
    Ok(())
}

#[tokio::test]
#[ignore = "requires explicitly reserved release reader fixtures"]
async fn occurrence_expansion_is_bounded_and_keeps_the_selected_copy() -> anyhow::Result<()> {
    anyhow::ensure!(std::env::var("HOOVER4_RELEASE_READER_FIXTURES").as_deref() == Ok("1"), "Reserved fixtures are required.");
    let run = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?.as_nanos();
    let hash = sha256::digest(format!("occurrence-bound-{run}"));
    let client = get_collection_client("release_api_b");
    client.query("INSERT INTO email_headers (collection_dataset,email_hash,subject,date_sent,date_sent_known) SELECT concat('release_api_b_occurrence_',leftPad(toString(number),3,'0')), ?, 'bounded occurrence fixture', toDateTime(1600000000), 1 FROM numbers(501)")
        .bind(&hash).execute().await?;
    client.query("INSERT INTO vfs_files (collection_dataset,container_hash,path,hash,updated_at) SELECT concat('release_api_b_occurrence_',leftPad(toString(number),3,'0')), '', ?, ?, toDateTime(1600000000) FROM numbers(501)")
        .bind(format!("/{hash}.eml")).bind(&hash).execute().await?;
    let centre = document("release_api_b_occurrence_500", &hash);
    let graph = backend::api::documents::get_email_graph::get_email_graph(&user(false), centre.clone(), 50, 3).await?;
    assert_eq!(graph.nodes.len(), 1);
    assert_eq!(graph.nodes[0].occurrences.len(), common::email_graph::MAX_GRAPH_OCCURRENCES);
    assert_eq!(graph.nodes[0].document_identifier, centre);
    assert!(graph.nodes[0].occurrences.iter().any(|occurrence| occurrence.document_identifier == centre));
    assert!(graph.occurrences_truncated);
    assert!(graph.truncated);
    assert!(!graph.cluster_size_complete);
    Ok(())
}

#[tokio::test]
#[ignore = "requires explicitly reserved release reader fixtures"]
async fn collection_cleanup_requires_an_unambiguous_latest_tombstone() -> anyhow::Result<()> {
    anyhow::ensure!(std::env::var("HOOVER4_RELEASE_READER_FIXTURES").as_deref() == Ok("1"), "Reserved fixtures are required.");
    let run = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?.as_nanos();
    let collection = format!("release_api_a_delete_{run}");
    let client = backend::db_utils::clickhouse_utils::get_global_client().with_option("optimize_on_insert", "0");
    client.query("SYSTEM STOP MERGES collections").execute().await?;
    let result = async {
        for deleted in [0u8, 1] {
            client.query("INSERT INTO collections (collectionname,updated_at,is_deleted) VALUES (?,toDateTime(1600000000),?)")
                .bind(&collection).bind(deleted).execute().await?;
        }
        let raw = client.query("SELECT is_deleted FROM collections WHERE collectionname = ? ORDER BY is_deleted")
            .bind(&collection).fetch_all::<u8>().await?;
        anyhow::ensure!(raw == vec![0, 1], "The fixture must retain both tied states before cleanup validation.");
        let handle = tokio::runtime::Handle::current();
        let lookup = move |collection: String| {
            let handle = handle.clone();
            tokio::task::spawn_blocking(move || {
                use backend::uploads::BatchStore;
                backend::uploads::store::ClickHouseStore::new(handle).collection_deleted(&collection)
            })
        };
        anyhow::ensure!(!lookup(collection.clone()).await??, "Tied deletion states cannot prove deletion.");
        anyhow::ensure!(!lookup(format!("{collection}_missing")).await??, "A missing registry row cannot prove deletion.");
        client.query("INSERT INTO collections (collectionname,updated_at,is_deleted) VALUES (?,toDateTime(1600000001),1)")
            .bind(&collection).execute().await?;
        anyhow::ensure!(lookup(collection).await??, "An unambiguous latest tombstone must prove deletion.");
        Ok(())
    }.await;
    let restored = client.query("SYSTEM START MERGES collections").execute().await;
    restored?;
    result
}

#[tokio::test]
#[ignore = "requires explicitly reserved release reader fixtures"]
async fn facet_descriptors_keep_canonical_codes_and_storage_names_use_the_registry() -> anyhow::Result<()> {
    anyhow::ensure!(std::env::var("HOOVER4_RELEASE_READER_FIXTURES").as_deref() == Ok("1"), "Reserved fixtures are required.");
    let run = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?.as_nanos();
    let dataset = "release_api_a_documents";
    let hash = sha256::digest(format!("facet-{run}"));
    let language_id = (run % 1_000_000_000) as u64 + 1000;
    let type_id = language_id + 1;
    let client = get_collection_client("release_api_a");
    client.query("INSERT INTO manticore_shards (shard_name,shard_index,text_bytes,doc_count) VALUES ('release_api_a_1',1,1,1)").execute().await?;
    for (field, id, value) in [("language", language_id, "de"), ("filetype", type_id, "pdf")] {
        client.query("INSERT INTO string_term_id_to_text (collection_dataset,term_field,term_id,term_value) VALUES (?,?,?,?)")
            .bind(dataset).bind(field).bind(id).bind(value).execute().await?;
    }
    let quote = backend::db_utils::manticore_match::quoted_manticore_string;
    let sql = format!("INSERT INTO release_api_a_1_pages (id,page_text,file_hash,collection_dataset,extracted_by,page_id,language,file_types,file_size_bytes) VALUES ({},'facetfixture',{},{},'raw_text',1,({language_id}),({type_id}),100)", (run % i64::MAX as u128) as u64, quote(&hash), quote(dataset));
    let response: serde_json::Value = reqwest::Client::new().post(format!("{}/sql?mode=raw", std::env::var("MANTICORE_URL")?))
        .basic_auth("manticore", Some("manticore")).form(&[("query", sql)]).send().await?.json().await?;
    anyhow::ensure!(response[0]["error"].as_str().is_none_or(str::is_empty), "Manticore insert failed: {response}");
    let mut query = common::search_query::SearchQuery { query_string: "facetfixture".into(), ..Default::default() };
    query.facet_filters.insert("collection_dataset".into(), std::collections::BTreeSet::from([common::search_result::FacetOriginalValue::String(dataset.into())]));
    for (column, kind, code, id) in [("language", "language", "de", language_id), ("file_types", "filetype", "pdf", type_id)] {
        let facets = backend::api::search::search_string_facet(&user(false), query.clone(), column.into(), Some(kind.into()), None).await?;
        let item = facets.facet_values.iter().find(|item| item.original_value == common::search_result::FacetOriginalValue::Int(id)).unwrap();
        assert_eq!(item.descriptor, Some(common::search_result::FacetTermDescriptor { kind: kind.into(), code: code.into() }));
    }
    let text = backend::api::search::search_string_facet(&user(false), query.clone(), "extracted_by".into(), None, None).await?;
    assert_eq!(text.facet_values[0].descriptor.as_ref().unwrap().code, "raw_text");
    let sizes = backend::api::search::search_numeric_facet(&user(false), query).await?;
    assert_eq!(sizes.facet_values[0].descriptor.as_ref().unwrap().kind, "size_range");
    let global = backend::db_utils::clickhouse_utils::get_global_client();
    global.query("INSERT INTO collections (collectionname,fullname,is_public,created_at,updated_at,is_deleted) SELECT collectionname,'Reader fixture display',is_public,created_at,updated_at+1,is_deleted FROM collections FINAL WHERE collectionname='release_api_a'").execute().await?;
    let tree = backend::api::list_datasets::list_permitted_collection_tree(&user(false)).await?;
    assert_eq!(tree.iter().find(|node| node.collectionname == "release_api_a").unwrap().display_name.as_deref(), Some("Reader fixture display"));
    assert!(tree.iter().all(|node| node.collectionname != "release_api_hidden"));
    Ok(())
}
