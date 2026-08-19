//! The email envelope and the connection graph around one message.
//!
//! Both read the tables P6's `build_email_graph` materialises. Neither traverses at
//! write cost: the envelope's `cluster_size` is one point lookup on `email_clusters`,
//! which is what makes the "Open Connected Emails" button affordable on every email
//! opened — the vast majority are in no cluster, and discovering that with a traversal
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
    // The icon label, in a second query rather than a correlated subquery: `file_types`
    // is a separate ReplacingMergeTree and joining it inside an aggregate is how a
    // missing row turns an attachment list into an empty one.
    let member_hashes: Vec<String> = attachments.iter().map(|(_, _, h)| h.clone()).collect();
    let coarse_types: Vec<(String, String)> = if member_hashes.is_empty() {
        Vec::new()
    } else {
        client
            .query(
                "SELECT hash, arrayElement(file_types, 1) FROM file_types FINAL
                 WHERE collection_dataset = ? AND hash IN ? AND length(file_types) > 0",
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
        // The parent can be in another dataset — that is what an identity edge is — so
        // the permission check is redone for it and a refusal simply hides the banner.
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

/// A bounded neighbourhood of `centre`, breadth-first, both bounds clamped server-side.
///
/// Breadth-first rather than depth-first: with a 50-node budget on a component of
/// thousands, a depth-first walk spends the whole budget on one arm and the picture it
/// draws is a line, not a neighbourhood. The prompt's "depth-first order" is about
/// exhausting a cluster, and the budget makes that impossible either way — so the budget
/// is spent on the nodes NEAREST the centre, which is what a person opening the graph on
/// a message is asking for.
pub async fn get_email_graph(
    user: &CurrentUser,
    centre: DocumentIdentifier,
    max_nodes: u32,
    max_depth: u32,
) -> anyhow::Result<EmailGraph> {
    permissions::assert_can_read(user, &centre.collection_dataset).await?;
    let max_nodes = max_nodes.clamp(1, MAX_GRAPH_NODES) as usize;
    let max_depth = max_depth.clamp(1, MAX_GRAPH_DEPTH);
    let collectionname = resolve_collection(&centre.collection_dataset).await?;
    let client = get_client_for_dataset(&centre.collection_dataset).await?;

    let mut visited: HashSet<(String, String)> = HashSet::new();
    let mut kept_edges: Vec<EmailGraphEdge> = Vec::new();
    let mut seen_edges: HashSet<(String, String, String, String, String)> = HashSet::new();
    let mut queue: VecDeque<((String, String), u32)> = VecDeque::new();
    let centre_key = (centre.collection_dataset.clone(), centre.file_hash.clone());
    visited.insert(centre_key.clone());
    queue.push_back((centre_key.clone(), 0));
    let mut truncated = false;
    // Nodes whose expansion the budget refused. Recorded per node so the page can say
    // "there is more here" on the exact node it is true of.
    let mut truncated_nodes: HashSet<(String, String)> = HashSet::new();

    while let Some(((dataset, hash), depth)) = queue.pop_front() {
        if depth >= max_depth {
            // Not an error: the frontier of a depth-limited walk always has some.
            truncated_nodes.insert((dataset, hash));
            truncated = true;
            continue;
        }
        // Both directions in one query. Only one direction of an edge is stored and the
        // graph is undirected for traversal; the arrow the interface draws comes from
        // `kind`, not from which column a row happened to land in.
        let rows: Vec<EdgeRow> = client
            .query(
                "SELECT src_dataset, src_hash, dst_dataset, dst_hash, toString(kind),
                        confidence, evidence
                 FROM email_edges FINAL
                 WHERE collectionname = ?
                   AND ((src_dataset = ? AND src_hash = ?) OR (dst_dataset = ? AND dst_hash = ?))
                 ORDER BY confidence DESC, kind ASC, dst_hash ASC
                 LIMIT ?",
            )
            .bind(&collectionname)
            .bind(&dataset)
            .bind(&hash)
            .bind(&dataset)
            .bind(&hash)
            .bind(max_nodes as u64 * 4)
            .fetch_all()
            .await?;

        for (src_dataset, src_hash, dst_dataset, dst_hash, kind, confidence, evidence) in rows {
            let src = (src_dataset.clone(), src_hash.clone());
            let dst = (dst_dataset.clone(), dst_hash.clone());
            let other = if src == (dataset.clone(), hash.clone()) { dst.clone() } else { src.clone() };
            if !visited.contains(&other) {
                if visited.len() >= max_nodes {
                    truncated = true;
                    truncated_nodes.insert((dataset.clone(), hash.clone()));
                    continue;
                }
                visited.insert(other.clone());
                queue.push_back((other, depth + 1));
            }
            let edge_key =
                (src_dataset.clone(), src_hash.clone(), kind.clone(), dst_dataset.clone(), dst_hash.clone());
            if seen_edges.insert(edge_key) {
                kept_edges.push(EmailGraphEdge {
                    src: DocumentIdentifier { collection_dataset: src_dataset, file_hash: src_hash },
                    dst: DocumentIdentifier { collection_dataset: dst_dataset, file_hash: dst_hash },
                    kind,
                    confidence,
                    evidence,
                });
            }
        }
    }

    // Edges to nodes the budget refused are dropped: an edge with only one end drawn is
    // a line into nothing, and the node it came from already says it was truncated.
    kept_edges.retain(|edge| {
        visited.contains(&(edge.src.collection_dataset.clone(), edge.src.file_hash.clone()))
            && visited.contains(&(edge.dst.collection_dataset.clone(), edge.dst.file_hash.clone()))
    });

    // One metadata read per dataset present, not per node.
    let mut by_dataset: HashMap<String, Vec<String>> = HashMap::new();
    for (dataset, hash) in &visited {
        by_dataset.entry(dataset.clone()).or_default().push(hash.clone());
    }
    let mut nodes = Vec::with_capacity(visited.len());
    for (dataset, hashes) in by_dataset {
        // A dataset in the same collection the user cannot read must not leak a subject.
        if permissions::assert_can_read(user, &dataset).await.is_err() {
            continue;
        }
        let dataset_client = get_client_for_dataset(&dataset).await?;
        let rows: Vec<(String, String, i64, u8)> = dataset_client
            .query(
                "SELECT h.email_hash, h.subject, toInt64(h.date_sent), h.date_sent_known
                 FROM email_headers AS h FINAL
                 WHERE h.collection_dataset = ? AND h.email_hash IN ?",
            )
            .bind(&dataset)
            .bind(&hashes)
            .fetch_all()
            .await?;
        let senders: Vec<(String, String)> = dataset_client
            .query(
                "SELECT email_hash, any(address) FROM email_addresses FINAL
                 WHERE collection_dataset = ? AND email_hash IN ? AND toString(role) = 'from'
                 GROUP BY email_hash",
            )
            .bind(&dataset)
            .bind(&hashes)
            .fetch_all()
            .await?;
        let sender_by_hash: HashMap<String, String> = senders.into_iter().collect();
        for (email_hash, subject, date_sent, date_sent_known) in rows {
            let key = (dataset.clone(), email_hash.clone());
            nodes.push(EmailGraphNode {
                is_centre: key == centre_key,
                truncated: truncated_nodes.contains(&key),
                from_display: sender_by_hash.get(&email_hash).cloned().unwrap_or_default(),
                document_identifier: DocumentIdentifier {
                    collection_dataset: dataset.clone(),
                    file_hash: email_hash,
                },
                subject,
                date_sent,
                date_sent_known: date_sent_known == 1,
            });
        }
    }
    // Stable order: the simulation seeds new nodes from this list and a shuffled order
    // would make the same graph settle differently on every navigation.
    nodes.sort_by(|a, b| {
        (a.date_sent, &a.document_identifier.collection_dataset, &a.document_identifier.file_hash)
            .cmp(&(
                b.date_sent,
                &b.document_identifier.collection_dataset,
                &b.document_identifier.file_hash,
            ))
    });

    let cluster: Vec<u32> = client
        .query(
            "SELECT cluster_size FROM email_clusters FINAL
             WHERE collectionname = ? AND collection_dataset = ? AND email_hash = ? LIMIT 1",
        )
        .bind(&collectionname)
        .bind(&centre.collection_dataset)
        .bind(&centre.file_hash)
        .fetch_all()
        .await?;
    let cluster_size = cluster.into_iter().next().unwrap_or(nodes.len() as u32);

    Ok(EmailGraph {
        truncated: truncated || (cluster_size as usize) > nodes.len(),
        cluster_size,
        nodes,
        edges: kept_edges,
    })
}

