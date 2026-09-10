# PDF viewer

The upstream viewer the document view embeds, its server-side companion, and the scripts
that build both.

| script | does |
|---|---|
| `viewer-rebuild.sh` | builds the viewer bundle from `_viewer/` |
| `viewer-replay.sh` | applies `patches/scroll-strategy-lifecycle.patch` to the pinned nested source, then runs `viewer-rebuild.sh` |
| `server-run.sh` | runs the companion server for local development |
| `server-copy-dist.sh` | copies the built server distribution to where the backend serves it |

`_viewer/` is a symlink to `website/frontend/assets/embed-pdf/_viewer/`.
`embed-pdf-viewer/` is the pinned nested Git link.
A scroll-plugin change lives in `patches/scroll-strategy-lifecycle.patch`.
Run `viewer-replay.sh` so the nested source and the generated bundle match.
The scroll plugin skips a scroll or viewport update when that document has no strategy.
