//! Query test over seeded `operation_failures` rows.
//!
//! Run with the stack up: `cargo test -p backend -- --ignored`. Needs ClickHouse on
//! `CLICKHOUSE_URL`. Skips when the `failcap_tiny3` capture is not present.

use backend::db_utils::clickhouse_utils::get_global_client;
use common::current_user::CurrentUser;
use common::failure_types::{FailureListFilter, FailureListSort};

fn admin_user() -> CurrentUser {
    CurrentUser {
        username: "integration-admin".to_string(),
        fullname: String::new(),
        email: String::new(),
        is_admin: true,
        groups: vec![],
    }
}

#[tokio::test]
#[ignore = "needs live stack"]
async fn operation_failures_filters_sort_and_page_two() {
    let counts = get_global_client()
        .query("SELECT count() FROM operation_failures WHERE collection_dataset = ?")
        .bind("failcap_tiny3")
        .fetch_all::<u64>()
        .await
        .unwrap_or_default();
    if counts.first().copied().unwrap_or(0) == 0 {
        eprintln!("[stack] skip: failcap_tiny3 has no operation_failures rows");
        return;
    }
    let user = admin_user();
    let sig_activity = "ActivityError|RuntimeError|/app/.venv/lib/python3.13/site-packages/temporalio/worker/_workflow_instance.py|run_activity";
    let sig_runtime = "RuntimeError|ApplicationFailure|/app/tasks/P3_parse_files/parse_text.py|extract_plaintext_chunks";
    let tiny3 = FailureListFilter {
        collectionname: "failcap".into(),
        collection_dataset: "failcap_tiny3".into(),
        ..FailureListFilter::default()
    };
    let sort_sig_asc = FailureListSort {
        column: "signature".into(),
        descending: false,
    };
    let sort_sig_desc = FailureListSort {
        column: "signature".into(),
        descending: true,
    };

    let page = backend::api::admin::failures::admin_list_operation_failures(
        &user,
        tiny3.clone(),
        sort_sig_asc.clone(),
        25,
        0,
    )
    .await
    .unwrap();
    assert_eq!(
        page.groups.len(),
        2,
        "tiny3 has two signatures: {:?}",
        page.groups
    );
    assert!(!page.has_more);
    assert_eq!(page.groups[0].signature, sig_activity);
    assert_eq!(page.groups[1].signature, sig_runtime);
    assert_eq!(page.groups[0].failure_count, 1);
    assert_eq!(page.groups[1].failure_count, 1);

    let desc = backend::api::admin::failures::admin_list_operation_failures(
        &user,
        tiny3.clone(),
        sort_sig_desc,
        25,
        0,
    )
    .await
    .unwrap();
    assert_eq!(desc.groups[0].signature, sig_runtime);
    assert_eq!(desc.groups[1].signature, sig_activity);

    let page1 = backend::api::admin::failures::admin_list_operation_failures(
        &user,
        tiny3.clone(),
        sort_sig_asc.clone(),
        1,
        0,
    )
    .await
    .unwrap();
    assert_eq!(page1.groups.len(), 1);
    assert!(page1.has_more);
    assert_eq!(page1.groups[0].signature, sig_activity);

    let page2 = backend::api::admin::failures::admin_list_operation_failures(
        &user,
        tiny3.clone(),
        sort_sig_asc.clone(),
        1,
        1,
    )
    .await
    .unwrap();
    assert_eq!(page2.groups.len(), 1);
    assert!(!page2.has_more);
    assert_eq!(page2.groups[0].signature, sig_runtime);

    let mut none = tiny3.clone();
    none.collectionname = "no_such_collection".into();
    let empty = backend::api::admin::failures::admin_list_operation_failures(
        &user,
        none,
        sort_sig_asc.clone(),
        25,
        0,
    )
    .await
    .unwrap();
    assert!(
        empty.groups.is_empty(),
        "a missing collection is zero groups, not a zero count"
    );

    let mut by_task = tiny3.clone();
    by_task.task_name = "ParseSingleFile".into();
    let tasks = backend::api::admin::failures::admin_list_operation_failures(
        &user,
        by_task,
        sort_sig_asc.clone(),
        25,
        0,
    )
    .await
    .unwrap();
    assert_eq!(tasks.groups.len(), 1);
    assert_eq!(tasks.groups[0].signature, sig_activity);
    assert_eq!(tasks.groups[0].task_name, "ParseSingleFile");

    let mut by_class = tiny3.clone();
    by_class.error_class = "RuntimeError".into();
    let classes = backend::api::admin::failures::admin_list_operation_failures(
        &user,
        by_class,
        sort_sig_asc.clone(),
        25,
        0,
    )
    .await
    .unwrap();
    assert_eq!(classes.groups.len(), 1);
    assert_eq!(classes.groups[0].error_class, "RuntimeError");
    assert_eq!(classes.groups[0].signature, sig_runtime);

    let mut by_kind = tiny3.clone();
    by_kind.operation_kind = "add_dataset".into();
    let kinds = backend::api::admin::failures::admin_list_operation_failures(
        &user,
        by_kind,
        sort_sig_asc.clone(),
        25,
        0,
    )
    .await
    .unwrap();
    assert_eq!(
        kinds.groups.len(),
        2,
        "add_dataset is the tiny3 operation: {:?}",
        kinds.groups
    );

    let mut wrong_kind = tiny3.clone();
    wrong_kind.operation_kind = "purge_dataset".into();
    let no_kind = backend::api::admin::failures::admin_list_operation_failures(
        &user,
        wrong_kind,
        sort_sig_asc.clone(),
        25,
        0,
    )
    .await
    .unwrap();
    assert!(no_kind.groups.is_empty());

    let mut by_day = tiny3.clone();
    by_day.captured_from = "2026-09-11".into();
    by_day.captured_to = "2026-09-11".into();
    let on_day = backend::api::admin::failures::admin_list_operation_failures(
        &user,
        by_day,
        sort_sig_asc.clone(),
        25,
        0,
    )
    .await
    .unwrap();
    assert_eq!(on_day.groups.len(), 2);

    let mut other_day = tiny3.clone();
    other_day.captured_from = "2020-01-01".into();
    other_day.captured_to = "2020-01-01".into();
    let off_day = backend::api::admin::failures::admin_list_operation_failures(
        &user,
        other_day,
        sort_sig_asc,
        25,
        0,
    )
    .await
    .unwrap();
    assert!(off_day.groups.is_empty());
}

#[tokio::test]
#[ignore = "needs live stack"]
async fn operation_failures_scrubbed_copy_elides_long_stacks() {
    let counts = get_global_client()
        .query("SELECT count() FROM operation_failures WHERE op_id = ?")
        .bind("add_dataset-failcap_tiny3-1789137444")
        .fetch_all::<u64>()
        .await
        .unwrap_or_default();
    if counts.first().copied().unwrap_or(0) == 0 {
        eprintln!("[stack] skip: seeded op_id has no operation_failures rows");
        return;
    }
    let tree = backend::api::admin::failures::admin_get_failure_tree(
        &admin_user(),
        "add_dataset-failcap_tiny3-1789137444".to_string(),
    )
    .await
    .unwrap();
    assert_eq!(tree.nodes.len(), 2);
    assert!(tree.nodes.iter().all(|n| n.parent_index == -1));
    assert!(
        tree.scrubbed_copy.contains("[elided"),
        "long stacks must be elided in the scrubbed copy"
    );
    println!("SCRUBBED_COPY_BEGIN");
    println!("{}", tree.scrubbed_copy);
    println!("SCRUBBED_COPY_END");
}
