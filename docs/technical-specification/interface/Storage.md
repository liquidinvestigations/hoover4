# Storage routes share folder controls.

The storage routes show readable collections, their datasets, and nested folder contents.
[The storage page](../../../website/frontend/src/pages/file_browser_page.rs) and [VFS APIs](../../../website/backend/src/api/vfs/) own the contract.
[The user procedure](../../user-manual/User_Manual.md#8-storage-browsing-by-folder) explains these tasks.

## Controls

| Control | Behavior | Constraint |
|---|---|---|
| Collection and dataset cards | Open the selected scope. | Counts come from stored dataset statistics. |
| Tree chevron | Expand or collapse children. | Expansion and label navigation are separate actions. |
| Folder label and breadcrumb | Open a folder, including a container member path. | Parent links preserve container boundaries. |
| Name search | Filter names below the current folder. | The control does not search document contents. |
| Open in Search | Open collection search with the current folder restriction. | The folder must resolve to its search identity. |
| File row | Select the document preview. | Document access applies to the preview request. |
| Dividers | Resize the sidebar or preview. | Double-click restores the default width. |

## States

| State | Display |
|---|---|
| Loading | The requested tree or folder waits for its data. |
| Empty scope | The scope contains no visible children. |
| Unavailable statistics | Counts remain unavailable until computed or read successfully. |
| Expanded tree | Child rows appear within the current window. |
| Selected file | The preview shows the selected document. |
| Request failure | The affected component displays the request error. |

## Constraints

**Files** counts nested archive members and email attachments for each path.
**Size** counts bytes at the current container level.
A container's members do not add their bytes again at its parent's level.
The tree windows large sibling groups and deep ancestor chains.
Every document read retains collection access checks.
