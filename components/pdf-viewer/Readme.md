# PDF viewer

The upstream viewer that the document view embeds, and the scripts that build it.

| script | does |
|---|---|
| [viewer-rebuild.sh](viewer-rebuild.sh) | builds the viewer bundle from [_viewer/](_viewer) |
| [viewer-replay.sh](viewer-replay.sh) | applies `patches/scroll-strategy-lifecycle.patch` to the pinned nested source, then runs [viewer-rebuild.sh](viewer-rebuild.sh) |

[_viewer/](_viewer) is a symlink to [website/frontend/assets/embed-pdf/_viewer/](../../website/frontend/assets/embed-pdf/_viewer).
[embed-pdf-viewer/](embed-pdf-viewer) is the pinned nested Git link.
A scroll-plugin change lives in `patches/scroll-strategy-lifecycle.patch`.
Run [viewer-replay.sh](viewer-replay.sh) so the nested source and the generated bundle match.
The scroll plugin skips a scroll or viewport update when that document has no strategy.
