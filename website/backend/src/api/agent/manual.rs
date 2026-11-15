//! The routes `manual/search` and `manual/read`: the sections of the manuals of `/docs`
//! (`api::manual`). The administration manual answers only an administrator caller, as its
//! page does, in a chat of an administrator group (`item_access::run_manual_reader`), so a
//! member who is not an administrator cannot read it through the chat of an administrator. Every section result holds the link that opens it on the manual page.

use common::manual::{ADMIN_MANUAL, ADMIN_MANUAL_PATH, USER_MANUAL, USER_MANUAL_PATH};

use super::*;
use crate::api::manual::{self as manuals, ManualRefusal};

fn refusal(refusal: ManualRefusal) -> AgentError {
    match refusal {
        ManualRefusal::NotAdmin => {
            AgentError::permission_denied("only an administrator reads the administration manual")
        }
        ManualRefusal::Missing(error) => {
            AgentError::new(StatusCode::SERVICE_UNAVAILABLE, "backend_unavailable", format!("the manual is not loaded: {error}"))
        }
    }
}

pub async fn manual_search(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<ManualSearchRequest>,
) -> AgentResult<ManualSearchResponse> {
    let group = crate::auth::item_access::run_group(&user, &headers).await.map_err(AgentError::from_anyhow)?;
    let reader = crate::auth::item_access::run_manual_reader(&user, &group);
    manual_search_body(manuals::load(), &reader, &body).map(Json)
}

fn manual_search_body(
    loaded: &manuals::Manuals,
    user: &CurrentUser,
    body: &ManualSearchRequest,
) -> Result<ManualSearchResponse, AgentError> {
    validate_plain_text(&body.query)?;
    if body.query.trim().is_empty() {
        return Err(AgentError::invalid_argument("give the words to search for"));
    }
    let mut list = vec![manuals::manual_for(loaded, user, false).map_err(refusal)?];
    if user.is_admin {
        list.push(manuals::manual_for(loaded, user, true).map_err(refusal)?);
    }
    Ok(ManualSearchResponse { sections: manuals::search(&list, &body.query) })
}

pub async fn manual_read(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<ManualReadRequest>,
) -> AgentResult<ManualReadResponse> {
    let group = crate::auth::item_access::run_group(&user, &headers).await.map_err(AgentError::from_anyhow)?;
    let reader = crate::auth::item_access::run_manual_reader(&user, &group);
    manual_read_body(manuals::load(), &reader, &body).map(Json)
}

/// The manual and the anchor of a request. The section can be an anchor or a link of the
/// manual page, such as `/docs/admin#datasets`.
fn requested_section(body: &ManualReadRequest) -> Result<(bool, String), AgentError> {
    let mut admin = match body.manual.trim() {
        "" | USER_MANUAL => false,
        ADMIN_MANUAL => true,
        other => {
            return Err(AgentError::invalid_argument(format!(
                "manual is {USER_MANUAL} or {ADMIN_MANUAL}, not {other}"
            )));
        }
    };
    let section = body.section.trim();
    let (path, anchor) = match section.split_once('#') {
        Some((path, anchor)) => (path, anchor),
        None if section.starts_with('/') || section.contains("://") => (section, ""),
        None => ("", section),
    };
    if !path.is_empty() {
        let path = path.split_once("://").map_or(path, |(_, rest)| rest.find('/').map_or("", |i| &rest[i..]));
        match path.trim_end_matches('/') {
            ADMIN_MANUAL_PATH => admin = true,
            USER_MANUAL_PATH => admin = false,
            _ => return Err(AgentError::invalid_argument("the link is not a link of the manual page /docs")),
        }
    }
    Ok((admin, anchor.to_string()))
}

fn manual_read_body(
    loaded: &manuals::Manuals,
    user: &CurrentUser,
    body: &ManualReadRequest,
) -> Result<ManualReadResponse, AgentError> {
    validate_plain_text(&body.section)?;
    let (admin, section) = requested_section(body)?;
    let manual = manuals::manual_for(loaded, user, admin).map_err(refusal)?;
    manual.read(&section).ok_or_else(|| {
        AgentError::not_found(format!(
            "the manual has no section {section}. Call search_manual, or read_manual with an empty section for the contents"
        ))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn loaded() -> manuals::Manuals {
        manuals::Manuals {
            user: Ok(manuals::Manual::parse("# User\n\n## 4. Search\n\nType a query in the search box.\n".into(), false)),
            admin: Ok(manuals::Manual::parse("# Admin\n\n## Datasets\n\nAdd a dataset to a collection.\n".into(), true)),
            dir: std::path::PathBuf::from("/x"),
        }
    }

    fn person(admin: bool) -> CurrentUser {
        CurrentUser { username: "u".into(), fullname: String::new(), email: String::new(), is_admin: admin, groups: vec![] }
    }

    fn read(section: &str, manual: &str, admin: bool) -> Result<ManualReadResponse, AgentError> {
        manual_read_body(&loaded(), &person(admin), &ManualReadRequest { section: section.into(), manual: manual.into() })
    }

    #[test]
    fn an_ordinary_user_gets_no_administration_manual() {
        let denied = read("datasets", "admin", false).err().unwrap();
        assert_eq!((denied.status, denied.error), (StatusCode::FORBIDDEN, "permission_denied"));
        assert_eq!(read("/docs/admin#datasets", "", false).err().unwrap().status, StatusCode::FORBIDDEN);
        assert_eq!(read("datasets", "admin", true).unwrap().link, "/docs/admin#datasets");
        // The search of an ordinary user leaves the administration manual out.
        let search = |admin: bool| {
            manual_search_body(&loaded(), &person(admin), &ManualSearchRequest { query: "dataset collection search".into() })
                .unwrap()
                .sections
                .into_iter()
                .map(|s| s.manual)
                .collect::<Vec<_>>()
        };
        assert!(!search(false).contains(&"admin".to_string()));
        assert!(search(true).contains(&"admin".to_string()));
    }

    #[test]
    fn a_section_can_be_an_anchor_or_a_page_link() {
        assert_eq!(read("4-search", "", false).unwrap().link, "/docs#4-search");
        assert_eq!(read("https://hoover.example.org/docs#4-search", "", false).unwrap().section, "4-search");
        assert_eq!(read("/docs", "user", false).unwrap().section, "");
        assert_eq!(read("missing", "", false).err().unwrap().status, StatusCode::NOT_FOUND);
        assert_eq!(read("x", "other", false).err().unwrap().status, StatusCode::BAD_REQUEST);
        assert_eq!(read("/search#x", "", false).err().unwrap().status, StatusCode::BAD_REQUEST);
    }
}
