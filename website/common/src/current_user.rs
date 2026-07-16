//! Current authenticated user identity.

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct CurrentUser {
    pub username: String,
    pub fullname: String,
    pub email: String,
    pub is_admin: bool,
    pub is_guest: bool,
    pub groups: Vec<String>,
}
