"""The materialised VFS tree: node keys, the ancestor closure, and the builder.

Why a node key at all
---------------------
The old `parent_paths` term field hashed the bare path, so
``hash_string_to_uint63("/data")`` was the same integer in every dataset and inside
every archive. Filtering on one dataset's `/data` folder therefore also matched the
other dataset's, and matched `/data` inside an unrelated zip. A tree built on those ids
is not slightly wrong, it is meaningless.

A node key is scoped by both::

    node_key := "{collection_dataset}\\x1f{container_hash}\\x1f{normalised_path}"

The unit separator cannot occur in a dataset id and cannot occur in a path we accept —
paths with control characters are rejected and logged, on top of P0's existing surrogate
rejection. The per-dataset pseudo-root is ``"{collection_dataset}\\x1f\\x1f/"`` and is
what the tree's dataset row filters on.

Why the closure has more than one parent
----------------------------------------
The ancestor closure of a document is every folder it can be reached through, and
"through" crosses container boundaries: a `.docx` inside `a.zip` inside `b.zip` inside
`/data` must come back when the user filters on `/data`. Containers are content-addressed,
so ONE container hash can sit at several paths — the `zip-in-multiple-locations` fixture
is two copies of the same `parent.zip` — and the closure includes the ancestors of
*every* copy. ``vfs_nodes.parent_key`` is single-valued and is only for breadcrumbs;
anything that decides *membership* uses :func:`ancestor_node_keys`.

Cycles are not hypothetical: `eml-7-recursive` is an email containing itself. Hence a
visited set on ``(container_hash, path)``, a container-hop cap, and a term cap — with
the truncation recorded in ``struct_flags`` rather than silently swallowed.
"""

from dataclasses import dataclass
import logging
import os
import re

from database.enum_wire import KIND_DEFAULT, KIND_ORDINALS, enum_from_wire

log = logging.getLogger(__name__)

UNIT_SEP = "\x1f"

#: Container hops before the closure gives up. `eml-7-recursive` is an email that
#: contains itself; the visited set stops that one, this stops the merely absurd.
MAX_ANCESTOR_DEPTH = 64

#: Terms per document before the closure gives up. A pathological tree (`many-children`
#: plus deep nesting) would otherwise write an MVA big enough to slow every query.
MAX_ANCESTOR_TERMS = 4096

#: `struct_flags` bits. A bitfield rather than a column each: these are cheap booleans
#: that only ever need equality, and Manticore has no boolean attribute.
STRUCT_FLAG_EMAIL_HAS_ATTACHMENTS = 1 << 0
STRUCT_FLAG_TRUNCATED_ANCESTRY = 1 << 1

#: `kind` as ClickHouse writes it (Enum8) and as Manticore stores it (int). Manticore has
#: no enum type, so the int is the wire format there.
KIND_DIR = "dir"
KIND_FILE = "file"
KIND_CONTAINER = "container"
KIND_TO_INT = dict(KIND_ORDINALS)
INT_TO_KIND = {value: name for name, value in KIND_TO_INT.items()}


def kind_from_wire(value) -> str:
    """Normalise a `kind` that may arrive as a name or as an ordinal.

    One line over :func:`database.enum_wire.enum_from_wire`, which carries the reasoning
    and is used for `email_addresses.role` as well. Kept as a name because `kind` is read
    in several places and "which enum, with which default" is worth saying once.
    """
    return enum_from_wire(value, KIND_ORDINALS, KIND_DEFAULT)

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def normalise_path(path: str) -> str | None:
    """Absolute, ``/``-rooted, no trailing slash except for the root itself.

    Returns None for a path we refuse to key: one containing a control character (the
    unit separator among them) would make ``node_key`` ambiguous, and an ambiguous key
    silently merges two folders. Rejecting is the only safe answer, and the caller logs.
    """
    if path is None:
        return None
    text = str(path)
    if _CONTROL_CHARS.search(text):
        return None
    if not text.startswith("/"):
        text = "/" + text
    # posixpath.normpath collapses `..`, `.` and duplicate slashes; without it
    # `/a//b` and `/a/b` are two different keys for one folder.
    text = os.path.normpath(text)
    if text != "/":
        text = text.rstrip("/")
    return text or "/"


def make_node_key(collection_dataset: str, container_hash: str, path: str) -> str | None:
    """The canonical identity of one VFS node, or None if the path is unkeyable."""
    normalised = normalise_path(path)
    if normalised is None:
        return None
    return f"{collection_dataset}{UNIT_SEP}{container_hash or ''}{UNIT_SEP}{normalised}"


def dataset_root_key(collection_dataset: str) -> str:
    """The per-dataset pseudo-root. Every document's closure contains it."""
    return f"{collection_dataset}{UNIT_SEP}{UNIT_SEP}/"


def path_ancestors(path: str) -> list[str]:
    """Every ancestor directory of ``path``, root first, EXCLUDING ``path`` itself.

    ``/a/b/c.txt`` -> ``['/', '/a', '/a/b']``. ``/`` -> ``[]``.
    """
    normalised = normalise_path(path)
    if normalised is None or normalised == "/":
        return []
    parts = normalised.strip("/").split("/")
    out = ["/"]
    for i in range(1, len(parts)):
        out.append("/" + "/".join(parts[:i]))
    return out


