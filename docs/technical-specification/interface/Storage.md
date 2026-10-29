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

## Upload routes

The website receives uploads into the upload dataset of a collection under `/_upload/`.
No page sends uploads yet. [The receiver](../../../website/backend/src/uploads/) and [the tus handlers](../../../website/backend/src/server_extra/tus.rs) own the contract.
Rows `F-store-10` to `F-store-13` of [the feature register](../Features.md) give the statuses of each refusal.

| Route | Behavior | Constraint |
|---|---|---|
| `GET /_upload/limits` | Return the limits and the upload targets of the caller. | A collection with two upload datasets is listed as a conflict without a target. |
| `POST /_upload/begin` | Check a manifest, reserve its paths and return the batch id and one tus address for each file. | The body is JSON of at most 16 MiB. No byte is accepted before these checks pass. |
| tus requests under `/_upload/files/` | Create, read the offset of, append to and end the transfer of one file. | Each request needs `Tus-Resumable: 1.0.0` and `X-Hoover-Upload: 1`. Only the batch owner may send it. |
| `GET /_upload/<batch_id>/prefix/<file_no>` | Return the SHA-256 of the acknowledged prefix. | Only the batch owner may read it. |
| `POST /_upload/<batch_id>/commit` | End the transfer and return the detail address `/uploads/<collection>/<batch_id>`. | The body is JSON. A repeat returns the same address. |

A transfer change needs the batch owner and a current upload target: the uploader membership,
the dataset setting and the writable mount. A removed permission stops new bytes and
placement. Files that are in the dataset folder stay. Another owner's batch is a `403`.
