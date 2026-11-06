//! Read controlled automatic OCR publication states from the isolated browser fixtures.

use backend::api::admin::dataset_ocr::admin_get_dataset_ocr;
use common::current_user::CurrentUser;

#[tokio::test]
#[ignore = "requires the maintained isolated automatic browser fixture"]
async fn status_uses_latest_visible_states_without_resurrecting_internal_rows() {
    assert_eq!(std::env::var("HOOVER4_RELEASE_READER_FIXTURES").as_deref(), Ok("1"));
    let user = CurrentUser { username: "admin".into(), fullname: String::new(),
        email: String::new(), is_admin: true, groups: vec![] };
    let ordered = admin_get_dataset_ocr(&user, "release_browser_status_order".into()).await.unwrap().automatic_status;
    assert_eq!(ordered.states.len(), 1);
    assert_eq!((ordered.states[0].state.as_str(), ordered.states[0].files, ordered.states[0].pages), ("published", 1, 1));
    assert_eq!(ordered.capability_digests, ["current-status-order"]);
    assert_eq!(ordered.page_decisions.len(), 1);
    assert_eq!(ordered.page_decisions[0].pages, 1);
    let panel = admin_get_dataset_ocr(&user, "release_browser_primary".into()).await.unwrap();
    let status = panel.automatic_status;
    assert!(status.automatic);
    assert_eq!(status.policy_version, 1);
    assert_eq!(status.states.iter().map(|row| row.files).sum::<u64>(), 6);
    assert_eq!(status.states.iter().map(|row| row.pages).sum::<u64>(), 6);
    for state in ["applied", "published", "failed", "incomplete", "unsupported", "planned"] {
        assert!(status.states.iter().any(|row| row.state == state), "{state}");
    }
    assert_eq!(status.page_decisions.iter().map(|row| row.pages).sum::<u64>(), 6);
    assert!(!status.page_decisions.iter().any(|row| row.script == "InternalFixtureScript"));
    assert_eq!(status.capability_digests, ["browser-controlled-coverage"]);
    assert!(status.states.iter().any(|row| row.reason == "FixtureTransportFailure"));
}
