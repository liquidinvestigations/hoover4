# Interface inventory

Every route the site serves. The identifier is the route variant in
`website/frontend/src/routes.rs`, **character for character**. That is what makes a page
added, renamed or deleted in the code mechanically visible against this tree, and it is what
`website/tools/check-spec-drift.sh` joins on.

| id | path | control table |
|---|---|---|
| `UI-HomePage` | `/` | - |
| `UI-SearchPage` | `/search/…` | [`Search.md`](Search.md) |
| `UI-ViewDocumentPage` | `/view_document/…` | - |
| `UI-FileBrowserCollectionsPage` | `/file_browser` | - |
| `UI-FileBrowserCollectionPage` | `/file_browser/c/:collectionname` | - |
| `UI-FileBrowserPage` | `/file_browser/…` | - |
| `UI-EmailGraphPage` | `/email_graph/…` | - |
| `UI-AiChatPage` | `/ai_chat` | - |
| `UI-AiChatHistoryPage` | `/ai_chat/history` | - |
| `UI-AiChatSessionPage` | `/ai_chat/c/…` | - |
| `UI-AdminDashboardPage` | `/admin` | - |
| `UI-AdminCollectionsPage` | `/admin/collections` | - |
| `UI-AdminCollectionPage` | `/admin/collections/:collection_id` | - |
| `UI-AdminCollectionProcessingPage` | `/admin/collections/:collection_id/processing` | - |
| `UI-AdminDatasetPage` | `/admin/collections/:collection_id/datasets/:dataset_id` | - |
| `UI-AdminOperationsPage` | `/admin/operations` | - |
| `UI-AdminUsersPage` | `/admin/users` | - |
| `UI-AdminUserPage` | `/admin/users/:username` | - |
| `UI-AdminUserLlmPage` | `/admin/users/:username/llm` | - |
| `UI-AdminGroupsPage` | `/admin/user_groups` | - |
| `UI-AdminGroupPage` | `/admin/user_groups/:groupname` | - |
| `UI-AdminSettingsPage` | `/admin/settings` | - |
| `UI-AdminLlmPage` | `/admin/llm` | - |
| `UI-AdminAiStatusPage` | `/admin/ai_status` | - |
| `UI-AdminMetricsPage` | `/admin/metrics` | - |
| `UI-NotFoundPage` | anything else | - |

## Why most rows have no control table

**A page's control table is written when, and only when, that page's browser acceptance walk
is written against it.** A table nobody walks is decoration: it cannot catch the one defect
nothing else catches (a control that renders and does nothing), and it goes stale in exactly
the way a control table is supposed to prevent.

So a dash in the third column means the route exists and its controls have not been
enumerated. It does not mean the page is unbuilt, and it is not a placeholder for a file that
is about to appear. [`Search.md`](Search.md) is the worked example of what one looks like, and
it is the shape the next one takes.

## The shape of a page file

Three sections, always in this order:

- **Controls**, one row per control: its identifier, what it does, and, only where there is
  one, the constraint that is not obvious from the name.
- **States**. What the page shows in each state it can be in, including the failure states.
  Two empty results that need different reactions from the user are two states, not one.
- **Constraints**. What holds across the whole page.

Several routes may share one file where they share a shell and a control vocabulary; a route
is **never** split across files, and a file stays under roughly two hundred lines. Past that
the split is by route.
