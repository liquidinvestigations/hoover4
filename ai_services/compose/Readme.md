# GPU tier compose overlays

One overlay per service in the standalone GPU tier. `deploy.py` selects them from
`hoover4.ini`; they are never run by hand with a bare `up -d`.

| file | service |
|---|---|
| `ai-server.yaml` | embeddings, reranking and NER |
| `easyocr.yaml` | GPU OCR |
| `vllm.yaml` | local model serving |

Relative paths in these files resolve against the **project directory** — the first compose
file's directory — not against the overlay's own location. Render the merged configuration
and read the absolute paths whenever an overlay is added or moved.

A service whose build context does not exist takes the whole tier down, because compose
builds everything before starting anything. Disabling a service in the configuration is the
way to skip it.
