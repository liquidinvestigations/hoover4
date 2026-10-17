# Interface inventory

Every route the site serves. The identifier is the route variant in
[website/frontend/src/routes.rs](../../../website/frontend/src/routes.rs), **character for character**. That is what makes a page
added, renamed or deleted in the code mechanically visible against this tree, and it is what
[website/tools/check-spec-drift.sh](../../../website/tools/check-spec-drift.sh) joins on.

| id | path | control table |
|---|---|---|
| `UI-HomePage` | `/` | - |
| `UI-SearchPage` | `/search/…` | [`Search.md`](Search.md) |
| `UI-SignalTermsPage` | `/red_flag_terms` | - |
| `UI-ViewDocumentPage` | `/view_document/…` | [`Document.md`](Document.md) |
| `UI-FileBrowserCollectionsPage` | `/file_browser` | [Storage.md](Storage.md) |
| `UI-FileBrowserCollectionPage` | `/file_browser/c/:collectionname` | [Storage.md](Storage.md) |
| `UI-FileBrowserPage` | `/file_browser/…` | [Storage.md](Storage.md) |
| `UI-EmailGraphPage` | `/email_graph/…` | [Connected_Email.md](Connected_Email.md) |
| `UI-AiChatPage` | `/ai_chat` | - |
| `UI-AiChatHistoryPage` | `/ai_chat/history` | - |
| `UI-AiBoardCreatePage` | `/ai_chat/boards/new` | - |
| `UI-AiBoardPage` | `/ai_chat/boards/:board_id?selected=&zoom=&assessment=` | [`Board.md`](Board.md) |
| `UI-AiChatSessionPage` | `/ai_chat/c/…` | [`Chat.md`](Chat.md) |
| `UI-AdminDashboardPage` | `/admin` | [Administration.md](Administration.md) |
| `UI-AdminCollectionsPage` | `/admin/collections` | [Administration.md](Administration.md) |
| `UI-AdminCollectionPage` | `/admin/collections/:collection_id` | [Administration.md](Administration.md) |
| `UI-AdminCollectionProcessingPage` | `/admin/collections/:collection_id/processing` | [Administration.md](Administration.md) |
| `UI-AdminDatasetPage` | `/admin/collections/:collection_id/datasets/:dataset_id` | [Administration.md](Administration.md) |
| `UI-AdminOperationsPage` | `/admin/operations` | [Administration.md](Administration.md) |
| `UI-AdminOperationDetailPage` | `/admin/operations/:op_id` | [Administration.md](Administration.md) |
| `UI-AdminFailuresPage` | `/admin/failures` | [Administration.md](Administration.md) |
| `UI-AdminFailureDetailPage` | `/admin/failures/:op_id` | [Administration.md](Administration.md) |
| `UI-AdminFeedbackPage` | `/admin/feedback` | [Administration.md](Administration.md) |
| `UI-AdminUsersPage` | `/admin/users` | [Administration.md](Administration.md) |
| `UI-AdminUserPage` | `/admin/users/:username` | [Administration.md](Administration.md) |
| `UI-AdminUserLlmPage` | `/admin/users/:username/llm` | [Administration.md](Administration.md) |
| `UI-AdminGroupsPage` | `/admin/user_groups` | [Administration.md](Administration.md) |
| `UI-AdminGroupPage` | `/admin/user_groups/:groupname` | [Administration.md](Administration.md) |
| `UI-AdminSettingsPage` | `/admin/settings` | [Administration.md](Administration.md) |
| `UI-AdminLlmPage` | `/admin/llm` | [Administration.md](Administration.md) |
| `UI-AdminAiStatusPage` | `/admin/ai_status` | [Administration.md](Administration.md) |
| `UI-AdminMetricsPage` | `/admin/metrics` | [Administration.md](Administration.md) |
| `UI-NotFoundPage` | anything else | - |

## Control tables describe selected interface contracts.

**A page's control table is written when, and only when, that page's browser acceptance walk
is written against it.** A table nobody walks is decoration: it cannot catch the one defect
nothing else catches (a control that renders and does nothing), and it goes stale in exactly
the way a control table is supposed to prevent.

So a dash in the third column means the route exists and its controls have not been
enumerated. It does not mean the page is unbuilt, and it is not a placeholder for a file that
is about to appear. [`Search.md`](Search.md) is the worked example of what one looks like, and
it is the shape the next one takes.

## Use the interface page format.

Three sections, always in this order:

- **Controls**, one row per control: its identifier, what it does, and, only where there is
  one, the constraint that is not apparent from the name.
- **States**. What the page shows in each state it can be in, including the failure states.
  Two empty results that need different reactions from the user are two states, not one.
- **Constraints**. What holds across the whole page.

Several routes may share one file where they share a shell and a control vocabulary; a route
is **never** split across files, and a file stays under roughly two hundred lines. Past that
the split is by route.
