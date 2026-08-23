# Hoover4 Frontend

The frontend is a Dioxus WASM application that provides the Hoover4 user interface. It uses server functions to call the backend APIs and shares types via the `common` crate.

## Structure

- `assets/` - Static assets and global styles.
- `src/main.rs` - Dioxus entry point and application launch configuration.
- `src/app.rs` - Application root component, layout, and router. The router sits inside
  `components/session_gate.rs`: no page renders until `whoami` has answered and the session
  cookie exists, because every other endpoint refuses a request without one. When the
  deployment issues no anonymous session, the gate renders *Sign-in required* as a page
  rather than raising it into the error boundary. A boundary presents the site as broken
  and offers a retry that cannot work.
- `src/routes.rs` - Route definitions (search, document view, file browser, AI chat, admin).
- `src/pages/` - Page-level UI compositions (`ai_chat/`, `admin/`, search, …).
- `src/components/` - Reusable UI building blocks (`chat_components/`, `search_components/`, …).
  `resizable_sidebar.rs` is the storage pane's drag handle and remembered width; it reads
  local storage and measures the layout scale, so it is the one component that needs
  `web-sys` beyond `Window`.
- `src/api/` - Server functions that proxy to the backend crate.

## The document viewer's right-hand tabs

`/view_document/…` ends with a `ViewerRightTabState` URL parameter naming one of three
tabs: `Entities`, `File Locations`, `Metadata`. **Declaration order in
`ViewerRightTabSelection` is the rendered order of the strip**, so moving a variant moves
the tab. The parameter is CBOR by variant NAME, so an old link keeps its meaning when a
variant is added in the middle.

`File Locations` is `doc_file_locations_panel.rs`: one full path per row. Containers
included, because a file inside a zip has no meaningful path without the archive, with a
button that opens the containing folder in the file browser (a new tab, hence `<a
target="_blank">` rather than `Link`) and a button that copies the path. These are
descriptions of a document rather than renderings of it, which is why neither this nor the
metadata panel is offered as a preview source in the source dropdown.

## The Collections filter is composed client-side

`collections_facet_pane.rs` groups the flat `collection_dataset` facet buckets into
collections using `list_storage_tree()`, sums the counts and sorts both levels
count-descending. **The filter the backend sees is unchanged**, still a flat set of
dataset ids.

Expanding a collection issues **no request**: the buckets and the collection → dataset map
are both in hand before the first row is drawn. Expansion state is a `Signal<BTreeSet>`
that only the rows read, each through a `Memo` of its own key, so opening one collection
re-renders that row rather than the pane. Anything else added to this pane should keep both
properties.

## AI Chat routes

| Path | Component |
|---|---|
| `/ai_chat` | `AiChatPage` |
| `/ai_chat/history` | `AiChatHistoryPage` |
| `/ai_chat/c/:session_id/:selected_result_hash/:doc_viewer_state` | `AiChatSessionPage` |

Admin route stubs, registered with no body yet:

| Path | Component |
|---|---|
| `/admin/metrics` | `AdminMetricsPage` |
| `/admin/users/:username/llm` | `AdminUserLlmPage` |

See [`src/components/chat_components/README.md`](src/components/chat_components/README.md).

## Hooks run unconditionally, and `dx check` is what proves it

Every `use_*` call must run on every render, in the same order, and never from inside a
closure. A `use_effect` placed inside `if let Some(x) = some_resource.read()…` is absent on
the first render and present on the second, which shifts every hook index after it and
traps the WebAssembly runtime: the page paints, and from then on nothing re-renders, no
event handler fires and `pushState` changes the URL while the view stays put. The debug
build says `Unable to retrieve the hook that was initialized at this index`; the release
build says only `RuntimeError: unreachable`, naming no file.

The fix is always the same shape. Hoist the hook above the conditional and put the
condition *inside* the closure, reading the resource there so the effect still re-runs when
it resolves:

```rust
use_effect(move || {
    if let Some(Ok(value)) = defaults_res.read().as_ref().cloned() { … }
});
```

`cargo check` cannot see any of this. `dx check --package frontend` names the exact line,
in about a second, and both `run-stack-tests.sh` and `development.sh` gate on it.

## Development

From this directory:

```bash
dx serve --platform web
```

Or rebuild the container: `main_services/start-docker.sh --build hoover4-website`.

## Navigation

-  [Go Back](../Readme.md)
