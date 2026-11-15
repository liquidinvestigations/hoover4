//! The route `links/parse`: the reference of each Hoover link that a model copied.
//!
//! It applies the parser and the read rule of the chat input (`api::links`), limited to
//! the collections of the run: the `X-Hoover4-Collections` header and the `collections` of
//! the body, which the collection server takes from its caller ACL. A run without
//! collections reads no dataset item, and it still reads chats and boards by the group
//! rule. A link of any host is read by its path, because the website does not know the
//! address that the person used.

use super::*;

pub async fn links_parse(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<LinksParseRequest>,
) -> AgentResult<LinksParseResponse> {
    Deadline::start().run(links_parse_body(&user, &headers, body)).await.map(Json)
}

async fn links_parse_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: LinksParseRequest,
) -> Result<LinksParseResponse, AgentError> {
    if body.urls.is_empty() {
        return Err(AgentError::invalid_argument("give at least one link"));
    }
    if body.urls.len() > crate::api::links::MAX_REFERENCES {
        return Err(AgentError::invalid_argument(format!(
            "give at most {} links in one call",
            crate::api::links::MAX_REFERENCES
        )));
    }
    for url in &body.urls {
        validate_plain_text(url)?;
    }
    let header = requested_collections_header(headers);
    let mut only = match permitted_collectionnames(user, &header).await? {
        PermissionSet::All => None,
        PermissionSet::Some(names) => Some(names),
    };
    if let Some(run) = &body.collections {
        let run: std::collections::HashSet<String> = run.iter().cloned().collect();
        only = Some(match only {
            Some(names) => names.intersection(&run).cloned().collect(),
            None => run,
        });
    }
    let reader = crate::api::links::LinkReader::new(user, only.as_ref()).await.map_err(AgentError::from_anyhow)?;
    let mut links = Vec::with_capacity(body.urls.len());
    for url in body.urls {
        let (reference, error) = match reader.resolve(user, &url).await {
            Ok(reference) => (Some(reference), None),
            Err(error) => (None, Some(error)),
        };
        links.push(AgentLink { url, reference, error });
    }
    Ok(LinksParseResponse { links })
}
