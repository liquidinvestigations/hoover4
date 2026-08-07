"""Split one page's text into embeddable chunks, addressed by BYTE offsets.

A chunk addresses into exactly one page's text (see migration 00013: `page_id` is a
real 1-based page number for paged formats, a 256 KB segment ordinal otherwise), so
`index_start` / `index_end` are small offsets within that page. They are **byte offsets
into the UTF-8 encoding**, never character offsets — Python slices strings by character
and ClickHouse `substring()` counts bytes, and mixing the two corrupts multibyte text
silently, with no error anywhere. The migration comments on `text_chunks` say the same
thing; keep them saying it.

Chunks break on word boundaries (never mid-word, which also means never inside a
UTF-8 sequence) and overlap by roughly `CHUNK_OVERLAP_BYTES` so a fact split across a
boundary still appears whole in at least one chunk. Deterministic: the same page text
always produces the same chunk set, which is what makes the embed activity's left-anti
join a correct idempotency key.
"""

from dataclasses import dataclass

#: e5-small truncates at 512 tokens; 1200 bytes is ~300 tokens of English, comfortably
#: inside the window, and small enough that a KNN hit points at a passage rather than a
#: page. Byte budget, not character budget — see the module docstring.
CHUNK_MAX_BYTES = 1200

#: How much of a chunk's tail the next chunk re-covers.
CHUNK_OVERLAP_BYTES = 200


@dataclass
class Chunk:
    chunk_index: int
    index_start: int  # start BYTE offset within the UTF-8 page text
    index_end: int    # end BYTE offset, exclusive
    text: str


def chunk_page_text(
    text: str,
    max_bytes: int = CHUNK_MAX_BYTES,
    overlap_bytes: int = CHUNK_OVERLAP_BYTES,
) -> list[Chunk]:
    """Split `text` into chunks of at most ~`max_bytes` bytes, overlapping by ~`overlap_bytes`.

    Returns an empty list for whitespace-only text. Offsets address into the original
    `text` (a chunk's text is a slice of it, minus any leading whitespace the word
    packing skipped).
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if not 0 <= overlap_bytes < max_bytes:
        raise ValueError("overlap_bytes must be in [0, max_bytes)")

    # Word spans, then each word's byte offset — computed incrementally (one pass, each
    # gap encoded once) rather than as len(text[:pos].encode()) per word, which is
    # quadratic on a 256 KB segment.
    import re

    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    if not words:
        return []

    byte_starts: list[int] = []
    byte_ends: list[int] = []
    byte_pos = 0
    last_char = 0
    for start, end in words:
        byte_pos += len(text[last_char:start].encode("utf-8"))
        byte_starts.append(byte_pos)
        byte_pos += len(text[start:end].encode("utf-8"))
        byte_ends.append(byte_pos)
        last_char = end

    chunks: list[Chunk] = []
    i = 0
    n = len(words)
    while i < n:
        start_byte = byte_starts[i]
        # Extend the chunk while the next word still fits the budget. A single word
        # longer than max_bytes becomes a chunk of its own (j stays i) — truncating it
        # would split a UTF-8 sequence or a word, and dropping it would lose text.
        j = i
        while j + 1 < n and byte_ends[j + 1] - start_byte <= max_bytes:
            j += 1
        end_byte = byte_ends[j]
        end_char = words[j][1]
        chunks.append(Chunk(
            chunk_index=len(chunks),
            index_start=start_byte,
            index_end=end_byte,
            text=text[words[i][0]:end_char],
        ))
        if j == n - 1:
            break
        # Overlap: the next chunk restarts far enough back to re-cover roughly
        # overlap_bytes of this chunk's tail, but always strictly forward — a chunk
        # smaller than the overlap budget must not wedge the loop.
        k = j
        while k > i and end_byte - byte_starts[k] < overlap_bytes:
            k -= 1
        i = max(k, i + 1)
    return chunks
