"""The email connection graph: identities, edges, and connected components.

Everything in this module is PURE. The activity that uses it (`build_email_graph` in
`activities.py`) does the ClickHouse I/O and nothing else, because every interesting
decision here is a threshold and a threshold is only trustworthy if it is testable
without a database.

Why the graph is not built on RFC threading headers
---------------------------------------------------
It is built on all of them, but they carry almost nothing on the corpora this runs
against. A Lotus Notes export has ``Message-ID:`` on 100% of its messages,
``In-Reply-To:`` on 0.06% and ``References:`` on 0.15%. A graph built on threading
headers alone would be empty for the largest corpus present. What is strong instead:

* **Message-id identity** -- the same message present in two mailboxes. Exact, and
  common: about one message in five has a second rendition in another dataset. This is
  the "sender's copy and the recipient's copy" relation.
* **Attachment containment** -- an email carried inside another email. Exact.
* **Subject + participants** -- the only thing that can recover a reply or forward chain
  when the headers are gone, and a HEURISTIC. It is carried as its own edge kinds with a
  confidence below 1 so the interface can draw it differently, because an interface that
  draws wrong connections confidently is worse than no interface.

The three guards on the inferred edges
--------------------------------------
41.5% of the subjects in the corpus carry an ``RE:``/``FW:`` prefix, so the naive rule
"same normalised subject means same thread" connects a large fraction of the corpus into
one component and the graph becomes a picture of nothing. The guards below exist to stop
that, they are module constants rather than literals so they can be tightened after the
inferred edges are hand-audited, and `build_edges` logs what each one dropped.
"""

from dataclasses import dataclass, field
import logging
import re

log = logging.getLogger(__name__)

#: Every leading ``RE:`` / ``FW:`` / ``FWD:`` / ``AW:`` / ``WG:`` run, with optional
#: bracketed counters (``Re[2]:``) and surrounding whitespace. Anchored and applied
#: repeatedly, so ``RE: FW: RE: x`` normalises to ``x``.
#:
#: The colon is REQUIRED. Without it a subject that merely begins with the letters of a
#: prefix -- "Reply requested by Friday", "Award ceremony" -- loses its first word and
#: silently joins an unrelated thread.
_SUBJECT_PREFIX_RE = re.compile(r"^\s*(re|fw|fwd|aw|wg|tr|sv|vs|antwort)\s*(\[\d+\])?\s*:\s*", re.IGNORECASE)

#: Which direction a raw subject prefix implies. ``FW``/``FWD``/``TR`` is a forward,
#: everything else in the prefix set is a reply.
_FORWARD_PREFIXES = {"fw", "fwd", "tr"}

#: A `subject_norm` shared by more than this many messages is dropped entirely: at that
#: size it is a mailing list, a daily report or an autoresponder subject ("Weekly Update",
#: "FW:"), not a thread. Chosen against the enron corpus, where the largest genuine
#: human thread observed is well under 100 messages and the subjects above 200 are all
#: automated. Every drop is logged with the subject and its count.
MAX_MESSAGES_PER_SUBJECT = 200

#: An inferred edge is only kept when the two messages are within this many days of each
#: other. Same-subject messages a year apart are a recurring report, not a reply.
INFERRED_WINDOW_DAYS = 90

#: A `subject_norm` this short or shorter is not evidence of anything: "hi", "fyi", "".
MIN_SUBJECT_NORM_LENGTH = 3

#: What an inferred edge records. Anything derived from an exact key records 1.0.
INFERRED_CONFIDENCE = 0.5
EXACT_CONFIDENCE = 1.0

#: Seconds, derived. Kept next to the day count so a change to one cannot miss the other.
INFERRED_WINDOW_SECONDS = INFERRED_WINDOW_DAYS * 24 * 3600

KIND_IDENTITY = "identity"
KIND_REPLY = "reply"
KIND_FORWARD = "forward"
KIND_ATTACHMENT = "attachment"
KIND_REFERENCE = "reference"


def normalise_subject(subject: str) -> str:
    """Strip every leading reply/forward prefix run, lowercase, collapse whitespace.

    ``"RE: FW: RE: Gingrich view"`` and ``"Gingrich view"`` both become
    ``"gingrich view"``; ``"Reply requested"`` becomes ``"reply requested"`` and keeps
    its first word, because the prefix pattern requires the colon.
    """
    text = subject or ""
    while True:
        stripped = _SUBJECT_PREFIX_RE.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped
    return " ".join(text.split()).lower()


