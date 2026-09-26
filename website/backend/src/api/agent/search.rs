//! The search routes: `search/results`, `search/facet_values`, `search/histogram` and
//! `search/entity_explainer`.

use super::*;

// ===================================================================================
// search/results
// ===================================================================================

fn sort_spec_from_agent(sort: Option<&AgentSort>) -> Result<SortSpec, AgentError> {
    let Some(sort) = sort else { return Ok(SortSpec::default()) };
    let key = match sort.field.as_str() {
        "relevance" => SortKey::Relevance,
        "date" => SortKey::Date,
        "file_size" => SortKey::FileSize,
        "name" => SortKey::Name,
        _ => return Err(AgentError::invalid_argument("invalid sort field")),
    };
    let desc = match sort.direction.as_str() {
        "asc" => false,
        "desc" => true,
        _ => return Err(AgentError::invalid_argument("invalid sort direction")),
    };
    Ok(SortSpec { key, desc })
}

/// Every facet the search page's filter modal lists, with the term dictionary field that
/// the modal passes to `search_string_facet` to turn a term id into text. Every facet
/// except `collection_dataset` filters by integer term id.
const SEARCH_FACETS: &[(&str, Option<&str>)] = &[
    ("collection_dataset", None),
    ("file_types", Some("filetype")),
    ("file_paths", Some("vfs_node")),
    ("email_from", Some("email_address")),
    ("email_to", Some("email_address")),
    ("struct_flags", None),
    ("ner_per", Some("ner")),
    ("ner_org", Some("ner")),
    ("ner_loc", Some("ner")),
    ("ner_misc", Some("ner")),
    ("re_email", Some("regex_email")),
    ("re_phone", Some("regex_phone")),
    ("re_bank_account", Some("regex_bank_account")),
    ("re_company_id", Some("regex_company_id")),
    ("re_money", Some("regex_money")),
    ("re_crypto_wallet", Some("regex_crypto_wallet")),
];

/// The search result pages that exist: the website shows at most
/// `MAX_PAGINATION_DOCUMENT_LIMIT` results, `PAGE_SIZE` a page.
const MAX_SEARCH_PAGES: u64 =
    common::search_const::MAX_PAGINATION_DOCUMENT_LIMIT / common::search_const::PAGE_SIZE;

fn search_facet(name: &str) -> Result<Option<&'static str>, AgentError> {
    SEARCH_FACETS
        .iter()
        .find(|(field, _)| *field == name)
        .map(|(_, terms)| *terms)
        .ok_or_else(|| {
            let names: Vec<&str> = SEARCH_FACETS.iter().map(|(field, _)| *field).collect();
            AgentError::invalid_argument(format!("unknown facet {name:?}; the facets are {}", names.join(", ")))
        })
}

fn refuse_reversed_range(name: &str, low: Option<i64>, high: Option<i64>) -> Result<(), AgentError> {
    if let (Some(low), Some(high)) = (low, high) {
        if low > high {
            return Err(AgentError::invalid_argument(format!("the {name} range is invalid: the start is after the end")));
        }
    }
    Ok(())
}

