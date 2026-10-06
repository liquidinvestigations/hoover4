"""Keep distinct filename extensions within the workflow payload budget."""

import json
import os


def bounded_file_names(names: list[str], limit: int = 120) -> list[str]:
    """Keep at most four names within their serialized JSON size limit."""
    kept = []
    extensions = set()
    for raw in names:
        name = raw.rsplit("/", 1)[-1]
        stem, extension = os.path.splitext(name)
        if extension.lower() in extensions or len(extension) > 16:
            continue
        room = limit - len(json.dumps(kept).encode()) - (2 if kept else 0)
        while stem and len(json.dumps(stem + extension).encode()) > room:
            stem = stem[:-1]
        cut = stem + extension
        if not cut or len(json.dumps(kept + [cut]).encode()) > limit:
            continue
        kept.append(cut)
        extensions.add(extension.lower())
        if len(kept) == 4:
            break
    return kept