def subject_prefix_kind(subject: str) -> str:
    """``forward``, ``reply``, or ``""`` for the OUTERMOST prefix of a raw subject.

    The outermost one is the most recent action: ``FW: RE: x`` was forwarded last, so it
    is a forward. This is the only direction evidence an inferred edge has, which is why
    a message with no prefix never becomes the destination of one.
    """
    match = _SUBJECT_PREFIX_RE.match(subject or "")
    if not match:
        return ""
    return KIND_FORWARD if match.group(1).lower() in _FORWARD_PREFIXES else KIND_REPLY


def normalise_message_id(raw: str) -> str:
    """Lowercase, strip angle brackets and whitespace. ``""`` when there is nothing left.

    Message ids are compared for equality across mailboxes, where one side has often been
    re-serialised by a different mail client, so the comparison has to be on the
    normalised form or the identity edge silently finds nothing.
    """
    text = (raw or "").strip()
    if text.startswith("<") and text.endswith(">"):
        text = text[1:-1]
    return text.strip().lower()


def split_message_ids(raw: str) -> list[str]:
    """Every ``<id>`` in a ``References:`` or ``In-Reply-To:`` header, in order.

    ``References:`` is a whitespace-separated list and ``In-Reply-To:`` is supposed to
    hold one id but in the wild holds several, so both go through the same splitter.
    """
    return [normalise_message_id(part) for part in re.findall(r"<[^<>]+>", raw or "")] or (
        [normalise_message_id(raw)] if raw and "<" not in raw else []
    )


@dataclass(frozen=True)
class EmailIdentity:
    """One message's join keys. Mirrors a row of the ``email_identity`` table."""

    collection_dataset: str
    email_hash: str
    message_id: str
    subject_norm: str
    subject_prefix: str
    date_sent: int
    date_sent_known: int
    from_address: str
    participants: tuple[str, ...]

    @property
    def key(self) -> tuple[str, str]:
        return (self.collection_dataset, self.email_hash)


@dataclass(frozen=True)
class EmailEdge:
    """One directed edge. Mirrors a row of the ``email_edges`` table."""

    src_dataset: str
    src_hash: str
    dst_dataset: str
    dst_hash: str
    kind: str
    confidence: float
    evidence: str


@dataclass
class EdgeBuildStats:
    """What each rule produced and what each guard dropped, for one log line."""

    per_kind: dict = field(default_factory=dict)
    dropped_busy_subjects: int = 0
    dropped_busy_subject_messages: int = 0
    dropped_short_subject: int = 0
    dropped_out_of_window: int = 0
    dropped_no_overlap: int = 0
    dropped_no_direction: int = 0
    dropped_undated: int = 0

    def count(self, kind: str) -> None:
        self.per_kind[kind] = self.per_kind.get(kind, 0) + 1

    def summary(self) -> str:
        kinds = ", ".join(f"{k}={v}" for k, v in sorted(self.per_kind.items())) or "none"
        return (
            f"edges by kind: {kinds}; dropped: "
            f"busy_subjects={self.dropped_busy_subjects} "
            f"(messages={self.dropped_busy_subject_messages}), "
            f"short_subject={self.dropped_short_subject}, "
            f"undated={self.dropped_undated}, "
            f"out_of_window={self.dropped_out_of_window}, "
            f"no_participant_overlap={self.dropped_no_overlap}, "
            f"no_direction={self.dropped_no_direction}"
        )


def _ordered(a: tuple[str, str], b: tuple[str, str]) -> tuple[tuple[str, str], tuple[str, str]]:
    """The pair sorted, so an undirected edge is stored exactly once."""
    return (a, b) if a <= b else (b, a)


def build_identity_edges(identities) -> tuple[list[EmailEdge], EdgeBuildStats]:
    """Edges between renditions of the SAME message, keyed on the message id.

    Exact, and the most valuable edge in this graph: it is what connects one custodian's
    sent copy to another custodian's received copy. Stored once per unordered pair.
    """
    stats = EdgeBuildStats()
    by_message_id: dict[str, list[EmailIdentity]] = {}
    for identity in identities:
        if identity.message_id:
            by_message_id.setdefault(identity.message_id, []).append(identity)

    edges: list[EmailEdge] = []
    for message_id, group in by_message_id.items():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda i: i.key)
        # A star from the lowest key rather than a clique: a message id present in
        # twenty mailboxes is one component either way, and the clique would be 190
        # edges saying the same thing.
        hub = ordered[0]
        for other in ordered[1:]:
            edges.append(EmailEdge(
                src_dataset=hub.collection_dataset, src_hash=hub.email_hash,
                dst_dataset=other.collection_dataset, dst_hash=other.email_hash,
                kind=KIND_IDENTITY, confidence=EXACT_CONFIDENCE, evidence=message_id,
            ))
            stats.count(KIND_IDENTITY)
    return edges, stats


