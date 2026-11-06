//! Actual document dates use the same inclusive predicate in results and histogram bins.
use std::collections::BTreeSet;
use common::{current_user::CurrentUser, search_query::{SearchQuery,RangeFilter,DATE_UNKNOWN},search_result::FacetOriginalValue};
use backend::db_utils::clickhouse_utils::get_collection_client;

fn user()->CurrentUser { CurrentUser{username:"date-fixture".into(),fullname:String::new(),email:String::new(),is_admin:true,groups:Vec::new()} }
async fn sql(statement:String)->anyhow::Result<()> {
    let response:serde_json::Value=reqwest::Client::new().post(format!("{}/sql?mode=raw",std::env::var("MANTICORE_URL")?))
        .basic_auth("manticore",Some("manticore")).form(&[("query",statement)]).send().await?.json().await?;
    let rows=response.as_array().cloned().unwrap_or_else(||vec![response.clone()]);
    for row in rows { anyhow::ensure!(row.get("error").and_then(serde_json::Value::as_str).is_none_or(str::is_empty),"Fixture SQL failed: {row}"); }
    Ok(())
}
fn query(term:String)->SearchQuery {
    let mut query=SearchQuery{query_string:term,..Default::default()};
    query.facet_filters.insert("collection_dataset".into(),BTreeSet::from([FacetOriginalValue::String("release_api_a_documents".into())]));
    query
}
async fn ledger()->anyhow::Result<()> {
    sql("CREATE TABLE IF NOT EXISTS release_api_a_2_pages LIKE release_api_a_1_pages".into()).await?;
    get_collection_client("release_api_a").query("INSERT INTO manticore_shards (shard_name,shard_index,text_bytes,doc_count) VALUES ('release_api_a_1',1,1,1),('release_api_a_2',2,1,1)").execute().await?;
    Ok(())
}

