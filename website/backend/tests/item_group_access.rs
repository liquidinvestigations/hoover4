//! Verify shared item reads against a disposable, migrated database.

use axum::Extension;
use backend::{api::{agent, boards, chat}, auth::item_access, db_chat};
use backend::db_utils::clickhouse_utils::get_global_client;
use common::current_user::CurrentUser;
use serde_json::{json, Value};

fn user(name: &str) -> CurrentUser {
    CurrentUser {
        username: name.into(), fullname: String::new(), email: String::new(),
        is_admin: false, groups: Vec::new(),
    }
}

async fn post(base: &str, session: &str, route: &str, body: Value) -> anyhow::Result<(u16, Value)> {
    let response = reqwest::Client::new().post(format!("{base}/api/agent/v1/{route}"))
        .header(item_access::RUN_SESSION_HEADER, session).json(&body).send().await?;
    Ok((response.status().as_u16(), response.json().await?))
}

#[tokio::test]
#[ignore = "requires a disposable migrated database and HOOVER4_ITEM_ACCESS_FIXTURES=1"]
async fn members_read_shared_items_and_agent_runs_stay_in_their_group() -> anyhow::Result<()> {
    anyhow::ensure!(std::env::var("HOOVER4_ITEM_ACCESS_FIXTURES").as_deref() == Ok("1"),
                    "A disposable database is required.");
    let suffix = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?.as_nanos();
    let alice = user(&format!("alice-{suffix}"));
    let bob = user(&format!("bob-{suffix}"));
    let outsider = user(&format!("outsider-{suffix}"));
    let group_a = format!("team-a-{suffix}");
    let group_b = format!("team-b-{suffix}");
    let client = get_global_client();
    for (person, group) in [(&alice, &group_a), (&alice, &group_b), (&bob, &group_a), (&outsider, &group_b)] {
        client.query("INSERT INTO user_group_membership (username, groupname) VALUES (?, ?)")
            .bind(&person.username).bind(group).execute().await?;
    }
    let session_a = db_chat::create_session(&alice.username, &group_a, "Shared chat", &[]).await?;
    let session_b = db_chat::create_session(&alice.username, &group_b, "Other chat", &[]).await?;
    let board_a = format!("board-a-{suffix}");
    let board_b = format!("board-b-{suffix}");
    for (board, group) in [(&board_a, &group_a), (&board_b, &group_b)] {
        client.query("INSERT INTO boards (board_id, owner, owner_group, title, goal, created_at, updated_at) \
                      VALUES (?, ?, ?, 'Board', 'Goal', now64(3), now64(3))")
            .bind(board).bind(&alice.username).bind(group).execute().await?;
    }
    assert_eq!(chat::readable_session(&bob, &session_a).await?.username, alice.username);
    assert!(chat::readable_session(&outsider, &session_a).await.is_err());
    assert!(boards::board_snapshot(&bob, board_a.clone()).await.is_ok());
    assert!(boards::board_snapshot(&outsider, board_a.clone()).await.is_err());
    assert!(chat::delete_chat_session(&bob, session_a.clone()).await.is_err());
    assert!(db_chat::get_session_by_id(&session_a).await?.is_some());

    let listener = tokio::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0)).await?;
    let base = format!("http://{}", listener.local_addr()?);
    let server = tokio::spawn(async move {
        axum::serve(listener, agent::router().layer(Extension(alice))).await
    });
    for (route, field, own, other) in [
        ("chats/read", "session_id", &session_a, &session_b),
        ("boards/read", "board_id", &board_a, &board_b),
    ] {
        assert_eq!(post(&base, &session_a, route, json!({field: own})).await?.0, 200);
        assert_eq!(post(&base, &session_a, route, json!({field: other})).await?.0, 403);
        assert_eq!(post(&base, &session_a, route, json!({field: format!("missing-{suffix}")})).await?.0, 404);
        assert_eq!(post(&base, "", route, json!({field: own})).await?.0, 403);
    }
    for (route, key, field, own, other) in [
        ("chats/list", "chats", "session_id", &session_a, &session_b),
        ("boards/list", "boards", "board_id", &board_a, &board_b),
    ] {
        let (status, result) = post(&base, &session_a, route, json!({"ids": [own, other]})).await?;
        assert_eq!(status, 200);
        let rows = result[key].as_array().unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0][field], *own);
    }
    server.abort();
    for (caller, group, expected) in [(bob, &group_a, 200), (outsider, &group_b, 403)] {
        let run = db_chat::create_session(&caller.username, group, "Caller chat", &[]).await?;
        let listener = tokio::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0)).await?;
        let base = format!("http://{}", listener.local_addr()?);
        let server = tokio::spawn(async move {
            axum::serve(listener, agent::router().layer(Extension(caller))).await
        });
        assert_eq!(post(&base, &run, "chats/read", json!({"session_id": session_a})).await?.0, expected);
        assert_eq!(post(&base, &run, "boards/read", json!({"board_id": board_a})).await?.0, expected);
        server.abort();
    }
    Ok(())
}