def build_rfc_edges(identities, header_pairs_by_key) -> tuple[list[EmailEdge], EdgeBuildStats]:
    """``In-Reply-To`` and ``References`` edges, for the messages that carry them.

    Rare in these corpora and exact when present, so they are built unconditionally and
    cost nothing when the headers are absent. The edge points from the referenced
    message (the parent) to the referring one, which is the direction the viewer's
    "Forward of ..." banner reads.
    """
    stats = EdgeBuildStats()
    by_message_id: dict[str, EmailIdentity] = {}
    for identity in identities:
        if identity.message_id:
            by_message_id.setdefault(identity.message_id, identity)

    edges: list[EmailEdge] = []
    for identity in identities:
        pairs = header_pairs_by_key.get(identity.key) or []
        for header_name, kind in (("in-reply-to", KIND_REPLY), ("references", KIND_REFERENCE)):
            for raw in [value for name, value in pairs if name.lower() == header_name]:
                for referenced in split_message_ids(raw):
                    parent = by_message_id.get(referenced)
                    if parent is None or parent.key == identity.key:
                        continue
                    edges.append(EmailEdge(
                        src_dataset=parent.collection_dataset, src_hash=parent.email_hash,
                        dst_dataset=identity.collection_dataset, dst_hash=identity.email_hash,
                        kind=kind, confidence=EXACT_CONFIDENCE, evidence=header_name,
                    ))
                    stats.count(kind)
    return edges, stats


def build_attachment_edges(identities, containment) -> tuple[list[EmailEdge], EdgeBuildStats]:
    """Edges from a containing email to every email it carries as an attachment.

    ``containment`` is ``(collection_dataset, container_hash, member_hash)`` triples out
    of ``vfs_files``. Only pairs where BOTH ends are known emails become edges -- a PDF
    attachment is not a node in this graph.
    """
    stats = EdgeBuildStats()
    known = {identity.key for identity in identities}
    edges: list[EmailEdge] = []
    seen: set[tuple] = set()
    for collection_dataset, container_hash, member_hash in containment:
        src = (collection_dataset, container_hash)
        dst = (collection_dataset, member_hash)
        if src == dst or src not in known or dst not in known:
            continue
        if (src, dst) in seen:
            continue
        seen.add((src, dst))
        edges.append(EmailEdge(
            src_dataset=src[0], src_hash=src[1], dst_dataset=dst[0], dst_hash=dst[1],
            kind=KIND_ATTACHMENT, confidence=EXACT_CONFIDENCE, evidence="vfs_files.container_hash",
        ))
        stats.count(KIND_ATTACHMENT)
    return edges, stats