/// Build the shared `SearchQuery` the search routes compose, from the agent's request
/// shape. Every value is checked here, so a query that reaches the datastore has the
/// types the index expects.
async fn build_search_query(
    user: &CurrentUser,
    permitted: &PermissionSet,
    collectionnames: &[String],
    query_string: &str,
    filters: &AgentSearchFilters,
    sort: SortSpec,
) -> Result<SearchQuery, AgentError> {
    validate_plain_text(query_string)?;
    if filters.date_confirmed_only == Some(true) {
        return Err(AgentError::invalid_argument(
            "date_confirmed_only is not a website filter: a date range already excludes documents with no date, and date_unknown_only selects them",
        ));
    }
    refuse_reversed_range("date", filters.date_after, filters.date_before)?;
    refuse_reversed_range("mentioned date", filters.mentioned_date_after, filters.mentioned_date_before)?;
    refuse_reversed_range("size", filters.size_min, filters.size_max)?;
    for (name, values) in &filters.facet_filters {
        validate_plain_text(name)?;
        search_facet(name)?;
        for value in values {
            validate_plain_text(value)?;
        }
    }
    let selected: Vec<String> = if collectionnames.is_empty() {
        match permitted {
            PermissionSet::All => list_permitted_collections(user).await.map_err(AgentError::from_anyhow)?,
            PermissionSet::Some(names) => names.iter().cloned().collect(),
        }
    } else {
        collectionnames.to_vec()
    };
    let tree = list_datasets::list_permitted_collection_tree(user).await.map_err(AgentError::from_anyhow)?;
    let mut datasets = Vec::new();
    for name in &selected {
        require_collection(permitted, name)?;
        datasets.extend(tree.iter().filter(|node| node.collectionname == *name).flat_map(|node| node.datasets.iter()));
    }
    if datasets.is_empty() {
        return Err(AgentError::permission_denied("no selected dataset is readable"));
    }
    if let Some(wanted) = filters.facet_filters.get("collection_dataset") {
        datasets.retain(|dataset| {
            wanted.iter().any(|name| *name == dataset.collection_dataset || *name == dataset.dataset_name)
        });
        if datasets.is_empty() {
            return Err(AgentError::permission_denied("the dataset facet is outside the selected collections"));
        }
    }
    let mut query = SearchQuery { query_string: query_string.to_string(), sort, ..Default::default() };
    query.facet_filters.insert(
        "collection_dataset".to_string(),
        datasets.iter().map(|dataset| FacetOriginalValue::String(dataset.collection_dataset.clone())).collect(),
    );
    for (facet, values) in &filters.facet_filters {
        if facet == "collection_dataset" {
            continue;
        }
        let mut ids = std::collections::BTreeSet::new();
        for value in values {
            let id = value.trim().parse::<u64>().map_err(|_| {
                AgentError::invalid_argument(format!(
                    "the facet {facet:?} takes term ids, and {value:?} is not one; search_facet_values lists the ids"
                ))
            })?;
            ids.insert(FacetOriginalValue::Int(id));
        }
        query.facet_filters.insert(facet.clone(), ids);
    }
    if filters.filename_only.unwrap_or(false) {
        // The file names of a document are one pages row with this `extracted_by`.
        query.facet_filters.insert(
            "extracted_by".to_string(),
            [FacetOriginalValue::String(FILENAME_INDEX_EXTRACTED_BY.to_string())].into_iter().collect(),
        );
    }
    if let Some(term_id) = filters.folder_term_id {
        query
            .facet_filters
            .entry("file_paths".to_string())
            .or_default()
            .insert(FacetOriginalValue::Int(term_id));
    }
    let unknown = filters.date_unknown_only.unwrap_or(false);
    if filters.date_after.is_some() || filters.date_before.is_some() || unknown {
        query.range_filters.insert(
            "dates".to_string(),
            RangeFilter { min: filters.date_after, max: filters.date_before, include_unknown: unknown },
        );
    }
    if filters.mentioned_date_after.is_some() || filters.mentioned_date_before.is_some() {
        query.range_filters.insert(
            "mentioned_dates".to_string(),
            RangeFilter { min: filters.mentioned_date_after, max: filters.mentioned_date_before, include_unknown: false },
        );
    }
    if filters.size_min.is_some() || filters.size_max.is_some() {
        query.range_filters.insert(
            "file_size_bytes".to_string(),
            RangeFilter { min: filters.size_min, max: filters.size_max, include_unknown: false },
        );
    }
    Ok(query)
}

/// Flatten decomposed highlight spans into one plain-text snippet, wrapping a matched
/// run in `**…**` so a reader, human or model, can still see what matched without the
/// server's own `<hoover4_strong>` marker leaking into a tool result.
fn spans_to_snippet(spans: &[common::text_highlight::HighlightTextSpan]) -> String {
    let mut out = String::new();
    for span in spans {
        if span.is_highlighted {
            out.push_str("**");
            out.push_str(&span.text);
            out.push_str("**");
        } else {
            out.push_str(&span.text);
        }
    }
    out
}