def ancestor_node_keys(
    collection_dataset: str,
    vfs_rows: list[tuple[str, str]],
    container_parents: dict[str, list[tuple[str, str]]],
) -> tuple[set[str], bool]:
    """The full ancestor closure of one document, and whether it was truncated.

    ``vfs_rows`` are the ``(container_hash, path)`` pairs of the document's own
    ``vfs_files`` rows. ``container_parents`` maps a container hash to every
    ``(container_hash, path)`` at which that container itself lives — plural, because a
    content-addressed container can sit in several places at once, and a document inside
    it is genuinely reachable through all of them.

    Returns the set of node keys and a truncation flag (a cap was hit, so the closure is
    incomplete and the document's `struct_flags` should say so). The dataset pseudo-root
    is always included, even when everything else was truncated: it is what the tree's
    dataset row filters on, and losing it would hide the document from the tree entirely.
    """
    keys: set[str] = set()
    truncated = False
    visited: set[tuple[str, str]] = set()
    # (container_hash, path, container_hops)
    queue: list[tuple[str, str, int]] = [
        (ch or "", path, 0) for ch, path in vfs_rows
    ]

    while queue:
        container_hash, path, hops = queue.pop()
        marker = (container_hash, path)
        if marker in visited:
            continue
        visited.add(marker)

        for ancestor in path_ancestors(path):
            key = make_node_key(collection_dataset, container_hash, ancestor)
            if key is None:
                continue
            keys.add(key)
            if len(keys) >= MAX_ANCESTOR_TERMS:
                truncated = True
                break
        if truncated:
            break

        if not container_hash:
            continue
        if hops >= MAX_ANCESTOR_DEPTH:
            truncated = True
            continue
        for parent_container, parent_path in container_parents.get(container_hash, ()):
            # The container FILE is itself a node, and filtering on the folder that
            # holds it must find what is inside it.
            key = make_node_key(collection_dataset, parent_container or "", parent_path)
            if key is not None:
                keys.add(key)
            queue.append((parent_container or "", parent_path, hops + 1))

    keys.add(dataset_root_key(collection_dataset))
    return keys, truncated


@dataclass
class VfsNode:
    container_hash: str
    path: str
    node_key: str
    parent_key: str
    kind: str
    file_hash: str
    file_size_bytes: int
    depth: int

    @property
    def name(self) -> str:
        """The label the tree shows. Empty only for the dataset pseudo-root, which the
        caller renders under the dataset's own name."""
        return "" if self.path == "/" else os.path.basename(self.path)


