# PDF viewer

The upstream viewer the document view embeds, its server-side companion, and the scripts
that build both.

| script | does |
|---|---|
| `viewer-rebuild.sh` | builds the viewer bundle from `_viewer/` |
| `server-run.sh` | runs the companion server for local development |
| `server-copy-dist.sh` | copies the built server distribution to where the backend serves it |

`_viewer/`, `_server/` and `embed-pdf-viewer/` are vendored upstream trees. Patch them only when the change is
also carried in a script here, or the next rebuild discards it.
