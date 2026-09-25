//! The folder routes: `folders/overview`, `folders/list` and `folders/search`.

use super::*;

// ===================================================================================
// folders/overview
// ===================================================================================

pub async fn folders_overview(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<FoldersOverviewRequest>,
) -> AgentResult<FoldersOverviewResponse> {
    let deadline = Deadline::start();
    deadline.run(folders_overview_body(&user, &headers, body, deadline)).await.map(Json)
}

async fn folders_overview_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: FoldersOverviewRequest,
    deadline: Deadline,
) -> Result<FoldersOverviewResponse, AgentError> {
    let header = requested_collections_header(headers);
    let permitted = permitted_collectionnames(user, &header).await?;
    require_collection(&permitted, &body.collectionname)?;
    if let Some(dataset) = &body.dataset {
        require_collection_dataset(user, &permitted, &body.collectionname, dataset).await?;
    }

    let overview = list_datasets::collection_overview(user, body.collectionname.clone())
        .await
        .map_err(AgentError::from_anyhow)?;

    let selected: Vec<&common::storage_tree::DatasetSummary> = overview
        .datasets
        .iter()
        .filter(|d| body.dataset.as_ref().is_none_or(|wanted| *wanted == d.dataset_name || *wanted == d.collection_dataset))
        .collect();
    let aggregates: Vec<&common::storage_tree::DatasetAggregates> =
        selected.iter().filter_map(|d| overview.aggregates_for(&d.collection_dataset)).collect();
    let datasets: Vec<AgentDatasetSummary> = selected
        .iter()
        .map(|d| AgentDatasetSummary {
            name: d.dataset_name.clone(),
            document_count: overview.aggregates_for(&d.collection_dataset).map(|a| a.document_count).unwrap_or(0),
        })
        .collect();
    let total_bytes = aggregates.iter().map(|a| a.total_size_bytes).sum();
    let indexed_count = aggregates.iter().map(|a| a.indexed_count).sum();
    let error_count = aggregates.iter().map(|a| a.error_count).sum();
    let file_count = datasets.iter().map(|d| d.document_count).sum();

    let mut folder_count = 0;
    let mut sources = Vec::new();
    for dataset in &selected {
        let count: u64 = deadline
            .collection_client(&body.collectionname)
            .query("SELECT countIf(kind != 'file') FROM vfs_nodes FINAL WHERE collection_dataset = ?")
            .bind(&dataset.collection_dataset)
            .fetch_one()
            .await
            .map_err(AgentError::from_clickhouse)?;
        folder_count += count;
        sources.push(folder_source_fingerprint(&deadline, &body.collectionname, &dataset.collection_dataset).await?);
    }
    Ok(FoldersOverviewResponse {
        datasets,
        folder_count,
        file_count,
        total_bytes,
        indexed_count,
        error_count,
        source: sources.join("|"),
    })
}

// ===================================================================================
// folders/list
// ===================================================================================

const FOLDER_PAGE_SIZE: u64 = 200;

/// Refuses a node key that names no node of the dataset with 404 `not_found`. Without
/// this check, a listing of an unknown key is an empty success.
async fn require_node(
    deadline: &Deadline,
    collectionname: &str,
    collection_dataset: &str,
    node_key: &str,
) -> Result<(), AgentError> {
    if node_key == dataset_root_key(collection_dataset) {
        return Ok(());
    }
    let count: u64 = deadline
        .collection_client(collectionname)
        .query("SELECT count() FROM vfs_nodes FINAL WHERE collection_dataset = ? AND node_key = ?")
        .bind(collection_dataset)
        .bind(node_key)
        .fetch_one()
        .await
        .map_err(AgentError::from_clickhouse)?;
    if count == 0 {
        return Err(AgentError::not_found(format!(
            "the dataset has no node {node_key:?}. folders/list gives the node ids of a folder"
        )));
    }
    Ok(())
}

fn node_kind_str(kind: common::vfs::VfsNodeKind) -> &'static str {
    match kind {
        common::vfs::VfsNodeKind::Dir => "dir",
        common::vfs::VfsNodeKind::File => "file",
        common::vfs::VfsNodeKind::Container => "container",
    }
}

pub async fn folders_list(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<FoldersListRequest>,
) -> AgentResult<FoldersListResponse> {
    let deadline = Deadline::start();
    deadline.run(folders_list_body(&user, &headers, body, deadline)).await.map(Json)
}

