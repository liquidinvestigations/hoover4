# Hoover4 Frontend

The frontend is a Dioxus WASM application that provides the Hoover4 user interface. It uses server functions to call the backend APIs and shares types via the `common` crate.

## Structure

- `assets/` - Static assets and global styles.
- `src/main.rs` - Dioxus entry point and application launch configuration.
- `src/app.rs` - Application root component, layout, and router.
- `src/routes.rs` - Route definitions (search, document view, file browser, AI chat, admin).
- `src/pages/` - Page-level UI compositions (`ai_chat/`, `admin/`, search, …).
- `src/components/` - Reusable UI building blocks (`chat_components/`, `search_components/`, …).
- `src/api/` - Server functions that proxy to the backend crate.

## AI Chat routes

| Path | Component |
|---|---|
| `/ai_chat` | `AiChatPage` |
| `/ai_chat/history` | `AiChatHistoryPage` |
| `/ai_chat/c/:session_id/:selected_result_hash/:doc_viewer_state` | `AiChatSessionPage` |

Admin route stubs — registered, no body yet:

| Path | Component |
|---|---|
| `/admin/metrics` | `AdminMetricsPage` |
| `/admin/users/:username/llm` | `AdminUserLlmPage` |

See [`src/components/chat_components/README.md`](src/components/chat_components/README.md).

## Development

From this directory:

```bash
dx serve --platform web
```

Or rebuild the container: `main_services/start-docker.sh --build hoover4-website`.

## Navigation

-  [Go Back](../Readme.md)