/// The searched collections and their fingerprint, compared with `expected_source`
/// before any page is read.
async fn search_source(
    user: &CurrentUser,
    query: &SearchQuery,
    expected: Option<&str>,
) -> Result<(Vec<String>, String), AgentError> {
    let collections = fanout::permitted_search_collections(user, query).await.map_err(AgentError::from_anyhow)?;
    let source = collection_source_fingerprint(&collections).await?;
    verify_expected_source(expected, &source)?;
    Ok((collections, source))
}

/// The counts of every facet in [`SEARCH_FACETS`] for one query, read at once. The
/// second value is true when a shard could not be read for some facet.
async fn search_facet_counts(
    user: &CurrentUser,
    query: &SearchQuery,
) -> Result<(BTreeMap<String, Vec<AgentFacetCount>>, bool), AgentError> {
    let reads = SEARCH_FACETS.iter().map(|(field, terms)| async move {
        let facets = search_string_facet(user, query.clone(), field.to_string(), terms.map(str::to_string), None)
            .await
            .map_err(AgentError::from_anyhow)?;
        Ok::<_, AgentError>((*field, facets))
    });
    let selected_datasets = query.facet_filters.get("collection_dataset");
    let mut counts = BTreeMap::new();
    let mut partial = false;
    for (field, facets) in futures::future::try_join_all(reads).await? {
        partial |= facets.partial;
        let values = facets
            .facet_values
            .into_iter()
            .filter_map(|item| match &item.original_value {
                FacetOriginalValue::String(value) if field == "collection_dataset" => selected_datasets
                    .is_none_or(|selected| selected.contains(&FacetOriginalValue::String(value.clone())))
                    .then(|| AgentFacetCount { value: item.display_string.clone(), id: None, count: item.count }),
                FacetOriginalValue::String(_) => {
                    Some(AgentFacetCount { value: item.display_string.clone(), id: None, count: item.count })
                }
                FacetOriginalValue::Int(id) => {
                    Some(AgentFacetCount { value: item.display_string.clone(), id: Some(*id), count: item.count })
                }
            })
            .collect::<Vec<_>>();
        // An empty list tells the reader nothing and fills a page ahead of the rows.
        if !values.is_empty() {
            counts.insert(field.to_string(), values);
        }
    }
    Ok((counts, partial))
}

/// The repairs that the full-text match builder applies to `query`, for example `OR`
/// read as `|`. The search itself builds the match in `search_sql::match_argument`,
/// which escapes every `@` first, so the same escape runs here and the notes describe
/// the query that ran. An empty query is a browse and has no notes.
fn query_notes(query: &str) -> Vec<String> {
    let query = query.trim().replace('@', "\\@");
    if query.is_empty() {
        return Vec::new();
    }
    crate::db_utils::manticore_match::prepare_match_query(&query).map(|p| p.repairs).unwrap_or_default()
}

pub async fn search_results(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<SearchResultsRequest>,
) -> AgentResult<SearchResultsResponse> {
    Deadline::start().run(search_results_body(&user, &headers, body)).await.map(Json)
}

