# Shared website types

Types used by both the server and the WASM client. Anything that crosses that boundary lives
here rather than being defined twice.

The pipeline stage identifiers are the load-bearing example: they are stored values on the
pipeline side and mirrored here, so the two must move together or the admin processing view
silently loses a stage.