def build_node_rows(
    collection_dataset: str,
    dir_rows: list[tuple[str, str]],
    file_rows: list[tuple[str, str, str, int]],
    container_hashes: set[str],
) -> list[VfsNode]:
    """Materialise every node of one dataset's tree.

    ``dir_rows``  -- ``(container_hash, path)`` from `vfs_directories`.
    ``file_rows`` -- ``(container_hash, path, file_hash, file_size_bytes)`` from
    `vfs_files`. ``container_hashes`` -- hashes that are archives or emails, i.e. files
    that COULD be folders.

    A file is a container here only if something is actually inside it. Being detected as
    an archive, or being an email, is not enough: an email with no attachments and a
    ``.zip`` whose listing found nothing have no children, and rendering them as folders
    gives the tree an expandable chevron that opens onto nothing. The evidence is already
    in hand — a hash has members exactly when some `vfs_directories` or `vfs_files` row
    names it as its ``container_hash`` — so the container test is the intersection of "is
    an archive or an email" with "has members". The demotion is to the tree's ``kind``
    only: the file keeps its `archives`/`emails` rows and its Email or Archive rendering
    in the viewer.

    There is NO synthetic ``/`` node inside a container. What lives at the top of an
    archive hangs directly off the archive FILE, so expanding `report.zip` shows what is
    in it rather than a single row named ``/`` that has to be opened again. ``depth``
    therefore counts one hop per container rather than two, which is what a container hop
    always was.

    Synthesises what the scan does not record: the dataset pseudo-root, and any
    intermediate directory that has files but no `vfs_directories` row (which happens
    whenever a container's listing skipped a level).

    ``parent_key`` is single-valued and crosses container boundaries. When a container
    lives at more than one path the lexicographically smallest location wins — an
    arbitrary but STABLE choice, so breadcrumbs do not flip between runs. Membership
    never uses it (see :func:`ancestor_node_keys`); only "show me the path to this node"
    does, and there is genuinely more than one right answer.
    """
    root_key = dataset_root_key(collection_dataset)
    nodes: dict[str, VfsNode] = {
        root_key: VfsNode(
            container_hash="", path="/", node_key=root_key, parent_key="",
            kind=KIND_DIR, file_hash="", file_size_bytes=-1, depth=0,
        )
    }
    rejected: list[str] = []

    def add(container_hash, path, kind, file_hash="", size=-1) -> str | None:
        if container_hash and normalise_path(path) == "/":
            # The root INSIDE a container is not a node. It arrives from three places —
            # a `vfs_directories` row for `/`, the ancestor walk of every member, and the
            # old explicit synthesis — so it is refused here once rather than guarded at
            # each of them. Members hang off the container file instead; see the
            # docstring. The `/` of the DATASET is a different node and is seeded above.
            return None
        key = make_node_key(collection_dataset, container_hash, path)
        if key is None:
            rejected.append(f"{container_hash}:{path}")
            return None
        existing = nodes.get(key)
        # A container beats a plain file, and a real row beats a synthesised directory.
        if existing is None or KIND_TO_INT[kind] > KIND_TO_INT[existing.kind]:
            nodes[key] = VfsNode(
                container_hash=container_hash or "", path=normalise_path(path),
                node_key=key, parent_key="", kind=kind,
                file_hash=file_hash, file_size_bytes=int(size), depth=0,
            )
        elif existing.file_size_bytes < 0 and size >= 0:
            existing.file_size_bytes = int(size)
        return key

    # Where every container physically lives, for the parent links of what is inside it.
    container_locations: dict[str, list[str]] = {}

    # A hash is a container only if something names it as its container. See the
    # docstring: "detected as an archive" is a guess, "has members" is the fact.
    hashes_with_members = {ch for ch, *_ in dir_rows if ch}
    hashes_with_members |= {ch for ch, *_ in file_rows if ch}
    effective_containers = set(container_hashes) & hashes_with_members

    for container_hash, path in dir_rows:
        add(container_hash or "", path, KIND_DIR)

    for container_hash, path, file_hash, size in file_rows:
        is_container = file_hash in effective_containers
        key = add(container_hash or "", path, KIND_CONTAINER if is_container else KIND_FILE,
                  file_hash=file_hash, size=size)
        if key is not None and is_container:
            container_locations.setdefault(file_hash, []).append(key)
        # Every ancestor directory must exist as a node even when the scan recorded no
        # row for it, or the tree has holes exactly where a container skipped a level.
        for ancestor in path_ancestors(path):
            add(container_hash or "", ancestor, KIND_DIR)

    for node in nodes.values():
        if node.node_key == root_key:
            continue
        parent_path = os.path.dirname(node.path) or "/"
        if node.container_hash and parent_path == "/":
            # The top level inside a container hangs off the container FILE — there is no
            # `/` node in between. When the container lives at more than one path the
            # lexicographically smallest wins: arbitrary, but stable across runs, so a
            # breadcrumb does not flip. A container whose own file was never seen (its
            # members arrived without it) falls back to the dataset root rather than
            # dangling.
            locations = sorted(container_locations.get(node.container_hash, ()))
            node.parent_key = locations[0] if locations else root_key
        else:
            # The only node left whose own path is `/` is the dataset pseudo-root, and
            # that one is skipped above.
            node.parent_key = make_node_key(
                collection_dataset, node.container_hash, parent_path
            ) or root_key

    _assign_depths(nodes, root_key)

    if rejected:
        log.warning(
            "%s: %d VFS path(s) rejected for control characters and left out of the "
            "tree: %s", collection_dataset, len(rejected), rejected[:10],
        )
    return sorted(nodes.values(), key=lambda n: n.node_key)


def _assign_depths(nodes: dict[str, VfsNode], root_key: str) -> None:
    """Distance from the dataset pseudo-root, counting container hops.

    Iterative with a visited set rather than recursive: `eml-7-recursive` makes the
    parent chain a cycle, and a recursive walk over it is a crash rather than a wrong
    number. A node whose chain does not reach the root (or hits the cap) keeps the depth
    it accumulated, which is what the UI's indent cap wants anyway.
    """
    for node in nodes.values():
        if node.node_key == root_key:
            continue
        depth = 0
        seen = {node.node_key}
        cursor = node
        while cursor.parent_key and cursor.parent_key != root_key:
            if cursor.parent_key in seen or depth >= MAX_ANCESTOR_DEPTH:
                break
            seen.add(cursor.parent_key)
            parent = nodes.get(cursor.parent_key)
            if parent is None:
                break
            depth += 1
            cursor = parent
        node.depth = depth + 1


def container_parents_from_nodes(nodes) -> dict[str, list[tuple[str, str]]]:
    """``{container_hash: [(container_hash, path), …]}`` from materialised nodes.

    The multi-parent map :func:`ancestor_node_keys` needs, derived from the node table
    rather than re-read from `vfs_files`: one query, one source of truth, and the
    duplicated-container case falls out of it for free.
    """
    out: dict[str, list[tuple[str, str]]] = {}
    for node in nodes:
        raw_kind = node["kind"] if isinstance(node, dict) else node.kind
        if kind_from_wire(raw_kind) != KIND_CONTAINER:
            continue
        file_hash = node["file_hash"] if isinstance(node, dict) else node.file_hash
        container_hash = node["container_hash"] if isinstance(node, dict) else node.container_hash
        path = node["path"] if isinstance(node, dict) else node.path
        out.setdefault(file_hash, []).append((container_hash or "", path))
    return out