/// A `NodeKey` position continues after that child, in the order of the website's own
/// listing.
async fn folders_list_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: FoldersListRequest,
    deadline: Deadline,
) -> Result<FoldersListResponse, AgentError> {
    let node_id = body.node_id.as_deref().map(node_key_argument).transpose()?;
    if let Some(other) = body.position.as_ref().filter(|p| !matches!(p, AgentPosition::NodeKey { .. })) {
        return Err(wrong_position_kind("folders/list", other, "NodeKey"));
    }
    let header = requested_collections_header(headers);
    let permitted = permitted_collectionnames(user, &header).await?;
    let dataset = require_collection_dataset(user, &permitted, &body.collectionname, &body.dataset).await?;
    let collection_dataset = dataset.collection_dataset.clone();

    let source = folder_source_fingerprint(&deadline, &body.collectionname, &collection_dataset).await?;
    verify_expected_source(body.expected_source.as_deref(), &source)?;

    let node_key = node_id.unwrap_or_else(|| dataset_root_key(&collection_dataset));
    require_node(&deadline, &body.collectionname, &collection_dataset, &node_key).await?;

    let breadcrumb = vfs_api::vfs_tree_path_to(user, collection_dataset.clone(), node_key.clone())
        .await
        .map_err(AgentError::from_anyhow)?
        .into_iter()
        .map(|n| {
            let name = n.display_name().to_string();
            AgentBreadcrumbNode { node_id: n.node_key, name }
        })
        .collect();

    // One row past the page tells whether another page exists.
    let mut children_page = match &body.position {
        Some(AgentPosition::NodeKey { node_key: after }) => {
            let after = node_key_argument(after)?;
            vfs_api::vfs_tree_children_after(user, collection_dataset.clone(), node_key.clone(), after, FOLDER_PAGE_SIZE + 1)
                .await
                .map_err(AgentError::from_anyhow)?
        }
        _ => vfs_api::vfs_tree_children(
            user,
            collection_dataset.clone(),
            node_key.clone(),
            FOLDER_PAGE_SIZE + 1,
            0,
            false,
        )
        .await
        .map_err(AgentError::from_anyhow)?,
    };
    let more = children_page.nodes.len() as u64 > FOLDER_PAGE_SIZE;
    children_page.nodes.truncate(FOLDER_PAGE_SIZE as usize);
    let next_position = more
        .then(|| children_page.nodes.last().map(|n| AgentPosition::NodeKey { node_key: n.node_key.clone() }))
        .flatten();

    let node_keys: Vec<String> = children_page.nodes.iter().map(|n| n.node_key.clone()).collect();
    let term_ids = vfs_api::tree::node_term_ids(&collection_dataset, &node_keys).await.unwrap_or_default();
    let child_counts: HashMap<String, u64> = deadline.collection_client(&body.collectionname)
        .query("SELECT parent_key, count() FROM vfs_nodes FINAL WHERE collection_dataset = ? AND parent_key IN (?) GROUP BY parent_key")
        .bind(&collection_dataset)
        .bind(&node_keys)
        .fetch_all::<(String, u64)>()
        .await
        .map_err(AgentError::from_clickhouse)?
        .into_iter()
        .collect();
    let file_hashes: Vec<String> = children_page.nodes.iter()
        .filter(|n| n.kind != common::vfs::VfsNodeKind::Dir)
        .map(|n| n.file_hash.clone())
        .collect();
    let file_types: HashMap<String, String> = deadline.collection_client(&body.collectionname)
        .query("SELECT hash, file_type FROM file_type_canonical FINAL WHERE collection_dataset = ? AND hash IN (?)")
        .bind(&collection_dataset)
        .bind(&file_hashes)
        .fetch_all::<(String, String)>()
        .await
        .map_err(AgentError::from_clickhouse)?
        .into_iter()
        .collect();
    let file_dates: HashMap<String, i64> = deadline.collection_client(&body.collectionname)
        .query("SELECT hash, min(date) FROM document_dates FINAL WHERE collection_dataset = ? AND hash IN (?) GROUP BY hash")
        .bind(&collection_dataset)
        .bind(&file_hashes)
        .fetch_all::<(String, i64)>()
        .await
        .map_err(AgentError::from_clickhouse)?
        .into_iter()
        .collect();

    let total = children_page.total;
    let mut children = Vec::new();
    let mut files = Vec::new();
    for node in children_page.nodes {
        let term_id = term_ids.get(&node.node_key).copied();
        if node.kind != common::vfs::VfsNodeKind::Dir {
            files.push(AgentFolderFile {
                node_id: node.node_key.clone(),
                file_hash: node.file_hash.clone(),
                name: node.display_name().to_string(),
                size: node.file_size_bytes,
                date: file_dates.get(&node.file_hash).copied(),
                canonical_file_type: file_types.get(&node.file_hash).cloned(),
                is_container: node.kind == common::vfs::VfsNodeKind::Container,
                term_id,
            });
        }
        if node.kind != common::vfs::VfsNodeKind::File {
            children.push(AgentFolderChild {
                node_id: node.node_key.clone(),
                name: node.display_name().to_string(),
                kind: node_kind_str(node.kind).to_string(),
                child_count: Some(*child_counts.get(&node.node_key).unwrap_or(&0)),
                term_id,
            });
        }
    }

    let container_root = if node_key.contains('\u{1f}') && !node_key.ends_with('\u{1f}') {
        let parts: Vec<&str> = node_key.split('\u{1f}').collect();
        let container_hash = parts.get(1).copied().unwrap_or("");
        if !container_hash.is_empty() {
            vfs_api::vfs_tree_container_node(user, collection_dataset.clone(), container_hash.to_string())
                .await
                .ok()
                .flatten()
                .map(|n| n.node_key)
        } else {
            None
        }
    } else {
        None
    };

    Ok(FoldersListResponse {
        breadcrumb,
        container_root,
        children,
        files,
        dataset: dataset.short_name,
        page_info: AgentPageInfo { source, next_position, total: Some(total), partial: false },
    })
}

