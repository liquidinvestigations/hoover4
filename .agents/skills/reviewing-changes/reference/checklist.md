# Repository review checklist

Use the rows that apply to the changed behavior.
Select checks with the verification skill. Reuse captured evidence when it remains valid.

| Boundary | Contract to verify |
|---|---|
| Python and Rust share stored values. | Keep stage values, extractor keys, and shared message fields consistent across readers and writers. |
| Text pages are replaced. | Call `insert_text_pages` once per file and extractor with the complete page list. Later calls can remove earlier pages. |
| Text pages have identities. | Use one-based page or segment numbers and the shared extractor-key formatter. |
| A blob is read. | Take its bucket from the stored path. Do not reconstruct ownership from configuration. |
| An artifact identifier reaches a reader. | Resolve ownership and enforce owner-or-admin access. Preserve the established foreign-owner response. |
| A migration is added. | The runner splits on semicolons without parsing SQL. Keep semicolons out of comments and literals, and comments above statements. |
| An applied migration changes. | Its complete-file checksum makes even comment edits incompatible. Use a new migration unless the owner authorized resets. |
| A Temporal activity argument changes. | Preserve real type annotations so deserialization constructs the expected value. |
| An activity writes before it can retry. | Verify its idempotency identity and behavior after a partial failure. |
| A workflow grows with input. | Verify history growth and continuation against the supported input size. |
| Retry or heartbeat settings change. | Compare the settings and failure interpretation across the caller, worker, and configuration. |
| Several writers update one record. | Verify serialization or atomic updates. Read-then-insert alone does not exclude a second writer. |
| An identifier changes. | Verify uniqueness at the actual call rate. A one-second timestamp alone can collide. |
| ClickHouse returns typed rows. | Verify column names and Enum values on the actual wire. Avoid aliases that shadow source columns. |
| An aggregate answers an existence question. | Read the aggregate value. Empty input can still produce a result row. |
| A structure query changes. | Keep mutable folder-tree reads outside the ordinary search cache. |
| A search match is constructed. | Use the shared full-text query builder. |
| A Dioxus component changes. | Keep hooks unconditional and verify affected interactions in a browser. |
| A service request changes. | Exercise the receiving interface. Matching local types cannot establish remote acceptance. |
| Agent shared code changes. | Verify vendored copies and image build contexts. |
| A shell check reports success. | Preserve the failing command's status through pipelines and conditional callers. |
| A derived metric or status changes. | Verify what it can establish, including duplicate inputs and partial results. |
| A capability changes. | Update its specification row and affected documentation in the same patch. |
| A public file changes. | Exclude private infrastructure details and working-plan references. |

Report which applicable contracts were verified and what remains uncertain.