async fn search_results_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: SearchResultsRequest,
) -> Result<SearchResultsResponse, AgentError> {
    let page = match &body.position {
        None => 0,
        Some(AgentPosition::Page { page }) => u64::from(*page),
        Some(other) => return Err(wrong_position_kind("search/results", other, "Page")),
    };
    if page >= MAX_SEARCH_PAGES {
        return Err(AgentError::invalid_argument(format!(
            "page {page} is past the website's limit of {} results; pages 0 to {} exist, so narrow the query or the filters",
            common::search_const::MAX_PAGINATION_DOCUMENT_LIMIT,
            MAX_SEARCH_PAGES - 1
        )));
    }
    let header = requested_collections_header(headers);
    let permitted = permitted_collectionnames(user, &header).await?;
    let sort = sort_spec_from_agent(body.sort.as_ref())?;
    let query = build_search_query(user, &permitted, &body.collectionname, &body.query, &body.filters, sort).await?;
    let (_, source) = search_source(user, &query, body.expected_source.as_deref()).await?;

    let (results, hit_count, (facet_counts, facets_partial)) = tokio::try_join!(
        async { search_for_results(user, query.clone(), page).await.map_err(AgentError::from_anyhow) },
        async { search_for_results_hit_count(user, query.clone()).await.map_err(AgentError::from_anyhow) },
        search_facet_counts(user, &query),
    )?;

    // collection_dataset -> (collectionname, dataset_name), for the two fields the
    // per-result item wants and `search_for_results` does not carry itself.
    let tree = list_datasets::list_permitted_collection_tree(user).await.map_err(AgentError::from_anyhow)?;
    let mut lookup: HashMap<String, (String, String)> = HashMap::new();
    for node in &tree {
        for dataset in &node.datasets {
            lookup.insert(dataset.collection_dataset.clone(), (node.collectionname.clone(), dataset.dataset_name.clone()));
        }
    }

    let paths = futures::future::join_all(
        results.results.iter().map(|item| vfs_api::get_first_vfs_path(user, item.document_identifier())),
    )
    .await;
    let mut documents = Vec::with_capacity(results.results.len());
    for (item, path) in results.results.iter().zip(paths) {
        let (collectionname, dataset) = lookup
            .get(&item.collection_dataset)
            .cloned()
            .unwrap_or_else(|| (item.collection_dataset.clone(), String::new()));
        documents.push(AgentSearchDocument {
            collectionname,
            file_hash: item.file_hash.clone(),
            path: path.map(|d| d.path).unwrap_or_default(),
            title: item.title.clone(),
            snippet: spans_to_snippet(&item.highlight_text_spans),
            canonical_file_type: item.file_type.clone(),
            size: item.file_size_bytes,
            document_date: item.document_date,
            dataset,
            collection_dataset: item.collection_dataset.clone(),
        });
    }

    let next_position = (results.next_hash.is_some() && page + 1 < MAX_SEARCH_PAGES)
        .then(|| AgentPosition::Page { page: (page + 1) as u32 });
    Ok(SearchResultsResponse {
        documents,
        total_count: hit_count.total,
        facet_counts,
        page,
        has_more: next_position.is_some(),
        query_notes: query_notes(&body.query),
        page_info: AgentPageInfo {
            source,
            next_position,
            total: Some(hit_count.total),
            partial: results.partial || hit_count.partial || facets_partial,
        },
    })
}

// ===================================================================================
// search/facet_values
// ===================================================================================

pub async fn search_facet_values(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<SearchFacetValuesRequest>,
) -> AgentResult<SearchFacetValuesResponse> {
    Deadline::start().run(search_facet_values_body(&user, &headers, body)).await.map(Json)
}