#[tokio::test]
#[ignore="requires reserved isolated release reader fixtures"]
async fn recorded_dates_exclude_gaps_and_histogram_bins_match_results()->anyhow::Result<()> {
    anyhow::ensure!(std::env::var("HOOVER4_RELEASE_READER_FIXTURES").as_deref()==Ok("1"),"Reserved fixtures are required.");
    ledger().await?;
    let run=std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?.as_nanos();
    let term=format!("datefixture{run}");
    let records=vec![("gap",vec![946684800,1577836800]),("inside",vec![1199145600]),("unknown",vec![]),("historic",vec![-315619200]),("boundary",vec![1104537600,1293839999])];
    let quote=backend::db_utils::manticore_match::quoted_manticore_string;
    for (index,(name,dates)) in records.iter().enumerate() {
        for page in 1..=2 {
            let values=dates.iter().map(i64::to_string).collect::<Vec<_>>().join(",");
            let low=dates.iter().min().copied().unwrap_or(DATE_UNKNOWN);
            let high=dates.iter().max().copied().unwrap_or(DATE_UNKNOWN);
            let row=format!("({}, {}, {}, 'release_api_a_documents','raw_text',{page},({values}),{low},{high},({}))",(run%i64::MAX as u128)as u64+index as u64*10+page,quote(&term),quote(&format!("{name}{run}")),if *name=="inside" {2}else{1});
            sql(format!("INSERT INTO release_api_a_1_pages (id,page_text,file_hash,collection_dataset,extracted_by,page_id,dates,date_min,date_max,file_paths) VALUES {row}")).await?;
            if *name=="inside" || *name=="unknown" { sql(format!("INSERT INTO release_api_a_2_pages (id,page_text,file_hash,collection_dataset,extracted_by,page_id,dates,date_min,date_max,file_paths) VALUES {row}")).await?; }
        }
    }
    let base=query(term.clone());
    let mut selected=base.clone();
    selected.range_filters.insert("dates".into(),RangeFilter{min:Some(1104537600),max:Some(1293839999),include_unknown:false});
    let mut folder_query=selected.clone();
    folder_query.facet_filters.insert("file_paths".into(),BTreeSet::from([FacetOriginalValue::Int(1)]));
    assert_eq!(backend::api::search::search_for_results(&user(),folder_query.clone(),0).await?.results.len(),1);
    assert_eq!(backend::api::search::search_for_results_hit_count(&user(),folder_query).await?.total,1);
    let found=backend::api::search::search_for_results(&user(),selected.clone(),0).await?;
    assert_eq!(found.results.len(),3);
    let histogram=backend::api::search::search_date_histogram(&user(),selected).await?;
    assert_eq!(histogram.unknown_count,2);
    for bin in histogram.buckets {
        let mut bin_query=base.clone();
        bin_query.range_filters.insert("dates".into(),RangeFilter{min:Some(bin.start),max:Some(bin.end-1),include_unknown:false});
        let found=backend::api::search::search_for_results(&user(),bin_query,0).await?;
        assert_eq!(bin.count,found.results.len()as u64,"Bin {}..{}",bin.start,bin.end);
    }
    get_collection_client("release_api_b").query("INSERT INTO manticore_shards (shard_name,shard_index,text_bytes,doc_count) VALUES ('release_api_b_1',1,1,1)").execute().await?;
    sql(format!("INSERT INTO release_api_b_1_pages (id,page_text,file_hash,collection_dataset,extracted_by,page_id,dates,date_min,date_max) VALUES ({},{},{},'release_api_b_documents','raw_text',1,(1199145600),1199145600,1199145600)",(run%i64::MAX as u128)as u64+100,quote(&term),quote(&format!("inside{run}")))).await?;
    let mut multi=base.clone();
    multi.facet_filters.get_mut("collection_dataset").unwrap().insert(FacetOriginalValue::String("release_api_b_documents".into()));
    multi.range_filters.insert("dates".into(),RangeFilter{min:Some(1199145600),max:Some(1199145600),include_unknown:false});
    let found=backend::api::search::search_for_results(&user(),multi.clone(),0).await?;
    assert_eq!(found.results.len(),3);
    let histogram=backend::api::search::search_date_histogram(&user(),multi.clone()).await?;
    let bin=histogram.buckets.iter().find(|bin|bin.start<=1199145600 && bin.end>1199145600).unwrap();
    multi.range_filters.insert("dates".into(),RangeFilter{min:Some(bin.start),max:Some(bin.end-1),include_unknown:false});
    assert_eq!(bin.count,backend::api::search::search_for_results(&user(),multi,0).await?.results.len()as u64);
    for filter in [RangeFilter{min:None,max:Some(-1),include_unknown:false},RangeFilter{min:Some(1577836800),max:None,include_unknown:false},RangeFilter{include_unknown:true,..Default::default()}] {
        let expected=if filter.include_unknown {2}else{1};
        let mut q=base.clone();q.range_filters.insert("dates".into(),filter);
        assert_eq!(backend::api::search::search_for_results(&user(),q,0).await?.results.len(),expected);
    }
    Ok(())
}

#[tokio::test]
#[ignore="requires reserved isolated release reader fixtures"]
async fn histogram_counts_ten_thousand_documents_with_duplicate_pages()->anyhow::Result<()> {
    anyhow::ensure!(std::env::var("HOOVER4_RELEASE_READER_FIXTURES").as_deref()==Ok("1"),"Reserved fixtures are required.");
    ledger().await?;
    let run=std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?.as_nanos();
    let term=format!("bulkdate{run}");
    for start in (0..10000).step_by(500) {
        let mut rows=Vec::new();
        for doc in start..start+500 {
            for page in 0..2 {
                rows.push(format!("({},'{term}','bulk{run}_{doc:05}','release_api_a_documents','raw_text',{},(1000000000),1000000000,1000000000)",(run%i64::MAX as u128)as u64+doc*2+page,page+1));
            }
        }
        sql(format!("INSERT INTO release_api_a_1_pages (id,page_text,file_hash,collection_dataset,extracted_by,page_id,dates,date_min,date_max) VALUES {}",rows.join(","))).await?;
    }
    let started=std::time::Instant::now();
    let histogram=backend::api::search::search_date_histogram(&user(),query(term)).await?;
    assert_eq!(histogram.buckets.iter().map(|bin|bin.count).sum::<u64>(),10000);
    eprintln!("The 10000-document, 20000-page histogram took {:?}.",started.elapsed());
    Ok(())
}
