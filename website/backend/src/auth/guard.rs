//! Admin access guard helpers.

use common::current_user::CurrentUser;

pub fn require_admin(user: &CurrentUser) -> anyhow::Result<()> {
    if user.is_admin {
        Ok(())
    } else {
        anyhow::bail!("forbidden")
    }
}

pub fn is_forbidden(err: &anyhow::Error) -> bool {
    err.to_string().contains("forbidden")
}