/// With a needle and a term dictionary, the dictionary search finds the terms, and one
/// facet read counts them. Without a dictionary, such as `file_types`, or without a
/// needle, the facet read lists the values with the most documents, and the needle
/// filters their text.
async fn search_facet_values_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: SearchFacetValuesRequest,
) -> Result<SearchFacetValuesResponse, AgentError> {
    if body.facet == "collection_dataset" {
        return Err(AgentError::invalid_argument(
            "collection_dataset values are dataset names, and collections/list lists them",
        ));
    }
    let term_field = search_facet(&body.facet)?;
    let needle = body.query.as_ref().map(|q| q.trim().to_string()).filter(|q| !q.is_empty());
    if let Some(needle) = &needle {
        validate_plain_text(needle)?;
    }
    let header = requested_collections_header(headers);
    let permitted = permitted_collectionnames(user, &header).await?;
    let query = build_search_query(
        user, &permitted, &body.collectionname, "", &AgentSearchFilters::default(), SortSpec::default(),
    )
    .await?;
    let (collections, source) = search_source(user, &query, None).await?;

    let terms: Vec<AgentFacetTerm> = match (&needle, term_field_for_column(&body.facet).ok()) {
        (Some(needle), Some(_)) => {
            let hits = search_entity_terms(user, query.clone(), needle.clone(), vec![body.facet.clone()])
                .await
                .map_err(AgentError::from_anyhow)?;
            let ids: Vec<u64> = hits.hits.iter().map(|hit| hit.term_id).collect();
            let counted = search_string_facet(user, query.clone(), body.facet.clone(), term_field.map(str::to_string), Some(ids))
                .await
                .map_err(AgentError::from_anyhow)?;
            let counts: HashMap<u64, u64> = counted
                .facet_values
                .into_iter()
                .filter_map(|item| match item.original_value {
                    FacetOriginalValue::Int(id) => Some((id, item.count)),
                    FacetOriginalValue::String(_) => None,
                })
                .collect();
            hits.hits
                .into_iter()
                .map(|hit| AgentFacetTerm { id: hit.term_id, text: hit.term_display, count: Some(*counts.get(&hit.term_id).unwrap_or(&0)) })
                .collect()
        }
        (needle, _) => {
            let needle = needle.as_ref().map(|n| n.to_lowercase());
            let facets = search_string_facet(user, query.clone(), body.facet.clone(), term_field.map(str::to_string), None)
                .await
                .map_err(AgentError::from_anyhow)?;
            facets
                .facet_values
                .into_iter()
                .filter(|item| needle.as_ref().is_none_or(|n| item.display_string.to_lowercase().contains(n)))
                .filter_map(|item| match item.original_value {
                    FacetOriginalValue::Int(id) => Some(AgentFacetTerm { id, text: item.display_string, count: Some(item.count) }),
                    FacetOriginalValue::String(_) => None,
                })
                .collect()
        }
    };

    let mut resolved = BTreeMap::new();
    if let (Some(ids), Some(field)) = (body.ids.filter(|ids| !ids.is_empty()), term_field) {
        let values = fetch_db_terms_for_ints(&collections, ids, field.to_string())
            .await
            .map_err(AgentError::from_anyhow)?;
        for (id, text) in values {
            resolved.insert(id.to_string(), text);
        }
    }
    Ok(SearchFacetValuesResponse { terms, resolved, source })
}

// ===================================================================================
// search/histogram
// ===================================================================================

pub async fn search_date_histogram_handler(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<SearchDateHistogramRequest>,
) -> AgentResult<SearchDateHistogramResponse> {
    Deadline::start().run(search_histogram_body(&user, &headers, body)).await.map(Json)
}

/// `date` and `mentioned_date` read the website's date histograms. `size` reads the four
/// file-size buckets of the filter modal.
async fn search_histogram_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: SearchDateHistogramRequest,
) -> Result<SearchDateHistogramResponse, AgentError> {
    if !matches!(body.date_field.as_str(), "date" | "mentioned_date" | "size") {
        return Err(AgentError::invalid_argument("the histogram field is date, mentioned_date or size"));
    }
    let header = requested_collections_header(headers);
    let permitted = permitted_collectionnames(user, &header).await?;
    let query =
        build_search_query(user, &permitted, &body.collectionname, &body.query, &body.filters, SortSpec::default()).await?;
    let (_, source) = search_source(user, &query, None).await?;

    let buckets = match body.date_field.as_str() {
        "size" => search_numeric_facet(user, query.clone())
            .await
            .map_err(AgentError::from_anyhow)?
            .facet_values
            .into_iter()
            .filter_map(|item| match item.original_value {
                FacetOriginalValue::Int(index) => {
                    let (start, end) = size_bucket_range(index as usize);
                    Some(AgentHistogramBucket {
                        start: start.unwrap_or(0),
                        end,
                        count: item.count,
                        label: Some(item.display_string),
                    })
                }
                FacetOriginalValue::String(_) => None,
            })
            .collect(),
        field => {
            let histogram = if field == "mentioned_date" {
                search_mentioned_date_histogram(user, query.clone()).await.map_err(AgentError::from_anyhow)?
            } else {
                date_histogram::search_date_histogram(user, query.clone()).await.map_err(AgentError::from_anyhow)?
            };
            histogram
                .buckets
                .into_iter()
                .map(|b| AgentHistogramBucket { start: b.start, end: Some(b.end), count: b.count, label: None })
                .collect()
        }
    };
    Ok(SearchDateHistogramResponse { buckets, date_field: body.date_field, source })
}

