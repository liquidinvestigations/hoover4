//! Admin API server function wrappers.

use common::admin_types::*;
use dioxus::prelude::*;

#[cfg(feature = "server")]
use crate::api::error_util::to_server_fn_error;

macro_rules! admin_server_fn {
    ($name:ident, $backend_path:path, ($($arg:ident : $ty:ty),*)) => {
        #[server]
        pub async fn $name($($arg: $ty),*) -> Result<(), ServerFnError> {
            let user = crate::api::server_auth::extract_user().await?;
            $backend_path(&user, $($arg),*)
                .await
                .map_err(to_server_fn_error)
        }
    };
    ($name:ident, $backend_path:path, ($($arg:ident : $ty:ty),*) -> $ret:ty) => {
        #[server]
        pub async fn $name($($arg: $ty),*) -> Result<$ret, ServerFnError> {
            let user = crate::api::server_auth::extract_user().await?;
            $backend_path(&user, $($arg),*)
                .await
                .map_err(to_server_fn_error)
        }
    };
}

admin_server_fn!(admin_list_users, backend::api::admin::users::admin_list_users, () -> Vec<AdminUserItem>);
admin_server_fn!(admin_get_user, backend::api::admin::users::admin_get_user, (username: String) -> AdminUserDetail);
admin_server_fn!(admin_create_user, backend::api::admin::users::admin_create_user, (username: String, fullname: String, email: String, is_admin: bool));
admin_server_fn!(admin_update_user, backend::api::admin::users::admin_update_user, (username: String, fullname: String, email: String, is_admin: bool));
admin_server_fn!(admin_delete_user, backend::api::admin::users::admin_delete_user, (username: String));

admin_server_fn!(admin_list_groups, backend::api::admin::groups::admin_list_groups, () -> Vec<AdminGroupItem>);
admin_server_fn!(admin_get_group, backend::api::admin::groups::admin_get_group, (groupname: String) -> AdminGroupDetail);
admin_server_fn!(admin_create_group, backend::api::admin::groups::admin_create_group, (groupname: String, fullname: String));
admin_server_fn!(admin_update_group, backend::api::admin::groups::admin_update_group, (groupname: String, fullname: String));
admin_server_fn!(admin_delete_group, backend::api::admin::groups::admin_delete_group, (groupname: String));
admin_server_fn!(admin_add_member, backend::api::admin::groups::admin_add_member, (groupname: String, username: String, is_group_admin: bool));
admin_server_fn!(admin_remove_member, backend::api::admin::groups::admin_remove_member, (groupname: String, username: String));
admin_server_fn!(admin_set_group_admin, backend::api::admin::groups::admin_set_group_admin, (groupname: String, username: String, is_group_admin: bool));

admin_server_fn!(admin_list_collections, backend::api::admin::collections::admin_list_collections, () -> Vec<AdminCollectionItem>);
admin_server_fn!(admin_list_unassigned_datasets, backend::api::admin::collections::admin_list_unassigned_datasets, () -> Vec<String>);
admin_server_fn!(admin_get_collection, backend::api::admin::collections::admin_get_collection, (collectionname: String) -> AdminCollectionDetail);
admin_server_fn!(admin_create_collection, backend::api::admin::collections::admin_create_collection, (collectionname: String, fullname: String));
admin_server_fn!(admin_update_collection, backend::api::admin::collections::admin_update_collection, (collectionname: String, fullname: String));
admin_server_fn!(admin_delete_collection, backend::api::admin::collections::admin_delete_collection, (collectionname: String));
admin_server_fn!(admin_assign_dataset, backend::api::admin::collections::admin_assign_dataset, (collectionname: String, collection_dataset: String));
admin_server_fn!(admin_unassign_dataset, backend::api::admin::collections::admin_unassign_dataset, (collection_dataset: String));
admin_server_fn!(admin_grant_permission, backend::api::admin::collections::admin_grant_permission, (groupname: String, collectionname: String));
admin_server_fn!(admin_revoke_permission, backend::api::admin::collections::admin_revoke_permission, (groupname: String, collectionname: String));

admin_server_fn!(admin_get_dataset, backend::api::admin::datasets::admin_get_dataset, (collection_dataset: String) -> AdminDatasetDetail);
admin_server_fn!(admin_update_dataset, backend::api::admin::datasets::admin_update_dataset, (collection_dataset: String, dataset_name: String, collectionname: Option<String>));
admin_server_fn!(admin_delete_dataset, backend::api::admin::datasets::admin_delete_dataset, (collection_dataset: String));
admin_server_fn!(admin_trigger_workflow, backend::api::admin::datasets::admin_trigger_workflow, (collection_dataset: String, kind: String) -> String);

admin_server_fn!(admin_list_settings, backend::api::admin::settings::admin_list_settings, () -> Vec<ServerSettingItem>);
admin_server_fn!(admin_set_setting, backend::api::admin::settings::admin_set_setting, (key: String, value: String));

#[server]
pub async fn admin_dashboard_counts() -> Result<(u32, u32, u32, u32), ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    let users = backend::api::admin::users::admin_list_users(&user).await.map_err(to_server_fn_error)?;
    let groups = backend::api::admin::groups::admin_list_groups(&user).await.map_err(to_server_fn_error)?;
    let collections = backend::api::admin::collections::admin_list_collections(&user).await.map_err(to_server_fn_error)?;
    let datasets = backend::api::list_datasets::list_dataset_ids().await.map_err(to_server_fn_error)?;
    Ok((
        users.len() as u32,
        groups.len() as u32,
        collections.len() as u32,
        datasets.len() as u32,
    ))
}