def build_inferred_edges(
    identities,
    max_messages_per_subject: int = MAX_MESSAGES_PER_SUBJECT,
    window_seconds: int = INFERRED_WINDOW_SECONDS,
    min_subject_length: int = MIN_SUBJECT_NORM_LENGTH,
) -> tuple[list[EmailEdge], EdgeBuildStats]:
    """Reply and forward edges inferred from ``subject_norm`` plus participant overlap.

    The heuristic, in full, with each guard named:

    1. ``subject_norm`` must be longer than ``min_subject_length`` characters. An empty
       or two-letter subject is not evidence.
    2. A ``subject_norm`` shared by more than ``max_messages_per_subject`` messages is
       dropped WHOLE and logged: at that size it is a mailing list or an autoresponder.
    3. Both messages must have a real ``Date:`` (``date_sent_known``), and they must be
       within ``window_seconds`` of each other.
    4. They must share at least one participant address.
    5. The LATER message's raw subject must carry a reply or forward prefix -- that
       prefix is the only direction evidence there is, and it decides the kind.

    Every surviving edge records `INFERRED_CONFIDENCE`, never 1.0.

    The thresholds are parameters so the whole rule can be re-run at a different setting
    against the same fixtures once the inferred edges have been hand-audited.
    """
    stats = EdgeBuildStats()
    by_subject: dict[str, list[EmailIdentity]] = {}
    for identity in identities:
        if len(identity.subject_norm) <= min_subject_length:
            stats.dropped_short_subject += 1
            continue
        if not identity.date_sent_known:
            stats.dropped_undated += 1
            continue
        by_subject.setdefault(identity.subject_norm, []).append(identity)

    edges: list[EmailEdge] = []
    for subject_norm, group in sorted(by_subject.items()):
        if len(group) < 2:
            continue
        if len(group) > max_messages_per_subject:
            stats.dropped_busy_subjects += 1
            stats.dropped_busy_subject_messages += len(group)
            log.info(
                "[P6] email graph: dropping subject %r shared by %d messages (cap %d)",
                subject_norm[:120], len(group), max_messages_per_subject,
            )
            continue
        ordered = sorted(group, key=lambda i: (i.date_sent, i.key))
        for index, earlier in enumerate(ordered):
            for later in ordered[index + 1:]:
                if later.date_sent <= earlier.date_sent:
                    # Same instant: no direction, and two renditions of one message are
                    # an identity edge's job, not this rule's.
                    continue
                if later.date_sent - earlier.date_sent > window_seconds:
                    stats.dropped_out_of_window += 1
                    # `ordered` is ascending, so every remaining `later` is further away.
                    break
                if not (set(earlier.participants) & set(later.participants)):
                    stats.dropped_no_overlap += 1
                    continue
                kind = later.subject_prefix
                if kind not in (KIND_REPLY, KIND_FORWARD):
                    stats.dropped_no_direction += 1
                    continue
                edges.append(EmailEdge(
                    src_dataset=earlier.collection_dataset, src_hash=earlier.email_hash,
                    dst_dataset=later.collection_dataset, dst_hash=later.email_hash,
                    kind=kind, confidence=INFERRED_CONFIDENCE, evidence=subject_norm[:200],
                ))
                stats.count(kind)
    return edges, stats


def merge_stats(*many) -> EdgeBuildStats:
    merged = EdgeBuildStats()
    for stats in many:
        for kind, count in stats.per_kind.items():
            merged.per_kind[kind] = merged.per_kind.get(kind, 0) + count
        merged.dropped_busy_subjects += stats.dropped_busy_subjects
        merged.dropped_busy_subject_messages += stats.dropped_busy_subject_messages
        merged.dropped_short_subject += stats.dropped_short_subject
        merged.dropped_out_of_window += stats.dropped_out_of_window
        merged.dropped_no_overlap += stats.dropped_no_overlap
        merged.dropped_no_direction += stats.dropped_no_direction
        merged.dropped_undated += stats.dropped_undated
    return merged


def build_all_edges(identities, header_pairs_by_key, containment):
    """Every edge kind, deduplicated, plus the merged statistics.

    Deduplication is on ``(src, dst, kind)``: two rules can legitimately produce the same
    kind of edge for the same pair (a message referenced by both ``In-Reply-To`` and
    ``References``), and the table is a ReplacingMergeTree keyed on exactly that.
    """
    identities = list(identities)
    parts = [
        build_identity_edges(identities),
        build_rfc_edges(identities, header_pairs_by_key),
        build_attachment_edges(identities, containment),
        build_inferred_edges(identities),
    ]
    seen: set[tuple] = set()
    edges: list[EmailEdge] = []
    for part_edges, _ in parts:
        for edge in part_edges:
            key = (edge.src_dataset, edge.src_hash, edge.kind, edge.dst_dataset, edge.dst_hash)
            if key in seen:
                continue
            seen.add(key)
            edges.append(edge)
    return edges, merge_stats(*[stats for _, stats in parts])


def connected_components(edges) -> dict[tuple[str, str], set[tuple[str, str]]]:
    """Union-find over the edges, ignoring direction.

    Returns a map from every node that has at least one edge to the SET of nodes in its
    component. A node with no edge is absent: it is in no cluster, and writing a row per
    isolated message would be one row per email in the corpus to say "nothing here".
    """
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(node):
        parent.setdefault(node, node)
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    for edge in edges:
        a = find((edge.src_dataset, edge.src_hash))
        b = find((edge.dst_dataset, edge.dst_hash))
        if a != b:
            parent[max(a, b)] = min(a, b)

    components: dict[tuple[str, str], set] = {}
    for node in list(parent):
        components.setdefault(find(node), set()).add(node)
    return {node: members for members in components.values() for node in members}
