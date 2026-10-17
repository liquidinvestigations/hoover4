# Connected email shows a bounded message graph.

`UI-EmailGraphPage` displays the neighborhood of one center message and the selected document preview.
[The graph page](../../../website/frontend/src/pages/email_graph_page.rs), [shared types](../../../website/common/src/email_graph.rs), and [email API](../../../website/backend/src/api/documents/get_email_graph.rs) own this contract.

## Controls

| Control | Behavior | Constraint |
|---|---|---|
| Connected email link | Open the graph for the current email. | It uses that message as the graph center. |
| Message node | Select a message for the preview. | Selection changes preserve the center. |
| Document preview | Read the selected message and its stored sources. | Normal document access checks apply. |

## States

| State | Display |
|---|---|
| Loading | The graph request waits for its result. |
| Selected message | The selected node and the document preview identify the same message. |
| Unknown date | The dimmed message has no established send date. |
| Request failure | The graph pane displays the request error. |

## Constraints

The graph includes at most 50 nodes and traverses at most three relationship levels.
Horizontal placement orders known message dates within the rendered graph.
A message without a known date remains distinct from a message dated at the epoch.
The layout settles before display and retains surviving node positions across selection changes.
A graph limit can exclude a connected message.
[The user procedure](../../user-manual/User_Manual.md#read-connected-email) explains separate search when a message is outside the displayed neighborhood.
