//! The email envelope and the connection graph around one message.
//!
//! Both read the tables P6's `build_email_graph` materialises. Neither traverses at
//! write cost: the envelope's `cluster_size` is one point lookup on `email_clusters`,
//! which is what makes the "Open Connected Emails" button affordable on every email
//! opened. The vast majority are in no cluster, and discovering that with a traversal
//! per opened message would be the expensive way to render nothing.
//!
//! The graph walk is bounded twice, by depth and by node count, and it carries a visited
//! set that is NOT optional: `eml-7-recursive` is an email that contains itself, so a
//! cycle in this graph is a fixture, not a hypothetical.

use std::collections::{HashMap, HashSet, VecDeque};

use common::current_user::CurrentUser;
use common::email_graph::{
    EmailAttachment, EmailEnvelope, EmailGraph, EmailGraphEdge, EmailGraphNode, EmailParty,
    EmailRelation, MAX_GRAPH_DEPTH, MAX_GRAPH_NODES,
};
use common::search_result::DocumentIdentifier;

use crate::auth::permissions;
use crate::db_utils::clickhouse_utils::{get_client_for_dataset, resolve_collection};

/// Everything the viewer draws above the message body, in one round trip.
pub async fn get_email_envelope(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Option<EmailEnvelope>> {
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
    let dataset = document_identifier.collection_dataset.clone();
    let hash = document_identifier.file_hash.clone();

    let headers: Vec<(String, i64, u8)> = client
        .query(
            "SELECT subject, toInt64(date_sent), date_sent_known FROM email_headers FINAL
             WHERE collection_dataset = ? AND email_hash = ? LIMIT 1",
        )
        .bind(&dataset)
        .bind(&hash)
        .fetch_all()
        .await?;
    let Some((subject, date_sent, date_sent_known)) = headers.into_iter().next() else {
        // Not an email. The viewer asks for every document it opens in the Email source,
        // so this is an answer, not an error.
        return Ok(None);
    };

    let participants: Vec<(String, String, String)> = client
        .query(
            // `toString(role)`: an Enum8 read as a raw value is its ORDINAL, and every
            // comparison against a role name is then silently false.
            "SELECT toString(role), address, display_name FROM email_addresses FINAL
             WHERE collection_dataset = ? AND email_hash = ?
             ORDER BY role, address",
        )
        .bind(&dataset)
        .bind(&hash)
        .fetch_all()
        .await?;

    let mut envelope = EmailEnvelope {
        subject,
        date_sent: (date_sent_known == 1).then_some(date_sent),
        ..Default::default()
    };
    for (role, address, display_name) in participants {
        let party = EmailParty { address, display_name };
        match role.as_str() {
            "from" => envelope.from.push(party),
            "cc" => envelope.cc.push(party),
            "bcc" => envelope.bcc.push(party),
            _ => envelope.to.push(party),
        }
    }

    // The attachment cards. `max(file_size_bytes)` because the same member can have
    // several rows and a card must not flicker between two sizes.
    let attachments: Vec<(String, u64, String)> = client
        .query(
            "SELECT path, toUInt64(max(file_size_bytes)), hash FROM vfs_files FINAL
             WHERE collection_dataset = ? AND container_hash = ?
             GROUP BY path, hash
             ORDER BY path",
        )
        .bind(&dataset)
        .bind(&hash)
        .fetch_all()
        .await?;
    // The icon label, in a second query rather than a correlated subquery:
    // `file_type_canonical` is a separate ReplacingMergeTree and joining it inside an
    // aggregate is how a missing row turns an attachment list into an empty one. It is
    // also the only table that holds ONE type per document. The per-detector
    // `file_types` rows disagree with each other by design, and picking one of them here
    // would give an attachment a different glyph from the one it has everywhere else.
    // A document with no row yet gets the generic glyph.
    let member_hashes: Vec<String> = attachments.iter().map(|(_, _, h)| h.clone()).collect();
    let coarse_types: Vec<(String, String)> = if member_hashes.is_empty() {
        Vec::new()
    } else {
        client
            .query(
                "SELECT hash, file_type FROM file_type_canonical FINAL
                 WHERE collection_dataset = ? AND hash IN ?",
            )
            .bind(&dataset)
            .bind(&member_hashes)
            .fetch_all()
            .await?
    };
    let coarse_by_hash: HashMap<String, String> = coarse_types.into_iter().collect();
    envelope.attachments = attachments
        .into_iter()
        .map(|(path, size_bytes, file_hash)| EmailAttachment {
            file_name: path.rsplit('/').next().unwrap_or(&path).to_string(),
            coarse_type: coarse_by_hash.get(&file_hash).cloned().unwrap_or_default(),
            size_bytes,
            document_identifier: DocumentIdentifier {
                collection_dataset: dataset.clone(),
                file_hash,
            },
        })
        .collect();

    // Never derived by splitting the dataset id: the mapping lives in the `dataset`
    // table and a dataset id is allowed to contain the separator.
    let collectionname = resolve_collection(&dataset).await?;
    let cluster: Vec<u32> = client
        .query(
            "SELECT cluster_size FROM email_clusters FINAL
             WHERE collectionname = ? AND collection_dataset = ? AND email_hash = ? LIMIT 1",
        )
        .bind(&collectionname)
        .bind(&dataset)
        .bind(&hash)
        .fetch_all()
        .await?;
    envelope.cluster_size = cluster.into_iter().next().unwrap_or(0);

    // The banner: one edge pointing AT this message. Exact edges first, then the highest
    // confidence, so an inferred parent is never shown while an RFC one exists.
    let parents: Vec<(String, String, String, f32)> = client
        .query(
            "SELECT src_dataset, src_hash, toString(kind), confidence FROM email_edges FINAL
             WHERE collectionname = ? AND dst_dataset = ? AND dst_hash = ?
               AND kind IN ('reply', 'forward', 'reference', 'attachment')
             ORDER BY confidence DESC, kind ASC LIMIT 1",
        )
        .bind(&collectionname)
        .bind(&dataset)
        .bind(&hash)
        .fetch_all()
        .await?;
    if let Some((src_dataset, src_hash, kind, confidence)) = parents.into_iter().next() {
        // The parent can be in another dataset (that is what an identity edge is), so
        // the permission check is redone for it and a refusal hides the banner.
        let parent_readable = permissions::assert_can_read(user, &src_dataset).await.is_ok();
        let parent_client = get_client_for_dataset(&src_dataset).await?;
        let rows: Vec<(String, i64, u8, String)> = if parent_readable {
            parent_client
                .query(
                    "SELECT h.subject, toInt64(h.date_sent), h.date_sent_known,
                            any(a.address)
                     FROM email_headers AS h FINAL
                     LEFT JOIN (SELECT email_hash, address FROM email_addresses FINAL
                                WHERE collection_dataset = ? AND toString(role) = 'from') AS a
                       ON h.email_hash = a.email_hash
                     WHERE h.collection_dataset = ? AND h.email_hash = ?
                     GROUP BY h.subject, h.date_sent, h.date_sent_known LIMIT 1",
                )
                .bind(&src_dataset)
                .bind(&src_dataset)
                .bind(&src_hash)
                .fetch_all()
                .await?
        } else {
            Vec::new()
        };
        if let Some((parent_subject, parent_date, parent_date_known, from_address)) =
            rows.into_iter().next()
        {
            envelope.parent = Some(EmailRelation {
                document_identifier: DocumentIdentifier {
                    collection_dataset: src_dataset,
                    file_hash: src_hash,
                },
                subject: parent_subject,
                from_display: from_address,
                date_sent: (parent_date_known == 1).then_some(parent_date),
                kind,
                confidence,
            });
        }
    }

    Ok(Some(envelope))
}

/// One row of `email_edges`, as read.
type EdgeRow = (String, String, String, String, String, f32, String);

/// Read permitted exact-hash message occurrences before grouping logical graph nodes.
/// Node and depth limits apply to logical messages. Occurrence expansion has a separate limit.
pub async fn get_email_graph(
    user: &CurrentUser,
    centre: DocumentIdentifier,
    max_nodes: u32,
    max_depth: u32,
) -> anyhow::Result<EmailGraph> {
    get_email_graph_scoped(user, centre, max_nodes, max_depth, None).await
}

/// Preserve a caller's collection scope while grouping its readable occurrences.
pub async fn get_email_graph_scoped(
    user: &CurrentUser, centre: DocumentIdentifier, max_nodes: u32, max_depth: u32,
    collection_scope: Option<&[String]>,
) -> anyhow::Result<EmailGraph> {
    permissions::assert_can_read(user, &centre.collection_dataset).await?;
    let centre_client = get_client_for_dataset(&centre.collection_dataset).await?;
    let live = centre_client.query("SELECT count() FROM vfs_files FINAL WHERE collection_dataset = ? AND hash = ? AND is_deleted = 0")
        .bind(&centre.collection_dataset).bind(&centre.file_hash).fetch_one::<u64>().await?;
    anyhow::ensure!(live > 0, "The selected email copy no longer exists.");
    let max_nodes = max_nodes.clamp(1, MAX_GRAPH_NODES) as usize;
    let max_depth = max_depth.clamp(1, MAX_GRAPH_DEPTH);
    let permitted = crate::api::list_datasets::list_permitted_datasets(user).await?;
    let mut collections: std::collections::BTreeMap<String, Vec<String>> = std::collections::BTreeMap::new();
    for dataset in permitted {
        if collection_scope.is_some_and(|scope| !scope.contains(&dataset.collectionname)) { continue; }
        collections.entry(dataset.collectionname).or_default().push(dataset.collection_dataset);
    }
    anyhow::ensure!(collections.values().any(|datasets| datasets.contains(&centre.collection_dataset)), "forbidden: no read access to graph collection scope");
    let collection_by_dataset: HashMap<String, String> = collections.iter().flat_map(|(collection, datasets)| datasets.iter().map(move |dataset| (dataset.clone(), collection.clone()))).collect();
    let mut queue = VecDeque::from([(centre.file_hash.clone(), 0)]);
    let mut visited = HashSet::from([centre.file_hash.clone()]);
    let mut nodes: Vec<EmailGraphNode> = Vec::new();
    let mut edges: Vec<EmailGraphEdge> = Vec::new();
    let mut occurrence_count = 0usize;
    let mut occurrences_truncated = false;
    let mut truncated = false;
    while let Some((hash, depth)) = queue.pop_front() {
        let mut occurrences = Vec::new();
        let mut metadata = HashMap::new();
        for (collection, datasets) in &collections {
            let client = crate::db_utils::clickhouse_utils::get_collection_client(collection);
            let remaining = common::email_graph::MAX_GRAPH_OCCURRENCES.saturating_sub(occurrence_count);
            let rows: Vec<(String, String, i64, u8)> = client.query(
                "SELECT collection_dataset, subject, toInt64(date_sent), date_sent_known
                 FROM email_headers FINAL WHERE collection_dataset IN ? AND email_hash = ?
                 AND (collection_dataset, email_hash) IN
                   (SELECT collection_dataset, hash FROM vfs_files FINAL WHERE hash = ? AND is_deleted = 0)
                 ORDER BY collection_dataset LIMIT ?"
            ).bind(datasets).bind(&hash).bind(&hash).bind((remaining + 1) as u64).fetch_all().await?;
            if rows.len() > remaining { occurrences_truncated = true; }
            for (dataset, subject, date, known) in rows.into_iter().take(remaining) {
                metadata.insert(dataset.clone(), (subject, date, known));
                occurrences.push(DocumentIdentifier { collection_dataset: dataset, file_hash: hash.clone() });
                occurrence_count += 1;
            }
        }
        // Keep the selected occurrence even when earlier aliases exhausted the bound.
        if hash == centre.file_hash && !occurrences.contains(&centre) {
            occurrences_truncated = true;
            let client = get_client_for_dataset(&centre.collection_dataset).await?;
            let rows: Vec<(String, i64, u8)> = client.query(
                "SELECT subject, toInt64(date_sent), date_sent_known FROM email_headers FINAL
                 WHERE collection_dataset = ? AND email_hash = ? LIMIT 1"
            ).bind(&centre.collection_dataset).bind(&hash).fetch_all().await?;
            if let Some(row) = rows.into_iter().next() {
                if occurrence_count == common::email_graph::MAX_GRAPH_OCCURRENCES {
                    occurrences.pop();
                    occurrence_count -= 1;
                }
                metadata.insert(centre.collection_dataset.clone(), row);
                occurrences.push(centre.clone());
                occurrence_count += 1;
            }
        }
        occurrences.sort_by(|a, b| a.collection_dataset.cmp(&b.collection_dataset));
        occurrences.dedup();
        let representative = if hash == centre.file_hash { occurrences.iter().find(|o| **o == centre) } else { occurrences.first() };
        let Some(representative) = representative.cloned() else { continue };
        let (subject, date_sent, known) = metadata.remove(&representative.collection_dataset).unwrap();
        let mut node_truncated = depth >= max_depth;
        if depth < max_depth {
            for (collection, datasets) in &collections {
                let aliases: Vec<String> = occurrences.iter().filter(|occurrence| collection_by_dataset.get(&occurrence.collection_dataset) == Some(collection)).map(|occurrence| occurrence.collection_dataset.clone()).collect();
                if aliases.is_empty() { continue; }
                let client = crate::db_utils::clickhouse_utils::get_collection_client(collection);
                let limit = max_nodes * 4;
                let rows: Vec<EdgeRow> = client.query(
                    "SELECT src_dataset, src_hash, dst_dataset, dst_hash, toString(kind), confidence, evidence
                     FROM email_edges FINAL WHERE collectionname = ?
                     AND src_dataset IN ? AND dst_dataset IN ?
                     AND ((src_hash = ? AND src_dataset IN ?) OR (dst_hash = ? AND dst_dataset IN ?))
                     ORDER BY confidence DESC, kind, src_hash, dst_hash LIMIT ?"
                ).bind(collection).bind(datasets).bind(datasets).bind(&hash).bind(&aliases).bind(&hash).bind(&aliases)
                    .bind((limit + 1) as u64).fetch_all().await?;
                if rows.len() > limit { node_truncated = true; }
                let keys: Vec<(String, String)> = rows.iter().flat_map(|row| [(row.0.clone(), row.1.clone()), (row.2.clone(), row.3.clone())]).collect();
                let live: HashSet<(String, String)> = if keys.is_empty() { HashSet::new() } else {
                    client.query("SELECT DISTINCT collection_dataset, hash FROM vfs_files FINAL WHERE (collection_dataset, hash) IN ? AND is_deleted = 0")
                        .bind(&keys).fetch_all::<(String, String)>().await?.into_iter().collect()
                };
                for (src_dataset, src_hash, dst_dataset, dst_hash, kind, confidence, evidence) in rows.into_iter().take(limit) {
                    if !live.contains(&(src_dataset.clone(), src_hash.clone())) || !live.contains(&(dst_dataset.clone(), dst_hash.clone())) || (src_hash == dst_hash && kind == "identity") { continue; }
                    let other = if src_hash == hash { &dst_hash } else { &src_hash };
                    if !visited.contains(other) {
                        if visited.len() >= max_nodes { node_truncated = true; continue; }
                        visited.insert(other.clone());
                        queue.push_back((other.clone(), depth + 1));
                    }
                    edges.push(EmailGraphEdge {
                        src: DocumentIdentifier { collection_dataset: src_dataset, file_hash: src_hash },
                        dst: DocumentIdentifier { collection_dataset: dst_dataset, file_hash: dst_hash },
                        kind, confidence, evidence,
                    });
                }
            }
        }
        truncated |= node_truncated;
        nodes.push(EmailGraphNode {
            logical_id: hash.clone(),
            occurrences: occurrences.into_iter().map(|document_identifier| common::email_graph::EmailGraphOccurrence {
                collectionname: collection_by_dataset[&document_identifier.collection_dataset].clone(), document_identifier,
            }).collect(),
            document_identifier: representative,
            subject, from_display: String::new(), date_sent, date_sent_known: known == 1,
            truncated: node_truncated, is_centre: hash == centre.file_hash,
        });
    }
    let mut by_dataset: HashMap<String, Vec<String>> = HashMap::new();
    for node in &nodes {
        by_dataset.entry(node.document_identifier.collection_dataset.clone()).or_default()
            .push(node.document_identifier.file_hash.clone());
    }
    for (dataset, hashes) in by_dataset {
        let client = get_client_for_dataset(&dataset).await?;
        let senders: HashMap<String, String> = client.query(
            "SELECT email_hash, min(address) FROM email_addresses FINAL
             WHERE collection_dataset = ? AND email_hash IN ? AND toString(role) = 'from'
             GROUP BY email_hash"
        ).bind(&dataset).bind(&hashes).fetch_all::<(String, String)>().await?.into_iter().collect();
        for node in nodes.iter_mut().filter(|node| node.document_identifier.collection_dataset == dataset) {
            node.from_display = senders.get(&node.logical_id).cloned().unwrap_or_default();
        }
    }
    let representatives: HashMap<String, DocumentIdentifier> = nodes.iter().map(|node| (node.logical_id.clone(), node.document_identifier.clone())).collect();
    let mut grouped: std::collections::BTreeMap<(String, String, String), EmailGraphEdge> = std::collections::BTreeMap::new();
    for mut edge in edges {
        let (Some(src), Some(dst)) = (representatives.get(&edge.src.file_hash), representatives.get(&edge.dst.file_hash)) else { continue };
        edge.src = src.clone(); edge.dst = dst.clone();
        let key = (src.file_hash.clone(), dst.file_hash.clone(), edge.kind.clone());
        match grouped.get_mut(&key) {
            Some(previous) => {
                previous.confidence = previous.confidence.max(edge.confidence);
                if !previous.evidence.split('\n').any(|value| value == edge.evidence) {
                    previous.evidence.push('\n'); previous.evidence.push_str(&edge.evidence);
                }
            }
            None => { grouped.insert(key, edge); }
        }
    }
    nodes.sort_by(|a, b| (a.date_sent, &a.logical_id).cmp(&(b.date_sent, &b.logical_id)));
    // Stored component sizes count occurrences and cannot describe logical nodes.
    let cluster_size = nodes.len() as u32;
    Ok(EmailGraph { cluster_size_complete: !truncated && !occurrences_truncated, nodes, edges: grouped.into_values().collect(), cluster_size,
        truncated: truncated || occurrences_truncated, occurrences_truncated })
}
