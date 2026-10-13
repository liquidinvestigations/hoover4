# Shared website types

Types used by both the server and the WASM client. Anything that crosses that boundary lives
here rather than being defined twice.

The pipeline stage identifiers are the clearest example. They are stored values on the
pipeline side and mirrored here, so the two must move together or the admin processing view
silently loses a stage.

PDF source values include source kind, engine, languages, and current document page ranges.
Older values default to the original source kind and an empty manifest.
Source selection compares source identity explicitly.
Reactive values compare the complete manifest so refreshed ranges reach the viewer.
`pdfocr_<engine>_<languages>` identifies PDF OCR text.
`ocr_<engine>_<languages>` identifies image OCR text, including image Preview OCR.
