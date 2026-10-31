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
| Upload | Open the upload page. Inside a folder of an upload dataset of the reader, it opens at that folder. | It shows only for a reader with an upload target. |

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
The upload pages below send them. [The receiver](../../../website/backend/src/uploads/) and [the tus handlers](../../../website/backend/src/server_extra/tus.rs) own the contract.
Rows `F-store-10` to `F-store-13` of [the feature register](../Features.md) give the statuses of each refusal.

| Route | Behavior | Constraint |
|---|---|---|
| `GET /_upload/limits` | Return the limits and the upload targets of the caller. | A collection with two upload datasets is listed as a conflict without a target. |
| `POST /_upload/begin` | Check a manifest, reserve its paths and return the batch id and one tus address for each file. | The body is JSON of at most 16 MiB. No byte is accepted before these checks pass. It is refused while a deletion or a purge of the upload dataset is live. |
| tus requests under `/_upload/files/` | Create, read the offset of, append to and end the transfer of one file. | Each request needs `Tus-Resumable: 1.0.0` and `X-Hoover-Upload: 1`. Only the batch owner may send it. |
| `GET /_upload/<batch_id>/prefix/<file_no>` | Return the SHA-256 of the acknowledged prefix. | Only the batch owner may read it. |
| `POST /_upload/<batch_id>/commit` | End the transfer and return the detail address `/uploads/<collection>/<batch_id>`. | The body is JSON. A repeat returns the same address. |

A transfer change needs the batch owner and a current upload target: the uploader membership,
the dataset setting and the writable mount. A removed permission stops new bytes and
placement. Files that are in the dataset folder stay. Another owner's batch is a `403`.

## Upload pages

[The upload pages](../../../website/frontend/src/pages/uploads/) and [their server functions](../../../website/backend/src/api/uploads_api.rs) own the contract.
[The upload driver](../../../website/frontend/assets/uploads.js) runs the transfer with the vendored tus-js-client.
[The user procedure](../../user-manual/User_Manual.md#upload-files-and-folders) explains these tasks.
Rows `F-store-15` and `F-store-16` of [the feature register](../Features.md) state the behavior.

| Route | Page | Readers |
|---|---|---|
| `/upload?collection&folder` | The upload page. | Users with an upload target. |
| `/uploads?collection` | The batch list. | Uploaders of the listed collections and administrators. |
| `/uploads/<collection>/<batch_id>?page` | The batch detail. | Uploaders of the collection and administrators. |

| Control | Behavior | Constraint |
|---|---|---|
| Destination | Select the upload target. | It is a select only with more than one target. Its value is in the address. |
| Folder | Select the destination folder in the folder tree of the upload dataset. | The tree reads the structure index without a cache. The folder is in the address. |
| Drop zone | Add dropped files and folders, or open the file dialog on a click. | The file dialog has no type filter. |
| Choose a folder | Add a folder with its subfolders. | |
| File row close | Remove one file from the selection. | The list shows 500 rows and a count of the rest. |
| Clear | Remove every file from the selection. | |
| Upload | Send `begin` and start the transfer. | It is disabled with no file and while a page check fails. |
| Pause, Continue | Stop each transfer after its current chunk, and resume from the server offset. | |
| Retry finish | Repeat a failed commit of the same batch. | It appears after a commit failure. |
| Stop upload | End the transfers and commit the batch. | The files that arrived are ingested. |
| Retry failed files | Send the failed files again. | It shows after a file fails its last retry. |
| Collection filter | List the batches of one collection or of every readable collection. | The filter is in the address. |
| Batch row | Open the batch detail. | |
| Show all | Read the remaining batches in pages of 200. | |
| Continue upload | Match a new selection with the files of the batch, check the acknowledged bytes and resume. | It shows to the owner of an `uploading` batch. The run commits only when it sends every file that waits for bytes. |
| Finish upload | Commit an `uploading` batch without its files that have not been sent. | It shows to the owner of an `uploading` batch. The files that arrived are ingested. |
| Folder link | Open the batch folder in Storage. | |
| Operation link | Open the operation of the batch. | It shows to administrators. |
| Indexed path | Open the document view. | |
| Page buttons | Open the previous or next 200 files of the file table. | The page is in the address. |

| State | Display |
|---|---|
| No upload target | "You cannot upload into any collection." |
| Two upload datasets | "This collection has two upload datasets. An administrator must disable one." |
| Page check failure | The files that break a rule with the rule, and each batch limit that the selection exceeds. |
| `begin` refusal | The files and rules, or the existing paths under "These paths exist in the folder:". |
| Continue upload selection | The page shows the count of selected files outside the batch and each file whose bytes differ. It lists the waiting files that were not sent. |
| Transfer | A bar of acknowledged bytes, the acknowledged bytes and files, and at most 3 files in transfer. |
| Running batch | The detail page reads the counts again every 3 seconds until the state is terminal. |
| No history access | The batch pages show the refusal. |

Upload and Finish upload reject repeated clicks while their request runs.
The dialog shows starting, prefix verification, transfer, pause, and commit states.
Pause and Stop upload are disabled during initialization, prefix verification, and commit.
The dialog prevents interaction with the page behind it.
A prefix request failure closes the dialog and shows an error beside the selection controls.
An unavailable collection in the address does not select another collection.
Changing the destination reloads its folder tree.
A failed shared member marks every uploaded archive that contains it as having errors.
Each manifest entry contributes once to the counts.

A failed batch read retries on the next poll.
A failed resume-manifest read offers Retry loading files.
Opening another batch clears the previous batch selection and transfer state.