// ===================================================================================
// folders/search
// ===================================================================================

/// Sets how many matches one `folders/search` page returns.
const FOLDER_SEARCH_PAGE_SIZE: u64 = 500;

pub async fn folders_search(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<FoldersSearchRequest>,
) -> AgentResult<FoldersSearchResponse> {
    let deadline = Deadline::start();
    deadline.run(folders_search_body(&user, &headers, body, deadline)).await.map(Json)
}

/// Pages of 500 matches with an `Offset` position, up to the 2,000 matches that
/// `vfs_search_in_folder` reaches. Past that cap there is no position, and `partial`
/// says so.
async fn folders_search_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: FoldersSearchRequest,
    deadline: Deadline,
) -> Result<FoldersSearchResponse, AgentError> {
    validate_plain_text(&body.query)?;
    let node_id = body.node_id.as_deref().map(node_key_argument).transpose()?;
    let cap = vfs_api::tree::MAX_CHILDREN_PER_PAGE;
    let offset = match &body.position {
        None => 0,
        Some(AgentPosition::Offset { offset }) if offset % FOLDER_SEARCH_PAGE_SIZE == 0 && *offset < cap => *offset,
        Some(AgentPosition::Offset { .. }) => {
            return Err(AgentError::invalid_argument(format!(
                "a folder search offset is a multiple of {FOLDER_SEARCH_PAGE_SIZE} below {cap}"
            )));
        }
        Some(other) => return Err(wrong_position_kind("folders/search", other, "Offset")),
    };
    let header = requested_collections_header(headers);
    let permitted = permitted_collectionnames(user, &header).await?;
    let dataset = require_collection_dataset(user, &permitted, &body.collectionname, &body.dataset).await?;
    let collection_dataset = dataset.collection_dataset.clone();
    let source = folder_source_fingerprint(&deadline, &body.collectionname, &collection_dataset).await?;
    verify_expected_source(body.expected_source.as_deref(), &source)?;

    let node_key = node_id.unwrap_or_else(|| dataset_root_key(&collection_dataset));
    require_node(&deadline, &body.collectionname, &collection_dataset, &node_key).await?;
    let results = vfs_api::vfs_search_in_folder(
        user,
        collection_dataset.clone(),
        node_key,
        body.query,
        FOLDER_SEARCH_PAGE_SIZE,
        offset,
    )
    .await
    .map_err(AgentError::from_anyhow)?;

    let node_keys: Vec<String> = results.nodes.iter().map(|n| n.node_key.clone()).collect();
    let term_ids = vfs_api::tree::node_term_ids(&collection_dataset, &node_keys).await.unwrap_or_default();
    let reached = offset + results.nodes.len() as u64;
    let next_position = (reached < results.total.min(cap) && !results.nodes.is_empty())
        .then_some(AgentPosition::Offset { offset: reached });
    let total = results.total;

    let matches = results
        .nodes
        .into_iter()
        .map(|n| AgentFolderMatch {
            node_id: n.node_key.clone(),
            parent_id: n.parent_key.clone(),
            name: n.display_name().to_string(),
            kind: node_kind_str(n.kind).to_string(),
            path: n.path.clone(),
            term_id: term_ids.get(&n.node_key).copied(),
        })
        .collect();

    Ok(FoldersSearchResponse {
        matches,
        dataset: dataset.short_name,
        page_info: AgentPageInfo { source, next_position, total: Some(total), partial: total > cap },
    })
}