// ===================================================================================
// search/entity_explainer
// ===================================================================================

pub async fn search_entity_explainer(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<SearchEntityExplainerRequest>,
) -> AgentResult<SearchEntityExplainerResponse> {
    let deadline = Deadline::start();
    deadline.run(search_entity_explainer_body(&user, &headers, body, deadline)).await.map(Json)
}

async fn search_entity_explainer_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: SearchEntityExplainerRequest,
    deadline: Deadline,
) -> Result<SearchEntityExplainerResponse, AgentError> {
    let header = requested_collections_header(headers);
    let permitted = permitted_collectionnames(user, &header).await?;
    require_collection(&permitted, &body.collectionname)?;
    validate_plain_text(&body.entity_type)?;

    let explanation = explain_entity(user, body.entity_type.clone(), body.entity_value.clone(), None)
        .await
        .map_err(AgentError::from_anyhow)?
        .map(|card| AgentEntityExplanation {
            title: card.title,
            subtitle: card.subtitle,
            body: card.body,
            facts: card.facts.into_iter().map(|f| AgentEntityFact { label: f.label, value: f.value }).collect(),
            references: card
                .references
                .into_iter()
                .map(|r| AgentEntityLink { title: r.title, url: r.url, note: r.note })
                .collect(),
        });

    let source = collection_source_fingerprint(std::slice::from_ref(&body.collectionname)).await?;
    let tree = list_datasets::list_permitted_collection_tree(user).await.map_err(AgentError::from_anyhow)?;
    let mut documents = Vec::new();
    for dataset in tree.iter().filter(|entry| entry.collectionname == body.collectionname)
        .flat_map(|entry| entry.datasets.iter()) {
        let rows: Vec<(String, String)> = deadline.collection_client(&body.collectionname)
            .query("SELECT file_hash, any(surface_text) FROM (SELECT file_hash, entity_rule_ids, entity_value_json, entity_texts FROM regex_entity_hit FINAL WHERE collection_dataset = ? AND (file_hash, rule_set_version) IN (SELECT file_hash, max(rule_set_version) FROM regex_entity_hit FINAL WHERE collection_dataset = ? GROUP BY file_hash)) ARRAY JOIN entity_rule_ids AS rule_id, entity_value_json AS value_json, entity_texts AS surface_text WHERE rule_id = ? AND value_json = ? GROUP BY file_hash ORDER BY file_hash LIMIT 20")
            .bind(&dataset.collection_dataset)
            .bind(&dataset.collection_dataset)
            .bind(&body.entity_type)
            .bind(&body.entity_value)
            .fetch_all()
            .await
            .map_err(AgentError::from_clickhouse)?;
        for (file_hash, snippet) in rows {
            let identifier = DocumentIdentifier { collection_dataset: dataset.collection_dataset.clone(), file_hash: file_hash.clone() };
            let path = vfs_api::get_first_vfs_path(user, identifier).await
                .map(|p| p.path)
                .unwrap_or_default();
            let title = path.rsplit('/').next().unwrap_or(&path).to_string();
            documents.push(AgentEntityDocument { file_hash, path, title, snippet });
        }
    }
    Ok(SearchEntityExplainerResponse { explanation, documents, source })
}
