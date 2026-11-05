//! Session identity and permitted storage share resources across the website.
//! Focus and visibility changes refresh identity and access.
//! Storage and permission edits invalidate the permitted tree.

use common::current_user::CurrentUser;
use common::storage_tree::CollectionNode;
use dioxus::prelude::*;

use crate::api::auth_api::whoami;

/// The shared identity request under [`SessionProvider`].
#[derive(Clone, Copy)]
pub struct SessionResource(pub Resource<Result<CurrentUser, ServerFnError>>);

/// The signed-in user, or `None` while the identity call is still in flight.
pub fn use_session_user() -> Option<CurrentUser> {
    let session = try_consume_context::<SessionResource>()?;
    let value = session.0.read();
    value.as_ref().and_then(|r| r.as_ref().ok()).cloned()
}

/// Provide shared identity and permitted storage resources.
///
/// Children render immediately; they do not wait for the identity to resolve, because
/// the backend has already refused the request if it carried none.
#[component]
pub fn SessionProvider(children: Element) -> Element {
    let mut session = use_resource(whoami);
    use_context_provider(|| SessionResource(session));
    let mut storage = use_resource(move || {
        let identity = session.read().clone();
        async move {
            match identity {
                Some(Ok(_)) => crate::api::storage_api::list_storage_tree().await,
                Some(Err(error)) => Err(error),
                None => Ok(Vec::new()),
            }
        }
    });
    use_context_provider(|| StorageResource(storage));
    use_future(move || async move {
        let mut events = document::eval(r#"
            const refresh = () => { if (!document.hidden) dioxus.send(true); };
            window.addEventListener('focus', refresh);
            document.addEventListener('visibilitychange', refresh);
        "#);
        while let Ok(true) = events.recv::<bool>().await {
            if matches!(*session.state().peek(), UseResourceState::Pending) { continue; }
            storage.clear();
            session.clear();
            session.restart();
        }
    });
    rsx! { {children} }
}

/// The permitted storage tree shares one request across the session.
#[derive(Clone, Copy)]
pub struct StorageResource(pub Resource<Result<Vec<CollectionNode>, ServerFnError>>);

/// Subscribe to the session storage request.
pub fn use_storage_tree() -> Resource<Result<Vec<CollectionNode>, ServerFnError>> {
    use_context::<StorageResource>().0
}

/// Clear old names and permissions before requesting the current tree.
pub fn invalidate_storage_tree() {
    if let Some(mut storage) = try_consume_context::<StorageResource>() {
        storage.0.clear();
        storage.0.restart();
    }
}

/// Resolve a collection name without changing its identifier.
pub fn collection_label(tree: &[CollectionNode], identifier: &str) -> String {
    tree.iter().find(|node| node.collectionname == identifier)
        .and_then(|node| node.display_name.as_deref()).filter(|name| !name.trim().is_empty())
        .unwrap_or(identifier).to_string()
}

/// Resolve a dataset name without changing its identifier.
pub fn dataset_label(tree: &[CollectionNode], identifier: &str) -> String {
    tree.iter().flat_map(|node| &node.datasets)
        .find(|dataset| dataset.collection_dataset == identifier)
        .map(|dataset| dataset.label()).unwrap_or(identifier).to_string()
}
